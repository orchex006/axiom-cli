# macOS x64 installer wrappers

These scripts are thin adapters to `axiom-cli`. The CLI verifies the release
set and invokes the `axiom` installation engine with explicit argv; the scripts
do not copy, delete, hash, or register services themselves.

They operate in an isolated per-user root when `AXIOM_CLI_INSTALL_ROOT` is set.
They never call `sudo`, edit shell startup files, alter global PATH, bypass
Gatekeeper, or run `launchctl`. The engine now provides owned per-user service
registration/control and approval-bound uninstall. The scoped Mac x64 lifecycle
passes; these wrappers still require supplied entrypoints and do not manage
per-user shell PATH. See `docs/32-LOCAL-LIFECYCLE-GAPS.md` for remaining acceptance.
