# macOS x64 packaging

`Build-ReleaseSet.sh` is the J-005 entrypoint for a native Intel macOS build.
It delegates to the shared, architecture-validating macOS recipe with
`--arch x64`; it never cross-builds or labels another architecture as x64.

```sh
sh packaging/macos/Build-ReleaseSet.sh --out-dir out/macos-x64 --build --json
```

The recipe records no signing or notarization assertion. An unsigned artifact
is reported as unsigned; any Gatekeeper or quarantine action remains an
explicit operator action and is not performed by the packager.

For a complete Intel Mac entrypoint candidate, provide the two binaries from
the same pinned core revision:

```sh
sh packaging/macos/Build-ReleaseSet.sh --out-dir out/macos-x64 \
  --cli-binary target/x86_64-apple-darwin/release/axiom-cli \
  --engine-cli /path/to/pinned/axiom --engine-daemon /path/to/pinned/axiom-graphd \
  --core-version 0.1.0 --core-revision <40-hex-core-commit> --json
```

The packager verifies each input is executable x86_64 Mach-O, copies it into
the release set and records its byte count, SHA-256 and declared version. The
core revision argument is the operator's immutable source pin and must match
the build being supplied. `python3` is used only on the packaging host; it is
not a clean-user installation prerequisite. This candidate manifest is not a
signed or published channel manifest: it explicitly declares `unsigned` and
`not_notarized`, and the candidate installer accepts only those declarations.

For a local engine-install candidate, add a pinned MCP wheel and an
engine-format skills bundle after building the entrypoint set:

```sh
python3 packaging/macos/Build-EngineCandidate.py \
  --release-set out/macos-x64 \
  --mcp-wheel /path/to/axiom_mcp-0.1.0-py3-none-any.whl \
  --mcp-sha256 <verified-64-hex-digest> \
  --mcp-revision <40-hex-owner-commit> \
  --skills-bundle /path/to/engine-format-skills
```

The composer checks every declared core, wheel and skills payload byte, then
writes a local `channel.json` with `published: false` and the repository's
development trust root. It does not replace a channel or artifact that already
exists. `axiom-cli install --from out/macos-x64` can then resolve that candidate
locally. A clean user still needs the K-002 versioned Python runtime before
engine apply; the composer does not install Python or pass an MCP executable to
the engine. Full owner skills, final update/rollback and signing remain separate
release requirements. `test_engine_candidate.py` can use `--python` to prepare
Python in its temporary HOME, or `--mcp-bundle` to provision the pinned offline
K-002 bundle there with a system-only PATH. In the latter mode it verifies the
installed owner's absolute stdio launch plan, runs the CLI and engine candidate
install, checks the MCP environment remains active, and removes it with the
other owned files while retaining user data. `--service` also exercises the
isolated LaunchAgent. These are separately approved operations in the test;
the CLI still does not include MCP provisioning or executable/argv handoff in
its engine transaction.
