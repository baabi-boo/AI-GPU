# Independent paired-circuit review

**Disposition: the measurement obligation is complete; the cheapest-correct-alternative cost obligation remains open (F2).** The eight Beacon and eight generic Yosys runs completed, with no measured depth increase. Their raw RV64 area failures remain failures. This review grants no waiver, baseline update, physical timing claim, or phase acceptance.

## Source and evidence

Reviewed candidate `18c888058ac851b802350c99770ed9ac2d27b582`, executed as PR merge `6e6426a0bf761baab11e932a4c86b49a5de81217`, tree `d6dd742a905e0f3e76c7374cc678ba87e5c2a19e`, against production reference `4df7186edbca82b21b2b8cba9b3b192248b99209`. GitHub's commit endpoint confirmed both parents and the tree. The circuit job `137089144444` in [run 44983573225](https://github.com/baabi-boo/AI-GPU/actions/runs/44983573225) completed successfully; that denotes completed measurements, not passing cost gates.

The [archive index](../hosted/attempt3-circuits.json) binds the [raw ZIP](../hosted/attempt3-circuits.zip), SHA-256 `42bfd452643d56aa0a9fe9d5070dcb38ad63a291c2d3a83e452799334e1a5754`. Independently checked all 263 members, CRCs and safe paths; 46 structured command-log hashes; 204 retained configuration/report artifacts; 442 candidate and 441 reference input records against their original Git bytes. Only four identical test/catalog overlays supplement the reference. Production `VX_csr_mpm.sv` retains its original reference bytes. Source, tool, reference and generated-configuration records stay equal before/after; all eight Beacon executions precede all eight Yosys confirmations.

## Measured deltas

Each cell uses the same registered live-input wrapper, tools, constraints and declared configuration on both sides. Numbers below are parent → candidate.

| Variant | Beacon LUT | Beacon FF | Beacon depth | Yosys generic cells | Yosys FF cells | Yosys path |
|---|---:|---:|---:|---:|---:|---:|
| RV32, PERF off | 93 → 93 | 193 → 193 | 4 → 4 | 397 → 397 | 168 → 168 | 7 → 7 |
| RV32, PERF on | 1439 → 1439 | 369 → 369 | 8 → 8 | 997 → 997 | 360 → 360 | 10 → 10 |
| RV64, PERF off | 72 → 93 | 193 → 193 | 4 → 4 | 320 → 397 | 144 → 168 | 7 → 7 |
| RV64, PERF on | 1022 → 1439 | 369 → 369 | 8 → 8 | 770 → 997 | 288 → 360 | 10 → 10 |

Every raw Beacon build reports `NO-BASELINE` and exits 1. RV32 comparison exits are 0; RV64 comparison exits are 3 for area: **+21 LUT (+29.2%)** off and **+417 LUT (+40.8%)** on. RAM and DSP counts remain zero. The retained aggregate `gate_outcome` is `fail`.

## Attribution and established cost

| Case | Introducing commit | Mechanism | Cost classification |
|---|---|---|---|
| RV64 off | `58c71d34f316baf47928228069f943ab8a1edd8c` | Restore high-half routes for cycles and instret | Correctness restoration; avoidable combinational cost not yet excluded |
| RV64 on | Same | Restore high-half routes plus CORE counters | Same unresolved cost obligation |

Only `VX_csr_mpm.sv` changes under production RTL. `VX_dcr_data.sv`, its response registers, and protocol are unchanged. The repair reuses the existing RV32 decode; no sequential block, pipeline stage, counter width or unrelated area improvement was added.

The [premeasurement prediction](../agents/w07_a02.md) was 24/72 newly observable register bits. Independently inspecting the retained generic netlists confirms precisely that: reference bits `[43:32]` of the two/six wrapper counter registers are discarded (`x`); candidate bits connect through ordinary DFFs to the corresponding independent input bits. Their total is exactly **2 × 12 = 24** or **6 × 12 = 72**, with no additional FF delta. Returning arbitrary independent high bits at this registered boundary requires retaining them. These are wrapper input registers becoming observable, not new production pipeline registers.

The remaining Yosys increase is **53/155 combinational cells**. Beacon localizes its logic increase to `csr_mpm`; `dcr_data` remains 49 LUT/58 FF. Design totals differ by one LUT from rounded per-unit deltas. Beacon's structural FF accounting already counts the full input registers on the reference; optimized Yosys removes dead high bits. The two FF counts therefore answer different questions and are not interchangeable.

After removing source attributes only, candidate RV64 and both RV32 generic netlists are **exactly structurally equal**, including cell types, connections and bit identifiers. This strengthens attribution and excludes RV64-specific excess relative to the existing RV32 implementation. It does not establish globally minimal combinational cost.

## Open finding and next experiment

**F2, high confidence, missing-test — `docs/bug_fixes.md` §6.5; candidate `hw/rtl/core/VX_csr_mpm.sv`.** The measured area increase is attributed, but its entire combinational portion has not been shown inherent. The current macro repeats low/high address cases. A contract-preserving same-module alternative can normalize the high-selector address bit once, select one complete 44-bit counter through the existing class/index map, then select low/high 32-bit output once. It requires no new state or ABI. No retained experiment compares its cost with this candidate, so equality with historical RV32 cannot close the cheapest-correct-alternative obligation.

Measure that alternative under the same four variants and tools. Preserve unsupported/hole behavior, exact vectors, response schedule and both native backends. If it is cheaper without another regression, fix the decoder in this same change; otherwise retain the counterexample and justify the original cost. Do not edit thresholds or goldens to close this finding.

**R3 verdict: land after this cost obligation and the separate native/integration reviews close.** This review ran no new native build or synthesis. The leaf covers base counters and four live CORE counters; extension classes, full GPU, AFU, placed timing, Liberty area, STA and physical Fmax are outside scope. Original warm qualification, P06-A02/A03 and the inherited DSP finding remain separate.
