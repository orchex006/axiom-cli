#!/usr/bin/env python3
"""Compose the owned Mac candidate install, service and data-preserving removal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
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
    parser.add_argument("action", choices=("install", "uninstall"))
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
        checked = inputs(release)
        digest_value = plan_digest(release, home, args.action, checked)
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
        result = (
            run_install(release, home, root, env, checked)
            if args.action == "install"
            else run_uninstall(release, home, root, env)
        )
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
