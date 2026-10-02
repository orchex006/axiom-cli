#!/usr/bin/env python3
"""WSL negative boundaries using exact kit bytes and actual home-dependent IDs."""
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
    allowed_cli = set(baseline['cli_generations'])
    expected_cli = sha(args.kit/'release/axiom-cli')
    expected_core = sha(args.kit/'release/axiom-graphd')
    root = args.home/'.local/share/axiom'
    cli_root = args.home/'.local/share/axiom-cli/generations'

    def snapshot(home: Path) -> dict:
        state = original(home)
        engines = set(state.pop('engine_generations'))
        cli = set(state.pop('cli_generations'))
        assert engines <= {'0.1.0','0.1.1'}, 'unexpected engine generation'
        if '0.1.1' in engines:
            assert sha(root/'installs/ecosystem/versions/0.1.1/bin/axiom-graphd') == expected_core
        for generation in cli - allowed_cli:
            assert generation.startswith('0.1.1-'), 'unexpected CLI generation'
            assert sha(cli_root/generation/'axiom-cli') == expected_cli, 'retained candidate changed'
        return state

    previous.snapshot = snapshot
    try:
        result = previous.run(args)
    finally:
        previous.snapshot = original
    result['inactive_candidate_verified'] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--incompatible-kit', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    print(json.dumps(run(parser.parse_args()),sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
