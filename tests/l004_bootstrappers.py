#!/usr/bin/env python3
"""L-004 real-host harness (Windows x64 lane): the exact `irm …/install.ps1 | iex` one-liner.

Builds staged releases from an extracted release directory plus the CLI under test, serves them
from a local HTTP server laid out like GitHub release downloads (`<base>/<tag>/<asset>`), generates
the bootstrappers with `packaging/oneline/generate_bootstrappers.py --base-url <server>`, and runs
them through Windows PowerShell exactly as a user would. Per-user data, TEMP and the PATH target
are redirected into the work directory / an HKCU test key, so the real account is not changed.

    python tests/l004_bootstrappers.py --release <extracted-release> --cli target/release/axiom-cli.exe --work <short-dir>
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "packaging" / "oneline" / "generate_bootstrappers.py"
TEST_KEY = r"Software\AxiomCliTest\L004"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_zip(release: Path, cli: Path, out: Path) -> bytes:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(release.rglob("*")):
            rel = path.relative_to(release).as_posix()
            if path.is_dir() or rel.startswith("axiom-") and rel.endswith((".zip", ".tar.gz")) or rel == "axiom-cli.exe":
                continue
            archive.write(path, rel)
        archive.write(cli, "axiom-cli.exe")
    return out.read_bytes()


def publish(base: Path, tag: str, served: bytes, digest: str, base_url: str) -> None:
    """Lay out `<base>/<tag>/` with the archive bytes and scripts that embed `digest`."""
    version = tag[1:]
    directory = base / tag
    directory.mkdir(parents=True, exist_ok=True)
    asset = f"axiom-{version}-windows-x64.zip"
    (directory / asset).write_bytes(served)
    sums = f"{digest}  {asset}\n{'0' * 64}  axiom-{version}-linux-x64.tar.gz\n{'0' * 64}  axiom-{version}-macos-x64.tar.gz\n"
    (directory / "SHA256SUMS").write_text(sums, encoding="utf-8")
    subprocess.run([sys.executable, str(GENERATOR), "--tag", tag, "--sums", str(directory / "SHA256SUMS"),
                    "--out", str(directory), "--base-url", base_url], check=True, capture_output=True)


def serve(directory: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def reg(*args):
    return subprocess.run(["reg", *args], capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--cli", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    if os.name != "nt":
        print(json.dumps({"task_id": "L-004", "lane": "windows-x64", "status": "not_run", "reason": "not a Windows host"}))
        return 0
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    (work / "srv").mkdir(parents=True)
    good = build_zip(args.release, args.cli, work / "staged.zip")
    good_sha = sha(good)
    server = serve(work / "srv")
    base = f"http://127.0.0.1:{server.server_address[1]}"
    T = {n: f"v0.1.3-l004.{n}" for n in range(1, 6)}
    publish(work / "srv", T[1], good, good_sha, base)                    # normal
    publish(work / "srv", T[2], good, good_sha, base)                    # pin target
    publish(work / "srv", T[3], good + b"tamper", good_sha, base)        # tampered bytes
    publish(work / "srv", T[4], good[: len(good) // 2], good_sha, base)  # truncated bytes
    broken = good[: len(good) // 2]
    publish(work / "srv", T[5], broken, sha(broken), base)               # digest matches, zip broken
    dead = work / "srv-dead"
    publish(dead, "v0.1.3-l004.9", good, good_sha, "http://127.0.0.1:9")
    reg("delete", r"HKCU\Software\AxiomCliTest", "/f")
    reg("add", "HKCU\\" + TEST_KEY, "/v", "Path", "/t", "REG_EXPAND_SZ", "/d", r"%USERPROFILE%\tools", "/f")
    real_before = reg("query", r"HKCU\Environment", "/v", "Path").stdout
    cases = []

    def run(name, command, extra=None):
        data = work / name
        temp = work / f"tmp-{name}"
        temp.mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("AXIOM")}
        env.update(LOCALAPPDATA=str(data), TEMP=str(temp), TMP=str(temp), AXIOM_CLI_TEST_USER_ENV_KEY=TEST_KEY)
        env.update(extra or {})
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-c", command],
                              env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
        root = data / "Axiom"
        return {"command": command, "exit_code": proc.returncode, "stdout_tail": proc.stdout[-1500:],
                "stderr_tail": proc.stderr[-1500:], "installed": (root / "installed.json").is_file(),
                "root_exists": root.exists(), "path_record": (root / "path-change.json").is_file(),
                "temp_leftovers": sorted(p.name for p in temp.iterdir())}

    def case(name, passed, **detail):
        cases.append({"case": name, "passed": bool(passed), **detail})

    url = lambda tag: f"{base}/{tag}/install.ps1"  # noqa: E731
    r = run("oneliner", f"irm {url(T[1])} | iex", {"AXIOM_INSTALL_YES": "1"})
    case("oneliner_installs_embedded_version", r["exit_code"] == 0 and r["installed"] and r["path_record"]
         and not r["temp_leftovers"], run=r)
    r = run("switches", f"& ([scriptblock]::Create((irm {url(T[1])}))) -Yes -NoModifyPath")
    case("yes_and_no_modify_path_pass_through", r["exit_code"] == 0 and r["installed"] and not r["path_record"]
         and not r["temp_leftovers"], run=r)
    r = run("pin", f"& ([scriptblock]::Create((irm {url(T[1])}))) -Yes -NoModifyPath -Version {T[2][1:]}")
    case("version_pin_runs_that_tags_installer", r["exit_code"] == 0 and r["installed"]
         and f"using the {T[2]} installer" in r["stdout_tail"] and f"downloading {T[2]}" in r["stdout_tail"]
         and not r["temp_leftovers"], run=r)
    r = run("noyes", f"irm {url(T[1])} | iex")
    case("no_terminal_without_yes_changes_nothing", r["exit_code"] != 0 and not r["root_exists"]
         and not r["temp_leftovers"] and "exited 4" in r["stderr_tail"], run=r)
    r = run("tampered", f"irm {url(T[3])} | iex", {"AXIOM_INSTALL_YES": "1"})
    case("tampered_archive_refused", r["exit_code"] != 0 and not r["root_exists"] and "SHA-256 mismatch" in r["stderr_tail"]
         and not r["temp_leftovers"], run=r)
    r = run("truncated", f"irm {url(T[4])} | iex", {"AXIOM_INSTALL_YES": "1"})
    case("truncated_archive_refused", r["exit_code"] != 0 and not r["root_exists"] and "SHA-256 mismatch" in r["stderr_tail"]
         and not r["temp_leftovers"], run=r)
    r = run("broken", f"irm {url(T[5])} | iex", {"AXIOM_INSTALL_YES": "1"})
    case("unextractable_archive_refused", r["exit_code"] != 0 and not r["root_exists"]
         and "could not be extracted" in r["stderr_tail"] and not r["temp_leftovers"], run=r)
    dead_script = (dead / "v0.1.3-l004.9" / "install.ps1").as_posix()
    r = run("network", f"& ([scriptblock]::Create((Get-Content -Raw '{dead_script}'))) -Yes")
    case("network_failure_refused", r["exit_code"] != 0 and not r["root_exists"] and "download failed" in r["stderr_tail"]
         and not r["temp_leftovers"], run=r)
    r = run("arch", f"irm {url(T[1])} | iex", {"AXIOM_INSTALL_YES": "1", "PROCESSOR_ARCHITECTURE": "ARM64", "PROCESSOR_ARCHITEW6432": ""})
    case("unsupported_architecture_refused", r["exit_code"] != 0 and not r["root_exists"]
         and "unsupported architecture" in r["stderr_tail"], run=r)
    sh = shutil.which("sh")
    if sh:
        proc = subprocess.run([sh, str(work / "srv" / T[1] / "install.sh"), "--yes"], capture_output=True, text=True)
        case("install_sh_refuses_unsupported_os", proc.returncode != 0 and "unsupported platform" in proc.stderr,
             run={"exit_code": proc.returncode, "stderr_tail": proc.stderr[-400:]})
    regen = work / "regen"
    subprocess.run([sys.executable, str(GENERATOR), "--tag", T[1], "--sums", str(work / "srv" / T[1] / "SHA256SUMS"),
                    "--out", str(regen), "--base-url", base], check=True, capture_output=True)
    case("generator_is_deterministic", all((regen / n).read_bytes() == (work / "srv" / T[1] / n).read_bytes()
                                          for n in ("install.ps1", "install.sh")),
         sha256={n: sha((regen / n).read_bytes()) for n in ("install.ps1", "install.sh")})
    cases.append({"case": "elevated_run_refused", "passed": None, "status": "not_run",
         "reason": "an elevated PowerShell cannot be started non-interactively on this host (UAC); the script checks "
                "WindowsBuiltInRole::Administrator and the CLI checks TokenElevation before any change"})
    server.shutdown()
    reg("delete", r"HKCU\Software\AxiomCliTest", "/f")
    case("real_user_path_untouched", reg("query", r"HKCU\Environment", "/v", "Path").stdout == real_before)
    doc = {"task_id": "L-004", "lane": "windows-x64",
           "host": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
           "cli_sha256": sha(args.cli.read_bytes()), "staged_archive_sha256": good_sha, "cases": cases,
           "passed": all(c["passed"] for c in cases if c["passed"] is not None),
           "not_run": [c["case"] for c in cases if c["passed"] is None]}
    print(json.dumps(doc, indent=2))
    return 0 if doc["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
