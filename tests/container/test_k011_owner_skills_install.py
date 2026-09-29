#!/usr/bin/env python3
"""Install the immutable owner skills bundle through the K-011 candidate CLI."""

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


def run(*argv: str) -> dict:
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode:
        raise AssertionError(f"exit {result.returncode}: {result.stdout[-800:]} {result.stderr[-800:]}")
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--skills-owner", required=True, type=Path)
    args = parser.parse_args()
    owner_revision = subprocess.check_output(
        ("git", "-C", str(args.skills_owner), "rev-parse", "HEAD"), text=True
    ).strip()
    manifest_path = args.skills_owner / "release/skills-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert len(manifest["files"]) == 41 and manifest["spec_revision"]
    with tempfile.TemporaryDirectory(prefix="axiom-k011-skills-install-") as dirname:
        root = Path(dirname)
        root.chmod(0o755)
        release = root / "release"
        shutil.copytree(args.release, release)
        shutil.rmtree(release / "skills")
        shutil.copy2(manifest_path, release / "skills-manifest.json")
        for row in manifest["files"]:
            source = args.skills_owner / row["path"]
            assert sha(source) == row["sha256"] and source.stat().st_size == row["bytes"]
            target = release / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        channel_path = release / "channel.json"
        channel = json.loads(channel_path.read_text())
        next(row for row in channel["components"] if row["component"] == "skills")["revision"] = owner_revision
        channel_path.write_text(json.dumps(channel, sort_keys=True, indent=2) + "\n")
        home = root / "home"
        home.mkdir(mode=0o777)
        home.chmod(0o777)
        base = (
            "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
            "--user", "10001:10001", "--env", "HOME=/home/axiom",
            "--mount", f"type=bind,src={home},dst=/home/axiom",
            "--mount", f"type=bind,src={release},dst=/release,readonly",
            "--entrypoint", "/opt/axiom/release/axiom-cli", args.image,
        )
        plan = run(*base, "install", "--from", "/release", "--dry-run", "--json")
        assert plan["code"] == 0
        applied = run(*base, "install", "--from", "/release", "--apply",
                      "--approve-digest", plan["details"]["plan_digest"], "--json")
        assert applied["code"] == 0, applied
        install_root = home / ".local/share/axiom/installs/ecosystem"
        skills_root = install_root / "skills/0.1.0"
        assert (install_root / "skills/current").exists(), [str(p.relative_to(home)) for p in home.rglob("current")]
        pointer = json.loads((install_root / "skills/current").read_text())
        assert pointer["revision"] == owner_revision
        assert pointer["manifest_sha256"] == applied["details"]["engine"]["skills"]["manifest_sha256"]
        for row in manifest["files"]:
            installed = skills_root / row["path"]
            assert installed.is_file() and sha(installed) == row["sha256"]
            assert installed.stat().st_size == row["bytes"]
        note = home / "user-note.txt"
        note.write_text("preserve owner skills candidate data\n")
        removal = run(*base, "uninstall", "--dry-run", "--json")
        removed = run(*base, "uninstall", "--apply", "--approve-digest",
                      removal["details"]["plan_digest"], "--json")
        assert removed["code"] == 0
        assert not (install_root / "skills/current").exists()
        assert (skills_root / "bundle.json").is_file()
        assert all(not (skills_root / row["path"]).exists() for row in manifest["files"])
        assert note.read_text() == "preserve owner skills candidate data\n"
        print(json.dumps({"task": "K-011", "scope": "owner skills candidate install",
                          "certified": False, "published": False,
                          "skills_owner_revision": owner_revision,
                          "skills_manifest_sha256": sha(manifest_path),
                          "skills_files": len(manifest["files"]),
                          "installed_files_hash_verified": len(manifest["files"]),
                          "uninstall_preserved_user_data": True,
                          "plan_digest": plan["details"]["plan_digest"],
                          "install_details": applied["details"]}, sort_keys=True))


if __name__ == "__main__":
    main()
