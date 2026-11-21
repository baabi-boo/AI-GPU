# P06 — Memory and performance scaling

**Goal:** measure and improve useful work per second, byte and joule without
confusing simulated behavior with physical speed. **P06 is `in_progress`** with
frozen baseline tooling implemented and native qualification outstanding.
No performance result or P06 acceptance is established yet. Live state and canonical gates are in
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

## Current bounded implementation

The [development audit](../p06-benchmark-audit.md) selected a repeated native
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

**Next action:** execute the reviewed
[hosted qualification](../../../.github/workflows/p06-baseline.yml), preserve
original artifacts and every failed attempt, and obtain independent replay
against their supplied digests. Retain the two-job, 4 GiB memory and 15 GiB disk
prerequisites. Local source/host checks cannot replace native execution or
justify relaxing a blocked prerequisite. Only after an accepted baseline
select a bounded optimization hypothesis from its measurements.

P06-A01 awaits that execution and review; its acceptance evidence list remains
empty. P06-A02/A03 remain open. P04 supplies the entry dependency and P05 is
independent. The missing P01 vendor `hw_emu` evidence and inherited
[267 → 283 DSP area-gate failure](../p04-executor-audit.md) remain unresolved.

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
remains hosted baseline qualification and independent review; a documented
board-readiness decision and physical implementation plan follow later.
