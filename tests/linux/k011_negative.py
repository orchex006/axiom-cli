#!/usr/bin/env python3
"""Run the K-406 refusal matrix on a fresh K-011 volume.

Graphd intentionally retains an inactive candidate generation after rollback.
This wrapper checks its bytes and active state rather than requiring deletion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import k406_negative as previous


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: argparse.Namespace) -> dict:
    original = previous.snapshot
    baseline = original(args.home)
    candidate = args.home / ".local/share/axiom/installs/ecosystem/versions/0.1.1/bin/axiom-graphd"
    expected = sha(args.kit / "release/axiom-graphd")
    cli_candidate = args.home / ".local/share/axiom-cli/generations/0.1.1-a58fee41a243/axiom-cli"
    cli_expected = sha(args.kit / "release/axiom-cli")

    def snapshot(home: Path) -> dict:
        state = original(home)
        generations = state.pop("engine_generations")
        cli_generations = state.pop("cli_generations")
        if not set(generations).issubset({"0.1.0", "0.1.1"}):
            raise ValueError(f"unexpected engine generation: {generations}")
        if "0.1.1" in generations and sha(candidate) != expected:
            raise ValueError("inactive candidate digest differs from pinned kit")
        if not set(cli_generations).issubset({"0.1.0-6a0a98edf256", "0.1.1-a58fee41a243"}):
            raise ValueError(f"unexpected CLI generation: {cli_generations}")
        if "0.1.1-a58fee41a243" in cli_generations and sha(cli_candidate) != cli_expected:
            raise ValueError("inactive CLI candidate digest differs from pinned kit")
        return state

    previous.snapshot = snapshot
    try:
        result = previous.run(args)
    finally:
        previous.snapshot = original
    result["retained_candidate"] = {
        "path": str(candidate),
        "sha256": sha(candidate) if candidate.exists() else None,
        "expected_sha256": expected,
        "active_engine_pointer_unchanged": original(args.home)["engine"] == baseline["engine"],
        "engine_generations": original(args.home)["engine_generations"],
        "cli_generations": original(args.home)["cli_generations"],
        "cli_sha256": sha(cli_candidate) if cli_candidate.exists() else None,
        "cli_expected_sha256": cli_expected,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--incompatible-kit", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    print(json.dumps(run(parser.parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
