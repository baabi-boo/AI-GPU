# P06 counter qualification plan

## Decision and current boundary

**Next bounded development: add a read-only pending-read observation and a
separately versioned lifetime witness for all 33 managed run/reset pairs.**
Follow the [native handoff](p06-managed-preflight-handoff.md) for exact reset
accounting, flush and terminal balance, ownership and actual destruction
boundaries. This is the next implementation increment within the broader
qualification path below; fresh dependency compilation-to-loader provenance
and independent complete qualification remain separate requirements.

The [completed managed-preflight original](evidence/p06-managed-preflight-replay/README.md)
at `57248e73dfce4ae2d21d2cbdb82c3953eef2e3db`,
[run 45085300171, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45085300171),
records four seed-free processes, 132 launches and 4,224 exact output words.
The [complete inert reader](../designs/managed_counter_preflight_replay_v1.md)
now verifies that original against independent archive/source expectations.
It cannot supply the absent per-run pending-balance observations or prove that
the selected sources produced the cached dependency binaries. Preserve that
original version and scope; a fresh preflight must carry the new witness and
provenance evidence before it can satisfy the remaining qualification boundary.

The all-33 native model transport and directed public-runtime diagnostics have
a latest independently audited diagnostic
original pass at `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, separately repeating
the earlier corrected `e5f152464dda5e488d6d1a030c1fcdc49b5a9701` execution. The
[terminal lifetime argument](../designs/simx_counter_lifetime_v1.md) supplies a
conditional source proof for the exact 33-selector/40-component RV64
`p02-tfr`, timing SimX, `PERF=1` route. Applying it to measurement still requires
the full caller's ownership, reset and terminal observations, and provenance
from the actual loaded dependencies and binaries to the reviewed sources.

The [checked-counter prerequisite](../designs/simx_checked_counters_v1.md)
guards stored updates and formed aggregates. The
[model](../../ci/project/p06_counter_diagnostics_replay.py) and
[public](../../ci/project/p06_counter_public_replay.py) offline readers, plus
the [explicit source-inventory helper](../../ci/project/p06_counter_source_inventory.py),
are published at
[`4268d2d5d811063bb886cde7bd0e27e61a79c9b4`](https://github.com/baabi-boo/AI-GPU/commit/4268d2d5d811063bb886cde7bd0e27e61a79c9b4).
They check retained-data consistency and preserve diagnostic nonacceptance.
Those diagnostic readers and the complete managed-preflight consistency reader
retain their bounded scopes. Neither a complete counter-qualification route
nor a fresh complete matched warm attempt has been completed. The managed
preflight and its replay keep `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance` and
`performance_acceptance` false. Their three unresolved obligations remain
`all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance` and
`independent_complete_counter_qualification`.

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
high bits cannot be recovered from low words. Diagnostic and replay results
retain `qualified=false`, `ready_for_warm=false`, `warm_execution=false` and
`acceptance=false`. P06 and P06-T01 remain `in_progress`; P06-A02/A03 remain open.
P01-A03 remains blocked on vendor XRT `hw_emu`. P05 acceptance obligations and
the inherited tensor area finding remain separate, as recorded in the
[canonical roadmap](roadmap.json) and [current status](status.md).

## Completed diagnostic checkpoint and evidence limits

The [native index](evidence/p06-counter-diagnostics/native/index.json) preserves
the earlier corrected original from
[run 45031746149, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45031746149),
job `137236632765`, artifact `14758252829`, at source `e5f1524` and tree
`74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`. The retained
[original archive](evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip)
has SHA-256
`05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276`.

The latest independently audited original is
[run 45034575685, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685),
job `137245341329`, artifact `14760051170`, at source
`4268d2d5d811063bb886cde7bd0e27e61a79c9b4` and tree
`061ecbddc9b321edbd70c054c8efce4d188de04f`. Its retained
[archive](evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip)
has 4,290,949 bytes and 1,046 members, SHA-256
`6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb`.
The [independent original-packet audit](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit.md)
matches all 270 model and 683 public source bodies to immutable Git, reconciles
17 model/14 public commands and confirms the same thirteen passing diagnostic
process cases and public observation counts. Both inert replay routes pass;
public replay uses the explicit independently Git-pinned 683-source manifest.

| Completed evidence | Established scope | Remaining qualification boundary |
|---|---|---|
| Seven model cells | Ordinary/checked all-33 boundaries, Core updater overflow, cache aggregate overflow, pending primitive underflow, actual cache backing overflow and actual TCU backing overflow; each boundary has 6,389 assertions and 1,788 half reads across all 40 components | Seeded diagnostic storage and builds do not qualify a later seed-free measurement binary |
| Public build boundary control and five public modes | Normal, immediate/delayed overflow, cache overflow and coherent-terminal cases pass through actual Processor/RAM, runtime, CP and backend; the combined packet has 13 native test process cases | Directed scalar controls do not exercise the complete managed warm-workspace caller or its FP16/BF16 policy matrix |
| Public lifetime observations | Ten actual Processor constructions/disposals, seven complete terminal vectors, 231 selector queries, 462 successful native half reads and one additional failed cache half read | Each observation belongs to its original caller/context; seeded terminal values and fresh unseeded controls retain distinct scopes |
| Conditional lifetime source argument | Exact 33-selector/40-component inventory, monotone production updates/reset preservation, terminal checked sums and selected finalizer suffix | Actual loaded dependency provenance and every full warm-caller premise must still be established |
| Offline model/public replay and explicit source expectations | Current trusted readers validate original archives, raw observations, build/command bindings and complete source descriptors without executing retained code | A consistent archive is not proof of native execution, source-to-binary provenance, warm readiness or acceptance |

The [public diagnostic contract](../designs/simx_counter_public_diagnostics_v1.md)
defines these scenarios, their exact terminal/CP conditions and their replay
boundary. The earlier original at
`81ed6871634fefbf5c78fb27cf10dce913bd4d9c`, run `45029135146`, remains a
native failure: model cells and the public build control passed, public normal
failed, and four public modes were blocked. Its diagnostic incorrectly treated
unsupported host head writeback as an internal CP head. The corrected
observation contract does not change production CP behavior or relabel that
failed original. The earlier `407ab9f` pass remains model-only evidence.

The [host index](evidence/p06-counter-diagnostics/host/index.json) separately
retains the failed concurrent local run and the failed `81ed687` hosted suite.
The latter exposed the host's Python 3.12.3 observation through a controlled
fixture to the strict native interpreter validator; its repair isolates
synthetic observations and keeps the native CPython 3.12.14 pin. The clean
`e5f1524` hosted governance run `45031746158`, job `137236633104`, passed
**3,158 tests in 1,305.183 seconds**, with zero failures/errors. This full-suite
receipt excludes the later replay/source-inventory additions at `4268d2d5`;
their focused tests and independent review are separate evidence. The new
[completed hosted receipt](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/receipt.json)
for run `45034575638`, job `137245340992`, records **3,312 executed tests in
1,811.712 seconds: 3,310 `ok`, two `FAIL`, no errors or skips, exit 1**, on
Python 3.12.3. Independent original-log review matches all executed IDs to the
earlier discovery. Both failed test isolation guards reject the current trusted
helper when checkout and recorded producer pathnames coincide; those guards
did not complete, and this original remains failed. The
[independently reviewed test-only repair](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md)
is published at `142b2d6aaea2fa4226118b857514113032d2e26c`, tree
`754ef8577f9a72785c0809048762c70b16cb4857`, with both F2 findings closed.
Its 89 affected methods pass in 139.141 seconds; separate independent scopes
pass eight methods / 670 subtests in 4.956 seconds and three methods / 15
subtests in 4.437 seconds. The subsequent
[clean local full-suite receipt](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/receipt.json)
and [independent review](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/review.md)
record **all 3,318 tests passing in 1,918.414 seconds on CPython 3.12.14**, with
all four governance commands exiting 0. The detached source checkout is clean
before/after; all 365 source records match immutable `142b2d6` and remain
unchanged. Both formerly failed guards and all six new methods actually pass.
This is the completed local full-suite verification, separate from the focused
counts above. The [hosted retry](evidence/p06-counter-diagnostics/host/checkpoint-142b2d6/pending-receipt-20261122T165509Z.json)
`45040805357`, job `137264592244`, and native retry `45040805341`, job
`137264592580`, were queued at that retained receipt's checkpoint, with no
executed results in the receipt. The latest audited native diagnostic scope
stays at `4268d2d5`. None of these results changes production timing,
runtime/RTL semantics, public ABI,
goldens or tolerances.

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
exercise persistent waits/query rejection. The later original `e5f1524`
packet supplies separately scoped native public counter-fault execution as
described above; the older controlled tests are not relabeled as native
evidence. Neither establishes RTL execution or the complete warm caller's
lifetime. Preserve the 15 GiB native disk reserve.

## Exact route and completed selector coverage

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

The original checked-counter packet at `9fd7eac20` advanced that coverage to
**19 available selectors**: thirteen Core/base, three local-memory, one
coalescer and two TCU fields, with ten vectors and both half-read orders.
Its 760 half reads and 2,749 assertions per boundary cell remain the original
scope. Nine I/D-cache selectors, four global-memory selectors and private
TCU-buffer local-memory reads were then unseeded.

The current [model diagnostic contract](../designs/simx_counter_diagnostics_v2.md),
[harness](../../tests/unittest/checked_counters/main.cpp) and
[backing-source accessors](../../tests/unittest/checked_counters/counter_access.cpp)
close that fourteen-selector diagnostic gap. The latest audited `4268d2d5` original
seeds **all 33 available selectors and all 40 contributing components** through
the actual ownership/CSR route, including distinct banks and private TCU
buffers. Its ten-vector coverage, both half-read orders, repeated/interleaved
reads and high values produce 1,788 half reads and 6,389 assertions per model
boundary cell. The twelve unavailable L2/L3 rows remain unqueried. This is full
coverage of the declared SimX diagnostic inventory; it is not seed-free
workload qualification or coverage of a later FP16/BF16 measurement artifact.

`memory_bank_st` at class 7, CSR `0xB06`, has a
[SimX backing source](../../sim/simx/csr_unit.cpp) but no case in the
[RTL MEM decoder](../../hw/rtl/core/VX_csr_mpm.sv). A future all-33 SimX
qualification therefore cannot be called all-33 RTL parity. An RTL extension
requires its own separate implementation and evidence. Preserve the existing
[host MPM wire contract](../designs/host_mpm_transport_v1.md) and public ABI:
each available public read reconstructs two successful unsigned 32-bit replies;
the high-half selector is internal, not a second public CSR argument.

## Qualification work to implement and review

The sequence below describes the remaining qualification route. Its next
bounded implementation is the versioned boundary witness in the
[native handoff](p06-managed-preflight-handoff.md); the completed inert reader
does not promote the original preflight into that future qualification scope.

1. **Freeze a new qualification contract.** Specify its record, reader and
   explicit admission path separately from warm-v1 and the diagnostic replay
   contracts. Preserve the measurement-contract digest and every workload,
   timing, population and statistical rule below. Require the exact generated
   RV64 `p02-tfr` timing configuration, 33 available/12 unavailable selectors,
   all 40 backing components, one worker and exclusive submission. Name the
   exact diagnostic originals and lifetime source premises that it consumes;
   their passing outcomes are prerequisites, not an acceptance flag to reuse.
2. **Bind actual seed-free binaries and loaded dependencies.** Retain the
   complete source revision/tree, relevant transitive source bodies, generated
   configuration, original compiler/linker records, tool identities and actual
   host/runtime/kernel and loaded-library bytes or independently verifiable
   payload attestations. Demonstrate that measurement builds enable the checked
   guard consistently and contain no test seeding/accessors, diagnostic object
   substitutions or tiny guard limits. Bind the actual Ramulator artifact to
   the pinned selected source graph and its build, rather than treating a
   cached-library hash as compilation provenance. Independently review any
   source projection from diagnostic/proof revisions to the measurement tree.
   Require identical guarded binaries across both policies within each format
   and before/after stability. Consume both the actual executing interpreter
   and PATH `python3` identities, preserving the equality rule and the
   [standalone interpreter finding](evidence/p06-mpm-transport/reviews/enforcement-review.md).
3. **Apply the lifetime proof to the complete managed caller.** Bind zero
   origins, every admitted updater and reset, all initialization/prime/warm-up/
   measured operations, downloads/flushes and final cleanup. At the existing
   `before_release` boundary, establish actual queue-worker joins, final owner
   references, enabled-CP retirement and absence of concurrent submissions.
   Validate all 33 successful checked aggregates and both raw half replies;
   require the twelve unavailable rows to remain unqueried. Prove that every
   selected component is stable through the readout and until destruction,
   with no future event delivery, launch reset, flush, storage replacement or
   finalizer adjustment. The proof must cover the whole storage lifetime;
   observed monotonicity, small values and process timeouts are insufficient.
4. **Implement pure qualification validation.** Extend the reviewed complete
   managed-preflight consistency relationships with the separately versioned
   lifetime and provenance requirements. Bind pre-execution expectations
   separately from final archive identities, then join each process's original
   commands, raw observations, resource records and terminal result. Use the
   reviewed diagnostic readers as scoped inputs while retaining their
   `retained-data-consistency-only` result. The new contract must supply its own
   complete warm-caller/build/dependency closure; the diagnostic source manifest
   does not silently expand to cover it. Do not execute retained helpers or
   resolve recorded producer paths on the replay host. Explicit version and
   source-manifest selection must fail closed without fallback or a new live
   source glob.
5. **Exercise and independently review rejection.** Reject old, absent,
   unsupported, truncated, source/configuration/binary-mismatched or unreviewed
   inputs; disabled guards; seeded measurement builds; wrong/partial selector
   inventories; unsafe ownership/reset/CP/finalizer conditions; any guard or
   query error; incomplete cleanup; and changed process populations. Include
   consistent rehashing, copied diagnostic success and favorable/unfavorable
   statistics among invalid inputs. Require review by an agent that did not
   author the enforcement change under the
   [review policy](../review/code-review-policy.md), before fresh performance
   results are inspected.
6. **Run a fresh preflight carrying the new witness and provenance.** The
   original four-process preflight and its consistency replay are complete;
   they do not contain the missing observations. Once the new contract,
   validation and provenance requirements are independently reviewed, repeat
   the four-process FP16/BF16 × policy matrix below with the new versioned
   evidence to establish the complete lifecycle and snapshot obligations.
   Keep its outputs separate from performance samples. Reassess diagnostic
   coverage against the exact new artifacts and
   repeat only the controls needed for changed source/configuration/build
   boundaries; a historical scalar control cannot qualify a new warm binary.
7. **Collect the fresh complete matched attempt.** Only after the prerequisites
   and independent review pass, run all 24 processes under the frozen sampling
   and resource rules. Validate every process, including excluded primes and
   warm-ups, through its terminal destruction boundary before analyzing the
   measured populations. Retain valid negative performance results and all
   failures. P06-A02/A03 still require their separate reviewed acceptance.

Freeze the new qualification contract and review its tests before inspecting
fresh performance results. Do not widen a statistical threshold, change a
fixture, alter a golden or remove a failed attempt to obtain qualification.

## Implemented arithmetic guard and conditional lifetime proof

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
have distinct seeded transport evidence. These formulas must be checked
against actual generated configuration, not inferred from a profile name.

### Applying the terminal-observation proof

The [versioned source argument](../designs/simx_counter_lifetime_v1.md) now
establishes the conditional theorem and audits the selected update/reset and
finalization paths. Its [source manifest](evidence/p06-counter-diagnostics/lifetime-source-manifest.json)
binds 45 production and 10 inventory/caller bodies at `407ab9f`; its
[dependency manifest](evidence/p06-counter-diagnostics/dependency-source-manifest.json)
binds 21 Ramulator bodies at `e62c84a6f0e06566ba6e182d308434b4532068a5`.
These are source premises, not a complete transitive build attestation.

For nonnegative, monotone components `c_i(t)` with checked updates and
zero origins, a successful checked terminal read at `T` gives
`sum(c_i(T)) <= UINT64_MAX`; every earlier sum is no larger. Proving no later
component update extends the bound until storage destruction. This requires
all 33 final aggregates, including the six two-bank D-cache sums and the
two-buffer TCU sum, even if those aggregates were not queried earlier.
The checked type alone does not prove monotonicity: assignments, subtraction,
diagnostic seeding and reset behavior need their separate source constraints.
A guard failure anywhere invalidates the entire lifetime, even if a later
snapshot would fit.

The current [warm caller](../../tests/regression/ai_warm_workspace/main.cpp)
waits, closes and destroys each operation before its post-operation snapshot.
[Queue destruction](../../sw/runtime/common/queue.cpp) joins the worker.
[Owner release](../../sw/runtime/ai/runtime.cpp) frees resident buffers, kernel
and module before the wrapped device release. The
[observer](../../tests/regression/ai_warm_workspace/observer.cpp) takes all
available `before_release` queries immediately before the real device-release
call, while checking owner-close phase and zero observed live buffers. This
ordering identifies the proof location without changing timing intervals,
policy order or sample populations. Its capability-derived subset checks do
not yet enforce the complete exact 33/12 inventory or demonstrate every final
reference/CP premise; the separately versioned integration must do so for the
actual complete warm caller.

The proof and future reader must bind all of the following; none may be inferred
from a successful release return alone:

| Boundary | Required source proof and native observation |
|---|---|
| Origins and updates | All 40 components start at zero and remain monotone through checked production updates and permitted resets, with no diagnostic seeds or replacement storage; transient pending balance needs matched requests/responses and quiescent reset. |
| Exact inventory | All 33 expected enabled rows are queried successfully and the twelve unavailable rows are not queried; validation of a dynamically enabled subset is insufficient. |
| Exclusive ownership | One context and one submitter; no surviving operation/queue worker, external Device retain or legacy/debug submitter can advance the model or replace a DCR reply. |
| Terminal readout | All operations and synchronous CP transactions retire before CP disable and the complete checked snapshot; both halves succeed, saved class is restored and every selected source remains stable through the entire vector. |
| After the snapshot | VM is off, `CP_ON_L2=CP_ON_L3=0`, and no later launch, reset, cache flush, event delivery or model-ticking transfer can update selected storage. Apply the source proof across allocator release, CP bookkeeping, backend join and actual final destruction. |
| Dependency teardown | Bind the actual loaded DRAM backend and its source-to-binary provenance to the pinned Ramulator graph; no finalizer may update selected components or deliver their callbacks after the terminal vector. |
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
- [Platform cleanup](../../sim/common/simobject.h) discards queued events
  without delivering them and resets its clock; neither action certifies
  that earlier work completed. The [DRAM adapter](../../sim/common/dram_sim.cpp)
  calls Ramulator frontend/memory-system finalizers. The pinned source proof
  establishes statistics-only finalization for the selected graph and confines
  GPU callback delivery to `tick()`/`drain()`, which the adapter destructor does
  not call. That resolves the selected source-level finalizer question; the
  actual loaded dependency must still be bound to those sources. Its binary
  hash or a successful diagnostic alone does not prove compilation origin.

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

## Remaining native warm-caller qualification preflight

The seven model cells and five public modes close their declared diagnostic
gaps at `4268d2d5`, repeating the earlier corrected `e5f1524` scope. Their scalar
controls do not execute managed FP16/BF16 matmul or workspace reuse. The later
`57248e73` original does execute the four-process managed policy matrix, and
its complete inert replay now verifies the retained observations. It lacks the
per-run pending-balance witness and dependency compilation provenance required
for complete qualification. The remaining native obligation is therefore a
fresh preflight carrying those versioned observations and provenance, after
their contract and validation are independently reviewed. Freeze that route
before collecting performance results.

| Obligation | Minimum scope | Pass/fail boundary |
|---|---|---|
| Scope-matched transport and guard evidence | Compare the reviewed diagnostic source/configuration/build projection with each distinct FP16/BF16 measurement backend | Account for every selected updater/aggregate, guard selection and generated dimension. A changed or unbound component requires its own relevant diagnostic evidence; a revision label alone is insufficient. Diagnostic seeds remain outside the actual measurement binaries. |
| Complete managed caller and coherent snapshots | FP16/BF16 × both policies: four seed-free processes, each one prime plus 32 serial operations | 132 launches and 4,224 exact output words. The four snapshot locations yield 16 snapshots, 528 enabled queries/1,056 successful half replies and 192 unavailable rows receiving no query. Require exact inventory, correctness, exclusive ownership and quiescence across each pair. |
| Terminal lifetime and actual disposal | Every preflight process from construction through all operation/owner cleanup and final destruction | All 40 components satisfy the bound source premises; all 33 checked terminal aggregates succeed before CP disable; pending balance is zero; workers are joined; the final reference and loaded dependency provenance are established; no selected source can update afterward. |
| Native failure containment applicable to these artifacts | Bind the original immediate/delayed/cache faults and fresh-context controls, refreshing controls for changed relevant code or configuration | Sticky failure survives waits, query failure and queue-error consumption; later processor entries and direct-RAM DMA side effects remain suppressed. No failed-context reuse or partial snapshot is admitted, and teardown is complete. |

The completed source-access diagnostics use real backing counters through the
Processor → Cluster → Socket → Core → CSR route. A copied decoder, synthetic
selector array or zero-only TCU test would not establish source selection. In
particular, [TcuUnit::perf_stats](../../sim/simx/tcu/tcu_unit.cpp) derives its
local-memory reads from private TCU buffers; assigning a temporary stats copy
would not exercise them. Preserve this distinction when projecting diagnostic
coverage to a measurement build. SimX's 64-bit backing fields and RTL's 44-bit
fields remain separate scopes.

The conditional coherence argument uses the
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

The fresh qualification preflight carrying the new evidence remains future
work. The completed original and any future four-process preflight are not
measured samples or substitutes for the full 24-process attempt. Their terminal
observations cannot be copied into a later process's record, and missing
versioned fields cannot be inferred from the historical archive. Controlled
host faults, seeded selector checks, unseeded scalar controls, full managed-caller execution and
source lifetime proofs retain distinct scopes. General internal-worker
exception transport, fatal-abort recovery, simultaneous contexts and forced
cancellation remain outside this qualification route.

## New qualification binding and replay

Use a separately named versioned record, reader and execution binding,
retaining the unchanged measurement-contract digest. Select this new route
explicitly; do not add a caller flag, permissive branch or fallback that makes
the historical warm-v1 reader accept its blocked archives. Derive qualification
from verified evidence for the actual process. The existing `qualification_id`
is an execution-binding digest, not proof of counter qualification. Keep
pre-execution identities distinct from final archive identities to avoid
circular bindings.

### Reuse diagnostic validation within its original scope

The published `4268d2d5` readers accept the complete original **270-name model**
and **676-name public** source inventories. These are fixed inventories, not
compiled-unit subsets or results of a current-checkout glob. A later diagnostic
producer with additional source names must supply an independently reviewed,
complete [versioned source manifest](../../ci/project/p06_counter_source_inventory.py)
and its independently supplied exact-byte SHA-256 via both
`--source-inventory` and `--source-inventory-sha256`. All original names remain
mandatory, additions stay within the reviewed producer roots, and every path,
size and hash must equal the retained descriptors and source bodies.

The actual `4268d2d5` original adds seven public source names. Its
[683-source manifest](evidence/p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json)
has independently verified exact-byte SHA-256
`bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`.
The latest [public replay receipt](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit-public-replay.json)
passes with that explicit manifest; the fixed 676-name route rejects the same
expanded packet. This is retained-data validation of an actual later original,
not qualification of measurement artifacts.

Missing either option, an invalid explicit manifest, a changed descriptor or
an unsafe path fails closed. There is no fallback to the original inventory
after explicit-manifest failure and no discovery of new files on the replay
host. Preserve external archive/revision/manifest expectations with the receipt
and its actual `trusted_replay_sources` closure. A manifest digest establishes
the chosen expected bytes; it does not authenticate a Git origin, a build or
execution. New warm-caller roots or a different producer contract require
separate review rather than silently widening this diagnostic helper.

Keep diagnostic replay results at `scope="retained-data-consistency-only"`,
`native_execution="not_run"` and `retained_code_executed=false`, with all
qualification/readiness/warm-execution/acceptance claims false. Their current
validation of recorded object/library/tool identities does not supply absent
payloads or establish a cached dependency's compilation origin. A qualifying
record must independently resolve the chain from source to actual binary and
loaded dependency before relying on the lifetime theorem.

### Bind and review the new qualification record

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
