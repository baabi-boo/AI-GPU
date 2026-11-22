# P06 counter qualification plan

## Decision and current boundary

**Next bounded development: freeze and independently review a versioned
counter, coherence and lifetime contract for the exact 33-selector RV64
`p02-tfr`, timing SimX, `PERF=1` warm route.** Then implement the reviewed narrow
guard and qualification reader, qualify their actual native/public execution,
and collect one fresh complete matched warm attempt. This is a prospective
plan: the guard, qualification record and new evidence format described below
are not implemented, and no absolute no-wrap bound is established by this document.

The [transport audit](p06-mpm-transport-audit.md) identifies the original RV64
high-half defect and paired SimX/RTL repair. The
[reviewed native packet](evidence/p06-mpm-transport/reviews/native-review.md)
passes all eight directed candidate executions and establishes both same-harness
parent numeric failures at `18c8880`. Its immutable governance suite passes
2,910 tests. The [alternative comparison](evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the specific cost-review finding and selects the direct decoder, with
raw area failures preserved. The [handoff](p06-mpm-transport-handoff.md) separately records the transport
CI/publication history. A native transport pass is distinct from a proved
counter lifetime, a warm experiment or P06 acceptance.

The [warm v1 contract](../designs/warm_workspace_benchmark_v1.md), its
[analyzer](../../ci/project/p06_warm_analyze.py) and
[replay](../../ci/project/p06_warm_replay.py) retain the unconditional
`P06-WARM-RV64-MPM-HIGH-HALF` block, `qualified=false` and
`absolute_no_wrap_bound="not_established"`. Preserve their historical rejection
behavior, original cold execution pins and accepted archives. Missing historical
high bits cannot be recovered from low words.

## Completion prerequisite

The [completion contract](../designs/simulator_completion_v1.md) addresses
exceptions lost by the old SimX run entry and asynchronous backend wrappers,
tasks completed before their first busy poll, and abandoned channel accounting
at full timing/functional platform teardown. The checked entry preserves valid
`gp` values, including `-1`; `AsyncRun` consumes futures, retains processor
failure, preserves the launch edge and joins pending execution before teardown.
Synchronous processor hooks share that terminal boundary. Unrelated CP/host
exceptions retain the inherited mapping: CP scratch OOM can report
`VX_ERR_OUT_OF_HOST_MEMORY` and permit same-device transfer continuation without
making a failed processor reusable.

The [completion evidence index](evidence/p06-simulator-completion/README.md)
separates controlled host faults, actual framework checks, built negative
controls and native execution by exact source. The initial native checkpoint
`db5ebb3` passed checked-model/fresh-context and public-success controls; the
subsequent CP error-boundary repair at `4781ca9` requires its own source-bound
verification. Use the index's receipts and independent review to assess that
repair; do not relabel the initial packet as later-code evidence. A prospective
counter guard must use the verified processor-failure path and reach public
waits persistently. Host injection does not establish native public fault or
RTL execution. Preserve the 15 GiB native disk reserve.

## Exact route and selector gap

Bind the [frozen manifest](../../ci/project/p06_warm_contract.json),
[profile](../../profiles/p02-tfr.json), actual
[compiler records](../../ci/project/p06_warm_compiler_records.py) and expanded
C++ dimensions. The route is RV64 timing SimX, one cluster/core/socket, four
warps of four threads, issue width one, TFR tensor and STD scalar arithmetic,
ordinary dense FP16/BF16 WMMA with FP32 output, and `PERF=1`. I/D caches and
16 KiB local memory are enabled; L2/L3, VM, WGMMA, DSM, sparse and matrix-load/
store routes are excluded. `SIMX_FUNCTIONAL` and `SIMX_MT` are excluded, giving
one simulation worker. The complete manifest governs the remaining feature
and configuration exclusions; a profile name alone cannot establish them.

The [counter inventory](../../tests/regression/ai_bench_common/counters.h) and
[observer](../../tests/regression/ai_warm_workspace/observer.cpp) require:

| Counter class | Available rows | Unavailable rows | Required sources |
|---|---:|---:|---|
| BASE | 2 | 0 | Cycles and instructions |
| CORE | 11 | 0 | Scheduler, warp/issue, stall, instruction and load/store counters |
| ICACHE | 3 | 0 | Reads, read misses and MSHR stalls |
| DCACHE | 6 | 0 | Reads/writes, both miss kinds, evictions and MSHR stalls |
| MEM | 8 | 0 | Local memory, coalescer and global-memory counters |
| TCU | 3 | 0 | Buffer stalls, cache hits and local-memory reads |
| L2 / L3 | 0 | 12 | Six unavailable rows for each cache |
| **Total** | **33** | **12** | Exact class/CSR/core/scope/availability binding |

All rows use representative `core_id=0` while retaining their actual scope.
The twelve unavailable rows must remain `enabled=false,status=null,value=null`
and receive **no query**; a reported zero is not their representation. TCU rows
remain available even when the workload leaves them zero. Only cycles and
instructions require positive batch deltas under the existing warm rules.

The earlier [SimX transport harness](../../tests/unittest/mpm_transport/main.cpp)
seeds only **5 of the 33** required rows: cycles, instructions, scheduler idle,
active warps and stores. Its empty-profile, TCU-disabled configuration leaves
28 rows and the actual tensor configuration unqualified. Cycling through
performance classes while reading BASE selectors does not cover the distinct
selectors of those classes. The
[RTL leaf harness](../../hw/unittest/mpm_transport/main.cpp) seeds **19 of the
33**, leaving 14 omissions. Its extra L2/L3 seeds do not make those unavailable
warm rows available.

`memory_bank_st` at class 7, CSR `0xB06`, has a
[SimX backing source](../../sim/simx/csr_unit.cpp) but no case in the
[RTL MEM decoder](../../hw/rtl/core/VX_csr_mpm.sv). A future all-33 SimX
qualification therefore cannot be called all-33 RTL parity. An RTL extension
requires its own separate implementation and evidence. Preserve the existing
[host MPM wire contract](../designs/host_mpm_transport_v1.md) and public ABI:
each available public read reconstructs two successful unsigned 32-bit replies;
the high-half selector is internal, not a second public CSR argument.

## Qualification work to implement and review

1. **Specify the supported route.** Name the exact RV64 `p02-tfr` SimX timing
   configuration, enabled tensor/performance features, topology and available
   counter selectors used by the warm experiment. The directed transport tests
   use stable injected counters and TCU-disabled configurations; extend evidence
   to the actual warm configuration and each required available selector before
   claiming that coverage. Preserve architectural CSR semantics and public ABI.
2. **Bind evidence to execution.** Define a new versioned qualification record
   that binds reviewed transport evidence and its scope to the complete source
   revision/tree, relevant source bodies, generated configuration, original
   compiler/linker records, tools/dependencies and actual host/runtime/kernel
   binary identities. Resolve the [standalone interpreter finding](evidence/p06-mpm-transport/reviews/enforcement-review.md)
   by recording the actual executing interpreter separately from PATH `python3`;
   the current hosted workflow already requires their equality. Require identical
   binaries for both policies within each format, with before/after stability
   checks. A revision label, caller flag or
   self-asserted qualification ID is insufficient.
3. **Prove counter meaning and read coherence.** Document each counter's width,
   reset/lifetime, accumulation semantics and availability. Establish whether
   every snapshot is taken while the model is quiescent and prove that its two
   32-bit reads observe one stable value. If a counter can advance during the
   read, require a separately reviewed coherent-read contract and adversarial
   rollover evidence. The transport repair itself introduces no atomic snapshot
   or concurrency guarantee.
4. **Establish the absolute no-wrap bound.** Supply an independently reviewed
   bound for every required true cumulative counter over the complete interval,
   including initialization, primes, measured calls and teardown observations.
   Bind its assumptions to the executed configuration and reject violations.
   Observed monotonicity, small reported values, a process timeout or guessed
   event rates cannot substitute for that proof. Missing bounds remain blocked.
5. **Review rejection and replay behavior.** Keep the frozen v1 path blocked and
   introduce the new qualification path explicitly. Reject old, absent,
   unsupported, truncated, source/configuration/binary-mismatched or unreviewed
   evidence. Exercise both favorable and unfavorable statistics with invalid
   qualification data. Offline replay treats retained code as data and checks
   original archives, commands, resource observations and bindings independently.
   Require review by an agent that did not author the enforcement change under
   the [review policy](../review/code-review-policy.md).

Freeze the new qualification contract and review its tests before inspecting
fresh performance results. Do not widen a statistical threshold, change a
fixture, alter a golden or remove a failed attempt to obtain qualification.

## Prospective lifetime guard and proof obligations

The [platform clock](../../sim/common/simobject.h) resets on ordinary launch
reset, while the required cumulative MPM counters survive. Active-core cycles
also omit idle platform work. A per-launch cycle ceiling, a fixed launch count,
observed monotonicity, small readings or a wall-time deadline therefore cannot
establish an absolute bound for the device context.

**Design candidate for review, not implemented limits:** allow at most
`T = 2^32 - 1` charged platform ticks per context, with separate cumulative
memory-read and memory-write caps `E = 2^32 - 1`. These values are mathematical
guard choices, not measured workload requirements. A smaller reviewed ceiling
is possible; freeze the choice before inspecting performance.

| Boundary | Required proof or enforcement |
|---|---|
| Context birth | Establish zero origins and install one lifetime ledger before any initialization/model work; identify a definite owner/epoch for the process-global platform. |
| Every platform tick | Compare before increment and before any domain, immediate/due-event or worker action. Reject an exhausted or invalid ledger before counter mutation; charge partially executed ticks. |
| Launch/reset/flush/close | Preserve ledger and failure through `reset()`, `reset_launch()`, queries and explicit close. Include initialization, cache flushing, stepping and before-release observations. Only complete disposal permits a new lifetime. |
| Memory callbacks | Before any mutation, bound cumulative reads/writes and pending reads by `E`; reject a response at pending zero; justify pending resets by quiescence. Cover callbacks outside the kernel run loop. |
| Readout and growth | Inventory every increment and aggregate addition, derive conservative rates from actual compiled dimensions, and evaluate bounds with checked arithmetic. |
| Guard failure | Use the processor-origin terminal path, require repeated public wait/query failure and suppress later work. Invalidate the entire attempt even when a prime or excluded warm-up trips the guard. |

If pending reads are bounded by `E` and
[memory latency](../../sim/simx/processor.cpp) adds that quantity at most once
per charged tick, then
`memory_lt <= T * E = (2^32 - 1)^2 = 2^64 - 2^33 + 1 < 2^64`.
This candidate argument requires proof of the unique accumulation sites and
checked pending bookkeeping; a tick ceiling alone does not bound latency.
For every other required value, independently prove zero origin and
`C_j(t) <= R_j * t`, including all summed objects, with
`R_j <= (2^64 - 1) / T`. Do not perform an overflowing multiplication to check
that inequality.

The updater review must close the full call graph, including retirement's
per-FU gather path, simultaneous cache admission/pipe misses, nested dirty-sector
flush walks, local-memory/coalescer aggregation, memory crossbar collisions and
TCU-buffer backing sums. One increment per port, instruction or bank cannot be
assumed from names or comments. Each object must tick at most once per charged
platform tick; every out-of-tick update must have a directly proved bound.
Resetting required counters or saturating without failure would change their
semantics. If complete rate proofs cannot be closed, the wider alternative is
checked arithmetic before every relevant increment and aggregate addition.
Snapshot-only overflow checks are insufficient.

Require tests below, at and beyond lifetime/request limits; successive
individually short launches crossing the cumulative limit; pending underflow;
flush/close coverage; and actual updater/aggregate boundaries. Keep test-only
seeds or tiny guard limits out of the measurement binary. Reject unsupported
topology, worker count, features or guard configuration. No environment opt-out
or caller assertion may bypass enforcement.

## Smallest useful native diagnostic matrix

Freeze the additional diagnostic matrix before collecting performance results.
Each cell uses the exact supported warm configuration and retains its own
execution scope:

| Diagnostic | Minimum scope | Pass/fail boundary |
|---|---|---|
| Actual selector transport | All 33 rows against each distinct FP16/BF16-bound timing SimX backend artifact | Reuse all ten frozen SimX vectors at each actual backing source. Verify both halves and reconstruction, repeat and alternate unequal classes/selectors, including values above bit 43. Missing, wrong, stale or truncated replies fail. |
| Public snapshot coherence | FP16/BF16 × both policies: four processes, each one prime plus 32 operations | 132 launches and 4,224 exact words. All four snapshot locations yield 16 snapshots, 528 enabled queries/1,056 half replies and 192 unavailable rows receiving no query. Prove ownership/quiescence through each pair, numerical correctness and complete cleanup. |
| Guard failure containment | Directed bound violations at the actual guarded model entry plus normal controls in the same configuration | Immediately failing and delayed tasks retain failure through waits/queries and queue-error consumption. No successful retirement, later work or qualified partial snapshot is accepted. Join/teardown remain required; failed-context reuse stays forbidden. |

Seed real backing counters with distinct nonconstant values through the actual
Processor → Cluster → Socket → Core → CSR route. A copied decoder, synthetic
selector array or zero-only TCU test cannot establish source selection. In
particular, [TcuUnit::perf_stats](../../sim/simx/tcu/tcu_unit.cpp) derives its
local-memory reads from the TCU buffer; assigning a temporary stats copy does
not exercise that source. SimX's 64-bit backing fields and RTL's 44-bit fields
remain separate scopes.

The candidate coherence argument uses the
[processor run loop](../../sim/simx/processor.cpp) finishing only when cores
stop and the platform is idle, synchronized
[backend DCR hooks](../../sw/runtime/simx/vortex.cpp), a DCR/CSR route that
does not tick the model, and the
[warm caller](../../tests/regression/ai_warm_workspace/main.cpp) explicitly
closing every operation before its snapshot. Bind serial CP ownership and the
absence of queued work capable of advancing the model through both reads.
The exact profile has `CP_ON_L2=CP_ON_L3=0`; broader LLC-client transfer routes
must not be silently included. If a required source can advance between halves,
require a separately reviewed coherent-read algorithm and adversarial rollover
tests. Repeated equality alone does not prove coherence.

These four public diagnostic processes do not replace the full warm matrix.
Controlled host faults, native selector checks, actual public execution and
static maximum-rate proofs have different scopes. General internal-worker
exception transport, fatal-abort recovery, simultaneous contexts and forced
cancellation remain outside this qualification route.

## New qualification binding and replay

Use a separately named versioned record and execution binding, retaining the
unchanged measurement-contract digest. Derive qualification from verified
evidence. The existing `qualification_id` is an execution-binding digest, not
proof of counter qualification. Keep pre-execution identities distinct from
final archive identities to avoid circular bindings.

In addition to the source/configuration/tool/binary requirements above, bind
the reviewed 33-selector inventory, true backing sources, widths, availability,
coherence proof, complete lifetime/updater proof, guard constants and supported
execution route. Include scope-matched transport/completion records and the
actual executing interpreter. Require identical guarded binaries across both
policies within each format and before/after stability observations.

The qualification digest must be bound before each fresh process launches.
The final verification result joins that digest to the original command/log/
resource packet and all 24 completed processes. Reject disabled guards, invalid
epochs, false coherence/bound claims, guard trips, incomplete close/cleanup and
mismatched source/configuration/selector/compiler/tool/binary/attempt identities.
Test invalid qualification with favorable and unfavorable statistics.
Rehashing inconsistent records must not make them valid; attaching new metadata
cannot qualify a historical archive. Retained helpers are data, never trusted
code to execute. Independent enforcement review precedes fresh performance.

## Fresh matched attempt

After the qualification prerequisites pass, use the unchanged warm workload,
timing interval, allocation observer, poison schedule, policy order and sample
populations. Run FP16 then BF16, six ordered policy pairs per format, one prime
plus 32 serial operations per process: **24 processes, 792 launches and 25,344
exact FP32 output words**, including excluded primes and warm-ups. Both policies
use the same clean source and guarded executable per format. Retain all data:

| Disjoint operation population | Launches | Exact FP32 output words | Statistical role |
|---|---:|---:|---|
| Non-prime operations in measured processes | 640 | 20,480 | Measured intervals |
| Primes in measured processes | 20 | 640 | Excluded, retained |
| Non-prime operations in warm-up processes | 128 | 4,096 | Excluded, retained |
| Primes in warm-up processes | 4 | 128 | Excluded, retained |
| **Complete 24-process attempt** | **792** | **25,344** | All correctness/provenance checked |

The 24 primes and 128 non-prime warm-up operations are disjoint. Counting all
warm-up operations again would double-count the four warm-up primes.

Keep the five measured batch means per format/policy and all three original
predicates: candidate median at most 95% of reference in each format, no slower
measured host pair, and no increased measured paired active-cycle delta. Use
exact comparisons. No replacement samples, optional stopping, outlier removal
or observer-overhead subtraction is permitted. An incomplete attempt is invalid;
a fully qualified valid failure to improve remains a retained negative result.

Preserve the existing two-job, 4 GiB polled RSS, 15 GiB free-disk, 16 MiB log,
1,800-second build, 180-second invocation and 90-minute hosted-job limits.
Report instrumented host time and scoped modeled counters; this experiment
does not establish physical speed, energy or whole-GPU fit.

P06-A02/A03 require their own reviewed acceptance. Vendor P01-A03, P05-A02/A03,
the inherited 267 → 283 DSP finding against the unchanged 5% threshold,
physical FPGA and silicon obligations remain separate. Preserve all original acceptance records and unavailable evidence.
