# P01 — Reproducible baseline

Live status and authoritative gates are in [roadmap.json](../roadmap.json).
Dependency: **P00**. Accountable role: **Verification lead**.

## Implementation checkpoint

P01 is `in_progress`; its acceptance evidence array is still empty. The
[runbook](../p01-baseline-runbook.md) now connects an immutable
[toolchain lock](../../../ci/project/p01_toolchain.lock.json), verified
[bootstrap](../../../ci/project/baseline_bootstrap.py), frozen
[six-case native matrix](../../../ci/project/p01_baseline.json) and bounded
[execution runner](../../../ci/project/baseline.py). Provenance, configuration,
process-limit and failure-retention tests exercise this tooling independently of
GPU workloads.

The clean execution source is `03181532b81fe95b1cfeac2ffb25d8597af689b2`.
Pinned submodules/tools and dependency, kernel-library and runtime builds are
prepared. An initial FP16 SimX build failed in the pinned spdlog/fmt dependency
under GCC 14.2 before the workload ran; its failure is retained while a verified
host compiler is prepared. Native numerical results and their review remain
outstanding. Full vendor XRT `hw_emu` is blocked by missing tools/platform, so
neither processor RTL nor supplemental `xrtsim` can close P01-A03.

## Goal and boundary

Reproduce inherited AI building blocks on pinned configurations before changing
their behavior. Source files, historical upstream results and successful
configuration generation are not evidence that this baseline builds or runs.
Physical-board performance and new model/framework features are later work.

## Entry conditions

- P00 acceptance is complete and an actual verification owner is identified.
- Read the [baseline](../baseline.md), [developer guide](../developer-guide.md)
  and [verification plan](../verification.md).
- Approve the execution environment, storage/memory/job budget and required
  dependency access before downloading tools or starting substantial builds.
- Use separate out-of-tree build directories for incompatible ISA/configuration
  variants; initialize exact submodule revisions and retain tool provenance.

## Ordered work packages

1. **Freeze provenance:** record the commit/tree, clean or dirty state, submodule
   commits, toolchain tag plus resolved commit/bundle hashes, host and tools.
2. **Freeze the baseline matrix:** choose supported XLEN/profile, tensor backend,
   formats, warp geometry and workload sizes from the existing catalog. Identify
   native FP16/BF16 GEMM, supported small attention and integration coverage.
3. **Build reproducibly:** configure a clean build tree, retain generated config
   hashes and compile with identical application/backend settings. Reconfigure
   after build-participating source/configuration changes.
4. **Reproduce numerical behavior:** run SimX and native processor RTL cases
   against their existing CPU references. Preserve tolerances and golden data.
5. **Exercise integration:** validate DMA, launch and completion through the full
   XRT AFU hardware-emulation path; document missing tools/platforms as blockers.
6. **Publish the baseline packet:** retain commands, logs, results, discrepancies,
   applicable parity evidence and explicit coverage gaps for review.

Use the frozen matrix and its runner for the bounded P01 packet. The inherited
generated regression runner also accepts `--test` marker expressions. These
remain broader catalog slice examples, **not a claim they have run**:

```sh
# Run from the configured build tree, not the source root.
./ci/regression.sh --test 'tensor and simx'
./ci/regression.sh --test 'tensor and rtlsim'
./ci/regression.sh --test 'tensor_wg and rtlsim'
```

These slices contain multiple configurations and are not the frozen matrix by
themselves. Inspect [tensor cases](../../../ci/testcases/tensor.yaml) and
[WGMMA cases](../../../ci/testcases/tensor_wg.yaml) before choosing bounded runs.
The catalog's small WGMMA attention RTL case is RV64; do not assume generic
RV32 instruction-count parity applies to its soft-float behavior.

## Deliverables and exit acceptance

| Gate | Required deliverable and proof | Evidence level |
|---|---|---|
| `P01-A01` | Clean-build recipe and successful build logs with pinned tools, submodules and generated configuration hashes. | `simulated` |
| `P01-A02` | Native FP16/BF16 tensor GEMM and supported small attention reference results on SimX and native RTL, with exact cases/configurations. | `rtl_verified` |
| `P01-A03` | Full XRT `hw_emu` integration report covering DMA, launch and completion; unavailable integration remains blocked, not passed. | `rtl_verified` |

## Evidence distinctions and stop rules

Record arithmetic backend separately from execution driver. `VX_CFG_TCU_TYPE_DPI`
delegates arithmetic to C; a DPI pass cannot satisfy native tensor RTL proof.
Processor `rtlsim` bypasses the AFU surface. XRT `hw_emu` exercises integration
but is not physical FPGA hardware. Functional-only SimX timing is nonphysical.

Stop closure for missing provenance, stale/mismatched configurations, absent
required runs, numerical failures, unexplained divergence or missing AFU evidence.
Do not loosen tolerances, edit goldens, hide failures or substitute documentation
checks for execution. Retain failures and blocked work under the
[acceptance policy](../acceptance.md), with a reproducible root-cause task.

Handoff to [P02](p02-tensor.md): a reviewed baseline packet, supported native
configuration matrix, known arithmetic limitations and the first numerical
contract work item. No FPGA or silicon claim follows from this phase.
