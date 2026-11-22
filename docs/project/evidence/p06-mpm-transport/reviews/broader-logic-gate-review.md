# Broader logic-gate failure attribution

**Disposition: the tensor DSP gate remains failed; this is the documented inherited area finding, with no new MPM regression established.** Retain the scoped transport repair. This review neither waives the tensor failure nor grants full-CI, P06 phase, or physical-design acceptance.

Reviewer: `/root/w10_a03`; observation: **2026-11-22 05:03:37 UTC**.

## Actual failure and historical comparison

The [current job 137094134318](https://github.com/baabi-boo/AI-GPU/actions/runs/44983573278/job/137094134318) ran `ci/logic_gate.py -j 2` at XLEN32, executing the 14 default Beacon builds. **13 pass; tensor alone fails:** DSP **267 → 283 (+6.0%)**, exceeding the unchanged **5%** tolerance. The command exits 1. Its [complete retained log and index](../hosted/broader-logic-gate.json) bind 95,492 UTF-8 bytes, SHA-256 `b26ba3a4e0846202863b42bae26f925a8cb78a63eab2cfd8192c44511218be6e`.

I independently retrieved the completed [historical job 136199969543](https://github.com/baabi-boo/AI-GPU/actions/runs/44705486919/job/136199969543), whose checkout is `10ace66193686e3862c3c218760b66c044f1d4ae`. It has the **same 14 verdicts and every displayed circuit metric**; only some elapsed times differ. Both tensor rows report 259,593 LUT, 161,523 FF, 114.5 BRAM, 283 DSP, maximum depth25 and estimated Fmax253.4. These are reported Beacon estimates, not placed timing. The complete historical [index](../hosted/broader-logic-gate-prior.json) and [compressed log](../hosted/broader-logic-gate-prior.log.gz) retain 136,438 UTF-8 bytes. The [machine-readable review](broader-logic-gate-review.json) binds both final index SHA-256 hashes and independently verified compressed/uncompressed log hashes.

The [P04 executor audit](../../../p04-executor-audit.md) already records this exact failure. The [earlier audit](../../../p04-audit.md) documents matching failures at `fd80375`, `9006939` and the subsequent P03 audit. This review directly reread the 10ace job; it did not reread every older job or run a historical bisect.

## Source, configuration and tool boundary

The current PR job executed merge `6e6426a0bf761baab11e932a4c86b49a5de81217`, tree `d6dd742a905e0f3e76c7374cc678ba87e5c2a19e`, for candidate `18c888058ac851b802350c99770ed9ac2d27b582`. Published `16c359c2fe55995e41406a7a9177bd73ba604ebb` has identical `hw/`, `sim/`, `ci/` and workflow bytes to that candidate.

Historical10ace and baseline `4df7186edbca82b21b2b8cba9b3b192248b99209` share the complete RTL tree `5bd5f829d605ffa16a43ec98577612c8b43611eb`. Tensor wrapper/core, configuration, Beacon implementation/calibration, tensor golden and toolchain inputs are unchanged through publication. Removing the four new opt-in MPM entries makes the current logic-gate catalog semantically identical to the historical catalog; tensor still uses XLEN32, 16 threads/warps and the unchanged tensor target at250MHz.

Both logs resolve toolchain tag `v3.0.2` to `6cff3efdc1b721e4fec9165801ecd405be34dd11` and download the same named 4,804,521-byte FoldSim archive. Historical/current cache profiles are **full/lite**, respectively. These logs do not hash the synthesis executables, so this comparison does **not** assert byte-identical tool installations.

## Why the MPM change is excluded

`VX_tensor_top.sv` instantiates the tensor, LSU/memory, DXA and cache slice without `VX_core`. The only production instantiation of `VX_csr_mpm` is inside `VX_core`; the edited decoder is therefore outside this tensor hierarchy. SimX C++ is not an input to RTL synthesis.

Independently, the edited decoder retains the old RV32 low/high macro; at XLEN32, both old XLEN-based widths and new DCR widths equal32. No sequential logic changes. The [paired-circuit review](circuit-review.md) measured identical parent/candidate RV32 results with PERF off/on: Beacon LUT93/1439, FF193/369, depth4/8, DSP0; generic cells397/997 and paths7/10. Attribute-stripped generic netlists also match. These controls support this narrow exclusion; they do not establish full-GPU physical equivalence. The separate [alternative-cost review](alternative-review.md) closed the repair's own cost-comparison obligation.

## Classification and readiness

**Inherited F2, measured area regression:** tensor DSP remains283 against267. The original introducing cause remains unproved. The earlier audit's wider MX scale-index arithmetic hypothesis at `1a898f7fb292e2b554ddd5c2065710a6cb5faba5` is still a static candidate, not a measured causal attribution.

This job establishes no new transport rollback blocker. It prevents any claim that broader CI is green or tensor cost is accepted. A separate tensor correction needs matched historical/parent measurements and equivalent arithmetic without reintroducing the index-width bug. No golden, threshold, source, workflow or previous snapshot was changed here. No new synthesis, native run, commit, remote mutation or additional agent was used.
