# Distribution and installers — axiom-cli

Owner: axiom-cli. **Intended distribution contract; no downloadable runtime release is included in this seed.** The normative rules live in `axiom-specs/contracts/axiom-cli-distribution-contract.md`; this guide is the owner-side runbook and must not restate a shared schema or protocol.

## Scope

`axiom-cli` owns what a human or an agent obtains and runs: the distributed entrypoint, the native installer scripts, the transactional install/update/uninstall, the published container image and the update channel manifest. It does not own the installation engine, the analyzers, the store, the daemon lifecycle or the bootstrap engine — those stay in `axiom-graphd`, and this repository invokes them through their documented argv surface.

## Entrypoint and verbs

One executable, `axiom-cli` (`axiom-cli.exe` on Windows), is the single distribution entrypoint on every platform. It exposes `install`, `update`, `doctor`, `version` and `uninstall`, and delegates engine work to the installed `axiom-graphd` programs. The engine CLI `axiom` shipped in the core release stays owned by `axiom-graphd`; `axiom-cli` installs, verifies and updates it rather than duplicating any of its behaviour. All five verbs dispatch to real work, and a verb refuses with a typed exit code and reason instead of starting a partial operation when a required prerequisite, digest, pin or platform declaration is missing; `NotReady` (`4`) is one such refusal, not the universal answer. Invocation is program plus argv; no verb requires a shell string, Bash or elevation.

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

The `axiom-cli` binary itself stops at that delegation point today: `install --dry-run` resolves and verifies the release set (a bare `install` is `2` validation, because an explicit mode is required), then `install --apply` refuses `4` `engine_bundle_not_assembled` because this layer does not assemble the bundle the engine's `install plan --bundle <dir>` verb needs (a `bundle.json` manifest plus verified component payloads and a `skills/` bundle), or `3` `engine_not_found` when no engine is present, instead of placing bytes. The installed PowerShell and POSIX-sh installer scripts are what actually verify and write files; the CLI never fabricates a placement the engine did not perform.

## ## Update

J-007 implements the update path in `src/update/` with the channel manifest in `channels/stable.json`; `docs/50-UPDATE-CHANNEL.md` records what runs today and what does not. Implemented now:

- `update check`, `update plan`, `update apply` and `update rollback` resolve a version only from the channel manifest the installed release recorded; a branch tip, a tag alias, a network `latest` and an unsigned channel are refused.
- Every artifact's length and sha256 are verified before it is used, and `axiom-cli` self-updates inside the same transaction under one approval digest.
- The swap keeps the previous generation until the new one passes its health probe; a failed verification or health check restores the previous generation, and an interrupted apply is recovered from the journal. Every changed component is reported under `needs_restart`.
- An update is never applied without an explicit approved request.

The engine now implements local ecosystem activation, owned-service coordination and rollback (ADR-0014). This distribution channel still uses a separate delivery generation store; its bridge to that engine transaction remains unfinished. A signed channel with published artifacts remains release-gated.

Uninstall

Uninstall removes only owned executables and startup entries by default. Workspace data, checkpoints and private state require a separate, explicit deletion approval. Never recursively delete `.axiom`.

`axiom-cli uninstall --dry-run` embeds the canonical engine removal plan in its outer approval document. `--apply --approve-digest <digest>` invokes that exact engine plan, then clears only an unchanged distribution marker. The engine verifies ownership, stops its owned service, preserves edited/unowned files and writes retryable removal evidence. The wrapper refuses `--purge-data`; native Mac x64 evidence is recorded under `evidence/J-005/local-lifecycle-20260922/`.

## Dependencies

Installation dependencies and their version manifest are owned by the distribution contract. This seed deliberately invents no version: an entry whose manifest does not exist yet is recorded as undeclared pending the owning task, not guessed. Known prerequisite classes are the Rust toolchain for the core and the CLI, a pinned Python interpreter range for the gateway and the SQLite driver. Node.js, WSL, Docker, Bash and elevation are explicitly not required on a supported host.

## Evidence gate

Record, per target: the actual OS/architecture, the artifact digest, the installer and update transcript, the rollback result and the unverified remainder. Compiling for a target, publishing a container image or passing spec unit tests does not certify any platform. No platform is certified by this guide.

## Windows x64 per-user install (card J-004 — implemented and executed)

This section is the owner-side runbook for the one native target that is implemented and has actually
been executed. Sources: `installers/windows/`, `packaging/windows/` and `tests/windows/` in this
repository. The card proposed exactly these paths; no path change was needed. Everything here runs in
the Windows PowerShell that ships with Windows — no WSL, Bash, Docker, Node.js or elevation.

### Files

| Path | Role |
|---|---|
| `packaging/windows/Build-ReleaseSet.ps1` | Assembles a `release-set.json` whose sha256 is the approval digest for the whole transaction. |
| `packaging/install-result.schema.json` | Draft 2020-12 schema for the machine-readable install-result envelope. |
| `installers/windows/AxiomCli.Windows.Common.ps1` | Shared helpers: canonical JSON, sha256, per-user PATH rules, transaction lock, host info. |
| `installers/windows/Install-AxiomCli.ps1` | Transactional per-user install, repair and recovery. |
| `installers/windows/Uninstall-AxiomCli.ps1` | Transactional removal that preserves user data unless a separate purge plan is approved. |
| `tests/windows/Invoke-AxiomCliWindowsDistributionTests.ps1` | The executed acceptance harness (32 legs) that produces `evidence/J-004/`. |

### Step 1 — assemble the release set and obtain the approval digest

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\Build-ReleaseSet.ps1 `
  -OutDir .\_out\release-set -CliExe .\target\release\axiom-cli.exe -Version 0.1.0 -Json
```

Writes `<_out>\release-set.json` plus the carried artifact bytes. The report is a release-set
assembly report, not an install-result envelope.

### Step 2 — plan (never mutates)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installers\windows\Install-AxiomCli.ps1 `
  -ReleaseSet .\_out\release-set -Json
```

Exit `0`, `outcome = planned`, `mutated = false`, nothing created. The sha256 of `release-set.json` is
the approval digest.

### Step 3 — install with the approval digest

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installers\windows\Install-AxiomCli.ps1 `
  -ReleaseSet .\_out\release-set -Apply -ApproveDigest <sha256-of-release-set.json> -Json
```

Exit `0` with `outcome = installed` and `elevation_required = false`.

### Step 4 — uninstall (preserves user data)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installers\windows\Uninstall-AxiomCli.ps1 -InstallRoot <root> -Json
powershell -NoProfile -ExecutionPolicy Bypass -File installers\windows\Uninstall-AxiomCli.ps1 `
  -InstallRoot <root> -Apply -ApproveDigest <sha256-of-uninstall-plan> -Json
```

`-PurgeData` removes the install root as well. It is a different plan, so it is a different digest and
a different approval; a purge is never implied by a plain uninstall.

### Layout and scope

Default install root is `%LOCALAPPDATA%\Axiom` (per-user). Under it: `bin\axiom-cli.exe`, the
versioned `cli\generations\<version>\`, `cli\staging\` and `cli\rollback\` artifacts,
`cli\journal.json` (interrupted-transaction recovery), `cli\state.json`, `cli\transaction.lock` and
`install-manifest.json`. Only `HKCU\Environment\Path` (user scope) is changed; the machine-wide PATH is
snapshotted before and after every transaction and a change throws.

### Exit codes (PowerShell installer)

This table is the Windows PowerShell installer's exit mapping, not the `axiom-cli` binary's. `0`
success, `2` validation or missing approval, `3` not found, `5` approval mismatch, `6` conflict,
`8` I/O failure with rollback, `9` digest mismatch or refused downgrade, `10` transaction lock
unavailable. A mutating run that fails rolls back and reports `rolled_back`.

The CLI's own per-verb exit behaviour (including the engine handoff) is tabulated in
[docs/40-CLI-ARGV-SURFACE.md](40-CLI-ARGV-SURFACE.md).

### Reproduce the evidence

```powershell
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File tests\windows\Invoke-AxiomCliWindowsDistributionTests.ps1
```

Records `evidence/J-004/`: `j004-run-transcript.txt`, `j004-step-records.json`,
`j004-artifact-digests.txt`, `j004-schema-validation.txt`, `envelopes\` (install-result envelopes,
validated against the schema) and `release-set-reports\`.

The harness is self-cleaning: the legs that deliberately leave an installation behind
(`L07b` forced unowned install, `L08b` allowed downgrade, `L09` interrupted-install recovery) are
uninstalled by explicit `L17a-c` cleanup legs, and `L17-cleanup-path-hygiene` asserts that no
`_j004-run` per-user PATH entry survives. Run it twice in a row: the second run proves the cleanup is
idempotent and a previously leaked PATH entry cannot be re-masked by the pre-run PATH guard.

### Verified vs unverified on Windows x64

Verified by the executed harness on Windows 11 Pro 10.0.26200 x64: per-user install, idempotent
re-run, interrupted-install recovery, digest-mismatch refusal, unowned-entrypoint conflict,
downgrade refusal, held-lock refusal, uninstall, purge behind a separate approval, scheduled-task
registration and removal at `Limited` run level, user-PATH add/remove with an unchanged machine PATH,
and schema validation of every captured install-result envelope.

Unverified and never reported as installed: the `axiom-graphd` core artifacts (`axiom-graphd.exe`,
`axiom.exe`) because the pinned core release is not built, so the release set declares them and records
them under `unverified_artifacts`; `axiom-mcp` and the skills versions because no version source is
available to this release; and every non-Windows target. `windows-x64` remains `certified: false` in
the platform matrix; a Windows run is not certification.
