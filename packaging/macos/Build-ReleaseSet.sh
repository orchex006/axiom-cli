#!/bin/sh
# macOS x64 packaging entrypoint (J-005).
#
# The architecture-aware implementation is shared with the arm64 recipe.  This
# file deliberately supplies only the J-005 target identity; it does not fork
# artifact inspection, hashing, signing policy, or release-set generation.

set -eu

for argument in "$@"; do
    if [ "$argument" = "--arch" ]; then
        printf '%s\n' 'Build-ReleaseSet.sh: J-005 always packages macos-x64; --arch is not accepted here' >&2
        exit 2
    fi
done

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$SCRIPT_DIR/../macos-arm64/Build-ReleaseSet.sh" --arch x64 "$@"
