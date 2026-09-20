# Changelog — axiom-cli

## Unreleased

V2 seed adopts `2.0.0-draft.1`, `.axiom` workspace layout and component-owned docs/tests. Distribution, installer and update-channel implementation and platform certification are pending.

### J-006 — container delivery channel (`ghcr.io/orchex006/axiom-cli`)

- Added `containers/Dockerfile`: a builder and a runtime stage, both base images pinned by digest (`rust:1.85-slim-bookworm`, `debian:bookworm-slim`), a complete OCI label set (title, description, source, url, documentation, version, revision, created, licences), the non-native delimiters `io.orchex006.axiom.channel` and `io.orchex006.axiom.native-evidence="false"`, and a non-root runtime user `axiom` (uid/gid `10001`). The release build is `cargo build --release --locked --offline`, so it fetches nothing beyond the two pinned base images.
- Added `containers/entrypoint.sh`: `exec /usr/local/bin/axiom-cli "$@"`. Argv reaches the binary verbatim, so the container exposes the same five verbs with the same exit codes. No verb is added, renamed or re-implemented, and an unbuilt verb keeps answering `NotReady` with exit `4`.
- Added `.github/workflows/publish-container.yml`: buildx, `linux/amd64` in the finish-first tier, `linux/arm64` only behind an explicit input, immutable version and commit-derived tags with no floating tag, opt-in push, and the resolved digest recorded as a build artifact and in the run summary. It never overrides the base-image pins and certifies no platform.
- Added `tests/container_distribution.rs`, which pins the base digests, the OCI label set, the non-root user and uid, the `VERSION` to `ARG AXIOM_VERSION` link, the argv-forwarding entrypoint, the immutable-tag rule, the arm64 gate, the opt-in push default and the digest recording.
- Added `docs/50-CONTAINER-CHANNEL.md` (build and run procedure, digest-recording location, offline or air-gapped variant) and linked it from `docs/README.md`.
- Verified locally on Windows 11 x64 with Docker Desktop 29.6.2 (engine `linux/amd64`) at revision `7ac376b`: image build exit `0`, resolved image id `sha256:843e184865ccb2f161036a149330526a4952750708caa14a4528a8fa49c54d56`, runtime `uid=10001(axiom)`, and 18 of 18 argv cases matching the native binary exactly (0 mismatches), including the empty-argv path exiting `2`.
- No publication happened: no push to `ghcr.io`, no image tag and no release. `distribution.container.published_image_digest` in the platform matrix stays `null`, `linux/arm64` is unbuilt, and a container run is never recorded as native evidence for any native target.

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
