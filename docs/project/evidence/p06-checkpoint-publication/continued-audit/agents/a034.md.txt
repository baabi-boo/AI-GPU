# Agent 034 — Python launcher audit

Scope: read-only review of `python/vortex_ai/launch.py`, the native-startup contract in `python/README.md:48–88`, relevant binding contract/helpers, and existing launcher checks. Repository HEAD: `a693d6f8828e4e10b5374db7fef8c727aa69d34e`. Existing unrelated documentation edits were present and left untouched.

## Finding: PID-directed termination leaves the launched script running (P2)

**Location:** `python/vortex_ai/launch.py:59–60`.

The launcher creates a child with `subprocess.run`, then waits without a SIGTERM handler or other child-ownership cleanup. Sending SIGTERM to the launcher PID terminates only the launcher; its Python child continues and can perform further work after the launcher has already reported termination to its caller. This affects ordinary PID-based termination by a caller/supervisor and can leave simulator work running after that caller believes its launch has ended. Sending a signal to the entire process group is a different operation and does not demonstrate this failure.

A tiny host-only probe imported the actual launch module, replaced only `verified_environment` with an environment-copy stub, and launched an ordinary Python script through the real `main`/`subprocess.run` path. The child printed `READY` and waited for a gate file. The probe sent SIGTERM to the launcher, waited for its exit, and only then created the gate file. Observations:

```text
launcher_returncode: -15
child_output: CHILD_COMPLETED_AFTER_LAUNCHER_EXIT
launcher_stderr:
```

The child included a three-second alarm and completed normally; no native library, GPU workload, download, or build was used. This proves a process-lifetime defect, not a native cleanup failure. The README does not expressly promise signal forwarding, so this should be evaluated as launcher ownership behavior rather than a violated documented cancellation guarantee.

Recommended bounded correction: make ownership under SIGTERM explicit, forward termination to the owned child and reap it before exiting. An exec-based launch is another option only if replacing the launcher process is acceptable to the existing launcher contract. Preserve current child exit-code behavior and avoid claiming bounded native cleanup from this host-only observation.

## Other reviewed behavior

No concrete additional defects found within the supported script-launch contract. The implementation checks disallowed parent loader variables before native import; verifies the immutable bundle pin/files; sets the canonical library directory and SimX driver; removes the listed Python/build overrides; invokes the same interpreter with `-I -B`; passes script arguments as an argument vector; rejects missing/nonregular scripts; maps startup failures to status 2; preserves ordinary child statuses; and maps child signal exits to shell-style `128 + signal` status.

No source changes or broad tests were made. Existing launcher tests were inspected, not executed. This audit does not qualify native execution, arbitrary-host compatibility, or hostile concurrent filesystem mutation.
