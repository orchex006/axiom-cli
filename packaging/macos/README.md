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
