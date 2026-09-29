# K-106 work in progress (Mac Intel candidate)

The K-105 candidate archive (SHA-256
`caeee2470868b67367c27bbfc368171ba744bcf92c18afafe85d61a9fca2c86f`)
installed in an isolated native Mac user home. Its CLI and engine pointer were
then tested against a candidate carrying the current K-106 CLI and the same
0.1.0 core, MCP and skills artifacts. That candidate was refused because the
engine pointer did not change. The coordinator restored the A entrypoint,
runtime and engine pointer hashes. This does **not** satisfy AC1 or AC3: a real
compatible B ecosystem generation is still needed.

After reviewing that trace, update planning and apply now reject a candidate
whose core version or source revision equals installed A. This refusal occurs
before staging or mutating the runtime. The earlier same-core smoke is evidence
of compensation in that implementation, not a positive A→B update.

The public distribution bootstrap now accepts `update` and `rollback`. The
candidate update delegates plan, apply and rollback to the graphd engine's
public `axiom update` argv. It binds approval to the verified release and the
exact installed A state; it stages the MCP runtime and entrypoints, verifies
the new engine pointer, and compensates by restoring the prior pointers when
an observed step fails. A committed update writes an owned receipt for an
explicit rollback. Full native positive and rollback proof remains pending.

The separate K-003 guard commits `f6b1192` and `74aaa74` were read and
cherry-picked onto the K-106 task branch as `dc4dd85` and `9867eb0`. The
original K-003 worktree was left unchanged. `cargo test --locked` and
`cargo clippy --locked --all-targets -- -D warnings` passed after integration.
The K-106 early negative transcript is in `early-failure-transcript.json`;
its five refusal cases all retained A hashes, but the post-activation injection
was not reached because the same-ecosystem candidate failed the new-pointer
check first. Do not treat that case as a passed post-activation test.
`early-refusal-transcript.json` records stale approval, corrupted core bytes,
incompatible channel identity and rollback without a receipt; all refused
without changing the four observed A hashes.
`preupdate-query.json` records an installed K-105 daemon running under the
owned LaunchAgent: it registered the real C# solution, answered a catalog
query, observed a source edit through the persistent watcher and answered the
new-symbol query. That proves only the A side; B and rollback queries remain.
`early-uninstall.json` records successful A removal after the refusal smoke;
the bindings hash, source file and generated catalog pointer were observed
unchanged. That smoke did not create a separate user-data marker, so its
preservation claim is limited to those three observed objects. The LaunchAgent
was removed and no test daemon remained.

Remaining: obtain/build a source-pinned B core candidate with a distinct
version and digest, rerun public A→B update plus catalog query and watcher,
exercise explicit rollback and all failure boundaries, review service/data
ownership and crash recovery, add native harness and owner docs, then complete
the scoped report and canonical after-work checks. No release or main
integration is claimed.

Crash recovery needs specific work before AC2 can close. The engine writes a
durable update journal, but the distribution coordinator writes its own receipt
only after engine activation and entrypoint replacement. A process death in
that interval leaves the coordinator without a receipt; the directory lock also
remains. The current exception handler covers observed errors, not an abrupt
process death. Do not infer atomic cross-component recovery from the early
failure-injection results.
