#!/bin/sh
# Native macOS x64 wrapper and packager regression harness (J-005).
set -eu

case "$(uname -s):$(uname -m)" in Darwin:x86_64) ;; *) printf '%s\n' 'NOT_RUN: native macOS x64 host required' >&2; exit 4 ;; esac
CLI=""
while [ "$#" -gt 0 ]; do
    case "$1" in --cli-binary) [ "$#" -ge 2 ] || exit 2; CLI=$2; shift 2 ;; *) printf '%s\n' "unknown option: $1" >&2; exit 2 ;; esac
done
[ -x "$CLI" ] || { printf '%s\n' '--cli-binary must name an executable' >&2; exit 3; }
ROOT=$(mktemp -d /tmp/axiom-j005-test.XXXXXX)
trap 'rm -rf "$ROOT"' EXIT HUP INT TERM
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
expect() {
    expected=$1; shift
    set +e; "$@" >"$ROOT/stdout" 2>"$ROOT/stderr"; actual=$?; set -e
    [ "$actual" = "$expected" ] || { cat "$ROOT/stderr" >&2; fail "expected exit $expected, got $actual: $*"; }
}

# Positive: package a real native binary and verify its recorded digest and CPU type.
expect 0 sh "$REPO/packaging/macos/Build-ReleaseSet.sh" --out-dir "$ROOT/release" --cli-binary "$CLI" --json
test -x "$ROOT/release/axiom-cli" || fail 'packager did not preserve executable mode'
file "$ROOT/release/axiom-cli" | grep -q 'Mach-O 64-bit executable x86_64' || fail 'packager output is not x86_64 Mach-O'
PACKAGED_SHA=$(shasum -a 256 "$ROOT/release/axiom-cli" | awk '{print $1}')
grep -q "$PACKAGED_SHA" "$ROOT/stdout" || fail 'packager envelope omitted artifact digest'

# Negative: the x64 wrapper cannot be redirected to another architecture.
expect 2 sh "$REPO/packaging/macos/Build-ReleaseSet.sh" --arch arm64 --out-dir "$ROOT/wrong-arch" --cli-binary "$CLI"
test ! -e "$ROOT/wrong-arch/axiom-cli" || fail 'arch override wrote an artifact'
cp "$CLI" "$ROOT/arm-header"
printf '\014\000\000\001' | dd of="$ROOT/arm-header" bs=1 seek=4 conv=notrunc status=none
expect 9 sh "$REPO/packaging/macos/Build-ReleaseSet.sh" --out-dir "$ROOT/wrong-header" --cli-binary "$ROOT/arm-header"
test ! -e "$ROOT/wrong-header/axiom-cli" || fail 'wrong Mach-O header wrote an artifact'

# Negative: an unapproved mutation reaches no CLI transaction and preserves user data.
printf 'must-survive\n' > "$ROOT/user-data"
expect 2 env AXIOM_CLI_INSTALL_ROOT="$ROOT/install" sh "$REPO/installers/macos/Install-AxiomCli.sh" --cli "$CLI" --from "$ROOT/release" --apply
test "$(cat "$ROOT/user-data")" = 'must-survive' || fail 'missing approval changed user data'
test ! -e "$ROOT/install" || fail 'missing approval created install state'
expect 2 env AXIOM_CLI_INSTALL_ROOT="$ROOT/install" sh "$REPO/installers/macos/Uninstall-AxiomCli.sh" --cli "$CLI" --apply
test "$(cat "$ROOT/user-data")" = 'must-survive' || fail 'uninstall without approval changed user data'

# A checked relative basename is made absolute before exec, so PATH cannot
# substitute a different entrypoint after validation.
mkdir "$ROOT/local" "$ROOT/hostile"
printf '%s\n' '#!/bin/sh' 'printf "%s\n" "$0" > "$MARKER"' > "$ROOT/local/axiom-cli"
printf '%s\n' '#!/bin/sh' 'exit 99' > "$ROOT/hostile/axiom-cli"
chmod 0755 "$ROOT/local/axiom-cli" "$ROOT/hostile/axiom-cli"
(cd "$ROOT/local" && MARKER="$ROOT/called" PATH="$ROOT/hostile:$PATH" sh "$REPO/installers/macos/Install-AxiomCli.sh" --cli axiom-cli --from "$ROOT/release" --dry-run)
test "$(cat "$ROOT/called")" = "$ROOT/local/axiom-cli" || fail 'relative checked CLI was replaced through PATH'

# A PATH-local uname shim changes only this child process and cannot change host state.
mkdir "$ROOT/bin"
printf '%s\n' '#!/bin/sh' 'case "$1" in -s) echo Linux;; -m) echo x86_64;; esac' > "$ROOT/bin/uname"
chmod 0755 "$ROOT/bin/uname"
expect 9 env PATH="$ROOT/bin:$PATH" sh "$REPO/installers/macos/Uninstall-AxiomCli.sh" --cli "$CLI" --dry-run
printf 'PASS: native macOS x64 packaging and wrapper boundaries\n'
