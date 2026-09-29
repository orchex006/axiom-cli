#!/usr/bin/env python3
"""Exercise an installed Linux graphd generation on a real C# source file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active_daemon(root: Path) -> Path:
    pointer = json.loads((root / "installs/ecosystem/current").read_text())
    rows = [row for row in pointer["activated"] if row["component"] == "axiom-graphd"]
    if len(rows) != 1:
        raise ValueError("no unique installed daemon")
    path = Path(rows[0]["destination"])
    if not path.is_relative_to(root) or sha(path) != rows[0]["sha256"]:
        raise ValueError("installed daemon differs from its engine pointer")
    return path


def generation(work: Path, previous: str | None = None) -> str:
    pointer = work / ".axiom/graph/demo-solution/_catalog/live/current.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if pointer.is_file():
            value = json.loads(pointer.read_text())["generation_id"]
            if value != previous:
                return value
        time.sleep(0.2)
    raise ValueError("persistent watcher did not publish a new catalog")


def run(args: argparse.Namespace) -> dict:
    home = args.home
    root = home / ".local/share/axiom"
    work = home / "demo-repo"
    source = work / "src/TokenSource.cs"
    binding = root / "config/bindings.json"
    data = home / "user-data.txt"
    daemon = active_daemon(root)
    env = dict(os.environ, HOME=str(home), AXIOM_HOME=str(root), PATH="/usr/bin:/bin")
    if args.setup:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            'namespace Demo;\npublic class TokenSource { public string Issue() => "ok"; }\n'
        )
        (work / "Demo.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>\n'
        )
        data.write_text("preserve user data\n")
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text(json.dumps({"bindings": {"demo-repo": str(work)}}) + "\n")
        config = home / "solution.json"
        config.write_text(
            json.dumps(
                {
                    "id": "demo-solution",
                    "profile": "default",
                    "catalog_host_repo": "demo-repo",
                    "projects": [
                        {"id": "demo-project", "repo_id": "demo-repo", "path": "src"}
                    ],
                }
            )
            + "\n"
        )
        result = subprocess.run(
            [
                str(daemon),
                "solution",
                "register",
                "--config",
                str(config),
                "--apply",
                "--json",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise ValueError("solution register failed: " + result.stderr[-500:])
    before_hashes = {
        name: sha(path)
        for name, path in (
            ("source", source),
            ("bindings", binding),
            ("user_data", data),
        )
    }
    process = subprocess.Popen(
        [str(daemon), "serve", "--json"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # A retained catalog pointer can predate this daemon instance. Give the
        # startup inventory time to attach its watcher before editing source.
        time.sleep(2)
        if process.poll() is not None:
            raise ValueError("installed foreground daemon exited during startup")
        first = generation(work)
        query = subprocess.run(
            [
                str(daemon),
                "query",
                "context",
                "--solution",
                "demo-solution",
                "--symbol",
                "Demo.TokenSource",
                "--json",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if query.returncode or "TokenSource" not in query.stdout:
            raise ValueError("installed query did not return the source symbol")
        with source.open("a") as stream:
            stream.write(f"public sealed class {args.symbol} {{ }}\n")
        second = generation(work, first)
        changed = subprocess.run(
            [
                str(daemon),
                "query",
                "context",
                "--solution",
                "demo-solution",
                "--symbol",
                f"Demo.{args.symbol}",
                "--json",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if changed.returncode or args.symbol not in changed.stdout:
            raise ValueError("installed query did not return the watcher edit")
    finally:
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=30)
    if process.returncode != 0 or "Drained" not in stdout:
        raise ValueError("installed foreground daemon did not drain")
    after_hashes = {
        name: sha(path)
        for name, path in (
            ("source", source),
            ("bindings", binding),
            ("user_data", data),
        )
    }
    if (
        before_hashes["bindings"] != after_hashes["bindings"]
        or before_hashes["user_data"] != after_hashes["user_data"]
    ):
        raise ValueError("query/watcher changed human bindings or user data")
    return {
        "status": "passed",
        "daemon": str(daemon),
        "daemon_sha256": sha(daemon),
        "catalog_before": first,
        "catalog_after": second,
        "symbol": args.symbol,
        "source_sha256_before": before_hashes["source"],
        "source_sha256_after": after_hashes["source"],
        "bindings_sha256": after_hashes["bindings"],
        "user_data_sha256": after_hashes["user_data"],
        "daemon_exit_code": process.returncode,
        "stdout_tail": stdout[-1000:],
        "stderr_tail": stderr[-500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--setup", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
