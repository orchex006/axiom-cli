#!/bin/sh
# axiom-cli container entrypoint.
#
# The container exposes the same argv surface as the native binary: the five verbs
# `install`, `update`, `doctor`, `version` and `uninstall`; the global options
# `-h`/`--help`, `--json` and `--verbose`; and the canonical exit vocabulary
# (0 2 3 4 5 6 7 8 9 10 20).
#
# It deliberately does nothing else:
#   * argv is forwarded as a program plus an argument vector - never re-split,
#     re-quoted or concatenated into a shell string;
#   * no verb is intercepted, renamed or re-implemented;
#   * exit codes come from the binary unchanged, including `4` NotReady for a
#     declared-but-unbuilt verb and `2` for a missing verb.
#
# The container must never turn an unbuilt verb into a success, and a run inside it
# must never look like native evidence for a native target.

set -eu

exec /usr/local/bin/axiom-cli "$@"
