# K-011 owner skills input boundary

On 2026-09-28, `axiom-skills` revision
`9579ceb6bbf34bf2ea7081ef117640a2fa3b3ffc` passed its own
`python3 release/verify_manifest.py --manifest release/skills-manifest.json
--root .` (exit 0, 41 files). The original manifest SHA-256 is
`dddbbb5cc81e60c1ec3fbb53c7badbd3e52f97d4974596be8aebc96f9abe7cf7`.
Its `install_policy.requires_explicit_human_approval` is `true`.

```sh
python3 tests/container/test_k011_owner_skills_boundary.py \
  --image axiom-cli:k011-combined-rebuild \
  --release /tmp/axiom-k011-release \
  --skills-owner ../axiom-skills \
  --spec-revision 3e03896e4a80543b7e6be94bf0071b42fd613fa2 \
  > evidence/K-011/owner-skills-boundary.json
```

The command exited 0. It copied the verified owner files into a disposable
release set and invoked real CLI plan/apply with network disabled as uid 10001.
The unchanged owner manifest refused before engine activation with exit 4,
`skills_spec_revision_not_pinned`. Adding a pinned spec revision only to a
second disposable copy refused with exit 4,
`skills_capability_review_required:adapters/codex/hooks/graph_stop.py`.
The engine active pointer remained absent in both cases. Structured output:
`owner-skills-boundary.json` (SHA-256
`adcc731f5c4ac8518fc73bb34bd62ce58340d6153e1293550fad6e33553770db`).
The harness source SHA-256 is
`9004f48f4b97373b52b0cf67439f9aa61690232a862a7504296fce088e43dc52`.

The original `axiom-skills` checkout and manifest were not modified. A full
owner bundle needs a reviewed immutable spec revision and explicit capability
declarations for executable entries. This test establishes the refusal
boundary; it is not approval to synthesize those fields or a completed K-011
release closure.
