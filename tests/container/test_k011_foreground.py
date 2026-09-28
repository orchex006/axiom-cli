#!/usr/bin/env python3
"""Check Docker-supervised graphd foreground stop and restart in a K-011 image."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid


def call(*argv: str, expected: int = 0) -> str:
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode != expected:
        raise AssertionError(f"exit {result.returncode}, expected {expected}: {result.stdout[-500:]} {result.stderr[-500:]}")
    return result.stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_catalog(pointer: Path, previous: str | None, name: str) -> str:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if pointer.is_file():
            generation = json.loads(pointer.read_text())["generation_id"]
            if generation != previous:
                return generation
        state = json.loads(call("docker", "inspect", name))[0]["State"]
        if not state["Running"]:
            raise AssertionError(f"graphd exited early: {state['ExitCode']}")
        time.sleep(0.2)
    raise AssertionError("graphd did not publish a catalog within 25 seconds")


def wait_restart_ready(name: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        logs = subprocess.run(["docker", "logs", name], text=True, capture_output=True, check=True)
        if logs.stderr.count("instance lock acquired") >= 2:
            # Allow the startup pass to establish its watcher baseline.
            time.sleep(1)
            return
        time.sleep(0.2)
    raise AssertionError("graphd did not restart within 10 seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    image = json.loads(call("docker", "image", "inspect", args.image))[0]
    assert image["Architecture"] == "amd64"
    assert image["Config"]["User"] == "10001:10001"
    assert image["Config"]["Labels"]["io.orchex006.axiom.candidate"] == "true"
    name = f"axiom-k011-foreground-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="axiom-k011-foreground-", dir="/tmp") as dirname:
        root = Path(dirname)
        root.chmod(0o777)
        repo = root / "repo"
        home = root / "graph-home"
        (repo / "src").mkdir(parents=True)
        (home / "config").mkdir(parents=True)
        source = repo / "src/Demo.cs"
        shutil.copyfile(args.source, source)
        (home / "config/bindings.json").write_text(json.dumps({"bindings": {"demo-repo": "/home/axiom/repo"}}))
        (root / "solution.json").write_text(json.dumps({"id": "demo-solution", "profile": "default", "catalog_host_repo": "demo-repo", "projects": [{"id": "demo-project", "repo_id": "demo-repo", "path": "src"}]}))
        for path in root.rglob("*"):
            path.chmod(0o777 if path.is_dir() else 0o666)
        base = (
            "--platform", "linux/amd64", "--network", "none", "--user", "10001:10001",
            "--env", "HOME=/home/axiom", "--env", "AXIOM_HOME=/home/axiom/graph-home",
            "--mount", f"type=bind,src={root},dst=/home/axiom",
            "--entrypoint", "/opt/axiom/release/axiom-graphd", args.image,
        )
        register = json.loads(call("docker", "run", "--rm", *base, "solution", "register", "--config", "/home/axiom/solution.json", "--apply", "--json"))
        assert register["id"] == "demo-solution"
        pointer = repo / ".axiom/graph/demo-solution/_catalog/live/current.json"
        try:
            call("docker", "run", "-d", "--name", name, *base, "serve", "--json")
            first = wait_catalog(pointer, None, name)
            call("docker", "stop", "--timeout", "10", name)
            first_state = json.loads(call("docker", "inspect", name))[0]["State"]
            assert first_state["ExitCode"] == 0
            first_logs = call("docker", "logs", name)
            assert any(json.loads(line).get("shutdown") == "Drained" for line in first_logs.splitlines())
            call("docker", "start", name)
            wait_restart_ready(name)
            restart_baseline = json.loads(pointer.read_text())["generation_id"]
            source.write_text(source.read_text() + "\npublic sealed class K011ForegroundRestartEdit { }\n")
            after = wait_catalog(pointer, restart_baseline, name)
            call("docker", "stop", "--timeout", "10", name)
            second_state = json.loads(call("docker", "inspect", name))[0]["State"]
            assert second_state["ExitCode"] == 0
            logs = call("docker", "logs", name)
            reports = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
            assert sum(row.get("shutdown") == "Drained" for row in reports) == 2
            print(json.dumps({"task": "K-011", "scope": "unpublished candidate foreground/supervisor check", "certified": False, "image_id": image["Id"], "network": "none", "runtime_user": image["Config"]["User"], "source_sha256": digest(args.source), "first_catalog": first, "restart_catalog": restart_baseline, "edited_catalog": after, "stop_exit_codes": [first_state["ExitCode"], second_state["ExitCode"]], "shutdown_reports": [row["shutdown"] for row in reports if "shutdown" in row]}, sort_keys=True))
        finally:
            subprocess.run(["docker", "rm", "-f", name], text=True, capture_output=True, check=False)


if __name__ == "__main__":
    main()
