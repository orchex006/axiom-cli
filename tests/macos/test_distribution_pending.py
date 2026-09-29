"""Focused recovery-boundary checks for the Mac distribution coordinator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


INSTALLER = (
    Path(__file__).resolve().parents[2] / "installers/macos/Install-Distribution.py"
)
SPEC = importlib.util.spec_from_file_location("axiom_distribution_installer", INSTALLER)
assert SPEC is not None and SPEC.loader is not None
distribution = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(distribution)


class PendingUpdateTests(unittest.TestCase):
    def test_recovery_refuses_a_foreign_candidate_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            release = root / "candidate"
            release.mkdir()
            (release / "release-set.json").write_text("{}\n")
            distribution.pending_update_path(root).write_text(
                json.dumps({
                    "schema_version": 1, "action": "update",
                    "release_set_sha256": "f" * 64, "before": {},
                    "engine_journals_before": [],
                }) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "does not bind this candidate"):
                distribution.pending_recovery(release, root)

    def test_recovery_refuses_a_foreign_new_engine_journal(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            journal_dir = root / "installs/ecosystem/journal"
            journal_dir.mkdir(parents=True)
            (journal_dir / "ecosystem-update-foreign.json").write_text(
                json.dumps({
                    "schema_version": 1, "kind": "ecosystem-update-journal",
                    "transaction_id": "foreign", "state": "finalized",
                    "previous_pointer_sha256": "a" * 64,
                    "candidate": {"core_artifacts": [{"sha256": "b" * 64}]},
                }) + "\n"
            )
            pending = {
                "action": "update", "before": {"engine_pointer_sha256": "c" * 64},
                "engine_journals_before": [],
            }
            checked = {"entry": {"artifacts": [{}, {}, {"sha256": "b" * 64}]}}
            with self.assertRaisesRegex(ValueError, "does not bind A and B"):
                distribution.recovery_transaction(root, pending, checked)

    def test_lock_rejects_a_second_coordinator_and_releases_on_close(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with distribution.update_lock(root):
                with self.assertRaisesRegex(ValueError, "another distribution update"):
                    with distribution.update_lock(root):
                        pass
            with distribution.update_lock(root):
                self.assertTrue((root / "distribution-update.lock").is_file())

    def test_pending_record_refuses_following_operations(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            distribution.atomic_text(
                distribution.pending_update_path(root), '{"schema_version":1}\n'
            )
            with self.assertRaisesRegex(ValueError, "recovery required"):
                distribution.refuse_pending_update(root)

    def test_early_failure_cleans_pending_after_verified_compensation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            home = base / "home"
            root = home / "owned"
            release = base / "candidate"
            root.mkdir(parents=True)
            release.mkdir()
            (release / "release-set.json").write_text(json.dumps({"artifacts": []}))
            runtime_pointer = root / "mcp-runtime/current.json"
            runtime_pointer.parent.mkdir()
            runtime_pointer.write_text('{"generation":"a"}\n')
            before = {
                "core_version": "0.1.0",
                "core_revision": "source-a",
                "cli_sha256": "a" * 64,
                "engine_cli_sha256": "b" * 64,
                "runtime_pointer_sha256": distribution.digest(runtime_pointer),
            }
            checked = {
                "entry": {
                    "artifacts": [{}, {}, {"version": "0.1.1", "revision": "source-b"}]
                },
                "runtime": {},
            }
            with (
                patch.object(distribution, "command", return_value={"exit_code": 0}),
                patch.object(
                    distribution, "installed_update_state", return_value=before
                ),
                patch.dict(distribution.os.environ, {"AXIOM_K106_FAIL_AT": "download"}),
            ):
                with self.assertRaisesRegex(ValueError, "acquisition failure"):
                    distribution.run_update(release, home, root, {}, checked, before)
            self.assertFalse(distribution.pending_update_path(root).exists())
            self.assertFalse((root / "distribution-update.json").exists())

    def test_provision_error_after_pointer_change_still_rolls_back_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            home = base / "home"
            root = home / "owned"
            release = base / "candidate"
            root.mkdir(parents=True)
            release.mkdir()
            (release / "release-set.json").write_text(json.dumps({"artifacts": []}))
            runtime_pointer = root / "mcp-runtime/current.json"
            runtime_pointer.parent.mkdir()
            runtime_pointer.write_text('{"generation":"a"}\n')
            before = {
                "core_version": "0.1.0",
                "core_revision": "source-a",
                "cli_sha256": "a" * 64,
                "engine_cli_sha256": "b" * 64,
                "runtime_pointer_sha256": distribution.digest(runtime_pointer),
            }
            checked = {
                "entry": {
                    "artifacts": [{}, {}, {"version": "0.1.1", "revision": "source-b"}]
                },
                "runtime": {
                    "mcp_version": "0.1.0",
                    "mcp_revision": "mcp-a",
                    "files": {
                        name: "c" * 64
                        for name in (
                            "python.tar.gz",
                            "wheelhouse.tar.gz",
                            "axiom_mcp-0.1.0-py3-none-any.whl",
                            "requirements.txt",
                        )
                    },
                },
            }
            rolled_back = []

            def interrupted_provision(argv: list[str], _env: dict) -> dict:
                if "provision" in argv:
                    runtime_pointer.write_text('{"generation":"b"}\n')
                    raise ValueError("provision interrupted after pointer move")
                if "rollback" in argv:
                    rolled_back.append(True)
                    runtime_pointer.write_text('{"generation":"a"}\n')
                return {"exit_code": 0}

            with (
                patch.object(
                    distribution, "command", side_effect=interrupted_provision
                ),
                patch.object(
                    distribution, "installed_update_state", return_value=before
                ),
            ):
                with self.assertRaisesRegex(ValueError, "provision interrupted"):
                    distribution.run_update(release, home, root, {}, checked, before)
            self.assertEqual(rolled_back, [True])
            self.assertEqual(
                distribution.digest(runtime_pointer), before["runtime_pointer_sha256"]
            )
            self.assertFalse(distribution.pending_update_path(root).exists())

    def test_unreported_engine_journal_keeps_pending_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            home = base / "home"
            root = home / "owned"
            release = base / "candidate"
            root.mkdir(parents=True)
            release.mkdir()
            (release / "release-set.json").write_text(json.dumps({"artifacts": []}))
            runtime_pointer = root / "mcp-runtime/current.json"
            runtime_pointer.parent.mkdir()
            runtime_pointer.write_text('{"generation":"a"}\n')
            before = {
                "core_version": "0.1.0",
                "core_revision": "source-a",
                "cli_sha256": "a" * 64,
                "engine_cli_sha256": "b" * 64,
                "runtime_pointer_sha256": distribution.digest(runtime_pointer),
            }
            checked = {
                "entry": {
                    "artifacts": [{}, {}, {"version": "0.1.1", "revision": "source-b"}]
                },
                "runtime": {
                    "mcp_version": "0.1.0",
                    "mcp_revision": "mcp-a",
                    "files": {
                        name: "c" * 64
                        for name in (
                            "python.tar.gz",
                            "wheelhouse.tar.gz",
                            "axiom_mcp-0.1.0-py3-none-any.whl",
                            "requirements.txt",
                        )
                    },
                },
            }

            def lost_engine_report(argv: list[str], _env: dict) -> dict:
                if argv[0].endswith("axiom-cli") and "--dry-run" in argv:
                    return {"exit_code": 0, "body": {"plan_digest": "d" * 64}}
                if argv[0].endswith("axiom-cli") and "--apply" in argv:
                    journal = root / "installs/ecosystem/journal"
                    journal.mkdir(parents=True)
                    (journal / "ecosystem-update-tx.json").write_text("{}\n")
                    raise ValueError("engine report lost")
                return {"exit_code": 0, "body": {}}

            with (
                patch.object(distribution, "command", side_effect=lost_engine_report),
                patch.object(
                    distribution, "installed_update_state", return_value=before
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError, "engine journal needs explicit recovery"
                ):
                    distribution.run_update(release, home, root, {}, checked, before)
            self.assertTrue(distribution.pending_update_path(root).is_file())
            with self.assertRaisesRegex(ValueError, "recovery required"):
                distribution.refuse_pending_update(root)


if __name__ == "__main__":
    unittest.main()
