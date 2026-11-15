# P09 — Training and multi-device research

## Goal and boundaries

Demonstrate small-model training and cooperation between two physical accelerators
as separately tested capabilities. Inference, a custom-op bridge or a simulator
does not establish either capability. This optional research program does not
promise frontier-model training, linear scaling, CUDA compatibility or NVLink
equivalence. [roadmap.json](../roadmap.json) owns live status and exit criteria.

## Entry conditions

- P08 has an accepted, hardened physical-prototype release and evidence package.
- The maintainer explicitly activates the research scope and assigns its research
  lead; required devices, transport, tools and access are available and approved.
- The workload, precision, optimizer and physical topology are recorded decisions,
  not assumptions. Additional purchases need separate authority.
- P09 is **not** a prerequisite for the bounded inference ASIC in P10/P11.

## Ordered work packages

1. Choose a small redistributable training fixture and freeze architecture, data,
   seeds, optimizer, precision, gradient accumulation and acceptance bounds before
   evaluation. Define the reference implementation and reproducible loss checks.
2. Implement and verify only the declared backward kernels and optimizer steps.
   Compare intermediate gradients and parameter updates with independent reference
   results; use finite-difference checks where appropriate to the chosen contract.
3. Reproduce the fixed training trajectory on the physical FPGA. Test overflow,
   invalid gradients and mixed-precision scaling if advertised; a decreasing loss
   by itself is not sufficient evidence of correct training.
4. Freeze a two-device topology and transport contract: rank/device identity,
   buffers, completion, synchronization, ordering, cancellation and failure handling.
   Build the smallest required transfer and collective operations first.
5. Test payload sizes, ordering, repeated collectives, mismatched participation,
   interrupted transfers and recovery. Trace both physical devices; two simulated
   ranks or two processes sharing one accelerator do not satisfy this gate.
6. Compare single- and two-device runs under a declared equivalent-work policy.
   Report useful step throughput, end-to-end latency, communication/synchronization
   costs and numerical behavior without omitting host work or transfer overhead.

## Deliverables

- Versioned training/gradient contract, deterministic fixtures and physical results.
- Topology/transport specification, collective correctness and failure-test reports.
- Reproducible comparative benchmarks with raw samples, operating conditions,
  compatibility limits and a research continuation or stop recommendation.

## Acceptance and required evidence

| Gate | Required proof | Evidence level |
|---|---|---|
| P09-A01 | The fixed small training workload matches reference gradients and convergence under its predeclared precision and optimizer settings. | `fpga_measured` |
| P09-A02 | Transport and collectives pass correctness, ordering, failure and recovery tests on the declared two-device physical topology. | `fpga_measured` |
| P09-A03 | Single/multi-device comparisons measure scaling and communication costs on identified hardware without unsupported NVLink/CUDA claims. | `fpga_measured` |

Evidence records source/tool/configuration hashes, model/data provenance, seeds,
optimizer settings, device identities, bitstreams, achieved clocks, transport,
commands, raw samples and frozen acceptance thresholds. Report uncertainty and
limitations under [benchmarks](../benchmarks.md) and [acceptance](../acceptance.md).
Simulated experiments can guide development but cannot close these physical gates.

## Stop conditions and handoff

Missing physical devices, unresolved gradient/reference mismatches, collective
deadlocks, corrupt data, unrecoverable errors or unfair workload comparisons block
the corresponding claim and phase closure. Do not hide host fallback, alter
thresholds after seeing results or infer scaling from theoretical link bandwidth.

Hand off the accepted research evidence and compatibility matrix to the
[release process](../releases.md); record follow-up priorities in
[status](../status.md) and [backlog](../backlog.md). Any use in a silicon target
requires its own reviewed [P10 decision](p10-asic.md), not an automatic scope change.
