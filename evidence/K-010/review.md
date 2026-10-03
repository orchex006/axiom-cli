# K-010 Windows final distribution candidate review

The owner source revision is `79eb58cc57bc0d47330df491df59034fe0f22b3b`
on `feature/k-010-windows-final-lifecycle`. It packages the exact K-309 core
revision `4f8765a74ae5f077f53d092ddb4fea40d0c44fe3` into an unsigned
Windows 0.1.2 kit (ZIP SHA-256
`70113cd08b01b6d41dc535ba962101b4ffee8ec976d6e276118f4468bd72ca73`).
The K-305 A archive remains byte-exact. `reproducibility.json` records two
equal ZIP, kit-manifest, candidate-files and release-set outputs.

## Acceptance

- **AC1:** A new native Windows 11 x64 install root received K-305 A through
  the shipped per-user installer, pinned Python 3.13.15/MCP wheel and graphd
  engine. The public B kit check/plan/apply changed CLI and core to 0.1.2;
  B daemon SHA `2c85a61a8f03f433b5cde82ba05e70eeabdc4e3a56fd4c003cc733a023f86164`
  matches K-309. The installed public service registered a Limited Scheduled
  Task, ran a C# query, published a new generation after an edit and stopped
  through the owner API. The installed MCP wheel passed all seven native query,
  stdio and HTTP security matrix legs. B service uninstall followed by public
  rollback restored A 0.1.1. Engine, runtime and distribution uninstall kept
  the user-data sentinel; no task/process remained and HKCU Path value/type
  matched the pre-run snapshot.
- **AC2:** `native-report.json` and `logs/` retain redacted command results,
  observed exit codes and SHA-256 links to exact local raw outputs. The K-010
  kit refused corrupt and incompatible variants without changing A. The build
  refused the prior K-308 core manifest. Rollback while a service had been
  registered after B activation returned exit 2 with exact B pointers and the
  Running task unchanged; the operator then removed the owned service and
  rollback passed. A separate Limited Task installed and uninstalled the final
  B release set with `is_elevated=false`, all exits 0 and HKCU Path restored.
  No WSL, Bash, Docker or elevation was required.

The test capture deliberately omits the registry Path value, machine paths and
account name from committed logs. Raw outputs and their hashes remain in the
isolated local run directory; the committed `logs/` preserve command results
after redaction. The `tests/windows/capture_k010_final.py` checker validated
the final kit and every recorded acceptance condition before import.

## Remaining release work

The installed `axiom migrate plan` returned `NOT_READY` (exit 4). That gate
requires separate graphd implementation and installed migration evidence;
K-010's listed AC1 lifecycle has no migration verb. The kit is unsigned and
unpublished. K-601/K-602 and aggregate K-005/K-008/K-009 still need released,
trusted three-lane evidence and release authority. Independent CI review and
main integration are not claimed.
