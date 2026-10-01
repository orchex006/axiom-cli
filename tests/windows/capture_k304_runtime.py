"""Capture native Windows K-304 runtime, refusal and rollback evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "packaging/windows/Provision-McpRuntime.ps1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--pip-wheel", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--alternate-inputs", type=Path, required=True)
    parser.add_argument("--missing-inputs", type=Path, required=True)
    parser.add_argument("--unsupported-runtime", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    scratch = args.scratch.resolve()
    if scratch.exists() or sys.platform != "win32":
        raise SystemExit("K-304 requires a new scratch root on native Windows")
    scratch.mkdir(parents=True)
    home = scratch / "user-home"
    home.mkdir()
    sentinel = home / "user-data" / "sentinel.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("human data remains\n", encoding="utf-8", newline="\n")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env = dict(os.environ, PATH=os.pathsep.join((str(system_root / "System32"),
                                               str(system_root / "System32/WindowsPowerShell/v1.0"))), PYTHONPATH="",
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    inputs = {"runtime": args.runtime.resolve(), "pip": args.pip_wheel.resolve(),
              "bundle": args.inputs.resolve()}
    transcript = []

    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            return value.replace(str(scratch), "<isolated-root>")
        return value

    def invoke(case: str, action: str, expected: int, *, runtime: Path | None = None,
               bundle: Path | None = None, interrupt: bool = False) -> dict:
        used_runtime = runtime or inputs["runtime"]
        used_bundle = bundle or inputs["bundle"]
        argv = [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                "-Action", action, "-Root", str(home), "-RuntimeArchive", str(used_runtime),
                "-RuntimeSha256", digest(used_runtime)]
        if action == "provision":
            argv += ["-PipWheel", str(inputs["pip"]), "-PipSha256", digest(inputs["pip"]),
                     "-Inputs", str(used_bundle), "-InputsSha256", digest(used_bundle),
                     "-SourceRevision", args.source_revision, "-Version", "0.1.1"]
            if interrupt:
                argv.append("-InterruptBeforeActivate")
        result = subprocess.run(argv, env=env, cwd=scratch, capture_output=True, timeout=240)
        output = result.stdout.decode("utf-8", errors="replace").strip()
        error = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode != expected:
            raise AssertionError(f"{case}: exit {result.returncode} != {expected}: {error[-350:]}")
        try:
            value = json.loads(output or error.splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise AssertionError(f"{case}: no JSON result: {output[-100:]} {error[-100:]}") from exc
        transcript.append({"case": case, "action": action, "exit_code": result.returncode,
                           "expected_exit_code": expected, "runtime_sha256": digest(used_runtime),
                           "inputs_sha256": digest(used_bundle), "result": scrub(value)})
        return value

    first = invoke("clean-provision", "provision", 0)
    assert first["status"] == "provisioned" and first["source_revision"] == args.source_revision
    initial = first["generation"]
    assert (home / "mcp-runtime/versions" / initial / "venv/Scripts/python.exe").is_file()
    assert invoke("idempotency", "provision", 0)["status"] == "already_current"
    assert invoke("status", "status", 0)["generation"] == initial

    corrupt = scratch / "corrupt-runtime.zip"
    shutil.copyfile(inputs["runtime"], corrupt)
    with corrupt.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        original = stream.read(1)
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes([original[0] ^ 1]))
    # A byte-mismatched archive must fail the approved digest before any stage.
    bad = [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
           "-Action", "provision", "-Root", str(home), "-RuntimeArchive", str(corrupt),
           "-RuntimeSha256", digest(inputs["runtime"])]
    refusal = subprocess.run(bad, env=env, cwd=scratch, capture_output=True, timeout=30)
    assert refusal.returncode == 9 and b"digest mismatch" in refusal.stderr
    transcript.append({"case": "corrupt-runtime", "action": "provision", "exit_code": 9,
                       "expected_exit_code": 9, "reason": "runtime input digest mismatch"})

    unsupported = invoke("unsupported-interpreter", "provision", 9,
                         runtime=args.unsupported_runtime.resolve())
    assert "pinned Windows policy" in unsupported["reason"]
    missing = invoke("missing-dependency", "provision", 9,
                     bundle=args.missing_inputs.resolve())
    assert "missing members" in missing["reason"]
    assert invoke("after-refusals", "status", 0)["generation"] == initial

    alternate = args.alternate_inputs.resolve()
    interrupted = invoke("interrupted-provision", "provision", 9,
                         bundle=alternate, interrupt=True)
    assert "injected interruption" in interrupted["reason"]
    assert invoke("after-interruption", "status", 0)["generation"] == initial
    second = invoke("candidate-b", "provision", 0, bundle=alternate)
    assert second["generation"] != initial and second["status"] == "provisioned"
    assert invoke("runtime-rollback", "rollback", 0)["generation"] == initial
    assert sentinel.read_text(encoding="utf-8") == "human data remains\n"
    removed = invoke("owned-removal", "remove", 0)
    assert len(removed["owned_generations"]) == 2
    assert sentinel.read_text(encoding="utf-8") == "human data remains\n"
    assert not (home / "mcp-runtime/current.json").exists()
    assert not (home / "mcp-runtime/versions").exists()
    report = {"ok": True, "lane": "windows-x64", "source_revision": args.source_revision,
              "cases": transcript, "user_data_preserved": True, "certified": False}
    (scratch / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "cases": len(transcript), "user_data_preserved": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
