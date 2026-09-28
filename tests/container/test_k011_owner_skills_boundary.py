#!/usr/bin/env python3
"""Show why the pinned axiom-skills owner manifest cannot close K-011 yet."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*argv: str, expected: int = 0) -> str:
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode != expected:
        raise AssertionError(f"exit {result.returncode}, expected {expected}: {result.stdout[-500:]} {result.stderr[-500:]}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--skills-owner", required=True, type=Path)
    parser.add_argument("--spec-revision", required=True)
    args = parser.parse_args()
    original = args.skills_owner / "release/skills-manifest.json"
    manifest = json.loads(original.read_text())
    assert manifest["component"] == "axiom-skills"
    assert manifest["component_version"] == "0.1.0"
    assert manifest["install_policy"]["requires_explicit_human_approval"] is True
    assert "spec_revision" not in manifest
    assert len(manifest["files"]) == 41
    for row in manifest["files"]:
        source = args.skills_owner / row["path"]
        assert source.is_file() and not source.is_symlink()
        assert sha(source) == row["sha256"] and source.stat().st_size == row["bytes"]
    assert len(args.spec_revision) == 40 and all(c in "0123456789abcdef" for c in args.spec_revision)

    with tempfile.TemporaryDirectory(prefix="axiom-k011-owner-skills-", dir="/tmp") as dirname:
        root = Path(dirname)
        root.chmod(0o755)
        release = root / "release"
        shutil.copytree(args.release, release)
        shutil.rmtree(release / "skills")
        shutil.copy2(original, release / "skills-manifest.json")
        for row in manifest["files"]:
            target = release / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.skills_owner / row["path"], target)
        home = root / "home"
        home.mkdir(mode=0o777)
        home.chmod(0o777)
        base = (
            "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
            "--user", "10001:10001", "--env", "HOME=/home/axiom",
            "--mount", f"type=bind,src={home},dst=/home/axiom",
            "--mount", f"type=bind,src={release},dst=/release,readonly",
            "--entrypoint", "/opt/axiom/release/axiom-cli", args.image,
            "install", "--from", "/release",
        )

        def refusal(expected_reason: str) -> dict:
            plan = json.loads(run(*base, "--dry-run", "--json"))
            assert plan["code"] == 0
            answer = json.loads(run(*base, "--apply", "--approve-digest", plan["details"]["plan_digest"], "--json", expected=4))
            assert answer["details"]["reason_code"] == expected_reason
            assert not (home / ".local/share/axiom/installs/ecosystem/current").exists()
            return {"exit_code": 4, "reason_code": expected_reason, "engine_pointer_absent": True}

        missing_spec = refusal("skills_spec_revision_not_pinned")
        derived = dict(manifest)
        derived["spec_revision"] = args.spec_revision
        (release / "skills-manifest.json").write_text(json.dumps(derived, sort_keys=True, indent=2) + "\n")
        missing_review = refusal("skills_capability_review_required:adapters/codex/hooks/graph_stop.py")
        print(json.dumps({"task": "K-011", "scope": "owner skills candidate refusal", "certified": False, "published": False, "skills_revision": run("git", "-C", str(args.skills_owner), "rev-parse", "HEAD"), "original_manifest_sha256": sha(original), "owner_file_count": len(manifest["files"]), "spec_revision_used_only_in_derived_copy": args.spec_revision, "missing_spec_revision": missing_spec, "missing_executable_capability_review": missing_review}, sort_keys=True))


if __name__ == "__main__":
    main()
