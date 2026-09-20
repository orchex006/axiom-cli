# Changelog — axiom-cli

## Unreleased

V2 seed adopts `2.0.0-draft.1`, `.axiom` workspace layout and component-owned docs/tests. Distribution, installer and update-channel implementation and platform certification are pending.

### W10-DOCTRUTH — documentation links that escaped the repository

- Removed the four relative Markdown links that used `../../../` and resolved outside `axiom-cli`, in
  `docs/30-DISTRIBUTION-AND-INSTALLERS.md`, `docs/40-CLI-ARGV-SURFACE.md` and
  `docs/60-LINUX-AND-MACOS-ARM64.md`. They pointed at `contracts/axiom-cli-distribution-contract.md` and
  `docs/16-CLI-AND-CONTROL-API.md` relative to a parent of the repository, which exists on no machine.
- Both documents are canonical in `axiom-specs` and cannot be linked relatively from this repository, so
  each reference is now plain text naming the canonical path — `axiom-specs/contracts/axiom-cli-distribution-contract.md`
  and `axiom-specs/docs/16-CLI-AND-CONTROL-API.md` — matching the existing convention in
  `packaging/macos-arm64/README.md` and `docs/50-CONTAINER-CHANNEL.md`. No URL was invented and no
  unresolvable link remains.
- Verified: every remaining relative link in the repository's Markdown resolves inside `axiom-cli`, and both
  named `axiom-specs` documents exist at the sibling checkout. Documentation-only change; no entrypoint,
  installer, container or channel behavior changed. `spec.lock.json` is still unset.

### J-006 — container delivery channel (`ghcr.io/orchex006/axiom-cli`)

- Added `containers/Dockerfile`: a builder and a runtime stage, both base images pinned by digest (`rust:1.85-slim-bookworm`, `debian:bookworm-slim`), a complete OCI label set (title, description, source, url, documentation, version, revision, created, licences), the non-native delimiters `io.orchex006.axiom.channel` and `io.orchex006.axiom.native-evidence="false"`, and a non-root runtime user `axiom` (uid/gid `10001`). The release build is `cargo build --release --locked --offline`, so it fetches nothing beyond the two pinned base images.
- Added `containers/entrypoint.sh`: `exec /usr/local/bin/axiom-cli "$@"`. Argv reaches the binary verbatim, so the container exposes the same five verbs with the same exit codes. No verb is added, renamed or re-implemented, and an unbuilt verb keeps answering `NotReady` with exit `4`.
- Added `.github/workflows/publish-container.yml`: buildx, `linux/amd64` in the finish-first tier, `linux/arm64` only behind an explicit input, immutable version and commit-derived tags with no floating tag, opt-in push, and the resolved digest recorded as a build artifact and in the run summary. It never overrides the base-image pins and certifies no platform.
- Added `tests/container_distribution.rs`, which pins the base digests, the OCI label set, the non-root user and uid, the `VERSION` to `ARG AXIOM_VERSION` link, the argv-forwarding entrypoint, the immutable-tag rule, the arm64 gate, the opt-in push default and the digest recording.
- Added `docs/50-CONTAINER-CHANNEL.md` (build and run procedure, digest-recording location, offline or air-gapped variant) and linked it from `docs/README.md`.
- Verified locally on Windows 11 x64 with Docker Desktop 29.6.2 (engine `linux/amd64`) at revision `7ac376b`: image build exit `0`, resolved image id `sha256:843e184865ccb2f161036a149330526a4952750708caa14a4528a8fa49c54d56`, runtime `uid=10001(axiom)`, and 18 of 18 argv cases matching the native binary exactly (0 mismatches), including the empty-argv path exiting `2`.
- No publication happened: no push to `ghcr.io`, no image tag and no release. `distribution.container.published_image_digest` in the platform matrix stays `null`, `linux/arm64` is unbuilt, and a container run is never recorded as native evidence for any native target.

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

### J-007 — the update channel with verification, atomic swap and rollback

- Added `src/update/` (`check`, `plan`, `apply`, `rollback`) and `channels/stable.json`. Versions resolve **only** from the channel manifest the installed release recorded: a branch tip, a tag alias, a network `latest`, a forbidden pin and an unsigned channel are refused. Added `docs/50-UPDATE-CHANNEL.md` and `tests/update_channel.rs` (23 legs).
- Every artifact's length and sha256 are verified before it is used; a mismatch is `artifact_digest_mismatch` and nothing is swapped. An artifact that cannot be obtained from the local cache stays unverified and the verb answers not-ready (`4`, `artifact_unreachable`) instead of reporting an applied update.
- `apply` is transactional: it takes the coordinator lock, stages, writes the journal, renames the generation into place, swaps the active pointer and keeps the previous generation until the new one passes its health probe. A failed verification or health check restores the previous generation, and an interrupted apply is recovered from the journal. `axiom-cli` is one component of the same plan, so self-update and component updates are one transaction with one approval digest, and the plan is refused when the recorded digest no longer matches the installed bytes.
- Reused the frozen exit vocabulary: `0` success, `2` validation, `3` not found, `4` not ready, `6` conflict, `8` I/O or internal, `9` incompatible, `10` lock unavailable. `--json` still writes exactly one object carrying `details.reason_code` and `details.reason`.
- Publication is closed for this wave: `channels/stable.json` has `published: false` and no artifact entries, and its `trust_root` is a documented development seed rather than a release signing root, so nothing was pushed, tagged or released.
- Evidence is windows-x64 only, against local on-disk fixtures, recorded under `evidence/J-007/`. `linux-x64`, `macos-arm64` and `macos-x64` stay unverified; a WSL2 run is Linux evidence and is never Windows evidence.

### J-008 — Linux x64 (including the WSL2 lane) and macOS arm64 tiers

- Added the Linux x64 per-user distribution path in POSIX `sh` under `installers/linux/`:
  `AxiomCli.Linux.Common.sh` (shared helpers, host facts, envelope builder, transaction lock,
  `systemd --user` probe), `Install-AxiomCli.sh` (transactional install/update) and
  `Uninstall-AxiomCli.sh` (owned-only removal with `--purge` gated behind separate approval).
  No path requires Bash, Docker, elevation or a symlink, and every mutation requires an approved
  plan digest.
- Added `packaging/linux/`: the release-set builder (`Build-ReleaseSet.sh`, refuses a non-ELF or
  non-x86_64 input and invents no version), the line-oriented `release-set.schema.json`, and
  `install-result.schema.json` — the Linux profile of the shared 33-key machine-readable
  `install-result` envelope, equal key-for-key to the Windows profile.
- The Linux install registers a `systemd --user` unit when a user manager answers and degrades
  explicitly when it does not; with `--service systemd-user` an unreachable manager is a refusal
  (exit `4`, check `systemd-user-available`) that rolls the entrypoint back rather than silently
  skipping registration. The reference artifact's highest glibc requirement is `GLIBC_2.34`.
- Added `packaging/macos-arm64/`: one macOS recipe shared by `arm64` and `x64`, parameterised by
  `--arch`, gated on `Darwin`, recording the architecture of every artifact from its Mach-O
  `cputype`. **No macOS artifact is built on this host**: the arm64 leg stays `not_run` with
  `certified: false` and empty evidence.
- Added `tests/linux/Invoke-AxiomCliLinuxDistributionTests.sh` (23 executable Linux legs, L01–L20)
  and `tests/linux_distribution.rs` (static guards for the POSIX shell, the envelope key order, the
  schema and the macOS "not built" record).
- Executed the Linux x64 path under WSL2 on Debian 12 (bookworm, glibc 2.36, no systemd) and on
  Ubuntu 26.04.1 LTS (glibc 2.43, systemd as init): 23/23 legs, 0 failures, and the systemd-user
  leg registered and removed a real unit on Ubuntu. The WSL2 lane is recorded as `linux-x64`
  evidence and never as Windows evidence. `linux/arm64`, signing/attestation, the container image
  and the update channel (`J-007`) are not done; `spec.lock.json` is still unset.
