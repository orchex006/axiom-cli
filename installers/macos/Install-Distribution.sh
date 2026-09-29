#!/bin/sh
# Bootstrap the pinned candidate interpreter without requiring a host Python.
set -eu

PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
[ "$(uname -s):$(uname -m)" = Darwin:x86_64 ] || { echo macos_x64_required >&2; exit 9; }
[ "$(id -u)" -ne 0 ] || { echo root_user_refused >&2; exit 5; }

SET="" VERB="" MODE="" APPROVAL=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        install|update|rollback|uninstall) [ -z "$VERB" ] || exit 2; VERB=$1; shift ;;
        --release-set|--approve-digest)
            [ "$#" -ge 2 ] || exit 2
            case "$1" in --release-set) SET=$2 ;; *) APPROVAL=$2 ;; esac
            shift 2 ;;
        --dry-run|--apply) [ -z "$MODE" ] || exit 2; MODE=$1; shift ;;
        --help|-h)
            echo 'Usage: Install-Distribution.sh install|update|rollback|uninstall --release-set DIR --dry-run|--apply [--approve-digest SHA256]'
            exit 0 ;;
        *) echo unknown_option >&2; exit 2 ;;
    esac
done
[ -n "$SET" ] && [ -n "$VERB" ] && [ -n "$MODE" ] || exit 2
[ "$MODE" != --apply ] || [ -n "$APPROVAL" ] || exit 2
SET=$(CDPATH= cd -- "$SET" && pwd)
MANIFEST="$SET/runtime/manifest.json"
ARCHIVE="$SET/runtime/python.tar.gz"
INSTALLER="$SET/runtime/install.py"
[ -f "$MANIFEST" ] && [ ! -L "$MANIFEST" ] || exit 3
[ -f "$ARCHIVE" ] && [ ! -L "$ARCHIVE" ] || exit 3
[ -f "$INSTALLER" ] && [ ! -L "$INSTALLER" ] || exit 3
expected=$(plutil -extract python_sha256 raw -o - "$MANIFEST")
installer_expected=$(plutil -extract installer_sha256 raw -o - "$MANIFEST")
[ "$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')" = "$expected" ] || { echo runtime_digest_mismatch >&2; exit 9; }
[ "$(shasum -a 256 "$INSTALLER" | awk '{print $1}')" = "$installer_expected" ] || { echo installer_digest_mismatch >&2; exit 9; }
bootstrap=$(mktemp -d "${TMPDIR:-/tmp}/axiom-runtime-bootstrap.XXXXXX")
trap 'rm -rf -- "$bootstrap"' EXIT HUP INT TERM
tar -xzf "$ARCHIVE" -C "$bootstrap"
PYTHON="$bootstrap/cpython-3.13.15-macos-x86_64-none/bin/python3.13"
[ -x "$PYTHON" ] && [ ! -L "$PYTHON" ] || { echo runtime_python_missing >&2; exit 9; }
if [ -n "$APPROVAL" ]; then
    "$PYTHON" "$INSTALLER" "$VERB" --release-set "$SET" "$MODE" --approve-digest "$APPROVAL"
    exit $?
fi
"$PYTHON" "$INSTALLER" "$VERB" --release-set "$SET" "$MODE"
