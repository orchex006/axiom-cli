# K-002 pinned runtime with K-001 Mac candidate bridge

On macOS 26.7 x86_64, the following command exited 0 with the pinned MCP wheel
`365d4d2baa3b155b1c2cb661fdfd8439db1f628ba9ea524e0b0ee49d14c22705`,
bundle manifest `5c63b71390d4330e3dc430453865411ee6dc54eb3df95c5fb780d730d987e77e`,
and K-006 core candidate revision `90c5865c8b3e3c09980b6f78bf5e359bd95a21c5`.

```sh
python3 tests/macos/test_engine_candidate.py \
  --cli target/debug/axiom-cli \
  --engine /tmp/axiom-k001-core-mac-new/axiom \
  --daemon /tmp/axiom-k001-core-mac-new/axiom-graphd \
  --mcp-wheel /tmp/axiom-k002-bundle-v11/wheels/axiom_mcp-0.1.0-py3-none-any.whl \
  --mcp-sha256 365d4d2baa3b155b1c2cb661fdfd8439db1f628ba9ea524e0b0ee49d14c22705 \
  --mcp-revision b947b697ac931dead8e3983d4d72c1c998be7d33 \
  --core-version 0.1.0 \
  --core-revision 90c5865c8b3e3c09980b6f78bf5e359bd95a21c5 \
  --skills-bundle evidence/J-005/local-lifecycle-20260922/fixture-template/skills \
  --mcp-bundle /tmp/axiom-k002-bundle-v11 --service \
  > evidence/K-002/candidate-bridge-native-check.json
```

The observed steps and results are in `candidate-bridge-native-check.json`. The JSON evidence
SHA-256 is `b7e310fe7e801e0ccb44300dd6b2cfbcada3ed2a34f8601e52403dcc6572d7d2`.

In a temporary HOME with system-only PATH, the test approved the MCP manager's
plan and provisioned its pinned standalone interpreter. It resolved the
installed wheel's absolute stdio executable and argv, installed the three
entrypoints, ran `axiom-cli install` through the real graphd engine, checked
the MCP environment remained active, registered/removed the LaunchAgent, and
uninstalled engine, MCP environment and entrypoints while preserving a user
file. It also refused five bad candidate inputs with exit 2. The skills input
was the minimal J-005 engine fixture. This does not certify owner skills.

`cargo test --quiet` passed 200 tests across six suites; `cargo fmt --all --
--check`, `cargo clippy --all-targets -- -D warnings`, spec-lock validation,
Python compilation and `git diff --check` exited 0. No credentials were found
in the evidence scan. The test's approved MCP provisioning and removal are
separate operations, outside the `axiom-cli install` transaction. The engine
still treats MCP as a wheel payload and has no executable/argv handoff in its
bundle service contract. No released-version MCP update/rollback, signed
artifact, publication, Windows or WSL2 execution is established here. K-002
remains blocked.
