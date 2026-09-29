# K-106 engine recovery dependency (unresolved)

Inspected `axiom-graphd` source revision
`fa90e5c6eea84b7bf63b375f7e5af9bcb32b1e78` on
`feature/k-102-macos-core-candidate`. This is an owner handoff for a native
failure boundary, not a claim that the boundary was run with distinct A/B
artifacts.

## Reproducible state transition in the current source

1. `crates/axiom/src/update/ecosystem_runtime.rs:296-298` persists a
   `prepared` update journal before the service drain and pointer activation.
2. `crates/axiom/src/cli.rs:1172-1175` generates the transaction ID inside
   `update apply`. The caller receives it only after the command returns.
3. An abrupt process death can therefore leave a new `prepared` journal with
   no transaction ID in the distribution coordinator's process memory.
4. `ecosystem_runtime.rs:480-483` allows public rollback only for `activated`
   or `finalized` after handling two service-recovery states; it rejects
   `prepared` as `journal-not-active`.
5. `ecosystem_runtime.rs:571-596` refuses another apply while any journal is
   neither `finalized` nor `rolled-back`, reporting `recovery-required`.

The K-106 wrapper now persists `distribution-update-pending.json` before its
first mutation and refuses another operation while it exists. This detects the
interrupted state and avoids silently presenting a mixed installation as
complete. It cannot restore the service and clear the engine's `prepared`
journal through the current public command. An unreported `activated` or
`finalized` journal also needs a transaction discovery/reconciliation path that
binds to the approved A pointer and B candidate, rather than guessing from a
file name.

The same pending record now covers explicit rollback: it is written after
verifying the retained A CLI and MCP runtime but before invoking engine
rollback. A failure after that point leaves the receipt and pending record for
recovery. This detects interruption; it does not yet resume a partial rollback.

## Owner change needed before K-106 AC2

The `axiom-graphd` owner needs a reviewed recovery behavior for a valid
`prepared` journal. It should verify the journal identity, previous pointer,
retained artifacts and current pointer/skills before restoring service and
marking the journal recoverable or rolled back. It must refuse foreign,
corrupt, changed or ambiguous state. A native crash test should stop update
after journal persistence and after pointer activation, then invoke only the
public recovery command and verify pointer, service, user data and ability to
retry. The command/contract change belongs to the engine owner; K-106 must
consume it through public argv rather than rewriting the engine in Python.

K-102 explicitly routes engine install/service defects found downstream to
the engine owner with regression. Its existing completion certifies the
0.1.0 candidate only; this handoff does not change that result. A new
source-pinned B core candidate with an owner-declared version and digest is
also required for K-106's A→B native proof. No B version or artifact is
declared here.
