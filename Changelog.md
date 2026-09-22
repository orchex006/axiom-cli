# Changelog — axiom-cli

## Unreleased

### macOS x64 distribution boundary (J-005)

- Add Intel macOS packaging and installer/removal adapters. They delegate to
  `axiom-cli` and its engine, preserve an isolated user-data root on validation
  failure, and refuse architecture overrides. Engine-owned launchd registration
  and removal remain explicitly not-ready until their argv transactions exist.

- `uninstall --dry-run` now obtains the canonical engine plan before sealing the
  distribution plan; `--apply` passes that embedded, approved plan unchanged to
  `axiom uninstall apply`. A changed approval refuses, engine failures retain
  the distribution marker, and successful removal clears only the marker bytes
  that were bound into the reviewed plan. The local macOS x64 harness covers
  install and uninstall dry-runs/applies, executable hash/mode/version, and
  preservation of user, unowned, and human-edited skill files.

### Installation engine wired end to end: `install --apply` really places files

- Added `src/bundle.rs`: the engine-bundle assembler and invoker. `axiom-cli install --apply`
  now assembles `bundle.json` + the verified component payloads + a `skills/` bundle from the
  release set's own verified bytes, then invokes the `axiom-graphd` engine as
  `axiom install plan --bundle <dir> --out <plan file>` followed by
  `axiom install apply --plan <plan file> --approve-digest <engine plan digest>`. Placement stays
  the engine's; this layer assembles inputs and reports the engine's own status, exit code, stdout
  and stderr as evidence. Proven on `macos-x64`: `install --apply --from <release set> --json`
  exits `0`, `status:"ok"`, `engine_status:"installed"`, and independent re-hashing finds 41/41
  skills payloads and both core payloads byte-correct with no symlinks.
- The bundle is assembled from **verified bytes only**, and that rule now covers the skills
  pass-through tree too: when a release set supplies an engine-format `skills/bundle.json`, every
  payload it declares is re-hashed against the declared `sha256`/`size_bytes` before the engine is
  invoked. A payload that disagrees is refused as `skills_payload_unverified:<path>` (exit `2`), and
  no bundle is left behind for the engine to read. A path that is not portable-relative, or a
  digest that is not lowercase 64-hex, is refused as `skills_bundle_manifest_invalid`.
- Fixed two defects in the `axiom-skills` source-manifest converter (`convert_skills`) that would
  have been caught only by the real engine, not by any test in this repository:
  the generated `skills/bundle.json` named the bundle component `axiom-skills` where
  `SkillBundle::validate` requires `skills` (it would have been refused `unexpected_component`), and
  it omitted `capabilities` on entries with an empty review where `DeclaredEntry` requires the field
  on every entry (it would have been refused `missing field capabilities`). Both are now pinned by
  a converter test whose assertions fail against the previous behaviour.
- Verified against the real engine that the converter accepts a source manifest carrying
  `spec_revision` and a per-executable `capabilities` review (41/41 payloads byte-identical to the
  `axiom-skills` repository), and refuses honestly when either is absent:
  `4 not_ready skills_spec_revision_not_pinned` and
  `4 not_ready skills_capability_review_required:<path>`. Which repository supplies those two
  values is an open owner decision; this layer refuses rather than inventing them.
- The "verified bytes only" rule now covers every byte, not just declared ones: a file under
  `skills/payload/**` that `skills/bundle.json` does not declare is refused as
  `skills_payload_undeclared` (exit `2`) and named, instead of being copied into the bundle
  unhashed. A symlink anywhere in the payload tree is refused as `skills_bundle_symlink`.
- The assembled bundle declares the permissions an artifact's `kind` implies: a `binary` component
  announces `read` + `execute` (matching the engine's own fixture), a `python` artifact `read`
  alone. Previously every component announced `read` only, so the engine's reviewed plan
  under-declared the executable it was about to place. The two values a local release set cannot
  declare — `service` and `network_access` — are now documented as this layer's *policy*
  (no service registration, no network access requested) rather than presented as declarations.
- When the engine exits `0` without sending a `status` object, the report now carries
  `engine_status:"unreported"` and `engine_status_reported:false` instead of substituting
  `"installed"`. Exit `0` is still the engine's own answer, but this layer no longer names a
  placement the engine never named.
- `install --dry-run` now answers `4 not_ready nothing_to_install` when the release set declares no
  artifact for this host, exactly as `install --apply` already did, and the refusal names the plan
  digest it refused. Previously `--dry-run` answered `0` with `verified_artifacts: []`, so a caller
  could approve a digest for a plan that would install nothing.
- Exit-code reachability: `5` (`FORBIDDEN` -> `authorization_error`), `7` (`TIMEOUT_BUSY` ->
  `timeout_busy`), `20` (`PARTIAL` -> `partial`) and `8` (`IO_ERROR` -> `io_error`, via an
  unreadable `installed.json`) now each have a test. `9` and `10` already did. No emitter exists for
  a code the engine cannot produce, and none is faked.
- Test suite is green with `cargo test --no-fail-fast`: 89 unit + 14 `argv_surface` + 56
  `cli_verbs` + 9 `container_distribution` + 6 `linux_distribution` + 24 `update_channel`
  (198 tests).

### Implemented lifecycle verbs: install, uninstall, doctor, version and engine discovery

- Added `src/lifecycle.rs` (install/uninstall release-set resolution, plan build and approval),
  `src/doctor.rs` (real checks and worst-code exit), `src/version.rs` (installed/available report),
  `src/target.rs` (delivery platform, tier and compiled-in host id) and `src/engine.rs` (engine
  discovery and invocation). `src/cli.rs` now dispatches all five contract verbs to real actions;
  the "unbuilt verb" `NotReady` fallback is gone.
- `install` and `uninstall` now require an explicit mode. A bare verb is a validation error (`2`,
  `status:"validation_error"`) whose message names `--dry-run` and `--apply`, following
  `axiom-specs/docs/16-CLI-AND-CONTROL-API.md` section 6 rule 4: a non-interactive verb that writes
  or removes state must carry `--dry-run` or `plan`/`apply`, otherwise a bare install could answer
  `0` for work it never did and an argv-only consumer could not tell the two apart. `Mode::Report`
  was deleted; the only modes are `--dry-run` (token `"dry-run"`) and `--apply` (token `"apply"`).
  The global `--help` NOTES and the per-verb `install|uninstall --help` state the requirement.
- `install --dry-run` reports the resolved release set and changes nothing: exit `0` when a release
  set resolves, `4` `no_release_set` when none does, and `4` when `--from` names an unreadable
  manifest. `install --apply` requires `--approve-digest`; after verifying every artifact it assembles the
  engine bundle and hands placement to the engine (see the section above). `3` `engine_not_found`
  when no engine binary is present.
- `uninstall --dry-run` reports the removal plan and changes nothing (exit `0`, `mode:"dry-run"`).
  `uninstall --apply` refuses `3` `nothing_installed`, `3` `engine_not_found`, or `4`
  `engine_removal_unavailable` (the engine publishes no removal verb).
- `doctor` runs real checks (target, install root, installed-release integrity, prerequisites and
  engine) and exits with the worst code: `0` clean, `4` when a required check is unverified (for
  example an absent engine or no python 3.13), and `2` when an installed generation fails integrity.
  `version` exits `0` even with nothing installed (`installed:false`, `available:null`,
  `available_source:"unresolved"`); the previous `NotReady` answer is gone.
- Engine discovery precedence is `AXIOM_ENGINE_BIN` (env) -> the sibling of the running `axiom-cli`
  binary -> `PATH`; the program name is `axiom` (`axiom.exe` on Windows). No engine is exit `3`
  `engine_not_found` with the `searched[]` list of every place tried. The engine is invoked as
  program plus argv and is never re-implemented.
- `AXIOM_CLI_INSTALL_ROOT`, `AXIOM_CLI_CHANNEL_MANIFEST` and `AXIOM_CLI_ARTIFACT_CACHE` now govern
  `install`, `uninstall`, `doctor` and `version`, not only `update`.
- Fixed the approval-digest defect that made every `--apply` unusable: the plan was sealed without a
  `plan_digest` member, so `plan_contract` never found `plan["plan_digest"] == approved` and refused
  `plan_digest_not_approved`; a per-second `generated_at` also changed the digest each run and added
  `approval_stale`. `seal()` now writes `plan_digest` back into the plan (safe because the member is
  excluded from the digest body) and `generated_at` is out of the plan body, kept only in the report
  detail. Five regression tests pin the seal.
- Added `the_detected_host_rows_are_exactly_the_engine_bundle_hosts` in `src/target.rs`. The four
  rows this CLI can detect are now pinned against the installation engine's own bundle-host list
  (`axiom-graphd`, `crates/axiom/src/install/plan.rs`, `HOSTS`), which is the vocabulary a bundle
  manifest's `host` field is validated against once this repository starts assembling bundles. A
  divergence fails here instead of surfacing as an opaque refusal at install time. Detection itself
  is unchanged and was already correct on both macOS architectures.
- Fixed an order-dependent breach of the `--json` contract: `--json` was latched only when the
  argv scan reached that token, so a refusal raised before it (`axiom-cli frobnicate --json`, and
  an unknown global option followed by `--json`) answered prose on stderr with an empty stdout
  while the flag-first spelling answered the envelope. `src/cli.rs` now pre-scans argv, so one
  invocation is one answer shape regardless of where the caller put the flag. A refused
  invocation that names `--json` emits exactly one JSON object on stdout and nothing on stderr;
  plain mode still writes prose to stderr.
- Test suite (counts as of the section above) is green with `cargo test --no-fail-fast`: 89 unit
  + 14 `argv_surface` + 56 `cli_verbs` + 9 `container_distribution` + 6 `linux_distribution`
  + 24 `update_channel` (198 tests).
- The update channel remains unpublished (`published: false`), so it cannot establish a signed
  release update. The engine handoff itself is exercised locally on `macos-x64`: it installs,
  updates, rolls back and performs owned uninstall in a temporary development root. No target is
  certified.

### 0.1.0 experimental Windows distribution

Set the distributed CLI package and Dockerfile default to `0.1.0`. The Windows
release set is unsigned. Superseded: `axiom-cli version` no longer returns `not_ready`
while the pinned update channel is unconfigured; it exits `0` and reports the real state
(see the Unreleased entry above). macOS Intel was later exercised as the current
`macos-x64` development host; it stays `certified: false`.

V2 seed adopts `2.0.0-draft.1`, `.axiom` workspace layout and component-owned docs/tests. The installer and update-channel implementation has since landed (see the entries below and the Unreleased entry above); platform certification stays pending and no target is `certified`.

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
- Added `containers/entrypoint.sh`: `exec /usr/local/bin/axiom-cli "$@"`. Argv reaches the binary verbatim, so the container exposes the same five verbs with the same exit codes. No verb is added, renamed or re-implemented. (Superseded for verb behaviour: the five verbs now dispatch to real work and answer with their own typed refusals instead of a blanket `NotReady`; see the Unreleased entry above.)
- Added `.github/workflows/publish-container.yml`: buildx, `linux/amd64` in the finish-first tier, `linux/arm64` only behind an explicit input, immutable version and commit-derived tags with no floating tag, opt-in push, and the resolved digest recorded as a build artifact and in the run summary. It never overrides the base-image pins and certifies no platform.
- Added `tests/container_distribution.rs`, which pins the base digests, the OCI label set, the non-root user and uid, the `VERSION` to `ARG AXIOM_VERSION` link, the argv-forwarding entrypoint, the immutable-tag rule, the arm64 gate, the opt-in push default and the digest recording.
- Added `docs/50-CONTAINER-CHANNEL.md` (build and run procedure, digest-recording location, offline or air-gapped variant) and linked it from `docs/README.md`.
- Verified locally on Windows 11 x64 with Docker Desktop 29.6.2 (engine `linux/amd64`) at revision `7ac376b`: image build exit `0`, resolved image id `sha256:843e184865ccb2f161036a149330526a4952750708caa14a4528a8fa49c54d56`, runtime `uid=10001(axiom)`, and 18 of 18 argv cases matching the native binary exactly (0 mismatches), including the empty-argv path exiting `2`. The 18-case parity count was measured against the pre-lifecycle argv surface and is superseded: the container still forwards argv verbatim, but the verbs' exit codes changed when they were wired to real work (see the Unreleased entry above).
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
  > Superseded: this bullet records the `J-003` seed only. All five verbs now dispatch to real actions (see the Unreleased entry above); `version` exits `0`, and the mutating verbs refuse at the engine handoff instead of returning a blanket `NotReady`.
- Added `tests/argv_surface.rs`, which pins usage text against the dispatcher so a verb removed from either one alone fails, and `docs/40-CLI-ARGV-SURFACE.md`.
- The `J-003` slice's recorded development run was Windows x64 with `rustc 1.98.1`. No evidence exists for the lifecycle verbs added later, whose current development host is `macos-x64` (declared finish-first, not certified). No other platform is verified or certified; `spec.lock.json` still needs a verified immutable pin.

### J-007 — the update channel with verification, atomic swap and rollback

- Added `src/update/` (`check`, `plan`, `apply`, `rollback`) and `channels/stable.json`. Versions resolve **only** from the channel manifest the installed release recorded: a branch tip, a tag alias, a network `latest`, a forbidden pin and an unsigned channel are refused. Added `docs/50-UPDATE-CHANNEL.md` and `tests/update_channel.rs` (23 legs).
- Every artifact's length and sha256 are verified before it is used; a mismatch is `artifact_digest_mismatch` and nothing is swapped. An artifact that cannot be obtained from the local cache stays unverified and the verb answers not-ready (`4`, `artifact_unreachable`) instead of reporting an applied update.
- `apply` is transactional: it takes the coordinator lock, stages, writes the journal, renames the generation into place, swaps the active pointer and keeps the previous generation until the new one passes its health probe. A failed verification or health check restores the previous generation, and an interrupted apply is recovered from the journal. `axiom-cli` is one component of the same plan, so self-update and component updates are one transaction with one approval digest, and the plan is refused when the recorded digest no longer matches the installed bytes.
- Reused the frozen exit vocabulary: `0` success, `2` validation, `3` not found, `4` not ready, `5` authorization, `6` conflict, `7` timeout/busy, `8` I/O or internal, `9` incompatible, `10` lock unavailable, `20` partial. `--json` still writes exactly one object carrying `details.reason_code` and `details.reason`.
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
