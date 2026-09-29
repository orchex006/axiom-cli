# K-003 distribution update safety boundary

Branch `feature/k-003-composite-update-guard` starts from `axiom-cli` main
`e20aeca`. The K-003 activation RFC remains Proposed in `axiom-specs` branch
`spec/v2-k003-composite-activation`; no shared activation contract is approved.

The J-007 update code changes only `installed.json`, while the installed engine
ecosystem uses `installs/ecosystem/current`. Until both resolve one authority,
`axiom-cli update check|plan|apply|rollback` refuses exit 4 with
`composite_activation_not_ready` whenever the engine pointer is active. The
regression fixture records both pointers before each verb and proves neither
changes; `plan` creates no approval file.

Commands on macOS x64, 2026-09-29:

```text
cargo test --test update_channel  -> exit 0, 24 passed
cargo fmt --check                 -> exit 0
git diff --check                  -> exit 0
cargo test                        -> exit 101, 60 passed, 1 failed
```

The full-suite failure is the pre-existing cross-platform unit test
`update::health::tests::an_absolute_probe_program_is_used_as_written`, which
expects a Windows `D:/` path to be absolute on macOS. The new update-channel
suite passes. This is a fail-closed interim boundary, not K-003 AC1/AC2.
