# SimX checked performance counters v1

## Scope and status

This contract defines the opt-in arithmetic guard implemented in
[`perf_counter.h`](../../sim/common/perf_counter.h) and its integration into the
33 available counters of the
[warm-workspace manifest](../../ci/project/p06_warm_contract.json). It supplies
a source-level no-wrap invariant for an instrumented SimX build. It does not
itself establish native execution, complete selector transport coverage, a
qualified warm attempt, or any phase acceptance.

The [counter qualification plan](../project/p06-mpm-qualification-plan.md)
continues to require independently reviewed source/build bindings, counter
semantics, coherent reads, native evidence and a fresh complete experiment.
The historical [warm v1 contract](warm_workspace_benchmark_v1.md), analyzer and
replay retain their unconditional `P06-WARM-RV64-MPM-HIGH-HALF` block,
`qualified=false` and `absolute_no_wrap_bound="not_established"`. New source
cannot recover missing historical high bits or qualify old binaries.

## Build and arithmetic contract

When `SIMX_CHECKED_COUNTERS` is undefined, `vortex::PerfCounter` is exactly an
alias for `uint64_t`. Defining it to the preprocessor value `1` selects the
checked class; any other defined value is a compilation error. This is a
simulator instrumentation option, independent of the generated hardware
configuration. All relevant SimX translation units must use the same mode.
Mixing checked and ordinary objects is unsupported and must be rejected by the
qualification build's compiler-record and binary checks.

The enabled class stores one unsigned 64-bit value, initially zero. Integral
construction, assignment and deltas reject negative operands; operands wider
than `uint64_t` are rejected at compilation. It supports checked `+=`, `-=`,
prefix/postfix increment and decrement, copying, and conversion to `uint64_t`
for existing read interfaces. Direct binary addition/subtraction involving the
class is deleted so that aggregate construction uses checked accumulation.

Before an addition, the guard requires `delta <= UINT64_MAX - value`. Before
a subtraction, it requires `delta <= value`. A violation throws the dedicated `PerfCounterError` before modifying the
affected stored value. Its `Reason` is `Overflow`, `Underflow` or
`NegativeOperand`; `what()` returns the corresponding static
`SIMX_CHECKED_COUNTER_FAILURE: overflow`, `underflow` or `negative operand`
diagnostic. The exception payload constructs no dynamic diagnostic string;
this does not assert that the C++ exception runtime allocates no storage.
Checks remain active with `NDEBUG`. Failure neither clamps nor saturates a
counter and cannot produce a valid measurement.

The [completion contract](simulator_completion_v1.md) supplies failure
transport. The supported asynchronous entry is `Processor::run_checked()`,
whose exception is consumed by `AsyncRun`; synchronous processor queries use
its guarded `invoke()` boundary. Either path retains terminal device failure,
rejects later work and joins execution during destruction. The legacy direct
`Processor::run()` catch-and-return interface is outside this route. Catching
a guard exception does not make a failed context reusable or validate a partial
aggregate. Full failed-context disposal must precede a fresh context. The
supervisor must invalidate the whole attempt, including faults in excluded
primes or warm-ups, under the existing no-replacement rule.

## Supported qualification route

The declared route is RV64 `p02-tfr` SimX **timing** execution with `PERF=1`
and effective `PERF_ENABLE`, plus checked counters enabled in every applicable
model object. The source
[profile](../../profiles/p02-tfr.json) and effective generated configuration
must agree on one cluster, one core, one socket, four warps, four threads and
issue width one. Tensor arithmetic is TFR; scalar arithmetic is STD. FP16 and
BF16 inputs use the existing FP32-output `(8,4,8)` workload.

The warm contract also fixes 64-byte memory blocks, 16 KiB I-cache, D-cache and
local memory, two memory banks, and disabled L2/L3 cache reporting. It forbids
`SIMX_FUNCTIONAL` and `SIMX_MT`. Presence of the guard alone does not qualify
another topology, optional extension, execution mode or counter inventory.
All 45 manifest rows remain explicit: **33 available and 12 unavailable**.
Unavailable L2/L3 rows must not become fabricated zero-valued measurements.

Every selected query uses `core_id=0`. The runtime's all-core selector
`0xffffffff`, whose summation has a separate implementation, is outside this
contract. No public runtime API, CSR/DCR encoding, RTL counter width or hardware
counter implementation is changed by this instrumentation.

## Storage and aggregation coverage

The following map names every available warm selector. Declaration links locate
the checked types; update/aggregation links identify the source bodies that must
be bound and independently reviewed with them.

| Selectors | Count | Checked storage and aggregation |
|---|---:|---|
| `cycles`, `instructions`, `core_sched_idle`, `core_active_warps`, `core_stalled_warps`, `core_issued_warps`, `core_issued_threads`, `core_stall_scrb`, `core_stall_lsu`, `core_stall_tcu`, `core_instr_tcu`, `core_loads`, `core_stores` | 13 | [`Core::PerfStats`](../../sim/simx/core.h); updates in [`core.cpp`](../../sim/simx/core.cpp) and [`lsu_unit.cpp`](../../sim/simx/lsu_unit.cpp) |
| `icache_reads`, `icache_miss_r`, `icache_mshr_st`, `dcache_reads`, `dcache_writes`, `dcache_miss_r`, `dcache_miss_w`, `dcache_evicts`, `dcache_mshr_st` | 9 | [`Cache::PerfStats` and its `operator+=`](../../sim/simx/mem/cache.h); bank/cache updates in [`cache.cpp`](../../sim/simx/mem/cache.cpp), with aggregation through [`cache_cluster.cpp`](../../sim/simx/mem/cache_cluster.cpp) and [`socket.cpp`](../../sim/simx/socket.cpp) |
| `lmem_reads`, `lmem_writes`, `lmem_bank_st` | 3 | [`LocalMem::PerfStats`](../../sim/simx/mem/local_mem.h), updated in [`local_mem.cpp`](../../sim/simx/mem/local_mem.cpp) |
| `coalescer_miss` | 1 | [`MemCoalescer::PerfStats::misses`](../../sim/simx/mem/mem_coalescer.h), updated in [`mem_coalescer.cpp`](../../sim/simx/mem/mem_coalescer.cpp); checked local sum in [`csr_unit.cpp`](../../sim/simx/csr_unit.cpp) |
| `memory_reads`, `memory_writes`, `memory_lt` | 3 | Stored and returned memory counters in [`ProcessorImpl`](../../sim/simx/processor_impl.h); request/response and latency updates in [`processor.cpp`](../../sim/simx/processor.cpp) |
| `memory_bank_st` | 1 | [`TxCrossBar::collisions_`](../../sim/simx/types.h), propagated through [`Memory::PerfStats`](../../sim/simx/mem/memory.h) in [`memory.cpp`](../../sim/simx/mem/memory.cpp) |
| `tcu_tbuf_stalls`, `tcu_tbuf_cache_hits`, `tcu_lmem_reads` | 3 | [`TcuUnit::PerfStats`](../../sim/simx/tcu/tcu_unit.h), updated in [`tcu_unit.cpp`](../../sim/simx/tcu/tcu_unit.cpp); underlying buffer `reads_` and the checked per-buffer sum in [`tcu_tbuf.cpp`](../../sim/simx/tcu/tcu_tbuf.cpp) |

`ProcessorImpl::perf_mem_pending_reads_` is additionally checked because it
feeds `memory_lt`: request increments and response decrements must not wrap.
An unmatched response throws before the pending count changes; it must reach
the terminal processor-failure boundary instead of contributing a wrapped
`UINT64_MAX` balance to latency.

Some additional members of these statistics structures acquire the checked
type, but that does not extend this contract's inventory. In particular,
cache-internal collision sources for non-warm cache bank-stall counters and
operand-stall sources remain outside the reviewed 33-selector claim. This is
not an every-counter, every-extension or whole-simulator no-wrap contract.

## Absolute arithmetic bound and its assumptions

Let `U = 2^64 - 1`. At construction a cumulative source counter is zero.
Assume its stored value equals the true nonnegative integer total `c`, with
`0 <= c <= U`, and that the next exact event increment is `d >= 0`. A successful
guarded update requires `d <= U - c`, so its new value is exactly `c + d <= U`.
Induction over every update therefore gives **true cumulative value `< 2^64`**
throughout a fully instrumented context whose guarded operations all complete
normally. An attempted violation throws before overflow, even if it occurs
after the last measurement, and invalidates the context and its attempt.

The same argument applies to each zero-initialized aggregate and each checked
`+=` of its component totals. Guarding only the published field is insufficient:
the TCU buffer read total, CSR coalescer sum and underlying crossbar collision
storage must also be checked. Pending-read subtraction must preserve its
nonnegative accounting invariant before it contributes to latency.

This proof depends on source inspection as well as the counter class. The
class permits assignment and conversion for existing interfaces; it does not
recognize a cumulative counter reset, an explicit narrowing cast, an already
wrapped scalar expression, or writes that bypass it. Qualification must bind
and review every update, reset and derived sum in the table. In particular, a
checked `+=` cannot detect overflow that already occurred while computing its
argument. The supported update paths supply exact nonnegative counts or checked
component totals; any changed source path requires renewed review.

The bound applies across initialization, excluded primes, measured operations,
and teardown because the same stored counters remain guarded throughout the
process. It relies on no estimated event rate, wall-clock timeout, small observed
value, sampled monotonicity or simulator tick limit. A passing standalone class
test proves its arithmetic behavior; it does not prove every model object in a
particular executable used that class.

## Lifetime and coherent observation

The source counters start at zero when their owning objects are constructed.
The existing model deliberately retains cumulative statistics across kernel
launch resets. This instrumentation preserves that behavior. Fresh temporary
aggregates may start at zero on each query; their components remain cumulative.
The separate pending-read balance retains its existing explicit reset and must
be reconciled with request/response completion. Counter guarding does not make
an arbitrary reset while requests remain outstanding a supported operation.

`cycles` counts active core cycles, not elapsed platform ticks. Instructions,
warp/thread events, memory requests, accumulated pending-read latency and tensor
buffer events keep their existing distinct meanings and units in the manifest.
No-wrap alone proves neither event semantics nor reset correctness.

Coherence is scoped to the serial owner in the
[workspace contract](serial_matmul_workspace_v1.md). The benchmark observes
counters after explicit operation close, with one context and no concurrent
launch or DMA caller. [`ProcessorImpl::run()`](../../sim/simx/processor.cpp)
drains the platform before normal completion, and the
[SimX DCR hooks](../../sw/runtime/simx/vortex.cpp) wait for the processor future.
The [public query](../../sw/runtime/common/perf.cpp) submits low and high reads
synchronously; those DCR reads do not advance the model. Under these conditions
both halves observe the same stable value. Checked arithmetic adds no atomic
snapshot, lock, arbitrary-client concurrency guarantee or RTL coherence proof.

## Evidence required before using new measurements

A new versioned qualification route must establish all of the following:

1. Independent review of the guard, all 33 storage/update/aggregation paths,
   reset semantics and serial coherence assumptions at the exact source bodies.
2. Real positive and negative guard tests, including overflow, aggregate carry,
   underflow, signed-negative operands, release builds, unchanged rejected
   primitive values and persistent asynchronous/synchronous failure.
   A failed build, timeout or unrelated crash cannot substitute for an expected
   guard failure. Helper-level `AsyncRun` checks, linked native model failures
   and actual public runtime wait/query failures remain distinct evidence.
3. Actual warm-configuration transport coverage, including required selectors
   and high-half boundaries. Earlier TCU-disabled transport evidence retains
   its original narrower scope.
4. Clean source revision/tree and retained source bodies; actual generated
   configuration; independent compiler/linker records proving checked mode in
   every relevant translation unit; dependencies, tools, actual executing
   interpreter and host/runtime/kernel binary identities; before/after stability.
5. A complete fresh native attempt using identical instrumented binaries for
   both policies within each format. Archives and raw outcomes must survive
   independent replay; retained code remains inert during that replay.

A caller flag, revision label, reviewer string or self-generated digest cannot
replace these obligations. Missing proof remains blocked. Malformed, stale,
unsupported or mismatched evidence is rejected. Readiness for a new experiment,
its successful execution, its statistical outcome and phase acceptance are
separate decisions.

## Timing, compatibility and acceptance limits

The ordinary undefined-mode alias preserves existing field types and arithmetic.
The integration changes no modeled pipeline, scheduling, queue depth, arithmetic
datapath or event rule. Native comparisons must still establish that the guarded
and ordinary modes agree on defined outputs and modeled counts below failure;
source equivalence is not a report of an executed parity test.

Checked mode adds host instructions. Any future warm comparison measures the
instrumented implementation, with the same guard in both allocation policies.
Its cost is not subtracted and no result is attributed to uninstrumented code.
The existing workload, poison sequence, policy order, 24-process population,
792 launches, 25,344 output words, five measured batch means and three unchanged
statistical predicates remain the proposed fresh-experiment contract.

This document claims no hosted run or current warm readiness. It accepts no
speedup, P06-A02/A03, vendor P01-A03, physical FPGA result, silicon measurement,
power/energy result or synthesis budget. The inherited tensor DSP regression,
original acceptance records and other open phase obligations remain separate.
