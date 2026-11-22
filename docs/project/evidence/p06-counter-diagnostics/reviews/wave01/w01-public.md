# W01 public native counter audit

Audited master `7455e008c1e001d3329e74fd55ffcd942592ec5f`. Read-only audit; no production files edited and no native execution claimed.

## Concrete findings

1. `tests/unittest/checked_counters/main.cpp:362–397` genuinely seeds the production Core cycles counter and reaches its updater through `Processor::run_checked`, but directly owns `AsyncRun`; the JSON correctly says `public_runtime:false`. `cache_overflow():400–417` only aggregates two independent `Cache::PerfStats` values, not the real two-bank D-cache selected through CSR. `pending_underflow():420–428` is a primitive check, not the production response callback.
2. `ci/project/test_p06_checked_public.py:58–71,91–96` intentionally substitutes both Processor and RAM. It executes real common runtime, CP and backend failure containment; `fixtures/checked_counter_public.cpp` accurately reports `native_model=0`. Its typed error is produced by a local PerfCounter in a shim hook. Thus these tests cannot establish native model/public integration.
3. Native public success already has a reusable model: `tests/regression/simx_completion/main.cpp` builds actual modules, creates queues/buffers, performs launches and exact readback, then explicitly releases resources. Its runner `p06_simulator_execute.py:417–445` builds the real common runtime, backend, model, kernel and application with recorded compiler artifacts. It covers six successes, no native injected failure.
4. Production containment is structurally ready: `sw/runtime/simx/vortex.cpp:211–223` routes synchronous DCR operations through `AsyncRun::invoke` and async work through `start(run_checked)`. `AsyncRun::invoke` poisons on any model exception; `collect` retains asynchronous failure. Backend MMIO converts retained processor failure to `-1`, with unrelated CP/host exception behavior preserved.
5. `sw/runtime/common/perf.cpp:277–286` only writes the caller's 64-bit destination after both successful half reads. A failed low or high reply must preserve the sentinel. `Device::cp_submit_dcr_read():1007–1025` reads the final response outside submit/poll locking. Coherence therefore requires the declared exclusive serial submitter, not merely a completed kernel or repeated equal measurements.

## Recommended next implementation

Add a separately named native public diagnostic executable/backend and runner; retain the existing historical five-cell reader and controlled tests. Reuse actual common runtime + CP + backend + Processor + RAM. Keep all seeds and observation hooks in the diagnostic artifact; measurement binaries remain free of test controls.

A practical injection design is a test-only linker wrapper around the actual Processor constructor/destructor plus `run_checked` and `dcr_read`: capture the exact backend-owned instance, seed it only while the queue/model is quiescent, count actual entry calls/typed errors, call each real function unchanged, and rethrow captured `PerfCounterError` for the unmodified production AsyncRun boundary to consume. The GNU/Itanium symbol spelling must be derived/verified from `nm`, required by the dedicated link command, and validated in artifacts; do not silently fall back if wrapping fails. This is preferable to replacing Processor/RAM or copying runtime failure logic. A distinct test adapter subclass compiling the backend source can also work but must be clearly recorded as an instrumented diagnostic derivative, not a byte-identical backend. Never introduce a hidden environment fault switch into ordinary binaries.

Coordinate the real-cache access mechanism with the all-33 selector harness: two actual D-cache bank storage fields must be seeded `UINT64_MAX` and `1`. Seeding a returned `perf_stats()` aggregate copy does nothing. The public call must traverse real CP → Processor → Core CSR → Socket/Cache aggregation. No simulated-error-only throw can substitute for this cell.

### Required native cells

- Normal control: actual module executes, produces exact expected words, repeated waits succeed, output read and all releases succeed, new context repeats success.
- Immediate async overflow: seed actual Core cycles to UINT64_MAX after module upload, launch, and confirm the production updater throws before that field changes. Repeated event waits retain failure; `vx_queue_finish` may consume only the queue error, never revive the backend. Later DMA/query/launch—including a second queue—must fail without additional Processor entries. Destroy events/queues/module/device and prove the actual Processor destructor ran before creating a successful fresh context.
- Delayed async overflow: seed close enough below max to let actual execution advance, then overflow. Demonstrate nonzero native progress before failure, the same terminal semantics, and no successful retirement/output acceptance.
- Synchronous aggregate overflow: seed the actual two D-cache banks, query an enabled D-cache selector via `vx_device_mpm_query`, retain caller sentinel and unchanged source components, observe the real typed exception, and confirm every subsequent model call is suppressed until full destruction. Fresh context succeeds.
- Stable half-read diagnostics: capture actual DCR tags/replies and model tick/counter state for each pair; require exact class/core/selector, successful low then high, unchanged model clock through both reads, and exact 64-bit reconstruction for all 33 selectors. Test high-half failure preservation independently if the fixture can induce a real aggregate fault between diagnostic reads; clearly distinguish intentional mutation from the coherence-supported route.

### Public workload coherence

Run the exact existing `ai_warm_workspace` caller in four fresh diagnostic processes (FP16/BF16 × ephemeral/workspace), one prime plus 32 operations each. Its four snapshot locations already exist (`main.cpp:340–479`, `observer.cpp:100,204,218`). Expected complete scope is 132 launches, 4,224 exact words, 16 snapshots, 528 available queries/1,056 halves, and 192 unavailable rows with no query. Require explicit operation close, no live queue/submitter before terminal snapshot, queue worker join, all buffer/kernel/module releases, and exact full enabled inventory. The existing dynamic-subset `valid_snapshot` is insufficient by itself.

## Boundaries and risks

- This scope is RV64 p02-tfr timing SimX, PERF=1, checked counters, one worker, CP direct RAM; do not infer LLC-client or native RTL qualification. Both FP16/BF16 backend artifacts need distinct source/build binding if format flags differ.
- DCR reads do not themselves tick the model, but CP polling and concurrent submitters can invalidate an informal coherence argument. Observe entry traces and prove caller ownership, do not claim atomic public API semantics.
- Device release success is not a drain/final-destruction certificate. Strong diagnostic counters must establish the actual destructor and no surviving queues/references. Terminal finalizer proof remains the lifetime audit's independent responsibility.
- Clean source, generated configuration, all actual compile/link commands, tools/dependencies, executing interpreter, all executable artifacts and before/after identities must be retained. Diagnostic wrappers must be bound and absent from warm measurement artifacts.
- Local native execution is unavailable under the currently observed disk reserve; use the existing bounded hosted workflow rather than lower the 15 GiB guard.
- A diagnostic pass advances the prerequisite; it does not establish warm readiness or close P06-A02/A03. Keep warm-v1 rejection unconditional.
