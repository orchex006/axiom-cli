# K-011 isolated Linux container candidate preflight

Date: 2026-09-28. Owner: `axiom-cli`. Branch:
`feature/k-011-container-candidate`, based on clean CLI commit
`80ee16f37166220175f9bfbca54fa6514a0a7bba`; canonical remote is
`git@github.com:orchex006/axiom-cli.git`. The matching specs evidence branch
starts from `f4cafae16d2db1d8c5af65b789fe351c24d36ac7`. Neither checkout
had dirty files before branch creation. ADR-0016 authorizes scoped commit and
push; it does not authorize signing, registry publication or release claims.

Read `AGENTS.md`, `Development.md`, the verified immutable `spec.lock.json`,
K-011, the distribution contract and platform matrix. K-001, K-002, K-003 and
K-006 are not `done`, so this work is an isolated candidate spike, not final
K-011 implementation. `specctl validate --task K-011 --stage before` refused
`checklist.unchecked:before.P1` because the canonical K-011 preflight remains
unticked; it is not marked complete while dependencies remain unfinished.

Allowed changes are a directly necessary container test harness, owner-side
candidate evidence and documentation. The public Dockerfile, release channel,
tags and service contracts are out of scope. Positive check: build current CLI
image from pinned bases, compose an unpublished local Linux candidate from
K-006 core revision `90c5865c8b3e3c09980b6f78bf5e359bd95a21c5`, pinned
MCP wheel revision `b947b697ac931dead8e3983d4d72c1c998be7d33` and a
minimal skills fixture, then run approved engine install, hash/version check
and data-preserving uninstall as uid 10001 with network disabled. Negative
checks: corrupt wheel and stale approval. Record exact image/base/artifact
digests, exit codes and limitations. This cannot prove query, watcher,
update/rollback, an owner MCP environment or final OCI release closure.
