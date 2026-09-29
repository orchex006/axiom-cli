#!/usr/bin/env python3
"""Verify every byte of the K-405 local container candidate handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--runtime-input", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    expected = {row["path"]: row for row in manifest["files"]}
    if manifest["task_id"] != "K-405" or not manifest["candidate"] or not expected:
        raise ValueError("candidate manifest identity is invalid")
    observed: dict[str, bytes] = {}
    with tarfile.open(args.archive, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or member.name in observed
            ):
                raise ValueError("candidate archive has an unsafe member")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("candidate archive member is unreadable")
            observed[member.name] = stream.read()
    if set(observed) != set(expected):
        raise ValueError("candidate archive membership differs from manifest")
    for name, body in observed.items():
        row = expected[name]
        if sha(body) != row["sha256"] or len(body) != row["size_bytes"]:
            raise ValueError(f"candidate artifact digest or size changed: {name}")
    inputs = manifest["inputs"]
    if json.loads(observed["candidate-inputs.json"]) != inputs:
        raise ValueError("candidate input receipt changed")
    runtime_bytes = args.runtime_input.read_bytes()
    if sha(runtime_bytes) != inputs["runtime_input_sha256"]:
        raise ValueError("K-404 runtime input changed")
    runtime = json.loads(runtime_bytes)
    if (
        runtime["task_id"] != "K-404"
        or runtime["lane"] != inputs["lane"]
        or runtime["runtime"]["sha256"] != inputs["runtime_archive_sha256"]
        or runtime["wheelhouse"]["sha256"] != inputs["wheelhouse_archive_sha256"]
        or runtime["mcp"]["dependency_lock_sha256"]
        != inputs["dependency_lock_sha256"]
    ):
        raise ValueError("runtime input identity is incompatible")
    release_set = json.loads(observed["release-set.json"])
    channel = json.loads(observed["channel.json"])
    if (
        release_set["platform"] != "linux-x64"
        or release_set["arch"] != "x86_64"
        or release_set["signing"] != "unsigned"
        or channel["published"] is not False
    ):
        raise ValueError("candidate claims incompatible platform or authority")
    for row in release_set["artifacts"]:
        if sha(observed[row["name"]]) != row["sha256"]:
            raise ValueError("release-set artifact changed")
    if sha(observed["axiom-cli"]) != inputs["cli_binary_sha256"]:
        raise ValueError("CLI binary changed")
    if sha(observed["skills-manifest.json"]) != inputs["skills_manifest_sha256"]:
        raise ValueError("skills manifest changed")
    wheel_name = "axiom_mcp-0.1.0-py3-none-any.whl"
    if sha(observed[wheel_name]) != inputs["mcp_wheel_sha256"]:
        raise ValueError("MCP wheel changed")
    print(
        json.dumps(
            {
                "ok": True,
                "task_id": "K-405",
                "lane": inputs["lane"],
                "files_checked": len(observed),
                "archive_sha256": sha(args.archive.read_bytes()),
                "runtime_input_sha256": sha(runtime_bytes),
                "published": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
