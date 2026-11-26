# Agent 044 — independent launcher implementation review

## Scope and disposition

Reviewed every changed hunk of `python/vortex_ai/launch.py` and
`ci/project/test_p05_launcher.py` against committed HEAD
`a693d6f8828e4e10b5374db7fef8c727aa69d34e`. Agent 041 authored these changes;
this agent made no production or test edits. Read Agent 034's original
PID-directed SIGTERM reproduction, Agent 037's design, Agent 041's implementation
report, the launcher contract, root project instructions, and the installed
CPython 3.12 `Popen.send_signal`, `_internal_poll`, and `_wait` implementations.

**No concrete supported-contract production blocker found.** The implementation
addresses the reproduced direct-child orphan behavior while preserving the
existing launcher validation, argument/environment handling, and return-status
contract. One boundedness observation about an existing test adaptation is
recorded below; it is not evidence of a production failure.

| Inspected file | Bytes | SHA-256 |
| --- | ---: | --- |
| `python/vortex_ai/launch.py` | 4,349 | `01bdadc8469b50fc2b6e511684d37f1bc92d2f4030d3a0900481b8fb5173a128` |
| `ci/project/test_p05_launcher.py` | 19,343 | `55d6d31580ceca32c6ca91e94191bcd9c55c6eac8e57b09f00da2c593f1da5ea` |

These hashes matched at the beginning and end of this review. Other agents/root
were editing unrelated paths. No test execution, build, native execution,
commit, push, or repository mutation was performed by this reviewer.

## Production hunk review

### Imports and startup boundary

The two new imports are standard-library `signal` and `threading`; importing
this module still does not load the native extension or any simulator runtime.
`verified_environment` is unchanged. `main` still resolves and checks the script,
validates the immutable installed pin and all bundle files, and prepares the
same scrubbed environment before entering the child runner. The interpreter
argument vector remains `[sys.executable, '-I', '-B', script, *arguments]`, with
no shell, new process group, or new interpreter mode.

### Pending SIGTERM and ownership

The main-thread check precedes signal installation and child creation. It makes
unsupported worker-thread calls fail cleanly through the existing status-2
`RuntimeError` diagnostic path. The documented module CLI is a main-thread path.

The temporary SIGTERM handler is installed before `Popen`, and its body only
sets a local pending flag. It performs no subprocess operation, raw-PID signal,
wait, exit, or exception. A signal during real child creation or before the
returned `Popen` owner is assigned therefore remains pending for the first loop
iteration; it does not terminate the launcher in that ownership gap.

Forwarding occurs in ordinary control flow through the owned process object.
The installed CPython implementation polls before signalling and avoids sending
to a child whose completion is already known. Crucially, the Python signal
handler cannot reenter that operation while `waitpid` has reaped the child but
has not yet published `returncode`: it only records pending state. The launcher
adds no second thread or external child reaper that would invalidate this
single-owner reasoning.

The `wait(timeout=0.1)` interval bounds when pending notification is reconsidered;
it does not bound child execution or escalate the signal. `TimeoutExpired` alone
continues the loop. Successful wait returns the child's raw result after reaping.
A pending signal arriving after successful wait need not be forwarded to an
already-completed child. Boolean coalescing is appropriate for this cancellation
request; there is no exact signal-count guarantee.

### Cleanup, handler restoration and exit status

If spawn fails, `child` is still absent, so cleanup does not attempt to adopt or
signal an unknown process. If forwarding or waiting raises after assignment,
cleanup attempts both owned-child kill and wait, then re-raises the original
exception. Secondary kill/wait exceptions are suppressed rather than replacing
the initiating failure. This is best-effort error cleanup; it cannot promise
reaping under persistent OS failure or repeated unrelated interruption.

The prior SIGTERM disposition is restored in `finally` on successful completion,
startup error, and the exceptional cleanup path. The runner temporarily owns
SIGTERM instead of invoking a previous custom handler concurrently; the previous
handler or ignore disposition is reinstated afterward. Restoring this same valid
signal on the main thread presents no ordinary supported-path failure. Arbitrary
fault injection into handler restoration would need its own explicit failure
contract, not an unqualified universal cleanup claim.

`main` still maps nonnegative child statuses directly and negative statuses to
`128 - returncode`, preserving the tested `-15 -> 143` and `-9 -> 137` behavior.
The existing classes of bundle/import/OS/runtime startup failure still produce
the prefixed status-2 diagnostic. No child work is retried.

## Existing test hunk review

Pure prelaunch tests now mock the private runner seam and retain their original
verification-order, forbidden-environment, immutable-pin, file-validation,
argument-vector and status assertions. Removing the former `check=False`
assertion follows the new runner interface; ordinary nonzero status propagation
continues to be asserted independently.

The startup-failure test now patches actual `Popen`, so it exercises the real
runner's startup failure/restoration path instead of skipping it. The real
flags/environment test likewise enters the actual runner and actual `Popen`,
uses owned temporary files for output capture, and still asserts status 37,
exact arguments, `-I -B` flags, scrubbed environment, and no native import.
The new test module owned by Agent 042 was not part of this assigned hunk review.
Agent 041's reported 25-test pass was read, not independently rerun or added to
any aggregate count by this reviewer.

### Nonblocking test-bound observation

The real environment test formerly bounded its child with the parent-side
`subprocess.run(timeout=5)`. It now sets a five-second alarm inside the child.
That bounds a stuck child after its Python startup reaches the alarm, but does
not bound a hypothetical regression that loops forever in the parent after the
child exits. The new lifecycle regressions should use an outer supervisory
process/timeout to make such failures finite. Root was informed of this limit.
It is not an observed failure of the current implementation and does not justify
adding a production execution timeout.

## Required claim limits

The supported correction is PID-directed SIGTERM forwarding to the direct owned
child. A script that deliberately ignores SIGTERM remains owned and waited for;
there is no new deadline or SIGKILL escalation. Uncatchable SIGKILL and arbitrary
grandchildren remain outside this supervision contract. Host process tests do
not establish native operation cleanup, GPU cancellation, hardware correctness,
performance, or portability beyond the documented platform. Root should retain
these limits and the main-thread CLI scope in the launcher documentation.
