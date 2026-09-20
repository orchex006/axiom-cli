# Distribution and installers — axiom-cli

Owner: axiom-cli. **Intended distribution contract; no downloadable runtime release is included in this seed.** The normative rules live in [contracts/axiom-cli-distribution-contract.md](../../../contracts/axiom-cli-distribution-contract.md) in `axiom-specs`; this guide is the owner-side runbook and must not restate a shared schema or protocol.

## Scope

`axiom-cli` owns what a human or an agent obtains and runs: the distributed entrypoint, the native installer scripts, the transactional install/update/uninstall, the published container image and the update channel manifest. It does not own the installation engine, the analyzers, the store, the daemon lifecycle or the bootstrap engine — those stay in `axiom-graphd`, and this repository invokes them through their documented argv surface.

## Entrypoint and verbs

One executable, `axiom-cli` (`axiom-cli.exe` on Windows), is the single distribution entrypoint on every platform. It exposes `install`, `update`, `doctor`, `version` and `uninstall`, and delegates engine work to the installed `axiom-graphd` programs. The engine CLI `axiom` shipped in the core release stays owned by `axiom-graphd`; `axiom-cli` installs, verifies and updates it rather than duplicating any of its behaviour. Every verb exits non-zero with a typed `NotReady` reason instead of starting a partial operation when a required prerequisite, digest, pin or platform declaration is missing. Invocation is program plus argv; no verb requires a shell string, Bash or elevation.

## Delivery platforms

| Platform | Artifact class | Executable |
|---|---|---|
| windows-x64 | archive containing `.exe` | `axiom-cli.exe` |
| linux-x64 | archive preserving the executable bit | `axiom-cli` |
| macos-x64 | archive preserving the executable bit | `axiom-cli` |
| macos-arm64 | archive preserving the executable bit | `axiom-cli` |
| container-linux-x64 | OCI image `ghcr.io/orchex006/axiom-cli` | `axiom-cli` |

The container image is a delivery channel for Linux-family automation. It is never native runtime evidence and never certifies a host OS target.

## Release tiers

Finish-first, release-blocking now: Windows x64, macOS x64 (Intel) and the GitHub Container Registry image.

Design-complete, verification later: Linux x64 including the WSL2 lane, and macOS arm64. These carry the same declared contract but stay explicitly unverified until a native run is recorded. A WSL2 run is Linux evidence and is never Windows evidence.

## Install

Installing is transactional and reversible. Verify release provenance and the per-artifact SHA256 before unpacking; unpack into a user-writable install directory; never require root, never bypass Gatekeeper, never mutate a global PATH and never use `curl | sh`. Then delegate to the engine to register the solution, bind logical repositories to native absolute paths and apply managed bootstrap with an approved plan digest. Re-running install must be idempotent.

## Update

- Read the update channel manifest pinned to an immutable revision.
- Compare the installed component versions against the manifest; refuse an undeclared or downgrade transition.
- Verify every artifact digest before use.
- Stop affected writers, preserve the durable queue and state, swap atomically, and update `axiom-cli` itself inside the same transaction.
- Keep a rollback artifact and a transactional journal; recover an interrupted update to the previous consistent state.
- Never update without an explicit approved request.

## Uninstall

Uninstall removes only owned executables and startup entries by default. Workspace data, checkpoints and private state require a separate, explicit deletion approval. Never recursively delete `.axiom`.

## Dependencies

Installation dependencies and their version manifest are owned by the distribution contract. This seed deliberately invents no version: an entry whose manifest does not exist yet is recorded as undeclared pending the owning task, not guessed. Known prerequisite classes are the Rust toolchain for the core and the CLI, a pinned Python interpreter range for the gateway and the SQLite driver. Node.js, WSL, Docker, Bash and elevation are explicitly not required on a supported host.

## Evidence gate

Record, per target: the actual OS/architecture, the artifact digest, the installer and update transcript, the rollback result and the unverified remainder. Compiling for a target, publishing a container image or passing spec unit tests does not certify any platform. No platform is certified by this guide.
