#!/usr/bin/env python3
"""Exercise an unpublished Linux core candidate through the CLI in a container.

This is a K-011 dependency spike. It proves engine placement and refusal
boundaries, not MCP provisioning, a watcher or a released OCI lifecycle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


REPO = Path(__file__).resolve().parents[2]
PYTHON_IMAGE = (
    "python:3.13.15-slim-bookworm@"
    "sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26"
)
CORE_REVISION = "90c5865c8b3e3c09980b6f78bf5e359bd95a21c5"
MCP_REVISION = "b947b697ac931dead8e3983d4d72c1c998be7d33"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str, expected: int = 0) -> str:
    completed = subprocess.run(args, text=True, capture_output=True, check=False)
    if completed.returncode != expected:
        raise AssertionError(
            f"{args[0]} returned {completed.returncode}, expected {expected}: "
            f"{completed.stdout[-500:]} {completed.stderr[-500:]}"
        )
    return completed.stdout.strip()


def docker(release: Path, home: Path, program: str, *args: str,
           expected: int = 0) -> dict:
    stdout = run(
        "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
        "--user", "10001:10001", "--env", "HOME=/home/axiom",
        "--mount", f"type=bind,src={release},dst=/release,readonly",
        "--mount", f"type=bind,src={home},dst=/home/axiom",
        "--entrypoint", program, PYTHON_IMAGE, *args, expected=expected,
    )
    return json.loads(stdout)


def compose(release: Path, archive: Path, manifest: dict, wheel: Path,
            skills: Path, image: str) -> dict:
    archive_sha = manifest["archive"]["sha256"]
    if sha(archive) != archive_sha:
        raise ValueError("core archive differs from candidate manifest")
    records = {row["name"]: row for row in manifest["binaries"]}
    with tarfile.open(archive, "r:gz") as stream:
        for name in ("axiom", "axiom-graphd"):
            member = stream.getmember(name)
            if not member.isfile() or member.name != name:
                raise ValueError(f"unsafe core archive member: {name}")
            with stream.extractfile(member) as source:
                (release / name).write_bytes(source.read())
            (release / name).chmod(0o755)
            if sha(release / name) != records[name]["sha256"]:
                raise ValueError(f"core executable changed: {name}")
    if wheel.name != "axiom_mcp-0.1.0-py3-none-any.whl":
        raise ValueError("unexpected MCP wheel")
    shutil.copyfile(wheel, release / wheel.name)
    shutil.copytree(skills, release / "skills")
    skills_info = json.loads((release / "skills/bundle.json").read_text())

    container = run("docker", "create", image)
    try:
        run("docker", "cp", f"{container}:/usr/local/bin/axiom-cli", str(release / "axiom-cli"))
    finally:
        run("docker", "rm", container)
    (release / "axiom-cli").chmod(0o755)

    trust = json.loads((REPO / "channels/stable.json").read_text())["trust"]

    def component(name: str, version: str, revision: str,
                  filename: str | None, restart: bool) -> dict:
        path = release / filename if filename else None
        artifacts = [] if path is None else [{
            "platform": "linux-x64", "class": "per-user-installer",
            "url": f"https://candidate.invalid/{filename}", "sha256": sha(path),
            "size_bytes": path.stat().st_size,
        }]
        return {
            "component": name, "status": "declared", "version": version,
            "revision": revision, "declared_source": "unpublished K-011 local candidate",
            "needs_restart": restart, "artifacts": artifacts,
        }

    channel = {
        "manifest_version": 1, "channel": "stable",
        "updated_at": "2026-09-28T00:00:00Z", "published": False,
        "note": "Unsigned, unpublished Linux container dependency spike",
        "trust": trust,
        "components": [
            component("axiom-graphd", "0.1.0", CORE_REVISION, "axiom-graphd", True),
            component("axiom-mcp", "0.1.0", MCP_REVISION, wheel.name, True),
            component("axiom", "0.1.0", CORE_REVISION, "axiom", True),
            component("skills", skills_info["version"], skills_info["revision"], None, False),
        ],
    }
    (release / "channel.json").write_text(json.dumps(channel, indent=2, sort_keys=True) + "\n")
    return {
        "archive_sha256": archive_sha,
        "channel_sha256": sha(release / "channel.json"),
        "cli_sha256": sha(release / "axiom-cli"),
        "core_sha256": {name: sha(release / name) for name in records},
        "mcp_wheel_sha256": sha(release / wheel.name),
        "skills_manifest_sha256": sha(release / "skills/bundle.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-image", required=True)
    parser.add_argument("--cli-revision", required=True)
    parser.add_argument("--core-archive", required=True, type=Path)
    parser.add_argument("--core-manifest", required=True, type=Path)
    parser.add_argument("--mcp-wheel", required=True, type=Path)
    parser.add_argument("--skills-bundle", required=True, type=Path)
    args = parser.parse_args()
    if shutil.which("docker") is None:
        raise SystemExit("NOT_RUN: Docker unavailable")
    image = json.loads(run("docker", "image", "inspect", args.cli_image))[0]
    if image["Config"]["User"] != "10001:10001" or image["Architecture"] != "amd64":
        raise ValueError("CLI image is not Linux amd64/non-root")
    if image["Config"]["Labels"]["org.opencontainers.image.revision"] != args.cli_revision:
        raise ValueError("CLI image revision label differs from source revision")
    manifest = json.loads(args.core_manifest.read_text())
    if manifest["source_revision"] != CORE_REVISION:
        raise ValueError("core candidate revision mismatch")
    runtime_uid = run("docker", "run", "--rm", "--platform", "linux/amd64",
                      "--network", "none", "--user", "10001:10001",
                      "--entrypoint", "/usr/bin/id", PYTHON_IMAGE, "-u")
    runtime_version = run("docker", "run", "--rm", "--platform", "linux/amd64",
                          "--network", "none", "--user", "10001:10001",
                          "--entrypoint", "python", PYTHON_IMAGE, "--version")
    if runtime_uid != "10001" or runtime_version != "Python 3.13.15":
        raise ValueError("unexpected runtime user or Python version")

    with tempfile.TemporaryDirectory(prefix="axiom-k011-candidate-", dir="/tmp") as name:
        root = Path(name)
        root.chmod(0o755)
        release = root / "release"
        release.mkdir(mode=0o755)
        home = root / "home"
        home.mkdir(mode=0o777)
        home.chmod(0o777)
        inputs = compose(release, args.core_archive, manifest, args.mcp_wheel,
                         args.skills_bundle, args.cli_image)
        events = []

        plan = docker(release, home, "/release/axiom-cli", "install", "--from",
                      "/release", "--dry-run", "--json")
        assert plan["code"] == 0 and plan["details"]["target"] == "linux-x64"
        events.append({"step": "install_plan", "exit_code": 0})
        stale = docker(release, home, "/release/axiom-cli", "install", "--from",
                       "/release", "--apply", "--approve-digest", "0" * 64,
                       "--json", expected=6)
        assert stale["details"]["reason_code"] == "approval_required"
        events.append({"step": "stale_approval_refused", "exit_code": 6})

        corrupt = root / "corrupt"
        shutil.copytree(release, corrupt)
        wheel_bytes = bytearray((corrupt / args.mcp_wheel.name).read_bytes())
        wheel_bytes[-1] ^= 1  # Keep the declared length; exercise the digest check.
        (corrupt / args.mcp_wheel.name).write_bytes(wheel_bytes)
        refused = docker(corrupt, home, "/release/axiom-cli", "install", "--from",
                         "/release", "--dry-run", "--json", expected=2)
        assert refused["details"]["reason_code"] == "artifact_unverified:axiom-mcp"
        events.append({"step": "corrupt_wheel_refused", "exit_code": 2})

        applied = docker(release, home, "/release/axiom-cli", "install", "--from",
                         "/release", "--apply", "--approve-digest",
                         plan["details"]["plan_digest"], "--json")
        assert applied["details"]["engine_status"] == "installed"
        ecosystem = home / ".local/share/axiom/installs/ecosystem"
        pointer = json.loads((ecosystem / "current").read_text())
        installed = {row["component"]: row for row in pointer["activated"]}
        assert set(installed) == {"axiom-graphd", "axiom-mcp"}
        for row in installed.values():
            path = home / Path(row["destination"]).relative_to("/home/axiom")
            assert sha(path) == row["sha256"]
        daemon = docker(release, home, installed["axiom-graphd"]["destination"],
                        "version", "--json")
        assert daemon["build_revision"] == CORE_REVISION
        events.append({"step": "engine_install_and_installed_bytes", "exit_code": 0})

        note = home / "user-note.txt"
        note.write_text("preserve K011 user data\n")
        removal = docker(release, home, "/release/axiom-cli", "uninstall",
                         "--dry-run", "--json")
        removed = docker(release, home, "/release/axiom-cli", "uninstall",
                         "--apply", "--approve-digest",
                         removal["details"]["plan_digest"], "--json")
        assert removed["code"] == 0 and not (ecosystem / "current").exists()
        assert note.read_text() == "preserve K011 user data\n"
        for row in installed.values():
            assert not (home / Path(row["destination"]).relative_to("/home/axiom")).exists()
        events.append({"step": "approved_uninstall_preserve_data", "exit_code": 0})

        print(json.dumps({
            "task": "K-011", "scope": "Linux container dependency spike",
            "certified": False, "published": False,
            "cli_revision": args.cli_revision, "core_revision": CORE_REVISION,
            "mcp_revision": MCP_REVISION, "cli_image_id": image["Id"],
            "python_image": PYTHON_IMAGE, "runtime_user": "10001:10001",
            "network": "none", "platform": "linux/amd64",
            "python_version": runtime_version, "runtime_uid": runtime_uid,
            "input_sha256": inputs,
            "install_plan_digest": plan["details"]["plan_digest"],
            "engine_plan_digest": applied["details"]["engine_plan_digest"],
            "uninstall_plan_digest": removal["details"]["plan_digest"],
            "installed_sha256": {key: row["sha256"] for key, row in installed.items()},
            "user_data_sha256": sha(note), "events": events,
        }, sort_keys=True))


if __name__ == "__main__":
    main()
