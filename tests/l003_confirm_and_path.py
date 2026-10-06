#!/usr/bin/env python3
"""L-003 real-host harness: single confirmation, --yes, and the announced, reversible user PATH.

Uses an extracted release (the CLI under test is copied into it), removes every `AXIOM_*`
variable, redirects the per-user data directory to a work directory, and redirects the user PATH
target so the real one is never touched: on Windows `AXIOM_CLI_TEST_USER_ENV_KEY` points the
registry writes at `HKCU\\Software\\AxiomCliTest\\L003` (seeded with a REG_EXPAND_SZ value that
holds an unexpanded variable); on POSIX `HOME` points at a work directory with a seeded profile.
`AXIOM_CLI_TEST_PROMPT_STDIN=1` lets the harness answer the real `Proceed? [Y/n]` prompt.

    python tests/l003_confirm_and_path.py --release <extracted-release> --cli target/release/axiom-cli[.exe] --work <short-dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
EXE = ".exe" if WINDOWS else ""
TEST_KEY = r"Software\AxiomCliTest\L003"
SEED = r"%USERPROFILE%\tools;C:\Program Files\Example"
PROFILE_SEED = "umask 022\nexport EDITOR=vi\n"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reg(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["reg", *args], capture_output=True, text=True)


def seed_path_target(home: Path) -> None:
    if WINDOWS:
        reg("delete", "HKCU\\" + TEST_KEY, "/f")
        reg("add", "HKCU\\" + TEST_KEY, "/v", "Path", "/t", "REG_EXPAND_SZ", "/d", SEED, "/f")
    else:
        home.mkdir(parents=True, exist_ok=True)
        (home / ".profile").write_text(PROFILE_SEED, encoding="utf-8")


def path_target_state(home: Path):
    if WINDOWS:
        out = reg("query", "HKCU\\" + TEST_KEY, "/v", "Path").stdout
        line = next((l for l in out.splitlines() if l.strip().startswith("Path")), "")
        parts = line.split(None, 2)
        return {"type": parts[1] if len(parts) > 1 else None, "value": parts[2] if len(parts) > 2 else None}
    profile = home / ".profile"
    return {"profile": profile.read_text(encoding="utf-8") if profile.exists() else None}


def real_user_path():
    if not WINDOWS:
        return None
    return reg("query", r"HKCU\Environment", "/v", "Path").stdout


def env_for(data_home: Path, home: Path, extra=None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("AXIOM")}
    if WINDOWS:
        env["LOCALAPPDATA"] = str(data_home)
        env["AXIOM_CLI_TEST_USER_ENV_KEY"] = TEST_KEY
    else:
        env["XDG_DATA_HOME"] = str(data_home)
        env["HOME"] = str(home)
        env["SHELL"] = "/bin/sh"
    env.update(extra or {})
    return env


def root_of(data_home: Path) -> Path:
    return data_home / ("Axiom" if WINDOWS else "axiom")


def run(argv, env, stdin=None, cwd=None):
    proc = subprocess.run([str(a) for a in argv], env=env, input=stdin, cwd=cwd,
                          capture_output=True, text=True,
                          stdin=None if stdin is not None else subprocess.DEVNULL)
    return {"argv": [str(a) for a in argv], "stdin": stdin, "exit_code": proc.returncode,
            "stdout_tail": proc.stdout[-1800:], "stderr_tail": proc.stderr[-1200:]}


def stage(release: Path, cli: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(release, target, ignore=shutil.ignore_patterns("axiom-*-*.zip", "axiom-*-*.tar.gz"))
    shutil.copy2(cli, target / f"axiom-cli{EXE}")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--cli", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    release = stage(args.release, args.cli, work / "rel")
    cli = release / f"axiom-cli{EXE}"
    home = work / "home"
    real_before = real_user_path()
    cases = []

    def case(name, passed, **detail):
        cases.append({"case": name, "passed": bool(passed), **detail})

    # 1. No terminal, no --yes: plan printed, exit 4, nothing changed.
    seed_path_target(home)
    d1 = work / "d1"
    env = env_for(d1, home)
    before = path_target_state(home)
    out = run([cli, "install"], env)
    text = out["stdout_tail"] + out["stderr_tail"]
    case("no_terminal_exit_4_no_change", out["exit_code"] == 4 and "PATH: add" in text and "size:" in text
         and "--yes" in text and not root_of(d1).exists() and path_target_state(home) == before, run=out)

    # 2. Declined at the prompt: exit 5, nothing changed.
    out = run([cli, "install"], env_for(d1, home, {"AXIOM_CLI_TEST_PROMPT_STDIN": "1"}), stdin="n\n")
    case("declined_exit_5_no_change", out["exit_code"] == 5 and "Proceed? [Y/n]" in out["stdout_tail"]
         and not root_of(d1).exists() and path_target_state(home) == before, run=out)

    # 3. Confirmed at the prompt (default answer): installs the printed plan and adds the PATH entry.
    out = run([cli, "install"], env_for(d1, home, {"AXIOM_CLI_TEST_PROMPT_STDIN": "1"}), stdin="\n")
    bin_dir = root_of(d1) / "bin"
    during = path_target_state(home)
    added = (str(bin_dir) in (during.get("value") or "")) if WINDOWS else (str(bin_dir) in (during.get("profile") or ""))
    record = root_of(d1) / "path-change.json"
    case("confirmed_installs_and_adds_path", out["exit_code"] == 0 and "Proceed? [Y/n]" in out["stdout_tail"]
         and (root_of(d1) / "installed.json").is_file() and added and record.is_file()
         and (not WINDOWS or during.get("type") == "REG_EXPAND_SZ"),
         run=out, path_during=during)

    # 4. Uninstall --yes from the installed bin: PATH restored byte for byte, bin removed, data kept.
    user_file = root_of(d1).parent / "my-workspace" / "notes.md"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("keep me", encoding="utf-8")
    out = run([bin_dir / f"axiom-cli{EXE}", "uninstall", "--yes"], env_for(d1, home), cwd=work)
    after = path_target_state(home)
    leftovers = sorted(p.name for p in bin_dir.iterdir()) if bin_dir.exists() else []
    case("uninstall_restores_path_byte_for_byte", out["exit_code"] == 0 and after == before
         and not record.exists() and not (root_of(d1) / "installed.json").exists()
         and all(name.endswith(".uninstalled") for name in leftovers)
         and user_file.read_text(encoding="utf-8") == "keep me",
         run=out, path_before=before, path_after=after, bin_leftovers=leftovers)

    # 5. --yes with --no-modify-path: installs, PATH untouched, plan says skipped.
    d2 = work / "d2"
    out = run([cli, "install", "--yes", "--no-modify-path"], env_for(d2, home))
    case("yes_no_modify_path", out["exit_code"] == 0 and "PATH: unchanged" in out["stdout_tail"]
         and (root_of(d2) / "installed.json").is_file() and not (root_of(d2) / "path-change.json").exists()
         and path_target_state(home) == before, run=out)

    # 6. AXIOM_INSTALL_YES=1 equals --yes (fresh root, PATH added, then removed by uninstall --yes).
    d3 = work / "d3"
    out = run([cli, "install"], env_for(d3, home, {"AXIOM_INSTALL_YES": "1"}))
    ok_add = out["exit_code"] == 0 and (root_of(d3) / "path-change.json").is_file()
    un = run([root_of(d3) / "bin" / f"axiom-cli{EXE}", "uninstall", "--yes"], env_for(d3, home), cwd=work)
    case("env_yes_equals_flag", ok_add and un["exit_code"] == 0 and path_target_state(home) == before,
         install=out, uninstall=un)

    # 7. Automation unchanged: --dry-run then --apply --approve-digest, no PATH change in the plan.
    d4 = work / "d4"
    dry = subprocess.run([str(cli), "install", "--dry-run", "--json"], env=env_for(d4, home), capture_output=True, text=True)
    digest = json.loads(dry.stdout)["details"]["plan_digest"] if dry.returncode == 0 else ""
    out = run([cli, "install", "--apply", "--approve-digest", digest], env_for(d4, home))
    case("automation_unchanged", dry.returncode == 0 and '"path_change"' not in dry.stdout and out["exit_code"] == 0
         and not (root_of(d4) / "path-change.json").exists() and path_target_state(home) == before, run=out)

    if WINDOWS:
        reg("delete", r"HKCU\Software\AxiomCliTest", "/f")
    real_after = real_user_path()
    case("real_user_path_untouched", real_before == real_after)

    doc = {"task_id": "L-003", "host": {"system": platform.system(), "machine": platform.machine(),
                                        "release": platform.release(), "python": platform.python_version()},
           "cli_sha256": sha(args.cli), "path_target": ("HKCU\\" + TEST_KEY) if WINDOWS else "HOME/.profile (work dir)",
           "cases": cases, "passed": all(c["passed"] for c in cases)}
    print(json.dumps(doc, indent=2))
    return 0 if doc["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
