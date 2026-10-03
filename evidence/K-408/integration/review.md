# Windows and WSL2 owner integration review

Current user authorization permits integrating the delivered evidence. Initial owner checkout was clean on feature/k-408-wsl-lifecycle at b1486c3; canonical main was 4ccd3df. K-305, K-306, K-010, K-408 and their declared upstream tasks are done in the canonical coordination ledger; their original P1-P6/D1-D8 and native evidence are retained.

Merge the Windows source branch 1e3d0f5882c51af6ed6ebd1825373b935d5918c0 into the delivered WSL2 branch. Preserve both append-only Changelog sections. Retain the exact verified newer WSL2 spec.lock.json pin 98202c694990b67bdfa44080f324d01bd611ace9 rather than reverting governance to the older Windows pin. No runtime or shared contract choice is changed by this resolution. The historical Windows pin remains in the source branch and native handoffs.

Review confirms the CLI delegates transactions and service lifecycle to graphd, keeps approval and digest verification, handles the running Windows entrypoint through its owned rollback path and restricts B-service rollback. Windows native evidence and actual WSL2 non-root evidence stay separate. All 110 Windows and 12 WSL2 historical committed evidence blobs match the delivered source exactly. Staged private-key/token-pattern review and whitespace checking with core.whitespace=cr-at-eol passed.

The merged Windows-host checks passed: Rust 1.85.0 fmt, clippy --offline --locked --all-targets -D warnings, 201 Rust tests and release build; four changed Windows Python files passed Ruff lint/format and three WSL policy regression tests passed. Canonical K-010 and K-408 completion validation is recorded in spec-completion.txt. Runtime install/update/uninstall and WSL execution are reused from hashed original evidence; no new native runtime execution is claimed. Signing/publication, production certification and final installed migration remain separate and unpassed. No release tag, installation or machine configuration changed.

The feature/main payload merge SHA and canonical remote verification are recorded after delivery in delivery.json. Main checkout is updated only after these checks pass. No unrelated dirty file is included.
