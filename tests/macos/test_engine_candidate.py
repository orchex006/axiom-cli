#!/usr/bin/env python3
"""K-001 Intel Mac candidate bridge, including the real engine install path.

The supplied Python is test preparation, not K-002 clean-host provisioning.
The supplied skills bundle may be a fixture; results never certify a release.
"""

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
PACKAGE = REPO / "packaging/macos/Build-ReleaseSet.sh"
COMPOSE = REPO / "packaging/macos/Build-EngineCandidate.py"
INSTALL = REPO / "installers/macos/Install-AxiomCli.sh"
UNINSTALL = REPO / "installers/macos/Uninstall-AxiomCli.sh"
LABEL = "com.axiom.axiom-graphd"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv, env=None, expected=0, contains=None):
    result = subprocess.run([str(x) for x in argv], env=env, capture_output=True, text=True)
    if result.returncode != expected:
        raise AssertionError(f"{[Path(str(x)).name for x in argv]}: expected {expected}, got {result.returncode}: {result.stdout[-700:]} {result.stderr[-700:]}")
    if contains is not None and contains not in result.stdout + result.stderr:
        raise AssertionError(f"expected refusal {contains!r}, got: {result.stdout[-350:]} {result.stderr[-350:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def package(root, args):
    release = root / "release"
    run(["/bin/sh", PACKAGE, "--out-dir", release, "--cli-binary", args.cli,
         "--engine-cli", args.engine, "--engine-daemon", args.daemon,
         "--core-version", args.core_version, "--core-revision", args.core_revision, "--json"])
    return release


def compose(release, args, wheel=None, wheel_sha=None, revision=None, skills=None,
            expected=0, contains=None):
    return run(["python3", COMPOSE, "--release-set", release,
                "--mcp-wheel", wheel or args.mcp_wheel,
                "--mcp-sha256", wheel_sha or args.mcp_sha256,
                "--mcp-revision", revision or args.mcp_revision,
                "--skills-bundle", skills or args.skills_bundle], expected=expected,
               contains=contains)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cli", "engine", "daemon", "mcp-wheel", "skills-bundle", "python"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--mcp-sha256", required=True)
    parser.add_argument("--mcp-revision", required=True)
    parser.add_argument("--core-version", required=True)
    parser.add_argument("--core-revision", required=True)
    parser.add_argument("--service", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise SystemExit("NOT_RUN: native Intel Mac required")
    for path in (args.cli, args.engine, args.daemon, args.mcp_wheel, args.python):
        assert path.is_file(), path
    label_target = f"gui/{os.getuid()}/{LABEL}"
    if args.service:
        absent = subprocess.run(["/bin/launchctl", "print", label_target], capture_output=True)
        if absent.returncode != 113:
            raise SystemExit(f"NOT_RUN: canonical LaunchAgent label is not absent (exit {absent.returncode})")
    events = []
    with tempfile.TemporaryDirectory(prefix="axiom-k001-engine-candidate-") as temporary:
        root = Path(temporary)
        release = package(root, args)
        packaged = json.loads((release / "release-set.json").read_text())
        events.append({"step": "package", "exit_code": 0})
        candidate = compose(release, args)
        assert candidate["published"] is False
        events.append({"step": "candidate-channel", "exit_code": 0})

        home = root / "home"
        home.mkdir()
        (home / "Library/LaunchAgents").mkdir(parents=True)
        preserved = home / "user-data.txt"
        preserved.write_text("preserve me\n")
        env = {**os.environ, "HOME": str(home), "SHELL": "/bin/zsh",
               "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
               "AXIOM_CLI_INSTALL_ROOT": str(home / ".local/share/axiom")}
        runtime = home / "test-prepared-python"
        run([args.python, "-m", "venv", runtime])
        events.append({"step": "test-prepared-python", "exit_code": 0})
        installed_cli = home / ".local/bin/axiom-cli"
        installed_engine = home / ".local/bin/axiom"
        plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
        try:
            entry_plan = run(["/bin/sh", INSTALL, "--release-set", release, "--dry-run"], env)
            run(["/bin/sh", INSTALL, "--release-set", release, "--apply",
                 "--approve-digest", entry_plan["plan_digest"]], env)
            assert sha(installed_cli) == sha(args.cli)
            assert sha(installed_engine) == sha(args.engine)
            events.append({"step": "entrypoints-install", "exit_code": 0})

            env["PATH"] = f"{runtime / 'bin'}:{home / '.local/bin'}:/usr/bin:/bin:/usr/sbin:/sbin"
            ecosystem_plan = run([installed_cli, "install", "--from", release,
                                  "--dry-run", "--json"], env)
            applied = run([installed_cli, "install", "--from", release, "--apply",
                           "--approve-digest", ecosystem_plan["details"]["plan_digest"],
                           "--json"], env)
            assert applied["details"]["engine_status"] == "installed"
            ecosystem = home / ".local/share/axiom/installs/ecosystem"
            pointer = json.loads((ecosystem / "current").read_text())
            assert {row["component"] for row in pointer["activated"]} == {"axiom-graphd", "axiom-mcp"}
            for row in pointer["activated"]:
                assert sha(Path(row["destination"])) == row["sha256"]
            events.append({"step": "engine-install", "exit_code": 0})

            if args.service:
                engine_env = dict(env, AXIOM_HOME=str(home / ".local/share/axiom"))
                run([installed_engine, "service", "install", "--component",
                     "axiom-graphd", "--user", "--json"], engine_env)
                run([installed_engine, "service", "status", "--component",
                     "axiom-graphd", "--json"], engine_env)
                events.append({"step": "service-install-status", "exit_code": 0})
                run([installed_engine, "service", "uninstall", "--component",
                     "axiom-graphd", "--json"], engine_env)
                events.append({"step": "service-uninstall", "exit_code": 0})
                assert subprocess.run(["/bin/launchctl", "print", label_target], capture_output=True).returncode == 113

            ecosystem_remove = run([installed_cli, "uninstall", "--dry-run", "--json"], env)
            run([installed_cli, "uninstall", "--apply", "--approve-digest",
                 ecosystem_remove["details"]["plan_digest"], "--json"], env)
            assert not any((ecosystem / "versions").rglob("axiom-graphd"))
            assert preserved.read_text() == "preserve me\n"
            events.append({"step": "engine-uninstall-preserve-data", "exit_code": 0})

            entry_remove = run(["/bin/sh", UNINSTALL, "--entrypoints", "--dry-run"], env)
            run(["/bin/sh", UNINSTALL, "--entrypoints", "--apply",
                 "--approve-digest", entry_remove["plan_digest"]], env)
            assert not installed_cli.exists() and not installed_engine.exists()
            assert preserved.read_text() == "preserve me\n"
            events.append({"step": "entrypoints-uninstall-preserve-data", "exit_code": 0})
        finally:
            if args.service:
                subprocess.run(["/bin/launchctl", "bootout", label_target], capture_output=True)
                if plist.exists():
                    plist.unlink()

        # Refusal cases operate on copies, never on the accepted release set.
        corrupted_core = root / "corrupt-core"
        shutil.copytree(release, corrupted_core)
        with (corrupted_core / "axiom-graphd").open("ab") as output:
            output.write(b"changed")
        (corrupted_core / "channel.json").unlink()
        (corrupted_core / args.mcp_wheel.name).unlink()
        shutil.rmtree(corrupted_core / "skills")
        compose(corrupted_core, args, expected=2, contains="candidate artifact has changed")
        assert not (corrupted_core / "channel.json").exists()
        events.append({"step": "corrupt-core-refused", "exit_code": 2})

        wrong_digest = root / "wrong-digest"
        shutil.copytree(corrupted_core, wrong_digest)
        shutil.copy2(release / "axiom-graphd", wrong_digest / "axiom-graphd")
        compose(wrong_digest, args, wheel_sha="0" * 64, expected=2,
                contains="MCP wheel digest mismatch")
        assert not (wrong_digest / "channel.json").exists()
        events.append({"step": "wrong-mcp-digest-refused", "exit_code": 2})

        bad_skills = root / "bad-skills"
        shutil.copytree(args.skills_bundle, bad_skills)
        first = json.loads((bad_skills / "bundle.json").read_text())["entries"][0]["path"]
        (bad_skills / "payload" / first).write_bytes(b"changed")
        compose(wrong_digest, args, skills=bad_skills, expected=2,
                contains="skills payload has changed")
        events.append({"step": "corrupt-skills-refused", "exit_code": 2})

        compose(wrong_digest, args, revision="main", expected=2,
                contains="immutable 40-hex revision")
        events.append({"step": "mutable-mcp-revision-refused", "exit_code": 2})

        compose(release, args, expected=2, contains="candidate output already exists")
        events.append({"step": "existing-output-refused", "exit_code": 2})

        print(json.dumps({"task": "K-001", "scope": "candidate bridge, test-prepared interpreter and supplied skills bundle",
                          "host": {"system": platform.system(), "machine": platform.machine(),
                                   "macos": platform.mac_ver()[0]},
                          "source_sha256": {"axiom-cli": sha(args.cli), "axiom": sha(args.engine),
                                            "axiom-graphd": sha(args.daemon), "axiom-mcp-wheel": sha(args.mcp_wheel)},
                          "core_revision": args.core_revision, "mcp_revision": args.mcp_revision,
                          "skills_revision": json.loads((release / "skills/bundle.json").read_text())["revision"],
                          "release_set_sha256": sha(release / "release-set.json"),
                          "candidate_channel_sha256": candidate["channel_sha256"],
                          "events": events, "certified": False}, sort_keys=True))


if __name__ == "__main__":
    main()
