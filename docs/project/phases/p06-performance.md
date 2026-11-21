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
targeted host checks and their synthetic/fault-injection limits.

**Next action:** finish checkpoint integration and run/review the frozen native
correctness matrix through the [workspace handoff](../p06-workspace-handoff.md).
The new native matrix is pending; existing historical passes do not qualify
changed sources. Then independently freeze matched workloads, source revisions,
numerical inputs, repetitions, measurement boundaries and rejection criteria
for the [draft warm performance experiment](../p06-next-experiment-proposal.md).
Retain the cold baseline separately. Keep the two-job, 4 GiB memory and 15 GiB
disk prerequisites unchanged. Neither host tests nor the correctness smoke
establish a speedup or P06-A02/A03 acceptance.

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
is qualification of a clean workspace checkpoint and its native executions,
followed by the separate warm performance protocol freeze described above. A
documented board-readiness decision and physical implementation plan follow later.
