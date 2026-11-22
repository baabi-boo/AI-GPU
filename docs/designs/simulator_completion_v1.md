# Simulator completion contract v1

## Scope and execution routes

This contract defines host completion for the [SimX backend](../../sw/runtime/simx/vortex.cpp)
and [processor RTL simulation backend](../../sw/runtime/rtlsim/vortex.cpp).
Both use the runtime-internal [AsyncRun owner](../../sw/runtime/common/async_run.h)
with the existing functional [CommandProcessor](../../sim/common/cmd_processor.cpp).
The [development audit](../project/p06-simulator-completion-audit.md) records why
this prerequisite precedes counter qualification. This document specifies
behavior and evidence obligations; it does not certify that a test ran.
The platform teardown boundary applies to both the
[timing](../../sim/common/simobject.h) and
[functional](../../sim/common/simobject_functional.h) SimObject frameworks.
Coverage of those headers is separate from native processor execution.

| Route | Normal completion | Execution failure |
|---|---|---|
| SimX runtime | `Processor::run_checked()` finishes the existing model run and ignores its legacy register-derived return | A model exception propagates into the asynchronous future |
| Processor RTL runtime | Its existing `void Processor::run()` returns normally | A C++ exception propagates into the asynchronous future |
| Legacy direct SimX caller | Existing `Processor::run()` behavior is retained | Its existing catch/log/`-1` behavior is retained |

SimX's legacy integer result reads architectural x3 (`gp`) through
[Operands::get_exit_code](../../sim/simx/operands.cpp). Kernel startup can use
that register as a legitimate global-data pointer. A nonzero value, including
the integer value `-1`, is therefore not an asynchronous execution error by
itself. The [checked entry](../../sim/simx/processor.cpp) separates exception
propagation from that legacy result without changing the model's run loop.
The legacy direct `Processor::run()` API and body, including its exception
logging and `-1` return, remain unchanged. Processor RTL's void return does not
add kernel exit-code reporting.

## Ownership and launch ordering

Host control of one completion owner is serial. The existing common runtime
serializes its CP register callbacks; the worker executes the processor task
asynchronously. `AsyncRun` adds no lock for concurrent callers, no independent
device-context scheduling, and no permission to overlap managed operations.
The [serial workspace ownership contract](serial_matmul_workspace_v1.md) and
SimX's process-wide state restrictions remain applicable.

The future, the unobserved launch edge and terminal failure are separate state.

| Observation or action | Required behavior |
|---|---|
| Start while healthy and idle | Own one asynchronous task and retain an unobserved launch edge |
| Start while a future or launch edge is still pending | Reject the overlapping launch and retain terminal failure |
| First busy observation after a successful start | Return busy once, even if normal completion was already consumed |
| Later busy observation while the task is pending | Return busy |
| Later observation after normal completion | Consume the future with `get()` before returning idle |
| Observation of an exceptional future | Consume it, retain terminal failure and propagate the exception to the guarded callback |
| Operation after terminal failure | Reject further execution; no reset of the completion owner is provided |

The command processor requires busy to rise before falling. A successful task
that finishes before its first poll must still satisfy that sequence. A
nonblocking check, a blocking wait or SimX's bounded polling wait may consume a
normal future without erasing the unobserved launch edge. A task exception must
be observed before the busy hook permits successful launch completion.

## Failure visibility and retained state

Each backend checks completion around CP register transactions. DCR and
last-level-cache memory hooks wait for and consume pending execution before
touching processor state; processor RTL's drain hook does the same. Both CP
register callbacks catch exceptions from their guarded transaction, latch
terminal failure, and return the existing nonzero HAL error. Async task creation
failure takes this path too.

The failing launch must not retire successfully or permit later work in the
same serial CP burst. Later CP reads and writes remain rejected for that backend
device's lifetime. A failed read must not publish its output as a successful
register observation. This provides no rollback of commands or memory writes
that completed before the failure.

The existing [CallbacksAdapter](../../sw/runtime/common/vortex2_internal.h)
maps a nonzero HAL result to `VX_ERR_INVALID_VALUE`.
[Device::cp_poll_seqnum_](../../sw/runtime/common/device.cpp) checks that result
before accepting the completion sequence number. The existing
[queue](../../sw/runtime/common/queue.cpp) and
[event](../../sw/runtime/common/event.cpp) error paths must carry the failure to
public waits and retain the event's error on repeated observations. This
contract adds no public error code, callback member or on-wire status.

Consuming a queue-local error with `vx_queue_finish` does not clear the backend
failure. A subsequent command using that device must still fail at the backend
boundary. Successful cleanup or a completed future does not authorize reuse of
the failed simulator state. A new device instance owns a new completion owner;
any claim that recreation succeeds must be demonstrated within the separately
declared simulator/context scope.

## Destruction and whole-platform accounting

Destruction joins outstanding execution before freeing registered host memory
or destroying the processor and RAM. The cleanup join consumes the future
without allowing an exception to escape destruction. Host-memory release remains
available after terminal failure; a successful release is a cleanup result, not
evidence that the earlier task succeeded.

An exception can abandon a queued packet or an undelivered endpoint reservation.
Destroying channel storage or discarding its scheduled event does not execute
the normal `SimChannel::queue_pop()` accounting path. Before the cleanup repair,
the process-global in-flight count could therefore survive whole-platform
teardown and keep a fresh context non-idle after it consumed all of its own work.

Both SimObject frameworks retire that abandoned accounting at full
`SimPlatform::cleanup()` only. Cleanup first stops and joins platform workers,
releases reset registrations and platform object ownership, deletes scheduled
and immediate events, discards execution domains and cross-domain inboxes, and
clears `cross_pending_`. It then stores zero in
`SimChannelBase::inflight_count()`. This boundary disposes of the finalized
context's work; it does not complete that work successfully. A failed live
context with queued or reserved work must remain non-idle before cleanup, and
its backend failure remains sticky for the device's lifetime.

External shared owners can defer channel destruction past finalization. Those
old objects are destruction-only: no send, pop, tick or other reuse is permitted.
Their later destruction must not subtract old occupancy from a fresh context's
global total. The supported runtime sequence still requires destruction of the
previous device/context before creation of the next. The host fixture's separate
late-owner case stresses destructor accounting while a fresh reservation is
live; it does not authorize simultaneous live contexts or operation of a
finalized object.

Neither `reset()` nor `reset_launch()` is a recovery entry point. Full reset's
existing quiescence requirement and launch reset's preservation of designated
memory-side in-flight work remain unchanged. Clearing abandoned accounting
does not clear an `AsyncRun` failure or authorize reuse of a failed backend.

## Exception and recovery limits

A host wait timeout does not cancel, detach or safely reclaim an executing
worker. A worker that never finishes can still block destruction. Safe forced
cancellation, recovery of a failed context, simultaneous callers, signals,
process termination and Verilator fatal aborts are outside this contract.
Only C++ exceptions reaching the future can be consumed by this mechanism.

A direct caller's tick exception can leave that thread's execution-domain and
cycle thread-local state at the fault site. Same-thread direct exception reuse
and restoration of that state are not qualified. The actual-framework fault
fixture uses one executor worker and a joined asynchronous task, so its faulting
thread ends before host teardown. Coordinated exception transport from multiple
platform workers, hung-worker recovery and fatal-abort recovery require separate
work and evidence. The unchanged legacy direct-call behavior does not establish
those recovery properties.

## Required verification

Independent review must check each production hunk and the evidence scope under
the [review policy](../review/code-review-policy.md). Retain exact source/build
identities, commands, raw outcomes and failed attempts. A built parent that fails
the intended behavioral assertion establishes sensitivity; a compile failure or
timeout does not substitute for it.

| Evidence | Required observations | Scope limit |
|---|---|---|
| [Actual backend and CP host fixture](../../ci/project/test_p06_simulator_completion.py) | Both backends; pending and serial success; standard and unknown exceptions; failure before retirement; suppressed later work; sticky reads/writes; RAM/LLC and drain synchronization; join before release | Controlled Processor/RAM faults establish host transport behavior, not native processor arithmetic or an RTL fault mechanism |
| [Actual timing/functional framework checks](../../ci/project/test_p06_simulator_platform.py), using the [platform cleanup fixture](../../ci/project/fixtures/simulator_platform_cleanup.cpp) | Compile each production header separately; queued model exception leaves live accounting nonzero; full cleanup retires queued work and scheduled undelivered reservations; fresh work is consumed exactly once and reaches idle; late owner destruction preserves new accounting; normal completion, launch-keep state and repeated clean finalization remain valid | Actual `SimObject`/`SimChannel` host checks with one executor worker and a joined asynchronous fault task; no substitute headers or manual count reset; no native `Processor`/RAM, native functional execution, multiworker exception transport or performance qualification |
| Deterministic immediate-completion fixture | Complete the task before the first busy observation; preserve busy then idle after each supported success-consumption path; reject exceptions and overlapping starts without losing failure | A helper or scripted-CP test must disclose its seam; sleeps or repeated lucky scheduling do not prove the boundary |
| Public runtime failure integration | Actual callback adapter, device polling, queue worker and event paths; repeated waits retain failure; consuming queue error does not rehabilitate the backend; cleanup stays usable | Source inspection and direct HAL tests alone do not establish the whole public error path |
| [Linked native SimX unit](../../tests/unittest/simx_completion/main.cpp) | Real `Processor`/RAM; normal x3 values `7` and `-1`; unchanged legacy success and caught-exception behavior; a real bounded-RAM `OutOfRange` exception reaches asynchronous `get()`; complete destruction of the failed context is followed by a fresh normal context | Fixed timing SimX, RV64 `p02-tfr`, `PERF=1`; directed native model evidence does not establish a native public-runtime failure or physical-device recovery |
| [Native public success regression](../../tests/regression/simx_completion/main.cpp) | Real generated kernel and runtime; global-data access with nonzero low `gp`; exact output checks; six successful serial launches across two contexts, event waits, cleanup and context recreation | Fixed timing SimX, RV64 `p02-tfr`, `PERF=1`; positive native execution does not replace fault-path evidence |

The actual-framework timing/functional checks and injected host failures do not
replace either native obligation. Native completion execution remains `not_run`
pending the hosted [completion workflow](../../.github/workflows/p06-simulator-completion.yml)
and its [native runner](../../ci/project/p06_simulator_execute.py). The required
bounded-RAM exception followed by a fresh normal context must remain in the
native unit; a host-header probe, weakened fixture or timeout cannot substitute
for that sequence. Native functional SimX and other configurations remain
unqualified by these fixed native cells.

Native tests run from fresh configured build trees with identified tools and
unchanged resource limits. The additive [completion build fragment](../../sim/simx/completion.mk)
keeps the accepted SimX Makefile intact. Changed helper bytes must cause both
backend shared libraries to rebuild. Unsupported or unexecuted configurations
remain explicitly unqualified.

## Preserved qualification boundaries

This contract changes host completion bookkeeping, failure visibility and
abandoned accounting at whole-platform teardown. It does not change the normal
processor run loop, event scheduling, pipeline, arithmetic, ISA, counter widths,
public ABI, sampling rules, statistics or performance thresholds. Host wall-time
effects are not a simulated-cycle or performance improvement claim.

The [warm v1 contract](warm_workspace_benchmark_v1.md) remains blocked with
`qualified=false` and no established absolute cumulative no-wrap bound.
The [counter qualification plan](../project/p06-mpm-qualification-plan.md) still
requires exact route/selector coverage, coherent reads and independently
reviewed lifetime bounds before a fresh performance qualification. P06-A02/A03,
vendor P01-A03, framework acceptance, inherited DSP-area failures and physical
FPGA/silicon obligations are not closed by this completion repair.
