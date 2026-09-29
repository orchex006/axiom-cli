#!/usr/bin/env python3
"""Native Mac Intel A/B distribution update, installed query, watcher and rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def call(
    argv: list[str], env: dict[str, str], trace: list[dict], expected: int = 0
) -> dict:
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=90)
    row = {
        "argv": argv,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    trace.append(row)
    if result.returncode != expected:
        raise AssertionError(
            f"{argv[0]} returned {result.returncode}, expected {expected}: {row}"
        )
    content = result.stdout if expected == 0 else result.stderr
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"text": content}


def distribution(
    release: Path,
    env: dict[str, str],
    trace: list[dict],
    action: str,
    mode: str,
    approval: str = "",
    expected: int = 0,
) -> dict:
    argv = [
        "/bin/sh",
        str(release / "runtime/bootstrap.sh"),
        action,
        "--release-set",
        str(release),
        mode,
    ]
    if approval:
        argv.extend(["--approve-digest", approval])
    return call(argv, env, trace, expected)


def state(home: Path) -> dict:
    root = home / ".local/share/axiom"
    paths = {
        "entrypoint_record": root / "entrypoints/current.tsv",
        "engine_pointer": root / "installs/ecosystem/current",
        "skills_pointer": root / "installs/ecosystem/skills/current",
        "runtime_pointer": root / "mcp-runtime/current.json",
        "cli_executable": home / ".local/bin/axiom-cli",
        "core_executable": home / ".local/bin/axiom",
        "bindings": root / "config/bindings.json",
        "user_data": home / "user-data.txt",
    }
    return {name: sha(path) for name, path in paths.items()}


def generation_details(home: Path) -> dict:
    root = home / ".local/share/axiom"
    pointer = json.loads((root / "installs/ecosystem/current").read_text())
    runtime = json.loads((root / "mcp-runtime/current.json").read_text())
    skills = json.loads((root / "installs/ecosystem/skills/current").read_text())
    skills_manifest = root / "installs/ecosystem" / skills["directory"] / "bundle.json"
    if sha(skills_manifest) != skills["manifest_sha256"]:
        raise AssertionError("skills pointer names changed manifest bytes")
    components = []
    for row in pointer["activated"]:
        destination = Path(row["destination"])
        if not destination.is_relative_to(root):
            raise AssertionError("engine activated an artifact outside the owned root")
        if sha(destination) != row["sha256"]:
            raise AssertionError("engine pointer names changed artifact bytes")
        components.append(
            {
                "component": row["component"],
                "version": row["version"],
                "path_below_install_root": destination.relative_to(root).as_posix(),
                "sha256": row["sha256"],
            }
        )
    mcp = root / "mcp-runtime/versions" / runtime["generation"] / "venv/bin/axiom-mcp"
    if sha(mcp) != runtime["executable_sha256"]:
        raise AssertionError("MCP runtime pointer names changed executable bytes")
    return {
        "cli_path_below_home": ".local/bin/axiom-cli",
        "cli_sha256": sha(home / ".local/bin/axiom-cli"),
        "engine_components": components,
        "skills_pointer": skills,
        "mcp_generation": runtime["generation"],
        "mcp_path_below_install_root": mcp.relative_to(root).as_posix(),
        "mcp_executable_sha256": runtime["executable_sha256"],
    }


def daemon_path(home: Path) -> Path:
    root = home / ".local/share/axiom"
    pointer = json.loads((root / "installs/ecosystem/current").read_text())
    rows = [row for row in pointer["activated"] if row["component"] == "axiom-graphd"]
    if len(rows) != 1:
        raise AssertionError("engine pointer has no unique graphd component")
    path = Path(rows[0]["destination"])
    if not path.is_file() or sha(path) != rows[0]["sha256"]:
        raise AssertionError("activated daemon does not match its pointer digest")
    return path


def wait_catalog(repo: Path, previous: str | None, timeout: float = 25) -> str:
    pointer = repo / ".axiom/graph/demo-solution/_catalog/live/current.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pointer.is_file():
            generation = json.loads(pointer.read_text())["generation_id"]
            if generation != previous:
                return generation
        time.sleep(0.2)
    raise AssertionError("persistent watcher did not advance the catalog")


def query_and_watch(
    home: Path,
    work: Path,
    source: Path,
    symbol: str,
    env: dict[str, str],
    trace: list[dict],
) -> str:
    daemon = daemon_path(home)
    before = wait_catalog(work, None)
    query = call(
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
        env,
        trace,
    )
    if "TokenSource" not in json.dumps(query):
        raise AssertionError("installed daemon query omitted the source symbol")
    source.write_text(source.read_text() + f"public sealed class {symbol} {{ }}\n")
    after = wait_catalog(work, before)
    changed = call(
        [
            str(daemon),
            "query",
            "context",
            "--solution",
            "demo-solution",
            "--symbol",
            f"Demo.{symbol}",
            "--json",
        ],
        env,
        trace,
    )
    if symbol not in json.dumps(changed):
        raise AssertionError("installed daemon query omitted the watcher edit")
    return after


def release_identity(release: Path) -> dict:
    content = json.loads((release / "release-set.json").read_text())
    channel = json.loads((release / "channel.json").read_text())
    runtime = json.loads((release / "runtime/manifest.json").read_text())
    return {
        "release_set_sha256": sha(release / "release-set.json"),
        "channel_sha256": sha(release / "channel.json"),
        "runtime_manifest_sha256": sha(release / "runtime/manifest.json"),
        "cli_sha256": content["artifacts"][0]["sha256"],
        "core_version": content["artifacts"][1]["version"],
        "core_revision": content["artifacts"][1]["revision"],
        "core_sha256": content["artifacts"][2]["sha256"],
        "mcp_version": runtime["mcp_version"],
        "mcp_revision": runtime["mcp_revision"],
        "skills_version": next(
            row["version"]
            for row in channel["components"]
            if row["component"] == "skills"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-a", required=True, type=Path)
    parser.add_argument("--candidate-b", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != (
        "Darwin",
        "x86_64",
    ) or os.getuid() == 0:
        raise SystemExit("native non-root Mac x64 host required")
    a, b = args.candidate_a.resolve(strict=True), args.candidate_b.resolve(strict=True)
    ai, bi = release_identity(a), release_identity(b)
    if (
        ai["cli_sha256"] == bi["cli_sha256"]
        or ai["core_version"] == bi["core_version"]
        or ai["core_revision"] == bi["core_revision"]
        or ai["core_sha256"] == bi["core_sha256"]
    ):
        raise SystemExit(
            "A/B must differ in CLI, core version, source revision and digest"
        )
    out = args.out.resolve()
    if out.exists():
        raise SystemExit("output already exists")
    with tempfile.TemporaryDirectory(prefix="axiom-k106-native-") as name:
        test_root = Path(name).resolve()
        home = test_root / "home"
        (home / "Library/LaunchAgents").mkdir(parents=True)
        (home / "user-data.txt").write_text("preserve user data\n")
        env = {
            **os.environ,
            "HOME": str(home),
            "SHELL": "/bin/zsh",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        }
        trace: list[dict] = []
        root = home / ".local/share/axiom"
        work = test_root / "real-source"
        source = work / "src/TokenSource.cs"
        source.parent.mkdir(parents=True)
        source.write_text(
            'namespace Demo;\npublic class TokenSource { public string Issue() => "ok"; }\n'
        )
        (work / "Demo.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>\n'
        )
        try:
            plan = distribution(a, env, trace, "install", "--dry-run")
            distribution(a, env, trace, "install", "--apply", plan["plan_digest"])
            (root / "config/bindings.json").write_text(
                json.dumps({"bindings": {"demo-repo": str(work)}}) + "\n"
            )
            solution = test_root / "solution.json"
            solution.write_text(
                json.dumps(
                    {
                        "id": "demo-solution",
                        "profile": "default",
                        "catalog_host_repo": "demo-repo",
                        "projects": [
                            {
                                "id": "demo-project",
                                "repo_id": "demo-repo",
                                "path": "src",
                            }
                        ],
                    }
                )
                + "\n"
            )
            graph_env = dict(env, AXIOM_HOME=str(root))
            engine = home / ".local/bin/axiom"
            call(
                [
                    str(engine),
                    "service",
                    "stop",
                    "--component",
                    "axiom-graphd",
                    "--json",
                ],
                graph_env,
                trace,
            )
            call(
                [
                    str(daemon_path(home)),
                    "solution",
                    "register",
                    "--config",
                    str(solution),
                    "--apply",
                    "--json",
                ],
                graph_env,
                trace,
            )
            call(
                [
                    str(engine),
                    "service",
                    "start",
                    "--component",
                    "axiom-graphd",
                    "--json",
                ],
                graph_env,
                trace,
            )
            a_catalog = query_and_watch(
                home, work, source, "K106WatcherA", graph_env, trace
            )
            a_state = state(home)
            a_details = generation_details(home)
            corrupt = test_root / "B-corrupt"
            shutil.copytree(b, corrupt)
            with (corrupt / "axiom").open("ab") as stream:
                stream.write(b"corrupt K-106 candidate")
            distribution(corrupt, env, trace, "update", "--dry-run", expected=9)
            if state(home) != a_state:
                raise AssertionError("corrupt B changed installed A")
            incompatible = test_root / "B-incompatible"
            shutil.copytree(b, incompatible)
            channel_path = incompatible / "channel.json"
            channel = json.loads(channel_path.read_text())
            channel["components"][0]["revision"] = "f" * 40
            channel_path.write_text(json.dumps(channel) + "\n")
            distribution(incompatible, env, trace, "update", "--dry-run", expected=9)
            if state(home) != a_state:
                raise AssertionError("incompatible B changed installed A")
            plan = distribution(b, env, trace, "update", "--dry-run")
            updated = distribution(
                b, env, trace, "update", "--apply", plan["plan_digest"]
            )
            b_state = state(home)
            b_details = generation_details(home)
            if (
                b_state["cli_executable"] != bi["cli_sha256"]
                or b_state["engine_pointer"] == a_state["engine_pointer"]
            ):
                raise AssertionError(
                    "public distribution update did not activate CLI and engine B"
                )
            b_catalog = query_and_watch(
                home, work, source, "K106WatcherB", graph_env, trace
            )
            status = call(
                [
                    str(home / ".local/bin/axiom"),
                    "service",
                    "status",
                    "--component",
                    "axiom-graphd",
                    "--json",
                ],
                graph_env,
                trace,
            )
            if "state = running" not in status.get("stdout", ""):
                raise AssertionError(
                    "owned service did not remain running after B update"
                )
            plan = distribution(b, env, trace, "rollback", "--dry-run")
            rolled = distribution(
                b, env, trace, "rollback", "--apply", plan["plan_digest"]
            )
            restored = state(home)
            restored_details = generation_details(home)
            for key in (
                "entrypoint_record",
                "engine_pointer",
                "skills_pointer",
                "runtime_pointer",
                "cli_executable",
                "core_executable",
                "bindings",
                "user_data",
            ):
                if restored[key] != a_state[key]:
                    raise AssertionError("rollback changed A state: " + key)
            rollback_catalog = query_and_watch(
                home, work, source, "K106WatcherRollback", graph_env, trace
            )
            # Every injected update must return to the exact A pointers and preserve user data.
            failures = {}
            for phase in (
                "download",
                "stage",
                "activation",
                "service_restart",
                "post_activation",
            ):
                injected = dict(env, AXIOM_K106_FAIL_AT=phase)
                plan = distribution(b, injected, trace, "update", "--dry-run")
                distribution(
                    b,
                    injected,
                    trace,
                    "update",
                    "--apply",
                    plan["plan_digest"],
                    expected=9,
                )
                observed = state(home)
                for key in (
                    "entrypoint_record",
                    "engine_pointer",
                    "skills_pointer",
                    "runtime_pointer",
                    "cli_executable",
                    "core_executable",
                    "bindings",
                    "user_data",
                ):
                    if observed[key] != a_state[key]:
                        raise AssertionError(f"{phase} left mixed state: {key}")
                failures[phase] = "A preserved"
            plan = distribution(a, env, trace, "uninstall", "--dry-run")
            distribution(a, env, trace, "uninstall", "--apply", plan["plan_digest"])
            if (home / "user-data.txt").read_text() != "preserve user data\n":
                raise AssertionError("uninstall changed user data")
            result = {
                "status": "local_verified",
                "lane": "macos-x64",
                "certified": False,
                "candidate_a": ai,
                "candidate_b": bi,
                "A_catalog_generation": a_catalog,
                "B_catalog_generation": b_catalog,
                "rollback_catalog_generation": rollback_catalog,
                "A_state": a_state,
                "B_state": b_state,
                "restored_state": restored,
                "A_generation": a_details,
                "B_generation": b_details,
                "restored_generation": restored_details,
                "engine_transaction": updated["engine_transaction"],
                "rollback_status": rolled["status"],
                "failure_boundaries": failures,
                "candidate_refusals": {
                    "corrupt": "A preserved",
                    "incompatible": "A preserved",
                },
                "user_data_preserved": True,
            }
        finally:
            if (home / ".local/bin/axiom").is_file():
                for action in ("stop", "uninstall"):
                    argv = [
                        str(home / ".local/bin/axiom"),
                        "service",
                        action,
                        "--component",
                        "axiom-graphd",
                        "--json",
                    ]
                    process = subprocess.run(
                        argv,
                        env=dict(env, AXIOM_HOME=str(root)),
                        capture_output=True,
                        text=True,
                    )
                    trace.append(
                        {
                            "argv": argv,
                            "exit_code": process.returncode,
                            "stdout": process.stdout,
                            "stderr": process.stderr,
                            "cleanup": True,
                        }
                    )
        out.mkdir(parents=True)
        marker = "<isolated-test-root>"
        text = json.dumps(trace, indent=2).replace(str(test_root), marker)
        (out / "native-transcript.json").write_text(text + "\n")
        (out / "report.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
