# Axiom CLI

`axm` (short for `axiom-cli`) installs, checks, updates and removes the Axiom ecosystem on your machine:

- `axm` / `axiom-cli` itself (two names for the same program).
- The graph engine, `axiom` and `axiom-graphd`.
- The MCP server and the skills bundle.

## Install and update

### Windows (PowerShell 5.1+, no Administrator)

Install:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://github.com/orchex006/axiom-cli/releases/latest/download/install.ps1 | iex"
```

Update:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://github.com/orchex006/axiom-cli/releases/latest/download/update.ps1 | iex"
```

### macOS, Linux and WSL2 (not as root)

Install:

```sh
curl -fsSL https://github.com/orchex006/axiom-cli/releases/latest/download/install.sh | sh
```

Update:

```sh
curl -fsSL https://github.com/orchex006/axiom-cli/releases/latest/download/update.sh | sh
```

The install script checks the download's SHA-256, shows what it will install and asks once. After installing, open a new terminal and check the result with `axm version` and `axm doctor`.

The update script finds your installation and runs its `axm update`, which shows the plan, asks once and keeps the previous version for rollback; it prints `up to date` when nothing is newer. If Axiom is on your PATH, `axm update` does the same. The update script also upgrades a 0.1.0/0.1.2 installation, but first remove the old `AXIOM_*` variables ([Upgrading from 0.1.0 or 0.1.2](docs/INSTALL.md#upgrading-from-010-or-012)). The update script is published from 0.1.4.

**Full guide:** [docs/INSTALL.md](docs/INSTALL.md) covers requirements, options, where files go, update, uninstall, upgrading from 0.1.0/0.1.2 and troubleshooting.

## Commands

| Command | What it does |
|---|---|
| `axm install` | Install or repair Axiom (shows the plan, asks once) |
| `axm version` | Show the installed and available versions |
| `axm doctor` | Check the installation; changes nothing |
| `axm update` | Update to the newest release (asks once; keeps a rollback) |
| `axm uninstall` | Remove the programs and PATH entry; keeps your data |

Run `axm --help` for every option and exit code. `axm` is installed from 0.1.5; on 0.1.4 or older use `axiom-cli` (same verbs), or run the update script once to get `axm`.

## For maintainers

- [Distribution and installers](docs/30-DISTRIBUTION-AND-INSTALLERS.md): how install, PATH, bootstrappers and legacy adoption work, and their test harnesses.
- [CLI argv surface](docs/40-CLI-ARGV-SURFACE.md) and [update channel](docs/50-UPDATE-CHANNEL.md).
- [Container channel](docs/50-CONTAINER-CHANNEL.md), which has its own publication status.
- [Development contract](Development.md) and [Changelog](Changelog.md).

The installation engine is owned by `axiom-graphd`; this repository packages and verifies releases and never forks that engine. The normative distribution contract lives in `axiom-specs`.
