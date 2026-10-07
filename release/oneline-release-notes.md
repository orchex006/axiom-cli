# Axiom release

Install with one command (ADR-0033). Each script is pinned to this release's tag and archive SHA-256 values, refuses to run elevated, verifies the archive before extracting and then runs `axiom-cli install`, which shows the plan and asks once.

Windows (PowerShell 5.1+):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://github.com/orchex006/axiom-cli/releases/latest/download/install.ps1 | iex"
```

macOS, Linux and WSL2:

```sh
curl -fsSL https://github.com/orchex006/axiom-cli/releases/latest/download/install.sh | sh
```

Pinned to this version: replace `latest/download` with `download/<tag>`.

Then `axiom-cli version`, `axiom-cli doctor`, `axiom-cli update` and `axiom-cli uninstall` (user data is kept). Every asset is listed in `SHA256SUMS`; `channel.json` is the update channel for `axiom-cli update`.

Full guide, covering options, upgrading from 0.1.0/0.1.2 and troubleshooting: https://github.com/orchex006/axiom-cli/blob/main/docs/INSTALL.md

Release maintainers: `releases/latest/download/…` resolves only to the newest release that is neither a draft nor a prerelease. A release meant for the one-line install MUST NOT be marked prerelease; otherwise users need the pinned `releases/download/<tag>/…` form.
