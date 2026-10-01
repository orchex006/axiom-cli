#!/usr/bin/env python3
"""Refuse corrupted and incompatible Windows kits through the public CLI verb."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path: Path, body: dict) -> None:
    path.write_bytes(
        (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


def run(kit: Path, root: Path, scratch: Path) -> tuple[int, dict]:
    runtime = json.loads((root / "mcp-runtime/current.json").read_text())
    scripts = root / "mcp-runtime/versions" / runtime["generation"] / "venv/Scripts"
    env = os.environ.copy()
    env.update(
        AXIOM_CLI_INSTALL_ROOT=str(root),
        AXIOM_CLI_COMPOSITE_KIT=str(kit),
        TEMP=str(scratch),
        TMP=str(scratch),
    )
    env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [str(kit / "release/axiom-cli.exe"), "update", "check", "--json"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    return result.returncode, json.loads(result.stdout or result.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--installed-root", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    args = parser.parse_args()
    scratch = args.scratch.resolve()
    root = args.installed_root.resolve()
    if not root.is_relative_to(scratch) or not args.kit.is_dir():
        raise ValueError("test inputs must be a named isolated install and kit")
    before = {
        name: sha(root / name)
        for name in (
            "cli/state.json",
            "bin/axiom-cli.exe",
            "installs/ecosystem/current",
            "mcp-runtime/current.json",
            "installs/ecosystem/skills/current",
            "user-data/sentinel.txt",
        )
    }
    temporary = Path(tempfile.mkdtemp(prefix="k306-negative-", dir=scratch)).resolve()
    if not temporary.is_relative_to(scratch):
        raise ValueError("temporary test directory escaped scratch root")
    cases = []
    try:
        for case in ("corrupt", "incompatible"):
            kit = temporary / case
            shutil.copytree(args.kit, kit)
            if case == "corrupt":
                path = kit / "release/axiom-graphd.exe"
                content = bytearray(path.read_bytes())
                content[-1] ^= 1
                path.write_bytes(content)
                expected = "candidate input changed"
            else:
                release_set = kit / "release/release-set.json"
                body = json.loads(release_set.read_text())
                body["release_version"] = "9.9.9"
                put(release_set, body)
                lock = kit / "release/candidate-lock.json"
                lock_body = json.loads(lock.read_text())
                lock_body["release_set_sha256"] = sha(release_set)
                put(lock, lock_body)
                files_path = kit / "candidate-files.json"
                files = json.loads(files_path.read_text())
                for row in files["files"]:
                    if row["path"] in ("release-set.json", "candidate-lock.json"):
                        path = kit / "release" / row["path"]
                        row.update(sha256=sha(path), size_bytes=path.stat().st_size)
                put(files_path, files)
                manifest = kit / "kit-manifest.json"
                kit_body = json.loads(manifest.read_text())
                kit_body["release_set_sha256"] = sha(release_set)
                kit_body["files"]["candidate-files.json"] = sha(files_path)
                put(manifest, kit_body)
                expected = "candidate platform, version or authority differs"
            code, answer = run(kit, root, scratch)
            if (
                code != 2
                or answer.get("status") != "refused"
                or expected not in answer.get("reason", "")
            ):
                raise AssertionError(
                    f"{case} was not refused at its intended boundary: {code} {answer}"
                )
            after = {name: sha(root / name) for name in before}
            if after != before:
                raise AssertionError(f"{case} mutated installed A or user data")
            cases.append({"id": case, "exit_code": code, "reason": answer["reason"]})
    finally:
        if not temporary.is_relative_to(scratch):
            raise ValueError("refusing to remove a directory outside scratch root")
        shutil.rmtree(temporary)
    print(json.dumps({"ok": True, "cases": cases, "a_unchanged": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
