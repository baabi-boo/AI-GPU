# P08 — Reliability and release hardening

## Goal and boundaries

Turn the physically demonstrated prototype into a reproducible experimental
release with a defined failure model, recovery behavior and published limits.
This phase does not establish production, safety-critical or arbitrary
multi-tenant suitability. Live status, dependencies and acceptance criteria are
owned by [roadmap.json](../roadmap.json), not by this plan.

## Entry conditions

- P05 framework integration and P07 physical FPGA prototype have accepted evidence.
- The exact supported board, bitstream, runtime, framework versions and model
  workloads are frozen; inherited source alone does not satisfy these conditions.
- The release and reliability lead has an assigned owner, suitable lab access and
  an approved resource budget. Review [risks](../risks.md), especially RK-017.

## Ordered work packages

1. Write a threat/failure model covering trusted host components, permitted users,
   device-memory boundaries, malformed requests, exhaustion, timeouts and resets.
   State which isolation guarantees are implemented and which remain unsupported.
2. Add deterministic negative cases for invalid descriptors, sizes, addresses and
   lifetimes. Verify actionable errors and cleanup without silent CPU fallback,
   stale completions or access outside the supported allocation boundaries.
3. Exercise queue/event failures, host interruption and device reset/recovery on
   physical hardware. Define outstanding-work disposition and prove a fresh
   workload succeeds after recovery; preserve failing traces for root-cause work.
4. Freeze a sustained-load matrix spanning the supported operators, model inputs,
   transfers and resource-pressure cases. Run the canonical 24-hour physical soak,
   recording errors, resets, memory/resource use and available thermal/power data.
5. Produce versioned experimental artifacts, dependency/license inventory and a
   compatibility matrix. Reproduce installation on a clean supported environment.
6. Resolve critical findings, publish residual limitations and obtain release
   review. Keep inherited regression coverage, numerical bounds and goldens intact.

## Deliverables

- Reviewed threat/failure model and fault-injection matrix with expected outcomes.
- Physical recovery, isolation-boundary and sustained-load reports with raw logs.
- Reproducible installation instructions, artifact hashes, source/license inventory,
  compatibility matrix, known limitations and reviewed experimental release record.

## Acceptance and required evidence

| Gate | Required proof | Evidence level |
|---|---|---|
| P08-A01 | Physical fault-injection tests cover error propagation, malformed requests, exhaustion, recovery and the declared isolation model; critical findings are resolved. | `fpga_measured` |
| P08-A02 | The declared workload matrix completes the canonical 24-hour physical soak with zero unexplained errors; preserve telemetry and issue disposition. | `fpga_measured` |
| P08-A03 | Clean installation reproduces versioned artifacts with source/license inventory, compatibility information and reviewed release evidence. | `source_present` |

Every record identifies source/configuration, board and firmware, bitstream hash,
achieved clock, exact commands, timestamps, expected outcomes and observed results.
Record absent telemetry explicitly. Simulation, `hw_emu`, a short demonstration
or a governance-check pass cannot replace the physical gates. Follow
[acceptance](../acceptance.md), [verification](../verification.md) and
[release policy](../releases.md).

## Stop conditions and handoff

Unexplained numerical errors, hangs, stale data, leaks, unsafe recovery or failed
isolation requirements block the affected release claim and phase closure.
Do not shorten the soak, weaken tolerances or remove a case to obtain a pass.
An unavailable board or incomplete run remains blocked/not run.

Hand off the accepted release baseline and unresolved limitations to the optional
[P09 research program](p09-research.md) and independently to
[P10 ASIC feasibility](p10-asic.md). P09 is not a prerequisite for the bounded
inference-ASIC path. Record the next bounded action in [status](../status.md).
