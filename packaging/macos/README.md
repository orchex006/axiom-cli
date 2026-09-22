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
