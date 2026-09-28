# K-001 engine candidate bridge preflight

The current K-001 feature branch is `feature/k-001-macos-entrypoints` at
`ca5d38a6f18764c30148852c3fcbb9e449cbcdf5`, with clean worktree and
canonical remote `git@github.com:orchex006/axiom-cli.git`. The immutable
`spec.lock.json` passed `tools/spec-lock-check.py --release`. The K-001 task
dependencies are done, but K-001 itself stays blocked pending a complete
clean-user lifecycle and final released artifacts.

The preceding isolated Intel Mac diagnostic showed that the Mac entrypoint
release set has only `release-set.json`, whereas `axiom-cli install --from`
requires a channel manifest and an engine bundle containing graphd, MCP and
skills. This slice adds a candidate-only composer under `packaging/macos/`,
plus its direct tests and local documentation. It accepts only pinned inputs,
verifies source bytes and writes a `published: false` local `channel.json`.
It will not sign, notarize, publish, alter the installed home or assert release
certification.

Verification plan: test valid composition, corrupted core/MCP/skills inputs,
missing owner revisions and existing-output refusal; run the candidate through
the actual CLI dry-run on Intel Mac with an isolated HOME. Record exit codes,
artifact hashes and any remaining engine refusal. Run formatter/lint/tests
for changed code, spec lock validation and diff check before commit/push.
