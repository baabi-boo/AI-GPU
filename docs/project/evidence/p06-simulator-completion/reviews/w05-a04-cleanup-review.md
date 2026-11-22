# Wave 5 / agent 4 — independent full-platform cleanup review

Base revision: `42809ff0c1b81384d7c9b079e4ef786be8407600`
Checkout: `/workspace/scratch/ea983fdea786/AI-GPU`
Reviewer: `/root/w05_a04_cleanup_review`
Disposition: **No concrete code blocker in the two cleanup hunks. Proceed to the required native CI; final native qualification remains open.**

This is an independent review of uncommitted source, bound to the exact file and diff hashes below. The reviewer did not author either production hunk or the repository regression tests. No repository source was edited, no native GPU/RTL build or download was attempted, and no commit or publication was performed. Reviewer-created probes and this report live outside the repository.

## Scope and rules

Applied the repository's `code-review` and `simx-review` skills, `AGENTS.md`, C++/Verilog coding rules, bug-fix discipline, review policy, SimObject design, simulator architecture and completion contract. Reviewed every changed line in `sim/common/simobject.h` and `sim/common/simobject_functional.h`, with their lifetime, scheduling and worker-shutdown consumers. Also reviewed the actual-header cleanup fixture and harness, the updated completion-contract boundary language, and the small AGENTS link addition.

The repository's path classifier maps each isolated framework file to R2 (`simx-model`). This review applies **R3 depth** because the overall completion change establishes externally visible failure/destruction behavior and a recovery boundary. This report does not classify or approve every other uncommitted file in the shared tree.

## Production conclusion

The timed header adds only two explanatory comment lines and `SimChannelBase::inflight_count().store(0, std::memory_order_relaxed)` at cleanup line 1374. The functional header adds the same three lines at cleanup line 1361. Neither hunk changes normal send/pop accounting, queue behavior, event scheduling, reset, launch reset, pipeline execution or cycle advancement.

The repair matches the demonstrated ownership defect. A terminal `reserve()` increments both pending endpoint occupancy and the process-global count. Delivery converts pending occupancy into queued storage without removing the global count. Only normal `SimChannel::queue_pop()` decrements that count. A fault before pop, or a discarded undelivered event, therefore leaves abandoned accounting. Neither a default channel-event destructor nor channel storage destruction invokes `queue_pop()`. Clearing the retired context's count at whole-platform destruction resolves that lifecycle leak without changing accounting while the context is live.

### Shutdown and destruction order

The store occurs after all of the following in both headers:

1. `stop_workers()` releases parked framework workers into their exit check and joins every thread.
2. Active reset registrations and the platform's shared ownership of simulation objects are released.
3. Every registered wheel event and immediate event is erased and deleted.
4. Execution domains and cross-domain inboxes are destroyed.
5. `cross_pending_` is cleared.

Consequently no old scheduled event or inbox callback remains available to reserve or consume packets after the store. The supported asynchronous runtime separately joins its outer processor task in `vx_device::~vx_device()` before processor destruction invokes `ProcessorImpl::~ProcessorImpl()` and `SimPlatform::finalize()`. The store is a disposal boundary, not successful completion of the failed launch. The live-fault tests preserve nonzero accounting and `idle()==false` until finalization.

Object ownership is released before event deletion, as on the base revision. Events hold raw channel pointers, but their destructors do not call `fire()` or dereference those targets. Discarding them therefore does not require a still-live bound channel. No new destruction-order dependency was introduced by the hunk.

### Retained owners and double decrement

`ProcessorImpl` finalizes in its destructor body, before its shared-pointer members are destroyed. Some channels can therefore outlive the global cleanup call. `SimChannelBase::~SimChannelBase()` only unregisters a raw topology pointer. Timed `RingQueue` destruction destroys stored packet values through its own storage pop; functional `std::deque` destruction destroys values. Neither path invokes the channel's global accounting decrement or pop callback. The module destructors inspected were empty or deleted their implementation/member ownership; no teardown path was found that consumes old channel entries after finalization.

This makes the existing late-owner behavior compatible with a context-wide store: destruction cannot subtract old occupancy from a new context's count. Both the repository fixture and the independent probe specifically release retained old owners while a new reservation has count one, then require that count to remain one and the fresh context to remain non-idle until it actually consumes its packet.

The scope is essential. Old owners are destruction-only after finalization. Calling an old channel's `pop()` after the store could underflow or subtract another context's count, and sending through a finalized topology could use removed peers/domains. Neither the implementation nor the reviewed contract authorizes those operations. The supported runtime still destroys the previous device/context before creating the next; the late-owner test is an accounting stress case, not simultaneous-context support.

### Relaxed atomic and normal behavior

The added store does not publish other state to concurrent live workers. The caller has joined the outer task, cleanup has joined healthy parked internal workers, and supported host operations are serial. Those lifetime boundaries provide the synchronization; `memory_order_relaxed` is adequate for the remaining atomic count assignment. Moving the store before worker shutdown, event/inbox disposal, or into normal reset would require a different proof. This patch does none of those things.

`reset()` retains its existing quiescence precondition, including the comment that dropping events does not unwind reservations. `reset_launch()` still preserves designated memory-side work. Neither is made into a failure-recovery mechanism. Normal reserve/pop, registered-ready behavior, bounded capacity, functional latency collapse and per-cycle execution are byte-for-byte unchanged in this diff. No model-parity, performance or physical-timing result is claimed.

No assertion was removed, weakened or added to conceal an accounting failure. The new regression expectations remain active independently of `NDEBUG`. The independent review probe passed both with debug framework assertions plus UBSan and with `-DNDEBUG`.

## Evidence reviewed and executed

### Actual-framework regression evidence

Reviewed `ci/project/fixtures/simulator_platform_cleanup.cpp` and `ci/project/test_p06_simulator_platform.py` in full, then reconciled the retained evidence in `/workspace/scratch/ea983fdea786/w05-a02`:

| Evidence | Observed outcome | Meaning |
|---|---|---|
| Current repository unittest harness | 4 tests passed in 7.010 seconds; 8 timing/functional × group cells | Both production headers compile and execute the named cases |
| Frozen candidate snapshot | Both compiles and all 8 group executions passed | Retained source and logs reproduce the current behavior |
| Pinned base `42809ff0...` headers with the same fixture | Both compiles passed; 6 fault/abandonment executions exited 1 | The old code fails semantic recovery assertions after fresh work is consumed |
| Pinned base normal controls | 2 executions passed | The normal control does not reject the parent indiscriminately |

The four groups are queued model exception, scheduled undelivered reservation, late owner and normal completion. The faulting tick executes in `std::async(std::launch::async)` and its future is joined before host finalization. A fresh asynchronous worker then executes the new context. There is no substitute framework header and no test-side reset of the global count. Fixed tick bounds let the parent reach the explicit `fresh context consumed its packet but remained non-idle` failure instead of relying on timeout.

The reviewer verified every one of the 22 retained command log hashes, successful expectation checks, both pinned parent header bytes against `git show`, both candidate headers against the working tree, and both current fixture/harness hashes against the retained candidate snapshot. The six parent failures are retained as failures; they are evidence of sensitivity, not passing production executions. This evidence was inspected rather than redundantly rerun by this reviewer.

### Independent pending-work and healthy worker-shutdown probe

Executed `/workspace/scratch/ea983fdea786/w05-a04-cleanup-probe/run_probe.py`. It snapshots the actual framework headers and local dependencies, builds the owned `lifecycle_probe.cpp`, checks source stability afterward and retains argument vectors, timeouts, environments, exits and log hashes in `commands.json`.

All four timed/functional × debug-UBSan/release cells compiled and passed using `/usr/bin/g++` 14.2.0. Debug cells used `-O1 -g0 -fsanitize=undefined -fno-sanitize-recover=undefined`; release cells used `-O2 -DNDEBUG`; all used C++17, `-Wall -Wextra -Werror -pthread`. Each compile had a 45-second timeout and each run a 15-second timeout. No timeout or sanitizer finding occurred.

The probe creates two execution domains, requests two executor threads, ticks once through an asynchronous coordinator and verifies that the two domains executed on distinct thread IDs. This establishes a healthy persistent internal worker, rather than merely requesting a worker count that might have been capped to one. It then schedules, while workers are parked:

- A cross-domain event-link payload, with global packet count zero but `idle()==false`.
- An immediate channel event.
- A registered channel event.
- A generic registered callback payload.

The packet count is two before finalization. Finalization completes and leaves count zero and `idle()==true`. All four weak payload witnesses expire, and no abandoned callback or message handler runs. Two external owners remain alive through finalization, are later destroyed while fresh packet accounting is one, and cannot change that accounting. Fresh work is consumed once and becomes idle; repeated clean finalization remains harmless. Each run emits:

```text
PASS lifecycle internal_workers=2 discarded_payloads=4 late_owners=2 fresh_consumed=1 fresh_idle=1
```

Here the reported worker count denotes two executor threads: the asynchronous coordinator plus one persistent internal worker. This is **healthy worker shutdown** coverage. No exception was thrown inside an internal multiworker executor.

### Static and policy checks

The scoped `git diff --check` passed. Each framework header's path classification is R2. Direct inspection confirms that the only new count stores are the two full-cleanup sites; reserve and pop remain the ordinary increment/decrement sites. Reviewed the revised completion-contract wording for teardown, destructor-only retained owners, reset exclusions, same-thread TLS limitations and multiworker exception exclusions; it matches the source and preserves the native evidence requirements. The AGENTS addition is only a link to that contract.

## Residual limits and required native qualification

**No F2/F3 code finding was established in the reviewed cleanup hunks.** The following boundaries remain open and must not be represented as covered:

- **Same-thread direct exception state:** `tick()` restores `tl_exec_domain_` and `tl_exec_object_` only on its ordinary return. A direct exception can retain the fault-site execution domain/cycle in that caller's TLS after cleanup, so a subsequent same-thread host send into another domain could be treated as a cross-domain send or use stale cycle state. This is present on the base and unchanged by the cleanup hunk. The asynchronous fault task's TLS ends with that joined task; the framework regression deliberately uses that contract. No same-thread multi-domain recovery claim is made, and no extra production patch is requested in this review.
- **Internal multiworker exceptions:** the worker lambda has no exception transport to the outer future, and an exception before a coordinator reaches its barrier is not repaired by a later count store. Worker termination, broken barrier progress, cancellation and hung-worker recovery remain outside the declared contract. The independent healthy-worker probe does not qualify them.
- **Destruction-only old owners:** no send/pop/tick on finalized objects, concurrent finalization, simultaneous contexts or reactivation of a failed backend is supported. Sticky `AsyncRun` failure is not cleared by the platform store.
- **Native execution:** the actual native `Processor`/bounded-RAM unit and the generated public-runtime success regression were **not compiled, linked or run** in this review. The observed workspace free space was about 2.4 GB, below the unchanged 15 GiB native prerequisite. No reserve was reduced and no native runner was invoked.

Before final native qualification, hosted CI must run the unchanged required timing SimX RV64 `p02-tfr`, `PERF=1` sequence: normal x3 values 7 and -1, unchanged legacy success/caught-exception behavior, real `OutOfRange` reaching asynchronous `get()`, full failed-context destruction and a subsequent fresh normal context. The generated public-runtime regression must also demonstrate its six serial successful launches across two contexts, exact outputs, waits and cleanup. Retain and independently reconcile the exact executing source/configuration/compiler/build identities and original results. A timeout, a header-only probe, deletion of the final fresh context, or manual test count clearing cannot satisfy those obligations.

This report establishes neither native functional SimX qualification nor public native fault recovery, model parity, accelerator performance, counter qualification, warm-workspace acceptance, RTL correctness or physical-device recovery.

## Verdict

**Class: R3 review depth for the completion contract; R2 path classification for each isolated cleanup file. Verdict: land after the required native CI evidence and the existing R3 approval process. No cleanup-source fixes are requested.** The reviewed patch is suitable to proceed into the bounded native verification workflow now. Host evidence closes the specific stale-count implementation blocker for the declared asynchronous framework scope; it does not close final native qualification. Concurrent changes after the identities below require their own reconciliation.

## Exact identities

The following identity table and the corresponding machine-readable manifest are generated from the reviewed files. The reviewed production diff is retained as `/workspace/scratch/ea983fdea786/w05-a04-cleanup-probe/cleanup.patch`; `review-inputs.json` also records the full observed Git status and source sizes.

Recorded: 2026-11-22T09:03:49.727712+00:00

| Reviewed repository input | SHA-256 |
|---|---|
| `sim/common/simobject.h` | `0e0369f5ea1ba85f5e461e03b85e9723bb47f0e118499ba2b21a7923594f7004` |
| `sim/common/simobject_functional.h` | `0a62df63e18f340096bda900ccb858e00a3c2d54d7688c92737c5cca06210984` |
| `ci/project/fixtures/simulator_platform_cleanup.cpp` | `efa3bb3d439297174b72f61ce096df3ebd9ce5094c288f95c3114f5fae4d43c9` |
| `ci/project/test_p06_simulator_platform.py` | `58ec716495b199369254ef80d37f746ae3d631b5f24d5b5ec1250e4043f80bba` |
| `docs/designs/simulator_completion_v1.md` | `d407a6d57be4806800ba37a60dacbd54c4e160286c5a65b08413a5e08b22b87b` |
| `AGENTS.md` | `fdd82f39a11d5b9bc96fe2c15f5779e2c08d359e89dc666595adbf30a01d1e0b` |
| `sw/runtime/common/async_run.h` | `17e229eb116c6d50d273780bb969630d0e0141a8aec39f22c0ab0fb62b74d2ed` |
| `sw/runtime/simx/vortex.cpp` | `61a14d8c29f9c2e9bef292d4ef8bbc5892ff6b13ad62110a80915f788917edd4` |
| `sim/simx/processor.cpp` | `569cf629d1e25ec9a295b20bfadfabbe21cd0989127f2b825fceee99a8062b78` |
| `sim/simx/processor.h` | `588db10c3997e91dd471771cd12bb0329dacbc3902248b84353beebd19bc0438` |
| `sim/simx/processor_impl.h` | `f9e596353f5f034f7d795fec62cc424c76ddebdbea2bbb860997e2b292243ca7` |
| `tests/unittest/simx_completion/main.cpp` | `343f68f1cf90ea5e81ae9d97d8428df9e5db246fb35ac29af163c5b099b1727e` |
| `tests/regression/simx_completion/main.cpp` | `07687cbb532f3f6901d928da5de181fa76d8c0efc8796bfd578d0c485008b468` |
| `docs/review/code-review-policy.md` | `99426ced05c04c1b14422f4fdacabcce3c680600461c4887b14e5eabf8b0587d` |
| `docs/designs/simobject.md` | `512d07816ef14ba4b06366ea1cd422ef8361f27dd364fd6dcba51ab2c6d2a5c4` |

| Reviewer artifact (under `w05-a04-cleanup-probe`) | SHA-256 |
|---|---|
| `cleanup.patch` | `31c51065c0279b8e8712502bcc608cdf4d764b552fd5437df7f2f0096c4fb3e3` |
| `lifecycle_probe.cpp` | `eaac865f32031c744ecf1eda34052fc325b8cc37b6a19615c770bd2c48d51b8c` |
| `run_probe.py` | `99f3c59260709ea5aed3ee7146394d38128ff4065e676c1c599707d874ac2124` |
| `commands.json` | `718b5e163da34e642df3656f000e4e97d9218f95c6233bb023bad3fe84045a0a` |
| `summary.json` | `53da2f48d8363b701426cd93d5c174cb2f7e8f503eab016ae50c2a1441c77a9d` |
| `review-inputs.json` | `16cc55ef86cb5f759b25da137cb7d98fe1da37b78b734528cca67faa9654a642` |

| Reviewed regression evidence (under `w05-a02`) | SHA-256 |
|---|---|
| `summary.json` | `7303ab55c3c96d4f059c5093ddcc5577c8867c53ce6fbe1fb1ce94d21963ce64` |
| `commands.json` | `c6a0dc05624ef4f6fc0b4d03e8e129cf8e7a70c0257df873621a58ead6a9b3d9` |
| `unittest-current.log` | `8aee05890a6ab21971e4d2a99e6720c6f225839038f668be9966d2ab9a2aeec7` |
| `source-hashes-before.json` | `c05f5fe82359e136e7d71d144603f12bc3f21c6df918baf6cf629a07dbf230de` |
| `source-hashes-after.json` | `c05f5fe82359e136e7d71d144603f12bc3f21c6df918baf6cf629a07dbf230de` |
| `parent-source-hashes.json` | `b40d4c16314f13402c9d42a902063b1a1558a90af786def3a95098cb68f904a7` |
