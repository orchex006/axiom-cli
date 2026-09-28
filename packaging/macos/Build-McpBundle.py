#!/usr/bin/env python3
"""Build and smoke-test the offline Intel Mac MCP runtime payload (K-002).

The packager is a build-host tool. The target host receives a checked standalone
CPython archive, the owner wheel, and a complete hashed wheelhouse; it need not
have Python, pip, uv, or a network connection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

RUNTIME_SHA256 = "327814efd865a0b6a99c149b12a261e9d0ad409183515c745d41bda2d07282e9"
RUNTIME_VERSION = "3.13.15"
MCP_REVISION = "b947b697ac931dead8e3983d4d72c1c998be7d33"
MCP_VERSION = "0.1.0"
MCP_SHA256 = "365d4d2baa3b155b1c2cb661fdfd8439db1f628ba9ea524e0b0ee49d14c22705"
RUNTIME_NAME = "cpython-3.13.15-macos-x64.tar.gz"
MCP_NAME = "axiom_mcp-0.1.0-py3-none-any.whl"
LOCK = Path(__file__).with_name("mcp-requirements.lock")
LOCK_SHA256 = "5cf467f4d856044458d29124fa866632fdf64f398dd3fd227f6b6d3501ed99c9"
INSTALLER = Path(__file__).resolve().parents[2] / "installers/macos"


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def run(*argv: str) -> None:
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(f"command failed ({result.returncode}): {Path(argv[0]).name}: {result.stderr[-500:]}")


def inspect_runtime(path: Path) -> None:
    if digest(path) != RUNTIME_SHA256:
        raise ValueError("standalone CPython digest mismatch")
    with tarfile.open(path, "r:gz") as archive:
        names = {item.name for item in archive.getmembers()}
        if "python/bin/python3.13" not in names:
            raise ValueError("standalone CPython executable missing")
        for item in archive.getmembers():
            parts = Path(item.name).parts
            if not parts or parts[0] != "python" or ".." in parts or Path(item.name).is_absolute():
                raise ValueError("runtime archive has an unsafe member")
            if item.issym() or item.islnk():
                target = Path(item.linkname)
                if target.is_absolute() or ".." in target.parts:
                    raise ValueError("runtime archive has an unsafe link")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--mcp-wheel", required=True, type=Path)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
        raise ValueError("native Intel macOS packaging host required")
    inspect_runtime(args.runtime)
    if digest(LOCK) != LOCK_SHA256:
        raise ValueError("pinned dependency lock digest mismatch")
    if args.mcp_wheel.name != MCP_NAME:
        raise ValueError("MCP wheel filename/version mismatch")
    if digest(args.mcp_wheel) != MCP_SHA256:
        raise ValueError("pinned MCP wheel digest mismatch")
    with zipfile.ZipFile(args.mcp_wheel) as wheel:
        metadata = wheel.read("axiom_mcp-0.1.0.dist-info/METADATA").decode()
    if "Name: axiom-mcp\n" not in metadata or f"Version: {MCP_VERSION}\n" not in metadata:
        raise ValueError("MCP wheel metadata mismatch")

    wheels = sorted(args.wheel_dir.glob("*.whl"))
    if len(wheels) != 32 or {path.name for path in wheels if path.name == MCP_NAME} != {MCP_NAME}:
        raise ValueError("expected exactly 31 dependency wheels and the MCP wheel")
    if any(path.is_symlink() or not path.is_file() for path in wheels):
        raise ValueError("wheelhouse contains a non-regular file")
    output = args.out_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.runtime, output / RUNTIME_NAME)
    shutil.copyfile(LOCK, output / LOCK.name)
    (output / "wheels").mkdir()
    for wheel in wheels:
        shutil.copyfile(wheel, output / "wheels" / wheel.name)
    for name in ("Manage-McpEnvironment.sh", "Manage-McpEnvironment.py"):
        shutil.copyfile(INSTALLER / name, output / name)
    (output / "Manage-McpEnvironment.sh").chmod(0o755)

    # Smoke-test the copied bytes through the very interpreter the recipient
    # will unpack, using no indexes or source builds.
    with tempfile.TemporaryDirectory(prefix="axiom-mcp-bundle-") as temporary:
        root = Path(temporary)
        with tarfile.open(output / RUNTIME_NAME, "r:gz") as archive:
            archive.extractall(root)  # Exact pinned digest and member paths checked above.
        python = root / "python/bin/python3.13"
        venv = root / "venv"
        run(str(python), "-m", "venv", str(venv))
        isolated = venv / "bin/python"
        run(str(isolated), "-m", "pip", "install", "--no-index", "--find-links", str(output / "wheels"), "--require-hashes", "-r", str(output / LOCK.name))
        run(str(isolated), "-m", "pip", "install", "--no-index", "--no-deps", str(output / "wheels" / MCP_NAME))
        run(str(isolated), "-m", "pip", "check")
        run(str(isolated), "-m", "axiom_mcp.cli", "version", "--json")

    artifacts = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            artifacts.append({"path": path.relative_to(output).as_posix(), "sha256": digest(path), "size_bytes": path.stat().st_size})
    manifest = {
        "schema_version": 1,
        "platform": "macos-x64",
        "python_version": RUNTIME_VERSION,
        "python_runtime_sha256": RUNTIME_SHA256,
        "mcp_version": MCP_VERSION,
        "mcp_revision": MCP_REVISION,
        "mcp_wheel_sha256": digest(output / "wheels" / MCP_NAME),
        "artifacts": artifacts,
    }
    manifest_path = output / "mcp-bundle.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"manifest_sha256": digest(manifest_path), "artifacts": len(artifacts), "mcp_wheel_sha256": manifest["mcp_wheel_sha256"]}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"MCP packaging refused: {error}", file=sys.stderr)
        sys.exit(9)
