#!/usr/bin/env python3
"""Native K-404 transaction proof using real wheel, lock and runtime bytes."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PROVISIONER = ROOT / "packaging/linux/Provision-McpRuntime.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], expected: int = 0) -> dict:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PIP_CONFIG_FILE": os.devnull,
    }
    result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    if result.returncode != expected:
        raise AssertionError(
            f"exit {result.returncode}, expected {expected}: {result.stdout[-300:]} {result.stderr[-300:]}"
        )
    return json.loads(result.stdout if expected == 0 else result.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "wheelhouse", "wheel", "lock"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="axiom-k404-native-") as temporary:
        temp = Path(temporary)
        root = temp / "owned"
        root.mkdir()
        user_file = root / "user-data.txt"
        user_file.write_text("keep me\n")

        def provision(**changes: object) -> dict:
            options = {
                name: getattr(args, name)
                for name in ("runtime", "wheelhouse", "wheel", "lock")
            }
            options.update(changes)
            cmd = [
                sys.executable,
                str(PROVISIONER),
                "provision",
                "--root",
                str(root),
                "--version",
                "0.1.0",
                "--source-revision",
                args.source_revision,
            ]
            for name in ("runtime", "wheelhouse", "wheel", "lock"):
                path = Path(options[name])
                cmd.extend(["--" + name, str(path), "--" + name + "-sha256", sha(path)])
            if changes.get("interrupt"):
                cmd.append("--interrupt-before-activate")
            return run(cmd, 9 if changes.get("interrupt") else 0)

        fresh = provision()
        assert fresh["status"] == "provisioned"
        first_pointer = (root / "current.json").read_bytes()
        assert Path(fresh["executable"]).is_file()
        assert Path(fresh["python"]).is_file()
        assert sha(Path(fresh["python"])) == fresh["python_sha256"]
        assert sha(Path(fresh["executable"])) == fresh["executable_sha256"]
        subprocess.run(
            [fresh["python"], "-c", "import axiom_mcp, mcp, fastapi"],
            env={"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"},
            check=True,
        )
        subprocess.run(
            [fresh["python"], "-m", "pip", "check"],
            env={"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"},
            check=True,
        )
        repeated = provision()
        assert repeated["status"] == "already_current"
        assert (root / "current.json").read_bytes() == first_pointer

        corrupt = temp / "corrupt-runtime.tar.gz"
        data = bytearray(args.runtime.read_bytes())
        data[-1] ^= 1
        corrupt.write_bytes(data)
        # The declared digest stays the original, so corruption must be refused
        # before touching the current pointer.
        corrupt_cmd = [
            sys.executable,
            str(PROVISIONER),
            "provision",
            "--root",
            str(root),
            "--version",
            "0.1.0",
            "--source-revision",
            args.source_revision,
        ]
        for name in ("runtime", "wheelhouse", "wheel", "lock"):
            path = corrupt if name == "runtime" else getattr(args, name)
            corrupt_cmd.extend(
                [
                    "--" + name,
                    str(path),
                    "--" + name + "-sha256",
                    sha(getattr(args, name)),
                ]
            )
        assert "differs from its declared SHA-256" in run(corrupt_cmd, 9)["reason"]
        assert (root / "current.json").read_bytes() == first_pointer
        base_cmd = corrupt_cmd.copy()
        runtime_index = base_cmd.index("--runtime")
        base_cmd[runtime_index + 1] = str(args.runtime)

        corrupt_wheel = temp / args.wheel.name
        wheel_bytes = bytearray(args.wheel.read_bytes())
        wheel_bytes[len(wheel_bytes) // 2] ^= 1
        corrupt_wheel.write_bytes(wheel_bytes)
        wheel_cmd = base_cmd.copy()
        wheel_index = wheel_cmd.index("--wheel")
        wheel_cmd[wheel_index + 1] = str(corrupt_wheel)
        assert "differs from its declared SHA-256" in run(wheel_cmd, 9)["reason"]
        assert (root / "current.json").read_bytes() == first_pointer

        unsupported = temp / "unsupported.tar.gz"
        with tarfile.open(unsupported, "w:gz") as archive:
            payload = b"#!/bin/sh\necho 3.12\n"
            row = tarfile.TarInfo("candidate/bin/python3.13")
            row.mode = 0o755
            row.size = len(payload)
            archive.addfile(row, io.BytesIO(payload))
        # Run the unsupported archive with its own hash, keeping the pinned
        # generation active when its interpreter reports Python 3.12.
        unsupported_cmd = base_cmd.copy()
        index = unsupported_cmd.index("--runtime")
        unsupported_cmd[index + 1] = str(unsupported)
        unsupported_cmd[index + 3] = sha(unsupported)
        assert "unsupported" in run(unsupported_cmd, 9)["reason"]
        assert (root / "current.json").read_bytes() == first_pointer

        missing = temp / "missing-mcp.tar.gz"
        with (
            tarfile.open(args.wheelhouse, "r:gz") as source,
            tarfile.open(missing, "w:gz") as target,
        ):
            for row in source:
                if "mcp-1.28.1" not in row.name:
                    target.addfile(
                        row, source.extractfile(row) if row.isfile() else None
                    )
        missing_cmd = base_cmd.copy()
        index = missing_cmd.index("--wheelhouse")
        missing_cmd[index + 1] = str(missing)
        missing_cmd[index + 3] = sha(missing)
        refused = run(missing_cmd, 9)
        assert "No matching distribution found for mcp==1.28.1" in refused["reason"], (
            refused
        )
        assert (root / "current.json").read_bytes() == first_pointer

        changed_lock = temp / "requirements.txt"
        changed_lock.write_bytes(
            args.lock.read_bytes() + b"\n# K-404 second generation\n"
        )
        interrupted = provision(lock=changed_lock, interrupt=True)
        assert "interruption" in interrupted["reason"]
        assert (root / "current.json").read_bytes() == first_pointer
        second = provision(lock=changed_lock)
        assert second["generation"] != fresh["generation"]
        second_pointer = (root / "current.json").read_bytes()
        first_launcher = root / "versions" / fresh["generation"] / "venv/bin/axiom-mcp"
        original_launcher = first_launcher.read_bytes()
        first_launcher.write_bytes(b"tampered launcher")
        refused_rollback = run(
            [sys.executable, str(PROVISIONER), "rollback", "--root", str(root)], 9
        )
        assert "digest changed" in refused_rollback["reason"]
        assert (root / "current.json").read_bytes() == second_pointer
        first_launcher.write_bytes(original_launcher)
        restored = run(
            [sys.executable, str(PROVISIONER), "rollback", "--root", str(root)]
        )
        assert restored["generation"] == fresh["generation"]
        assert user_file.read_text() == "keep me\n"
        removed = run([sys.executable, str(PROVISIONER), "remove", "--root", str(root)])
        assert removed["status"] == "removed" and len(removed["owned_generations"]) == 2
        assert user_file.read_text() == "keep me\n"
        print(
            json.dumps(
                {
                    "ok": True,
                    "fresh": fresh["generation"],
                    "second": second["generation"],
                    "cases": [
                        "clean-provision",
                        "idempotency",
                        "corrupt-runtime",
                        "corrupt-wheel",
                        "unsupported-interpreter",
                        "missing-dependency",
                        "interrupted-provision",
                        "runtime-rollback",
                        "owned-removal",
                    ],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
