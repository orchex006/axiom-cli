# CLI argv surface — axiom-cli

Owner: axiom-cli. Frozen by task `J-003`. The normative rules stay in
`axiom-specs/contracts/axiom-cli-distribution-contract.md`
section 2 and `axiom-specs/docs/16-CLI-AND-CONTROL-API.md` sections 1, 6
and 7 of the pinned `axiom-specs` revision. This guide is the owner-side description of the
implemented surface and must not restate a shared schema as an alternative edition.

## One executable, five verbs

`axiom-cli` (`axiom-cli.exe` on Windows) is the single distribution entrypoint. It exposes
`install`, `update`, `doctor`, `version` and `uninstall`. Every documented verb is reachable from
argv and listed by `--help`; the usage text and the dispatcher are pinned against each other by
`tests/argv_surface.rs`, so removing a verb from either one alone fails the suite.

The entrypoint is a thin distribution layer. It obtains, verifies, installs, updates and uninstalls
artifacts; the installation engine, bootstrap rules, service lifecycle and per-component update
transaction stay owned by `axiom-graphd` and are invoked through their published argv surface. This
repository re-implements none of them.

## Invocation

```
axiom-cli [GLOBAL OPTIONS] <verb> [verb options]
```

| Verb | Options implemented in this slice |
|---|---|
| `install` | `--dry-run` \| `--apply`, `--approve-digest <sha256>`, `--from <path>` |
| `update` | `check [--all]`, `plan --to <version> [--out <file>]`, `apply --plan <file> --approve-digest <sha256>`, `rollback --transaction <id> [--approve-digest <sha256>]` |
| `doctor` | `[--all]` |
| `version` | `[--all]` |
| `uninstall` | `--dry-run` \| `--apply`, `--approve-digest <sha256>`, `[--purge-data]` |

Global options: `-h`/`--help` (exit 0), `--json` (machine-readable mode) and `--verbose`
(diagnostics on stderr). `--json` may appear before or after the verb.

Invocation is program plus argv. No verb builds a shell string, requires Bash, WSL, Docker,
elevation or Node.js, mutates `PATH` or performs a silent auto-update.

## Machine-readable mode

`--json` writes exactly one JSON object to stdout and leaves diagnostics on stderr:

```json
{"code":4,"status":"not_ready","message":"...","retryable":false,"details":{...},"request_id":"..."}
```

## Exit vocabulary

The five verbs share the canonical CLI exit-code set owned by `axiom-specs`
`docs/16-CLI-AND-CONTROL-API.md` section 6. This repository defines no private space.

| Code | Meaning |
|---|---|
| `0` | success |
| `2` | validation |
| `3` | not found |
| `4` | not-ready / stale |
| `5` | authorization |
| `6` | conflict |
| `7` | timeout / busy |
| `8` | I/O or internal |
| `9` | incompatible |
| `10` | lock unavailable |
| `20` | partial multi-repository operation |

An unknown verb, a missing option value and an invalid flag combination return `2`.

## NotReady

A verb the distribution contract declares but whose production behaviour is not built answers
`NotReady` with exit code `4` and a stated reason. It never returns `0` and never emits an empty
success envelope. In this slice all five verbs are declared and argv-validated, and each one reports
the engine delegation or manifest work it still needs (`I-003`/`I-004` for the engine handoff,
`J-007` for the pinned channel manifest). A `NotReady` answer means nothing was installed, updated
or removed.

## Plan approval

A mutating `install`, `update` or `uninstall` transaction accepts `--approve-digest <sha256>` as its
approval artifact, bound to the canonical plan digest, exactly as `docs/16-CLI-AND-CONTROL-API.md`
section 7 requires. Supplying `--plan` alone is not approval; a digest that is not 64 hex characters
is rejected as validation. `uninstall --purge-data` additionally requires `--apply` and an explicit
approval, and an uninstall never recursively deletes `.axiom`.

## Building and testing

The binary builds with no third-party dependencies and no network fetch:

```
cargo build --release --offline
cargo test --offline
```

The pinned toolchain records `rust-version = "1.85"` in `Cargo.toml`; `Cargo.lock` pins the resolved
graph. The verified development host for this slice is Windows x64 with `rustc 1.98.1`, and that run
is Windows evidence only. No other platform is certified by this document.
