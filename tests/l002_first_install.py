#!/usr/bin/env python3
"""L-002 real-host harness: first install through `axiom-cli install` into one per-user root.

Runs against an extracted release directory (the CLI under test is copied into it) with every
`AXIOM_*` variable removed and the per-user data directory redirected to a fresh work directory
(`LOCALAPPDATA` on Windows, `XDG_DATA_HOME` on POSIX), so the default root is exercised exactly as
on a clean account. Prints one JSON evidence document; exit 0 only when every case passes.

    python tests/l002_first_install.py --release <extracted-release> --cli target/release/axiom-cli[.exe] --work <short-dir>
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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def env_for(data_home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("AXIOM")}
    if WINDOWS:
        env["LOCALAPPDATA"] = str(data_home)
    else:
        env["XDG_DATA_HOME"] = str(data_home)
    return env


def root_of(data_home: Path) -> Path:
    return data_home / ("Axiom" if WINDOWS else "axiom")


def run(argv, env, cwd=None):
    proc = subprocess.run([str(a) for a in argv], env=env, cwd=cwd, capture_output=True, text=True)
    return {"argv": [str(a) for a in argv], "exit_code": proc.returncode,
            "stdout_tail": proc.stdout[-1500:], "stderr_tail": proc.stderr[-1500:]}


def plan_digest(cli: Path, env) -> str:
    proc = subprocess.run([str(cli), "install", "--dry-run", "--json"], env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"dry-run failed: {proc.stdout}{proc.stderr}")
    return json.loads(proc.stdout)["details"]["plan_digest"]


def install(cli: Path, env):
    digest = plan_digest(cli, env)
    return digest, run([cli, "install", "--apply", "--approve-digest", digest], env)


def stage(release: Path, cli: Path, target: Path, drop=()) -> Path:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(release, target, ignore=shutil.ignore_patterns("axiom-*-*.zip", "axiom-*-*.tar.gz"))
    shutil.copy2(cli, target / f"axiom-cli{EXE}")
    for name in drop:
        (target / name).unlink()
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
    cases = []

    def case(name, passed, **detail):
        cases.append({"case": name, "passed": bool(passed), **detail})

    # 1. Clean first install, then version and doctor from the installed bin without AXIOM_*.
    release = stage(args.release, args.cli, work / "rel")
    home = work / "u1"
    env = env_for(home)
    digest, applied = install(release / f"axiom-cli{EXE}", env)
    root = root_of(home)
    bin_dir = root / "bin"
    installed = root / "installed.json"
    record = json.loads(installed.read_text(encoding="utf-8")) if installed.is_file() else {}
    names = sorted(p.name for p in bin_dir.iterdir()) if bin_dir.is_dir() else []
    case("first_install", applied["exit_code"] == 0 and installed.is_file()
         and names == sorted(f"{n}{EXE}" for n in ("axiom", "axiom-cli", "axiom-graphd"))
         and all(c.get("sha256") for c in record.get("components", []))
         and (root / "recorded-manifest.json").is_file(),
         plan_digest=digest, apply=applied, bin=names,
         installed_json_sha256=sha(installed) if installed.is_file() else None,
         components=record.get("components"), root=str(root))
    if not bin_dir.is_dir():
        print(json.dumps({"task_id": "L-002", "cases": cases, "passed": False}, indent=2))
        return 1
    version = run([bin_dir / f"axiom-cli{EXE}", "version", "--json"], env, cwd=work)
    case("version_reports_installed", version["exit_code"] == 0 and '"installed"' in version["stdout_tail"]
         and record.get("current_generation", "?") in version["stdout_tail"], run=version)
    doctor = run([bin_dir / f"axiom-cli{EXE}", "doctor", "--json"], env, cwd=work)
    engine_sibling = '"source":"sibling"' in doctor["stdout_tail"].replace(" ", "") or "(sibling)" in doctor["stdout_tail"]
    case("doctor_finds_sibling_engine", engine_sibling and "no installed release" not in doctor["stdout_tail"],
         run=doctor, note="doctor exit code is recorded; the sqlite-driver item stays unverified (pre-existing, not L-002)")

    # 2. Re-run idempotence: same generation, unchanged bin, no predecessor recorded.
    before = {p.name: sha(p) for p in bin_dir.iterdir()}
    _, rerun = install(release / f"axiom-cli{EXE}", env)
    again = json.loads(installed.read_text(encoding="utf-8"))
    case("rerun_idempotent", rerun["exit_code"] == 0
         and again["current_generation"] == record.get("current_generation")
         and again.get("previous_generation") is None
         and before == {p.name: sha(p) for p in bin_dir.iterdir()}, apply=rerun)

    # 3. Interrupted install: the record cannot be written, then the next run recovers.
    home2 = work / "u2"
    env2 = env_for(home2)
    obstacle = root_of(home2) / "installed.json.tmp"
    obstacle.mkdir(parents=True)
    _, broken = install(release / f"axiom-cli{EXE}", env2)
    left = (root_of(home2) / "installed.json").exists()
    obstacle.rmdir()
    _, recovered = install(release / f"axiom-cli{EXE}", env2)
    case("interrupted_install_recovers", broken["exit_code"] != 0 and not left
         and recovered["exit_code"] == 0 and (root_of(home2) / "installed.json").is_file(),
         interrupted=broken, recovered=recovered)

    # 4. Tampered artifact refused before any placement.
    tampered = stage(args.release, args.cli, work / "rel-tampered")
    graphd = tampered / f"axiom-graphd{EXE}"
    graphd.write_bytes(graphd.read_bytes() + b"tamper")
    home3 = work / "u3"
    env3 = env_for(home3)
    dry = run([tampered / f"axiom-cli{EXE}", "install", "--dry-run", "--json"], env3)
    case("tampered_artifact_refused", dry["exit_code"] != 0 and "artifact_unverified" in (dry["stdout_tail"] + dry["stderr_tail"])
         and not (root_of(home3) / "bin").exists() and not (root_of(home3) / "installs").exists(), run=dry)

    # 5. Nonempty foreign root refused with conflict (6), nothing placed.
    home4 = work / "u4"
    env4 = env_for(home4)
    root_of(home4).mkdir(parents=True)
    (root_of(home4) / "my-notes.txt").write_text("user data", encoding="utf-8")
    _, foreign = install(release / f"axiom-cli{EXE}", env4)
    case("foreign_root_refused", foreign["exit_code"] == 6 and "holds entries no Axiom install writes" in foreign["stdout_tail"] + foreign["stderr_tail"]
         and sorted(p.name for p in root_of(home4).iterdir()) == ["my-notes.txt"]
         and (root_of(home4) / "my-notes.txt").read_text(encoding="utf-8") == "user data", apply=foreign)

    # 6. Missing engine reported as not found (3).
    noengine = stage(args.release, args.cli, work / "rel-noengine", drop=(f"axiom{EXE}",))
    home5 = work / "u5"
    env5 = env_for(home5)
    env5["PATH"] = os.pathsep.join(p for p in env5.get("PATH", "").split(os.pathsep)
                                   if not (Path(p) / f"axiom{EXE}").exists())
    _, missing = install(noengine / f"axiom-cli{EXE}", env5)
    case("missing_engine_not_found", missing["exit_code"] == 3 and "was not found" in missing["stdout_tail"] + missing["stderr_tail"]
         and not (root_of(home5) / "installs").exists(),
         apply=missing)

    doc = {"task_id": "L-002", "host": {"system": platform.system(), "machine": platform.machine(),
                                        "release": platform.release(), "python": platform.python_version()},
           "cli_sha256": sha(args.cli), "release": str(args.release), "cases": cases,
           "passed": all(c["passed"] for c in cases)}
    print(json.dumps(doc, indent=2))
    return 0 if doc["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
