# Ordered development backlog

This is the actionable queue, not a second completion ledger. Live phase status,
dependencies and authoritative acceptance text are in [roadmap.json](roadmap.json);
the current handoff is in [status](status.md). Keep work-item IDs stable when
adding issue links or evidence. Role names below are **unassigned responsibilities**:
name an actual owner before starting work, and never imply staff or approval exists.

## Start here: reproduce, then extend

**Next bounded action: P01-T01, followed by P01-T02.** Produce an environment and
provenance manifest plus a reviewed native test matrix. Do not begin by adding
cores, advertising a memory capacity, replacing HIP, or downloading large models.
P01 execution requires accepted P00 and an approved resource/access budget.

The setup checkout had uninitialized third-party submodules and lacked the GPU
toolchain; no GPU workload or vendor-license/platform qualification was performed.
Recheck the actual execution environment rather than treating that snapshot as a
permanent property of the repository. These source-root observations are cheap:

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
All commands in this backlog are instructions, not claims of completed execution.

## Priority 1 — P01 baseline work

Short `Txx` dependency references use the work item's own phase prefix.

| Work item | Deliverable and completion check | Prerequisite / accountable role | Gate supported |
|---|---|---|---|
| **P01-T01 — Environment manifest** | Record exact source/tree and dirty state, all submodule commits, source pins and resolved tool/bundle identities, host/tool availability, effective RAM, free-disk reserve, job/runtime limits and retained-artifact budget. Missing access or licenses remain named blockers. | P00 accepted; verification lead | P01-A01 |
| **P01-T02 — Native matrix** | Freeze a small list of catalog IDs, XLEN, TFR/native versus DPI, dtypes/accumulation, warp geometry, dimensions, reference checks and expected failures. Record the full effective application/backend configuration and review any coverage gaps before adding cases. | T01; compute architecture lead with verification lead | P01-A02 |
| **P01-T03 — Clean build** | Prepare only the approved pinned dependencies, initialize exact submodules, configure a dedicated out-of-tree variant and build the selected path. Retain command exits, tool identities and generated-config hashes; reproduce from a clean checkout. | T01/T02 and resource/access approval; build/toolchain lead | P01-A01 |
| **P01-T04 — Native numerical baseline** | Run selected cases one at a time on SimX and matching native processor RTL. Preserve CPU-reference checks, output logs, exact numerics and applicable parity evidence. Add a focused regression for a missing required combination; do not alter inherited cases to reduce coverage. | T03; verification lead | P01-A02 |
| **P01-T05 — Full AFU integration** | Pin an available XRT emulation platform/tool environment, then prove DMA, launch and completion through full `hw_emu`. Publish its logs and configuration, or an explicit blocked record when unavailable. Processor-only `rtlsim` does not close this item. | T03/T04 plus platform/license access; FPGA platform lead | P01-A03 |
| **P01-T06 — Reviewed baseline packet** | Assemble hashes, exact commands/results, native/DPI distinctions, failures and limitations; obtain independent review, attach each satisfied gate, and update status plus the next task. Close P01 only when all three gates pass. | T01–T05 evidence; verification lead / maintainer | P01-A01, P01-A02, P01-A03 |

### Catalog selection is deliberate

The following are **starting points for P01-T02**, not an accepted matrix or test
results. Read their actual configuration and inherited application defaults:

| Starting point | What to inspect |
|---|---|
| [`tensor.yaml`](../../ci/testcases/tensor.yaml): `sgemm_tcu-3`, `sgemm_tcu-4` | SimX FP16/BF16-to-FP32 patterns; identify or add the matching bounded native-RTL coverage. Nearby DPI cases are not substitutes. |
| [`tensor_wg.yaml`](../../ci/testcases/tensor_wg.yaml): `flash_attn_tcu_wg-fp16` | Native tensor-attention SimX path, precision, dimensions and application-supplied feature flags. |
| Same catalog: `flash_attn_tcu_wg-rtlsim` | Existing RV64 small attention case (`-N 32 -D 16 -c 8 -t 8`); record its actual format and native backend, and the documented parity applicability limit. |

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
