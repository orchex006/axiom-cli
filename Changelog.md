# Changelog — axiom-cli

## Unreleased

V2 seed adopts `2.0.0-draft.1`, `.axiom` workspace layout and component-owned docs/tests. Distribution, installer and update-channel implementation and platform certification are pending.

### J-003 — axiom-cli repository seed and frozen argv surface

- Seeded the repository from `axiom-specs/repo-seeds/axiom-cli` (README, Development.md, AGENTS.md, Changelog.md, VERSION, `spec.lock.example.json`, `.editorconfig`, `.gitattributes`, `.gitignore`, `.github/pull_request_template.md`, `docs/`).
- Added the Rust distribution entrypoint: `Cargo.toml`, `Cargo.lock`, `src/main.rs`, `src/cli.rs`. No third-party dependencies, so the binary builds offline.
- Froze the five contract verbs `install`, `update`, `doctor`, `version` and `uninstall` on argv and in `--help`, with the canonical exit vocabulary of `docs/16-CLI-AND-CONTROL-API.md` section 6 (`0 2 3 4 5 6 7 8 9 10 20`). Unknown verb, missing option value and invalid flag combination return `2`; a mutating transaction requires `--approve-digest <sha256>`.
- Every declared verb answers `NotReady` with exit `4` and a stated reason, because the engine handoff (`I-003`/`I-004`) and the pinned channel manifest (`J-007`) are not built yet. Nothing is installed, updated or removed by this slice.
- Added `tests/argv_surface.rs`, which pins usage text against the dispatcher so a verb removed from either one alone fails, and `docs/40-CLI-ARGV-SURFACE.md`.
- Windows x64 development run recorded with `rustc 1.98.1`. No other platform is verified or certified; `spec.lock.json` still needs a verified immutable pin.

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
