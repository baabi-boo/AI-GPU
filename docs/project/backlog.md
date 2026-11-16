# Ordered development backlog

This is the actionable queue, not a second completion ledger. Live phase status,
dependencies and authoritative acceptance text are in [roadmap.json](roadmap.json);
the current handoff is in [status](status.md). Keep work-item IDs stable when
adding issue links or evidence. Role names below describe responsibilities;
the active execution owner is recorded in [status](status.md). Later-phase roles
remain unassigned until an actual owner is identified.

## Start here: reproduce, then extend

**Next bounded action: resolve P01-T05's vendor `hw_emu` prerequisite blocker.**
P01-A01's clean generated-build and P01-A02's complete six-case native numerical
packet are independently reviewed and accepted. The environment inventory,
immutable toolchain lock, native matrix and bounded runner are implemented.
FP16/BF16 GEMM and TF32 attention pass on both SimX and native processor RTL;
the fresh FP16 SimX build and supplemental full-AFU integer `xrtsim` smoke also
pass. Identify a qualified vendor release and supported platform, freeze their
identities and resource budget, and retain an actual matching build packet with
production provenance. Check the selected execution route's manifest, review
its inputs and obtain the required DMA/launch/completion evidence through
bounded supervised execution.
Preserve the earlier GCC 14 spdlog/fmt and missing-`ccache` failures.

Follow the [P01 runbook](p01-baseline-runbook.md). The two-worker budget, 15 GiB
disk reserve and per-command memory/log/time limits remain part of the packet.
The [vendor integration guide](p01-xrt-integration.md) now provides the executable
P01-T05 `probe`/`plan`/`run` route. Its strict receipt and artifact checks prepare
the missing vendor run; they do not replace it or grant acceptance.
It requires its own manifest/receipt, CLI budgets and fresh build directory;
there is no automatic adapter from the read-only `hwemu.py` candidate.
P01 remains blocked on A03 and P02 remains not started. Check the actual
execution state and accepted reports before extending the baseline:

```sh
git status --short
git rev-parse HEAD HEAD^{tree}
git submodule status --recursive
python3 ci/project/preflight.py --tier governance
python3 ci/project/preflight.py --tier simulation --json
```

A blocked simulation preflight is a list of prerequisites, not permission to
install everything automatically. The [developer guide](developer-guide.md)
defines separate tool directories, build trees, resource checks and safe cleanup.
Commands in this backlog are instructions; observed outcomes and current blockers
belong in [status](status.md) and the reviewed phase evidence.

## Priority 1 — P01 baseline work

Short `Txx` dependency references use the work item's own phase prefix.

T01/T02 have executable tooling and a frozen contract. T03/T04 are supported by
the accepted [clean-build](evidence/p01-build.json) and
[six-case numerical](evidence/p01-native.json) reports. T06 has retained and
independently reviewed the compact packet, historical failures and attention SS
coverage correction. T05 remains [blocked](evidence/p01-xrt-blocked.json) by
missing vendor `hw_emu` tools/platform. No phase-completion change is justified
while T05 remains blocked. The [handoff](p01-handoff.md) records exact source/tool
identities, review boundaries and the next integration obligation.

T05 now has read-only [inventory/planning tooling](../../ci/project/hwemu.py),
a [vendor-emulation runbook](p01-hwemu-runbook.md), a strict
[manifest/receipt contract](p01-hwemu-manifest.md) and a
[preparation handoff](p01-hwemu-handoff.md). Source, submodule, generated-build,
artifact and resource checks describe a candidate without launching it or
qualifying the vendor environment. The XRT source hook path is corrected and
waveform collection is opt-in. This preparation supplies no new GPU/vendor or
physical result; `planned` does not close T05 or P01-A03.

The reviewed **F1 compiler-glob follow-up is resolved** by the shared
[compiler-record validator](p01-compiler-records.md). It rejects pathname patterns
instead of expanding them and checks actual compiler option boundaries. The XRT
execution inspector now checks each runtime, kernel and host record independently;
definitions consumed as operands or supplied only by another record cannot
establish the frozen configuration. Exact kernel ISA/ABI and generated-runtime
linker checks accompany the correction. Real compiler and generated-Make oracles,
negative cases and runner-boundary tests support the implementation; the
[verification record](evidence/p01-compiler-records/verification.json) and
[current handoff](p01-compiler-records-handoff.md) retain its tested identity,
review and delivery state.

This completes a bounded T05 tooling correction. Actual producer records,
vendor/platform qualification and independently reviewed effective invocations
remain required before supervised execution. The preparation candidate gains no
launch readiness, T05 remains blocked on vendor integration, and P01 gates remain
unchanged.

| Work item | Deliverable and completion check | Prerequisite / accountable role | Gate supported |
|---|---|---|---|
| **P01-T01 — Environment manifest** | Record exact source/tree and dirty state, all submodule commits, source pins and resolved tool/bundle identities, host/tool availability, effective RAM, free-disk reserve, job/runtime limits and retained-artifact budget. Missing access or licenses remain named blockers. | P00 accepted; verification lead | P01-A01 |
| **P01-T02 — Native matrix** | Freeze a small list of catalog IDs, XLEN, TFR/native versus DPI, dtypes/accumulation, warp geometry, dimensions, reference checks and expected failures. Record the full effective application/backend configuration and review any coverage gaps before adding cases. | T01; compute architecture lead with verification lead | P01-A02 |
| **P01-T03 — Clean build** | Prepare only the approved pinned dependencies, initialize exact submodules, configure a dedicated out-of-tree variant and build the selected path. Retain command exits, tool identities and generated-config hashes; reproduce from a clean checkout. | T01/T02 and resource/access approval; build/toolchain lead | P01-A01 |
| **P01-T04 — Native numerical baseline** | Run selected cases one at a time on SimX and matching native processor RTL. Preserve CPU-reference checks, output logs, exact numerics and applicable parity evidence. Add a focused regression for a missing required combination; do not alter inherited cases to reduce coverage. | T03; verification lead | P01-A02 |
| **P01-T05 — Full AFU integration** | Qualify the vendor release/platform, retain an actual matching build packet, check its strict manifest and review the candidate before bounded supervised `hw_emu` execution. Prove DMA, launch and completion with retained logs/configuration, or preserve an explicit blocked record. Planning and processor-only `rtlsim` do not close this item. | T03/T04 plus platform/license access; FPGA platform lead | P01-A03 |
| **P01-T06 — Reviewed baseline packet** | Assemble hashes, exact commands/results, native/DPI distinctions, failures and limitations; obtain independent review, attach each satisfied gate, and update status plus the next task. Close P01 only when all three gates pass. | T01–T05 evidence; verification lead / maintainer | P01-A01, P01-A02, P01-A03 |

### Frozen catalog-derived matrix

[`p01_baseline.json`](../../ci/project/p01_baseline.json) is the execution contract.
Its strict [loader](../../ci/project/baseline_matrix.py) checks paired coverage,
native arithmetic, dimensions and inherited numerical tolerances. Both drivers
use the same explicit configuration for each workload; native RTL coverage added
by the matrix is identified as derived coverage, without changing inherited cases.

| Catalog source | Frozen P01 coverage |
|---|---|
| [`tensor.yaml`](../../ci/testcases/tensor.yaml): `sgemm_tcu-3` | FP16-to-FP32 GEMM, `64 × 64 × 64`, on SimX and processor RTL |
| Same catalog: `sgemm_tcu-4` | BF16-to-FP32 GEMM, `64 × 64 × 64`, on SimX and processor RTL; the existing DPI RTL case is not a substitute |
| [`tensor_wg.yaml`](../../ci/testcases/tensor_wg.yaml): `flash_attn_tcu_wg-rtlsim` | RV64 TF32-to-FP32 attention, `-N 32 -D 16 -c 8 -t 8`, on both drivers; no FP16 attention result is implied |

Use [baseline.py](../../ci/project/baseline.py) to plan and execute these six
cases after following the runbook. A plan or a partial selected run cannot close
P01. Preserve the separate native processor and full-AFU integration obligations.

After the environment is prepared, inspect selection from the **configured build
tree**, without running the workloads:

```sh
python3 -m pytest ci/test_runner.py --collect-only -q -m 'tensor and simx' --strict-markers
python3 -m pytest ci/test_runner.py --collect-only -q -m 'tensor_wg and rtlsim' --strict-markers
```

Collection requires the catalog's pytest/PyYAML environment and is not a build or
numerical pass. Record the selected node IDs, review their cost, then execute only
the approved nodes. The generated `ci/regression.sh --test '<marker expression>'`
runs a **slice**, potentially many cases; it is not automatically a bounded smoke
test. Do not use `--all` as the first baseline run. Any proposed `ai-dev` profile
remains an unqualified candidate until its selected configuration earns evidence.

## Priority 2 — Native AI software after the baseline

These items are planned and obey their parent phase's entry gates; preparation
does not count as acceptance. Detailed work packages remain in the phase guides.

| Work item | First bounded deliverable | Entry / accountable role | Gates |
|---|---|---|---|
| **P02-T01 — Arithmetic contract** | Version FP16/BF16-to-FP32 native semantics, supported layouts and independent fixtures; freeze tolerances before evaluation. | P01; compute architecture lead | P02-A01 |
| **P02-T02 — Arithmetic and concurrency proof** | Add normal/edge/cancellation cases and WGMMA synchronization/backpressure coverage; retain native RTL and applicable parity evidence. | T01; verification lead | P02-A02, P02-A03 |
| **P03-T01 — Operator contract** | Define the smallest model-relevant operator/signature matrix and explicit rejection/error/ownership rules over the existing native runtime. | P02; kernel and runtime lead | P03-A01 |
| **P03-T02 — Operator implementations and lifetime tests** | Reuse inherited kernels; independently verify each advertised operator, dispatch, bounds, queue/event lifetime and failure cleanup. | T01; kernel and runtime lead | P03-A02, P03-A03 |
| **P04-T01 — Fixed tiny model** | Freeze a redistributable model or deterministic generator, hashes, inputs, licenses and layer/reference outputs; map every operation to the accepted library. | P03; model runtime lead | P04-A01 |
| **P04-T02 — Native model execution** | Compose the fixed model, compare intermediates/final output, and retain device-dispatch and transfer traces with allowed host work explicit. | T01; model runtime lead | P04-A02, P04-A03 |
| **P05-T01 — Python/custom-op bridge** | Bind the accepted native path, test representations/lifetimes/errors and clean installation, reproduce the model, then publish tested versions and limitations. | P04; framework integration lead | P05-A01, P05-A02, P05-A03 |

Use [P02](phases/p02-tensor.md), [P03](phases/p03-operators.md),
[P04](phases/p04-inference.md) and [P05](phases/p05-framework.md). A custom-op
bridge is not a full device backend, CUDA compatibility, autograd or training.

## Later work — gated, not forgotten

| Queue | First decision or deliverable | Entry / accountable role |
|---|---|---|
| **P06-T01 — Measured optimization** | Freeze benchmarks and resource targets; optimize a demonstrated bottleneck with before/after correctness and performance evidence. | P04; performance and memory lead; [P06 gates](phases/p06-performance.md) |
| **P07-T01 — One physical FPGA** | Obtain an authorized board/platform decision; prove usable memory, DMA and the model on `hw`, followed by the specified initial soak. | P04/P06; FPGA platform lead; [P07 gates](phases/p07-fpga.md) |
| **P08-T01 — Experimental release qualification** | Freeze a threat/failure model, test recovery/isolation, complete the specified physical soak and reproduce the release packet. | P05/P07; reliability and release lead; [P08 gates](phases/p08-reliability.md) |
| **P09-T01 — Optional research branch** | Select a bounded training/gradient workload and two-device transport experiment; obtain physical correctness evidence before scaling claims. | P08; research lead; [P09 gates](phases/p09-research.md) |
| **P10-T01 — ASIC feasibility decision** | Qualify PDK/macros/IP/package/tool access and owners; develop sign-off, cost and risk evidence for a human go/no-go decision. | P08; silicon program lead; [P10 gates](phases/p10-asic.md) |
| **P11-T01 — Authorized silicon program** | Only after funded approval, complete qualified sign-off/manufacturing and measured board/silicon bring-up. | P10; silicon program lead; [P11 gates](phases/p11-silicon.md) |

P09 is not a prerequisite for the bounded inference-ASIC route. No queue entry
authorizes purchases, paid IP, partner commitments or tapeout. Resolve open
[decisions](decisions.md) and [risks](risks.md) before those commitments.

## Stop and hand off correctly

Stop an affected item for missing access/budget, stale or mismatched configuration,
unexplained numerical differences, hidden CPU fallback, resource overrun or absent
required evidence. Preserve failures; never widen tolerances, edit goldens or
rename emulation as physical hardware to close work. Follow [acceptance](acceptance.md).

Every work-item handoff records the actual owner, exact revision/configuration,
commands and observed outcomes, compact hash-checked artifacts, review disposition,
unresolved blockers and **one next bounded action**. Update the canonical phase
evidence and [status](status.md) together. A completed task or agent count alone
does not complete its phase.
