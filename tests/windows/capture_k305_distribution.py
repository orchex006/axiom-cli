"""Capture the installed Windows distribution and ecosystem lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import winreg
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "tests/windows/Invoke-K305NativeService.ps1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-set", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--mcp-revision", required=True)
    args = parser.parse_args()
    release = args.release_set.resolve()
    installer = release / "Install-AxiomCli.ps1"
    uninstaller = release / "Uninstall-AxiomCli.ps1"
    release_document = json.loads(
        (release / "release-set.json").read_text(encoding="utf-8")
    )
    artifact_rows = {row["name"]: row for row in release_document["artifacts"]}
    for name in (
        "Install-AxiomCli.ps1",
        "Uninstall-AxiomCli.ps1",
        "AxiomCli.Windows.Common.ps1",
    ):
        if (
            name not in artifact_rows
            or digest(release / name) != artifact_rows[name]["sha256"]
        ):
            raise SystemExit(
                "distributed installer script is missing or changed: " + name
            )
    scratch = args.scratch.resolve()
    if sys.platform != "win32" or scratch.exists():
        raise SystemExit("K-305 requires native Windows and a new scratch root")
    scratch.mkdir(parents=True)
    home = scratch / "user-install"
    sentinel = home / "user-data" / "sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("human data remains\n", encoding="utf-8", newline="\n")
    profile = home / "user-data" / "profile.ps1"
    profile.write_text("# human edited profile\n", encoding="utf-8", newline="\n")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    shell = system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"
    path_base = os.pathsep.join((str(system_root / "System32"), str(shell.parent)))
    env = dict(os.environ, PATH=path_base, PYTHONPATH="", PYTHONNOUSERSITE="1")
    env["PSModulePath"] = str(system_root / "System32/WindowsPowerShell/v1.0/Modules")
    registry = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE
    )
    try:
        before_path, path_kind = winreg.QueryValueEx(registry, "Path")
        had_path = True
    except FileNotFoundError:
        before_path, path_kind, had_path = None, None, False
    report = []

    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            for source, replacement in (
                (str(scratch), "<isolated-root>"),
                (str(release), "<candidate-set>"),
            ):
                value = value.replace(source, replacement)
                value = value.replace(source.replace("\\", "\\\\"), replacement)
            return value
        return value

    def ps(case: str, script: Path, options: list[str], expected: int = 0) -> dict:
        evidence = scratch / (case + ".json")
        argv = [
            str(shell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *options,
            "-Json",
            "-Out",
            str(evidence),
        ]
        outcome = subprocess.run(
            argv, env=env, cwd=scratch, capture_output=True, timeout=180
        )
        if outcome.returncode != expected or not evidence.is_file():
            stderr = outcome.stderr.decode("utf-8", errors="replace")
            raise AssertionError(
                f"{case} exit {outcome.returncode}, expected {expected}: {stderr[-300:]}"
            )
        value = json.loads(evidence.read_text(encoding="utf-8"))
        report.append(
            {
                "case": case,
                "exit_code": outcome.returncode,
                "expected_exit_code": expected,
                "result": scrub(value),
            }
        )
        return value

    def program(
        case: str, argv: list[str], extra_env: dict[str, str], expected: int = 0
    ) -> dict:
        outcome = subprocess.run(
            argv,
            env=dict(env, **extra_env),
            cwd=scratch,
            capture_output=True,
            timeout=90,
        )
        stdout = outcome.stdout.decode("utf-8", errors="replace")
        stderr = outcome.stderr.decode("utf-8", errors="replace")
        if outcome.returncode != expected:
            raise AssertionError(
                f"{case} exit {outcome.returncode}, expected {expected}: {stderr[-300:]}"
            )
        value = json.loads(stdout)
        report.append(
            {
                "case": case,
                "exit_code": outcome.returncode,
                "expected_exit_code": expected,
                "result": scrub(value),
            }
        )
        return value

    try:
        release_digest = digest(release / "release-set.json")
        corrupt_set = scratch / "corrupt-set"
        assert corrupt_set.resolve().parent == scratch
        shutil.copytree(release, corrupt_set)
        corrupt_daemon = corrupt_set / "axiom-graphd.exe"
        with corrupt_daemon.open("r+b") as stream:
            stream.seek(-1, os.SEEK_END)
            original = stream.read(1)
            stream.seek(-1, os.SEEK_END)
            stream.write(bytes([original[0] ^ 1]))
        corrupt_root = scratch / "corrupt-home"
        (corrupt_root / "user-data").mkdir(parents=True)
        (corrupt_root / "user-data/sentinel.txt").write_text("human data remains\n")
        refused = ps(
            "corrupt-payload-refused",
            installer,
            ["-ReleaseSet", str(corrupt_set), "-InstallRoot", str(corrupt_root)],
            9,
        )
        assert refused["outcome"] == "refused" and not (corrupt_root / "bin").exists()
        assert (
            corrupt_root / "user-data/sentinel.txt"
        ).read_text() == "human data remains\n"
        unowned_root = scratch / "unowned-home"
        (unowned_root / "bin").mkdir(parents=True)
        unowned_file = unowned_root / "bin/axiom-cli.exe"
        unowned_file.write_bytes(b"human-owned executable\n")
        conflict = ps(
            "unowned-conflict",
            installer,
            [
                "-ReleaseSet",
                str(release),
                "-InstallRoot",
                str(unowned_root),
                "-Apply",
                "-ApproveDigest",
                release_digest,
            ],
            6,
        )
        assert (
            conflict["outcome"] == "refused"
            and unowned_file.read_bytes() == b"human-owned executable\n"
        )
        locked_root = scratch / "locked-home"
        (locked_root / "cli").mkdir(parents=True)
        lock_record = {
            "pid": os.getpid(),
            "transaction_id": "txn-held-by-k305-harness",
            "acquired_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (locked_root / "cli/transaction.lock").write_text(
            json.dumps(lock_record) + "\n", encoding="utf-8", newline="\n"
        )
        lock_result = ps(
            "held-lock-refused",
            installer,
            [
                "-ReleaseSet",
                str(release),
                "-InstallRoot",
                str(locked_root),
                "-Apply",
                "-ApproveDigest",
                release_digest,
            ],
            10,
        )
        assert lock_result["outcome"] == "refused"
        assert (
            json.loads(
                (locked_root / "cli/transaction.lock").read_text(encoding="utf-8")
            )
            == lock_record
        )
        plan = ps(
            "distribution-plan",
            installer,
            ["-ReleaseSet", str(release), "-InstallRoot", str(home)],
        )
        assert plan["outcome"] == "planned" and plan["plan_digest"] == release_digest
        installed = ps(
            "distribution-install",
            installer,
            [
                "-ReleaseSet",
                str(release),
                "-InstallRoot",
                str(home),
                "-Apply",
                "-ApproveDigest",
                release_digest,
            ],
        )
        assert installed["outcome"] == "installed" and len(
            installed["artifacts"]
        ) == len(release_document["artifacts"])
        again = ps(
            "distribution-idempotent",
            installer,
            [
                "-ReleaseSet",
                str(release),
                "-InstallRoot",
                str(home),
                "-Apply",
                "-ApproveDigest",
                release_digest,
            ],
        )
        assert again["outcome"] == "already_installed"
        assert sentinel.read_text(encoding="utf-8") == "human data remains\n"
        assert profile.read_text(encoding="utf-8") == "# human edited profile\n"
        generation = home / "cli/generations/0.1.1"
        records = {row["name"]: row for row in installed["artifacts"]}
        for name, row in records.items():
            assert digest(Path(row["installed_path"])) == row["sha256"], name
        assert (
            digest(generation / "Provision-McpRuntime.ps1")
            == records["Provision-McpRuntime.ps1"]["sha256"]
        )
        runtime_args = [
            "-Action",
            "provision",
            "-Root",
            str(home),
            "-RuntimeArchive",
            str(generation / "python-3.13.15-embed-amd64.zip"),
            "-RuntimeSha256",
            records["python-3.13.15-embed-amd64.zip"]["sha256"],
            "-PipWheel",
            str(generation / "pip-26.1.2-py3-none-any.whl"),
            "-PipSha256",
            records["pip-26.1.2-py3-none-any.whl"]["sha256"],
            "-Inputs",
            str(generation / "windows-x64-py313-inputs.tar"),
            "-InputsSha256",
            records["windows-x64-py313-inputs.tar"]["sha256"],
            "-SourceRevision",
            args.mcp_revision,
            "-Version",
            "0.1.1",
        ]
        result = subprocess.run(
            [
                str(shell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(generation / "Provision-McpRuntime.ps1"),
                *runtime_args,
            ],
            env=env,
            cwd=scratch,
            capture_output=True,
            timeout=240,
        )
        if result.returncode:
            raise AssertionError(
                "installed runtime provisioning failed: "
                + result.stderr.decode("utf-8", errors="replace")[-300:]
            )
        runtime = json.loads(result.stdout.decode("utf-8"))
        assert runtime["status"] == "provisioned"
        report.append(
            {
                "case": "installed-runtime-provision",
                "exit_code": 0,
                "expected_exit_code": 0,
                "result": scrub(runtime),
            }
        )
        cli = home / "bin/axiom-cli.exe"
        engine = generation / "axiom.exe"
        native = generation / "axiom-graphd.exe"
        launch_env = {
            "AXIOM_CLI_INSTALL_ROOT": str(home),
            "AXIOM_ENGINE_BIN": str(engine),
            "PATH": os.pathsep.join((str(home / "bin"), path_base)),
        }
        candidate_plan = program(
            "ecosystem-plan",
            [str(cli), "install", "--dry-run", "--from", str(release), "--json"],
            launch_env,
        )
        approval = candidate_plan["details"]["plan_digest"]
        applied = program(
            "ecosystem-apply",
            [
                str(cli),
                "install",
                "--apply",
                "--approve-digest",
                approval,
                "--from",
                str(release),
                "--json",
            ],
            launch_env,
        )
        assert applied["code"] == 0 and len(applied["details"]["components"]) == 3
        native_report = program(
            "installed-daemon-version",
            [str(native), "version", "--json"],
            {"AXIOM_HOME": str(home)},
        )
        assert (
            native_report["build_revision"]
            == json.loads(
                (release / "candidate-lock.json").read_text(encoding="utf-8")
            )["core_revision"]
        )
        source = scratch / "source-repo/src/Widget.cs"
        source.parent.mkdir(parents=True)
        source.write_text(
            'namespace WinDemo; public sealed class Widget { public string Name() => "ok"; }\n',
            encoding="utf-8",
            newline="\n",
        )
        (scratch / "source-repo/WinDemo.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>\n',
            encoding="utf-8",
            newline="\n",
        )
        solution = scratch / "solution.json"
        solution.write_text(
            json.dumps(
                {
                    "id": "windows-demo",
                    "profile": "default",
                    "catalog_host_repo": "windows-repo",
                    "projects": [
                        {
                            "id": "windows-project",
                            "repo_id": "windows-repo",
                            "path": "src",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        config = home / "config"
        config.mkdir(exist_ok=True)
        (config / "bindings.json").write_text(
            json.dumps(
                {"bindings": {"windows-repo": str((scratch / "source-repo").resolve())}}
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        registered = program(
            "real-source-register",
            [
                str(native),
                "solution",
                "register",
                "--config",
                str(solution),
                "--apply",
                "--json",
            ],
            {"AXIOM_HOME": str(home)},
        )
        assert registered["id"] == "windows-demo"
        task_name = "AxiomK305NativeFinal1"
        service_output = subprocess.run(
            [
                str(shell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SERVICE),
                "-InstallRoot",
                str(home),
                "-ScratchRoot",
                str(scratch),
                "-TaskName",
                task_name,
            ],
            env=env,
            cwd=scratch,
            capture_output=True,
            timeout=120,
        )
        if service_output.returncode:
            raise AssertionError(
                "native service lifecycle failed: "
                + service_output.stderr.decode("utf-8", errors="replace")[-300:]
            )
        service = json.loads(service_output.stdout.decode("utf-8"))
        assert service["status"] == "passed" and service["user_data_preserved"]
        report.append(
            {
                "case": "scheduled-task-lifecycle",
                "exit_code": 0,
                "expected_exit_code": 0,
                "result": scrub(service),
            }
        )
        uninstall_plan = program(
            "ecosystem-uninstall-plan",
            [str(cli), "uninstall", "--dry-run", "--json"],
            launch_env,
        )
        uninstall_digest = uninstall_plan["details"]["plan_digest"]
        removed_ecosystem = program(
            "ecosystem-uninstall-apply",
            [
                str(cli),
                "uninstall",
                "--apply",
                "--approve-digest",
                uninstall_digest,
                "--json",
            ],
            launch_env,
        )
        assert removed_ecosystem["code"] == 0
        remove_runtime = subprocess.run(
            [
                str(shell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(generation / "Provision-McpRuntime.ps1"),
                "-Action",
                "remove",
                "-Root",
                str(home),
                "-RuntimeArchive",
                str(generation / "python-3.13.15-embed-amd64.zip"),
                "-RuntimeSha256",
                records["python-3.13.15-embed-amd64.zip"]["sha256"],
            ],
            env=env,
            cwd=scratch,
            capture_output=True,
            timeout=120,
        )
        if remove_runtime.returncode:
            raise AssertionError(
                "installed runtime removal failed: "
                + remove_runtime.stderr.decode("utf-8", errors="replace")[-300:]
            )
        runtime_removal = json.loads(remove_runtime.stdout.decode("utf-8"))
        assert runtime_removal["status"] == "removed"
        report.append(
            {
                "case": "installed-runtime-removal",
                "exit_code": 0,
                "expected_exit_code": 0,
                "result": scrub(runtime_removal),
            }
        )
        outer_plan = ps(
            "distribution-uninstall-plan", uninstaller, ["-InstallRoot", str(home)]
        )
        outer_digest = outer_plan["plan_digest"]
        outer_removed = ps(
            "distribution-uninstall-apply",
            uninstaller,
            ["-InstallRoot", str(home), "-Apply", "-ApproveDigest", outer_digest],
        )
        assert outer_removed["outcome"] == "removed"
        assert not cli.exists() and not engine.exists() and not native.exists()
        assert sentinel.read_text(encoding="utf-8") == "human data remains\n"
        assert profile.read_text(encoding="utf-8") == "# human edited profile\n"
        report.append(
            {
                "case": "preserved-human-content",
                "passed": True,
                "sentinel_sha256": digest(sentinel),
                "profile_sha256": digest(profile),
            }
        )
    finally:
        try:
            if had_path:
                winreg.SetValueEx(registry, "Path", 0, path_kind, before_path)
            else:
                try:
                    winreg.DeleteValue(registry, "Path")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(registry)
        (scratch / "partial-report.json").write_text(
            json.dumps({"cases": report}, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ
    ) as check:
        try:
            after_path, after_kind = winreg.QueryValueEx(check, "Path")
            after_present = True
        except FileNotFoundError:
            after_path, after_kind, after_present = None, None, False
    if after_present != had_path or (
        had_path and (after_path, after_kind) != (before_path, path_kind)
    ):
        raise AssertionError(
            "HKCU Path was not restored to its exact prior value and kind"
        )
    result = {
        "ok": True,
        "lane": "windows-x64",
        "candidate": True,
        "certified": False,
        "cases": report,
        "user_data_preserved": True,
        "user_path_preserved": True,
        "release_set_sha256": digest(release / "release-set.json"),
        "channel_sha256": digest(release / "channel.json"),
    }
    (scratch / "report.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"ok": True, "cases": len(report), "user_data_preserved": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
