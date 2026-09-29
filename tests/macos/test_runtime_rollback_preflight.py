"""Verify an MCP runtime rollback target before the engine pointer moves."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PROVISIONER = (
    Path(__file__).resolve().parents[2] / "packaging/macos/Provision-McpRuntime.py"
)
SPEC = importlib.util.spec_from_file_location("axiom_runtime_provisioner", PROVISIONER)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
INSTALLER = (
    Path(__file__).resolve().parents[2] / "installers/macos/Install-Distribution.py"
)
INSTALL_SPEC = importlib.util.spec_from_file_location(
    "axiom_distribution_installer", INSTALLER
)
assert INSTALL_SPEC is not None and INSTALL_SPEC.loader is not None
distribution = importlib.util.module_from_spec(INSTALL_SPEC)
INSTALL_SPEC.loader.exec_module(distribution)


class RollbackPreflightTests(unittest.TestCase):
    def test_engine_rollback_error_retains_durable_pending_record(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name).resolve()
            home = base / "home"
            root = home / "owned"
            release = base / "release"
            release.mkdir()
            retained = root / "entrypoints/versions" / ("a" * 64)
            retained.mkdir(parents=True)
            cli = retained / "axiom-cli"
            engine = retained / "axiom"
            cli.write_text("old cli")
            engine.write_text("old engine")
            receipt_path = root / "distribution-update.json"
            receipt_path.write_text('{"engine_transaction":"tx"}\n')
            before = {
                "release_set_sha256": "a" * 64,
                "cli_sha256": distribution.digest(cli),
                "engine_cli_sha256": distribution.digest(engine),
                "runtime_pointer_sha256": "b" * 64,
            }
            installed = {"runtime_pointer_sha256": "b" * 64}
            receipt = {
                "before": before,
                "engine_transaction": "tx",
                "release_set_sha256": "c" * 64,
            }
            with (
                patch.object(distribution, "rollback_receipt", return_value=receipt),
                patch.object(
                    distribution,
                    "command",
                    side_effect=ValueError("engine interrupted"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "engine interrupted"):
                    distribution.run_rollback(
                        release, home, root, {}, {"entry": {}}, installed
                    )
            pending = distribution.pending_update_path(root)
            self.assertEqual(json.loads(pending.read_text())["action"], "rollback")
            self.assertTrue(receipt_path.is_file())
            with self.assertRaisesRegex(ValueError, "recovery required"):
                distribution.refuse_pending_update(root)

    def test_distribution_refuses_changed_retained_runtime_before_engine(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name).resolve()
            home = base / "home"
            root = home / "owned"
            release = base / "release"
            release.mkdir()
            retained = root / "entrypoints/versions" / ("a" * 64)
            retained.mkdir(parents=True)
            cli = retained / "axiom-cli"
            engine = retained / "axiom"
            cli.write_text("old cli")
            engine.write_text("old engine")
            previous = root / "mcp-runtime/previous.json"
            previous.parent.mkdir(parents=True)
            previous.write_text('{"generation":"wrong"}\n')
            before = {
                "release_set_sha256": "a" * 64,
                "cli_sha256": distribution.digest(cli),
                "engine_cli_sha256": distribution.digest(engine),
                "runtime_pointer_sha256": "b" * 64,
            }
            installed = {"runtime_pointer_sha256": "c" * 64}
            receipt = {"before": before, "engine_transaction": "tx"}
            with (
                patch.object(distribution, "rollback_receipt", return_value=receipt),
                patch.object(distribution, "command") as command,
            ):
                with self.assertRaisesRegex(
                    ValueError, "missing or changed candidate input"
                ):
                    distribution.run_rollback(
                        release, home, root, {}, {"entry": {}}, installed
                    )
                command.assert_not_called()
            self.assertFalse(distribution.pending_update_path(root).exists())

    def test_dry_run_verifies_retained_executables_without_moving_pointers(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            records = []
            for generation in ("a" * 24, "b" * 24):
                version = root / "versions" / generation
                executable = version / "venv/bin/axiom-mcp"
                python = version / "venv/bin/python"
                executable.parent.mkdir(parents=True)
                (version / "owner.json").write_text("{}\n")
                executable.write_text("launcher " + generation)
                python.write_text("python " + generation)
                records.append(
                    {
                        "generation": generation,
                        "version": "0.1.0",
                        "executable_sha256": runtime.digest(executable),
                        "python_sha256": runtime.digest(python),
                        "wheel_sha256": "c" * 64,
                        "runtime_sha256": "d" * 64,
                        "wheelhouse_sha256": "e" * 64,
                        "lock_sha256": "f" * 64,
                    }
                )
            runtime.atomic_json(root / "previous.json", records[0])
            runtime.atomic_json(root / "current.json", records[1])
            current_before = (root / "current.json").read_bytes()
            previous_before = (root / "previous.json").read_bytes()
            planned = runtime.rollback(root, dry_run=True)
            self.assertEqual(planned["status"], "rollback_planned")
            self.assertEqual(planned["generation"], records[0]["generation"])
            cli = subprocess.run(
                [
                    sys.executable,
                    str(PROVISIONER),
                    "rollback",
                    "--root",
                    str(root),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(json.loads(cli.stdout)["status"], "rollback_planned")
            self.assertEqual((root / "current.json").read_bytes(), current_before)
            self.assertEqual((root / "previous.json").read_bytes(), previous_before)
            retained = (
                root / "versions" / records[0]["generation"] / "venv/bin/axiom-mcp"
            )
            retained.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "digest changed"):
                runtime.rollback(root, dry_run=True)
            self.assertEqual((root / "current.json").read_bytes(), current_before)


if __name__ == "__main__":
    unittest.main()
