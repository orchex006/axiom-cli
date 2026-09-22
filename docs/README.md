# axiom-cli documentation

These guides are owned and released with `axiom-cli`. They describe the behavior this repository implements today and mark what is still pending: all five verbs dispatch to real work, but `install --apply` and `uninstall --apply` stop at the `axiom-graphd` engine handoff, and the update channel is implemented with publication closed. Resolve cross-component normative references through the pinned `axiom-specs` revision; pack-relative references are conveniences inside the distribution only.

- [30-DISTRIBUTION-AND-INSTALLERS](30-DISTRIBUTION-AND-INSTALLERS.md)
- [40-CLI-ARGV-SURFACE](40-CLI-ARGV-SURFACE.md)
- [50-CONTAINER-CHANNEL](50-CONTAINER-CHANNEL.md)
- [50-UPDATE-CHANNEL](50-UPDATE-CHANNEL.md)
- [60-LINUX-AND-MACOS-ARM64](60-LINUX-AND-MACOS-ARM64.md)

The distribution contract and the platform matrix are canonical in axiom-specs. Do not create a local editable copy of them. A published site can aggregate documentation from immutable revisions without an extra repository.
