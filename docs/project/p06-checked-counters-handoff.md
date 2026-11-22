# P06 checked-counter development handoff

## Resume here

**The next implementation is a source-bound terminal `before_release`
qualification record and its enforcement path.** First close the lifetime and
ownership proof below, extend the native diagnostics to the fourteen remaining
backing sources and actual public failure/coherence paths, then implement and
independently review the new qualification reader. Only reviewed readiness can
admit the unchanged fresh warm experiment.

The [implemented guard contract](../designs/simx_checked_counters_v1.md),
[development audit](p06-checked-counters-audit.md) and
[qualification plan](p06-mpm-qualification-plan.md) govern this continuation.
Checked component storage and successful checked aggregate reads are now
implemented and have directed native evidence. Complete aggregate lifetime,
all-selector transport, native public counter-failure containment and the new
qualification reader remain open. The current runner reports `qualified=false`,
`ready_for_warm=false`, `full_warm_coverage=false` and `warm_execution=false`.

## Completed implementation and exact evidence

[`PerfCounter`](../../sim/common/perf_counter.h) is an opt-in checked class when
`SIMX_CHECKED_COUNTERS=1`. Undefined mode retains the exact `uint64_t` alias.
The integration covers the audited storage, updates and formed sums for all
33 available selectors, including the memory pending-read balance, crossbar
collision backing field, CSR coalescer sum and private tensor-buffer read sum.
It does not extend the reviewed inventory to every simulator counter.

Overflow, underflow and signed-negative operands throw typed
`PerfCounterError` before changing the rejected primitive value. The
[completion owner](../../sw/runtime/common/async_run.h) consumes the exception
from `Processor::run_checked()` or its guarded synchronous invocation, retains
terminal failure and suppresses later work until full disposal. The legacy
catch-and-return `Processor::run()` is excluded. Failed ticks or aggregates are
invalid; the implementation promises no rollback of earlier successful member
updates and no reuse of a failed context.

The [runner](../../ci/project/p06_checked_execute.py),
[build fragment](../../sim/simx/checked_counters.mk),
[native harness](../../tests/unittest/checked_counters/main.cpp) and
[hosted workflow](../../.github/workflows/p06-checked-counters.yml) establish a
bounded prerequisite route. The shared
[tool identity collector](../../ci/project/p06_mpm_execute.py) records the
actual `sys.executable` separately from PATH `python3`; the hosted workflow
requires their resolved identities to agree. A PATH lookup alone is no longer
the provenance claim for the executing interpreter.

### Original execution identities

| Evidence | Actual result and scope |
|---|---|
| [Actual hosted governance receipt](evidence/p06-checked-counters/hosted/governance-index.json) | **3,062 tests passed in 1,295.925 seconds** at published `9fd7eac…`, run `45017731138`, attempt 1. Independent original-log review confirms no failures/errors/skips and successful job cleanup. |
| [Full host governance receipt](evidence/p06-checked-counters/local/governance-53f4ad08c/index.json) | **3,043 tests passed in 1,647.227 seconds** at local `53f4ad08c469a1cc73fa604249b302f9416055e0`, with source and executing Python stable. |
| [Publication mapping](evidence/p06-checked-counters/publication.json) | That local checkpoint and published `a9227933c340fd44e73deaffafdd353fecf65492` share tree `80553bb237af44b187dd6d18178e851cd6671ec8`. Equal source trees do not change the actual execution identity or establish a later full-suite run. |
| Later host checks | The fourteen workflow and five controlled public-runtime methods passed separately. The later actual 3,062-test hosted run is separately retained; the earlier 3,043-test receipt is not relabeled as that execution. |
| [Hosted native run 45017731063, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45017731063) | **Passed** at actual published `9fd7eac203c77fa54c7af80fa0220ae09553cd55`: two fresh native variants, **44 compiled translation units and one link each**, and all five directed cells below. |
| [Original native ZIP](evidence/p06-checked-counters/native/run-45017731063-attempt1.zip) and [extracted report](evidence/p06-checked-counters/native/report-45017731063.json) | Artifact `14753040127`; 1,119,268-byte ZIP; SHA-256 `66dd0db69db3fb0d22f975c8d67cea8f445aa40a3f1ac0fbb0d5b20529aa9b40`. The report matches `checked-counters/report.json` in that ZIP. The [independent original-packet review](evidence/p06-checked-counters/reviews/native-review.md) verifies the five behaviors and source/build bindings with no F1/F2/F3 finding in either assigned scope. |
| [Local native preflight](evidence/p06-checked-counters/local/native-preflight-53f4ad08c.json) | Blocked by the unchanged 15 GiB free-disk reserve, before native processes started. This remains a separate blocked result. |
| [Local build dry run](evidence/p06-checked-counters/local/dry-run/README.md) | Configuration and prospective compiler-command evidence only; it neither compiled objects nor executed a native diagnostic. |

The native report records these distinct scopes:

| Cell | Passed observation | Limit |
|---|---|---|
| `ordinary-boundaries` | Nineteen seeded selectors, ten vectors each, both half-read orders; 760 half reads and 2,749 checks. | Fourteen available backing sources remain unseeded. |
| `checked-boundaries` | The same boundary matrix passes with checked storage; ordinary/checked directed observations agree. | Seeded transport/aggregate agreement does not establish normal-workload cycle parity. |
| `checked-core-overflow` | Actual Core updater failure through `run_checked()` and production `AsyncRun`; typed overflow, unchanged protected value, eight sticky-failure checks, two suppressed tasks, join and fresh-context success. | The cell does not call the public runtime. |
| `checked-cache-aggregate-overflow` | Production cache aggregate throws with unchanged tested source and protected value. | The directed first-member failure does not establish rollback after a later aggregate member fails. |
| `checked-pending-underflow` | Typed underflow and unchanged protected value. | This is a pending-counter primitive check, not injection into the private Processor pending-read balance. |

The implementation-stage **64 focused host methods** are separately scoped:

| Suite | Methods | Evidence boundary |
|---|---:|---|
| [Primitive and completion-owner tests](../../ci/project/test_p06_checked_counter.py) | 12 | Release/UBSan arithmetic, typed failure, ordinary compatibility and actual `AsyncRun` containment. |
| [Production-header integration](../../ci/project/test_p06_checked_integration.py) | 6 | Field types, layout, aggregate operators and harness syntax; no linked native model execution. |
| [Native-runner enforcement](../../ci/project/test_p06_checked_execute.py) | 27 | Real temporary identities with explicitly mocked native process execution. |
| [Workflow contract](../../ci/project/test_p06_checked_ci.py) | 14 | Actual preflight/interpreter bodies, failing producer pipelines and trust/resource constraints. |
| [Controlled public-runtime faults](../../ci/project/test_p06_checked_public.py) | 5 | Ten RAM/LLC cells through actual runtime, CP and SimX backend, using controlled Processor/RAM substitutes. |

Five additional executing-interpreter methods extend the existing
[transport-runner suite](../../ci/project/test_p06_mpm_execute.py). The ten
controlled public cells exercise real counter exceptions and sticky public
failure, but do not establish native backing-source fault injection. Their
[independent review](evidence/p06-checked-counters/reviews/public-fault-review.md)
also scopes the query failure to the first failing DCR read. It does not claim
exhaustive low/high-half failure coverage or native aggregate reduction.

The [integrated independent review](evidence/p06-checked-counters/reviews/integrated-review.md)
approved the bounded implementation/CI checkpoint, with
[source-proof](evidence/p06-checked-counters/reviews/source-proof-review.md) and
[execution-path](evidence/p06-checked-counters/reviews/execution-path-review.md)
reviews retained separately. The later [original native review](evidence/p06-checked-counters/reviews/native-review.md)
independently checks the actual five-cell packet and its source/build bindings;
it preserves the incomplete transport, public-runtime and lifetime scope.

## Exact route and remaining transport work

Bind the [frozen warm manifest](../../ci/project/p06_warm_contract.json),
[`p02-tfr` profile](../../profiles/p02-tfr.json), generated configuration and
actual compiler records. The supported route is RV64 timing SimX with
`PERF=1`, one cluster/core/socket, four warps of four threads, issue width one,
TFR tensor and STD scalar arithmetic, and dense FP16/BF16 `(8,4,8)` WMMA with
FP32 output. It uses 64-byte memory blocks, 16 KiB I-cache/D-cache/local memory
and two memory banks. VM, L2/L3, WGMMA, DSM, sparse and matrix-load/store routes
are excluded. `SIMX_FUNCTIONAL` and `SIMX_MT` are excluded; this is one
simulation worker. The complete manifest supplies the remaining exclusions.

Every query selects representative `core_id=0`; the public all-core selector
and its separate summation are outside this contract. The exact inventory is
**33 available and 12 unavailable**, not a dynamically accepted subset:

| Available selectors | Count | Native backing sources seeded so far |
|---|---:|---:|
| `cycles`, `instructions`, `core_sched_idle`, `core_active_warps`, `core_stalled_warps`, `core_issued_warps`, `core_issued_threads`, `core_stall_scrb`, `core_stall_lsu`, `core_stall_tcu`, `core_instr_tcu`, `core_loads`, `core_stores` | 13 | 13 |
| `icache_reads`, `icache_miss_r`, `icache_mshr_st` | 3 | 0 |
| `dcache_reads`, `dcache_writes`, `dcache_miss_r`, `dcache_miss_w`, `dcache_evicts`, `dcache_mshr_st` | 6 | 0 |
| `lmem_reads`, `lmem_writes`, `lmem_bank_st` | 3 | 3 |
| `coalescer_miss` | 1 | 1 |
| `memory_reads`, `memory_writes`, `memory_lt`, `memory_bank_st` | 4 | 0 |
| `tcu_tbuf_stalls`, `tcu_tbuf_cache_hits`, `tcu_lmem_reads` | 3 | 2 |
| **Total** | **33** | **19** |

The **fourteen unseeded available selectors** are explicitly:

```text
icache_reads
icache_miss_r
icache_mshr_st
dcache_reads
dcache_writes
dcache_miss_r
dcache_miss_w
dcache_evicts
dcache_mshr_st
memory_reads
memory_writes
memory_lt
memory_bank_st
tcu_lmem_reads
```

Keep the twelve unavailable L2/L3 rows as
`enabled=false,status=null,value=null`, receiving no query. TCU rows remain
available even where ordinary execution leaves them zero. Test-only injection
must reach each true backing source through the actual Processor → Cluster →
Socket → Core → CSR route. A copied decoder, synthetic selector array or
temporary statistics copy cannot establish that route. In particular,
[`TcuUnit::perf_stats()`](../../sim/simx/tcu/tcu_unit.cpp) derives local-memory
reads from the [private tensor buffers](../../sim/simx/tcu/tcu_tbuf.cpp).

`memory_bank_st` at MEM class 7 / CSR `0xB06` has a
[SimX source](../../sim/simx/csr_unit.cpp) but no corresponding case in the
[RTL MEM decoder](../../hw/rtl/core/VX_csr_mpm.sv). Completing these fourteen
SimX sources will not establish all-33 RTL parity. The public ABI, CSR/DCR
encodings and ordinary mode remain unchanged.

## Close the terminal lifetime proof

The guard proves that each audited stored component stays in
`[0, UINT64_MAX]`, and that each successfully formed checked aggregate fits.
Independent components can still have an unrepresentable mathematical sum
between queries. A successful process or several monotonic samples cannot
close that gap.

The selected proof location is the existing
[`before_release` observer](../../tests/regression/ai_warm_workspace/observer.cpp).
For source-proved nonnegative monotonic components `c_i`, a successful checked
terminal observation at `T` gives `sum(c_i(T)) <= UINT64_MAX`. For every earlier
`t`, monotonicity then gives `sum(c_i(t)) <= sum(c_i(T))`. A separate proof that
no later update occurs extends the result through actual disposal. All three
premises are required: guarded sources, monotonicity over the complete lifetime,
and a complete checked terminal snapshot followed by no updates.

The [configuration formulas](../../sim/simx/constants.h) and
[socket construction](../../sim/simx/socket.cpp) give **two D-cache banks**:
four RV64 LSU lanes cover 32 bytes, divided into two 16-byte D-cache words.
The six D-cache selectors are therefore six active two-source aggregates.
There is one I-cache bank, one shared local-memory statistics object despite
four physical banks, one coalescer and one global crossbar collision
accumulator. Two physical DRAM banks do not imply two global counter sources.
The TCU read aggregate has two private buffers; its ordinary producers, along
with buffer stalls/hits, remain inactive on this WGMMA-disabled route. Those
rows still require transport coverage and binding to the actual configuration.

The next record and reader must bind the following proof obligations:

| Boundary | Required implementation and retained proof |
|---|---|
| Construction and updates | Exact source bodies for all 33 selectors: zero origins, cumulative reset behavior, checked updates and each derived sum. The transient pending-read balance needs matched request/response accounting and quiescent reset; it is not a monotonic cumulative source. |
| Operations and queues | The [warm caller](../../tests/regression/ai_warm_workspace/main.cpp) waits, closes and destroys each operation before snapshots. Bind [queue destruction](../../sw/runtime/common/queue.cpp), worker join, release of work captures and disappearance of every operation-held Device reference. |
| Exclusive owner and submitter | One context, no surviving queues/workers, no external Device retain and no legacy/debug or concurrent CP submitter. Source review and observations must justify these premises rather than relying on successful calls alone. |
| Owner close | Bind [runtime release ordering](../../sw/runtime/ai/runtime.cpp): resident buffers, kernel and module are freed before the wrapped device release. Require the observer's owner-close phase and zero observed live public buffers. |
| Terminal snapshot | Require exactly all 33 expected available rows and all twelve unavailable rows. Both halves must succeed after operations and synchronous CP transactions retire, while no actor can update counters or replace replies. |
| After the snapshot | Bind VM off and `CP_ON_L2=CP_ON_L3=0`. Prove no later launch, flush or model-ticking transfer; separately account for allocator release, CP bookkeeping, completed backend join and actual full platform disposal. |
| Dependency finalization | Bind the selected DRAM backend and exact dependency revision, including the [DRAM adapter](../../sim/common/dram_sim.cpp), Ramulator frontend/memory-system `finalize()` calls and callback delivery. |
| Failure | A guard, query, ownership, cleanup or provenance failure invalidates the whole attempt, including excluded primes and warm-ups; preserve terminal failure and require failed-context disposal before a fresh context. |

Three existing behaviors require explicit treatment:

1. [`Device::cp_quiesce_()`](../../sw/runtime/common/device.cpp) returns no
   result and can stop after backend failure or exhausted polling. The
   [CP busy predicate](../../sim/common/cmd_processor.cpp) includes `enabled()`;
   disabling CP can make BUSY false with pending command state. Neither that
   observation nor a successful release is a drain certificate.
   `vx_device_release()` success can mean only a reference was released, not
   that the final reference destroyed the Device.
2. The [public MPM query](../../sw/runtime/common/perf.cpp) publishes a 64-bit
   value only after two successful reads. However, `cp_submit_dcr_read()` reads
   `Q_LAST_DCR_RSP` after releasing its submit/poll lock. A second submitter can
   replace the reply even when counters are quiescent. The qualification route
   must enforce exclusive serial submission; successful half reads alone do
   not provide atomic snapshot semantics.
3. [Platform cleanup](../../sim/common/simobject.h) discards queued events,
   while DRAM destruction also finalizes the bound Ramulator components.
   Adapter replies normally reach GPU callbacks through a subsequent drain/tick,
   but the dependency's finalization behavior still needs inspection. Do not
   assert that every teardown action only discards work before closing this
   dependency edge.

Preserve `memory_lt` semantics: it accumulates pending-read occupancy in the
existing run/cycle entry points. Other flush/CP-transfer paths can tick the
platform without updating it. It is not an integral over all platform ticks.
Do not replace the lifetime proof with a guessed event rate, timeout, small
observed value, sampled monotonicity, clamp or unimplemented tick cap.

## Sequenced development and exit conditions

1. **Close and independently review the terminal proof and record contract.**
   Review the exact source/configuration/dependency bodies above, distinguish
   final reference destruction from a successful release, and specify the
   required observations and rejection conditions. Keep readiness false where
   a lifetime, ownership or finalizer premise remains unsupported. Use the
   independently reviewed five-cell packet only within its documented native
   prerequisite scope.
2. **Extend actual native transport to the fourteen backing sources.** Use the
   ten frozen vectors, unequal source values, both half-read orders, repeated
   and alternating classes/selectors, and values above bit 43. Exercise each
   distinct FP16/BF16-bound timing SimX backend artifact. Retain fresh builds,
   original logs, true source selection and exact 33/12 accounting. Keep
   test-only seeding or reduced failure limits out of measurement binaries.
3. **Execute actual public coherence and native counter-failure diagnostics.**
   The planned coherence matrix is FP16/BF16 × both policies: four processes,
   each one prime plus 32 operations, for 132 launches and 4,224 exact output
   words. Four snapshot locations per process give 16 snapshots, 528 available
   queries/1,056 half replies and 192 unavailable rows with no query. Add actual
   guarded model failures with persistent public waits/query rejection, later
   work suppression, queue-error consumption, join/cleanup and fresh-context
   controls. Distinguish actual updater, aggregate, pending-balance and
   low/high-query failure paths; controlled Processor/RAM cells do not fulfill
   this native obligation.
4. **Implement the separately versioned strict qualification reader/replay.**
   Bind the reviewed inventory, source/tree and source bodies, generated
   configuration, compiler/link records, guard mode, dependencies, actual
   interpreter and all host/runtime/kernel binaries. Bind coherence, terminal
   readout, exclusive ownership, complete lifetime and dependency-finalization
   premises, plus native diagnostics at matching identities. Fix the
   qualification digest before each process launches; join it to final original
   commands/logs/resource records without circular archive bindings. Reject
   missing, stale, unsupported, altered or mismatched evidence and qualification
   that remains invalid even when statistics are favorable. Exercise both
   favorable and unfavorable statistics, rehashed inconsistent records,
   missing terminal rows, failed close/cleanup and disabled/mixed guards.
   Retained helpers are inert data during replay, never trusted code to execute.
   Independent enforcement review precedes readiness.
5. **After reviewed readiness, run the unchanged fresh warm matrix.** Preserve
   FP16 then BF16, six ordered policy pairs per format, one prime plus 32 serial
   operations per process: **24 processes, 792 launches and 25,344 exact FP32
   output words**. Retain excluded primes and warm-ups, identical checked
   binaries for both policies within each format, before/after identities and
   all failures. Keep five measured batch means and all three statistical
   predicates unchanged. No replacement samples, optional stopping, outlier
   removal or observer-overhead subtraction is permitted.

Retain the existing resource limits: two build jobs, 4 GiB polled RSS,
15 GiB free-disk reserve, 16 MiB logs, 1,800-second builds, 180-second
invocations and a 90-minute hosted job. The four-process diagnostic matrix
does not replace the complete warm experiment.

## Boundaries to preserve

Checked instrumentation adds host instructions. Future timing measures the
instrumented implementation with identical guarding in both policies; no
result represents uninstrumented host timing and no guard cost is subtracted.
Default ordinary builds retain their existing type and arithmetic behavior.
No modeled datapath, public API, CSR encoding or hardware counter width is
changed by this guard slice.

Keep the [warm-v1 contract](../designs/warm_workspace_benchmark_v1.md),
[analyzer](../../ci/project/p06_warm_analyze.py) and
[replay](../../ci/project/p06_warm_replay.py) unconditionally blocked by
`P06-WARM-RV64-MPM-HIGH-HALF`, with `qualified=false` and
`absolute_no_wrap_bound="not_established"`. New metadata cannot qualify old
archives or reconstruct missing historical high bits. Preserve original
acceptance records, cold execution pins, statistical thresholds, baselines and
goldens. This handoff establishes no performance improvement, P06-A02/A03
acceptance, RTL parity, vendor P01-A03 result, physical FPGA result, silicon
measurement or power/synthesis budget.
