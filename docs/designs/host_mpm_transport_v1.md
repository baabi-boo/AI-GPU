# Host MPM transport v1

**Contract frozen before native evaluation; execution qualification is pending.**
This contract repairs the host counter-width behavior audited at
`4df7186edbca82b21b2b8cba9b3b192248b99209`. Results belong in the
[transport evidence packet](../project/evidence/p06-mpm-transport/agents/),
with actual source/configuration identities and explicit omissions. This file
does not accept a performance hypothesis or close a phase gate.

## 1. Stable host wire contract

[`vx_device_mpm_query`](../../sw/runtime/common/perf.cpp) returns a `uint64_t`
assembled from **two unsigned 32-bit DCR replies on both RV32 and RV64**.
The API, DCR width, addresses, tag layout and request/response protocol remain
unchanged; [`VX_types.toml`](../../VX_types.toml) defines their values.

| Field | Contract |
|---|---|
| DCR read address | `VX_DCR_BASE_MPM_VALUE = 0x001` |
| Public CSR argument | `0xB00 <= addr < 0xB20`; index `i = addr - 0xB00` |
| Tag | Class `[29:22]`, selector `[21:16]`, core `[15:0]`; supported callers leave `[31:30]` zero |
| Low selector/address | `i` / `0xB00 + i` |
| High selector/address | `i + 32` / `0xB80 + i`; high tag differs by `0x00200000` |
| Reconstruction | `lo = uint32_t(value)`; `hi = uint32_t(value >> 32)`; `(uint64_t(hi) << 32) | lo` |

For CORE class 1, index 3, core 1, the tags are exactly
`0x00430001` and `0x00630001`. The public API accepts the low address only;
`0xAFF`, `0xB20` and `0xB80` return `VX_ERR_INVALID_VALUE`. Null-device and
null-output errors, low-then-high order, first-error propagation and publication
of the output only after successful reads remain unchanged. Public
`core_id = 0xffffffff` sums reconstructed per-core values using the existing
unsigned 64-bit accumulation; it is not a broadcast DCR core selector.

Exact reconstruction requires serialized reads while the relevant counters
remain stable across both halves and, for a sum, across the core sequence.
This repair supplies **no atomic snapshot, rollover retry, concurrent-caller
ordering guarantee or absolute no-wrap proof**. Complete the workload before
sampling and retain that boundary in measurement evidence. Moving-counter and
shared-response concurrency hazards identified in the
[audit](../project/evidence/p06-mpm-transport/agents/w01_a01.md) remain separate.

## 2. Width and architectural CSR preservation

[`VX_csr_mpm`](../../hw/rtl/core/VX_csr_mpm.sv) is the host-only decoder.
It must decode both halves independently of XLEN and use the DCR response
width. RTL counters remain **44 bits**: high replies contain bits `[43:32]`
in `[11:0]`, with `[31:12]` zero. No counter-width or latency change is implied.

SimX counters remain **`uint64_t`**, including bits above bit 43.
[`Core::dcr_read`](../../sim/simx/core.cpp) selects the requested half of the
full low-address value on RV64; RV32 retains the existing low/high CSR route.
The temporary MPM class must be restored after each supported host read.
Do not truncate SimX to RTL width or globally change the CSR decoder macro.

Architectural device reads keep their existing behavior in
[`CsrUnit`](../../sim/simx/csr_unit.cpp) and
[`VX_csr_data`](../../hw/rtl/core/VX_csr_data.sv): RV32 cycle/instret reads use
low/high aliases; RV64 low addresses return the full implemented value and
high aliases remain zero for supported classes. RTL device user-MPM slots
remain zero; SimX retains its existing device user-class decoding. The host
repair introduces no new architectural CSR alias.

## 3. Classes, selectors and routing

Cycles (index 0) and instret (index 2) work independently of the selected class
and of RTL `PERF_ENABLE`. User counters retain their existing mappings:

| Classes | Supported user-counter behavior |
|---|---|
| BASE `0` | User slots return zero |
| CORE `1`, ICACHE `3`, DCACHE `4`, L2 `5`, L3 `6`, MEM `7` | Existing mapped counters; unmapped slots return zero |
| TCU `11`, RASTER `12`, TEX `13`, OM `14`, RTU `15`, DXA `16` | Existing mappings when the corresponding extension is enabled |

With RTL PERF disabled, every user slot returns zero. SimX's existing
user-counter decoding is not conditioned on RTL's PERF gate; tests must not
invent cross-backend equality for that configuration. Reserved classes and
disabled extension classes are outside supported user-counter queries:
existing RTL reads return zero, while SimX aborts. Characterize class `2` and
`255` in bounded negative tests; do not redefine these outcomes as part of the
width repair.

The raw tag targets one existing 16-bit core ID. Wider routing checks use
unequal per-core seeds and name the socket/cluster boundaries actually tested.
Shared cache/memory counters may legitimately agree between cores. A missing core
currently leaves SimX output unchanged with success and produces no RTL
response; characterize this with a sentinel and bounded timeout, without
claiming new public invalid-core validation.

## 4. Independent exact vectors

These are the frozen hexadecimal vectors from the
[independent boundary audit](../project/evidence/p06-mpm-transport/agents/w01_a05.md).
Compare actual low reply, high reply and reconstruction separately, with no
tolerance. Hold seeds stable; use low-first, high-first and repeated reads,
then alternate unequal neighboring counters/classes/cores to expose stale or
swapped replies and selector leakage.

| Counter seed | Low reply | High reply | Scope |
|---|---|---|---|
| `0` | `00000000` | `00000000` | RTL and SimX |
| `1` | `00000001` | `00000000` | RTL and SimX |
| `ffffffff` | `ffffffff` | `00000000` | RTL and SimX |
| `100000000` | `00000000` | `00000001` | RTL and SimX |
| `100000001` | `00000001` | `00000001` | RTL and SimX |
| `abc12345678` | `12345678` | `00000abc` | RTL and SimX |
| `fffffffffff` | `ffffffff` | `00000fff` | RTL and SimX; 44-bit maximum |
| `100000000000` | `00000000` | `00001000` | SimX only |
| `fedcba9889abcdef` | `89abcdef` | `fedcba98` | SimX only |
| `ffffffffffffffff` | `ffffffff` | `ffffffff` | SimX only |

## 5. Required regression boundaries

Each row below requires execution of both native targets, not compilation alone:

| XLEN | PERF | Required counter coverage in both native backends |
|---|---|---|
| 32 | Off | Cycles, instret; RTL user-slot zero |
| 32 | On | Cycles, instret and representative CORE counters |
| 64 | Off | Cycles, instret; RTL user-slot zero |
| 64 | On | Cycles, instret and representative CORE counters |

The SimX target links the actual model and calls
`Processor::dcr_read` through cluster/socket/core and `CsrUnit`; controlled
counter injection must not replace that route. It also checks architectural
cycle/instret values and class restoration. The RTL target instantiates actual
`VX_dcr_data` plus `VX_csr_mpm`, drives raw tags and independent nonconstant
counter/perf inputs, and observes the DCR response. Check reset, matched and
unmatched core selection, response validity and the unchanged registered
response schedule. This leaf does not exercise `VX_csr_data` or the full AFU.

Run the applicable vectors for cycles and instret. With PERF on, use unequal
CORE seeds at index 3 and another mapped index; exercise both halves and
BASE user zeros. Check CORE's last mapped index 30 and holes 1/24/25/31 where
the harness exposes those inputs. TCU/other enabled-class index-3 checks,
exhaustive selector sweeps, wider core/socket/cluster topology and unsupported
class behavior are supplemental independent coverage. Declare exact extension
flags and untested selectors/topologies; a representative pass does not qualify
every class. A separate test links the actual
public reconstruction implementation to a controlled DCR responder for tag,
ordering, error, invalid-address and all-core sum checks; this is host-runtime
evidence, not an end-to-end native public-runtime execution.

At least one deterministic **RV64 high-half assertion must fail on the old
production implementation and pass on the repair in each native backend**.
Use the same harness, vectors, tools and configuration on both revisions;
retain the expected nonzero test exit and exact mismatched reply. For example,
seed `100000000` requires high reply `00000001`, while the old route returns
zero. A model copied into a test, a compile failure or a host-only mutation
cannot supply this evidence.

Use freshly configured separate XLEN/PERF trees, explicit run targets, bounded
timeouts and `THREADS=1`; PERF off means unset/empty, not `PERF=0`.
Retain all eight minimum executions with source/tool/configuration hashes,
commands and exits, plus any additional enabled-extension runs. Missing mandatory
coverage remains `not_run`/`blocked`. Keep applicable model-parity evidence
separate: an RV32 default parity case cannot establish RV64 high-half behavior.

## 6. Narrow timing and resource comparison

Use the same live-input, registered-boundary DCR/MPM wrapper in both synthesis
catalogs. Run **parent/head Beacon comparisons first**, explicitly covering
RV32/RV64 and PERF off/on, with live cycles/instret and CORE inputs matching
the native matrix. Additional extension comparisons are separately scoped. Confirm the
changed leaf with **paired parent/head Yosys** reports under identical tools,
wrapper, configurations and constraints; retain depth, area/resource deltas
and the inputs needed to reproduce them. The broken parent must keep its
original decoder; adding the identical test wrapper does not repair it.

Restoring formerly absent RV64 high-half logic may have an area/depth cost.
Report any measured increase and identify the restored logic; require a
reviewed explanation on the repair's own terms. Do not label an increase zero,
substitute an unrelated improvement, weaken a threshold, edit a golden or
turn a red gate into a pass. Preserve failed/unrun comparisons and the required
review disposition. These narrow estimates establish neither placed timing
nor physical performance; whole-GPU synthesis is not part of this leaf scope.

## 7. Historical and acceptance boundaries

Preserve the cold contract's execution pins, including `sim/simx/core.cpp`.
Changed current source must still fail its execution loader; historical
analysis uses its separate reviewed loader and replay checks the retained
original execution bytes. Preserve all warm v1 pins, analyzer/replay rejection
tests and the unconditional `P06-WARM-RV64-MPM-HIGH-HALF` block with
`qualified=false` and `absolute_no_wrap_bound="not_established"`.
The warm semantic pins alone do not identify the repaired transport; future
evidence must bind the complete source/build/archive.

A repair cannot recover missing high bits in historical low-word records.
Future warm qualification needs an independently reviewed qualification layer
that rejects old or source-mismatched packets, followed by a fresh complete
matched attempt under unchanged statistical rules. Original acceptance scopes,
P06-A02/A03, P01-A03, P05-A02/A03 and the inherited DSP finding remain separate.
No native, synthesis or performance pass is asserted by this contract.
