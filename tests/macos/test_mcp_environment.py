#!/usr/bin/env python3
"""Run the bundled MCP installer under an isolated HOME and system-only PATH."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--next-bundle", type=Path)
    args = parser.parse_args()
    cases = []
    launches = []
    with tempfile.TemporaryDirectory(prefix="axiom-k002-clean-") as name:
        home = Path(name) / "home"
        home.mkdir()
        environment = {"HOME": str(home), "PATH": "/usr/bin:/bin", "SHELL": "/bin/zsh"}

        def invoke(bundle: Path, action: str, *options: str, expected: int = 0) -> dict:
            script = bundle / "Manage-McpEnvironment.sh"
            argv = ["/bin/sh", str(script), action, "--bundle", str(bundle), *options]
            result = subprocess.run(argv, env=environment, text=True, capture_output=True, check=False)
            if result.returncode != expected:
                raise AssertionError(f"{action}: exit {result.returncode}, stdout {result.stdout[-300:]}, stderr {result.stderr[-300:]}")
            answer = json.loads(result.stdout)
            cases.append({"action": action, "exit_code": result.returncode, "status": answer["status"], **({"reason": answer["reason"]} if "reason" in answer else {})})
            return answer

        plan = invoke(args.bundle, "install", "--dry-run")
        invoke(args.bundle, "install", "--apply", "--approve-digest", "0" * 64, expected=9)
        root = home / ".local/share/axiom/mcp"
        root.mkdir(parents=True)
        pointer = root / "current.json"
        pointer.symlink_to(root / "missing-pointer-target")
        assert invoke(args.bundle, "install", "--apply", "--approve-digest", plan["plan_digest"], expected=9)["reason"] == "active_pointer_changed"
        pointer.unlink()
        installed = invoke(args.bundle, "install", "--apply", "--approve-digest", plan["plan_digest"])
        assert installed["previous"] is None
        assert installed["active"] == sha(args.bundle / "mcp-bundle.json")
        result = subprocess.run([installed["mcp_executable"], "version", "--json"], env=environment, text=True, capture_output=True, check=False)
        assert result.returncode == 0 and json.loads(result.stdout)["version"] == "0.1.0"
        cases.append({"action": "installed_wheel_version", "exit_code": result.returncode, "status": "ok"})

        def owner_launch(active: dict) -> dict:
            # Import and resolve the owner's locked launch contract from the
            # provisioned wheel. No checkout path or activated shell is present.
            result = subprocess.run(
                [active["python"], "-c",
                 "import json,sys; from axiom_mcp.entrypoints import MODE_STDIO,launch_plan; "
                 "print(json.dumps(launch_plan(MODE_STDIO,install_root=sys.argv[1]).as_dict()))",
                 str(root)], env=environment, text=True, capture_output=True, check=False,
            )
            assert result.returncode == 0, result.stderr[-500:]
            plan = json.loads(result.stdout)
            assert plan["runtime"]["isolated"] and plan["runtime"]["sdk_inside_environment"]
            assert plan["executable"] == str((root / "versions" / active["active"] / "venv/bin/python").resolve())
            assert plan["arguments"][:2] == ["-m", "axiom_mcp.stdio"]
            launches.append({"generation": active["active"], "plan_digest": plan["digest"],
                             "executable_sha256": sha(Path(plan["executable"])),
                             "lockfile_sha256": plan["runtime"]["lockfile_sha256"],
                             "sdk_version": plan["runtime"]["sdk_version"]})
            cases.append({"action": "owner_locked_stdio_launch", "exit_code": 0, "status": "ok"})
            return plan

        initial_launch = owner_launch(installed)
        invoke(args.bundle, "status")
        rerun = invoke(args.bundle, "install", "--apply", "--approve-digest", plan["plan_digest"])
        assert rerun["active"] == installed["active"]

        installed_artifact = home / ".local/share/axiom/mcp/versions" / installed["active"] / "artifact/axiom_mcp-0.1.0-py3-none-any.whl"
        original = installed_artifact.read_bytes()
        altered = bytearray(original)
        altered[-1] ^= 1
        installed_artifact.write_bytes(altered)
        assert invoke(args.bundle, "status", expected=9)["reason"] == "owner_wheel_changed"
        installed_artifact.write_bytes(original)
        invoke(args.bundle, "status")

        launch_lock = root / "versions" / installed["active"] / "lockfile.json"
        lock_original = launch_lock.read_bytes()
        launch_lock.write_bytes(lock_original + b" ")
        assert invoke(args.bundle, "status", expected=9)["reason"] == "entrypoint_lock_changed"
        launch_lock.write_bytes(lock_original)
        owner_launch(installed)

        venv = root / "versions" / installed["active"] / "venv"
        scripts = venv / "bin"
        moved_scripts = venv / "bin-temporary"
        scripts.rename(moved_scripts)
        scripts.symlink_to(moved_scripts, target_is_directory=True)
        assert invoke(args.bundle, "status", expected=9)["reason"] == "environment_path_changed"
        scripts.unlink()
        moved_scripts.rename(scripts)

        active_bundle = args.bundle
        if args.next_bundle is not None:
            second = invoke(args.next_bundle, "install", "--dry-run")
            upgraded = invoke(args.next_bundle, "install", "--apply", "--approve-digest", second["plan_digest"])
            assert upgraded["previous"] == installed["active"] and upgraded["active"] != upgraded["previous"]
            upgraded_launch = owner_launch(upgraded)
            assert upgraded_launch["digest"] != initial_launch["digest"]
            back = invoke(args.next_bundle, "rollback", "--to", installed["active"], "--dry-run")
            restored = invoke(args.next_bundle, "rollback", "--to", installed["active"], "--apply", "--approve-digest", back["plan_digest"])
            assert restored["active"] == installed["active"]
            restored_launch = owner_launch(restored)
            assert restored_launch["digest"] == initial_launch["digest"]
            active_bundle = args.next_bundle

        user_data = root / "data/user.txt"
        user_data.parent.mkdir(parents=True)
        user_data.write_text("preserve data\n")
        user_note = root / "versions" / installed["active"] / "user-note.txt"
        user_note.write_text("preserve note\n")
        deletion = invoke(active_bundle, "uninstall", "--dry-run")
        removed = invoke(active_bundle, "uninstall", "--apply", "--approve-digest", deletion["plan_digest"])
        assert removed["preserved_generations_with_unowned_files"] >= 1
        assert user_data.read_text() == "preserve data\n" and user_note.read_text() == "preserve note\n"
        assert invoke(active_bundle, "status")["active"] is None
    print(json.dumps({"ok": True, "bundle_manifest_sha256": sha(args.bundle / "mcp-bundle.json"),
                      "cases": cases, "owner_launches": launches}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
