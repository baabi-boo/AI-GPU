# P11 — Funded silicon realization and bring-up

**Goal:** fabricate and validate a funded design only after manufacturing sign-off.
The live status, dependencies and authoritative gate text are in
[roadmap.json](../roadmap.json); the accountable role is Silicon bring-up lead.
Neither this plan nor a completed feasibility review places a manufacturing order.

## Entry and boundaries

- P10 must be complete, including an explicit human go/no-go decision, qualified
  ownership, approved funding and availability of the required tools and IP.
- Keep the bounded inference target and frozen model/numerical contracts. A
  scope, process, memory or package change reopens the affected feasibility work.
- Use foundry-qualified components and sign-off criteria for the selected process.
  FPGA success, synthesis estimates and a generated GDS file are not substitutes.
- Paid services, partner commitments, tapeout and lab actions require appropriate
  authorization. Only qualified operators should energize or modify physical boards.

## Ordered work packages

1. Complete the approved design implementation and verification. Close functional,
   formal, equivalence and clock/reset-domain issues; implement scan, DFT and
   memory built-in self-test (MBIST), with reviewed test coverage and limitations.
2. Complete qualified physical sign-off: timing across required process/voltage/
   temperature corners, power integrity, electromigration, DRC/LVS and relevant
   reliability checks. Review package, memory/PHY, board, thermal and test interfaces.
   Every exception requires an accountable disposition, not an agent-issued waiver.
3. Freeze the release database, source/IP/tool identities, checksums, manufacturing
   test program and sign-off reports. Obtain explicit human manufacturing-release
   approval before the authorized partner submits the final tapeout package.
4. Prepare safe bring-up equipment, instrument calibration and board test procedures.
   Inspect assembly; validate rails, current limits, sequencing, clocks and reset
   before progressing to debug access, memory initialization and interface training.
5. Establish host enumeration and DMA round trips, then test address/bank boundaries,
   caches, core execution, tensor arithmetic and error/reset recovery. Retain device,
   package and board identities, operating conditions and failure-analysis records.
6. Execute the frozen model suite on actual silicon with dispatch traces and CPU
   comparisons. Measure achieved clock, usable capacity, latency/throughput, power
   and temperature at declared operating points; report uncertainty and limitations.
7. Evaluate manufacturing-test results and yield using actual sample counts and
   conditions. A successful sample does not establish production yield or broad
   reliability. Review failures, any respin decision and the qualified release scope.

## Deliverables and acceptance

| Gate | Required deliverable and proof | Evidence level |
|---|---|---|
| `P11-A01` | Foundry-qualified verification/DFT/physical sign-off reports, reviewed exceptions and explicit manufacturing-release approval | `source_present` |
| `P11-A02` | Actual packaged-device and board lab records proving power/clock/reset, memory, host/DMA and core/tensor operation | `silicon_measured` |
| `P11-A03` | Frozen-model acceptance and measured frequency/capacity/performance/power/yield limits, with a reviewed release decision | `silicon_measured` |

The first gate is documentary sign-off, not merely source-file existence. Physical
gates require raw instrument/test logs, source/configuration/firmware identities,
device and board revisions, test conditions, artifact hashes and reviewer records.
Record unavailable measurements and failures honestly; do not substitute simulated
or FPGA values. Keep restricted foundry/IP collateral out of public artifacts.
Use [verification](../verification.md), [benchmarks](../benchmarks.md),
[hardware](../hardware.md) and [acceptance](../acceptance.md).

## Stop conditions and handoff

Stop manufacturing release for missing authority, incomplete qualified sign-off,
unresolved critical failures or unavailable licensed IP. Stop physical testing for
unsafe power/thermal behavior; a qualified operator must diagnose the cause before
resuming. Unexplained corruption, hangs, interface failures or model mismatches
block acceptance. Do not invent measurements or weaken frozen criteria to ship.

Hand the [release process](../releases.md) the measured capability envelope,
reproducible software/firmware, compatibility matrix, manufacturing/lab evidence,
known limitations and support/recovery procedures. Record unresolved work and any
separately authorized production or respin plan in [status](../status.md) and
[backlog](../backlog.md). First-silicon success is not an automatic production claim.
