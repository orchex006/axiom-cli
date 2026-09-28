# K-011 candidate foreground and Docker supervision

On 2026-09-28, `tests/container/test_k011_foreground.py` exercised local
candidate image
`sha256:85a3ecf8e08a4f3a59a38a0792640b51ce4767bc64bf108268e41e3322db4afd`
as uid/gid 10001 with network disabled. The input C# fixture SHA-256 was
`54eb10fd18b5f4ab659bf85c5f1d6c8b966eccad28de017b53f175cd72da3e9f`.

```sh
python3 tests/container/test_k011_foreground.py \
  --image axiom-cli:k011-combined-rebuild \
  --source ../axiom-graphd/evidence/engine-readiness-20260922/sqlite-default-wal-e2e-Demo.cs \
  > evidence/K-011/foreground-candidate-check.json
```

The command exited 0. The harness registered a real solution with machine
bindings on a user volume, started `axiom-graphd serve --json` as the container
foreground process, waited for the published catalog, then issued `docker stop
--timeout 10`. Docker reported process exit 0 and graphd reported
`shutdown: Drained`. It restarted the same container on the retained volume,
edited the C# source, observed a changed catalog generation and repeated the
graceful stop. Both shutdowns reported `Drained`; exact generation digests and
exit codes are in `foreground-candidate-check.json` (SHA-256
`f4cdf2e7da544068ef630cf315123ff4a4e34200adfd105637e06c19e29cd126`).
The harness source SHA-256 is
`f2668e3786d7be89a07835a701e772bdadda07d2c094ad5af0f782ea095b197a`.

This checks Docker supervision of a foreground candidate process. It does
not check the final OCI artifact, owner-managed MCP launch, integrated
activation/update/rollback, or registry publication. K-011 AC1/AC2 remain
open.
