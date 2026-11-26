# Agent 041 — Python launcher SIGTERM ownership correction

## Scope

Implemented at checkout HEAD `a693d6f8828e4e10b5374db7fef8c727aa69d34e`, with
uncommitted changes limited to `python/vortex_ai/launch.py` and adaptations to
the existing `ci/project/test_p05_launcher.py`. Other agents/root own unrelated
edits and the new real-process regression module. No commit or push was made.

The implementation follows Agent 037's design and Agent 034's real host-only
orphan-child reproduction. It preserves supervised subprocess execution and
the tested `main(argv)` status contract.

## Implemented behavior

- The private `_run_child(command, *, env)` runner creates the same interpreter
  command only after all existing script, immutable-pin, bundle and environment
  checks succeed. It returns the raw child status; `main` retains ordinary
  status propagation and negative-signal normalization (`-15` becomes `143`).
- A temporary SIGTERM handler is installed before `Popen`. It records a pending
  boolean and never invokes a Popen method, exits, waits or raises. This covers
  the interval between actual child creation and assignment of its Python owner.
- The ordinary control flow forwards a pending SIGTERM through the owned
  `Popen.send_signal` and waits/reaps the direct child. `wait(timeout=0.1)` is a
  notification polling interval, not a child-runtime timeout. Calling Popen
  methods outside the signal handler avoids reentrant wait/reap state changes.
- The prior SIGTERM disposition is restored in `finally` after normal completion,
  startup failure or exceptional cleanup. A non-main-thread call fails before
  spawning, with a clear `RuntimeError` that `main` reports as launcher status 2.
- An exceptional runner path attempts child kill and wait before propagating its
  primary error. Secondary kill/wait errors do not replace that error. There is
  no retry of child work.

The temporary handler owns SIGTERM during this runner's child lifetime; the
previous custom handler/ignore disposition is restored afterward, not invoked
in parallel. The supported documented module CLI runs on the main thread.

## Test adaptations

The existing prelaunch-validation tests now mock the small private runner seam,
while retaining all original bundle-validation, verification-order, environment,
argument-vector and child-status assertions. The startup-failure check patches
actual `Popen` creation, exercising runner cleanup and the existing diagnostic.

The real environment/flags test now executes the actual runner and Popen path,
capturing child output in owned temporary files. Its inert child sets a
five-second alarm and returns status 37. It continues to check isolated/no-bytecode
flags, exact arguments, scrubbed environment and absence of native extension
import. No test IDs were added or removed in this existing module.

## Verification

An initial development run passed all 25 existing launcher tests in 0.299 seconds.
After a one-line explanatory docstring was added, a final bounded run captured
the exact final source identities before and after execution:

```text
python3 -B -m unittest ci.project.test_p05_launcher -v
Ran 25 tests in 0.289s
OK
```

The final invocation took 0.429479 seconds wall time, returned 0, and both owned
source files remained byte-identical during execution. No failures, errors or
skips were reported. `git diff --check` passed for both owned paths.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `python/vortex_ai/launch.py` | 4,349 | `01bdadc8469b50fc2b6e511684d37f1bc92d2f4030d3a0900481b8fb5173a128` |
| `ci/project/test_p05_launcher.py` | 19,343 | `55d6d31580ceca32c6ca91e94191bcd9c55c6eac8e57b09f00da2c593f1da5ea` |

Raw execution output and invocation/source metadata are retained as
`a041-launcher-tests.log` and `a041-launcher-tests.json` beside this report.
These runs overlap; their counts must not be summed. Agent 042 independently
owns real process termination, pending-startup-signal and restoration regressions.

## Boundaries and handoff

This is direct-child SIGTERM ownership, not descendant supervision. A child that
ignores SIGTERM remains owned and waited for; no arbitrary escalation deadline
was added. SIGKILL, repeated unrelated interruptions and persistent OS cleanup
failure cannot promise successful cleanup. Host process checks do not qualify
GPU cancellation, native cleanup, hardware correctness or performance.

Root should document the main-thread/direct-child scope and obtain independent
review plus exact-revision CI. No frozen proofs, measurement sources, numerical
goldens, resource/performance thresholds, workflows or native implementations
were changed by this agent.
