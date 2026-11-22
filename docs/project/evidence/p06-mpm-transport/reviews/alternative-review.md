# Independent shared-decoder comparison

**Retain the direct-half repair at `18c8880`; do not adopt the shared-decoder
experiment. The specific missing-comparison F2 in the [original circuit
review](circuit-review.md) is closed by measured evidence.** The alternative
is correct in the required native matrix and saves estimated FPGA LUTs, but
increases generic cell counts and the PERF-off topological path. This is a
cross-flow trade-off, not a uniformly cheaper implementation. The direct repair
preserves the measured depths and existing RV32 control results. Raw area
failures remain failures; this review grants no waiver or phase acceptance.

Reviewer `/root/w10_a01` authored neither implementation. Applied AGENTS.md,
the RTL/code review guidance, `docs/bug_fixes.md` §6.5 and the frozen
[transport contract](../../../../designs/host_mpm_transport_v1.md) §6.

## Matched experiment and verification

The [prospective comparison plan](../experiments/shared-decode-plan.json)
requires correctness and preservation of the other measured resources/depths.
The proposed alternative normalizes the high-address bit, selects one complete
counter, then selects the 32-bit reply half once. Commit
`27a18d4908aaec6c3f9431ec0d5e751fd46de4ce` differs from direct candidate
`18c888058ac851b802350c99770ed9ac2d27b582` in exactly one file:
`hw/rtl/core/VX_csr_mpm.sv`. I checked every hunk: all mappings and extension
guards remain; counter selection stays combinational; no state, response stage,
interface, architectural CSR, SimX or configuration changes are introduced.

[Run 44985166238](https://github.com/baabi-boo/AI-GPU/actions/runs/44985166238)
completed native job `137094033412` and circuit job `137094033563`. Actual PR
checkout `7a983db12dcbb6294f42eb7f290300c791e9db0c` has tree
`26211e4ff56dd0d2290a897f9fe99106d03c4734`; GitHub independently confirms its
parents `18c8880` and `27a18d4`. That tree equals the experiment head.

The [circuit archive/index](../hosted/attempt4-circuits.json) binds
[263 ZIP members](../hosted/attempt4-circuits.zip), 46 structured logs and 204
configuration/report artifacts. All hashes, sizes, CRCs and safe paths were
verified. I checked 442 candidate and 441 reference source records against
their original Git bytes. Only the four identical harness/catalog overlays
supplement the broken production reference `4df7186`.

Tool and environment records equal the direct repair's records; generated
configurations are identical. Candidate/reference/tool identities remain
unchanged during execution. The source-manifest difference from the direct
experiment is exactly the decoder. Repeated parent metrics reproduce exactly
in both flows. All eight Beacon executions precede all eight Yosys runs. Raw
Beacon CSVs and area totals, Yosys statistics, netlist cell counts and logged
longest paths independently reconcile with the structured measurements.

## Measured comparison

Both repaired implementations have identical counts at RV32 and RV64 within
each PERF mode. Direct → shared numbers below therefore apply to **both widths**.

| PERF | Beacon LUT | Beacon FF / depth | Yosys generic cells | Yosys FF | Yosys path | Beacon watch endpoints |
|---|---:|---:|---:|---:|---:|---:|
| Off | 93 → 91 | 193 / 4 → 193 / 4 | 397 → 406 | 168 → 168 | 7 → 8 | 0 → 0 |
| On | 1,439 → 1,371 | 369 / 8 → 369 / 8 | 997 → 1,018 | 360 → 360 | 10 → 10 | 12 → 32 |

RAM and DSP counts remain zero. The shared decoder saves **2 LUTs (2.2%)** off
and **68 LUTs (4.7%)** on relative to the direct repair. It adds **9 generic
cells (2.3%)** off and **21 (2.1%)** on. The PERF-off longest path increases
by one level. Beacon's modeled frequency also decreases from 413.7 to
393.3 MHz off and 370.7 to 369.8 MHz on. These are estimator outputs, not
placed timing or physical Fmax.

The longer Yosys path ends at the existing `dcr_data.flush_read_r` register.
`VX_dcr_data.sv` is unchanged: this is a whole-wrapper mapping consequence,
not evidence that the new half mux itself lies on that path or that a protocol
cycle was added. Moving changes into that unrelated block to erase the cost
would violate the same-change/stop rules. This review recommends neither that
workaround nor a new pipeline stage.

## Correctness and parent sensitivity

The [native archive/index](../hosted/attempt4-native.json) binds
[125 ZIP members](../hosted/attempt4-native.zip). Verified 34 structured logs,
80 retained configuration/compiler artifacts, 41 candidate source paths,
31 parent critical inputs and five identical harness overlays. Candidate,
parent and direct-repair tool/dependency records agree. Every recorded
before/after source, configuration and binary identity is stable.

All eight alternative candidate cells pass: **1,056 RTL reads, 19,912 RTL
assertions, 28 ignored requests and 18,064 SimX checks**. RTL reports the same
two-edge response and 44-bit width. Each of five SimX builds, including the
parent, compiles and links 41 production objects plus the harness.

Both original-production builds succeed, then their native runs exit 1 on the
missing high half. RTL reports tag `00220001`, expected `00000001`, actual
`00000000`. I independently parsed all 714 parent SimX failures among 5,251
checks: 357 missing high replies, 238 low-first and 119 high-first truncated
reconstructions. Every expected/actual value follows from its literal seed;
there is no unrelated failure class.

## Cost disposition

| Case | Introducing commit | Mechanism and disposition |
|---|---|---|
| RV64, PERF off | `58c71d34f316baf47928228069f943ab8a1edd8c` | Restore two high-half routes. Direct repair adds 21 Beacon LUTs and 24 observable Yosys FF bits over the broken parent; preserve it because the measured alternative worsens generic area/depth. |
| RV64, PERF on | Same | Restore high-half routes including live CORE counters. Direct repair adds 417 Beacon LUTs and 72 observable Yosys FF bits; the alternative's LUT saving costs more generic cells and watch endpoints. |

The 24/72 FF bits match the premeasurement prediction and the prior netlist
attribution: arbitrary independent bits `[43:32]` of two/six registered wrapper
inputs must remain observable. No production pipeline registers were added.
The high-half decoding is a correctness restoration, not a claim that the old
hardware already implemented the same logic. No unrelated gain offsets it.

The concrete lowest-cost alternative proposed by independent review has now
been built and measured under the same conditions. It cannot supply its LUT
gain while preserving every measured resource/depth. Therefore the direct
implementation is the **lowest-cost depth-preserving tested candidate under
the stated cross-flow constraints**. This closes the named missing experiment;
it does not prove global optimality across unexamined architectures or identify
physical gate area from generic cell counts.

All raw Beacon builds still report `NO-BASELINE`; both experiments retain
RV64 area-comparison exits 3 and `gate_outcome=fail`. No baseline, threshold,
golden, acceptance record or production source was changed by this review.
The full-GPU, enabled-extension, AFU, physical timing, live-counter/atomicity
and absolute no-wrap obligations remain outside this leaf experiment.

**R3 verdict: retain the direct repair; land after the separate integration
and publication reviews.** Warm v1 remains unconditionally unqualified;
historical high bits cannot be recovered. One audit-script probe-count filter
and one assumed failure-summary spelling were corrected during verification;
the final checks pass, and neither was a product failure. No native rerun or
synthesis was performed by this reviewer.
