# K-011 unpublished single-image Linux candidate

Date: 2026-09-28. Scope: local Docker Desktop `linux/amd64` integration
candidate only; not the final OCI distribution, registry publication, or native
Linux host evidence. The structured run is in `combined-image-candidate-check.json`.

Inputs: CLI source revision `fcff112a9541b9c4d77b12e33db3f9b30c4de74e`,
K-006 core revision `90c5865c8b3e3c09980b6f78bf5e359bd95a21c5`, MCP wheel
revision `b947b697ac931dead8e3983d4d72c1c998be7d33`, 31 Linux dependency
wheels from the locked MCP requirement set, and a minimal skills fixture.
The builder base is `rust:1.85-slim-bookworm@sha256:9f841bbe9e7d8e37ceb96ed907265a3a0df7f44e3737d0b100e7907a679acb36`;
the runtime base is `python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26`.

The exact positive commands were:

```sh
python3 tests/container/build_k011_combined_image.py \
  --release /tmp/axiom-k011-release \
  --linux-wheelhouse /tmp/axiom-k011-linux-wheels \
  --dependency-lock packaging/macos/mcp-requirements.lock \
  --revision fcff112a9541b9c4d77b12e33db3f9b30c4de74e \
  --created 2026-09-28T00:00:00Z \
  --tag axiom-cli:k011-combined-rebuild
python3 tests/container/test_k011_combined_image.py \
  --image axiom-cli:k011-combined-rebuild \
  --cli-revision fcff112a9541b9c4d77b12e33db3f9b30c4de74e \
  --release /tmp/axiom-k011-release \
  --catalog-source ../axiom-graphd/evidence/engine-readiness-20260922/sqlite-default-wal-e2e-Demo.cs \
  > evidence/K-011/combined-image-candidate-check.json
```

Both returned exit 0. Local image ID:
`sha256:85a3ecf8e08a4f3a59a38a0792640b51ce4767bc64bf108268e41e3322db4afd`,
size 77,989,585 bytes, configured uid/gid `10001:10001`. All runtime commands
used `--network none`. The builder used `--network none` for build steps and
`cargo --locked --offline`; Docker still resolved already-pinned base metadata.
The image is locally tagged and has no published registry digest.

The harness checked core, MCP wheel, channel, skills manifest and release-info
hashes against the release inputs. It recorded install-plan approval, stale
approval refusal (exit 6), installed engine/MCP file hashes, live MCP wheel
catalog query before/after a C# edit and after graphd restart, approved
uninstall, and retained user-note hash. The MCP query used a test-owned copy
of the baked venv with the engine-placed MCP wheel reinstalled into it.

For the negative image-build check, the last byte of a copy of the MCP wheel
was flipped without changing its length. Running the same build command with
`--release /tmp/axiom-k011-corrupt-release` and
`--tag axiom-cli:k011-corrupt-check` exited 1. The Dockerfile's `sha256sum
--check --strict` reported the MCP wheel `FAILED` and `1 computed checksum did
NOT match`; no corrupt image was created. This complements the stale-approval
refusal in the lifecycle run.

Source hashes: candidate Dockerfile
`4d21b87e5a21da812a37ec5e5f09f93c9c47b68b51d0f6a412ef1978048abd87`,
build script `1dd55904c45f52558c254444004bedc02719da0fe2384792a7667589428c61de`,
lifecycle script `e5b4dc3db16d5226c494e8a6dc1ddddd6404f5feea2f44f2221f94f081666bbd`.
The dependency lock hash is
`5cf467f4d856044458d29124fa866632fdf64f398dd3fd227f6b6d3501ed99c9`.

Open K-011 acceptance: this image is not wired into `publish-container.yml`;
K-003 has no approved composite activation/handoff; owner-managed MCP
environment, integrated update/rollback, and foreground/supervisor behavior
are unverified. The skills bundle is only a fixture. Neither AC1 nor AC2 is
complete, and this evidence does not authorize a release claim.
