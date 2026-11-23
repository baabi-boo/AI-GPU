# P06 — Memory and performance scaling

**Goal:** measure and improve useful work per second, byte and joule without
confusing simulated behavior with physical speed. **P06 is `in_progress`**, with
[P06-A01 accepted](../evidence/p06-baseline/acceptance.json) for the frozen cold
SimX baseline and P06-A02/A03 open. Live state and canonical gates are in
[roadmap.json](../roadmap.json); the accountable role is Performance and memory lead.

## Entry and boundaries

- P04 must supply accepted native tiny-model inference and frozen references.
  P05 framework integration is not a dependency for native performance work.
- Reuse the [cache hierarchy](../../designs/cache_subsystem.md),
  [DXA design](../../designs/dxa_async_copy_multicast.md),
  [roofline tool](../../../ci/roofline.py) and inherited performance gates.
- Follow the [benchmark policy](../benchmarks.md). Simulator host execution time,
  functional-mode cycle output, theoretical peak arithmetic and requested clock
  are not measured FPGA throughput or energy efficiency.
- Do not promise a core count, memory capacity, frequency, TOPS or commercial-GPU
  comparison. Freeze feasible configuration-specific targets before acceptance.

## Accepted baseline and next experiment

The [qualification audit](../p06-qualification-audit.md) independently qualifies
the original [run 44901052221, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44901052221)
at `84b6ca0ca75fba248ba330642bbf8764db3d459c`. The preceding
[development audit](../p06-benchmark-audit.md) selected this repeated native
baseline before an optimization. The implemented
[contract](../../designs/native_benchmark_v1.md),
[manifest](../../../ci/project/p06_benchmark_contract.json),
[runner](../../../ci/project/p06_execute.py) and
[original-packet replay](../../../ci/project/p06_replay.py) reuse the unchanged
accepted applications with a test-only observer.

The fixed suite has eight workloads: the three accepted matmul shapes and the
batch-16 `16 → 8 → 4` model in each of FP16/BF16. It uses the RV64 `p02-tfr`
SimX timing model, one core/cluster, four warps of four threads and issue width
one. Each workload has one retained warm-up and five measured fresh processes:
**48 processes / 72 launches**, of which **40 processes / 60 launches** are
measured. Every invocation starts a fresh device context; warm-cache behavior
is not established. The counter inventory has **45 rows: 33 available and
12 explicitly unavailable**. Counts span the whole context and all three
model launches, with host intervals and logical transfer/operation counts
retained separately.

The [packet](../evidence/p06-baseline/README.md) retains original archives,
source/numerical/counter review and [independent acceptance](../evidence/p06-baseline/reviews/acceptance-review.json).
The new [analyzer](../../../ci/project/p06_analyze.py) and
[analysis contract](../../designs/native_baseline_analysis_v1.md) provide
full-matrix replay and per-sample diagnostics. Stricter serial timing containment
preserves every original measurement and the existing 1,000 ns process allowance.
Host durations include supervision with a documented exit-observation limitation;
no fine-grained host speedup or physical performance is inferred.

The [serial workspace audit](../p06-workspace-audit.md) selected the ownership
prerequisite. Its [runtime/correctness contract](../../designs/serial_matmul_workspace_v1.md)
is now implemented: one context per linked managed-runtime instance, one live
operation through completed explicit close, sticky execution/cleanup errors, and
an opt-in `(8,4,8)` workspace retaining 320 requested A/B/D bytes. Default
allocation preserves all six signatures; the MLP rejects non-default policy.
The [workspace packet](../evidence/p06-serial-workspace/README.md) records
targeted host checks and their synthetic/fault-injection limits. The subsequent
[original correctness review](../evidence/p06-warm-workspace/README.md#reviewed-original-workspace-correctness)
reconciles run `44925627664`, attempt 1, at
`13dc0d1fdb6d5322104e381aa342dc139c7bb80c`: **8 processes, 32 native launches,
1,024 exact output words and 60 tensor-buffer lifetimes**. This is reviewed
historical execution, not qualification of every later source revision.

The [warm measurement contract](../../designs/warm_workspace_benchmark_v1.md)
and its runner/analyzer are implemented. Warm v1 remains unconditionally blocked
by `P06-WARM-RV64-MPM-HIGH-HALF`, with `qualified=false` and
`absolute_no_wrap_bound="not_established"`. The coupled SimX/host-only RTL
[transport repair](../p06-mpm-transport-audit.md) has reviewed strict native
coverage at `18c8880`: all eight RV32/RV64 × PERF off/on × engine cells pass,
and both old-production targets demonstrate the expected numeric high-half
failure. The immutable governance suite passes 2,910 tests. The
[transport evidence](../evidence/p06-mpm-transport/README.md) retains completed
paired circuit measurements and raw RV64 area failures. The
[alternative review](../evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the concrete comparison finding and selects the direct decoder. Broader
CI and publication remain separately tracked; no overall CI success is asserted.

The [checked-counter prerequisite](../../designs/simx_checked_counters_v1.md)
is implemented at `9fd7eac203c77fa54c7af80fa0220ae09553cd55`. Its
[reviewed original native packet](../evidence/p06-checked-counters/reviews/native-review.md)
supports five directed cells, with ordinary and checked builds compiling
44 translation units each. That checkpoint seeded nineteen available selectors.
The subsequent [diagnostic audit](../p06-counter-diagnostics-audit.md) and
[original evidence](../evidence/p06-counter-diagnostics/README.md) close all
fourteen remaining gaps: **33 available selectors, 40 backing components and
12 unavailable L2/L3 rows receiving no query**. The corrected original at
`e5f1524`, run `45031746149`, passes seven model cases and six public-runner
cases (one boundary control plus five modes). Each model boundary variant has
6,389 checks and 1,788 half reads; actual Processor/RAM public modes provide
ten context disposals and seven terminal snapshots. Offline readers published
at `4268d2d5` check retained-data consistency without executing retained code.

The latest audited [diagnostic run 45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685)
separately passes all thirteen diagnostic process cases at `4268d2d5`. Its
[independent original-packet audit](../evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit.md)
matches the 270 model/683 public source bodies to that immutable tree and
validates both inert replay routes. Public replay requires its independently
Git-pinned 683-source manifest; the fixed original 676-name route rejects the
expanded packet. The separate [completed host receipt](../evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/receipt.json)
for run `45034575638` records **3,312 executed tests in 1,811.712 seconds:
3,310 pass and two isolation-guard failures**, with no errors or skips. The
[test-only repair](../evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md)
is independently reviewed and published at `142b2d6`, closing both F2 findings.
The subsequent [clean local governance receipt](../evidence/p06-counter-diagnostics/host/local-clean-142b2d6/receipt.json)
records **all 3,318 tests passing in 1,918.414 seconds on CPython 3.12.14**, with
four successful commands and independently verified clean source/log bindings.
The separate [retained retry receipt](../evidence/p06-counter-diagnostics/host/checkpoint-142b2d6/pending-receipt-20261122T165509Z.json)
lists hosted `45040805357` and native `45040805341` as queued at that checkpoint,
without executed results. The original failed attempt remains retained, and the
latest audited native diagnostic execution stays at `4268d2d5`.

The subsequent seed-free managed preflight succeeded at
`57248e73dfce4ae2d21d2cbdb82c3953eef2e3db`,
[run 45085300171, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45085300171):
FP16/BF16 × both allocation policies, **four processes, 132 launches and 4,224
exact output words**. The implemented
[complete replay contract](../../designs/managed_counter_preflight_replay_v1.md)
and [evidence packet](../evidence/p06-managed-preflight-replay/README.md) now bind
all 999 retained source bodies to independent inventories and derivations,
close the application/backend command graphs, reproduce retained generated
configuration, and check process, loader, lifecycle and hosted records.
The reader hashes 17 retained binary bodies; the 43 model-object bodies per
format were not retained and cannot be independently hashed. The failed original
at `8756f400`, run `45084009157`, remains a required negative control with exact
`report.outcome: value differs` rejection. Replay executes no retained code and
supplies no new native run or qualification decision.

The later [native lifetime packet](../evidence/p06-native-lifetime/README.md)
records `b4127b19a004b5aebb8d52eab9ceda0da3ff4561`,
[run 45130300651, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45130300651):
**four processes, 132 launches and 4,224 exact FP32 result words**, with zero
mismatches. Independent original reviews reconcile all 33 run/reset pairs per
process, zero-pending observations, required flushes, terminal ownership and
actual destruction. The separate accessor probe observes positive pending
balances in both gp contexts and its always-zero control fails the exact
required assertion; its operations are excluded from the managed matrix.

The [lifetime argument](../../designs/simx_counter_lifetime_v1.md) remains
conditional on complete source/binary premises, including the managed caller's
ownership, resets and terminal observations plus actual loaded dependency
provenance. The implemented witness supplies bounded observations; seeded
diagnostics and directed scalar controls do not bind the entire argument to
measurement binaries. The [diagnostic handoff](../p06-counter-diagnostics-handoff.md)
retains the earlier diagnostic scope.

The [fresh dependency implementation packet](../evidence/p06-dependency-provenance/README.md)
records the separately versioned source/build/product route. The foundation is
published at `5527cb062e10dfff3266022d138dd7cdf63f5e5c`, the complete native/control
readers at `8b71ee07392c1ed86f654b2d683d9a8d2d1f50ea`, and the earlier reviewed
production code at `19333193192ba5a2d3667c0111235ec9e21a5898`.
The producer verifies immutable source and transitive inputs, records selected
configure/compile/archive/index/link execution, and binds products through
staging, static links and dynamic loader admission. Live admission now invokes
and binds the existing complete **30-command application graph**, including the
**14-source runtime stub**, to build/process identities. The dependency, native
and combined-control readers are implemented for bounded inert review with
external pins. The [full governance receipt](../evidence/p06-dependency-provenance/validation/candidate-full-governance-verification.json)
records 4,118 passing tests in 2,683.750 seconds at local `ba4deccd`, whose tree
equals published `8b71ee07`. The later repeated-input, map-category and archive
selection corrections have a separate
[125-test result](../evidence/p06-dependency-provenance/validation/w10_a06-spdlog-tests-01.json)
and [final-code review](../evidence/p06-dependency-provenance/agents/w09_a01-final-code.md)
binding all 380 Python files to `19333193`. The earlier full suite is not a run
of those later changes. These host checks establish no formal native original.

The dependency handoff's later local attempt 04 established the complete
dependency/native/control original in its declared scope. Its originals and
separately counted pending-read/always-zero and alternate-library controls
remain retained in the
[dependency packet](../evidence/p06-dependency-provenance/README.md).
At the earlier
[retained provider observation](../evidence/p06-dependency-provenance/validation/provider-observation-19333193.json)
for `19333193`, fresh run `45162083701` was pending with no jobs, and governance
run `45162084006` had one queued job and no steps. No queue cause or native
result is inferred; recheck and retain the actual provider identities before
intake. That historical provider observation does not establish a native result.
The [host diagnostic](../evidence/p06-dependency-provenance/host-diagnostic/README.md)
retains its actual attempts and separate host-build scope.
[Attempt `05` at `19333193`](../evidence/p06-dependency-provenance/host-diagnostic/execution-05-summary.json)
passes 406 actual compilations, three archives, two indexes and two shared links:
all 413 selected records, complete diagnostic graph validation and
[independent host-original consistency review](../evidence/p06-dependency-provenance/host-diagnostic/review-05.json) pass. The earlier
failed attempts remain retained. This result cannot replace formal
preparation/cache/staging, the managed population or loader joins.
The historical `57248e73` original retains its earlier four-snapshot scope and
its three unresolved obligations:
`all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance` and
`independent_complete_counter_qualification`. Those fields are preserved in
the historical records.

The subsequent [complete counter qualification](../../designs/complete_counter_qualification_v1.md)
supplies a separately versioned 33-selector/40-component/ten-premise proof,
prelaunch admission and complete inert reader. Its
[fresh original](../evidence/p06-counter-qualification/README.md) at
`17e0284496bab10c7632a48e4f91efb6fb4fec0b` passed preparation, all 413 selected
dependency operations and the FP16/BF16 × policy matrix: **four processes,
132 launches and 4,224 exact FP32 words**. Independent original reviews and
public replay derive `counter_qualification_passed=true` only for
`recorded-four-process-preflight-only`. The revised reader published at
`220399748ecab84d48ba5a5f123457c44a0c8699` explicitly inventories 94 trusted
inputs; replay of the same original changes only that inventory. Native
execution remains tied to `17e02844`. The
[audit](../p06-counter-qualification-audit.md) separates source/tooling
validation, original execution, replay and acceptance.

**Next development action:** implement and independently review an explicit
qualified route for the unchanged warm sampling contract, then execute its
fresh complete attempt. Follow the
[qualification handoff](../p06-counter-qualification-handoff.md) and
[qualification plan](../p06-mpm-qualification-plan.md). The existing qualified
runner and reader admit four processes; they cannot select the warm matrix
without a reviewed extension. Each format needs one warm-up policy pair and
five measured pairs, with one prime plus 32 serial operations per process:
**24 processes, 792 launches and 25,344 exact output words**. Bind every new
process before launch and verify it through destruction. Retain excluded
primes and warm-ups and all original performance predicates and negative results.
Preserve the v1 block and original cold baseline; source repair cannot recover
missing historical high bits. Keep the two-job, 4 GiB memory and 15 GiB disk
prerequisites unchanged. Correctness and transport tests establish no speedup
or P06-A02/A03 acceptance. All seven claims remain false: `qualified`,
`ready_for_warm`, `warm_execution`, `full_warm_coverage`, `acceptance_claimed`,
`phase_acceptance` and `performance_acceptance`.

P06 and P06-T01 remain `in_progress`; P06-A02/A03 remain open. P04 supplies the
entry dependency and P05 is independent. The missing P01 vendor `hw_emu` evidence
and inherited [267 → 283 DSP area-gate failure](../p04-executor-audit.md) remain unresolved.

## Ordered work packages

1. Freeze a bounded suite of operator and end-to-end model workloads. Record
   shapes, precision, sparsity, layouts, seeds, batch/sequence sizes, transfers,
   warm-up, repetitions, synchronization and numerical contracts before tuning.
2. Capture an unchanged baseline with exact source/tool/configuration identities.
   Record cycles, retired work, useful transfer bytes, cache/local-memory behavior
   and stalls. Check counter meanings and operation counts; the roofline tool's
   default compute roof is scalar, so a tensor roof needs an explicit derivation.
3. Identify the limiting resource before selecting changes: arithmetic occupancy,
   memory bandwidth, bank conflicts, data reuse, host transfers or launch overhead.
   Keep kernel-only, transfer and end-to-end measurements separate.
4. Evaluate one bounded change at a time: tiling, reuse, async-copy overlap,
   cache/local-memory geometry or core/cluster scale. Preserve coherency, fences,
   buffer bounds and supported operator semantics; more cores are not proof of
   useful speedup. Record rejected hypotheses as well as successful changes.
5. Pair every RTL timing change with its SimX model change. Run the affected
   numerical, native-RTL and applicable parity/performance cases on matched
   configurations; investigate divergence rather than widening tolerances.
6. Set an explicit resource/timing budget for the selected target. Use the
   [synthesis guide](../../synthesis_analysis.md) and required Beacon checks with
   reviewed disk/RAM/job limits. Report tool assumptions, RAM treatment, utilization
   and timing; estimates remain estimates until physical measurements exist.
7. Publish before/after raw samples and analysis with uncertainty and limitations.
   Preserve inherited golden data: only the authorized human-run review process
   may regenerate baselines. A faster incorrect result never satisfies this phase.

## Deliverables and acceptance

| Gate | Required deliverable and proof | Evidence level |
|---|---|---|
| `P06-A01` | Frozen workload/configuration manifests, baseline samples and analysis of cycles, traffic, cache/local-memory use and operation counts | `simulated` |
| `P06-A02` | Before/after evidence preserving numerical contracts and inherited gates, with synchronized SimX/native RTL and applicable parity results | `rtl_verified` |
| `P06-A03` | Reviewed scale/configuration budget and synthesis/resource/timing reports that distinguish predictions from measurements | `rtl_verified` |

Retain exact commands, arithmetic/execution backend, raw counters and report hashes.
The P06-A03 level does not turn a synthesis estimate into physical FPGA evidence.
Apply the [acceptance](../acceptance.md) and [verification](../verification.md)
policies. Report energy efficiency only with a measured, defined power boundary.

## Stop conditions and handoff

Block acceptance for numerical failures, unexplained parity/gate regressions,
uncontrolled benchmark changes, missing resource budgets or exhausted resources.
Do not hide a regression with a compensating improvement elsewhere.

After the P06 gates are accepted, hand P07 the selected configuration,
constraints, bounded workloads, memory-map assumptions and reproducible reports.
P07 also requires P01's vendor integration gate. Update [status](../status.md)
and [backlog](../backlog.md) as each gate earns evidence. The current next action
is the explicit qualified 24-process warm-route implementation and independent
review in the [qualification handoff](../p06-counter-qualification-handoff.md),
followed by the fresh unchanged matched warm attempt. The completed four-process
qualification cannot be copied into those new process records, and historical
warm-v1 remains blocked.
A documented board-readiness decision and physical
implementation plan follow later.
