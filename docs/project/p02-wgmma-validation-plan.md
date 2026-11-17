# P02-A03 WGMMA implementation and validation handoff

**Historical proposal for source `c9cf9ba0730f236e110a1d48a54d8f47a9faf9af`.**
The implemented workflow is described in the [WGMMA handoff](p02-wgmma-handoff.md).
This proposal is retained for design provenance; use the handoff and canonical
phase/evidence state for current implementation and qualification status.

Preserve the [canonical gate](roadmap.json) verbatim:

> WGMMA synchronization, metadata, multi-warp and backpressure cases preserve correctness with no unexplained model divergence.

Its verification remains “Concurrency tests and model-parity evidence or documented applicability limits”, at `rtl_verified`. Applicability limits cannot waive
numerical correctness or concurrency obligations ([phase](phases/p02-tensor.md),
[acceptance policy](acceptance.md)).

## Exact existing candidates

Use separate, freshly configured RV64 build trees and identical application/backend
flags. The common configuration is:

```sh
COMMON='-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_THREADS=8 -DVX_CFG_NUM_WARPS=8 -DVX_CFG_ISSUE_WIDTH=4 -DVX_CFG_FETCH_WIDTH=2 -DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_LSU_BLOCKS=1 -DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_WGMMA_ENABLE -DVX_CFG_TCU_TYPE_TFR -DVX_CFG_FPU_TYPE_STD -DVX_CFG_TCU_FP16_ENABLE -DOTYPE=fp32 -DWGMMA_NRC=8 -DKUNROLL=1'
```

Append exactly the listed flags; every row uses `-m64 -n8 -k16` on both `simx`
and `rtlsim`:

| Candidate ID | Application | Appended flags |
|---|---|---|
| dense-fp16-ss-two-ctas-two-k-tiles | `sgemm_tcu_wg` | `-DITYPE=fp16 -DWGMMA_SS` |
| dense-fp16-rs-two-ctas-two-k-tiles | `sgemm_tcu_wg` | `-DITYPE=fp16 -DWGMMA_RS` |
| dense-bf16-ss-two-ctas-two-k-tiles | `sgemm_tcu_wg` | `-DITYPE=bf16 -DWGMMA_SS` |
| dense-bf16-rs-two-ctas-two-k-tiles | `sgemm_tcu_wg` | `-DITYPE=bf16 -DWGMMA_RS` |
| dense-fp16-ss-row-major-a | `sgemm_tcu_wg` | `-DITYPE=fp16 -DWGMMA_SS -DWGMMA_RMAJOR_A` |
| sparse-fp16-ss-metadata-reload | `sgemm_tcu_wg_sp` | `-DITYPE=fp16 -DWGMMA_SS -DVX_CFG_TCU_SPARSE_ENABLE` |

These extend catalog `sgemm_tcu_wg-9`/`sgemm_tcu_wg_sp-8`
([catalog](../../ci/testcases/tensor_wg.yaml)). Geometry is eight threads/warp,
four warps/CTA, two CTAs, per-warp 8×8 outputs, and two K8 tiles. Verify resolved
TFR/STD, four TCU blocks, 16 KiB/eight-bank LMEM, latency four and DSP off.
`NUM_TCU_BLOCKS` must equal issue width; only ALU/LSU/FPU blocks are reduced.
SS is the kernel default; `WGMMA_RS` selects RS for NRC≤16. These configurations
are separate from `p02-tfr`.

## What existing tests establish

The [dense kernel](../../tests/regression/sgemm_tcu_wg/kernel.cpp) refills shared
slabs and executes two barriers per K tile; the
[sparse kernel](../../tests/regression/sgemm_tcu_wg_sp/kernel.cpp) loads metadata
per warp/tile. Existing hosts use seed 50 and an eight-ULP bound at K16, without
complete exact-output records. Two available CTAs do not establish an observed
CTA conflict.

The [unit wrapper](../../hw/unittest/tcu_unit/VX_tcu_unit_top.sv) asserts
`ISSUE_WIDTH==1` and exposes only slot zero. Its
[driver](../../hw/unittest/tcu_unit/main.cpp) sends ordinary WMMA from warp zero,
waits for completion before another packet, and fixes `commit_ready=1`. CTA,
`a_from_smem` and `cd_nregs` are not driven; conditional memory ports lack WGMMA
or metadata stimulus. Consequently it cannot demonstrate overlapping warps,
CTA ownership, downstream stalls or dependency scheduling. The
[tensor wrapper](../../hw/unittest/tensor/VX_tensor_top.sv) is a synthesis sandbox
without an executable driver. Ordinary K16 fixtures prove sequential arithmetic
and tile traversal under a [profile](../../profiles/p02-tfr.json) that disables
WGMMA and sparse metadata; leaf enable holds do not exercise these protocols.

## Required implementation and assertions

Build a focused four-slot `VX_tcu_unit`/`VX_tcu_shared` harness with complete
dispatch/commit fields, deterministic LMEM and metadata-LSU responders, and an
independent transaction scoreboard. Freeze finite schedules before qualification:

1. Skew same-CTA arrivals across slots; overlap multiple warp expansions. During
   an active expansion, present another CTA and assert no conflicting compute
   fire, followed by eventual entry after release. Observe actual ownership
   transitions ([lockstep](../../hw/rtl/tcu/VX_tcu_lockstep.sv)).
2. Hold a pending commit for eight cycles; fill enough work to observe upstream
   backpressure. Assert stable valid, data and identity during every blocked
   beat, exactly-once commits, no loss/duplication and bounded drain. Separately
   hold LMEM request-ready low for eight cycles and delay an accepted response
   eleven cycles. Count each exercised condition; zero coverage fails.
3. Overwrite A/B slabs, reuse descriptors for the second K tile, then change a
   descriptor. Check fresh values, address/stride routing, SS and RS, including
   the declared row-major-A case.
4. Alternate distinctive sparse masks by warp and K tile; delay metadata response
   thirteen cycles. Check request address, response tag/lane mask and metadata
   warp/slot writes, then exact sparse outputs. Separately instrument a full
   processor witness: disassembly must retain adjacent `TCU_LD`→WGMMA dependency;
   observe `XREG_0` busy, zero dependent issues before metadata writeback release,
   and eventual issue afterward. Source adjacency alone is insufficient; direct
   post-scoreboard dispatch cannot prove this ([decode](../../hw/rtl/core/VX_decode.sv),
   [scoreboard](../../hw/rtl/core/VX_scoreboard.sv),
   [AGU](../../hw/rtl/tcu/VX_tcu_agu.sv)).

Use independently reviewed integer fixtures: operands within −7…7, processor
initial +0, and unit accumulators within −31…31 keep K16 sums within ±815.
Compute expected FP32 words independently, including sparse expansion and layout;
do not reuse production packing/arithmetic as the oracle. Require distinct
warp/CTA signatures and sensitivity to stale second-tile data. Compare every
output word and transaction identity. Add two output-poisoned launches per
processor candidate and retain all 512 output words per launch.

## Execution, applicability and budget

First run the dense FP16 SS pilot using generated `./ci/blackbox.sh`, selected
`CONFIGS`, `--driver`, `--app`, `--args="-m64 -n8 -k16"`, and `--perf=11`.
Then qualify the six matched pairs and directed harness after fixture/assertion
review. TCU stall/read counters supplement assertions; they cannot identify
metadata waits or forced backpressure. Retain source/tree, tools, generated
macros, independent runtime/kernel/host compiler records, kernel/disassembly,
raw outputs, commands, coverage and failures.

Compare exact outputs, retired instructions and cycles across matching processor
runs. Existing [parity](../../ci/testcase.py) is RV32-only; preserve its exact
instruction and 5% cycle rule. The existing INT8-m64 pair is supplemental;
FP16 FEDP2K/LDST parity selects DPI. RV64 needs a reviewed bounded comparator
and explicit timing applicability record; do not silently extend that gate or
widen tolerances. Forced unit schedules are separate functional evidence. Scope
is processor RTL, six configurations and one sparse FP16 metadata witness;
MX, other geometries, full AFU and physical hardware remain unqualified.

After the shared compiler budget is released, run one variant at a time with
two compiler workers total, `MAKEFLAGS=-j2`, `THREADS=2`,
`CMAKE_BUILD_PARALLEL_LEVEL=2`, `OBJCACHE=`, `CCACHE_DISABLE=1`, and workspace
`TMPDIR`. Predeclare 15 GiB free-disk reserve, 6 GiB sampled process-group RSS,
16 MiB logs/command, 1,800 seconds/command and 100,000 cycles/directed witness.
Disable VCD; retain and stop on budget breach, mismatch or missing coverage.
Pilot estimates are 5–15 minutes and 2–6 GiB additional matrix storage, not
measurements. Independent review of executed evidence is required before A03
acceptance; this plan changes no gate.
