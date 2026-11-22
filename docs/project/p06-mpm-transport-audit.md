# P06 host counter transport audit

## Starting point and decision

This continuation audited the authorized `baabi-boo/AI-GPU` `master` branch at
`4df7186edbca82b21b2b8cba9b3b192248b99209`. The isolated checkout was clean.
The roadmap has P00/P02/P03/P04 complete, P01 blocked, P05/P06 in progress,
and P07–P11 not started. Source presence, a passing job, and accepted native
evidence remain different claims.

The highest-priority bounded development step is the inherited RV64 host MPM
high-half defect identified by `P06-WARM-RV64-MPM-HIGH-HALF`. The warm benchmark
already enforces a qualification block for that defect. The installed
`vx_device_mpm_query` assembles a 64-bit result from two 32-bit DCR replies,
but the RV64 model and host-only RTL decoder omit the high-half read while
returning success. An apparently monotonic low half cannot prove a correct
cycle comparison. Repair the transport before evaluating further performance
optimizations.

## Audit findings and boundaries

| Finding | Development consequence |
|---|---|
| `sw/runtime/common/perf.cpp` sends low and high tags over a fixed 32-bit host bus. | Preserve the public API, tags, addresses, and response width. |
| `sim/simx/core.cpp` maps the high tag to a CSR alias which RV64 `CsrUnit::get_csr` does not supply. | Select the requested half of the full low-address RV64 value in the host adapter. Preserve the RV32 route and device instruction semantics. |
| `hw/rtl/core/VX_csr_mpm.sv` uses an XLEN-dependent decoder despite being host-only. | Decode both 32-bit halves independently of XLEN, with zero extension above the implemented 44-bit counter width. |
| `VX_csr_data` is a separate architectural CSR path. | Do not introduce RV64 high CSR aliases or truncate device reads. |
| Existing warm analysis deliberately remains blocked. | Preserve historical records and the qualification block. A new source fix cannot retroactively supply missing high bits. |
| The existing general parity catalog defaults to RV32. | Add explicit RV64 boundary coverage; a small ordinary workload alone cannot exercise the high-half bug. |
| The local environment initially lacks Verilator and synthesis tools. | Prepare only the pinned narrow tools within the existing resource budget; avoid a whole-GPU build. |

The initial project-governance preflight and structure check passed; these are
metadata checks, not GPU execution. Hosted project-specific workflows for the
starting revision were successful, including the warm workspace job
[44977488154](https://github.com/baabi-boo/AI-GPU/actions/runs/44977488154).
The general CI run was queued at initial inspection. Existing original-artifact
acceptance is retained at its original source.

P05 custom-op artifact review, vendor P01-A03, P06-A02/A03, the inherited DSP
area finding, physical FPGA work, and silicon work remain separate obligations.
No numerical fixtures, tolerances, performance goldens, phase gates, or upstream
assets are changed to make this repair pass.

## Execution organization

Ten waves each contain six distinct agent assignments. With three worker slots,
each wave runs in two batches. The work covers source tracing, boundary design,
paired implementation, native harnesses, build and CI integration, adversarial
testing, timing/resource comparison, independent review, documentation, and
publication verification. Only completed receipts under
`evidence/p06-mpm-transport/agents/` count as completed work; the final ledger
must reconcile the actual assignments and their results.

The primary agent integrates changes and owns commits and publication to
`master`. Workers own disjoint files or conduct read-only reviews. The tested
source, exact commands, failures, omissions, and remaining qualification limits
will be retained in the evidence packet before final delivery.
