#!/usr/bin/env python3
"""Native K-002 offline packaging proof using explicitly supplied source bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PACKAGER = ROOT / "packaging/macos/Build-McpBundle.py"
MCP_WHEEL = "axiom_mcp-0.1.0-py3-none-any.whl"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="axiom-k002-test-") as name:
        temporary = Path(name)

        def check(case: str, runtime: Path, wheel: Path, wheelhouse: Path, expected: int, reason: str | None = None) -> Path:
            output = temporary / case
            argv = [sys.executable, str(PACKAGER), "--runtime", str(runtime), "--mcp-wheel", str(wheel), "--wheel-dir", str(wheelhouse), "--out-dir", str(output)]
            result = subprocess.run(argv, text=True, capture_output=True, check=False)
            if result.returncode != expected or (reason and reason not in result.stderr):
                raise AssertionError(f"{case}: exit {result.returncode}, stderr {result.stderr[-500:]}")
            row = {"case": case, "exit_code": result.returncode}
            if expected == 0:
                report = json.loads(result.stdout)
                row.update(report)
                row["manifest_sha256_checked"] = sha(output / "mcp-bundle.json") == report["manifest_sha256"]
            else:
                row["reason"] = reason
            results.append(row)
            return output

        owner = args.wheels / MCP_WHEEL
        good = check("offline_venv_and_cli", args.runtime, owner, args.wheels, 0)
        manifest = json.loads((good / "mcp-bundle.json").read_text())
        assert len(manifest["artifacts"]) == 36
        assert all(sha(good / row["path"]) == row["sha256"] for row in manifest["artifacts"])
        corrupt = temporary / "corrupt" / MCP_WHEEL
        corrupt.parent.mkdir()
        data = bytearray(owner.read_bytes())
        data[-1] ^= 1
        corrupt.write_bytes(data)
        check("corrupt_owner_wheel", args.runtime, corrupt, args.wheels, 9, "pinned MCP wheel digest mismatch")
        check("corrupt_runtime", owner, owner, args.wheels, 9, "standalone CPython digest mismatch")
        missing = temporary / "missing-wheels"
        missing.mkdir()
        for path in sorted(args.wheels.glob("*.whl"))[1:]:
            shutil.copyfile(path, missing / path.name)
        check("missing_dependency_wheel", args.runtime, owner, missing, 9, "expected exactly 31 dependency wheels")
    print(json.dumps({"ok": True, "runtime_sha256": sha(args.runtime), "owner_wheel_sha256": sha(args.wheels / MCP_WHEEL), "cases": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
