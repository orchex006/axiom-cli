#!/usr/bin/env python3
"""Coordinate an unsigned Windows CLI and engine update as one operation."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import uuid


HEX = re.compile(r"[0-9a-f]{64}\Z")
K309_CORE_MANIFEST_SHA = (
    "b33999d07c1a71d3ce00c93620870d08948eec6f0e010f7891d6c630717af7df"
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(path: Path, expected: str) -> None:
    if not HEX.fullmatch(str(expected)) or path.is_symlink() or not path.is_file():
        raise ValueError("missing or unsafe candidate input: " + path.name)
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("linked candidate input ancestor: " + path.name)
    if digest(path) != expected:
        raise ValueError("candidate input changed: " + path.name)


def safe_member(name: str) -> bool:
    relative = PurePosixPath(name)
    return (
        bool(name)
        and not relative.is_absolute()
        and "\\" not in name
        and ":" not in name
        and all(part not in ("", ".", "..") for part in name.split("/"))
    )


def candidate(release: Path, files_path: Path, runtime_input: Path) -> dict:
    if release.is_symlink() or not release.is_dir():
        raise ValueError("candidate release directory is missing or linked")
    files = json.loads(files_path.read_text(encoding="utf-8"))
    task_id = files.get("task_id")
    if task_id not in ("K-306", "K-010") or files.get("lane") != "windows-x64":
        raise ValueError("candidate file manifest identity differs")
    rows = files.get("files", [])
    names: set[str] = set()
    for row in rows:
        name = row["path"]
        if not safe_member(name) or name in names:
            raise ValueError("unsafe or duplicate candidate member")
        names.add(name)
        path = release.joinpath(*name.split("/"))
        require(path, row["sha256"])
        if path.stat().st_size != row["size_bytes"]:
            raise ValueError("candidate member size changed: " + name)
    observed = {
        p.relative_to(release).as_posix() for p in release.rglob("*") if p.is_file()
    }
    if observed != names or len(names) != 60:
        raise ValueError("candidate release membership differs")
    release_set = json.loads((release / "release-set.json").read_text(encoding="utf-8"))
    channel = json.loads((release / "channel.json").read_text(encoding="utf-8"))
    core = json.loads((release / "candidate-manifest.json").read_text(encoding="utf-8"))
    lock = json.loads((release / "candidate-lock.json").read_text(encoding="utf-8"))
    if (
        release_set.get("platform"),
        release_set.get("arch"),
        release_set.get("release_version"),
        core.get("platform"),
        core.get("version"),
        core.get("signing"),
        core.get("publication"),
        channel.get("published"),
        lock.get("task_id"),
    ) != (
        "windows-x64",
        "x86_64",
        "0.1.2",
        "windows-x64",
        "0.1.2",
        "unsigned",
        "not_published",
        False,
        task_id,
    ):
        raise ValueError("candidate platform, version or authority differs")
    if (
        task_id == "K-010"
        and digest(release / "candidate-manifest.json") != K309_CORE_MANIFEST_SHA
    ):
        raise ValueError("K-010 candidate does not carry the reviewed K-309 core")
    if (
        lock["release_set_sha256"] != digest(release / "release-set.json")
        or lock["core_archive_sha256"]
        != digest(release / "axiom-0.1.2-windows-x64.zip")
        or lock["core_archive_sha256"] != core["archive"]["sha256"]
        or lock["core_revision"] != core["source_revision"]
    ):
        raise ValueError("candidate lock differs from exact core and release set")
    artifacts = {row["name"]: row for row in release_set["artifacts"]}
    if len(artifacts) != len(release_set["artifacts"]):
        raise ValueError("duplicate release-set artifact")
    for name, row in artifacts.items():
        require(release / name, row["sha256"])
        if (release / name).stat().st_size != row["size_bytes"]:
            raise ValueError("release-set artifact size changed: " + name)
    binaries = {row["name"]: row for row in core["binaries"]}
    for name in ("axiom.exe", "axiom-graphd.exe"):
        if artifacts[name]["sha256"] != binaries[name]["sha256"]:
            raise ValueError("core binary differs from owner manifest: " + name)
        report = binaries[name]["version_report"]
        if (
            report.get("version") != "0.1.2"
            or report.get("build_revision") != core["source_revision"]
        ):
            raise ValueError("core binary version or revision differs: " + name)
    cli_report = subprocess.run(
        [str(release / "axiom-cli.exe"), "version", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    if (
        cli_report.returncode
        or json.loads(cli_report.stdout)["details"]["cli"]["version"] != "0.1.2"
    ):
        raise ValueError("candidate CLI version report differs")
    graphd = next(
        row for row in channel["components"] if row["component"] == "axiom-graphd"
    )
    mcp = next(row for row in channel["components"] if row["component"] == "axiom-mcp")
    skills = next(row for row in channel["components"] if row["component"] == "skills")
    if (
        graphd["version"] != "0.1.2"
        or graphd["revision"] != core["source_revision"]
        or graphd["artifacts"][0]["sha256"] != artifacts["axiom-graphd.exe"]["sha256"]
        or mcp["version"] != "0.1.1"
        or skills["version"] != "0.1.1"
    ):
        raise ValueError("candidate ecosystem component set differs")
    runtime = json.loads(runtime_input.read_text(encoding="utf-8"))
    if (
        runtime.get("task_id") != "K-304"
        or runtime.get("lane") != "windows-x64"
        or artifacts["windows-x64-py313-inputs.tar"]["sha256"]
        != runtime["mcp_inputs"]["sha256"]
        or artifacts["axiom_mcp-0.1.1-py3-none-any.whl"]["sha256"]
        != runtime["mcp_inputs"]["wheel_sha256"]
    ):
        raise ValueError("candidate runtime input differs")
    return {
        "files_sha256": digest(files_path),
        "release_set_sha256": digest(release / "release-set.json"),
        "channel_sha256": digest(release / "channel.json"),
        "runtime_input_sha256": digest(runtime_input),
        "cli_sha256": artifacts["axiom-cli.exe"]["sha256"],
        "core_sha256": artifacts["axiom-graphd.exe"]["sha256"],
        "core_version": "0.1.2",
        "core_revision": core["source_revision"],
        "mcp_wheel_sha256": mcp["artifacts"][0]["sha256"],
        "skills_revision": skills["revision"],
    }


def kit_manifest(path: Path, args: argparse.Namespace) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("candidate kit manifest missing or linked")
    body = json.loads(path.read_text(encoding="utf-8"))
    files = json.loads(args.files.read_text(encoding="utf-8"))
    if (
        body.get("task_id") not in ("K-306", "K-010")
        or body.get("task_id") != files.get("task_id")
        or body.get("published") is not False
    ):
        raise ValueError("candidate kit identity or authority differs")
    expected = {
        "Update-Distribution.py": Path(__file__),
        "Install-AxiomCli.ps1": args.cli_installer,
        "AxiomCli.Windows.Common.ps1": args.cli_installer.parent
        / "AxiomCli.Windows.Common.ps1",
        "candidate-files.json": args.files,
        "runtime-input.json": args.runtime_input,
    }
    for name, local in expected.items():
        if local.resolve() != (path.parent / name).resolve():
            raise ValueError("candidate kit path differs: " + name)
        require(local, body["files"][name])
    if body["release_set_sha256"] != digest(args.release / "release-set.json"):
        raise ValueError("candidate kit release set changed")
    return digest(path)


def owned_file(path: Path, root: Path) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError(
            "installed owned file is missing or outside root: " + path.name
        )


def installed(root: Path) -> dict:
    state_path = root / "cli/state.json"
    owned_file(state_path, root)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if (
        state.get("document_kind") != "axiom-cli-install-state"
        or state.get("platform") != "windows-x64"
        or state.get("install_root") != str(root)
    ):
        raise ValueError("CLI installed ownership record differs")
    cli = root / "bin/axiom-cli.exe"
    generation = Path(state["generation"])
    if not generation.is_relative_to(root / "cli/generations"):
        raise ValueError("CLI generation escapes its install root")
    owned_file(cli, root)
    owned_file(generation / "axiom-cli.exe", root)
    cli_row = next(row for row in state["artifacts"] if row["name"] == "axiom-cli.exe")
    require(cli, cli_row["sha256"])
    require(generation / "axiom-cli.exe", cli_row["sha256"])
    engine = root / "installs/ecosystem/current"
    runtime = root / "mcp-runtime/current.json"
    skills = root / "installs/ecosystem/skills/current"
    for path in (engine, runtime, skills):
        owned_file(path, root)
    active = json.loads(engine.read_text(encoding="utf-8"))
    rows = {row["component"]: row for row in active["activated"]}
    if set(rows) != {"axiom-graphd", "axiom-mcp"}:
        raise ValueError("active ecosystem component set differs")
    daemon = Path(rows["axiom-graphd"]["destination"])
    owned_file(daemon, root)
    require(daemon, rows["axiom-graphd"]["sha256"])
    mcp = json.loads(runtime.read_text(encoding="utf-8"))
    if mcp.get("owner_wheel_sha256") != rows["axiom-mcp"]["sha256"]:
        raise ValueError("active MCP wheel and engine pointer disagree")
    daemon_report = subprocess.run(
        [str(daemon), "version", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    if daemon_report.returncode:
        raise ValueError("installed daemon version probe failed")
    version = json.loads(daemon_report.stdout)
    if version.get("version") != rows["axiom-graphd"]["version"] or not re.fullmatch(
        r"[0-9a-f]{40}", version.get("build_revision", "")
    ):
        raise ValueError("installed daemon version differs from engine pointer")
    return {
        "cli_sha256": digest(cli),
        "cli_state_sha256": digest(state_path),
        "cli_generation": str(generation),
        "cli_version": state["release_version"],
        "core_version": rows["axiom-graphd"]["version"],
        "core_revision": version["build_revision"],
        "core_sha256": rows["axiom-graphd"]["sha256"],
        "engine_pointer_sha256": digest(engine),
        "runtime_pointer_sha256": digest(runtime),
        "skills_pointer_sha256": digest(skills),
        "mcp_wheel_sha256": mcp["owner_wheel_sha256"],
    }


def compatible(checked: dict, before: dict) -> None:
    old = tuple(int(part) for part in before["core_version"].split("."))
    new = tuple(int(part) for part in checked["core_version"].split("."))
    if (
        new <= old
        or new[0] != old[0]
        or checked["core_sha256"] == before["core_sha256"]
    ):
        raise ValueError("candidate core is not a newer compatible generation")
    if checked["cli_sha256"] == before["cli_sha256"]:
        raise ValueError("candidate does not self-update the CLI")


def seal(checked: dict, before: dict, kit_sha: str) -> str:
    body = {
        "schema_version": 1,
        "operation": "windows-distribution-update",
        "candidate": checked,
        "before": before,
        "kit_manifest_sha256": kit_sha,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def call(argv: list[str], env: dict[str, str]) -> dict:
    result = subprocess.run(
        argv,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    try:
        body = json.loads(result.stdout)
    except json.JSONDecodeError:
        body = {"stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]}
    if result.returncode:
        raise ValueError(
            f"{Path(argv[0]).name} exited {result.returncode}: {json.dumps(body)[-1000:]}"
        )
    return body


def environment(root: Path) -> dict[str, str]:
    pointer = json.loads(
        (root / "mcp-runtime/current.json").read_text(encoding="utf-8")
    )
    generation = pointer["generation"]
    if not re.fullmatch(r"[0-9a-f]{24}", generation):
        raise ValueError("active MCP runtime generation is invalid")
    scripts = root / "mcp-runtime/versions" / generation / "venv/Scripts"
    if scripts.is_symlink() or not scripts.is_dir():
        raise ValueError("active MCP runtime Scripts directory is missing")
    env = os.environ.copy()
    env.update(
        AXIOM_HOME=str(root),
        AXIOM_CLI_INSTALL_ROOT=str(root),
        AXIOM_CLI_COMPOSITE_UPDATE="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    # A Python child launched from PowerShell 7 can inherit its module path.
    # Windows PowerShell 5.1 must load its own Utility module for Get-FileHash.
    windows = Path(env.get("WINDIR", r"C:\Windows"))
    env["PSModulePath"] = os.pathsep.join(
        [
            str(windows / "System32/WindowsPowerShell/v1.0/Modules"),
            str(
                Path(env.get("ProgramFiles", r"C:\Program Files"))
                / "WindowsPowerShell/Modules"
            ),
        ]
    )
    return env


def atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".k306-", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def update_lock(root: Path):
    path = root / "distribution-update.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def restore_cli(root: Path, before: dict, state: bytes, manifest: bytes) -> None:
    source = Path(before["cli_generation"]) / "axiom-cli.exe"
    require(source, before["cli_sha256"])
    entry = root / "bin/axiom-cli.exe"
    if digest(entry) != before["cli_sha256"]:
        backup = (
            root / "cli/rollback" / ("k306-superseded-" + uuid.uuid4().hex + ".exe")
        )
        if backup.exists():
            raise ValueError("CLI rollback backup already exists")
        backup.parent.mkdir(parents=True, exist_ok=True)
        os.replace(entry, backup)
        atomic_bytes(entry, source.read_bytes())
    atomic_bytes(root / "cli/state.json", state)
    atomic_bytes(root / "install-manifest.json", manifest)
    if digest(root / "cli/state.json") != before["cli_state_sha256"]:
        raise ValueError("restored CLI state differs")


def engine_rollback(release: Path, env: dict[str, str], transaction: str) -> dict:
    return call(
        [
            str(release / "axiom.exe"),
            "update",
            "rollback",
            "--transaction",
            transaction,
            "--json",
        ],
        env,
    )


def cli_install(args: argparse.Namespace, env: dict[str, str]) -> dict:
    base = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(args.cli_installer),
        "-ReleaseSet",
        str(args.release / "release-set.json"),
        "-InstallRoot",
        str(args.root),
        "-Json",
    ]
    plan = call(base, env)
    return call(base + ["-Apply", "-ApproveDigest", plan["plan_digest"]], env)


def apply(
    args: argparse.Namespace, checked: dict, before: dict, approved: str, kit_sha: str
) -> dict:
    expected = seal(checked, before, kit_sha)
    if approved != expected:
        raise ValueError("stale or incorrect approval digest")
    root, release = args.root, args.release
    env = environment(root)
    pending = root / "distribution-update-pending.json"
    receipt = root / "distribution-update.json"
    with update_lock(root):
        if installed(root) != before or pending.exists() or receipt.exists():
            raise ValueError("installed generation changed or an update already exists")
        state = (root / "cli/state.json").read_bytes()
        manifest = (root / "install-manifest.json").read_bytes()
        atomic_bytes(
            pending,
            json.dumps(
                {"before": before, "candidate": checked}, sort_keys=True
            ).encode()
            + b"\n",
        )
        transaction = None
        events = []
        try:
            if args.fail_at == "download":
                raise ValueError("injected artifact acquisition failure")
            if args.fail_at == "stage":
                raise ValueError("injected staging failure")
            cli = str(release / "axiom-cli.exe")
            plan = call(
                [cli, "install", "--from", str(release), "--dry-run", "--json"], env
            )
            result = call(
                [
                    cli,
                    "install",
                    "--from",
                    str(release),
                    "--apply",
                    "--approve-digest",
                    plan["details"]["plan_digest"],
                    "--json",
                ],
                env,
            )
            events.append({"phase": "engine-update", "result": result})
            transaction = result.get("details", {}).get("engine_transaction")
            if not transaction:
                raise ValueError("engine update returned no rollback transaction")
            if args.fail_at in ("activation", "service-restart"):
                raise ValueError(
                    "injected " + args.fail_at + " failure after engine activation"
                )
            events.append(
                {"phase": "cli-self-update", "result": cli_install(args, env)}
            )
            after = installed(root)
            if (
                after["engine_pointer_sha256"] == before["engine_pointer_sha256"]
                or after["cli_sha256"] == before["cli_sha256"]
            ):
                raise ValueError("update did not activate both engine and CLI")
            if args.fail_at == "post-entrypoint":
                raise ValueError("injected post-entrypoint health failure")
            record = {
                "schema_version": 1,
                "candidate": checked,
                "before": before,
                "after": after,
                "engine_transaction": transaction,
                "approval_digest": expected,
                "state_before_hex": state.hex(),
                "manifest_before_hex": manifest.hex(),
            }
            atomic_bytes(receipt, json.dumps(record, sort_keys=True).encode() + b"\n")
            pending.unlink()
            return {
                "status": "updated",
                "before": before,
                "after": after,
                "plan_digest": expected,
                "engine_transaction": transaction,
                "events": events,
                "certified": False,
            }
        except Exception as error:
            failures = []
            if transaction:
                try:
                    engine_rollback(release, env, transaction)
                except Exception as rollback_error:
                    failures.append("engine: " + str(rollback_error))
            try:
                if digest(root / "bin/axiom-cli.exe") != before["cli_sha256"]:
                    restore_cli(root, before, state, manifest)
            except Exception as rollback_error:
                failures.append("cli: " + str(rollback_error))
            try:
                if installed(root) != before:
                    failures.append("installed state differs from approved A")
            except Exception as rollback_error:
                failures.append("state: " + str(rollback_error))
            if failures:
                raise ValueError(
                    str(error) + "; rollback incomplete: " + "; ".join(failures)
                ) from error
            pending.unlink()
            raise


def rollback(args: argparse.Namespace) -> dict:
    root = args.root
    receipt = root / "distribution-update.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise ValueError("no owned update receipt")
    record = json.loads(receipt.read_text(encoding="utf-8"))
    before, after = record["before"], record["after"]
    env = environment(root)
    with update_lock(root):
        # K-010 upgrades a 0.1.1 core that cannot run the new public Windows
        # task action. A service installed after activation is absent from the
        # graphd update journal; letting that journal roll back would leave the
        # B task running while the active pointer names A. Require its owner
        # API to remove the task before the distribution rollback begins.
        task_id = json.loads(args.files.read_text(encoding="utf-8")).get("task_id")
        service_state = root / "installs/ecosystem/state/service-v1.json"
        if task_id == "K-010" and (
            service_state.exists() or service_state.is_symlink()
        ):
            raise ValueError(
                "post-update Windows service must be removed with installed "
                "axiom service uninstall before rollback to the 0.1.1 core"
            )
        current = installed(root)
        if current == after:
            (root / "cli/rollback").mkdir(parents=True, exist_ok=True)
            require(
                Path(before["cli_generation"]) / "axiom-cli.exe", before["cli_sha256"]
            )
            result = engine_rollback(args.release, env, record["engine_transaction"])
        elif (
            current["engine_pointer_sha256"] == before["engine_pointer_sha256"]
            and current["core_sha256"] == before["core_sha256"]
            and current["runtime_pointer_sha256"] == before["runtime_pointer_sha256"]
            and current["skills_pointer_sha256"] == before["skills_pointer_sha256"]
            and current["cli_sha256"] == after["cli_sha256"]
            and current["cli_state_sha256"] == after["cli_state_sha256"]
        ):
            # Resume an interrupted rollback only with exact recorded A engine
            # and B CLI bytes. Never guess which generation owns a mixed state.
            result = {"status": "engine_already_rolled_back"}
        else:
            raise ValueError("installed generations differ from update receipt")
        restore_cli(
            root,
            before,
            bytes.fromhex(record["state_before_hex"]),
            bytes.fromhex(record["manifest_before_hex"]),
        )
        restored = installed(root)
        if restored != before:
            raise ValueError("rollback did not restore approved A")
        receipt.unlink()
        return {
            "status": "rolled_back",
            "before": after,
            "after": restored,
            "engine": result,
            "certified": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "plan", "apply", "rollback"))
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--runtime-input", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cli-installer", type=Path, required=True)
    parser.add_argument("--kit-manifest", type=Path, required=True)
    parser.add_argument("--to", default="")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--approve-digest", default="")
    parser.add_argument(
        "--fail-at",
        default=os.environ.get("AXIOM_CLI_COMPOSITE_FAIL_AT", ""),
        choices=(
            "",
            "download",
            "stage",
            "activation",
            "service-restart",
            "post-entrypoint",
        ),
    )
    args = parser.parse_args()
    try:
        if not args.root.is_absolute() or not args.home.is_absolute():
            raise ValueError("per-user candidate roots must be absolute")
        kit_sha = kit_manifest(args.kit_manifest, args)
        checked = candidate(args.release, args.files, args.runtime_input)
        if args.action == "rollback":
            print(json.dumps(rollback(args), sort_keys=True))
            return 0
        before = installed(args.root)
        if (
            args.action == "check"
            and checked["core_sha256"] == before["core_sha256"]
            and checked["cli_sha256"] == before["cli_sha256"]
        ):
            print(
                json.dumps(
                    {"status": "up_to_date", "installed": before, "certified": False},
                    sort_keys=True,
                )
            )
            return 0
        compatible(checked, before)
        if args.to and args.to != checked["core_version"]:
            raise ValueError("requested version differs from candidate")
        plan_digest = seal(checked, before, kit_sha)
        plan = {
            "status": "planned",
            "plan_digest": plan_digest,
            "before": before,
            "candidate": checked,
            "kit_manifest_sha256": kit_sha,
            "certified": False,
        }
        if args.action in ("check", "plan"):
            if args.action == "plan" and args.out:
                atomic_bytes(
                    args.out, json.dumps(plan, sort_keys=True).encode() + b"\n"
                )
            print(json.dumps(plan, sort_keys=True))
            return 0
        if (
            not args.plan_file
            or args.plan_file.is_symlink()
            or not args.plan_file.is_file()
            or json.loads(args.plan_file.read_text(encoding="utf-8")) != plan
        ):
            raise ValueError(
                "approved plan differs from current candidate or installation"
            )
        print(
            json.dumps(
                apply(args, checked, before, args.approve_digest, kit_sha),
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as error:
        print(
            json.dumps(
                {"status": "refused", "reason": str(error), "certified": False},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
