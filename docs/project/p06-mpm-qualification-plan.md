# P06 counter qualification plan

## Decision and current boundary

**Next bounded development: close and independently review the terminal
snapshot/lifetime argument for the exact 33-selector RV64 `p02-tfr`, timing
SimX, `PERF=1` route; complete the remaining native selector and public-failure
diagnostics; then implement a separately versioned qualification reader.**
The [checked-counter prerequisite](../designs/simx_checked_counters_v1.md) is now
implemented. It guards audited stored updates and formed aggregates, but does
not itself establish a complete context-lifetime bound, all-33 native transport,
coherent public snapshots or warm readiness. The qualification record/reader
and fresh complete matched warm attempt remain future work.

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

## Implemented checked-counter prerequisite

The [development audit](p06-checked-counters-audit.md) selected checked
arithmetic after source review of all 33 available counter paths. Published
checkpoint [9fd7eac20](https://github.com/baabi-boo/AI-GPU/commit/9fd7eac203c77fa54c7af80fa0220ae09553cd55)
contains the opt-in guard, model integration, directed native runner and host
tests. The original reviewed local implementation checkpoint `53f4ad08c` and
published parent `a9227933c` have the same file tree; their commit identities
remain distinct. Keep every execution receipt attached to its actual original
source, rather than relabeling a local run as a published-commit execution.
The immutable local governance suite passed 3,043 tests at `53f4ad08c`.
The later [hosted governance receipt](evidence/p06-checked-counters/hosted/governance-index.json)
records a distinct **3,062-test pass** at actual published `9fd7eac20`, run
`45017731138`, attempt 1. Independent original-log review establishes that
later count without relabeling or adding earlier executions.

`SIMX_CHECKED_COUNTERS=1` selects checked counter storage and accumulation;
ordinary builds retain the exact `uint64_t` alias. Overflow, underflow and
negative operands throw `PerfCounterError` before the rejected primitive
changes. The processor completion owner makes those failures terminal. An
aggregate may have earlier successful member updates before a later member
throws; failed-context reuse and publication of a partial snapshot remain
forbidden.

| Implemented verification | Established scope | Remaining boundary |
|---|---|---|
| [Primitive tests](../../ci/project/test_p06_checked_counter.py) | Release arithmetic, typed failure, unchanged rejected values, ordinary compatibility and actual `AsyncRun` containment | No native processor or public-runtime execution |
| [Production-header tests](../../ci/project/test_p06_checked_integration.py) | Actual counter field types/layouts and aggregate operators | Syntax/header checks do not link or run the model |
| [Controlled public-fault tests](../../ci/project/test_p06_checked_public.py) | Actual runtime, CP, backend, events, queries and cleanup with real counter exceptions | Processor/RAM are controlled substitutes; no native backing-source fault injection |
| [Native runner](../../ci/project/p06_checked_execute.py) and [workflow](../../.github/workflows/p06-checked-counters.yml) | Actual fresh ordinary/checked builds and all five cells pass at `9fd7eac…`; independent original-packet review confirms source/build/command bindings | Nineteen seeded selectors; no complete lifetime or native public-runtime qualification |

Dedicated [run 45017731063, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45017731063)
at `9fd7eac20` **passed all five native cells**. The
[independent original-packet review](evidence/p06-checked-counters/reviews/native-review.md)
confirms behavior and exact source/build bindings, including 264 retained
source files and 44 compiled translation units plus one link in each mode.
The [evidence index](evidence/p06-checked-counters/README.md) retains the original
receipts and review limits. The successful prerequisite keeps `qualified=false`,
`ready_for_warm=false`, `full_warm_coverage=false` and `warm_execution=false`.
The local 15 GiB disk block remains a separate blocked result, not an executed
native control.

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
subsequent CP error-boundary repair at `4781ca9` has separate source-bound
receipts. Use the index's receipts and independent review to assess that
repair; do not relabel the initial packet as later-code evidence. The implemented
counter guard uses this processor-failure path. Its controlled public tests
exercise persistent waits/query rejection; native public counter-fault execution
remains a separate obligation. Host injection does not establish native public
fault or RTL execution. Preserve the 15 GiB native disk reserve.

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

The new [checked-counter harness](../../tests/unittest/checked_counters/main.cpp)
is built in the actual RV64 `p02-tfr`, PERF-enabled timing configuration. Its
directed transport matrix seeds **19 available selectors**: thirteen Core/base,
three local-memory, one coalescer and two TCU fields. Each receives ten vectors,
with both half-read orders, for 760 half reads and 2,749 assertions per boundary
cell. These are declared harness obligations; an actual execution result must
come from its source-bound packet.

The **14 remaining available sources** are nine I/D-cache selectors, global
memory reads/writes/latency/bank stalls, and private TCU-buffer local-memory
reads. They are explicitly unseeded. The twelve unavailable L2/L3 rows receive
no query. Neither naturally zero TCU values nor the nineteen seeded sources
establish all-33 transport coverage.

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
   counter selectors used by the warm experiment. The earlier transport tests
   use a TCU-disabled configuration; the new harness selects the warm profile
   but still leaves fourteen sources unseeded. Complete actual backing-source
   coverage for every required available selector before claiming all-33
   transport. Preserve architectural CSR semantics and public ABI.
2. **Bind evidence to execution.** Define a new versioned qualification record
   that binds reviewed transport evidence and its scope to the complete source
   revision/tree, relevant source bodies, generated configuration, original
   compiler/linker records, tools/dependencies and actual host/runtime/kernel
   binary identities. The [standalone interpreter finding](evidence/p06-mpm-transport/reviews/enforcement-review.md)
   is addressed by separately recording the actual executing interpreter and
   PATH `python3`; consume and verify both identities in the new qualification
   binding. The hosted workflow requires their equality. Require identical
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
   Guarded components and formed reads are implemented; the complete aggregate
   lifetime argument below remains to be closed. Observed monotonicity, small
   reported values, a process timeout or guessed event rates cannot substitute
   for source-proved monotonicity and complete lifetime coverage. Missing bounds
   remain blocked.
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

## Implemented arithmetic guard and prospective lifetime closure

The [guard contract](../designs/simx_checked_counters_v1.md) establishes a
per-operation invariant: each audited stored component remains in
`[0, UINT64_MAX]`, and each formed aggregate either returns the exact value in
that range or throws before an overflowing addition. It preserves cumulative
statistics across launches and checks pending-read subtraction too. A successful
process alone does not continuously bound a mathematical sum of independently
growing components between its observations.

The [profile](../../profiles/p02-tfr.json), expanded
[configuration](../../VX_config.toml),
[LSU/cache formulas](../../sim/simx/constants.h),
[socket construction](../../sim/simx/socket.cpp) and
[tensor-buffer construction](../../sim/simx/tcu/tcu_tbuf.cpp) give these exact
aggregation boundaries:

| Required selectors | Count | Components per published value in the selected route |
|---|---:|---|
| Core/base | 13 | One checked Core field |
| I-cache | 3 | One cache with one bank |
| D-cache | 6 | One cache with **two independent bank counters** |
| Local memory | 3 | One shared stats object, despite four physical banks |
| Coalescer misses | 1 | One coalescer/LSU block |
| Global memory reads, writes, latency | 3 | One Processor field each |
| Global memory bank stalls | 1 | One crossbar collision accumulator |
| TCU buffer stalls and cache hits | 2 | One TCU field each; zero with WGMMA disabled |
| TCU local-memory reads | 1 | Two private buffer sources; zero with WGMMA disabled |
| **Available total** | **33** | Twelve unavailable L2/L3 rows remain unqueried |

Four RV64 LSU lanes cover 32 bytes; the 16-byte D-cache word yields two
coalesced channels and two D-cache banks. The six active D-cache sums are the
nontrivial aggregate-lifetime obligation. The TCU-buffer sources remain zero
on ordinary execution of this WGMMA-disabled route, but remain available and
still require distinct transport evidence. These formulas must be checked
against actual generated configuration, not inferred from a profile name.

### Candidate terminal-observation proof

**Recommended next proof, not an established native qualification:** retain the
existing `before_release` observation and prove that it is terminal for all
required backing sources. For nonnegative, monotonic components `c_i(t)`, a
successful checked read at terminal time `T` gives
`sum(c_i(T)) <= UINT64_MAX`; therefore every earlier sum is no larger. Proving
that no component can increase after `T` extends the bound through disposal.
This combines guarded source updates, source-proved monotonicity and complete
terminal readout; snapshot-only overflow checks or sampled monotonicity do not
supply those premises.

The current [warm caller](../../tests/regression/ai_warm_workspace/main.cpp)
waits, closes and destroys each operation before its post-operation snapshot.
[Queue destruction](../../sw/runtime/common/queue.cpp) joins the worker.
[Owner release](../../sw/runtime/ai/runtime.cpp) frees resident buffers, kernel
and module before the wrapped device release. The
[observer](../../tests/regression/ai_warm_workspace/observer.cpp) takes all
available `before_release` queries immediately before the real device-release
call, while checking owner-close phase and zero observed live buffers. This
ordering supplies a promising proof location without changing timing intervals,
policy order or sample populations.

The proof and future reader must bind all of the following; none may be inferred
from a successful release return alone:

| Boundary | Required source proof and native observation |
|---|---|
| Origins and updates | Every contributing source starts at zero, survives the permitted resets monotonically and uses checked arithmetic; transient pending balance still needs matched requests/responses and quiescent reset. |
| Exact inventory | All 33 expected enabled rows are queried successfully and the twelve unavailable rows are not queried; validation of a dynamically enabled subset is insufficient. |
| Exclusive ownership | One context and one submitter; no surviving operation/queue worker, external Device retain or legacy/debug submitter can advance the model or replace a DCR reply. |
| Terminal readout | All operations and synchronous CP transactions have retired before the complete checked snapshot; both halves succeed and refer to one stable source value. |
| After the snapshot | VM is off, `CP_ON_L2=CP_ON_L3=0`, and no later launch, cache flush or model-ticking memory operation is submitted. Bound allocator release, CP bookkeeping, backend join and full platform disposal separately. |
| Dependency teardown | Bind the selected DRAM backend and dependency revision, including Ramulator frontend/memory-system finalization; inspect its callbacks and finalization contract. |
| Failure | Any guard/query/cleanup failure invalidates the attempt, including excluded primes or warm-ups. Retain terminal processor failure and prohibit failed-context reuse. |

Three concrete boundaries prevent overstating this argument:

- [`Device::cp_quiesce_()`](../../sw/runtime/common/device.cpp) returns no result
  and can stop on backend failure or exhausted polling. The functional
  [CP busy predicate](../../sim/common/cmd_processor.cpp) includes `enabled()`;
  disabling the queue can report not busy despite pending command state.
  Consequently, release success or not-busy-after-disable is **not a drain
  certificate**. `vx_device_release()` also reports release of a reference,
  not proof that this was the final reference that destroyed the Device.
- The [public MPM query](../../sw/runtime/common/perf.cpp) combines low/high
  values only after both reads succeed. However,
  [`cp_submit_dcr_read()`](../../sw/runtime/common/device.cpp) retrieves
  `Q_LAST_DCR_RSP` outside its submit/poll lock. The proof must exclude all
  concurrent submitters as well as concurrent counter updates; successful
  replies alone do not make this an atomic snapshot API.
- [Platform cleanup](../../sim/common/simobject.h) discards queued events,
  but the [DRAM adapter](../../sim/common/dram_sim.cpp) also calls Ramulator
  frontend and memory-system `finalize()` functions during destruction.
  Adapter responses normally reach GPU callbacks through a later drain/tick,
  but that does not replace inspection of the bound dependency's finalization
  behavior. No complete finalizer proof or native lifetime closure is claimed
  by this plan.

`memory_lt` retains its existing run/cycle accumulation meaning. Other flush or
CP-transfer loops can tick the platform without adding pending occupancy to
that counter. Qualification must preserve these event semantics rather than
reinterpreting it as an integral over all platform ticks.

### Earlier cap alternative

The earlier candidate proposed a context ledger with
`T = 2^32 - 1` charged ticks and memory-event caps `E = 2^32 - 1`. Those limits
are **not implemented** and are not the selected checked-counter contract.
They would additionally require complete event-rate, out-of-tick update,
ledger-reset and pending-occupancy proofs; active-core cycles omit idle work
and the platform clock resets on launch. A conservative per-component cap or
continuously maintained aggregate could be reconsidered if terminal closure
cannot be proved, but requires its own reviewed contract and tests. No guessed
rate, timeout, clamp, saturation or caller opt-out can substitute for a bound.

Keep test-only seeds or tiny guard limits out of the measurement binary. Require
actual updater/aggregate boundaries, pending underflow and flush/close coverage;
reject unsupported topology, worker count, features or guard configuration.

## Smallest useful native diagnostic matrix

The implemented native prerequisite has five cells: ordinary and checked
nineteen-selector boundaries, checked real-Core updater overflow/fresh-context
success, checked cache-aggregate overflow and checked pending-counter primitive
underflow. It does not replace the remaining matrix below. The controlled
public host tests similarly leave actual native public fault injection open.

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
source lifetime proofs have different scopes. General internal-worker
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
coherence proof, complete lifetime/updater proof, guard selection/width and
supported execution route. Bind terminal-observation coverage and all ownership,
post-observation and dependency-finalization premises used by the lifetime
proof. Include scope-matched transport/completion records and the actual
executing interpreter. Require identical guarded binaries across both
policies within each format and before/after stability observations.

The qualification digest must be bound before each fresh process launches.
The final verification result joins that digest to the original command/log/
resource packet and all 24 completed processes. Reject disabled guards, invalid
context ownership, missing terminal rows, false coherence/bound claims, guard
trips, incomplete close/cleanup and mismatched
source/configuration/selector/compiler/tool/binary/attempt identities.
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
