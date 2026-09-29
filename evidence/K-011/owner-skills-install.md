# K-011 owner skills bundle candidate

On 2026-09-29, the local `axiom-cli:k011-combined-rebuild` Linux/amd64 image
ran the CLI as uid 10001 with network disabled. The release input was a
disposable copy of `/tmp/axiom-k011-release` with the owner manifest and all
41 files from `axiom-skills` commit
`c7deb0ff488507a40bcd9cafff0ddbe0e7783e7d`. The manifest SHA-256 was
`0de50f2dd4525e92dd6a9194192fb4cc9b3a960c6f3f032212a1e2930a05d511`.
Only the disposable channel's skills revision changed; no source release was
published or signed.

```sh
python3 tests/container/test_k011_owner_skills_install.py \
  --image axiom-cli:k011-combined-rebuild \
  --release /tmp/axiom-k011-release \
  --skills-owner ../axiom-skills \
  > evidence/K-011/owner-skills-install.json
```

Exit 0. The CLI planned and applied one approved engine transaction for core,
MCP and the real skills bundle. The harness verified every installed skill
file's SHA-256 and byte count against the owner manifest, then approved
uninstall and verified the active pointer and all 41 owned payloads were
removed while user data survived. The engine intentionally retains
`skills/0.1.0/bundle.json` as recovery evidence. Structured output SHA-256:
`6e194c589f8efee5d02fe651ba958e1d2264a1ef1152eb9b09f236a2328f18dc`.
Harness SHA-256:
`27197116346311bf34a3b3934adebb7ae55654ec922af1004320662b2a7bc913`.

This removes the owner skills manifest refusal from the K-011 candidate. It
does not establish K-003 composite activation, engine-managed MCP launch,
two-version update/rollback, a final signed image or registry publication.
The container certification claim remains false.
