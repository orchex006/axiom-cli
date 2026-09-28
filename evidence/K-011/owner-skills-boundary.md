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

## Owner review inputs

The manifest has six `.py` entries that the CLI converts to engine `script`
entries. None declares `capabilities`. Five are host hooks; source inspection
finds each reading its local hook-state file and writing a replacement with
`os.replace`. The sixth, `adapters/common/hook_runtime.py`, schedules a
bounded callback but says it performs no I/O of its own. The observed source
digests are:

| Executable entry | SHA-256 | Observed direct state effect |
|---|---|---|
| `adapters/codex/hooks/graph_stop.py` | `bc5e62750c96ee14c59c4c90fe21f73fdb68930c8b017d6021a41f58912e94ed` | read/write hook state |
| `adapters/claude/hooks/graph_stop.py` | `bf57f0567943bfb3b3a3b332161c1b69e967cadfd7f05bab050b0a6aa2009d5d` | read/write hook state |
| `adapters/claude/hooks/graph_task_completed.py` | `3b8def3693a54f88375416c21afa13ff97d53ef9705f54f7226d497b4d55a23c` | read/write hook state |
| `adapters/gemini/hooks/graph_after_agent.py` | `24473d21399a3d4e7bd0512fc358df927527e65e68eb87bb4e35a9580162e9c1` | read/write hook state |
| `adapters/antigravity/hooks/graph_stop.py` | `e93e80ff4ea1ecfc57e84151f6d7a668b2d4568462b4852abcee71d3c482bf2b` | read/write hook state |
| `adapters/common/hook_runtime.py` | `f77ce2d9479ecccf308bb5f1e794ac0239ab4480758bc0f5ab727f10a95f4fdd` | bounded callback; no direct I/O |

The `axiom-skills/spec.lock.json` pins `axiom-specs` revision
`6b23ea78e19902726edf40dbd9c15bda27c91ebb` for governance review. That
pin alone does not declare the `spec_revision` required in the installed
skills bundle or approve the executable capability set. The candidate test's
`3e03896e4a80543b7e6be94bf0071b42fd613fa2` was inserted only to expose
the next refusal; it is not a proposed release choice. The skills owner must
choose the reviewed spec revision and capability arrays in its own task and
branch. The owner repository's `AGENTS.md` limits edits to tasks it owns, so
this K-011 investigation leaves its manifest unchanged.
