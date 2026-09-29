# macOS x64 installer wrappers

`Install-AxiomCli.sh --release-set DIR` bootstraps the `axiom-cli` and `axiom`
entrypoints from a three-binary Intel Mac candidate produced by
`packaging/macos/Build-ReleaseSet.sh`. It checks all three Mach-O headers,
artifact sizes and SHA-256 values, then uses a plan digest for approved changes.
The entrypoints live in the user's `~/.local/bin`, with an ownership record and
versioned copy under `$AXIOM_CLI_INSTALL_ROOT/entrypoints` (default
`~/.local/share/axiom/entrypoints`). The managed block in `.zprofile` or
`.bash_profile` adds that directory to the user's shell PATH. Human text outside
the block is preserved; an edited block or an unowned executable is a conflict.
An `AXIOM_CLI_INSTALL_ROOT` override must stay inside the user's home; root
execution and symlinks along managed paths are refused.

```sh
sh installers/macos/Install-AxiomCli.sh --release-set out/macos-x64 --dry-run
sh installers/macos/Install-AxiomCli.sh --release-set out/macos-x64 --apply \
  --approve-digest <plan_digest_from_dry_run>
sh installers/macos/Uninstall-AxiomCli.sh --entrypoints --dry-run
sh installers/macos/Uninstall-AxiomCli.sh --entrypoints --apply \
  --approve-digest <uninstall_plan_digest>
```

The separate `--cli FILE --from CHANNEL` route delegates ecosystem placement
to the installed engine. Service registration/removal stays engine-owned; remove
that service and its ecosystem installation before removing the entrypoints.

The bootstrap never calls `sudo`, changes system PATH, bypasses Gatekeeper,
changes quarantine attributes, or runs `launchctl`. Candidate artifacts remain
unsigned/unnotarized unless a separate release process proves otherwise. The
entrypoint check is a local candidate run; it does not prove the MCP environment,
distribution update bridge or final four-lane lifecycle.

For the K-105 complete candidate, run `runtime/bootstrap.sh` inside the
composed release set. It accepts `install` or `uninstall`, `--release-set`,
`--dry-run` or `--apply`, and an approval digest for apply. The packaged uv
managed CPython 3.13.15 is hash checked and bootstrapped from the release set;
the user machine needs no developer Python or venv. The coordinator provisions
MCP, installs both owned CLI entrypoints and the engine payloads, and registers,
starts and checks the LaunchAgent. It writes an empty local bindings document
only if none exists, and never replaces a user-authored one. Uninstall stops and
removes the service, removes active installed files and owned entrypoints, then
removes the MCP runtime. It retains user data and local bindings.
