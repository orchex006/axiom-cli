#!/usr/bin/env python3
"""Build the unpublished K-011 single-image candidate from explicit inputs."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[2]
LOCK_SHA256 = "5cf467f4d856044458d29124fa866632fdf64f398dd3fd227f6b6d3501ed99c9"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_regular(source: Path, target: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise ValueError(f"expected regular file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--linux-wheelhouse", required=True, type=Path)
    parser.add_argument("--dependency-lock", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--created", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ValueError("revision must be a full Git commit ID")
    if sha(args.dependency_lock) != LOCK_SHA256:
        raise ValueError("unexpected MCP dependency lock")
    wheels = sorted(args.linux_wheelhouse.glob("*.whl"))
    if len(wheels) != 31:
        raise ValueError("expected exactly 31 Linux dependency wheels")
    with tempfile.TemporaryDirectory(prefix="axiom-k011-image-context-") as dirname:
        context = Path(dirname)
        for name in ("Cargo.toml", "Cargo.lock"):
            copy_regular(REPO / name, context / name)
        shutil.copytree(REPO / "src", context / "src", symlinks=False)
        release = context / "candidate/release"
        release.mkdir(parents=True)
        for name in ("axiom", "axiom-graphd", "axiom_mcp-0.1.0-py3-none-any.whl", "channel.json", "release-info.json"):
            copy_regular(args.release / name, release / name)
        for name in ("axiom", "axiom-graphd"):
            if not os.access(release / name, os.X_OK):
                raise ValueError(f"core candidate must be executable: {name}")
        shutil.copytree(args.release / "skills", release / "skills", symlinks=False)
        for wheel in wheels:
            copy_regular(wheel, context / "candidate/wheels" / wheel.name)
        copy_regular(args.dependency_lock, context / "candidate/mcp-requirements.lock")
        subprocess.run([
            "docker", "build", "--platform", "linux/amd64", "--network", "none",
            "-f", str(REPO / "containers/K011-Candidate.Dockerfile"),
            "--build-arg", f"AXIOM_REVISION={args.revision}",
            "--build-arg", f"AXIOM_CREATED={args.created}",
            "-t", args.tag, str(context),
        ], check=True)


if __name__ == "__main__":
    main()
