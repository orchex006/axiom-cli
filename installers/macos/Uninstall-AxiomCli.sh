#!/bin/sh
# macOS x64 distribution removal wrapper. Ecosystem removal stays engine-owned;
# --entrypoints removes only recorded per-user executable and PATH bytes.

set -eu

[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "x86_64" ] || {
    printf '%s\n' 'Uninstall-AxiomCli.sh supports native macOS x64 only' >&2
    exit 9
}

CLI=""
MODE=""
APPROVAL=""
ENTRYPOINTS=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --cli|--approve-digest)
            [ "$#" -ge 2 ] || { printf '%s\n' "missing value for $1" >&2; exit 2; }
            [ "$1" = --cli ] && CLI=$2 || APPROVAL=$2
            shift 2 ;;
        --dry-run|--apply)
            [ -z "$MODE" ] || { printf '%s\n' 'choose exactly one mode' >&2; exit 2; }
            MODE=$1; shift ;;
        --entrypoints) ENTRYPOINTS=1; shift ;;
        --help|-h)
            printf '%s\n' 'Usage: Uninstall-AxiomCli.sh --cli FILE (--dry-run|--apply) [--approve-digest SHA256]'
            printf '%s\n' '       Uninstall-AxiomCli.sh --entrypoints (--dry-run|--apply) [--approve-digest SHA256]'
            exit 0 ;;
        *) printf '%s\n' "unknown option: $1" >&2; exit 2 ;;
    esac
done
[ -n "$MODE" ] || { printf '%s\n' 'choose --dry-run or --apply' >&2; exit 2; }
if [ "$ENTRYPOINTS" -eq 1 ]; then
    [ -z "$CLI" ] || { printf '%s\n' '--entrypoints cannot be combined with --cli' >&2; exit 2; }
    SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    set -- uninstall "$MODE"
    if [ -n "$APPROVAL" ]; then set -- "$@" --approve-digest "$APPROVAL"; fi
    exec sh "$SCRIPT_DIR/Manage-Entrypoints.sh" "$@"
fi
[ -n "$CLI" ] && [ -x "$CLI" ] || { printf '%s\n' '--cli must name an executable axiom-cli' >&2; exit 3; }
case "$CLI" in
    /*) ;;
    */*) CLI="$(CDPATH= cd -- "$(dirname -- "$CLI")" && pwd)/$(basename -- "$CLI")" ;;
    *) CLI="$(pwd)/$CLI" ;;
esac
if [ "$MODE" = '--apply' ]; then
    [ -n "$APPROVAL" ] || { printf '%s\n' '--apply requires --approve-digest' >&2; exit 2; }
    exec "$CLI" uninstall --apply --approve-digest "$APPROVAL" --json
fi
exec "$CLI" uninstall --dry-run --json
