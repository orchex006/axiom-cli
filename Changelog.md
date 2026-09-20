# Changelog — axiom-cli

## Unreleased

V2 seed adopts `2.0.0-draft.1`, `.axiom` workspace layout and component-owned docs/tests. Distribution, installer and update-channel implementation and platform certification are pending.

### J-004 — Ship the Windows x64 finish-first distribution

- Added `installers/windows/`: `AxiomCli.Windows.Common.ps1` (canonical JSON, sha256, per-user PATH rules, transaction lock, host info), `Install-AxiomCli.ps1` (transactional per-user install with plan/approval, journal-based interrupted-install recovery, idempotent re-run, downgrade and unowned-entrypoint guards, atomic generation swap, machine-PATH guard, declared scheduled-task registration and health check) and `Uninstall-AxiomCli.ps1` (transactional removal that preserves the install root and the project graph output root unless a separately approved `-PurgeData` plan is applied).
- Added `packaging/windows/Build-ReleaseSet.ps1`, which assembles the release set whose sha256 is the single approval digest for the transaction, and `packaging/install-result.schema.json`, the draft 2020-12 schema for the install-result envelope that names every installed artifact, its version and its sha256.
- Added `tests/windows/Invoke-AxiomCliWindowsDistributionTests.ps1`: 32 executed legs (positive, negative and boundary) run as child processes of the shipped Windows PowerShell, covering plan-only, missing and wrong approval, approved install, idempotent re-run, corrupted-artifact refusal, unowned-entrypoint conflict and forced replacement, downgrade refusal and allowance, interrupted-install recovery, held-lock refusal, uninstall with a wrong and a correct approval, uninstall when absent, purge behind a separate approval, scheduled-task register/remove at `Limited` run level, an unchanged machine-wide PATH, explicit cleanup of the installations the forced/downgrade/recovery legs leave behind, a no-surviving-`_j004-run`-PATH-entry hygiene leg, and schema validation of every captured install-result envelope.
- Every artifact is size-checked and then sha256-verified before use; a mismatch is refused with `9`. Nothing is installed from a release set that fails verification, and components the release set does not carry are recorded under `unverified_artifacts` rather than reported as installed.
- Executed on Windows 11 Pro 10.0.26200 x64 with `rustc`/`cargo` 1.98.1 in the shipped Windows PowerShell 5.1: harness exit `0` on two consecutive runs with 32 legs passing and 30 install-result envelopes schema-valid, `cargo fmt --all -- --check` exit `0`, `cargo clippy --locked --all-targets -- -D warnings` exit `0`, `cargo test --locked --all-targets` exit `0` with 11/11 integration tests passing. Evidence under `evidence/J-004/`. `axiom-graphd` core artifacts are not built, so they stay unverified; `windows-x64` is not certified.
- Updated `docs/30-DISTRIBUTION-AND-INSTALLERS.md` with the executed Windows runbook, layout, exit codes and the verified/unverified split.
### J-003 — axiom-cli repository seed and frozen argv surface

- Seeded the repository from `axiom-specs/repo-seeds/axiom-cli` (README, Development.md, AGENTS.md, Changelog.md, VERSION, `spec.lock.example.json`, `.editorconfig`, `.gitattributes`, `.gitignore`, `.github/pull_request_template.md`, `docs/`).
- Added the Rust distribution entrypoint: `Cargo.toml`, `Cargo.lock`, `src/main.rs`, `src/cli.rs`. No third-party dependencies, so the binary builds offline.
- Froze the five contract verbs `install`, `update`, `doctor`, `version` and `uninstall` on argv and in `--help`, with the canonical exit vocabulary of `docs/16-CLI-AND-CONTROL-API.md` section 6 (`0 2 3 4 5 6 7 8 9 10 20`). Unknown verb, missing option value and invalid flag combination return `2`; a mutating transaction requires `--approve-digest <sha256>`.
- Every declared verb answers `NotReady` with exit `4` and a stated reason, because the engine handoff (`I-003`/`I-004`) and the pinned channel manifest (`J-007`) are not built yet. Nothing is installed, updated or removed by this slice.
- Added `tests/argv_surface.rs`, which pins usage text against the dispatcher so a verb removed from either one alone fails, and `docs/40-CLI-ARGV-SURFACE.md`.
- Windows x64 development run recorded with `rustc 1.98.1`. No other platform is verified or certified; `spec.lock.json` still needs a verified immutable pin.
