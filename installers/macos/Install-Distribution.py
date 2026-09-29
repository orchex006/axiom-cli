#!/usr/bin/env python3
"""Compose the owned Mac candidate install, service and data-preserving removal."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(path: Path, expected: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
        raise ValueError("invalid declared digest: " + str(path))
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("linked candidate input ancestor: " + str(path))
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise ValueError("missing or changed candidate input: " + str(path))


def inputs(release: Path) -> dict:
    for name in ("release-set.json", "channel.json", "runtime/manifest.json"):
        path = release / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("candidate manifest missing: " + name)
    entry = json.loads((release / "release-set.json").read_text())
    channel = json.loads((release / "channel.json").read_text())
    runtime = json.loads((release / "runtime/manifest.json").read_text())
    if (
        entry.get("platform"),
        entry.get("arch"),
        entry.get("signing"),
        entry.get("notarization"),
    ) != ("macos-x64", "x86_64", "unsigned", "not_notarized"):
        raise ValueError("release set platform or signing declaration is incompatible")
    if channel.get("published") is not False or runtime.get("published") is not False:
        raise ValueError("candidate cannot claim publication")
    if runtime.get("python_version") != "3.13.15" or runtime.get("lane") != "macos-x64":
        raise ValueError("runtime version or lane is incompatible")
    for row in entry.get("artifacts", []):
        name = row.get("name", "")
        if name not in ("axiom-cli", "axiom", "axiom-graphd"):
            raise ValueError("unexpected core artifact")
        verify(release / name, row["sha256"])
    if [row["name"] for row in entry["artifacts"]] != [
        "axiom-cli",
        "axiom",
        "axiom-graphd",
    ]:
        raise ValueError("core artifact set incomplete")
    for name, expected in runtime.get("files", {}).items():
        if name not in (
            "python.tar.gz",
            "wheelhouse.tar.gz",
            "axiom_mcp-0.1.0-py3-none-any.whl",
            "requirements.txt",
            "provision.py",
            "install.py",
            "bootstrap.sh",
            "entrypoints.sh",
        ):
            raise ValueError("unexpected runtime artifact")
        verify(release / "runtime" / name, expected)
    if len(runtime["files"]) != 8:
        raise ValueError("runtime artifact set incomplete")
    wheel = release / "axiom_mcp-0.1.0-py3-none-any.whl"
    verify(wheel, runtime["files"][wheel.name])
    skills = release / "skills-manifest.json"
    if skills.is_symlink() or not skills.is_file():
        raise ValueError("owner skills manifest missing")
    manifest = json.loads(skills.read_text())
    if (
        manifest.get("component") != "axiom-skills"
        or manifest.get("spec_revision") is None
    ):
        raise ValueError("owner skills manifest incompatible")
    for row in manifest.get("files", []):
        path = Path(row.get("path", ""))
        if path.is_absolute() or ".." in path.parts or not str(path):
            raise ValueError("unsafe owner skills path")
        verify(release / path, row["sha256"])
        if (release / path).stat().st_size != row["bytes"]:
            raise ValueError("owner skills size mismatch")
    if not manifest["files"]:
        raise ValueError("owner skills are empty")
    declared = {row.get("component"): row for row in channel.get("components", [])}
    if len(channel.get("components", [])) != 3 or set(declared) != {
        "axiom-graphd",
        "axiom-mcp",
        "skills",
    }:
        raise ValueError("candidate channel has an incomplete ecosystem")
    if (
        (
            declared["axiom-graphd"].get("version"),
            declared["axiom-graphd"].get("revision"),
        )
        != (entry["artifacts"][2]["version"], entry["artifacts"][2]["revision"])
        or entry["artifacts"][1]["version"] != entry["artifacts"][2]["version"]
        or entry["artifacts"][1]["revision"] != entry["artifacts"][2]["revision"]
        or (declared["axiom-mcp"].get("version"), declared["axiom-mcp"].get("revision"))
        != (runtime["mcp_version"], runtime["mcp_revision"])
        or declared["skills"].get("version") != manifest.get("component_version")
        or manifest.get("spec_revision") is None
    ):
        raise ValueError(
            "candidate channel, core, MCP or skills identity is incompatible"
        )
    return {
        "entry": entry,
        "channel": channel,
        "runtime": runtime,
        "skills_manifest_sha256": digest(skills),
    }


def command(argv: list[str], env: dict[str, str], *, accept: bool = False) -> dict:
    result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    if result.returncode and not accept:
        raise ValueError(
            f"{Path(argv[0]).name} exited {result.returncode}: {(result.stderr or result.stdout)[-500:]}"
        )
    try:
        body = json.loads(result.stdout)
    except json.JSONDecodeError:
        body = {"stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    return {"exit_code": result.returncode, "body": body}


def approval(body: dict) -> str:
    value = body.get("plan_digest") or body.get("details", {}).get("plan_digest")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
        raise ValueError("installer plan has no digest")
    return value


def plan_digest(release: Path, home: Path, verb: str, checked: dict) -> str:
    value = {
        "verb": verb,
        "release": str(release),
        "home": str(home),
        "release_set_sha256": digest(release / "release-set.json"),
        "channel_sha256": digest(release / "channel.json"),
        "runtime_manifest_sha256": digest(release / "runtime/manifest.json"),
        "skills_manifest_sha256": checked["skills_manifest_sha256"],
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def installed_update_state(home: Path, root: Path) -> dict:
    """Bind an update approval to the exact owned entrypoints and engine generation."""
    state = root / "entrypoints/current.tsv"
    if state.is_symlink() or not state.is_file():
        raise ValueError("owned entrypoint record missing")
    rows = state.read_text().splitlines()
    if len(rows) != 8 or rows[0] != "axiom-cli-entrypoints-v1":
        raise ValueError("owned entrypoint record incompatible")
    if not re.fullmatch(r"[0-9a-f]{64}", rows[1]):
        raise ValueError("owned release digest invalid")
    old = root / "entrypoints/versions" / rows[1]
    binaries = (home / ".local/bin/axiom-cli", home / ".local/bin/axiom")
    for current, retained, expected in zip(
        binaries, (old / "axiom-cli", old / "axiom"), rows[5:7]
    ):
        verify(current, expected)
        verify(retained, expected)
    pointer = root / "installs/ecosystem/current"
    runtime = root / "mcp-runtime/current.json"
    service = root / "installs/ecosystem/state/service-v1.json"
    for path in (pointer, runtime, service):
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                "installed engine, runtime or owned service missing: " + str(path)
            )
    return {
        "entrypoint_record_sha256": digest(state),
        "engine_pointer_sha256": digest(pointer),
        "runtime_pointer_sha256": digest(runtime),
        "service_record_sha256": digest(service),
        "release_set_sha256": rows[1],
        "cli_sha256": rows[5],
        "cli_version": rows[2],
        "engine_cli_sha256": rows[6],
        "core_version": rows[3],
        "core_revision": rows[4],
        "profile": rows[7],
    }


def update_digest(release: Path, home: Path, checked: dict, before: dict) -> str:
    value = {
        "candidate": plan_digest(release, home, "update", checked),
        "installed": before,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_new_core(checked: dict, before: dict) -> None:
    candidate_core = checked["entry"]["artifacts"][2]
    if (
        candidate_core["version"] == before["core_version"]
        or candidate_core["revision"] == before["core_revision"]
    ):
        raise ValueError("candidate core version and revision must advance together")


def rollback_receipt(release: Path, root: Path, installed: dict) -> dict:
    path = root / "distribution-update.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("no owned distribution update receipt to roll back")
    value = json.loads(path.read_text())
    if (
        value.get("schema_version") != 1
        or value.get("release_set_sha256") != digest(release / "release-set.json")
        or not re.fullmatch(r"[a-zA-Z0-9-]+", str(value.get("engine_transaction", "")))
        or not isinstance(value.get("before"), dict)
        or not isinstance(value.get("after"), dict)
        or set(value["before"]) != set(installed)
        or set(value["after"]) != set(installed)
    ):
        raise ValueError("distribution update receipt is incompatible")
    after = value.get("after", {})
    if any(
        installed.get(key) != expected
        for key, expected in after.items()
        if key != "service_record_sha256"
    ):
        raise ValueError("installed generation changed since the update receipt")
    return value


def rollback_digest(release: Path, root: Path, installed: dict) -> str:
    receipt = rollback_receipt(release, root, installed)
    value = {
        "action": "rollback",
        "receipt_sha256": digest(root / "distribution-update.json"),
        "release_set_sha256": receipt["release_set_sha256"],
        "installed": installed,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def atomic_copy(source: Path, target: Path, expected: str) -> None:
    verify(source, expected)
    descriptor, name = tempfile.mkstemp(prefix=".axiom-update-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, 0o755)
        verify(Path(name), expected)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_text(target: Path, value: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".axiom-record-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, 0o600)
        os.replace(name, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def update_lock(root: Path):
    lock = root / "distribution-update.lock"
    if lock.is_symlink() or (lock.exists() and not lock.is_file()):
        raise ValueError("distribution update lock is not an owned file")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "another distribution update or recovery holds the lock"
            ) from error
        yield
    finally:
        os.close(descriptor)


def pending_update_path(root: Path) -> Path:
    return root / "distribution-update-pending.json"


def refuse_pending_update(root: Path) -> None:
    pending = pending_update_path(root)
    if pending.exists() or pending.is_symlink():
        raise ValueError("distribution update recovery required: " + str(pending))


def pending_recovery(release: Path, root: Path) -> dict:
    path = pending_update_path(root)
    if path.is_symlink() or not path.is_file():
        raise ValueError("no owned distribution recovery intent")
    value = json.loads(path.read_text())
    if (
        value.get("schema_version") != 1
        or value.get("action") not in ("update", "rollback")
        or value.get("release_set_sha256") != digest(release / "release-set.json")
    ):
        raise ValueError("distribution recovery intent does not bind this candidate")
    before = value.get("before") if value["action"] == "update" else value.get("target")
    required = {
        "entrypoint_record_sha256", "engine_pointer_sha256", "runtime_pointer_sha256",
        "service_record_sha256", "release_set_sha256", "cli_sha256",
        "cli_version", "engine_cli_sha256", "core_version", "core_revision",
        "profile",
    }
    if not isinstance(before, dict) or set(before) != required or not all(
        re.fullmatch(r"[0-9a-f]{64}", str(before.get(key, "")))
        for key in (
            "release_set_sha256", "entrypoint_record_sha256",
            "engine_pointer_sha256", "runtime_pointer_sha256",
            "cli_sha256", "engine_cli_sha256",
        )
    ):
        raise ValueError("distribution recovery target is incomplete")
    if value["action"] == "update":
        journals = value.get("engine_journals_before")
        if (
            not isinstance(journals, list)
            or not all(isinstance(name, str) for name in journals)
            or len(journals) != len(set(journals))
        ):
            raise ValueError("distribution recovery journal baseline is missing")
    if value["action"] == "rollback" and not re.fullmatch(
        r"[a-zA-Z0-9-]+", str(value.get("engine_transaction", ""))
    ):
        raise ValueError("distribution recovery transaction is invalid")
    return value


def recovery_digest(release: Path, root: Path, pending: dict) -> str:
    value = {
        "action": "recover",
        "pending_sha256": digest(pending_update_path(root)),
        "release_set_sha256": pending["release_set_sha256"],
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def recovery_transaction(root: Path, pending: dict, checked: dict) -> str | None:
    if pending["action"] == "rollback":
        return pending["engine_transaction"]
    journal_dir = root / "installs/ecosystem/journal"
    old = set(pending["engine_journals_before"])
    new = {
        name for name in engine_journal_names(journal_dir).difference(old)
        if name.startswith("ecosystem-update-") and name.endswith(".json")
    }
    if not new:
        return None
    if len(new) != 1:
        raise ValueError("distribution recovery found ambiguous engine journals")
    name = next(iter(new))
    if not re.fullmatch(r"ecosystem-update-[a-zA-Z0-9-]+\.json", name):
        raise ValueError("distribution recovery found a foreign engine journal")
    path = journal_dir / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("distribution recovery journal is unsafe")
    journal = json.loads(path.read_text())
    transaction = name[len("ecosystem-update-") : -len(".json")]
    before = pending["before"]
    candidate = journal.get("candidate")
    if (
        journal.get("kind") != "ecosystem-update-journal"
        or journal.get("schema_version") != 1
        or journal.get("transaction_id") != transaction
        or journal.get("previous_pointer_sha256") != before["engine_pointer_sha256"]
        or journal.get("state") not in ("prepared", "activated", "finalized", "rolled-back", "restored-after-service-failure")
        or not isinstance(candidate, dict)
        or not isinstance(candidate.get("core_artifacts"), list)
        or not candidate["core_artifacts"]
        or candidate["core_artifacts"][0].get("sha256")
        != checked["entry"]["artifacts"][2]["sha256"]
    ):
        raise ValueError("distribution recovery journal does not bind A and B")
    return transaction


def run_recover(
    release: Path, home: Path, root: Path, env: dict, checked: dict, pending: dict
) -> dict:
    before = pending["before"] if pending["action"] == "update" else pending["target"]
    receipt = root / "distribution-update.json"
    if pending["action"] == "rollback":
        if (
            receipt.is_symlink()
            or not receipt.is_file()
            or digest(receipt) != pending.get("receipt_sha256")
        ):
            raise ValueError("distribution recovery receipt changed")
    elif receipt.exists() or receipt.is_symlink():
        raise ValueError("distribution recovery found an unexpected update receipt")
    retained = root / "entrypoints/versions" / before["release_set_sha256"]
    verify(retained / "axiom-cli", before["cli_sha256"])
    verify(retained / "axiom", before["engine_cli_sha256"])
    record = root / "entrypoints/current.tsv"
    if record.is_symlink() or not record.is_file():
        raise ValueError("distribution recovery entrypoint record is unsafe")
    if digest(record) != before["entrypoint_record_sha256"]:
        rows = record.read_text().splitlines()
        if len(rows) != 8 or rows[1] != pending["release_set_sha256"]:
            raise ValueError("distribution recovery entrypoint record changed")
    for name, old, new in zip(
        ("axiom-cli", "axiom"),
        (before["cli_sha256"], before["engine_cli_sha256"]),
        checked["entry"]["artifacts"][:2],
    ):
        current = home / ".local/bin" / name
        if current.is_symlink() or not current.is_file() or digest(current) not in (old, new["sha256"]):
            raise ValueError("distribution recovery entrypoint changed: " + name)
    runtime_dir = root / "mcp-runtime"
    runtime_pointer = runtime_dir / "current.json"
    if runtime_pointer.is_symlink() or not runtime_pointer.is_file():
        raise ValueError("distribution recovery runtime pointer is unsafe")
    runtime_changed = digest(runtime_pointer) != before["runtime_pointer_sha256"]
    provision = release / "runtime/provision.py"
    if runtime_changed:
        verify(runtime_dir / "previous.json", before["runtime_pointer_sha256"])
        planned = command(
            [sys.executable, str(provision), "rollback", "--root", str(runtime_dir), "--dry-run"],
            env,
        )
        if planned["body"].get("status") != "rollback_planned":
            raise ValueError("distribution recovery retained runtime preflight failed")
    transaction = recovery_transaction(root, pending, checked)
    engine_pointer = root / "installs/ecosystem/current"
    if transaction is None:
        verify(engine_pointer, before["engine_pointer_sha256"])
    else:
        command(
            [str(release / "axiom"), "update", "rollback", "--transaction", transaction, "--json"],
            env,
        )
    if runtime_changed:
        command([sys.executable, str(provision), "rollback", "--root", str(runtime_dir)], env)
    restore_entrypoints(home, root, before, checked["entry"])
    restored = installed_update_state(home, root)
    if any(restored[key] != before[key] for key in before if key != "service_record_sha256"):
        raise ValueError("distribution recovery did not restore the approved A generation")
    if pending["action"] == "rollback":
        receipt.unlink()
    pending_update_path(root).unlink()
    return {"status": "recovered", "engine_transaction": transaction, "after": restored}


def engine_journal_names(directory: Path) -> set[str]:
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValueError("engine update journal directory is unsafe")
    return {path.name for path in directory.iterdir()} if directory.is_dir() else set()


def activate_entrypoints(release: Path, home: Path, root: Path, before: dict) -> dict:
    entry = json.loads((release / "release-set.json").read_text())
    rows = entry["artifacts"]
    set_sha = digest(release / "release-set.json")
    if set_sha == before["release_set_sha256"]:
        raise ValueError("candidate release set is already active")
    state = root / "entrypoints/current.tsv"
    if digest(state) != before["entrypoint_record_sha256"]:
        raise ValueError("installed generation changed since update approval")
    for name, expected in (
        ("axiom-cli", before["cli_sha256"]),
        ("axiom", before["engine_cli_sha256"]),
    ):
        verify(home / ".local/bin" / name, expected)
    versions = root / "entrypoints/versions"
    target = versions / set_sha
    if target.is_symlink():
        raise ValueError("candidate entrypoint generation is linked")
    if target.exists():
        if not target.is_dir() or {path.name for path in target.iterdir()} != {
            "axiom-cli",
            "axiom",
        }:
            raise ValueError("retained candidate entrypoint generation changed")
        for name, row in zip(("axiom-cli", "axiom"), rows[:2]):
            verify(target / name, row["sha256"])
    else:
        target.mkdir()
        for name, row in zip(("axiom-cli", "axiom"), rows[:2]):
            atomic_copy(release / name, target / name, row["sha256"])
    for name, row, old_sha in zip(
        ("axiom-cli", "axiom"),
        rows[:2],
        (before["cli_sha256"], before["engine_cli_sha256"]),
    ):
        destination = home / ".local/bin" / name
        verify(destination, old_sha)
        atomic_copy(target / name, destination, row["sha256"])
    record = "\n".join(
        (
            "axiom-cli-entrypoints-v1",
            set_sha,
            rows[0]["version"],
            rows[1]["version"],
            rows[1]["revision"],
            rows[0]["sha256"],
            rows[1]["sha256"],
            before["profile"],
            "",
        )
    )
    atomic_text(root / "entrypoints/current.tsv", record)
    return {"release_set_sha256": set_sha, "cli_sha256": rows[0]["sha256"]}


def restore_entrypoints(home: Path, root: Path, before: dict, candidate: dict) -> None:
    retained = root / "entrypoints/versions" / before["release_set_sha256"]
    for name, expected, new in zip(
        ("axiom-cli", "axiom"),
        (before["cli_sha256"], before["engine_cli_sha256"]),
        candidate["artifacts"][:2],
    ):
        current = home / ".local/bin" / name
        if current.is_symlink() or not current.is_file():
            raise ValueError("entrypoint missing during rollback: " + name)
        if digest(current) not in (expected, new["sha256"]):
            raise ValueError("human-edited entrypoint during rollback: " + name)
        atomic_copy(retained / name, current, expected)
    record = "\n".join(
        (
            "axiom-cli-entrypoints-v1",
            before["release_set_sha256"],
            before["cli_version"],
            before["core_version"],
            before["core_revision"],
            before["cli_sha256"],
            before["engine_cli_sha256"],
            before["profile"],
            "",
        )
    )
    atomic_text(root / "entrypoints/current.tsv", record)


def run_update(
    release: Path, home: Path, root: Path, env: dict, checked: dict, before: dict
) -> dict:
    """Coordinate the engine's own update with the distribution-owned entrypoint move."""
    require_new_core(checked, before)
    runtime_dir = root / "mcp-runtime"
    runtime = checked["runtime"]
    provision = release / "runtime/provision.py"
    transaction = None
    events = []
    candidate_dir = root / "entrypoints/versions" / digest(release / "release-set.json")
    candidate_dir_preexisting = candidate_dir.exists() or candidate_dir.is_symlink()
    pending = pending_update_path(root)
    pending_written = False
    receipt_written = False
    journal_names: list[str] = []
    engine_journal = root / "installs/ecosystem/journal"
    try:
        refuse_pending_update(root)
        if (root / "distribution-update.json").exists():
            raise ValueError("previous distribution update needs rollback or review")
        command(
            [
                "/bin/sh",
                str(release / "runtime/entrypoints.sh"),
                "uninstall",
                "--dry-run",
            ],
            env,
        )
        command(
            [sys.executable, str(provision), "status", "--root", str(runtime_dir)], env
        )
        journal_names = sorted(engine_journal_names(engine_journal))
        atomic_text(
            pending,
            json.dumps(
                {
                    "schema_version": 1,
                    "action": "update",
                    "release_set_sha256": digest(release / "release-set.json"),
                    "before": before,
                    "engine_journals_before": journal_names,
                },
                sort_keys=True,
            )
            + "\n",
        )
        pending_written = True
        if os.environ.get("AXIOM_K106_FAIL_AT") == "download":
            raise ValueError("injected local artifact acquisition failure")
        result = command(
            [
                sys.executable,
                str(provision),
                "provision",
                "--root",
                str(runtime_dir),
                "--version",
                runtime["mcp_version"],
                "--source-revision",
                runtime["mcp_revision"],
                *[
                    part
                    for key, name in (
                        ("runtime", "python.tar.gz"),
                        ("wheelhouse", "wheelhouse.tar.gz"),
                        ("wheel", "axiom_mcp-0.1.0-py3-none-any.whl"),
                        ("lock", "requirements.txt"),
                    )
                    for part in (
                        "--" + key,
                        str(release / "runtime" / name),
                        "--" + key + "-sha256",
                        runtime["files"][name],
                    )
                ],
            ],
            env,
        )
        events.append({"phase": "runtime-stage", **result})
        if os.environ.get("AXIOM_K106_FAIL_AT") == "stage":
            raise ValueError("injected stage failure")
        candidate_cli = release / "axiom-cli"
        composite_env = dict(env, AXIOM_CLI_COMPOSITE_UPDATE="1")
        planned = command(
            [
                str(candidate_cli),
                "install",
                "--from",
                str(release),
                "--dry-run",
                "--json",
            ],
            composite_env,
        )
        applied = command(
            [
                str(candidate_cli),
                "install",
                "--from",
                str(release),
                "--apply",
                "--approve-digest",
                approval(planned["body"]),
                "--json",
            ],
            composite_env,
        )
        events.append({"phase": "engine-update", **applied})
        if os.environ.get("AXIOM_K106_CRASH_AT") == "engine_report":
            os._exit(97)
        transaction = applied["body"].get("details", {}).get("engine_transaction")
        if not transaction:
            raise ValueError("engine update returned no rollback transaction")
        if os.environ.get("AXIOM_K106_FAIL_AT") in ("activation", "service_restart"):
            raise ValueError("injected failure after engine activation")
        entry = activate_entrypoints(release, home, root, before)
        events.append({"phase": "entrypoints-update", "body": entry, "exit_code": 0})
        after = installed_update_state(home, root)
        if after["engine_pointer_sha256"] == before["engine_pointer_sha256"]:
            raise ValueError("engine did not activate a new generation")
        if os.environ.get("AXIOM_K106_FAIL_AT") == "post_activation":
            raise ValueError("injected post-activation failure")
        receipt = {
            "schema_version": 1,
            "release_set_sha256": entry["release_set_sha256"],
            "engine_transaction": transaction,
            "before": before,
            "after": after,
        }
        atomic_text(
            root / "distribution-update.json",
            json.dumps(receipt, sort_keys=True) + "\n",
        )
        receipt_written = True
        pending.unlink()
        return {
            "status": "updated",
            "before": before,
            "after": after,
            "engine_transaction": transaction,
            "runtime": result["body"],
            "events": events,
            "user_data_preserved": True,
        }
    except Exception as error:
        failures = []
        try:
            current = home / ".local/bin"
            if any(
                (current / name).is_file() and digest(current / name) != expected
                for name, expected in (
                    ("axiom-cli", before["cli_sha256"]),
                    ("axiom", before["engine_cli_sha256"]),
                )
            ):
                restore_entrypoints(home, root, before, checked["entry"])
        except Exception as rollback_error:
            failures.append("entrypoints: " + str(rollback_error))
        if transaction:
            try:
                command(
                    [
                        str(release / "axiom"),
                        "update",
                        "rollback",
                        "--transaction",
                        transaction,
                        "--json",
                    ],
                    env,
                )
            except Exception as rollback_error:
                failures.append("engine: " + str(rollback_error))
        try:
            runtime_pointer = runtime_dir / "current.json"
            if (
                runtime_pointer.is_symlink()
                or not runtime_pointer.is_file()
                or digest(runtime_pointer) != before["runtime_pointer_sha256"]
            ):
                command(
                    [
                        sys.executable,
                        str(provision),
                        "rollback",
                        "--root",
                        str(runtime_dir),
                    ],
                    env,
                )
        except Exception as rollback_error:
            failures.append("runtime: " + str(rollback_error))
        if pending_written and transaction is None:
            try:
                current_journals = engine_journal_names(engine_journal)
                new_journals = sorted(
                    name
                    for name in current_journals.difference(journal_names)
                    if name.startswith("ecosystem-update-") and name.endswith(".json")
                )
                if new_journals:
                    failures.append(
                        "engine journal needs explicit recovery: "
                        + ", ".join(new_journals)
                    )
            except Exception as rollback_error:
                failures.append("engine journal inspection: " + str(rollback_error))
        if (
            not candidate_dir_preexisting
            and candidate_dir.is_dir()
            and not candidate_dir.is_symlink()
        ):
            try:
                rows = checked["entry"]["artifacts"]
                for name, row in zip(("axiom-cli", "axiom"), rows[:2]):
                    path = candidate_dir / name
                    if path.exists():
                        verify(path, row["sha256"])
                        path.unlink()
                candidate_dir.rmdir()
            except Exception as rollback_error:
                failures.append("staged entrypoints: " + str(rollback_error))
        try:
            restored = installed_update_state(home, root)
            if any(
                restored[key] != before[key]
                for key in before
                if key != "service_record_sha256"
            ):
                failures.append(
                    "installed generation differs from the approved A state"
                )
        except Exception as rollback_error:
            failures.append("state verification: " + str(rollback_error))
        if failures:
            raise ValueError(
                str(error) + "; rollback failed: " + "; ".join(failures)
            ) from error
        if receipt_written:
            (root / "distribution-update.json").unlink()
        if pending_written:
            pending.unlink()
        raise


def run_rollback(
    release: Path, home: Path, root: Path, env: dict, checked: dict, installed: dict
) -> dict:
    refuse_pending_update(root)
    receipt = rollback_receipt(release, root, installed)
    before = receipt["before"]
    provision = release / "runtime/provision.py"
    # Verify both retained entrypoints before asking the engine to restore its pointer.
    retained = root / "entrypoints/versions" / before["release_set_sha256"]
    verify(retained / "axiom-cli", before["cli_sha256"])
    verify(retained / "axiom", before["engine_cli_sha256"])
    if installed["runtime_pointer_sha256"] != before["runtime_pointer_sha256"]:
        runtime_dir = root / "mcp-runtime"
        verify(runtime_dir / "previous.json", before["runtime_pointer_sha256"])
        planned_runtime = command(
            [
                sys.executable,
                str(provision),
                "rollback",
                "--root",
                str(runtime_dir),
                "--dry-run",
            ],
            env,
        )
        if planned_runtime["body"].get("status") != "rollback_planned":
            raise ValueError("runtime rollback preflight did not verify A")
    pending = pending_update_path(root)
    atomic_text(
        pending,
        json.dumps(
            {
                "schema_version": 1,
                "action": "rollback",
                "release_set_sha256": receipt["release_set_sha256"],
                "receipt_sha256": digest(root / "distribution-update.json"),
                "engine_transaction": receipt["engine_transaction"],
                "installed": installed,
                "target": before,
            },
            sort_keys=True,
        )
        + "\n",
    )
    result = command(
        [
            str(release / "axiom"),
            "update",
            "rollback",
            "--transaction",
            receipt["engine_transaction"],
            "--json",
        ],
        env,
    )
    if installed["runtime_pointer_sha256"] != before["runtime_pointer_sha256"]:
        command(
            [
                sys.executable,
                str(provision),
                "rollback",
                "--root",
                str(root / "mcp-runtime"),
            ],
            env,
        )
    restore_entrypoints(home, root, before, checked["entry"])
    restored = installed_update_state(home, root)
    if any(
        restored[key] != before[key] for key in before if key != "service_record_sha256"
    ):
        raise ValueError("rollback did not restore the approved A generation")
    (root / "distribution-update.json").unlink()
    pending.unlink()
    return {
        "status": "rolled_back",
        "engine": result["body"],
        "before": installed,
        "after": restored,
        "user_data_preserved": True,
    }


def engine_env(home: Path, root: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "SHELL": os.environ.get("SHELL", "/bin/zsh"),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "AXIOM_CLI_INSTALL_ROOT": str(root),
        "AXIOM_HOME": str(root),
    }


def initialize_empty_bindings(root: Path) -> None:
    """Create the empty local table needed before projects are registered."""
    config = root / "config"
    if config.is_symlink():
        raise ValueError("local config directory is a symlink")
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = config / "bindings.json"
    if path.is_symlink():
        raise ValueError("local bindings file is a symlink")
    if path.exists():
        return
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "w") as stream:
        stream.write('{"bindings":{}}\n')
        stream.flush()
        os.fsync(stream.fileno())


def prune_empty_skill_dirs(record: tuple[Path, str, list[Path]] | None) -> None:
    """Remove only empty directories named by the verified owner manifest."""
    if record is None:
        return
    for path in record[2]:
        if path.is_symlink():
            continue
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass  # Human files and unowned directories remain untouched.


def skill_manifest_record(root: Path) -> tuple[Path, str, list[Path]] | None:
    pointer = root / "installs/ecosystem/skills/current"
    if not pointer.exists():
        return None
    if pointer.is_symlink() or not pointer.is_file():
        raise ValueError("installed skills pointer is unsafe")
    value = json.loads(pointer.read_text())
    version = value.get("version", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("installed skills version is invalid")
    if value.get("directory") != "skills/" + version:
        raise ValueError("installed skills directory differs from pointer")
    expected = value.get("manifest_sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("installed skills manifest digest is invalid")
    directory = root / "installs/ecosystem/skills" / version
    manifest = directory / "bundle.json"
    if manifest.is_symlink() or not manifest.is_file() or digest(manifest) != expected:
        return manifest, expected, []
    entries = json.loads(manifest.read_text()).get("entries", [])
    owned_dirs = {directory}
    for entry in entries:
        relative = PurePosixPath(entry.get("path", ""))
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in (".", "..") for part in relative.parts)
        ):
            raise ValueError("installed skills entry path is unsafe")
        parent = directory.joinpath(*relative.parts[:-1])
        while parent != directory:
            owned_dirs.add(parent)
            parent = parent.parent
    return (
        manifest,
        expected,
        sorted(owned_dirs, key=lambda path: len(path.parts), reverse=True),
    )


def remove_owned_skill_manifest(record: tuple[Path, str, list[Path]] | None) -> None:
    if record is None:
        return
    path, expected, _ = record
    if (
        path.exists()
        and not path.is_symlink()
        and path.is_file()
        and digest(path) == expected
    ):
        path.unlink()


def run_install(
    release: Path, home: Path, root: Path, env: dict, checked: dict
) -> dict:
    runtime = checked["runtime"]
    runtime_dir = root / "mcp-runtime"
    entry_script = str(release / "runtime/entrypoints.sh")
    provision = str(release / "runtime/provision.py")
    cli = home / ".local/bin/axiom-cli"
    engine = home / ".local/bin/axiom"
    old_runtime = (runtime_dir / "current.json").is_file()
    old_entry = (root / "entrypoints/current.tsv").is_file()
    old_engine = (root / "installs/ecosystem/current").is_file()
    old_service = (home / "Library/LaunchAgents/com.axiom.axiom-graphd.plist").is_file()
    if any((old_runtime, old_entry, old_engine, old_service)) and not all(
        (old_runtime, old_entry, old_engine, old_service)
    ):
        raise ValueError("partial prior installation requires explicit repair")
    events = []
    installed = []
    try:
        result = command(
            [
                sys.executable,
                provision,
                "provision",
                "--root",
                str(runtime_dir),
                "--version",
                runtime["mcp_version"],
                "--source-revision",
                runtime["mcp_revision"],
                *[
                    part
                    for key, name in (
                        ("runtime", "python.tar.gz"),
                        ("wheelhouse", "wheelhouse.tar.gz"),
                        ("wheel", "axiom_mcp-0.1.0-py3-none-any.whl"),
                        ("lock", "requirements.txt"),
                    )
                    for part in (
                        "--" + key,
                        str(release / "runtime" / name),
                        "--" + key + "-sha256",
                        runtime["files"][name],
                    )
                ],
            ],
            env,
        )
        events.append({"phase": "runtime", **result})
        installed.append("runtime")
        if os.environ.get("AXIOM_K105_FAIL_AFTER") == "runtime":
            raise ValueError("injected failure after runtime")
        entry_plan = command(
            [
                "/bin/sh",
                entry_script,
                "install",
                "--release-set",
                str(release),
                "--dry-run",
            ],
            env,
        )
        entry_apply = command(
            [
                "/bin/sh",
                entry_script,
                "install",
                "--release-set",
                str(release),
                "--apply",
                "--approve-digest",
                approval(entry_plan["body"]),
            ],
            env,
        )
        events.append({"phase": "entrypoints", **entry_apply})
        installed.append("entrypoints")
        if os.environ.get("AXIOM_K105_FAIL_AFTER") == "entrypoints":
            raise ValueError("injected failure after entrypoints")
        cli_plan = command(
            [str(cli), "install", "--from", str(release), "--dry-run", "--json"], env
        )
        cli_apply = command(
            [
                str(cli),
                "install",
                "--from",
                str(release),
                "--apply",
                "--approve-digest",
                approval(cli_plan["body"]),
                "--json",
            ],
            env,
        )
        events.append({"phase": "engine", **cli_apply})
        installed.append("engine")
        if os.environ.get("AXIOM_K105_FAIL_AFTER") == "engine":
            raise ValueError("injected failure after engine")
        initialize_empty_bindings(root)
        env = dict(
            env,
            PATH=str(
                runtime_dir / "versions" / result["body"]["generation"] / "venv/bin"
            )
            + ":"
            + env["PATH"],
        )
        if not old_service:
            service = command(
                [
                    str(engine),
                    "service",
                    "install",
                    "--component",
                    "axiom-graphd",
                    "--user",
                    "--json",
                ],
                env,
            )
            events.append({"phase": "service-register", **service})
            installed.append("service")
        started = command(
            [str(engine), "service", "start", "--component", "axiom-graphd", "--json"],
            env,
        )
        events.append({"phase": "service-start", **started})
        status = command(
            [str(engine), "service", "status", "--component", "axiom-graphd", "--json"],
            env,
        )
        time.sleep(1)
        status = command(
            [str(engine), "service", "status", "--component", "axiom-graphd", "--json"],
            env,
        )
        if "state = running" not in status["body"].get("stdout", ""):
            raise ValueError("LaunchAgent did not remain running after start")
        events.append({"phase": "service-status", **status})
        if os.environ.get("AXIOM_K105_FAIL_AFTER") == "service":
            raise ValueError("injected failure after service")
        return {
            "status": "installed",
            "events": events,
            "runtime": result["body"],
            "signing": "unsigned",
            "notarization": "not_notarized",
        }
    except Exception:
        if not any((old_runtime, old_entry, old_engine, old_service)):
            if "service" in installed:
                command(
                    [
                        str(engine),
                        "service",
                        "stop",
                        "--component",
                        "axiom-graphd",
                        "--json",
                    ],
                    env,
                    accept=True,
                )
                command(
                    [
                        str(engine),
                        "service",
                        "uninstall",
                        "--component",
                        "axiom-graphd",
                        "--json",
                    ],
                    env,
                    accept=True,
                )
            if "engine" in installed:
                skill_record = skill_manifest_record(root)
                remove_plan = command(
                    [str(cli), "uninstall", "--dry-run", "--json"], env, accept=True
                )
                if remove_plan["exit_code"] == 0:
                    removed_engine = command(
                        [
                            str(cli),
                            "uninstall",
                            "--apply",
                            "--approve-digest",
                            approval(remove_plan["body"]),
                            "--json",
                        ],
                        env,
                        accept=True,
                    )
                    if removed_engine["exit_code"] == 0:
                        remove_owned_skill_manifest(skill_record)
                        prune_empty_skill_dirs(skill_record)
            if "entrypoints" in installed:
                remove_plan = command(
                    ["/bin/sh", entry_script, "uninstall", "--dry-run"],
                    env,
                    accept=True,
                )
                if remove_plan["exit_code"] == 0:
                    command(
                        [
                            "/bin/sh",
                            entry_script,
                            "uninstall",
                            "--apply",
                            "--approve-digest",
                            approval(remove_plan["body"]),
                        ],
                        env,
                        accept=True,
                    )
            if "runtime" in installed:
                command(
                    [sys.executable, provision, "remove", "--root", str(runtime_dir)],
                    env,
                    accept=True,
                )
        raise


def run_uninstall(release: Path, home: Path, root: Path, env: dict) -> dict:
    runtime_dir = root / "mcp-runtime"
    cli = home / ".local/bin/axiom-cli"
    engine = home / ".local/bin/axiom"
    events = []
    if not cli.is_file() or not engine.is_file():
        raise ValueError("owned entrypoints are missing")
    for action in ("stop", "uninstall"):
        result = command(
            [str(engine), "service", action, "--component", "axiom-graphd", "--json"],
            env,
        )
        events.append({"phase": "service-" + action, **result})
    plan = command([str(cli), "uninstall", "--dry-run", "--json"], env)
    skill_record = skill_manifest_record(root)
    result = command(
        [
            str(cli),
            "uninstall",
            "--apply",
            "--approve-digest",
            approval(plan["body"]),
            "--json",
        ],
        env,
    )
    events.append({"phase": "engine-remove", **result})
    remove_owned_skill_manifest(skill_record)
    prune_empty_skill_dirs(skill_record)
    entry_script = str(release / "runtime/entrypoints.sh")
    plan = command(["/bin/sh", entry_script, "uninstall", "--dry-run"], env)
    result = command(
        [
            "/bin/sh",
            entry_script,
            "uninstall",
            "--apply",
            "--approve-digest",
            approval(plan["body"]),
        ],
        env,
    )
    events.append({"phase": "entrypoints-remove", **result})
    result = command(
        [
            sys.executable,
            str(release / "runtime/provision.py"),
            "remove",
            "--root",
            str(runtime_dir),
        ],
        env,
    )
    events.append({"phase": "runtime-remove", **result})
    return {"status": "removed", "events": events, "user_data_preserved": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("install", "update", "rollback", "recover", "uninstall")
    )
    parser.add_argument("--release-set", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-digest")
    args = parser.parse_args()
    try:
        if (platform.system(), platform.machine()) != (
            "Darwin",
            "x86_64",
        ) or os.getuid() == 0:
            raise ValueError("native non-root Mac x64 user is required")
        release = args.release_set.resolve(strict=True)
        home = Path(os.environ["HOME"]).resolve(strict=True)
        root = Path(
            os.environ.get("AXIOM_CLI_INSTALL_ROOT", str(home / ".local/share/axiom"))
        ).resolve()
        if not root.is_relative_to(home) or root == home or root.is_symlink():
            raise ValueError("owned install root must be below the user home")
        pending = pending_recovery(release, root) if args.action == "recover" else None
        if args.action != "recover":
            refuse_pending_update(root)
        checked = inputs(release)
        before = (
            installed_update_state(home, root)
            if args.action in ("update", "rollback")
            else None
        )
        if args.action == "update":
            require_new_core(checked, before)
        digest_value = (
            update_digest(release, home, checked, before)
            if args.action == "update"
            else rollback_digest(release, root, before)
            if args.action == "rollback"
            else recovery_digest(release, root, pending)
            if args.action == "recover"
            else plan_digest(release, home, args.action, checked)
        )
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "status": "planned",
                        "action": args.action,
                        "plan_digest": digest_value,
                        "signing": "unsigned",
                        "notarization": "not_notarized",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.approve_digest != digest_value:
            raise ValueError("approved plan digest differs from current candidate")
        env = engine_env(home, root)
        if args.action == "install":
            result = run_install(release, home, root, env, checked)
        elif args.action == "recover":
            with update_lock(root):
                if pending_recovery(release, root) != pending:
                    raise ValueError("distribution recovery intent changed since approval")
                result = run_recover(release, home, root, env, checked, pending)
        elif args.action in ("update", "rollback"):
            with update_lock(root):
                if installed_update_state(home, root) != before:
                    raise ValueError("installed generation changed since approval")
                result = (
                    run_update(release, home, root, env, checked, before)
                    if args.action == "update"
                    else run_rollback(release, home, root, env, checked, before)
                )
        else:
            result = run_uninstall(release, home, root, env)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(
            json.dumps({"status": "refused", "reason": str(error)}, sort_keys=True),
            file=sys.stderr,
        )
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
