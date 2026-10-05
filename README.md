# Axiom CLI

The native distribution entrypoint for the Axiom ecosystem. The 0.1.2 test release combines `axiom-cli`, the core (`axiom` and `axiom-graphd`), one portable MCP wheel and one portable skills bundle, with source revisions and SHA-256 checksums.

Download the matching Windows x64, Mac Intel or Linux x64 archive from [GitHub Releases](https://github.com/orchex006/axiom-cli/releases/tag/v0.1.2). WSL2 uses the identical Linux archive. Mac ARM is excluded from this test release. Follow the included README: extract to a new directory, verify SHA256SUMS, choose a fresh per-user root, preview the install plan, then apply its exact approval digest. No certification, signing, Docker, WSL-on-Windows, Bash or elevation is required for native delivery.

The installer engine is owned by `axiom-graphd`; this repository composes and verifies owner payloads, and never forks that engine. MCP/skills stay portable. MCP stdio runs as an AI host child; optional HTTP is foreground. Configure scoped credentials separately; a bare gateway grants no tool authority.

The public entrypoint exposes `install`, `update`, `doctor`, `version` and `uninstall`. Existing retained-generation and data-preserving workflows remain. The packaged local channel is an offline verified payload description; existing signed automatic network update protocols are unchanged.

See [0.1.2 test release instructions](release/v0.1.2-notes.md), [development contract](Development.md) and [owner documentation](docs/README.md). Actual publication/source/platform results are recorded in `release/v0.1.2-receipt.json`; build success is not inferred as WSL or licensed AI host verification.

The separate [container and air-gapped channel guide](docs/50-CONTAINER-CHANNEL.md) retains its own publication status; native Release archives do not imply a new OCI image was published.
