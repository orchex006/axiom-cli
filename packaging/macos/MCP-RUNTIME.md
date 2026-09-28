# K-002 offline MCP runtime candidate

`Build-McpBundle.py` assembles a separate Intel Mac payload from exact bytes:

- CPython 3.13.15 `install_only_stripped` from `python-build-standalone` release `20260924`, pinned by SHA256 in the packager.
- `axiom-mcp` wheel 0.1.0 built from owner revision `b947b697ac931dead8e3983d4d72c1c998be7d33`, pinned by SHA256 in the packager.
- 31 dependency wheels resolved for CPython 3.13 on Intel macOS by `mcp-requirements.lock`, with complete accepted distribution hashes. The resolver bound `cryptography<49` so the exact Intel Mac wheel is available.

The packager copies the inputs and two clean-user installer scripts to an empty output directory, creates `mcp-bundle.json` with every artifact's SHA256 and size, then unpacks **the copied standalone interpreter** in a temporary directory. It creates an isolated venv and installs the copied wheelhouse with `--no-index` and `--require-hashes`; it installs the owner wheel with `--no-deps`, runs `pip check`, and launches `axiom_mcp.cli version --json`. Thus a packaging success proves dependency closure using the bytes delivered to the host. A candidate bundle is unsigned and unpublished.

Example after fetching the pinned runtime and preparing the exact wheelhouse on the build host:

```sh
python3 packaging/macos/Build-McpBundle.py \
  --runtime /path/to/cpython-3.13.15-x64.tar.gz \
  --mcp-wheel /path/to/axiom_mcp-0.1.0-py3-none-any.whl \
  --wheel-dir /path/to/wheelhouse \
  --out-dir /path/to/empty-output
```

The bundled `Manage-McpEnvironment.sh` runs on a clean Intel Mac with only system shell tools. It checks the pinned runtime archive before bootstrapping Python from that archive, then the Python manager checks every manifest artifact before modifying the owned root. `install --dry-run` computes an approval digest; `install --apply --approve-digest` creates a hash-named version directory with a standalone runtime, copied venv interpreter, owner wheel, the MCP owner's `lockfile.json` launch record, frozen package list and file inventory. The copied interpreter stays inside the versioned venv, as the owner's locked entrypoint resolver requires. `current.json` names that generation in both installer and MCP launch layouts. `rollback --to <manifest SHA256>` activates an existing verified generation. `uninstall` removes inventory-listed owned files and preserves added files and sibling user data. Both mutating actions require dry-run approval.

Example on the target host:

```sh
sh Manage-McpEnvironment.sh install --bundle /path/to/bundle --dry-run
sh Manage-McpEnvironment.sh install --bundle /path/to/bundle --apply --approve-digest <plan_digest>
sh Manage-McpEnvironment.sh status --bundle /path/to/bundle
```

The installer preserves a modified or unowned file instead of overwriting it. A preserved unknown file in a former generation can block reinstalling that exact generation until the operator resolves the conflict. The native `test_mcp_environment.py` asks the installed wheel's `axiom_mcp.entrypoints.launch_plan` for an isolated stdio plan, then rejects a changed lockfile or a substituted venv script directory; `mcp_catalog_fixture.py` launches graphd against actual C# source and queries both original and edited catalogs through the installed wheel, with no `axiom-mcp/src` import path. The bundle is not yet connected to the `axiom-cli install` transaction or the engine's executable discovery, and no two-version MCP update has been certified. K-002 remains in progress.
