#!/bin/sh
# Build-ReleaseSet.sh - assemble a linux-x64 axiom-cli release set.
#
# Owner: axiom-cli. Task J-008. POSIX shell only; the build recipe itself must
# not require Bash on the host that runs it.
#
# A release set is the unit the Linux installer consumes: a directory holding
# the distributed entrypoint `axiom-cli`, any component artifact this release
# actually carries, and `release-set.json` - a manifest that records the
# version, the byte length and the sha256 of every artifact, the honest state of
# the ecosystem components this release does not carry, and the optional
# systemd-user unit declaration.
#
# The manifest is the plan. Its own sha256 is the approval digest
# Install-AxiomCli.sh requires, so this script prints it:
#
#     set_dir=$(sh packaging/linux/Build-ReleaseSet.sh --out-dir _w10ev/rel \
#                  --cli-binary _w10ev/out/axiom-cli --json | ...)
#     sh installers/linux/Install-AxiomCli.sh --release-set "$set_dir/release-set.json" \
#         --apply --approve-digest "$digest"
#
# This script never invents a version it cannot read, never claims an artifact
# it cannot hash, and never writes outside --out-dir.
#
# The manifest shape is line-oriented on purpose: the installer reads it with
# sed, so no JSON parser is required on the target host. The exact shape is
# pinned by packaging/linux/release-set.schema.json.

set -u

AC_EXIT_SUCCESS=0
AC_EXIT_VALIDATION=2
AC_EXIT_NOT_FOUND=3
AC_EXIT_NOT_READY=4
AC_EXIT_INCOMPATIBLE=9

ac_usage() {
    cat <<'USAGE'
axiom-cli linux-x64 release-set builder

USAGE:
    sh Build-ReleaseSet.sh --out-dir DIR --cli-binary FILE [OPTIONS]

OPTIONS:
    --out-dir DIR          directory the release set is assembled into (required)
    --cli-binary FILE      built linux x86_64 `axiom-cli` ELF to distribute (required)
    --release-version VER  release version (default: VERSION in the repository root)
    --target-triple TRIPLE Rust target triple (default x86_64-unknown-linux-gnu)
    --libc FAMILY          C library family (default glibc)
    --service MODE         none | systemd-user   (default none)
    --unit-name NAME       systemd unit file name, e.g. axiom-graphd.service
    --unit-description TXT unit Description=
    --unit-exec-start CMD  unit ExecStart= (required with --service systemd-user)
    --unit-type TYPE       simple | exec | oneshot | notify | forking (default simple)
    --unit-owner NAME      component that owns the declared unit
    --json                 emit exactly one JSON object on stdout
    --help                 show this help and exit 0

EXIT CODES:
    0 success, 2 validation, 3 not found, 4 not-ready, 9 incompatible

The script refuses (exit 9) a --cli-binary that is not an ELF64 x86_64 object,
because assembling a release set around a foreign-architecture binary would
produce a manifest whose recorded `arch` contradicts the artifact.
USAGE
}

ac_json_string() {
    printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
}

AC_OUT_DIR=""
AC_CLI_BINARY=""
AC_RELEASE_VERSION=""
AC_TARGET_TRIPLE="x86_64-unknown-linux-gnu"
AC_LIBC="glibc"
AC_SERVICE="none"
AC_UNIT_NAME=""
AC_UNIT_DESCRIPTION=""
AC_UNIT_EXEC_START=""
AC_UNIT_TYPE="simple"
AC_UNIT_OWNER=""
AC_JSON=0

ac_fail() {
    # $1 = exit code, $2 = message
    printf 'Build-ReleaseSet.sh: error: %s\n' "$2" >&2
    exit "$1"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --out-dir)          [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--out-dir requires a value"; AC_OUT_DIR="$2"; shift 2 ;;
        --cli-binary)       [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--cli-binary requires a value"; AC_CLI_BINARY="$2"; shift 2 ;;
        --release-version)  [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--release-version requires a value"; AC_RELEASE_VERSION="$2"; shift 2 ;;
        --target-triple)    [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--target-triple requires a value"; AC_TARGET_TRIPLE="$2"; shift 2 ;;
        --libc)             [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--libc requires a value"; AC_LIBC="$2"; shift 2 ;;
        --service)          [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--service requires a value"; AC_SERVICE="$2"; shift 2 ;;
        --unit-name)        [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--unit-name requires a value"; AC_UNIT_NAME="$2"; shift 2 ;;
        --unit-description) [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--unit-description requires a value"; AC_UNIT_DESCRIPTION="$2"; shift 2 ;;
        --unit-exec-start)  [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--unit-exec-start requires a value"; AC_UNIT_EXEC_START="$2"; shift 2 ;;
        --unit-type)        [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--unit-type requires a value"; AC_UNIT_TYPE="$2"; shift 2 ;;
        --unit-owner)       [ $# -ge 2 ] || ac_fail "$AC_EXIT_VALIDATION" "--unit-owner requires a value"; AC_UNIT_OWNER="$2"; shift 2 ;;
        --json)             AC_JSON=1; shift ;;
        --help|-h)          ac_usage; exit "$AC_EXIT_SUCCESS" ;;
        *)                  ac_fail "$AC_EXIT_VALIDATION" "unknown option: $1" ;;
    esac
done

[ -n "$AC_OUT_DIR" ] || ac_fail "$AC_EXIT_VALIDATION" "--out-dir is required"
[ -n "$AC_CLI_BINARY" ] || ac_fail "$AC_EXIT_VALIDATION" "--cli-binary is required"

case "$AC_SERVICE" in
    none|systemd-user) ;;
    *) ac_fail "$AC_EXIT_VALIDATION" "--service must be none or systemd-user" ;;
esac
if [ "$AC_SERVICE" = "systemd-user" ]; then
    [ -n "$AC_UNIT_NAME" ] || ac_fail "$AC_EXIT_VALIDATION" "--unit-name is required with --service systemd-user"
    [ -n "$AC_UNIT_EXEC_START" ] || ac_fail "$AC_EXIT_VALIDATION" "--unit-exec-start is required with --service systemd-user"
fi
case "$AC_UNIT_TYPE" in
    simple|exec|oneshot|notify|forking) ;;
    *) ac_fail "$AC_EXIT_VALIDATION" "--unit-type must be simple, exec, oneshot, notify or forking" ;;
esac
case "$AC_TARGET_TRIPLE" in
    x86_64-unknown-linux-gnu) ;;
    *) ac_fail "$AC_EXIT_INCOMPATIBLE" "the linux-x64 tier only assembles x86_64-unknown-linux-gnu, not $AC_TARGET_TRIPLE" ;;
esac
case "$AC_LIBC" in
    glibc) ;;
    *) ac_fail "$AC_EXIT_INCOMPATIBLE" "the linux-x64 tier targets glibc, not $AC_LIBC" ;;
esac

AC_SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
AC_REPO_ROOT="$(CDPATH= cd -- "$AC_SELF_DIR/../.." && pwd)"

if [ ! -f "$AC_CLI_BINARY" ]; then
    ac_fail "$AC_EXIT_NOT_FOUND" "cli binary not found: $AC_CLI_BINARY"
fi
if [ ! -r "$AC_CLI_BINARY" ]; then
    ac_fail "$AC_EXIT_NOT_FOUND" "cli binary is not readable: $AC_CLI_BINARY"
fi

if [ -z "$AC_RELEASE_VERSION" ]; then
    if [ -r "$AC_REPO_ROOT/VERSION" ]; then
        AC_RELEASE_VERSION="$(sed -n '1p' "$AC_REPO_ROOT/VERSION" | tr -d ' \t\r')"
    fi
fi
[ -n "$AC_RELEASE_VERSION" ] || ac_fail "$AC_EXIT_NOT_READY" "no --release-version and no readable VERSION file; refusing to invent a version"

for ac_tool in od tr sed cut sha256sum mkdir cp chmod wc; do
    command -v "$ac_tool" >/dev/null 2>&1 || ac_fail "$AC_EXIT_NOT_READY" "required tool '$ac_tool' is not available"
done

# --- Verify the artifact really is an ELF64 x86_64 object -------------------
ac_magic="$(od -An -tx1 -N4 -- "$AC_CLI_BINARY" | tr -d ' \n')"
[ "$ac_magic" = "7f454c46" ] || ac_fail "$AC_EXIT_INCOMPATIBLE" "cli binary is not an ELF object (magic $ac_magic); the linux-x64 tier distributes an ELF64 x86_64 executable"
ac_class="$(od -An -tx1 -j4 -N1 -- "$AC_CLI_BINARY" | tr -d ' \n')"
[ "$ac_class" = "02" ] || ac_fail "$AC_EXIT_INCOMPATIBLE" "cli binary is not ELF64 (EI_CLASS=$ac_class)"
ac_machine="$(od -An -tx1 -j18 -N2 -- "$AC_CLI_BINARY" | tr -d ' \n')"
[ "$ac_machine" = "3e00" ] || ac_fail "$AC_EXIT_INCOMPATIBLE" "cli binary is not x86_64 (e_machine=$ac_machine); the linux-x64 tier distributes x86_64 only"

# --- Assemble ---------------------------------------------------------------
mkdir -p -- "$AC_OUT_DIR" || ac_fail "$AC_EXIT_NOT_READY" "cannot create --out-dir: $AC_OUT_DIR"
AC_OUT_DIR="$(CDPATH= cd -- "$AC_OUT_DIR" && pwd)"

AC_ART_NAME="axiom-cli"
cp -- "$AC_CLI_BINARY" "$AC_OUT_DIR/$AC_ART_NAME" || ac_fail "$AC_EXIT_NOT_READY" "cannot copy the artifact into the release set"
chmod 0755 -- "$AC_OUT_DIR/$AC_ART_NAME" || ac_fail "$AC_EXIT_NOT_READY" "cannot mark the artifact executable"

AC_ART_SHA="$(sha256sum -- "$AC_OUT_DIR/$AC_ART_NAME" | cut -d' ' -f1)"
AC_ART_SIZE="$(wc -c < "$AC_OUT_DIR/$AC_ART_NAME" | tr -d ' ')"
[ -n "$AC_ART_SHA" ] || ac_fail "$AC_EXIT_NOT_READY" "could not hash the artifact"

AC_RS_FILE="$AC_OUT_DIR/release-set.json"

# Scalars: exactly one `"key": "value"` per line. The installer greps these.
{
    printf '{\n'
    printf '  "release_set_version": 1,\n'
    printf '  "release_version": "%s",\n' "$AC_RELEASE_VERSION"
    printf '  "platform": "linux-x64",\n'
    printf '  "target_triple": "%s",\n' "$AC_TARGET_TRIPLE"
    printf '  "libc": "%s",\n' "$AC_LIBC"
    printf '  "arch": "x86_64",\n'
    printf '  "generated_by": "packaging/linux/Build-ReleaseSet.sh",\n'
    printf '  "carries_components": ["axiom-cli"],\n'
    if [ "$AC_SERVICE" = "systemd-user" ]; then
        printf '  "user_service": {"unit_name":%s,"description":%s,"exec_start":%s,"type":%s,"owner":%s},\n' \
            "$(ac_json_string "$AC_UNIT_NAME")" \
            "$(ac_json_string "${AC_UNIT_DESCRIPTION:-Axiom CLI component}")" \
            "$(ac_json_string "$AC_UNIT_EXEC_START")" \
            "$(ac_json_string "$AC_UNIT_TYPE")" \
            "$(ac_json_string "${AC_UNIT_OWNER:-axiom-cli}")"
    else
        printf '  "user_service": null,\n'
    fi
    printf '  "artifacts": [\n'
    printf '    {"name":"axiom-cli","component":"axiom-cli","version":"%s","arch":"x86_64","sha256":"%s","size_bytes":%s,"archive":"axiom-cli","kind":"executable"}\n' \
        "$AC_RELEASE_VERSION" "$AC_ART_SHA" "$AC_ART_SIZE"
    printf '  ]\n'
    printf '}\n'
} > "$AC_RS_FILE" || ac_fail "$AC_EXIT_NOT_READY" "cannot write the release set manifest"

AC_RS_SHA="$(sha256sum -- "$AC_RS_FILE" | cut -d' ' -f1)"

# The manifest sha256 is the approval digest the installer requires, and it is
# also what the envelope records as release_set.sha256.
if [ "$AC_JSON" = "1" ]; then
    printf '{"release_set_path":%s,"release_set_sha256":%s,"plan_digest":%s,"release_version":%s,"platform":"linux-x64","target_triple":%s,"libc":%s,"arch":"x86_64","artifact_name":"%s","artifact_sha256":%s,"artifact_size_bytes":%s,"service":%s}\n' \
        "$(ac_json_string "$AC_RS_FILE")" \
        "$(ac_json_string "$AC_RS_SHA")" \
        "$(ac_json_string "$AC_RS_SHA")" \
        "$(ac_json_string "$AC_RELEASE_VERSION")" \
        "$(ac_json_string "$AC_TARGET_TRIPLE")" \
        "$(ac_json_string "$AC_LIBC")" \
        "$AC_ART_NAME" \
        "$(ac_json_string "$AC_ART_SHA")" \
        "$AC_ART_SIZE" \
        "$(ac_json_string "$AC_SERVICE")"
else
    printf 'release set: %s\n' "$AC_RS_FILE"
    printf 'release set sha256 (approval digest): %s\n' "$AC_RS_SHA"
    printf 'artifact: %s sha256=%s size=%s\n' "$AC_ART_NAME" "$AC_ART_SHA" "$AC_ART_SIZE"
fi
exit "$AC_EXIT_SUCCESS"
