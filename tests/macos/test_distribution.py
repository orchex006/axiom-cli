#!/usr/bin/env python3
"""Native Mac x64 proof of the complete unpublished per-user distribution."""

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

LABEL = "com.axiom.axiom-graphd"
TRACE: list[dict] = []


def record(
    argv: list[str], result: subprocess.CompletedProcess, home: str = ""
) -> None:
    TRACE.append(
        {
            "argv": argv,
            "home": home,
            "exit_code": result.returncode,
            "stdout": result.stdout.decode(errors="replace")
            if isinstance(result.stdout, bytes)
            else result.stdout,
            "stderr": result.stderr.decode(errors="replace")
            if isinstance(result.stderr, bytes)
            else result.stderr,
        }
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call(argv: list[str], env: dict | None = None, expect: int = 0) -> dict:
    result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    record(argv, result, (env or {}).get("HOME", ""))
    if result.returncode != expect:
        raise AssertionError(
            f"{argv[0]}: expected {expect}, got {result.returncode}: "
            + (result.stderr or result.stdout)[-700:]
        )
    text = result.stdout if expect == 0 else result.stderr
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def target(
    release: Path,
    home: Path,
    verb: str,
    mode: str,
    approval: str = "",
    extra: dict | None = None,
) -> dict:
    env = {
        **os.environ,
        "HOME": str(home),
        "SHELL": "/bin/zsh",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        **(extra or {}),
    }
    args = [
        "/bin/sh",
        str(release / "runtime/bootstrap.sh"),
        verb,
        "--release-set",
        str(release),
        mode,
    ]
    if approval:
        args += ["--approve-digest", approval]
    return call(args, env)


def make_home(root: Path, name: str) -> Path:
    home = root / name
    (home / "Library/LaunchAgents").mkdir(parents=True)
    (home / "user-data.txt").write_text("preserve user data\n")
    return home.resolve()


def installed(release: Path, home: Path) -> dict:
    planned = target(release, home, "install", "--dry-run")
    result = target(release, home, "install", "--apply", planned["plan_digest"])
    assert result["status"] == "installed"
    root = home / ".local/share/axiom"
    pointer = json.loads((root / "mcp-runtime/current.json").read_text())
    launcher = (
        root / "mcp-runtime/versions" / pointer["generation"] / "venv/bin/axiom-mcp"
    )
    assert sha(launcher) == pointer["executable_sha256"]
    assert sha(home / ".local/bin/axiom-cli") == sha(release / "axiom-cli")
    assert sha(home / ".local/bin/axiom") == sha(release / "axiom")
    service = call(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"])
    assert "state = running" in service["text"]
    return result


def removed(release: Path, home: Path) -> dict:
    planned = target(release, home, "uninstall", "--dry-run")
    result = target(release, home, "uninstall", "--apply", planned["plan_digest"])
    assert result["status"] == "removed"
    assert not (home / ".local/bin/axiom-cli").exists()
    assert not (home / ".local/bin/axiom").exists()
    assert not (home / ".local/share/axiom/mcp-runtime/current.json").exists()
    assert not (home / "Library/LaunchAgents" / (LABEL + ".plist")).exists()
    assert not (home / ".local/share/axiom/installs/ecosystem/skills/0.1.0").exists()
    assert (home / "user-data.txt").read_text() == "preserve user data\n"
    assert (
        home / ".local/share/axiom/config/bindings.json"
    ).read_text() == '{"bindings":{}}\n'
    absence = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True
    )
    record(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], absence)
    assert absence.returncode == 113
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-set", type=Path, required=True)
    parser.add_argument("--transcript", type=Path)
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
        raise SystemExit("NOT_RUN: native Intel Mac required")
    release = args.release_set.resolve()
    preexisting = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True
    )
    record(["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], preexisting)
    if preexisting.returncode != 113:
        raise SystemExit("NOT_RUN: canonical LaunchAgent label is occupied")
    cases = []
    with tempfile.TemporaryDirectory(prefix="axiom-k105-native-") as name:
        root = Path(name)
        corrupt = root / "corrupt"
        shutil.copytree(release, corrupt)
        version = json.loads((corrupt / "runtime/manifest.json").read_text())[
            "mcp_version"
        ]
        wheel = corrupt / "runtime" / f"axiom_mcp-{version}-py3-none-any.whl"
        wheel.write_bytes(wheel.read_bytes() + b"corrupt")
        bad = subprocess.run(
            [
                "/bin/sh",
                str(corrupt / "runtime/bootstrap.sh"),
                "install",
                "--release-set",
                str(corrupt),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        record(
            ["/bin/sh", str(corrupt / "runtime/bootstrap.sh"), "install", "--dry-run"],
            bad,
        )
        assert bad.returncode == 9 and "changed candidate input" in bad.stderr
        cases.append("corrupt-payload")

        home = make_home(root, "zsh-home")
        profile = home / ".zprofile"
        before = None
        try:
            first = installed(release, home)
            assert [row["phase"] for row in first["events"]] == [
                "runtime",
                "entrypoints",
                "engine",
                "service-register",
                "service-start",
                "service-status",
            ]
            cases += ["clean-install", "service-lifecycle"]
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            }
            env.pop("ZDOTDIR", None)
            discover = call(
                ["/bin/zsh", "-lc", "command -v axiom-cli; command -v axiom"], env
            )
            assert str(home / ".local/bin/axiom-cli") in discover["text"]
            assert str(home / ".local/bin/axiom") in discover["text"]
            cases.append("discovery")
            again = target(
                release,
                home,
                "install",
                "--apply",
                target(release, home, "install", "--dry-run")["plan_digest"],
            )
            assert again["events"][0]["body"]["status"] == "already_current"
            assert again["events"][1]["body"]["status"] == "already_installed"
            assert (
                again["events"][2]["body"]["details"]["engine_status"]
                == "already-installed"
            )
            cases.append("idempotency")
            before = profile.read_text()
            profile.write_text(
                before.replace("# axiom-cli PATH begin", "# human-edited PATH begin")
            )
            refusal = subprocess.run(
                [
                    "/bin/sh",
                    str(release / "runtime/entrypoints.sh"),
                    "uninstall",
                    "--dry-run",
                ],
                env={**env, "SHELL": "/bin/zsh"},
                capture_output=True,
                text=True,
            )
            record(
                [
                    "/bin/sh",
                    str(release / "runtime/entrypoints.sh"),
                    "uninstall",
                    "--dry-run",
                ],
                refusal,
                str(home),
            )
            assert refusal.returncode == 6 and "shell_profile_changed" in refusal.stderr
            assert "# human-edited PATH begin" in profile.read_text()
            profile.write_text(before)
            cases.append("human-edits")
        finally:
            if before is not None and profile.is_file():
                profile.write_text(before)
            removed(release, home)
        cases.append("uninstall-preserve-data")
        installed(release, home)
        removed(release, home)
        cases.append("reinstall-after-removal")

        bash_home = make_home(root, "bash-home")
        bash_shell = {"SHELL": "/bin/bash"}
        bash_plan = target(release, bash_home, "install", "--dry-run", extra=bash_shell)
        bash_apply = target(
            release,
            bash_home,
            "install",
            "--apply",
            bash_plan["plan_digest"],
            bash_shell,
        )
        assert bash_apply["status"] == "installed"
        assert "axiom-cli PATH begin" in (bash_home / ".bash_profile").read_text()
        bash_env = {
            **os.environ,
            "HOME": str(bash_home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        }
        bash_env.pop("ZDOTDIR", None)
        bash_found = call(
            ["/bin/bash", "-lc", "command -v axiom-cli; command -v axiom"], bash_env
        )
        assert str(bash_home / ".local/bin/axiom-cli") in bash_found["text"]
        assert str(bash_home / ".local/bin/axiom") in bash_found["text"]
        bash_remove_plan = target(
            release, bash_home, "uninstall", "--dry-run", extra=bash_shell
        )
        bash_removed = target(
            release,
            bash_home,
            "uninstall",
            "--apply",
            bash_remove_plan["plan_digest"],
            bash_shell,
        )
        assert bash_removed["status"] == "removed"
        assert not (bash_home / ".local/bin/axiom-cli").exists()
        assert (bash_home / "user-data.txt").read_text() == "preserve user data\n"
        cases.append("bash-discovery")

        conflict = make_home(root, "conflict-home")
        (conflict / ".local/bin").mkdir(parents=True)
        (conflict / ".local/bin/axiom-cli").write_text("human executable\n")
        digest_plan = target(release, conflict, "install", "--dry-run")["plan_digest"]
        env = {
            **os.environ,
            "HOME": str(conflict),
            "SHELL": "/bin/zsh",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        }
        rejected = subprocess.run(
            [
                "/bin/sh",
                str(release / "runtime/bootstrap.sh"),
                "install",
                "--release-set",
                str(release),
                "--apply",
                "--approve-digest",
                digest_plan,
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        record(
            ["/bin/sh", str(release / "runtime/bootstrap.sh"), "install", "--apply"],
            rejected,
            str(conflict),
        )
        assert rejected.returncode == 9 and "unowned_cli_entrypoint" in rejected.stderr
        assert (conflict / ".local/bin/axiom-cli").read_text() == "human executable\n"
        assert not (conflict / ".local/share/axiom/mcp-runtime/current.json").exists()
        cases.append("unowned-conflict")

        interrupted = make_home(root, "failure-home")
        digest_plan = target(release, interrupted, "install", "--dry-run")[
            "plan_digest"
        ]
        env = {
            **os.environ,
            "HOME": str(interrupted),
            "SHELL": "/bin/zsh",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "AXIOM_K105_FAIL_AFTER": "engine",
        }
        failed = subprocess.run(
            [
                "/bin/sh",
                str(release / "runtime/bootstrap.sh"),
                "install",
                "--release-set",
                str(release),
                "--apply",
                "--approve-digest",
                digest_plan,
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        record(
            ["/bin/sh", str(release / "runtime/bootstrap.sh"), "install", "--apply"],
            failed,
            str(interrupted),
        )
        assert (
            failed.returncode == 9 and "injected failure after engine" in failed.stderr
        )
        assert not (interrupted / ".local/bin/axiom-cli").exists()
        assert not (
            interrupted / ".local/share/axiom/mcp-runtime/current.json"
        ).exists()
        assert (interrupted / "user-data.txt").read_text() == "preserve user data\n"
        cases.append("install-rollback")
    summary = {
        "ok": True,
        "cases": cases,
        "release_manifest_sha256": sha(release / "runtime/manifest.json"),
        "signing": "unsigned",
        "notarization": "not_notarized",
    }
    if args.transcript:
        args.transcript.write_text(
            json.dumps({"summary": summary, "commands": TRACE}, indent=2) + "\n"
        )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
