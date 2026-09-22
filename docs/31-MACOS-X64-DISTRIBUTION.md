# macOS x64 distribution boundary

J-005 packages native x86_64 Mach-O bytes and routes lifecycle requests through
`axiom-cli` to the `axiom` installation engine. The distribution adapters do not
copy payloads, implement a second uninstaller, or invent a service/update
protocol: they pass verified inputs and approval-bound plans to the owning engine
with argv, never an interpolated shell command.

The local macOS x64 lifecycle has been exercised against a temporary home and
install root. The combined run installed the graph daemon and MCP wheel, verified
that query code loaded from the installed wheel, registered the per-user
`com.axiom.axiom-graphd` LaunchAgent, applied and rolled back the engine/skills
pointers, and removed the owned service and runtime while retaining a user file.
It recorded every command with exit code 0; after uninstall, `launchctl` reported
the canonical label absent. See
`axiom-graphd/evidence/local-lifecycle-20260922/combined-native-lifecycle.json`.

The verified local interface uses approval-bound engine plans:

```text
axiom install plan --bundle <verified-local-bundle> --out <engine-plan.json>
axiom install apply --plan <engine-plan.json> --approve-digest <engine-plan-digest>
```

The reviewed engine plan declares executable core rows with `read` and `execute`
permissions. The installer enforces that declared mode after activation. The same
engine owns per-user launchd registration/removal and ownership-scoped uninstall;
the distribution wrapper supplies verified bytes and invokes its documented argv
forms.

This is development lifecycle evidence, not a release claim. The fixture uses
prepared CPython 3.13 dependencies and the same runnable development graphd bytes
in two version directories to exercise transaction semantics. It does not prove a
clean-machine entrypoint install, a dedicated versioned MCP environment, placement
of `axiom-cli` itself on the user's shell PATH, a signed/notarized artifact, or a
published immutable channel. Those remain the distribution gaps before J-005 can
be completed or certified. Gatekeeper/quarantine actions, if needed for a future
unsigned artifact, remain explicit operator actions and are never performed
silently.
