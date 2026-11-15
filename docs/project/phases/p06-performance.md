# P06 — Memory and performance scaling

**Goal:** measure and improve useful work per second, byte and joule without
confusing simulated behavior with physical speed. This is a development plan,
not a performance result. Live state and canonical gates are in
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

Hand P07 the selected configuration, constraints, bounded workloads, memory-map
assumptions and reproducible reports. Update [status](../status.md) and
[backlog](../backlog.md); the next bounded action is a documented board-readiness
decision and physical implementation plan, not an unsupported performance claim.
