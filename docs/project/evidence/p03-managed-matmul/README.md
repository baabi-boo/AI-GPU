# P03 managed matmul qualification

**P03-A02 and P03-A03 are accepted for the six declared signatures.** Together
with the preserved [historical A01 contract acceptance](../p03-operators/acceptance.json),
these results complete P03-T02 and P03. The next bounded action is P04-T01's
model/fixture freeze; P04 remains `not_started`.

The tested source is `319ad63532cee17ae88fa75757a5ac87ed5c6a77`, tree
`d7768f5f392cef417e59ccadfc29f20d3f67f707`. Source, tools, dependencies and built
artifacts remained unchanged during the formal runs and independent review.
The subsequent closeout changes documentation, evidence and the manifest's
next-action prose; [source-map.json](source-map.json) identifies the unchanged
implementation bytes. Earlier local implementation commit `b066586` and all
blocked/interrupted work remain separate history.

## Accepted results

| Result | Observed scope |
|---|---|
| [P03-A02](acceptance-numerics.json), `rtl_verified` | Four builds: FP16/BF16 on SimX and native processor RTL; 176 case executions, 352 actual launches, 14,336 exact output-word comparisons |
| [P03-A03](acceptance-lifecycle.json), `simulated` | Twelve actual SimX lifecycle groups in each of RV64 `p02-tfr` and default RV32; separately scoped host mock tests |
| Full host suite | 1,669 tests, zero errors/failures/skips, 427.714 seconds; the 45 P03 tests are included in that total |
| Process evidence | All 210 matrix command receipts passed, with complete cleanup and no resource-budget stop |
| Independent review | [Qualification review](qualification-review.json) verifies raw results and exact provenance; [implementation/policy review](implementation-review.json) resolves required source and CI obligations |

Support is ordinary dense matmul with FP16 or BF16 inputs, FP32 accumulation and
output, and `(M,N,K)` equal to `(8,4,8)`, `(8,4,16)` or `(16,8,16)`. A is compact
row-major, B compact column-major, D row-major, and initial C is exact positive
zero. All other operator families remain explicitly unavailable.

The operator profile is RV64 `profiles/p02-tfr.json`, one cluster/core, four
warps/threads, issue width one, ordinary native TFR WMMA and STD FPU, tile
`8x4x8`, and `KUNROLL=1`. WGMMA, sparse and other format banks are disabled.
The unchanged 88 independent P02 fixtures supply expected bits; each backend
executes all fixtures twice with different output poisons. The independent
reviewer reproduced those fixtures and reconstructed wire payloads and every
raw-word comparison without reusing the new output parser.

## Retained files

[archive-index.json](archive-index.json) gives SHA-256 and size for each archive
and every member. Archive ownership/timestamps are normalized; the actual
report, configuration, source and log bodies are byte-exact.

| File | Contents |
|---|---|
| [execution.tar.gz](execution.tar.gz) | Finished numerical report, all 210 raw logs, separate compiler records, source/tool snapshots, binding records and retained source/configuration bodies |
| [host-tests.tar.gz](host-tests.tar.gz) | Full 1,669-test log, governance and software-boundary logs, process/source receipt and exact host verification helper |
| [rv32-lifecycle.tar.gz](rv32-lifecycle.tar.gz) | Actual default RV32 configuration, source/tool/artifact stability, 201 canonical inputs from 41 compiler dependency files, lifecycle logs and exact helper |
| [reviews.tar.gz](reviews.tar.gz) | Independent numerical/lifecycle audit scripts and receipts, source/policy reviews, base-revision classifier and correction evidence |
| [development-history.tar.gz](development-history.tar.gz) | Earlier failures, preflight block, explicitly interrupted attempts and their retained logs/receipts; none supports acceptance |
| [summary.json](summary.json) | Machine-readable support, results, resource observations, review identities and limitations |

Paths in original receipts are relative to the task workspace. For example,
`p03-formal-results/report.json` maps to `execution.tar.gz` member `report.json`;
`p03-formal-host/verification.json` maps to the same member name in
`host-tests.tar.gz`; `p03-rv32/final-evidence/report.json` maps to `report.json`
in `rv32-lifecycle.tar.gz`. Review paths below `p03-review/` map to the same
suffix in `reviews.tar.gz`. These mappings preserve original receipt hashes.
Non-sensitive ephemeral workspace paths remain in raw commands and bindings;
no credentials or private account data are required to use the packet.

The packet identifies built GPU binaries, libraries and tools by hash. It is
source/configuration/raw-result evidence, not a binary-replay archive. Reproduce
from the tested commit using the fresh-build command in the
[handoff](../../p03-operators-handoff.md), with the identified dependencies and
matching toolchain. No toolchain download or whole dependency rebuild was
performed in this qualification.

## Lifecycle and failure meaning

Actual SimX runs exercise buffer bounds, invalid wait lists, retained timeouts,
fourteen skipped/sticky command variants, invalid-unmap errors, host/module
allocation unwind, three DMA allocation-failure stages, scratch cleanup and
32 transfer/release cycles. Each run frees 96 uncached scratch slots during
the deliberate pool-allocation failure. The late DMA failure occurs after
descriptor publication; reading a seeded destination before any replacement
write proves that the failed descriptor is not replayed. Device allocator
bytes and handle reference counts return to their expected baselines.

The raw RV32 `configuration.cache_enabled=false` field refers to **compiler
caching** through `CCACHE_DISABLE=1`. Its exact compiler flags have processor
instruction and data caches enabled. TCU and virtual memory are disabled in
that default RV32 configuration. The synthetic lifecycle images are never
executed, and that run builds no GPU kernel.

Nine managed-wrapper host tests separately inject device-loss, cleanup and
enqueue failures. Their sentinel arithmetic is not GPU numerical evidence.
Actual SimX transfer failures cover backend/common host-region registration and
software-CP copy-scratch allocation. They do not prove arbitrary simulator or
physical bus/device-loss recovery, rollback of partial DMA, exhaustive backend
constructor safety or whole-process heap-leak freedom. A timed-out operation
retains resources; destruction drains indefinitely if a backend never completes.

## Resource and acceptance limits

Builds used two jobs, a 15 GiB disk reserve, a 6 GiB polled process-group RSS
budget and a 16 MiB log limit per command. The matrix's highest sampled RSS was
1,484,550,144 bytes (about 1.38 GiB); 54,525,153,280 bytes (about 50.8 GiB) remained
free afterward. Polled limits do not establish instantaneous resource maxima.

Native processor RTL bypasses the AFU; integer DPI helpers remain. This packet
establishes no vendor `hw_emu`, physical FPGA recovery or performance, synthesis,
PPA, silicon or general-model result. The synchronous software-CP correction
does not change successful tick ordering; no additional `model_parity` run or
new timing claim is made. P01-A03 remains blocked and is required before P07
can close.

Independent agent engineering review supports these bounded acceptance records.
The originating user authorized implementation, commit and direct master push.
No human code review, waiver, procurement or manufacturing approval is asserted.
