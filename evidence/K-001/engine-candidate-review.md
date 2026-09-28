# K-001 Intel Mac engine candidate bridge review

The new `Build-EngineCandidate.py` accepts the existing Intel Mac entrypoint
set, a pinned MCP wheel, and an engine-format skills bundle. It verifies the
core set's file digests, wheel metadata and supplied SHA-256, skills manifest
and payload hashes, then writes an unpublished local `channel.json`. It refuses
existing output and does not install, sign, notarize or publish anything.

Native Intel Mac test inputs and exact identity:

| Input | Revision | SHA-256 |
|---|---|---|
| K-001 branch `axiom-cli` candidate binary | `ca5d38a6f18764c30148852c3fcbb9e449cbcdf5` | `7a64a09777d348538be63e4727c3b60279b4639cf8d8fa5e034984a9e7dde01a` |
| K-006 candidate `axiom` | `90c5865c8b3e3c09980b6f78bf5e359bd95a21c5` | `893751785b57fac380c56a0723e9722c39bd62f696053198ee853de9e01f7479` |
| K-006 candidate `axiom-graphd` | same | `505608f9088aaf2fa4bfaaaa882b27b718c1d68e2c27d162e9f8f263dc1f3a1b` |
| MCP 0.1.0 wheel built from owner revision | `b947b697ac931dead8e3983d4d72c1c998be7d33` | `d550f3dd8180f6dcc2e475d8bddfd5d9fba8943a8ca70b80309b8d09c8af320d` |

The executable test command is `python3 tests/macos/test_engine_candidate.py`
with those four input paths/digests, the skills fixture path,
`--python <host-python-3.13>`, and `--service`. Its
machine-readable result is `engine-candidate-native-check.json`, SHA-256
`d0f4999338679efd59f6d55a3c701942e25e38b4e69682fca0ffa36ab19f9944`.
The test exited 0 on macOS 26.7 x86_64. It verified candidate composition,
entrypoint install, engine install with real core and MCP wheel bytes,
LaunchAgent registration/status/removal, approved engine uninstall, entrypoint
removal and preservation of a user file. It also verified exit-2 refusals for
corrupt core, wrong MCP digest, corrupt skills payload, mutable MCP revision
and existing candidate output. The canonical LaunchAgent label was absent
before and after the test (`launchctl print` exit 113).

The older core binary at `1bf6365fe2129d880422abbac8e1a5b639c8f1a9`
refused the service command with `NOT_READY` (exit 4); the newer K-006
candidate was necessary for the service result above. The test creates a Python
3.13 venv from an already installed host interpreter, so it does **not** prove
K-002 clean-host runtime provisioning. The skills input is the minimal J-005
engine fixture, not the complete owner skills bundle. No MCP query, released
version update/rollback, signed/notarized artifact, final trust provenance or
Windows/WSL/container execution was proved here. K-001 AC1/AC2 remain open.
