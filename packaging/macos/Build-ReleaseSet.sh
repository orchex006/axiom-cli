#!/bin/sh
# Build the Intel Mac distribution entrypoint set. The shared recipe validates
# axiom-cli; optional core inputs are checked here before they join its manifest.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT=""
CLI=""
ENGINE=""
DAEMON=""
VERSION=""
CORE_VERSION=""
CORE_REVISION=""
SERVICE=""
BUILD=0
JSON=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --out-dir|--cli-binary|--engine-cli|--engine-daemon|--release-version|--core-version|--core-revision|--service)
            [ "$#" -ge 2 ] || { printf 'missing value for %s\n' "$1" >&2; exit 2; }
            case "$1" in
                --out-dir) OUT=$2 ;;
                --cli-binary) CLI=$2 ;;
                --engine-cli) ENGINE=$2 ;;
                --engine-daemon) DAEMON=$2 ;;
                --release-version) VERSION=$2 ;;
                --core-version) CORE_VERSION=$2 ;;
                --core-revision) CORE_REVISION=$2 ;;
                --service) SERVICE=$2 ;;
            esac
            shift 2 ;;
        --build) BUILD=1; shift ;;
        --json) JSON=1; shift ;;
        --arch) printf '%s\n' 'macos-x64 packager does not accept --arch' >&2; exit 2 ;;
        --help|-h)
            printf '%s\n' 'Usage: Build-ReleaseSet.sh --out-dir DIR (--cli-binary FILE | --build) [--engine-cli FILE --engine-daemon FILE --core-version VER --core-revision SHA] [--release-version VER] [--json]'
            exit 0 ;;
        *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done

# The two core executables share a release. A partial set cannot run the engine.
if [ -n "$ENGINE" ] && [ -z "$DAEMON" ] || [ -z "$ENGINE" ] && [ -n "$DAEMON" ]; then
    printf '%s\n' '--engine-cli and --engine-daemon must be supplied together' >&2
    exit 2
fi
if [ -n "$ENGINE" ]; then
    [ -n "$CORE_VERSION" ] && [ "${#CORE_REVISION}" -eq 40 ] || {
        printf '%s\n' 'core artifacts require a declared version and immutable 40-hex revision' >&2; exit 2;
    }
    case "$CORE_REVISION" in
        *[!0-9a-f]*) printf '%s\n' 'core revision must be lowercase hex' >&2; exit 2 ;;
    esac
elif [ -n "$CORE_VERSION" ] || [ -n "$CORE_REVISION" ]; then
    printf '%s\n' 'core identity requires both core artifacts' >&2; exit 2
fi

set -- --arch x64 --out-dir "$OUT"
if [ "$BUILD" -eq 1 ]; then set -- "$@" --build; fi
if [ -n "$CLI" ]; then set -- "$@" --cli-binary "$CLI"; fi
if [ -n "$VERSION" ]; then set -- "$@" --release-version "$VERSION"; fi
if [ -n "$SERVICE" ]; then set -- "$@" --service "$SERVICE"; fi
if [ -z "$ENGINE" ]; then
    if [ "$JSON" -eq 1 ]; then set -- "$@" --json; fi
    exec sh "$SCRIPT_DIR/../macos-arm64/Build-ReleaseSet.sh" "$@"
fi

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = x86_64 ] || {
    printf '%s\n' 'native macOS x64 host required for core packaging' >&2; exit 9;
}
command -v python3 >/dev/null 2>&1 || {
    printf '%s\n' 'python3 is required on the packaging host' >&2; exit 4;
}

# Validate both inputs before the shared recipe creates any release output.
for artifact in "$ENGINE" "$DAEMON"; do
    [ -f "$artifact" ] && [ -x "$artifact" ] || {
        printf 'core input must be an executable file: %s\n' "$artifact" >&2; exit 3;
    }
    magic=$(od -An -tx1 -N4 -- "$artifact" | tr -d ' \n')
    cpu=$(od -An -tx1 -j4 -N4 -- "$artifact" | tr -d ' \n')
    [ "$magic:$cpu" = 'cffaedfe:07000001' ] || {
        printf 'core input is not x86_64 Mach-O: %s\n' "$artifact" >&2; exit 9;
    }
done

sh "$SCRIPT_DIR/../macos-arm64/Build-ReleaseSet.sh" "$@" >/dev/null
python3 - "$OUT" "$ENGINE" "$DAEMON" "$JSON" "$CORE_VERSION" "$CORE_REVISION" <<'PY'
import hashlib, json, os, shutil, sys, tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
manifest_path = root / 'release-set.json'
manifest = json.loads(manifest_path.read_text())
manifest['signing'] = 'unsigned'
manifest['notarization'] = 'not_notarized'
version, revision = sys.argv[5:7]
for component, source in [('axiom', Path(sys.argv[2])), ('axiom-graphd', Path(sys.argv[3]))]:
    destination = root / component
    if destination.exists() and not destination.is_file():
        raise SystemExit(f'unowned packaging path blocks {destination}')
    fd, temporary = tempfile.mkstemp(prefix=f'.{component}.', dir=root)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    data = destination.read_bytes()
    manifest['artifacts'].append({
        'name': component, 'component': component, 'version': version,
        'revision': revision,
        'arch': 'x86_64', 'sha256': hashlib.sha256(data).hexdigest(),
        'size_bytes': len(data), 'archive': component, 'kind': 'executable',
    })
    manifest['carries_components'].append(component)
fd, temporary = tempfile.mkstemp(prefix='.release-set.', dir=root)
try:
    with os.fdopen(fd, 'w') as output:
        json.dump(manifest, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, manifest_path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
if sys.argv[4] == '1':
    print(json.dumps({
        'release_set_path': str(manifest_path),
        'release_set_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'release_version': manifest['release_version'], 'core_version': version,
        'core_revision': revision, 'platform': manifest['platform'],
        'target_triple': manifest['target_triple'], 'arch': 'x86_64',
        'artifact_sha256': manifest['artifacts'][0]['sha256'],
        'artifact_size_bytes': manifest['artifacts'][0]['size_bytes'],
        'artifacts': [{k: row[k] for k in ('name', 'sha256', 'size_bytes')} for row in manifest['artifacts']],
        'built': True,
    }, separators=(',', ':')))
else:
    print(f"release set: {manifest_path} sha256={hashlib.sha256(manifest_path.read_bytes()).hexdigest()}")
PY
