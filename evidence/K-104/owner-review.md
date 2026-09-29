# K-104 owner review

Source: `9ba9aa125c405e30c2216692ecece5a13bf2c692` on `feature/k-104-macos-mcp-runtime`, based on the Mac entrypoint candidate. The K-012 spec pin is verified from immutable Git bytes. The K-103 wheel, dependency lock, report and handoff hashes were checked before use.

The owned runtime transaction verifies a uv managed CPython 3.13.15 archive, offline wheelhouse, K-103 wheel and 31 hash locked dependencies before activating a new generation. It emits absolute Python and MCP launcher paths and their hashes. The CLI checks those hashes before passing the runtime bin path to the engine. A failed install keeps the active generation; rollback checks the target before changing the pointer. Removal stays inside the explicit owned runtime root and leaves user data elsewhere untouched.

The native Mac x64 test ran in an isolated home with sanitized PATH and no developer venv. It passed clean provision, rerun, corrupt runtime and wheel, unsupported interpreter, missing dependency, interrupted provision, rollback including tampering, and owned removal. Rust fmt, clippy, tests and release build passed. The candidate CLI is Mach-O x64. `git diff --check` and a secret/path scan passed. Runtime and wheelhouse SHA-256 values are in `runtime-input.json` and all command logs are in this directory.

Compatibility: MCP Python remains `>=3.13,<3.14`; K-103 wheel/lock identities remain unchanged. The old engine path is retained when no active runtime pointer exists. This is a local candidate provisioner and verified engine handoff. K-105 will compose it into an installed user flow; K-107 will test full MCP query and process behavior. No release signature, publication, or main integration is claimed.
