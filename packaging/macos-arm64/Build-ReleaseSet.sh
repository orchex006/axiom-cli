#!/bin/sh
# Build-ReleaseSet.sh - assemble a macOS axiom-cli release set (x64 or arm64).
#
# Owner: axiom-cli. Task J-008 owns the arm64 leg; the macOS x64 delivery is
# task J-005. Both consume THIS recipe: it is one script parameterised by
# --arch, and every artifact it writes records its own architecture, so an
# arm64 release set and an x64 release set cannot silently claim each other.
#
# Honest state on a non-macOS host: this script refuses with exit 4 (not-ready)
# and prints a NOT_RUN record. It never cross-compiles a macOS artifact from a
# foreign host, because such an artifact would not be evidence for a macOS
# target. macOS artifacts are therefore NOT BUILT for this card; the target
# stays certified:false with empty evidence.
#
# Usage on a real macOS host (the distribution entrypoint is `axiom-cli`):
#
#     sh packaging/macos-arm64/Build-ReleaseSet.sh \
#         --arch arm64 --out-dir out/macos-arm64 --build --json
#
# Exit codes: 0 success, 2 validation, 3 not found, 4 not-ready, 9 incompatible.

set -u

AC_EXIT_SUCCESS=0
AC_EXIT_VALIDATION=2
AC_EXIT_NOT_FOUND=3
AC_EXIT_NOT_READY=4
AC_EXIT_INCOMPATIBLE=9

ac_usage() {
    cat <<'USAGE'
axiom-cli macOS release-set builder (shared recipe for x64 and arm64)

USAGE:
    sh Build-ReleaseSet.sh --arch arm64|x64 --out-dir DIR (--cli-binary FILE | --build) [OPTIONS]

OPTIONS:
    --arch ARCH            arm64 | x64 (required; recorded on every artifact)
    --out-dir DIR          directory the release set is assembled into (required)
    --cli-binary FILE      prebuilt macOS `axiom-cli` to distribute
    --build                run `cargo build --release --locked --target TRIPLE` first
    --release-version VER  release version (default: VERSION in the repository root)
    --service MODE         none | launchd-user   (default none; launchd is not built yet)
    --json                 emit exactly one JSON object on stdout
    --help                 show this help and exit 0

TRIPLES: arm64 -> aarch64-apple-darwin, x64 -> x86_64-apple-darwin.

This script runs only on Darwin. On any other host it prints a NOT_RUN record
and exits 4, so a macOS artifact is never fabricated off-platform.
USAGE
}

ac_json_string() {
    printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
}

AC_ARCH=""
AC_OUT_DIR=""
AC_CLI_BINARY=""
AC_BUILD=0
AC_RELEASE_VERSION=""
AC_SERVICE="none"
AC_JSON=0

ac_fail() {
    printf 'Build-ReleaseSet.sh: error: %s\n' "$2" >&2
    exit "$1"
}

ac_not_run() {
    # $1 = reason
    if [ "$AC_JSON" = "1" ]; then
        printf '{"platform":%s,"arch":%s,"outcome":"not_run","built":false,"exit_code":4,"reason":%s}\n' \
            "$(ac_json_string "${AC_PLATFORM:-macos-arm64}")" \
            "$(ac_json_string "${AC_ARCH:-unknown}")" \
            "$(ac_json_string "$1")"
    else
        printf 'axiom-cli macOS release set: NOT RUN (%s)\n' "$1" >&2
    fi
    exit "$AC_EXIT_NOT_READY"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --arch)             [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--arch requires a value"; AC_ARCH="$2"; shift 2 ;;
        --out-dir)          [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--out-dir requires a value"; AC_OUT_DIR="$2"; shift 2 ;;
        --cli-binary)       [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--cli-binary requires a value"; AC_CLI_BINARY="$2"; shift 2 ;;
        --release-version)  [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--release-version requires a value"; AC_RELEASE_VERSION="$2"; shift 2 ;;
        --service)          [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--service requires a value"; AC_SERVICE="$2"; shift 2 ;;
        --build)            AC_BUILD=1; shift ;;
        --json)             AC_JSON=1; shift ;;
        --help|-h)          ac_usage; exit "$AC_EXIT_SUCCESS" ;;
        *)                  ac_fail "$AC_EXIT_VALIDATION" "unknown option: $1" ;;
    esac
done

[ -n "$AC_ARCH" ] || ac_fail "$AC_EXIT_VALIDATION" "--arch is required (arm64 or x64)"
[ -n "$AC_OUT_DIR" ] || ac_fail "$AC_EXIT_VALIDATION" "--out-dir is required"

case "$AC_ARCH" in
    arm64) AC_PLATFORM="macos-arm64"; AC_TRIPLE="aarch64-apple-darwin"; AC_CPUTYPE="0c000001"; AC_MACHINE="arm64" ;;
    x64)   AC_PLATFORM="macos-x64";   AC_TRIPLE="x86_64-apple-darwin";  AC_CPUTYPE="07000001"; AC_MACHINE="x86_64" ;;
    *) ac_fail "$AC_EXIT_VALIDATION" "--arch must be arm64 or x64, not $AC_ARCH" ;;
esac
case "$AC_SERVICE" in
    none|launchd-user) ;;
    *) ac_fail "$AC_EXIT_VALIDATION" "--service must be none or launchd-user" ;;
esac
if [ "$AC_SERVICE" = "launchd-user" ]; then
    ac_fail "$AC_EXIT_NOT_READY" "the launchd user agent is not built yet; this card does not ship a macOS service"
fi

AC_HOST_OS="$(uname -s 2>/dev/null || printf unknown)"
if [ "$AC_HOST_OS" != "Darwin" ]; then
    ac_not_run "the build host is $AC_HOST_OS, not Darwin; a macOS artifact is never cross-built off-platform, so this target stays not_run and unverified"
fi

AC_SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
AC_REPO_ROOT="$(CDPATH= cd -- "$AC_SELF_DIR/../.." && pwd)"

if [ -z "$AC_RELEASE_VERSION" ] && [ -r "$AC_REPO_ROOT/VERSION" ]; then
    AC_RELEASE_VERSION="$(sed -n '1p' "$AC_REPO_ROOT/VERSION" | tr -d ' \t\r')"
fi
[ -n "$AC_RELEASE_VERSION" ] || ac_fail "$AC_EXIT_NOT_READY" "no --release-version and no readable VERSION file"

if [ "$AC_BUILD" = "1" ]; then
    command -v cargo >/dev/null 2>&1 || ac_fail "$AC_EXIT_NOT_READY" "--build was requested but cargo is not on PATH"
    ( cd "$AC_REPO_ROOT" && cargo build --release --locked --target "$AC_TRIPLE" ) \
        || ac_fail "$AC_EXIT_NOT_READY" "cargo build --release --locked --target $AC_TRIPLE failed"
    [ -n "$AC_CLI_BINARY" ] || AC_CLI_BINARY="$AC_REPO_ROOT/target/$AC_TRIPLE/release/axiom-cli"
fi

[ -n "$AC_CLI_BINARY" ] || ac_fail "$AC_EXIT_VALIDATION" "supply --cli-binary FILE or --build"
[ -f "$AC_CLI_BINARY" ] || ac_fail "$AC_EXIT_NOT_FOUND" "cli binary not found: $AC_CLI_BINARY"

for ac_tool in od tr sed cut shasum mkdir cp chmod wc; do
    command -v "$ac_tool" >/dev/null 2>&1 || ac_fail "$AC_EXIT_NOT_READY" "required tool '$ac_tool' is not available"
done

# Verify the artifact is a 64-bit little-endian Mach-O of the requested arch.
ac_magic="$(od -An -tx1 -N4 -- "$AC_CLI_BINARY" | tr -d ' \n')"
[ "$ac_magic" = "cffaedfe" ] || ac_fail "$AC_EXIT_INCOMPATIBLE" "cli binary is not a 64-bit little-endian Mach-O object (magic $ac_magic)"
ac_cputype="$(od -An -tx1 -j4 -N4 -- "$AC_CLI_BINARY" | tr -d ' \n')"
[ "$ac_cputype" = "$AC_CPUTYPE" ] || ac_fail "$AC_EXIT_INCOMPATIBLE" "cli binary cputype $ac_cputype does not match --arch $AC_ARCH"

mkdir -p -- "$AC_OUT_DIR" || ac_fail "$AC_EXIT_NOT_READY" "cannot create --out-dir: $AC_OUT_DIR"
AC_OUT_DIR="$(CDPATH= cd -- "$AC_OUT_DIR" && pwd)"
AC_ART_NAME="axiom-cli"
cp -- "$AC_CLI_BINARY" "$AC_OUT_DIR/$AC_ART_NAME" || ac_fail "$AC_EXIT_NOT_READY" "cannot copy the artifact into the release set"
chmod 0755 -- "$AC_OUT_DIR/$AC_ART_NAME" || ac_fail "$AC_EXIT_NOT_READY" "cannot mark the artifact executable"

AC_ART_SHA="$(shasum -a 256 -- "$AC_OUT_DIR/$AC_ART_NAME" | cut -d' ' -f1)"
AC_ART_SIZE="$(wc -c < "$AC_OUT_DIR/$AC_ART_NAME" | tr -d ' ')"

AC_RS_FILE="$AC_OUT_DIR/release-set.json"
{
    printf '{\n'
    printf '  "release_set_version": 1,\n'
    printf '  "release_version": "%s",\n' "$AC_RELEASE_VERSION"
    printf '  "platform": "%s",\n' "$AC_PLATFORM"
    printf '  "target_triple": "%s",\n' "$AC_TRIPLE"
    printf '  "libc": "libSystem",\n'
    printf '  "arch": "%s",\n' "$AC_MACHINE"
    printf '  "generated_by": "packaging/macos-arm64/Build-ReleaseSet.sh",\n'
    printf '  "carries_components": ["axiom-cli"],\n'
    printf '  "user_service": null,\n'
    printf '  "artifacts": [\n'
    printf '    {"name":"axiom-cli","component":"axiom-cli","version":"%s","arch":"%s","sha256":"%s","size_bytes":%s,"archive":"axiom-cli","kind":"executable"}\n' \
        "$AC_RELEASE_VERSION" "$AC_MACHINE" "$AC_ART_SHA" "$AC_ART_SIZE"
    printf '  ]\n'
    printf '}\n'
} > "$AC_RS_FILE" || ac_fail "$AC_EXIT_NOT_READY" "cannot write the release set manifest"

AC_RS_SHA="$(shasum -a 256 -- "$AC_RS_FILE" | cut -d' ' -f1)"

if [ "$AC_JSON" = "1" ]; then
    printf '{"release_set_path":%s,"release_set_sha256":%s,"release_version":%s,"platform":%s,"target_triple":%s,"arch":%s,"artifact_sha256":%s,"artifact_size_bytes":%s,"built":true}\n' \
        "$(ac_json_string "$AC_RS_FILE")" \
        "$(ac_json_string "$AC_RS_SHA")" \
        "$(ac_json_string "$AC_RELEASE_VERSION")" \
        "$(ac_json_string "$AC_PLATFORM")" \
        "$(ac_json_string "$AC_TRIPLE")" \
        "$(ac_json_string "$AC_MACHINE")" \
        "$(ac_json_string "$AC_ART_SHA")" \
        "$AC_ART_SIZE"
else
    printf 'release set: %s\n' "$AC_RS_FILE"
    printf 'release set sha256: %s\n' "$AC_RS_SHA"
    printf 'artifact: %s arch=%s sha256=%s size=%s\n' "$AC_ART_NAME" "$AC_MACHINE" "$AC_ART_SHA" "$AC_ART_SIZE"
fi
exit "$AC_EXIT_SUCCESS"
