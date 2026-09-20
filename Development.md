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
