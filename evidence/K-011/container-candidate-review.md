# K-011 Linux container dependency spike

The input CLI image was built from source revision
`80ee16f37166220175f9bfbca54fa6514a0a7bba` with:

```sh
docker build --platform linux/amd64 -f containers/Dockerfile \
  --build-arg AXIOM_REVISION=80ee16f37166220175f9bfbca54fa6514a0a7bba \
  --build-arg AXIOM_VERSION=0.1.0 \
  --build-arg AXIOM_CREATED=2026-09-28T00:00:00Z \
  -t axiom-cli:k011-k002-candidate .
```

It resolved to local image ID
`sha256:2778033ca84a28d3ef9fbf38ccf33e5880ddeff3cbfba0929968c868b8a87f0f`
with Linux/amd64, configured uid/gid `10001:10001` and the exact source
revision label. The runtime was
`python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26`.
The harness required uid 10001 and Python 3.13.15, and used `--network none`
for every runtime operation. Docker Desktop server was 29.6.1 Linux/amd64.

The Linux K-006 core archive and candidate manifest were read from
`axiom-specs` branch `feature/k-006-core-candidates` under
`evidence/artifacts/K-006/90c5865c8b3e3c09980b6f78bf5e359bd95a21c5/linux-x64/`.
The input archive SHA-256 was
`a1f5e5dd5a573bb33ba3c9192b6fc11d45ae92875e845b15a849f2c1cd1f75ac`.
The MCP owner wheel was the K-002 pinned wheel
`365d4d2baa3b155b1c2cb661fdfd8439db1f628ba9ea524e0b0ee49d14c22705`.
The skills bundle was the minimal J-005 engine fixture.
The Linux dependency wheelhouse was acquired in the pinned Python image with
`python -m pip download --only-binary=:all: --require-hashes -r /lock -d /wheels`
against `packaging/macos/mcp-requirements.lock` (SHA-256
`5cf467f4d856044458d29124fa866632fdf64f398dd3fd227f6b6d3501ed99c9`).
This acquisition used network; the harness used the resulting 31 wheels with
`--network none`, `--no-index` and `--require-hashes`. Their individual Linux
wheel hashes are recorded in the machine-readable result. The catalog source
fixture SHA-256 was
`54eb10fd18b5f4ab659bf85c5f1d6c8b966eccad28de017b53f175cd72da3e9f`.

The exact harness invocation, after materializing the core archive and manifest
at the two paths shown, was:

```sh
python3 tests/container/test_k011_candidate.py \
  --cli-image axiom-cli:k011-k002-candidate \
  --cli-revision 80ee16f37166220175f9bfbca54fa6514a0a7bba \
  --core-archive /tmp/axiom-k011-core-linux-x64.tar.gz \
  --core-manifest /tmp/axiom-k011-core-manifest.json \
  --mcp-wheel /tmp/axiom-k002-bundle-v11/wheels/axiom_mcp-0.1.0-py3-none-any.whl \
  --skills-bundle evidence/J-005/local-lifecycle-20260922/fixture-template/skills \
  --linux-wheelhouse /tmp/axiom-k011-linux-wheels \
  --dependency-lock packaging/macos/mcp-requirements.lock \
  --catalog-source ../axiom-graphd/evidence/engine-readiness-20260922/sqlite-default-wal-e2e-Demo.cs \
  > evidence/K-011/container-candidate-check.json
```

Exit code was 0. The output SHA-256 is
`f5478fd229b7e3bef17685dbef9c6d646f0f3018b620ea6a96426225d48601f9`.
Its events record install plan 0, stale approval refusal 6, same-size corrupt
wheel refusal 2, real engine install and byte/version verification 0, offline
missing-dependency refusal 1, installed-wheel catalog query before/after a
source edit and again after daemon restart 0, and approved uninstall 0. The
three catalog generation IDs in the result differ. The user note remained
byte-identical with SHA-256
`3e6d6dae4a1a38ece9e3d1c75e62aaa95e8af39a6660da8babafd9b281b4ce91`.
The engine installed the verified graphd binary and MCP wheel. The harness
created a separate, test-prepared venv for the query; neither CLI nor engine
provisioned or registered that MCP environment.

This is an unpublished dependency spike. The released image still carries
only `axiom-cli`; this harness executes its verified binary in a separate
digest-pinned Python runtime image. No complete OCI artifact, owner-managed
MCP environment, engine-consumed MCP launch plan, released skills, two-version
update/rollback, registry publication, Windows or WSL2 execution is proved.
The catalog query and restarted watcher are container candidate evidence only;
K-011 AC1/AC2 remain open.
