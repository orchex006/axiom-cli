#!/bin/sh
# macOS x64 distribution removal wrapper (J-005). Engine-owned removal is not
# currently composed by axiom-graphd; this adapter faithfully returns that
# result and never deletes user data itself.

set -eu

[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "x86_64" ] || {
    printf '%s\n' 'Uninstall-AxiomCli.sh supports native macOS x64 only' >&2
    exit 9
}

CLI=""
MODE=""
APPROVAL=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --cli|--approve-digest)
            [ "$#" -ge 2 ] || { printf '%s\n' "missing value for $1" >&2; exit 2; }
            [ "$1" = --cli ] && CLI=$2 || APPROVAL=$2
            shift 2 ;;
        --dry-run|--apply)
            [ -z "$MODE" ] || { printf '%s\n' 'choose exactly one mode' >&2; exit 2; }
            MODE=$1; shift ;;
        --help|-h) printf '%s\n' 'Usage: Uninstall-AxiomCli.sh --cli FILE (--dry-run|--apply) [--approve-digest SHA256]'; exit 0 ;;
        *) printf '%s\n' "unknown option: $1" >&2; exit 2 ;;
    esac
done
[ -n "$CLI" ] && [ -x "$CLI" ] || { printf '%s\n' '--cli must name an executable axiom-cli' >&2; exit 3; }
case "$CLI" in
    /*) ;;
    */*) CLI="$(CDPATH= cd -- "$(dirname -- "$CLI")" && pwd)/$(basename -- "$CLI")" ;;
    *) CLI="$(pwd)/$CLI" ;;
esac
[ -n "$MODE" ] || { printf '%s\n' 'choose --dry-run or --apply' >&2; exit 2; }
if [ "$MODE" = '--apply' ]; then
    [ -n "$APPROVAL" ] || { printf '%s\n' '--apply requires --approve-digest' >&2; exit 2; }
    exec "$CLI" uninstall --apply --approve-digest "$APPROVAL" --json
fi
exec "$CLI" uninstall --dry-run --json
