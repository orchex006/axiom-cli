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
