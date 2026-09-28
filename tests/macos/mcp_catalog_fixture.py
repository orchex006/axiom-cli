#!/usr/bin/env python3
"""Query a real graphd catalog through the installed MCP wheel, with no source path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import axiom_mcp
from axiom_mcp.registry import load_registry
from axiom_mcp.tools.context import GuardedSnapshotSource, ToolContext, ToolPrincipal
from axiom_mcp.tools.query import graph_query


def run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, env=env, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(argv[0]).name} exited {result.returncode}: {result.stderr[-300:]}")
    return result


def query(home: Path, repo: Path, needle: str, platform: str) -> dict:
    registry_file = home.parent / "mcp-registry.json"
    registry_file.write_text(json.dumps({
        "schema_version": 1, "axiom_home": str(home),
        "instances": [{"instance_id": "local-instance"}],
        "solutions": [{"solution_id": "demo-solution", "instance_id": "local-instance", "catalog_host_repo": "demo-repo", "repositories": [{"repo_id": "demo-repo", "repo_root": str(repo), "projects": [{"project_id": "demo-project"}]}]}],
    }))
    registry = load_registry(registry_file, env={"AXIOM_HOME": str(home)}, platform=platform)
    context = ToolContext(
        registry=registry,
        principal=ToolPrincipal("installed-wheel-test", frozenset({"read"}), frozenset({"demo-solution"})),
        source=GuardedSnapshotSource(home / "instances/local-instance/solution.guard"),
    )
    return graph_query({"solution_id": "demo-solution", "operation": "search", "query": needle}, context)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphd", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--registry-platform", choices=("darwin", "linux"), default="darwin")
    parser.add_argument("--restart-check", action="store_true")
    args = parser.parse_args()
    prefix = Path(sys.prefix).resolve()
    origin = Path(axiom_mcp.__file__).resolve()
    if prefix not in origin.parents:
        raise RuntimeError("MCP import did not come from the installed venv")
    with tempfile.TemporaryDirectory(prefix="axiom-k002-catalog-") as name:
        root = Path(name)
        repo, home = root / "repo", root / "graph-home"
        (repo / "src").mkdir(parents=True)
        (home / "config").mkdir(parents=True)
        source = repo / "src/Demo.cs"
        shutil.copyfile(args.source, source)
        (home / "config/bindings.json").write_text(json.dumps({"bindings": {"demo-repo": str(repo)}}))
        solution = root / "solution.json"
        solution.write_text(json.dumps({"id": "demo-solution", "profile": "default", "catalog_host_repo": "demo-repo", "projects": [{"id": "demo-project", "repo_id": "demo-repo", "path": "src"}]}))
        env = {**os.environ, "AXIOM_HOME": str(home), "PATH": "/usr/bin:/bin"}
        register = run([str(args.graphd), "solution", "register", "--config", str(solution), "--apply", "--json"], env)
        process = subprocess.Popen([str(args.graphd), "serve", "--json"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pointer = repo / ".axiom/graph/demo-solution/_catalog/live/current.json"
        try:
            deadline = time.monotonic() + 20
            while not pointer.is_file():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("graphd did not publish a catalog")
                time.sleep(0.2)
            before = query(home, repo, "Demo", args.registry_platform)
            if not any(node["source"]["file"] == "Demo.cs" for node in before["nodes"]):
                raise RuntimeError("installed MCP wheel did not find the source node")
            before_id = before["catalog_generation_id"]
            source.write_text(source.read_text() + "\npublic sealed class K002CatalogEdit { }\n")
            while True:
                if process.poll() is not None or time.monotonic() > deadline + 20:
                    raise RuntimeError("graphd did not publish the source edit")
                if pointer.is_file() and json.loads(pointer.read_text())["generation_id"] != before_id:
                    break
                time.sleep(0.2)
            while True:
                after = query(home, repo, "K002CatalogEdit", args.registry_platform)
                if after["nodes"] and after["catalog_generation_id"] != before_id:
                    break
                if time.monotonic() > deadline + 20:
                    raise RuntimeError(f"installed MCP wheel did not query the new catalog: nodes={len(after['nodes'])}, before={before_id}, after={after['catalog_generation_id']}")
                time.sleep(0.2)
            restart = None
            if args.restart_check:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=10)
                process = subprocess.Popen([str(args.graphd), "serve", "--json"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                restart_before = after["catalog_generation_id"]
                source.write_text(source.read_text() + "\npublic sealed class K002RestartEdit { }\n")
                restart_deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None or time.monotonic() > restart_deadline:
                        raise RuntimeError("graphd did not publish after restart")
                    if pointer.is_file() and json.loads(pointer.read_text())["generation_id"] != restart_before:
                        break
                    time.sleep(0.2)
                while True:
                    restart = query(home, repo, "K002RestartEdit", args.registry_platform)
                    if restart["nodes"] and restart["catalog_generation_id"] != restart_before:
                        break
                    if time.monotonic() > restart_deadline:
                        raise RuntimeError("installed MCP wheel did not query the restarted catalog")
                    time.sleep(0.2)
            print(json.dumps({
                "ok": True, "register_exit": register.returncode,
                "wheel_import_under_venv": True,
                "interpreter_sha256": hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
                "catalog_before": before_id, "catalog_after": after["catalog_generation_id"],
                "nodes_before": len(before["nodes"]), "nodes_after": len(after["nodes"]),
                "restart_catalog_generation_id": restart["catalog_generation_id"] if restart else None,
                "restart_nodes": len(restart["nodes"]) if restart else None,
            }, sort_keys=True))
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
