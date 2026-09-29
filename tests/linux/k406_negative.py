#!/usr/bin/env python3
"""Exercise K-406 candidate refusals and prove the installed A bytes survive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(home: Path) -> dict:
    root = home / ".local/share/axiom"
    cli = home / ".local/share/axiom-cli"
    paths = {
        "cli": home / ".local/bin/axiom-cli",
        "cli_owner": cli / ".axiom-cli-owner",
        "engine": root / "installs/ecosystem/current",
        "skills": root / "installs/ecosystem/skills/current",
        "runtime": root / "mcp-runtime/current.json",
        "bindings": root / "config/bindings.json",
        "source": home / "demo-repo/src/TokenSource.cs",
        "user_data": home / "user-data.txt",
    }
    result = {name: sha(path) for name, path in paths.items()}
    result["cli_generations"] = sorted(
        path.name for path in (cli / "generations").iterdir()
    )
    result["engine_generations"] = sorted(
        path.name for path in (root / "installs/ecosystem/versions").iterdir()
    )
    result["pending_absent"] = not (root / "distribution-update-pending.json").exists()
    result["receipt_absent"] = not (root / "distribution-update.json").exists()
    return result


def call(argv: list[str], env: dict[str, str], expected: int) -> dict:
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=180)
    if result.returncode != expected:
        raise ValueError(
            f"{Path(argv[0]).name} exited {result.returncode}, expected {expected}: "
            + (result.stdout + result.stderr)[-1000:]
        )
    body = json.loads(result.stdout or result.stderr)
    if expected and body["status"] != "refused":
        raise ValueError("negative command did not return a refusal")
    return body


def run(args: argparse.Namespace) -> dict:
    home, kit, kit_a = args.home, args.kit, args.incompatible_kit
    root = home / ".local/share/axiom"
    baseline = snapshot(home)
    if not baseline["pending_absent"] or not baseline["receipt_absent"]:
        raise ValueError("negative test requires clean A state")
    cli = kit / "release/axiom-cli"
    env = dict(
        os.environ,
        HOME=str(home),
        AXIOM_CLI_INSTALL_ROOT=str(root),
        AXIOM_CLI_COMPOSITE_KIT=str(kit),
        PATH="/usr/bin:/bin",
    )
    plan_file = home / "k406-negative-plan.json"

    def plan() -> dict:
        return call(
            [
                str(cli),
                "update",
                "plan",
                "--to",
                "0.1.1",
                "--out",
                str(plan_file),
                "--json",
            ],
            env,
            0,
        )

    def unchanged() -> None:
        current = snapshot(home)
        if current != baseline:
            raise ValueError(
                f"negative case changed installed A: {current} != {baseline}"
            )

    planned = plan()
    cases: list[dict] = []
    wrong = call(
        [
            str(cli),
            "update",
            "apply",
            "--plan",
            str(plan_file),
            "--approve-digest",
            "0" * 64,
            "--json",
        ],
        env,
        2,
    )
    unchanged()
    cases.append({"id": "wrong-approval", "reason": wrong["reason"]})

    corrupt = args.scratch
    if corrupt.exists():
        raise ValueError("corrupt kit scratch already exists")
    shutil.copytree(kit, corrupt)
    with (corrupt / "release/axiom").open("ab") as stream:
        stream.write(b"corrupt K-406 candidate")
    bad_env = dict(env, AXIOM_CLI_COMPOSITE_KIT=str(corrupt))
    bad = call([str(cli), "update", "plan", "--to", "0.1.1", "--json"], bad_env, 2)
    unchanged()
    cases.append({"id": "corrupt-set", "reason": bad["reason"]})

    old_env = dict(env, AXIOM_CLI_COMPOSITE_KIT=str(kit_a))
    old = call([str(cli), "update", "plan", "--to", "0.1.0", "--json"], old_env, 2)
    unchanged()
    cases.append({"id": "incompatible-set", "reason": old["reason"]})

    pointer = json.loads((root / "mcp-runtime/current.json").read_text())
    python = root / "mcp-runtime/versions" / pointer["generation"] / "venv/bin/python"
    base = [
        str(python),
        str(kit / "Update-Distribution.py"),
        "apply",
        "--release",
        str(kit / "release"),
        "--files",
        str(kit / "candidate-files.json"),
        "--runtime-input",
        str(kit / "runtime-input.json"),
        "--home",
        str(home),
        "--root",
        str(root),
        "--cli-installer",
        str(kit / "Install-AxiomCli.sh"),
        "--kit-manifest",
        str(kit / "kit-manifest.json"),
        "--plan-file",
        str(plan_file),
        "--approve-digest",
        planned["plan_digest"],
    ]
    for boundary in (
        "download",
        "stage",
        "activation",
        "service-restart",
        "post-entrypoint",
    ):
        result = call(base + ["--fail-at", boundary], env, 2)
        unchanged()
        cases.append({"id": boundary + "-failure", "reason": result["reason"]})
        planned = plan()
    return {
        "status": "passed",
        "cases": cases,
        "case_count": len(cases),
        "baseline": baseline,
        "after": snapshot(home),
        "certified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--incompatible-kit", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
