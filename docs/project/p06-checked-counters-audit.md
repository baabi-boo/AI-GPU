# P06 checked counter development audit

## Outcome and next dependency

The selected development step is implemented and published: opt-in checked
arithmetic at the SimX counter storage and aggregation sites used by the P06
warm experiment, typed failure through the existing completion boundary, and
a source-bound native validation runner. The hosted directed run passed all
five cells at `9fd7eac203c77fa54c7af80fa0220ae09553cd55`. This establishes a
bounded counter prerequisite; `qualified`, `ready_for_warm` and
`full_warm_coverage` remain false.

The next dependency is to close aggregate lifetime and terminal-observation
proof, complete transport coverage for the fourteen remaining available
selectors, and bind actual native public-runtime diagnostics into a new
qualification reader. The [implemented contract](../designs/simx_checked_counters_v1.md),
[qualification plan](p06-mpm-qualification-plan.md) and
[evidence index](evidence/p06-checked-counters/README.md) separate those
obligations from the completed guard and directed execution.

## Starting point and selection rationale

This continuation starts at `42809ff0c1b81384d7c9b079e4ef786be8407600`
on `master`. The host MPM transport repair was present, while the historical
warm-v1 analyzer deliberately rejected full qualification. Source audits
identified 33 available counters and twelve unavailable L2/L3 rows in the
frozen RV64 `p02-tfr` experiment. The available counters retain cumulative
statistics across launches. Repairing high-word transport cannot establish
that the stored statistics, their contributing counts or their aggregate
sums never overflow. A timeout, small reported value or sampled monotonic
sequence does not establish an absolute lifetime bound.

The audit therefore selected checked arithmetic as an implementable
prerequisite before interpreting a fresh warm experiment. A lifetime tick cap
was considered but would additionally require independently justified event
rates, occupancies and a count that survives platform resets. The guard
instead provides a local, reviewable invariant at every covered operation.

| Audit finding | Implemented decision | Remaining limit |
|---|---|---|
| Cumulative unsigned storage can wrap | Guard source additions and increments before mutation in an explicitly instrumented build | Every relevant update and reset still needs exact-source review |
| Derived totals can exceed the range while components individually fit | Use checked cache, coalescer and TCU aggregation, including their contributing storage | A sum is checked when formed; a complete lifetime proof must cover intervals between observations |
| Pending-read underflow can corrupt accumulated latency | Check request increments and response decrements of the contributing pending balance | The native underflow diagnostic currently exercises the primitive, not an injected private Processor response |
| Completion behavior changed concurrently | Integrate upstream completion repairs and throw a typed counter exception through the supported boundary | Native public fault propagation remains distinct from controlled public-runtime tests |
| PATH Python can differ from the actual executing interpreter | Record `sys.executable` independently and check its identity before and after execution | This establishes interpreter identity, not native execution by itself |
| Earlier transport coverage does not establish the full warm profile | Add a native ordinary/checked matrix with explicit seeded and unseeded inventories | Nineteen selectors are seeded; fourteen available selectors remain unseeded |

## Implemented scope

`SIMX_CHECKED_COUNTERS=1` selects an eight-byte, trivially copyable checked
accumulator. With the option undefined, `vortex::PerfCounter` remains exactly
`uint64_t`. Checked construction, assignment and deltas reject negative
integral operands; addition, subtraction and increment/decrement reject an
out-of-range result before modifying the affected value. Direct binary
addition/subtraction involving the checked type is deleted, so covered sums
use checked accumulation. For `U = UINT64_MAX`, successful addition requires
`delta <= U - value`, and successful subtraction requires `delta <= value`.

The final implementation throws `PerfCounterError` with a typed overflow,
underflow or negative-operand reason and a static diagnostic. The supported
`Processor::run_checked()` and `AsyncRun::invoke()` boundaries preserve
terminal failure, suppress later work and join execution during destruction.
The legacy catch-and-return `Processor::run()` route is outside this contract.
The static diagnostic avoids constructing a dynamic message; it is not a
claim that the C++ exception runtime allocates no storage.

| Covered warm sources | Selectors | Integration |
|---|---:|---|
| Core and LSU | 13 | Actual `Core::PerfStats` storage and source updates |
| I-cache and D-cache | 9 | Actual cache storage and bank/cache-cluster reductions |
| Local memory | 3 | Actual `LocalMem::PerfStats` storage |
| Coalescer | 1 | Actual miss storage and the checked CSR sum |
| Global memory | 4 | Processor read/write/latency storage, contributing pending balance, and actual crossbar collision source |
| TCU | 3 | Stall/hit storage, private buffer read counts and their checked sum |

Additional fields in these structures acquire the checked type without
expanding the reviewed 33-selector contract. The declared route remains
serial RV64 `p02-tfr` timing SimX, `PERF=1`, one cluster/core/socket, four
warps, four threads and issue width one, with STD scalar and TFR tensor
arithmetic. The twelve unavailable L2/L3 rows remain unavailable. In
particular, `memory_lt` retains its existing pending-occupancy accumulation
in run/cycle entry points; separate flush and CP-transfer tick loops do not
all add to that counter.

The new [native runner](../../ci/project/p06_checked_execute.py),
[build fragment](../../sim/simx/checked_counters.mk) and
[workflow](../../.github/workflows/p06-checked-counters.yml) require fresh
ordinary and checked builds, clean expected source, per-translation-unit
compiler records, generated configuration, binary identities, retained logs,
and source/tool stability checks. The transport runner also records the
actual executing interpreter independently of PATH Python. Resource limits
remain 15 GiB free disk, 4 GiB RSS, two build jobs, 16 MiB per log, 120 seconds
for configure, 1,800 seconds for build, 180 seconds per run, and a 90-minute
hosted job. The workflow uses read-only permissions and restore-only caches.

## Integrated upstream work and review decisions

While this audit was active, `master` advanced through the simulator completion
repair, its CP error-origin correction and source-bound evidence to
`89aa43236038fcfff5d36a7cdb95646b038fe2fb`. These changes were fast-forwarded
before implementation continued. The original future-wait exception finding
is historical: the integrated route consumes futures with `get()` and retains
processor failure. That concurrent work is preserved in both published
checkpoints below.

The [completion-alignment review](evidence/p06-checked-counters/reviews/completion-alignment-review.md)
rejected the initial fatal-abort candidate because it bypassed persistent
public failure and full-platform cleanup. Its F2 finding was addressed by
the typed guard and existing completion route; its stale asynchronous-failure
rationale was corrected. Earlier abort-oriented probes and the historical
primitive review apply only to the discarded candidate.

Subsequent independent [source reviews](evidence/p06-checked-counters/reviews/source-proof-review.md)
covered the guard and all 33 selected source routes, and
[execution-path reviews](evidence/p06-checked-counters/reviews/execution-path-review.md)
covered the runner, native harness and host checks. The
[integrated R3 review](evidence/p06-checked-counters/reviews/integrated-review.md)
recommended landing the bounded implementation and CI-enabling checkpoint
with no open F2/F3 finding in its reviewed scope. The later controlled public
tests received their own [independent review](evidence/p06-checked-counters/reviews/public-fault-review.md).
Those reviews retain their actual source and execution boundaries. Wave 9's
[independent original-packet review](evidence/p06-checked-counters/reviews/native-review.md)
then verified the hosted behavior and source/build bindings directly from the
original ZIP and Git source, with no F1/F2/F3 finding in either assigned scope.
That review supports the bounded prerequisite result and preserves every
qualification limit below.

## Actual execution evidence

### Host governance and focused checks

The final implementation's [hosted governance receipt](evidence/p06-checked-counters/hosted/governance-index.json)
records **3,062 tests in 1,295.925 seconds, OK**, at actual published
`9fd7eac203c77fa54c7af80fa0220ae09553cd55`, run `45017731138`, attempt 1,
job `137193572417`. The [independent review](evidence/p06-checked-counters/reviews/hosted-governance-review.md)
reconciles 3,062 unique test entries with no failures/errors/skips and successful
job cleanup. The exact decoded original log is retained, including its BOM
and final newline: 638,690 bytes, SHA-256
`539713f1a68140cec166562eb0087d6b8cf4c3a62af564e9d0fa57f558ef7042`.
System CPython 3.12.3 executed governance; the native workflow's CPython 3.12.14
is a separate interpreter identity. This hosted source binding uses checkout,
preflight and the original log, without claiming a separate after-suite inventory.

The retained [governance packet](evidence/p06-checked-counters/local/governance-53f4ad08c/index.json)
records a clean execution at local commit
`53f4ad08c469a1cc73fa604249b302f9416055e0`, tree
`80553bb237af44b187dd6d18178e851cd6671ec8`. The command
`python3 -m unittest discover -s ci/project -p 'test_*.py' -v` passed
**3,043 tests in 1,647.227 seconds**. The bounded process exited zero with
cleanup complete; its elapsed duration was 1,648.962310 seconds and highest
sampled RSS was 326,823,936 bytes. Source and actual interpreter identities
were unchanged. The source inventory's uninitialized-submodule blockers
apply to native prerequisites; they do not turn this host-governance run into
a native build or invalidate its host result.

The focused checks comprise 64 newly added methods: twelve primitive, six
production-header integration, 27 runner enforcement, fourteen workflow, and
five controlled public-runtime methods. Five additional interpreter-identity
methods were added separately to the existing transport tests. The fourteen
workflow and five public methods were added after the immutable 3,043-test
run and have separate focused results; they must not be reported as members
of that completed full-suite execution.

The five controlled public methods cover ten RAM/LLC cells, compiling the
actual common runtime, CP and SimX backend with `-O2`, `NDEBUG` and UBSan
against controlled Processor/RAM implementations. They cover normal execution,
asynchronous overflow/underflow/negative-operand faults and synchronous MPM
query aggregation failure, including unchanged output on rejection, repeated
waits, sticky failure, suppression of later work, cleanup and a fresh context.
The query aggregate is a local checked addition at the controlled Processor
DCR hook; it does not exercise the real cache/TCU backing source.

### Hosted native prerequisite

[GitHub Actions run 45017731063](https://github.com/baabi-boo/AI-GPU/actions/runs/45017731063),
attempt 1, completed successfully at actual source
`9fd7eac203c77fa54c7af80fa0220ae09553cd55`. The original
[artifact ZIP](evidence/p06-checked-counters/native/run-45017731063-attempt1.zip)
and [report copy](evidence/p06-checked-counters/native/report-45017731063.json)
are retained. Artifact `14753040127` contains 317 ZIP entries and is
1,119,268 bytes; its SHA-256 is
`66dd0db69db3fb0d22f975c8d67cea8f445aa40a3f1ac0fbb0d5b20529aa9b40`.
The original report records 44 actual compiled translation units in each
ordinary/checked build and passing outcomes for these five cells:

| Cell | Observed result and scope |
|---|---|
| `ordinary-boundaries` | PASS: nineteen selectors, ten vectors each, 760 half reads and 2,749 checks |
| `checked-boundaries` | PASS: the same directed inventory and counts, with ordinary/checked observations equal |
| `checked-core-overflow` | PASS: actual `Core::tick` failure through `run_checked()` and `AsyncRun`, unchanged protected value, eight sticky-failure checks, two suppressed tasks, joining and successful execution after full failed-context destruction |
| `checked-cache-aggregate-overflow` | PASS: production cache-statistics aggregation rejects overflow without changing the protected value or source |
| `checked-pending-underflow` | PASS: pending-counter primitive rejects underflow before mutation; this is not a private Processor request/response injection |

The inventory is **nineteen seeded, fourteen available but unseeded, and
twelve unavailable**. The report explicitly records
`native_prerequisites_passed=true`, `qualified=false`, `ready_for_warm=false`,
`full_warm_coverage=false`, `warm_execution=false` and
`acceptance_claimed=false`. Neither the native Core failure nor the controlled
public tests constitute an actual native public-runtime fault experiment.

### Local native limits and build dry run

The original [local native preflight](evidence/p06-checked-counters/local/native-preflight-53f4ad08c.json)
was blocked with 4,310,839,296 free bytes, below the preserved 15 GiB reserve,
and started zero subprocess commands. The hosted pass does not relabel that
local result. The separately retained [dry-run packet](evidence/p06-checked-counters/local/dry-run/README.md)
contains actual configure, stamp and `make -n` output: 44 prospective compile
commands and one link per mode, with mocked object identities. It performed
zero C++ compilation, linking or native execution. Header/configuration hashes
added during packet assembly are identified as later captures.

## Publication identities

CLI publication lacked write credentials. The authorized GitHub Git Data API
published the reviewed trees after checking the expected previous `master`
head, with a non-force reference update. The
[publication map](evidence/p06-checked-counters/publication.json) retains both
local and published commit identities:

| Checkpoint | Local commit | Published commit | Identical repository tree |
|---|---|---|---|
| Guard, runner and initial verification checkpoint | `53f4ad08c469a1cc73fa604249b302f9416055e0` | `a9227933c340fd44e73deaffafdd353fecf65492` | `80553bb237af44b187dd6d18178e851cd6671ec8` |
| Controlled public tests and follow-up evidence | `713e05d99f8b37d4370f7607d1f8129d40cde73b` | `9fd7eac203c77fa54c7af80fa0220ae09553cd55` | `973fa9a286686990c96d10f95ab2e77ed6328f1a` |

The published parent chain is `89aa4323` → `a9227933` → `9fd7eac2`.
Local history is preserved as `audit/local-checked-counters-713e05d99`.
Identical trees establish identical repository file bytes, not identical
commit metadata or a new execution. The 3,043-test run therefore remains
attributed to local `53f4ad08c`, while the hosted native run is attributed to
published `9fd7eac2`.

## Remaining development lead: terminal aggregate proof

The guard bounds each covered stored component and every aggregate when it
is formed. Independently growing components can still have a mathematical
sum above `U` before any query, despite each component fitting. Successful
process exit alone cannot close that gap. In the exact profile, the D-cache
has two contributing banks and is the active multi-component concern. Core
fields, the one-bank I-cache, shared local-memory statistics, one LSU
coalescer and Processor memory fields have narrower fan-in. The ordinary
profile disables WGMMA producers for the relevant TCU buffer paths; naturally
zero counters remain available and still require real high-word transport
coverage.

The strongest next lead is the existing `before_release` observation after
operations are waited and closed, queue workers joined, and resident buffers,
kernel and module ownership released, immediately before actual device
release. If every component is monotonic from zero and a complete terminal
checked observation establishes `A(T) <= U`, then every earlier aggregate
satisfies `A(t) <= A(T)`. This argument additionally requires exact-source
proof that no later update occurs through relevant teardown. It depends on
one exclusive serial owner, no surviving queue worker or external Device
retain, no legacy/debug submitter, VM and CP-on-L2/L3 disabled, and successful
queries of all 33 available rows with the twelve unavailable rows skipped.

| Proof boundary found by the audit | Obligation before claiming terminal lifetime closure |
|---|---|
| `Device::cp_quiesce_()` returns void on errors or exhausted polls; CP `busy()` is gated by enable state | Disabling queue control can make BUSY false while work is pending. Establish actual drain and successful completion rather than treating disabled BUSY as a drain certificate |
| `vx_device_release()` success decrements a reference count | Prove exclusive ownership and actual destruction; successful release alone does not certify destruction |
| Low/high MPM reads are separate DCR commands, and `Q_LAST_DCR_RSP` is read outside the submit/poll lock | Bind exclusive query/response ownership so no concurrent submitter can replace the response |
| Platform cleanup discards queued events, but Memory destruction invokes the configured DRAM backend's finalization | Bind the selected backend and dependency revision, inspect Ramulator finalization and callback behavior, and prove no later relevant counter update; do not generalize event discard into an all-teardown claim |

These are future qualification proof obligations, not newly introduced
counter defects or fixes implemented by this checkpoint. The next bounded
development should:

1. Establish the terminal-observation proof or add an independently reviewed
   mechanism that enforces the aggregate bound during updates.
2. Seed the fourteen missing real backing sources: three I-cache, six D-cache,
   four global-memory and `tcu_lmem_reads`; then exercise native public snapshot
   coherence and fault containment at the exact declared configuration.
3. Add the strict versioned qualification reader and inert replay with original
   source/configuration/compiler/binary/cleanup bindings. Invalid evidence must
   reject both favorable and unfavorable performance conclusions. Only after
   these prerequisites pass should a fresh complete warm matrix be interpreted.

## Preserved acceptance boundaries

This work changes no RTL, public ABI, CSR/DCR encoding, modeled scheduling,
event order or numerical datapath. Checked mode adds host execution cost;
both policies in a future matched experiment must use the same identified
instrumented binary. It supplies no uninstrumented speedup claim.

The frozen workloads, reference fixtures, statistical predicates, budgets,
goldens and acceptance records remain intact. The future warm matrix remains
24 processes, 792 launches and 25,344 exact FP32 output words under its
existing policy. Historical warm v1 retains
`P06-WARM-RV64-MPM-HIGH-HALF`, `qualified=false` and
`absolute_no_wrap_bound="not_established"`; new code cannot recover missing
historical high bits. P06/T01 remains in progress and P06-A02/A03 remain open.
The inherited tensor 267-to-283 DSP failure, P01 vendor XRT `hw_emu`, P05
framework obligations and physical FPGA/silicon gates are unchanged. No phase
closure or performance acceptance follows from this bounded implementation.
