#!/bin/sh
# Clean-user MCP bootstrap. Python is supplied by the hash-pinned bundle.
set -eu

refuse() {
    printf '{"status":"refused","reason":"%s"}\n' "$1"
    exit 9
}
sha() { shasum -a 256 "$1" | awk '{print $1}'; }
[ "$(uname -s):$(uname -m)" = Darwin:x86_64 ] || refuse unsupported_host
[ "$(id -u)" -ne 0 ] || refuse root_user_refused
[ -n "${HOME:-}" ] || refuse home_missing

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ACTION=${1:-}
case "$ACTION" in install|rollback|status|uninstall) shift ;; *) refuse action_invalid ;; esac
BUNDLE="" ROOT="$HOME/.local/share/axiom/mcp" TARGET="" MODE="" APPROVAL=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --bundle|--root|--to|--approve-digest)
            [ "$#" -ge 2 ] || refuse option_value_missing
            case "$1" in
                --bundle) BUNDLE=$2 ;;
                --root) ROOT=$2 ;;
                --to) TARGET=$2 ;;
                --approve-digest) APPROVAL=$2 ;;
            esac
            shift 2 ;;
        --dry-run|--apply)
            [ -z "$MODE" ] || refuse duplicate_mode
            MODE=$1; shift ;;
        *) refuse option_unknown ;;
    esac
done
case "$ROOT" in "$HOME"/*) ;; *) refuse root_outside_user_home ;; esac
case "$ROOT" in */../*|*/..|*/./*|*/.|*'//'*) refuse root_noncanonical ;; esac
[ -n "$BUNDLE" ] || refuse bundle_required
[ -f "$BUNDLE/mcp-bundle.json" ] && [ ! -L "$BUNDLE/mcp-bundle.json" ] || refuse bundle_manifest_missing
[ -f "$BUNDLE/cpython-3.13.15-macos-x64.tar.gz" ] && [ ! -L "$BUNDLE/cpython-3.13.15-macos-x64.tar.gz" ] || refuse runtime_missing
[ "$(sha "$BUNDLE/cpython-3.13.15-macos-x64.tar.gz")" = 327814efd865a0b6a99c149b12a261e9d0ad409183515c745d41bda2d07282e9 ] || refuse runtime_digest_mismatch
case "$ACTION" in
    install) [ -z "$TARGET" ] || refuse unexpected_target ;;
    rollback) [ "${#TARGET}" -eq 64 ] || refuse rollback_target_invalid ;;
    uninstall) [ -z "$TARGET" ] || refuse unexpected_target ;;
    status) [ -z "$MODE$APPROVAL$TARGET" ] || refuse unexpected_status_option ;;
esac
if [ "$ACTION" != status ]; then
    case "$MODE" in --dry-run|--apply) ;; *) refuse mode_required ;; esac
    PLAN=$(printf '%s\n' "$ACTION" "$(sha "$BUNDLE/mcp-bundle.json")" "$ROOT" "$TARGET" | shasum -a 256 | awk '{print $1}')
    if [ "$MODE" = --dry-run ]; then
        printf '{"status":"planned","action":"%s","plan_digest":"%s"}\n' "$ACTION" "$PLAN"
        exit 0
    fi
    [ "$APPROVAL" = "$PLAN" ] || refuse approval_stale
fi

STAGE=$(mktemp -d "${TMPDIR:-/tmp}/axiom-mcp-bootstrap.XXXXXX") || refuse stage_unavailable
cleanup() { rm -rf -- "$STAGE"; }
trap cleanup EXIT HUP INT TERM
tar -xzf "$BUNDLE/cpython-3.13.15-macos-x64.tar.gz" -C "$STAGE" || refuse runtime_extract_failed
PYTHON="$STAGE/python/bin/python3.13"
[ -x "$PYTHON" ] || refuse runtime_executable_missing
case "$ACTION" in
    install) "$PYTHON" "$SCRIPT_DIR/Manage-McpEnvironment.py" install --root "$ROOT" --bundle "$BUNDLE" ;;
    rollback) "$PYTHON" "$SCRIPT_DIR/Manage-McpEnvironment.py" rollback --root "$ROOT" --to "$TARGET" ;;
    uninstall) "$PYTHON" "$SCRIPT_DIR/Manage-McpEnvironment.py" uninstall --root "$ROOT" ;;
    status) "$PYTHON" "$SCRIPT_DIR/Manage-McpEnvironment.py" status --root "$ROOT" ;;
esac
