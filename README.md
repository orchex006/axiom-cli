# Axiom CLI

`axiom-cli` installs, checks, updates and removes the Axiom ecosystem on your machine:

- `axiom-cli` itself.
- The graph engine, `axiom` and `axiom-graphd`.
- The MCP server and the skills bundle.

## Install

Windows (normal PowerShell, not Administrator):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://github.com/orchex006/axiom-cli/releases/latest/download/install.ps1 | iex"
```

Linux, WSL2 or macOS Intel (normal user, not `sudo`):

```sh
curl -fsSL https://github.com/orchex006/axiom-cli/releases/latest/download/install.sh | sh
```

The script checks the download's SHA-256, shows what it will install and asks once. Then open a new terminal and run:

```sh
axiom-cli version
axiom-cli doctor
```

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
