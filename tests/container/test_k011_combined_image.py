#!/usr/bin/env python3
"""Exercise an unpublished, single-image K-011 Linux integration candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str, expected: int = 0) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != expected:
        raise AssertionError(f"exit {result.returncode}, expected {expected}: {result.stdout[-700:]} {result.stderr[-700:]}")
    return result.stdout.strip()


def container(image: str, home: Path | None, program: str, *args: str,
              mounts: tuple[str, ...] = (), expected: int = 0) -> str:
    return run(
        "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
        "--user", "10001:10001", "--env", "HOME=/home/axiom",
        *(("--mount", f"type=bind,src={home},dst=/home/axiom") if home else ()),
        *(item for mount in mounts for item in ("--mount", mount)),
        "--entrypoint", program, image, *args, expected=expected,
    )


def data(image: str, home: Path, program: str, *args: str,
         mounts: tuple[str, ...] = (), expected: int = 0) -> dict:
    return json.loads(container(image, home, program, *args, mounts=mounts, expected=expected))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--cli-revision", required=True)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--catalog-source", required=True, type=Path)
    args = parser.parse_args()
    image = json.loads(run("docker", "image", "inspect", args.image))[0]
    labels = image["Config"]["Labels"]
    assert image["Architecture"] == "amd64" and image["Config"]["User"] == "10001:10001"
    assert labels["io.orchex006.axiom.candidate"] == "true"
    assert labels["org.opencontainers.image.revision"] == args.cli_revision
    assert container(args.image, None, "/usr/bin/id", "-u") == "10001"
    assert container(args.image, None, "/opt/axiom/mcp-venv/bin/python", "-m", "pip", "check") == "No broken requirements found."
    release_hashes = {}
    for name in ("axiom", "axiom-graphd", "axiom_mcp-0.1.0-py3-none-any.whl", "channel.json", "skills/bundle.json", "release-info.json"):
        expected_hash = sha(args.release / name)
        actual_hash = container(args.image, None, "/usr/bin/sha256sum", f"/opt/axiom/release/{name}").split()[0]
        assert expected_hash == actual_hash, name
        release_hashes[name] = actual_hash

    with tempfile.TemporaryDirectory(prefix="axiom-k011-combined-", dir="/tmp") as dirname:
        home = Path(dirname)
        home.chmod(0o777)
        cli = "/opt/axiom/release/axiom-cli"
        release = "/opt/axiom/release"
        events = []
        plan = data(args.image, home, cli, "install", "--from", release, "--dry-run", "--json")
        assert plan["code"] == 0 and plan["details"]["target"] == "linux-x64"
        events.append({"step": "install_plan", "exit_code": 0})
        stale = data(args.image, home, cli, "install", "--from", release, "--apply", "--approve-digest", "0" * 64, "--json", expected=6)
        assert stale["details"]["reason_code"] == "approval_required"
        events.append({"step": "stale_approval_refused", "exit_code": 6})
        applied = data(args.image, home, cli, "install", "--from", release, "--apply", "--approve-digest", plan["details"]["plan_digest"], "--json")
        assert applied["details"]["engine_status"] == "installed"
        ecosystem = home / ".local/share/axiom/installs/ecosystem"
        installed = {row["component"]: row for row in json.loads((ecosystem / "current").read_text())["activated"]}
        assert set(installed) == {"axiom-graphd", "axiom-mcp"}
        installed_hashes = {}
        for name, row in installed.items():
            path = home / Path(row["destination"]).relative_to("/home/axiom")
            assert sha(path) == row["sha256"]
            installed_hashes[name] = row["sha256"]
        graphd = data(args.image, home, installed["axiom-graphd"]["destination"], "version", "--json")
        assert graphd["build_revision"] == "90c5865c8b3e3c09980b6f78bf5e359bd95a21c5"
        events.append({"step": "engine_install_and_installed_bytes", "exit_code": 0})

        # The baked venv supplies only dependencies. Install the engine-placed
        # wheel in a writable copy to prove its bytes serve the live query.
        venv = "/home/axiom/test-mcp-venv"
        container(args.image, home, "/bin/cp", "-a", "/opt/axiom/mcp-venv", venv)
        python = f"{venv}/bin/python"
        container(args.image, home, python, "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--no-deps", "--force-reinstall", installed["axiom-mcp"]["destination"])
        assert container(args.image, home, python, "-m", "pip", "check") == "No broken requirements found."
        fixture = Path(__file__).resolve().parents[1] / "macos/mcp_catalog_fixture.py"
        catalog = data(args.image, home, python, "/fixture.py", "--graphd", installed["axiom-graphd"]["destination"], "--source", "/source.cs", "--registry-platform", "linux", "--restart-check", mounts=(f"type=bind,src={fixture},dst=/fixture.py,readonly", f"type=bind,src={args.catalog_source.resolve()},dst=/source.cs,readonly"))
        assert catalog["ok"] and catalog["wheel_import_under_venv"]
        assert catalog["catalog_before"] != catalog["catalog_after"]
        assert catalog["nodes_after"] > 0 and catalog["restart_nodes"] > 0
        assert catalog["restart_catalog_generation_id"] != catalog["catalog_after"]
        events.append({"step": "installed_wheel_query_edit_restart", "exit_code": 0})

        note = home / "user-note.txt"
        note.write_text("preserve K011 user data\n")
        removal = data(args.image, home, cli, "uninstall", "--dry-run", "--json")
        removed = data(args.image, home, cli, "uninstall", "--apply", "--approve-digest", removal["details"]["plan_digest"], "--json")
        assert removed["code"] == 0 and not (ecosystem / "current").exists()
        assert note.read_text() == "preserve K011 user data\n"
        for row in installed.values():
            assert not (home / Path(row["destination"]).relative_to("/home/axiom")).exists()
        events.append({"step": "approved_uninstall_preserve_data", "exit_code": 0})
        print(json.dumps({"task": "K-011", "scope": "unpublished single-image Linux candidate", "certified": False, "published": False, "image_id": image["Id"], "image_size_bytes": image["Size"], "cli_revision": args.cli_revision, "runtime_user": image["Config"]["User"], "network": "none", "platform": "linux/amd64", "release_sha256": release_hashes, "installed_sha256": installed_hashes, "catalog_source_sha256": sha(args.catalog_source), "catalog": catalog, "install_plan_digest": plan["details"]["plan_digest"], "engine_plan_digest": applied["details"]["engine_plan_digest"], "uninstall_plan_digest": removal["details"]["plan_digest"], "user_data_sha256": sha(note), "events": events}, sort_keys=True))


if __name__ == "__main__":
    main()
