#!/usr/bin/env python3
"""Validate and redact the native K-010 Windows candidate run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import zipfile


K305_A_SHA = "beb24f04848af03e62ebed10e9fd3587f38acba14f753a1baef86ccdbcebef8b"
K309_CORE_SHA = "ba9e294cd112c7311b755ab9aad2d3713502c68925febb48359fec0fe1cc2c53"
K309_MANIFEST_SHA = "b33999d07c1a71d3ce00c93620870d08948eec6f0e010f7891d6c630717af7df"
K309_DAEMON_SHA = "2c85a61a8f03f433b5cde82ba05e70eeabdc4e3a56fd4c003cc733a023f86164"
K010_KIT_SHA = "70113cd08b01b6d41dc535ba962101b4ffee8ec976d6e276118f4468bd72ca73"
K010_SOURCE = "79eb58cc57bc0d47330df491df59034fe0f22b3b"
K309_SOURCE = "4f8765a74ae5f077f53d092ddb4fea40d0c44fe3"
MCP_WHEEL_SHA = "36848a68ad4aa66932fbfd3773c020fab6267aa2e705ef624797745664409b56"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, document: dict) -> str:
    path.write_bytes(
        (
            json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode()
    )
    return sha(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--a-archive", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve(strict=True)
    kit = args.kit.resolve(strict=True)
    out = args.out.resolve(strict=True)
    logs = out / "logs"
    require(sha(args.a_archive) == K305_A_SHA, "K-305 A bytes changed")
    require(
        sha(args.core / "axiom-0.1.2-windows-x64.zip") == K309_CORE_SHA,
        "K-309 core bytes changed",
    )
    require(
        sha(args.core / "candidate-manifest.json") == K309_MANIFEST_SHA,
        "K-309 manifest changed",
    )
    archive = kit / "axiom-0.1.2-windows-x64-update-kit.zip"
    require(sha(archive) == K010_KIT_SHA, "K-010 kit bytes changed")
    with zipfile.ZipFile(archive) as zipped:
        require(
            hashlib.sha256(zipped.read("axiom-0.1.2-windows-x64.zip")).hexdigest()
            == K309_CORE_SHA,
            "kit does not carry exact K-309 core",
        )
        require(
            hashlib.sha256(zipped.read("axiom-graphd.exe")).hexdigest()
            == K309_DAEMON_SHA,
            "kit daemon differs from K-309",
        )
    files = read(kit / "candidate-files.json")
    release = read(kit / "release/release-set.json")
    lock = read(kit / "release/candidate-lock.json")
    require(
        files["task_id"] == "K-010" and files["cli_b_revision"] == K010_SOURCE,
        "kit task identity differs",
    )
    require(release["release_version"] == "0.1.2", "release set version differs")
    require(
        lock["core_revision"] == K309_SOURCE, "candidate lock core revision differs"
    )

    observed = {
        name: read(run / filename)
        for name, filename in {
            "a_install": "a-install-apply.json",
            "runtime": "a-runtime.json",
            "a_engine": "a-engine-apply.json",
            "negative": "negative-kit.json",
            "b_check": "b-check.json",
            "b_plan": "b-plan-result.json",
            "b_apply": "b-apply.json",
            "service_install": "service-install.json",
            "service_start": "service-start.json",
            "service_query_watch": "service-query-watch.json",
            "rollback_refusal": "rollback-refusal-summary.json",
            "service_uninstall": "service-uninstall.json",
            "b_rollback": "b-rollback.json",
            "engine_uninstall": "engine-uninstall-apply.json",
            "runtime_remove": "runtime-remove.json",
            "distribution_uninstall": "distribution-uninstall-apply.json",
            "unprivileged": "unprivileged-summary.json",
            "migration": "migration-readiness.json",
            "cleanup": "cleanup-summary.json",
        }.items()
    }
    matrix = read(run / "mcp-matrix/raw/matrix.json")
    observed["mcp_matrix"] = matrix
    wrong_core = read(run.parent / "wrong-core-refusal.json")
    require(
        wrong_core
        == {
            "status": "refused",
            "reason": "K-010 requires the reviewed K-309 core manifest",
        },
        "old core was not refused by the K-010 kit builder",
    )
    observed["wrong_core"] = wrong_core
    before_path = read(run / "hkcu-path-before.json")
    after_path = read(run / "hkcu-path-after.json")
    a_plan_digest = read(run / "a-engine-plan.json")["details"]["plan_digest"]
    b_plan_digest = observed["b_plan"]["plan_digest"]
    engine_uninstall_digest = read(run / "engine-uninstall-plan.json")["details"][
        "plan_digest"
    ]
    distribution_uninstall_digest = read(run / "distribution-uninstall-plan.json")[
        "plan_digest"
    ]

    require(
        observed["a_install"]["outcome"] == "installed"
        and observed["a_install"]["exit_code"] == 0,
        "A distribution install failed",
    )
    require(
        observed["runtime"]["status"] == "provisioned"
        and observed["runtime"]["bundle_sha256"]
        == "82e9ca2920f91f6b41d953d2b53a6d8f359c2958be7f0c7e781a5e6e76143190",
        "pinned MCP runtime failed",
    )
    require(observed["a_engine"]["code"] == 0, "A engine install failed")
    require(
        observed["negative"]["ok"] is True
        and observed["negative"]["a_unchanged"] is True
        and {c["id"] for c in observed["negative"]["cases"]}
        == {"corrupt", "incompatible"},
        "negative kit cases failed",
    )
    require(
        observed["b_check"]["candidate"]["core_revision"] == K309_SOURCE,
        "B check used another core",
    )
    require(
        observed["b_plan"]["plan_digest"] == observed["b_apply"]["plan_digest"],
        "B plan approval differs",
    )
    require(
        observed["b_apply"]["status"] == "updated"
        and observed["b_apply"]["after"]["core_revision"] == K309_SOURCE
        and observed["b_apply"]["after"]["mcp_wheel_sha256"] == MCP_WHEEL_SHA,
        "B activation differs",
    )
    require(
        observed["service_install"].get("registered") is not None
        and observed["service_start"]["code"] == 0,
        "public B service failed",
    )
    watcher = observed["service_query_watch"]
    require(
        watcher["Changed"] is True
        and watcher["TaskState"] in (4, "Running")
        and watcher["InitialGeneration"] != watcher["UpdatedGeneration"],
        "installed watcher did not advance",
    )
    require(
        matrix["passed"] is True
        and len(matrix["leg_status"]) == 7
        and set(matrix["leg_status"].values()) == {"passed"},
        "installed MCP matrix did not pass",
    )
    refusal = observed["rollback_refusal"]
    require(
        refusal["Exit"] == 2
        and refusal["StateSame"] is True
        and refusal["Pointer"] == "0.1.2"
        and refusal["TaskState"] in (4, "Running"),
        "post-update service rollback did not refuse safely",
    )
    require(
        observed["service_uninstall"]["removed"] is True,
        "owned B service was not removed",
    )
    require(
        observed["b_rollback"]["status"] == "rolled_back"
        and observed["b_rollback"]["after"]["core_version"] == "0.1.1",
        "A rollback failed",
    )
    require(
        observed["engine_uninstall"]["code"] == 0
        and observed["runtime_remove"]["status"] == "removed"
        and observed["distribution_uninstall"]["outcome"] == "removed",
        "owned uninstall failed",
    )
    limited = observed["unprivileged"]
    require(
        limited["Limited"] is True
        and limited["IsElevated"] is False
        and all(
            limited[k] == 0 for k in ("Install", "UninstallPlan", "UninstallApply")
        ),
        "Limited user install failed",
    )
    require(
        observed["cleanup"]
        == {
            "PathSame": True,
            "NoTask": True,
            "NoProcess": True,
            "Sentinel": True,
            "CliAbsent": True,
        },
        "cleanup or preservation failed",
    )
    require(
        before_path["Value"] == after_path["Value"]
        and before_path["Kind"] == after_path["Kind"],
        "HKCU Path changed",
    )
    require(
        observed["migration"]["code"] == "NOT_READY",
        "migration readiness changed; reassess the release gate",
    )

    workspace = Path(__file__).resolve().parents[3]
    substitutions = [
        (str(workspace), "<WORKSPACE>"),
        (os.environ.get("USERPROFILE", ""), "<USERPROFILE>"),
        (socket.gethostname(), "<HOST>"),
    ]

    def redact(value: object, key: str = "") -> object:
        if isinstance(value, dict):
            return {
                name: redact(item, name)
                for name, item in value.items()
                if not name.endswith("_hex")
            }
        if isinstance(value, list):
            return [redact(item, key) for item in value]
        if isinstance(value, str):
            if key.lower() in ("user", "username"):
                return "<CURRENT_USER>"
            for actual, token in substitutions:
                if actual:
                    value = value.replace(actual, token)
            return value
        return value

    logs.mkdir(exist_ok=True)
    raw = {
        "a_install": "a-install-apply.json",
        "runtime": "a-runtime.json",
        "a_engine": "a-engine-apply.json",
        "negative": "negative-kit.json",
        "b_check": "b-check.json",
        "b_plan": "b-plan-result.json",
        "b_apply": "b-apply.json",
        "service_install": "service-install.json",
        "service_start": "service-start.json",
        "service_query_watch": "service-query-watch.json",
        "rollback_refusal": "rollback-refusal-summary.json",
        "service_uninstall": "service-uninstall.json",
        "b_rollback": "b-rollback.json",
        "engine_uninstall": "engine-uninstall-apply.json",
        "runtime_remove": "runtime-remove.json",
        "distribution_uninstall": "distribution-uninstall-apply.json",
        "unprivileged": "unprivileged-summary.json",
        "migration": "migration-readiness.json",
        "cleanup": "cleanup-summary.json",
        "mcp_matrix": "mcp-matrix/raw/matrix.json",
    }
    imported = {}
    for name, filename in raw.items():
        source = run / filename
        target = logs / f"{name}.json"
        imported[name] = {
            "path": f"evidence/K-010/logs/{name}.json",
            "sha256": write(target, redact(observed[name])),
            "raw_sha256": sha(source),
        }
    wrong_log = logs / "wrong_core.json"
    imported["wrong_core"] = {
        "path": "evidence/K-010/logs/wrong_core.json",
        "sha256": write(wrong_log, wrong_core),
        "raw_sha256": sha(run.parent / "wrong-core-refusal.json"),
    }

    def command(identifier: str, argv: str, exit_code: int, log: str) -> dict:
        return {
            "id": identifier,
            "command": argv,
            "exit_code": exit_code,
            "output": imported[log],
        }

    commands = [
        command(
            "a-install",
            "pwsh -File Install-AxiomCli.ps1 -ReleaseSet <K305-A> -InstallRoot <isolated-run> -Apply -ApproveDigest ca01ab0fe241c43f4bcc25d7384f9c0095fa83965416aa13eea426454382b6b5 -NonInteractive -Json",
            0,
            "a_install",
        ),
        command(
            "runtime",
            "pwsh -File Provision-McpRuntime.ps1 -Action provision -Root <isolated-run> -RuntimeArchive <K305-A>/python-3.13.15-embed-amd64.zip -RuntimeSha256 d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf -PipWheel <K305-A>/pip-26.1.2-py3-none-any.whl -PipSha256 382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab -Inputs <K305-A>/windows-x64-py313-inputs.tar -InputsSha256 82e9ca2920f91f6b41d953d2b53a6d8f359c2958be7f0c7e781a5e6e76143190 -SourceRevision 78f991622b52db86499c3031ed98c07a4d9d408e -Version 0.1.1",
            0,
            "runtime",
        ),
        command(
            "a-engine",
            f"axiom-cli --json install --apply --from <K305-A>/channel.json --approve-digest {a_plan_digest}",
            0,
            "a_engine",
        ),
        command(
            "negative-kit",
            "python tests/windows/Verify-K306UpdateKit.py --kit <K010-kit> --installed-root <isolated-A> --scratch <isolated-run>",
            0,
            "negative",
        ),
        command(
            "b-check",
            "axiom-cli --json update check (AXIOM_CLI_COMPOSITE_KIT=<K010-kit>)",
            0,
            "b_check",
        ),
        command(
            "b-plan",
            "axiom-cli --json update plan --to 0.1.2 --out <isolated-run>/b-plan.json",
            0,
            "b_plan",
        ),
        command(
            "b-apply",
            f"axiom-cli --json update apply --plan <isolated-run>/b-plan.json --approve-digest {b_plan_digest}",
            0,
            "b_apply",
        ),
        command(
            "service-install",
            "axiom service install --component axiom-graphd --user --json",
            0,
            "service_install",
        ),
        command(
            "service-start",
            "axiom service start --component axiom-graphd --json",
            0,
            "service_start",
        ),
        command(
            "service-query-watch",
            "axiom-graphd query context --solution demo-solution --symbol K010.TokenSource/K010.WatcherAdded --json (before/after source edit)",
            0,
            "service_query_watch",
        ),
        command(
            "mcp-matrix",
            "python tests/native/capture_native_matrix.py --target windows-x64 --python <installed-venv> --installed-repo <isolated-source> --installed-axiom-home <isolated-run> --installed-symbol K010.WatcherAdded --task-id K-010",
            0,
            "mcp_matrix",
        ),
        command(
            "rollback-refusal",
            "axiom-cli --json update rollback --transaction previous (post-update B service present)",
            2,
            "rollback_refusal",
        ),
        command(
            "service-uninstall",
            "axiom service uninstall --component axiom-graphd --json",
            0,
            "service_uninstall",
        ),
        command(
            "b-rollback",
            "axiom-cli --json update rollback --transaction previous",
            0,
            "b_rollback",
        ),
        command(
            "engine-uninstall",
            f"axiom-cli --json uninstall --apply --approve-digest {engine_uninstall_digest}",
            0,
            "engine_uninstall",
        ),
        command(
            "runtime-remove",
            "pwsh -File Provision-McpRuntime.ps1 -Action remove -Root <isolated-run>",
            0,
            "runtime_remove",
        ),
        command(
            "distribution-uninstall",
            f"pwsh -File Uninstall-AxiomCli.ps1 -InstallRoot <isolated-run> -Apply -ApproveDigest {distribution_uninstall_digest} -Json",
            0,
            "distribution_uninstall",
        ),
        command(
            "unprivileged",
            "schtasks Limited powershell.exe -File Invoke-AxiomCliWindowsUnprivilegedLeg.ps1 (final B release set)",
            0,
            "unprivileged",
        ),
        command(
            "wrong-core-refusal",
            "python packaging/windows/Build-UpdateKit.py --task-id K-010 --b-core-dir <K308-core> --b-core-manifest-sha 62d25dae01c23a566d1157890c49a6ef572ff370003f09888504df3e5d1e73ee",
            9,
            "wrong_core",
        ),
        command(
            "migration-readiness",
            "axiom migrate plan --solution demo-solution --json",
            4,
            "migration",
        ),
        command(
            "cleanup",
            "PowerShell verify HKCU Path value/type, no Task/process, user sentinel and absent CLI",
            0,
            "cleanup",
        ),
    ]
    report = {
        "task_id": "K-010",
        "status": "local_verified",
        "certified": False,
        "provenance": "candidate",
        "platform": "windows-x64",
        "source_revision": K010_SOURCE,
        "core_source_revision": K309_SOURCE,
        "input_a_sha256": K305_A_SHA,
        "core_b_sha256": K309_CORE_SHA,
        "core_manifest_sha256": K309_MANIFEST_SHA,
        "kit_sha256": K010_KIT_SHA,
        "kit_manifest_sha256": sha(kit / "kit-manifest.json"),
        "release_set_sha256": sha(kit / "release/release-set.json"),
        "environment": {
            "os": observed["a_install"]["host"]["windows_version"],
            "arch": "x86_64",
            "execution": "native",
            "limited_install_elevated": limited["IsElevated"],
            "python_runtime": "3.13.15 pinned embeddable",
            "mcp_wheel_sha256": MCP_WHEEL_SHA,
        },
        "cases": {
            "distribution_install": True,
            "pinned_mcp": True,
            "negative_kit": True,
            "composite_update": True,
            "public_limited_service": True,
            "real_source_watcher": True,
            "installed_mcp_matrix_seven_legs": True,
            "post_update_service_rollback_refusal": True,
            "owned_service_removal_then_rollback": True,
            "uninstall_preserves_data_and_path": True,
            "unprivileged_install_and_uninstall": True,
        },
        "limitations": [
            "The installed migrate plan verb returned NOT_READY (exit 4); aggregate migration/release acceptance remains open.",
            "This candidate is unsigned and unpublished, and does not satisfy released-fixture trust or other required platform lanes.",
        ],
        "logs": imported,
        "commands": commands,
    }
    report_path = out / "native-report.json"
    print(
        json.dumps(
            {
                "status": "captured",
                "report_sha256": write(report_path, report),
                "kit_sha256": K010_KIT_SHA,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
