# K-011 owner review — local container-linux-x64

Result: AC1 and AC2 passed on a fresh named volume `axiom-k011-home`.
This is an unsigned, unpublished local candidate; `certified: false`.

## Exact artifact identity

- Final local OCI image `axiom-k011-final:local`: image ID
  `sha256:5eefb9516c2821064e52cd54559dbed549a15a01213f049aa8f55c26740496b1`,
  `linux/amd64`, uid/gid `10001:10001`; revision label is owner base
  `c98846964cf1bf89f4177a1e85de9a27bbe716d0` (see full inspect and build log).
  Its CLI binary SHA is `488ddfa41ea757a1e5e645e7764320d2547d654889fe1fcfa90f7970893f7d6d`,
  identical to the B OCI lifecycle image binary. The latter image ID is
  `sha256:044ff2cc44f0248f98305f481b0f50b6980c23006600044c339d85809d0d4bb3`.
- A kit archive SHA `93deb468f2a77085cb5a60936819cdf11c6de4edf9771c881248557d99cedfa9`;
  B kit archive SHA `ac13cfddeffbd720965b4415f65de8fb74bf9c457527eda9c4f5ac0e50452312`.
  They were extracted into the owned volume; `kit-extract.jsonl` records the
  verification. `runtime-provision.json` records the K-404 managed runtime.
- Dockerfile pins both builder and runtime base digests. There is no registry
  publication digest; local Docker image IDs are recorded here.

## Commands and outcomes

All Docker commands used `--platform linux/amd64`, volume
`-v axiom-k011-home:/home/axiom`, and the image default non-root user or
`--user 10001:10001`. The Python tool image was
`sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26`.

1. `Provision-McpRuntime.py provision` from the K-404 pinned inputs, then
   `kit-a/release/axiom-cli install --dry-run --from kit-a/release --json` and
   `install --apply --from kit-a/release --approve-digest <plan digest> --json`:
   exit `0` each. The engine A and CLI A installed with digest approval;
   see `engine-plan-a.json`, `engine-install-a.json`, `cli-plan-a-clean.json`,
   `cli-install-a.json`.
2. `k406_query_watch.py --home /home/axiom --symbol K011WatcherA --setup`:
   exit `0`; real C# source query, watcher edit and foreground SIGINT drain.
3. `k011_negative.py --home /home/axiom --kit /home/axiom/k011/kit-b
   --incompatible-kit /home/axiom/k011/kit-a --scratch /home/axiom/k011/corrupt-b`:
   exit `0`, eight expected exit-`2` refusals for wrong approval, corrupt kit,
   incompatible set, and injected download, stage, activation, service restart,
   post-entrypoint failures. Active CLI, engine, skills and runtime pointer
   hashes, bindings, source and user data stayed equal to baseline; pending and
   receipt files were absent. Retained inactive B graphd and CLI binaries
   match the kit SHA. See `negative.json`.
4. From actual OCI entrypoint with `AXIOM_CLI_INSTALL_ROOT` and
   `AXIOM_CLI_COMPOSITE_KIT` set: `update plan --to 0.1.1 --out
   /home/axiom/k011/plan-b.json --json`, `update apply --plan ...
   --approve-digest b9277d2f9d5c51add0b762c62489a9bab15fead1c03baf0d44817c65939e9fe0
   --json`, `update check --json`: exit `0`, statuses `planned`, `updated`,
   `up_to_date`. CLI B SHA `488dd...`; graphd B SHA `87b614...`.
5. `k406_query_watch.py --home /home/axiom --symbol K011WatcherB`:
   exit `0`. OCI `update rollback --transaction previous --json`: exit `0`,
   status `rolled_back`, CLI A SHA `02d7c...`, graphd A SHA `c34f9...`.
   `k406_query_watch.py --symbol K011WatcherRestored`: exit `0` after a fresh
   foreground daemon start, proving restart and restored query/watcher behavior.
6. `axiom uninstall plan --out /home/axiom/k011/engine-uninstall-plan.json
   --json` then `axiom uninstall apply --plan ... --approve-digest
   eba200e76dc5d514255e537bf3758ea14f0e5e487fb9adba2e59d2ec26e910b0
   --json`: exit `0`, owned engine removed. `Uninstall-AxiomCli.sh --plan`
   then `--apply --approve-digest
   235372506185ecc144711e37c63bedbfcdde7d38ba73b319880c9e1c4d7f8cc5`:
   exit `0`, CLI removed. `Provision-McpRuntime.py remove`:
   exit `0`, owned runtime removed. `retained-data.txt` proves the source,
   bindings and user-data SHA match the pre-removal `query-rollback.json`,
   while all three owned entrypoints or pointers are absent.

## Fresh-volume diagnostic and boundaries

The first negative harness run failed because it assumed no new generation
directory could remain after rollback. `negative-initial-failure.txt` retains
the actual mismatch. Graphd's rollback test
`rolled_back_candidate_can_be_activated_again_from_retained_payloads` confirms
the deliberate retention. The K-011 regression checks inactive payload hashes
and unchanged active state explicitly. It does not weaken the active-state,
data, or no-mixed-activation requirements.

`owner-checks.txt` records clean fmt, clippy, full Rust test suite, Python
compilation and shell syntax checks. Docker Desktop here has no user systemd
manager, so the foreground policy and SIGINT drain were checked; supervisor
registration remains unverified. No registry image was pushed or release
published. Native Linux evidence is a separate lane.
