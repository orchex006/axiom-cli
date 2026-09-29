# K-106 owner review — native macos-x64 local candidate

A is the K-105 archive SHA-256 `caeee2470868b67367c27bbfc368171ba744bcf92c18afafe85d61a9fca2c86f`.
B is this task's 57-file archive SHA-256
`5e8c7efb2c40acf8c1b29af5061962090d12e02b391de5de5ea441cb67f1314e`.
The B CLI source commit is `e6b9d2086ba62b5b32c33fe2c3edc49353a22851`;
the graphd owner core source commit is
`c4f643ebf7af95395d12cbba8572e7065254e8b4`. The latter declares local
core version 0.1.1 and passes its own native package verifier. MCP 0.1.0,
owner skills 0.1.0, and uv managed CPython 3.13.15 remain at their pinned
K-103/K-101/K-104 bytes. The B packager checked these hashes; archive extraction
was checked byte for byte against all 57 tested files.

`native-report.json` and `native-transcript.json` record public bootstrap
install A, real C# graph/catalog query and persistent watcher, update B,
query/watcher on B, service status, explicit rollback and query/watcher after
restoration. CLI and graphd bytes change; MCP and skills stay at their pinned
versions. Entry point, engine and skills pointers, runtime pointer, both
executables, bindings and user data return to exact A hashes. Corrupted B core
and incompatible B channel are refused before mutation. Injected download,
stage, activation, service restart and post-activation failures each preserve A.

`crash-report.json` and `crash-transcript.json` record an actual coordinator
process exit 97 after the engine returned and before its transaction was
captured. The next public `recover` dry-run/apply discovered the one matching
outer engine journal, invoked public `axiom update rollback --transaction`,
restored every A hash and cleared pending. A fresh B update then succeeded,
followed by rollback; user data remained unchanged. Engine-owner tests cover
`prepared` journals before and between pointer moves, foreign transaction and
changed retained payload refusal. Native SIGKILL at every internal engine
substep remains unrun and is not claimed.

Owner checks: `cargo fmt --all --check`, `cargo clippy --locked --all-targets --
-D warnings`, `cargo test --locked` (202 tests, 0 failed), offline Ruff check
and format check for changed Python, Python unit recovery/preflight tests
(10 passed), Python compilation, `git diff --check`, changed-file token/key
pattern scan, native release build and exact archive comparison. No signing,
notarization, publication, tag, certified lane or main integration is claimed.
Independent shared-update review remains pending. The older progress and
engine-handoff notes document discovery; this review records the resolved
local candidate behavior and its limits.
