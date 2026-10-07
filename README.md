# Axiom CLI

`axiom-cli` installs, checks, updates and removes the Axiom ecosystem on your machine:

- `axiom-cli` itself.
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
axiom-cli update
```

### macOS, Linux and WSL2 (not as root)

Install:

```sh
curl -fsSL https://github.com/orchex006/axiom-cli/releases/latest/download/install.sh | sh
```

Update:

```sh
axiom-cli update
```

The install script checks the download's SHA-256, shows what it will install and asks once. After installing, open a new terminal and check the result with `axiom-cli version` and `axiom-cli doctor`.

`axiom-cli update` shows the plan, asks once and keeps the previous version for rollback. It prints `up to date` when nothing is newer. On 0.1.2 or older, `axiom-cli` has no one-command update; run the install command instead, after the steps in [Upgrading from 0.1.0 or 0.1.2](docs/INSTALL.md#upgrading-from-010-or-012).

**Full guide:** [docs/INSTALL.md](docs/INSTALL.md) covers requirements, options, where files go, update, uninstall, upgrading from 0.1.0/0.1.2 and troubleshooting.

## Commands

| Command | What it does |
|---|---|
| `axiom-cli install` | Install or repair Axiom (shows the plan, asks once) |
| `axiom-cli version` | Show the installed and available versions |
| `axiom-cli doctor` | Check the installation; changes nothing |
| `axiom-cli update` | Update to the newest release (asks once; keeps a rollback) |
| `axiom-cli uninstall` | Remove the programs and PATH entry; keeps your data |

Run `axiom-cli --help` for every option and exit code.

## For maintainers

- [Distribution and installers](docs/30-DISTRIBUTION-AND-INSTALLERS.md): how install, PATH, bootstrappers and legacy adoption work, and their test harnesses.
- [CLI argv surface](docs/40-CLI-ARGV-SURFACE.md) and [update channel](docs/50-UPDATE-CHANNEL.md).
- [Container channel](docs/50-CONTAINER-CHANNEL.md), which has its own publication status.
- [Development contract](Development.md) and [Changelog](Changelog.md).

The installation engine is owned by `axiom-graphd`; this repository packages and verifies releases and never forks that engine. The normative distribution contract lives in `axiom-specs`.
