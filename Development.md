# Development — axiom-cli

## Pinned governance

The canonical workflow is Development.md in `axiom-specs` at the exact revision in `spec.lock.json`. A missing or unverified pin blocks implementation; do not treat `spec.lock.example.json` as valid authorization.

## Before work

Read the selected task, the distribution contract and the platform matrix, verify completed dependencies, claim a single owner, record branch/base revision/dirty tree, explicit commit and push authority, allowed files and tests. Preserve unrelated changes. A–G and J letters do not override task `repo` ownership.

## During work

Implement one bounded task; coordinate public changes through spec ADR/RFC first. Include positive, negative and failure-boundary tests. The distributed executable is a thin wrapper over the `axiom-graphd` installation engine; never fork or re-implement that engine here. Installer and update code must be transactional: verify a digest before use, swap atomically, keep a rollback artifact, and self-update `axiom-cli` inside the same transaction. Native behavior must not depend on Bash, WSL, Docker, administrator privileges or symlinks. Executable launches use program and argv, not an interpolated shell string. No `curl | sh`, no hidden PATH mutation and no silent auto-update.

## Completion

Attach real test output/hashes, acceptance mapping, changed-file review, compatibility and rollback notes, updated local docs and Changelog.md. Record which native targets were actually executed and which stayed unverified; a container image is never native runtime evidence and a WSL2 run is never Windows evidence. Complete the canonical six preflight and eight completion checks; spec tooling validates evidence consistency, but independent CI reruns remain required.

## Branch/release policy

Follow the pinned canonical governance. Do not invent a remote, push credentials or release version. `axiom-cli` is the canonical distribution repository; the daemon plus CLI share one core release, while MCP and skills version independently. Documentation follows its component version. No production action is authorized by copying this seed.

## K-404 Linux x64 runtime candidate

`packaging/linux/Provision-McpRuntime.py` provisions the K-403 MCP wheel and
hash-locked dependencies from local archives into a per-user Python 3.13
generation. `src/lifecycle.rs` verifies the active runtime executable hashes
and passes its absolute `venv/bin` to the engine for a `linux-x64` plan/apply.
The candidate inputs, transaction test and SHA-256 evidence are under
`evidence/K-404/`. This local container proof does not establish native WSL2
behavior or release provenance.

## K-405 container distribution candidate

The unsigned Linux x64 candidate is in `evidence/K-405/`. Its archive carries
the CLI and core binaries, MCP wheel, source skills and channel metadata; the
runtime-input receipt binds the separate K-404 Python archive, wheelhouse and
lock. `tests/linux/verify_k405_candidate.py` checks every archive member and
runtime receipt byte. The OCI image keeps uid/gid 10001 and uses an owned
volume. With no systemd user manager, the installed graphd daemon runs in the
foreground and drains on SIGINT. The local test uses the approved per-user
install and uninstall flows and preserves source, bindings and user data.
This is candidate verification; K-406 and K-407 retain update and query gates.

## K-406 local container update candidate

`packaging/linux/Build-UpdateKit.py` copies an exact K-405-format candidate,
the K-404 runtime receipt, Linux installer and update coordinator into an
unsigned local kit. `AXIOM_CLI_COMPOSITE_KIT` opts the public `axiom-cli update`
verbs into that installed-engine path. The coordinator verifies the kit and
every release member, binds the approval digest to the current CLI/engine
generation, and delegates ecosystem activation and rollback to `axiom`.
The distribution layer retains and restores its own CLI entrypoint. Without
the explicit kit, the K-003 guard still refuses split update; a feature-branch
candidate is not a published update channel.
