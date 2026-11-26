# Agent 037 — launcher termination correction design

## Scope and conclusion

Read-only review at `a693d6f8828e4e10b5374db7fef8c727aa69d34e` of
`python/vortex_ai/launch.py`, `python/vortex_ai/__init__.py`,
`python/README.md`, `docs/designs/python_binding_v1.md`,
`ci/project/test_p05_launcher.py`, the qualification call sites, and Agent 034's
host-only reproduction. No repository edits, test execution, native execution,
builds, commits, or pushes were performed.

The PID-directed SIGTERM observation is credible and follows directly from
the current `subprocess.run` ownership: the default SIGTERM disposition kills
the launcher before its Python cleanup can execute. A child receives no signal
when only its parent's PID is signalled.

**Recommended correction: keep a supervised subprocess and explicitly forward
SIGTERM to that owned direct child, then reap it before returning.** Install the
temporary handler before `Popen`, let the handler only record a pending signal,
forward it between short bounded `wait(timeout=...)` calls in ordinary control
flow, and restore the previous handler after reaping. Preserve
the existing integer result and child-signal normalization. Do not claim a
descendant-process supervisor or guaranteed native cleanup.

## Existing supported behavior

- The documented entry point is `python -I -B -m vortex_ai.launch --bundle ...
  -- SCRIPT [ARGS...]`. `main` is not an exported top-level package API, but
  it is directly exercised by the maintained launcher tests.
- `launch.py:44–64` parses only script launches, resolves the script, verifies
  the compiled pin and bundle, scrubs the child environment, invokes the same
  interpreter with `-I -B`, and returns the child's status.
- `test_p05_launcher.py::test_child_status_is_preserved_and_signal_status_uses_shell_convention`
  explicitly requires normal statuses to pass through and `-15 → 143`,
  `-9 → 137`. This is an existing tested behavior even though the README does
  not spell out the mapping.
- Other launcher tests require verification before startup, exact argument
  vector forwarding, error status 2, unchanged parent environment, and the
  isolated child flags/environment. Those expectations should remain.
- Actual P05 execution/replay consumers launch this module as a command. They
  do not import `main` or rely on a child PID. They inspect command success and
  retained output. No call site requires process replacement.

## Why not replace the launcher with exec in this change

`os.execve(sys.executable, argv, environment)` would be the smallest process
ownership implementation: the verified script would retain the launcher's PID,
so PID-directed termination naturally reaches it, and there is no supervisor
child to orphan. The checked environment would still take effect before the
new interpreter loads native libraries.

However, successful `main(argv)` would stop returning. A direct `subprocess`
caller would observe the target's negative signal return code instead of the
launcher's current positive `128 + signal` exit status. Shell display alone
does not establish equivalence: both can appear as status 143 to a shell while
their wait status differs. An exec change therefore needs a deliberate contract
change and replacement of existing status tests. Splitting CLI execution into
exec while retaining a separate subprocess path in `main` would leave two
termination semantics to maintain and retain the original defect for direct
callers. Neither is necessary for this bounded correction.

## Proposed ownership sequence

1. Keep parsing, script checks, and `verified_environment` unchanged.
2. Enter a small private child runner. Save the previous SIGTERM handler and
   install a temporary handler **before** starting `Popen`.
3. The handler only records a pending termination flag. It must not call
   `Popen` methods, raise `SystemExit`/`KeyboardInterrupt`, or exit the launcher.
4. Start `Popen` with the existing argument vector and environment, without
   changing session/process-group membership. Immediately after assignment,
   enter the ordinary wait loop. At the start of each iteration, forward any
   pending SIGTERM through the owned process object. This covers termination
   between actual process creation and receipt of its `Popen` object.
5. Use a short `wait(timeout=...)` polling interval, treating `TimeoutExpired`
   as an opportunity to check the pending flag again. This interval is not a
   timeout for the child and does not trigger escalation. If waiting otherwise
   raises, retain the normal subprocess cleanup
   obligation: terminate/kill the still-owned child as appropriate, reap it,
   and propagate the original exception. Do not add child-work retries.
6. Restore the previous SIGTERM disposition in `finally`, after the child has
   been reaped or startup has failed. Preserve the original error if a secondary
   cleanup operation fails.
7. Keep `main`'s current status-2 diagnostics and `returncode >= 0 ? returncode :
   128 - returncode` normalization.

This is a design sequence, not a proven implementation. Review the concrete
handler against reentrancy and late-signal races before merging. Python-level
signal delivery may coalesce repeated signals; do not promise exact forwarding
counts. A late SIGTERM after the child has already exited must not be sent via
an unchecked stale PID. In ordinary single-threaded control flow, use the owned
`Popen` object's `send_signal`/`poll`, without a separate raw-PID scheme.

The handler-only-records rule matters. Local CPython 3.12 source inspection
shows that `Popen._wait` holds `_waitpid_lock` across `waitpid` and the later
`returncode` publication. A Python signal handler can interrupt that interval.
Calling `send_signal` from the handler would invoke `poll`, which may fail to
acquire that lock, see an unpublished return code, and proceed to a PID signal
after the child has already been reaped. Keeping all `Popen` calls out of the
handler avoids that reentrancy window. No actual recycled-PID signal was
attempted; this is a concrete control-flow risk established from the installed
standard-library implementation.

## Necessary scope decisions

- The supported module CLI runs on the Python main thread. Installing a Python
  signal handler from another thread fails. Because `main` is not an exported
  library API, this need not become a new threaded-launch facility, but the
  implementation must not silently omit forwarding in a worker thread. If it
  rejects such use, make that limitation explicit and keep the failure clean.
- If the script deliberately ignores SIGTERM, forwarding alone cannot force it
  to exit. The launcher should continue to own/wait for it. Adding an arbitrary
  grace period and SIGKILL escalation would create a separate timeout contract;
  no such value is established by the current docs.
- SIGKILL cannot be handled. Arbitrary grandchildren are outside this direct
  child ownership scope. Starting a new session/process group changes terminal
  SIGINT behavior and should not be added merely to address PID-directed
  SIGTERM.
- This does not establish native operation cleanup, GPU cancellation, or new
  platform portability. Host subprocess observations must remain labelled as
  such.

## Minimal meaningful regression checks

1. A real inert Python child announces readiness. Send SIGTERM **only to the
   launcher PID**, require child termination/reaping before launcher exit, and
   verify the normal child-signal mapping (143 for SIGTERM). The old launcher
   should demonstrate the surviving child in a bounded negative control.
2. Deliberately deliver SIGTERM after real child creation but before the wrapper
   returns its `Popen` object; verify the pending-signal path forwards and reaps
   that child. This covers the otherwise easy-to-miss startup ownership gap.
3. Confirm the original SIGTERM handler is restored after ordinary exit,
   forwarded termination, and startup failure. Test harness cleanup must not
   leave a live process or changed handler after a failing assertion.
   A targeted wait-status publication boundary should confirm that the signal
   handler records pending termination without reentering `Popen` methods.
4. Preserve the existing argument/environment, startup-failure, normal-exit,
   and child-signal status tests. Mock a private runner for pure prelaunch
   validation tests if needed; retain real subprocess tests for process
   lifecycle behavior.

No broad native experiment or full-suite rerun is warranted solely to evaluate
this design. The concrete implementation still needs its focused tests,
independent review, and the repository's exact-revision CI requirements.
