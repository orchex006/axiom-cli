#!/usr/bin/env python3
"""Native Intel Mac K-001 entrypoint lifecycle in isolated per-user homes."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "installers/macos/Install-AxiomCli.sh"
UNINSTALL = REPO / "installers/macos/Uninstall-AxiomCli.sh"
PACKAGE = REPO / "packaging/macos/Build-ReleaseSet.sh"


def invoke(script, env, *args):
    result = subprocess.run(
        ["/bin/sh", str(script), *map(str, args)], env=env, capture_output=True, text=True
    )
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError((script, args, result.returncode, result.stdout, result.stderr)) from exc
    return result.returncode, envelope


def expect(code, actual, label):
    assert actual[0] == code, (label, actual)
    return actual[1]


def install_plan(env, release):
    return expect(0, invoke(INSTALL, env, "--release-set", release, "--dry-run"), "install plan")


def install_apply(env, release, digest):
    return invoke(INSTALL, env, "--release-set", release, "--apply", "--approve-digest", digest)


def uninstall_plan(env):
    return expect(0, invoke(UNINSTALL, env, "--entrypoints", "--dry-run"), "uninstall plan")


def uninstall_apply(env, digest):
    return invoke(UNINSTALL, env, "--entrypoints", "--apply", "--approve-digest", digest)


def make_home(parent, name):
    home = parent / name
    home.mkdir()
    env = os.environ.copy()
    env.update(HOME=str(home), SHELL="/bin/zsh", PATH="/usr/bin:/bin:/usr/sbin:/sbin")
    env.pop("ZDOTDIR", None)
    return home, env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--daemon", type=Path, required=True)
    parser.add_argument("--core-version", required=True)
    parser.add_argument("--core-revision", required=True)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise SystemExit("NOT_RUN: native Intel Mac required")

    with tempfile.TemporaryDirectory(prefix="axiom-k001-entrypoints-") as scratch:
        root = Path(scratch)
        release = root / "release"
        package = subprocess.run(
            ["/bin/sh", str(PACKAGE), "--out-dir", str(release), "--cli-binary", str(args.cli),
             "--engine-cli", str(args.engine), "--engine-daemon", str(args.daemon),
             "--core-version", args.core_version, "--core-revision", args.core_revision, "--json"],
            capture_output=True, text=True, check=True,
        )
        package_result = json.loads(package.stdout)
        manifest = release / "release-set.json"
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == package_result["release_set_sha256"]
        declared = json.loads(manifest.read_text())
        assert (declared["signing"], declared["notarization"]) == ("unsigned", "not_notarized")
        print("package", package_result["release_set_sha256"], "exit=0")

        home, env = make_home(root, "normal")
        profile = home / ".zprofile"
        profile.write_text("# human before\n")
        data = home / "keep.txt"
        data.write_text("user data\n")
        planned = install_plan(env, release)
        expect(6, install_apply(env, release, "0" * 64), "stale approval")
        assert not (home / ".local/bin/axiom-cli").exists()
        applied = expect(0, install_apply(env, release, planned["plan_digest"]), "install")
        assert applied["status"] == "installed"
        for row in applied["artifacts"]:
            installed = home / ".local/bin" / row["component"]
            assert hashlib.sha256(installed.read_bytes()).hexdigest() == row["sha256"]
        discovered = subprocess.run(
            ["/bin/zsh", "-lc", "command -v axiom-cli; command -v axiom"],
            env=env, capture_output=True, text=True, check=True,
        )
        assert str(home / ".local/bin/axiom-cli") in discovered.stdout
        assert str(home / ".local/bin/axiom") in discovered.stdout
        print("discovery", discovered.stdout.strip().replace("\n", ", "), "exit=0")
        assert expect(0, install_apply(env, release, planned["plan_digest"]), "rerun")["status"] == "already_installed"
        profile.write_text(profile.read_text() + "# human after\n")
        removal = uninstall_plan(env)
        assert expect(0, uninstall_apply(env, removal["plan_digest"]), "uninstall")["status"] == "uninstalled"
        assert profile.read_text().startswith("# human before\n")
        assert "# human after\n" in profile.read_text()
        assert "axiom-cli PATH begin" not in profile.read_text()
        assert data.read_text() == "user data\n"
        assert not (home / ".local/bin/axiom-cli").exists()
        print("lifecycle install/discovery/rerun/uninstall/data-preservation exit=0")

        bash_home, bash_env = make_home(root, "bash")
        bash_env["SHELL"] = "/bin/bash"
        bash_plan = install_plan(bash_env, release)
        expect(0, install_apply(bash_env, release, bash_plan["plan_digest"]), "bash install")
        bash_discovery = subprocess.run(
            ["/bin/bash", "-lc", "command -v axiom-cli; command -v axiom"],
            env=bash_env, capture_output=True, text=True, check=True,
        )
        assert str(bash_home / ".local/bin/axiom-cli") in bash_discovery.stdout
        assert "axiom-cli PATH begin" in (bash_home / ".bash_profile").read_text()
        bash_remove = uninstall_plan(bash_env)
        expect(0, uninstall_apply(bash_env, bash_remove["plan_digest"]), "bash uninstall")
        print("bash login-shell discovery and owned PATH removal exit=0")

        conflict_home, conflict_env = make_home(root, "conflict")
        (conflict_home / ".local/bin").mkdir(parents=True)
        unowned = conflict_home / ".local/bin/axiom-cli"
        unowned.write_text("human executable\n")
        assert expect(6, invoke(INSTALL, conflict_env, "--release-set", release, "--dry-run"), "unowned conflict")["reason"] == "unowned_cli_entrypoint"
        assert unowned.read_text() == "human executable\n"
        print("unowned conflict exit=6")

        outside_home, outside_env = make_home(root, "outside")
        outside_env["AXIOM_CLI_INSTALL_ROOT"] = str(root / "outside-root")
        assert expect(5, invoke(INSTALL, outside_env, "--release-set", release, "--dry-run"), "outside home")["reason"] == "install_root_outside_user_home"
        assert not (root / "outside-root").exists()
        print("system/outside-home root exit=5, no write")

        corrupt = root / "corrupt-release"
        shutil.copytree(release, corrupt)
        with (corrupt / "axiom").open("ab") as output:
            output.write(b"changed after packaging")
        corrupt_home, corrupt_env = make_home(root, "corrupt")
        assert expect(9, invoke(INSTALL, corrupt_env, "--release-set", corrupt, "--dry-run"), "corrupt artifact")["reason"] == "release_artifact_digest_mismatch"
        assert not (corrupt_home / ".local/bin").exists()
        print("corrupt artifact exit=9, no install state")

        rollback_home, rollback_env = make_home(root, "rollback")
        rollback_profile = rollback_home / ".zprofile"
        rollback_profile.write_text("# preserved before failure\n")
        rollback_env["AXIOM_CLI_TEST_FAIL_AFTER_PROFILE"] = "1"
        rollback_plan = install_plan(rollback_env, release)
        assert expect(8, install_apply(rollback_env, release, rollback_plan["plan_digest"]), "injected failure")["reason"] == "injected_failure"
        assert rollback_profile.read_text() == "# preserved before failure\n"
        assert not (rollback_home / ".local/bin/axiom-cli").exists()
        assert not (rollback_home / ".local/bin/axiom").exists()
        assert not (rollback_home / ".local/share/axiom/entrypoints/current.tsv").exists()
        print("injected rollback exit=8, original profile and data preserved")

        remove_home, remove_env = make_home(root, "remove-rollback")
        remove_install = install_plan(remove_env, release)
        expect(0, install_apply(remove_env, release, remove_install["plan_digest"]), "remove rollback setup")
        remove_env["AXIOM_CLI_TEST_FAIL_AFTER_REMOVAL"] = "1"
        remove_digest = uninstall_plan(remove_env)["plan_digest"]
        assert expect(8, uninstall_apply(remove_env, remove_digest), "remove rollback")["reason"] == "injected_failure"
        assert (remove_home / ".local/bin/axiom-cli").exists()
        assert (remove_home / ".local/bin/axiom").exists()
        assert (remove_home / ".local/share/axiom/entrypoints/current.tsv").exists()
        assert "axiom-cli PATH begin" in (remove_home / ".zprofile").read_text()
        print("injected uninstall rollback exit=8, owned entries restored")

        edited_home, edited_env = make_home(root, "edited")
        edited_plan = install_plan(edited_env, release)
        expect(0, install_apply(edited_env, release, edited_plan["plan_digest"]), "edited setup")
        edited_profile = edited_home / ".zprofile"
        edited_profile.write_text(edited_profile.read_text().replace("export PATH", "export PATH # human edit"))
        assert expect(6, invoke(UNINSTALL, edited_env, "--entrypoints", "--dry-run"), "edited block")["reason"] == "shell_profile_changed"
        assert (edited_home / ".local/bin/axiom-cli").exists()
        print("human-edited managed block exit=6, entrypoint preserved")

        changed_home, changed_env = make_home(root, "changed-binary")
        changed_plan = install_plan(changed_env, release)
        expect(0, install_apply(changed_env, release, changed_plan["plan_digest"]), "changed setup")
        changed_cli = changed_home / ".local/bin/axiom-cli"
        with changed_cli.open("ab") as output:
            output.write(b"human modification")
        assert expect(6, invoke(UNINSTALL, changed_env, "--entrypoints", "--dry-run"), "changed binary")["reason"] == "cli_entrypoint_changed"
        assert changed_cli.read_bytes().endswith(b"human modification")
        print("human-edited executable exit=6, edited bytes preserved")

    print("PASS: K-001 native Intel Mac per-user entrypoint boundary")


if __name__ == "__main__":
    main()
