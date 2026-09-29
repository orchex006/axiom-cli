#!/usr/bin/env python3
"""Native process-death recovery through the public distribution bootstrap."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.macos.test_distribution_update import distribution, state  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-a", required=True, type=Path)
    parser.add_argument("--candidate-b", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64") or os.getuid() == 0:
        raise SystemExit("native non-root Mac x64 host required")
    label = "com.axiom.axiom-graphd"
    if label in subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout:
        raise SystemExit("canonical LaunchAgent label is already registered")
    a, b = args.candidate_a.resolve(strict=True), args.candidate_b.resolve(strict=True)
    out = args.out.resolve()
    if out.exists():
        raise SystemExit("output already exists")
    with tempfile.TemporaryDirectory(prefix="axiom-k106-crash-") as name:
        home = Path(name) / "home"
        (home / "Library/LaunchAgents").mkdir(parents=True)
        (home / "user-data.txt").write_text("preserve crash recovery data\n")
        env = {**os.environ, "HOME": str(home), "SHELL": "/bin/zsh", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        trace: list[dict] = []
        root = home / ".local/share/axiom"
        try:
            plan = distribution(a, env, trace, "install", "--dry-run")
            distribution(a, env, trace, "install", "--apply", plan["plan_digest"])
            before = state(home)
            plan = distribution(b, env, trace, "update", "--dry-run")
            distribution(
                b, dict(env, AXIOM_K106_CRASH_AT="engine_report"), trace,
                "update", "--apply", plan["plan_digest"], expected=97,
            )
            pending = root / "distribution-update-pending.json"
            if not pending.is_file():
                raise AssertionError("process death did not leave durable pending intent")
            plan = distribution(b, env, trace, "recover", "--dry-run")
            recovered = distribution(b, env, trace, "recover", "--apply", plan["plan_digest"])
            after = state(home)
            if any(after[key] != value for key, value in before.items()):
                raise AssertionError("recovery did not restore exact A state")
            if pending.exists():
                raise AssertionError("completed recovery left a pending intent")
            plan = distribution(b, env, trace, "update", "--dry-run")
            distribution(b, env, trace, "update", "--apply", plan["plan_digest"])
            plan = distribution(b, env, trace, "rollback", "--dry-run")
            distribution(b, env, trace, "rollback", "--apply", plan["plan_digest"])
            if state(home) != before:
                raise AssertionError("retry and rollback did not restore A")
            plan = distribution(a, env, trace, "uninstall", "--dry-run")
            distribution(a, env, trace, "uninstall", "--apply", plan["plan_digest"])
            if (home / "user-data.txt").read_text() != "preserve crash recovery data\n":
                raise AssertionError("user data changed")
            result = {
                "status": "local_verified", "lane": "macos-x64", "certified": False,
                "crash_phase": "after_engine_report_before_transaction_capture",
                "recovery_status": recovered["status"], "exact_a_restored": True,
                "update_retry_and_rollback": True, "user_data_preserved": True,
            }
        finally:
            engine = home / ".local/bin/axiom"
            if engine.is_file():
                for action in ("stop", "uninstall"):
                    subprocess.run(
                        [str(engine), "service", action, "--component", "axiom-graphd", "--json"],
                        env=dict(env, AXIOM_HOME=str(root)), capture_output=True, text=True,
                    )
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                capture_output=True, text=True,
            )
        out.mkdir(parents=True)
        redacted = json.dumps(trace, indent=2).replace(name, "<isolated-test-root>")
        (out / "native-transcript.json").write_text(redacted + "\n")
        (out / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
