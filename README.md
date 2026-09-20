# axiom-cli

Component seed for Axiom Graph Ecosystem, specification `2.0.0-draft.1`. This directory contains development governance and co-located documentation/templates, not a finished executable or published package.

**Owner scope:** canonical distribution of the installed ecosystem — the distributed entrypoint, native installers, transactional install/update/uninstall, container image publication and the update channel manifest. The installation engine stays owned by `axiom-graphd` and is wrapped, never re-implemented.

## Start development

Obtain the `axiom-specs` repository and pin its immutable commit plus content digest in `spec.lock.json`, using `spec.lock.example.json` only as a shape example. The example deliberately has no invented revision. Resolve the source-of-truth and task ledger through that pin; do not rely on this seed's location in a ZIP or assume a sibling checkout path.

Read [Development.md](Development.md), [AGENTS.md](AGENTS.md), [documentation](docs/README.md) and the owner spec `J-axiom-cli.md` in the pinned specification. Select bounded tasks whose `repo` equals `axiom-cli`; A–G and J IDs preserve workstream history and no longer encode repository membership.

## Repository boundary

Code, installers, local tests, version/release manifests, [Changelog.md](Changelog.md) and docs move together. Shared schemas and public protocols change first through an approved spec revision. No separate bootstrap, docs or conformance repository is required.

## Platform support status

Windows x64, macOS x64 and the GitHub Container Registry image are the finish-first delivery tier; Linux x64 including the WSL2 lane and macOS arm64 are design-complete and stay unverified until a native run is recorded. There are no runtime artifacts or native certification results in this seed. A release must carry target-specific evidence from the current platform matrix, not infer support from a cross-compile or from a published container image.

## Implemented surface

Card `J-003` added the argv surface: a Rust binary named `axiom-cli` builds from `Cargo.toml` with no
third-party dependencies, and exposes the five contract verbs `install`, `update`, `doctor`,
`version` and `uninstall` with the canonical exit vocabulary. Every verb is declared but not yet
wired to the engine, so each one answers `NotReady` (exit `4`) with a stated reason instead of an
empty success. See [docs/40-CLI-ARGV-SURFACE.md](docs/40-CLI-ARGV-SURFACE.md). The installation
engine stays in `axiom-graphd`; nothing here installs, updates or removes anything yet.

Card `J-004` added the first real, executed distribution slice: a per-user Windows x64 installer and
uninstaller plus the release-set packaging step, all runnable from the shipped Windows shell with no
WSL, Bash, Docker or elevation. `installers/windows/` holds `AxiomCli.Windows.Common.ps1`,
`Install-AxiomCli.ps1` and `Uninstall-AxiomCli.ps1`; `packaging/windows/Build-ReleaseSet.ps1` produces
the release set whose sha256 is the single approval digest, and `packaging/install-result.schema.json`
is the install-result envelope schema. `tests/windows/Invoke-AxiomCliWindowsDistributionTests.ps1`
executes 26 legs and writes `evidence/J-004/`. See
[docs/30-DISTRIBUTION-AND-INSTALLERS.md](docs/30-DISTRIBUTION-AND-INSTALLERS.md). The released
`axiom-cli.exe` itself is still an argv surface whose verbs answer `NotReady`; the installer verifies
and installs artifacts but `axiom-graphd` core artifacts are not built yet, so they stay recorded as
unverified rather than installed. `windows-x64` is not certified.

`spec.lock.json` is still unset: this seed ships only `spec.lock.example.json`, and a verified
immutable `axiom-specs` pin has not been recorded.
