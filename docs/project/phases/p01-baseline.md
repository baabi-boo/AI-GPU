# P01 — Reproducible baseline

Live status and authoritative gates are in [roadmap.json](../roadmap.json).
Dependency: **P00**. Accountable role: **Verification lead**.

## Implementation checkpoint

P01 is `blocked` on vendor hardware emulation. Its acceptance evidence records
passing A01/A02 reports and the explicitly blocked A03 report. The
[runbook](../p01-baseline-runbook.md) now connects an immutable
[toolchain lock](../../../ci/project/p01_toolchain.lock.json), verified
[bootstrap](../../../ci/project/baseline_bootstrap.py), frozen
[six-case native matrix](../../../ci/project/p01_baseline.json) and bounded
[execution runner](../../../ci/project/baseline.py). Provenance, configuration,
process-limit and failure-retention tests exercise this tooling independently of
GPU workloads.

The clean execution source is `03181532b81fe95b1cfeac2ffb25d8597af689b2`, with
instrumentation at `e9c9ac01f93b0d84915340999100260f2599ec44`. The verified GNU 11
host compiler, pinned submodules/tools and dependency, kernel-library and runtime
builds are prepared. All six FP16/BF16 GEMM and TF32 attention cases pass their
unchanged CPU references on SimX and native processor RTL. A separate fresh
generated FP16 SimX build also passes. Independent reviews accept
[P01-A01](../evidence/p01-build.json) and [P01-A02](../evidence/p01-native.json).
The supplemental full-AFU vendor-free `xrtsim` smoke passes its 16-point integer
reference; it remains separate from the required vendor integration.

The initial GCC 14 spdlog/fmt and missing-`ccache` compilation failures are
preserved in the [historical packet](../evidence/p01/history/README.md). The
attention kernel uses SS operands for both GEMMs; read the original matrix
descriptions with the [coverage erratum](../evidence/p01/attention-operand-erratum.md).
Full vendor XRT `hw_emu` is blocked by missing tools/platform, so neither
processor RTL nor supplemental `xrtsim` can close P01-A03. See the
[handoff](../p01-handoff.md) for the accepted baseline's execution and publication checkpoint.

For supplemental vendor-free full-AFU `xrtsim` and focused unit checks, see the
[local qualification guide](../p01-local-qualification.md) and
[handoff](../p01-local-qualification-handoff.md). This coverage is separate from
the vendor `hw_emu` evidence required by P01-A03.

The earlier compiler-record tooling has a separate
[contract](../p01-compiler-records.md) and
[handoff](../p01-compiler-records-handoff.md). Preparation and execution use the
shared validator for independent runtime, kernel and host records and preserve
its transitive helper source snapshots. This tooling correction leaves the
accepted numerical evidence and the P01-A03 vendor blocker unchanged.

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

| Gate | Required deliverable and proof | Evidence level | Disposition |
|---|---|---|---|
| `P01-A01` | Clean-build recipe and successful build logs with pinned tools, submodules and generated configuration hashes. | `simulated` | [Accepted](../evidence/p01-build.json); fresh generated build with separately pinned reused dependencies |
| `P01-A02` | Native FP16/BF16 tensor GEMM and supported small attention reference results on SimX and native RTL, with exact cases/configurations. | `rtl_verified` | [Accepted](../evidence/p01-native.json); all six reference checks pass |
| `P01-A03` | Full XRT `hw_emu` integration report covering DMA, launch and completion; unavailable integration remains blocked, not passed. | `rtl_verified` | [Blocked](../evidence/p01-xrt-blocked.json); qualified vendor tools/platform unavailable |

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
contract work item. **P02 now has staged entry** from accepted P01-A01/A02
even though P01-A03 still blocks completion of P01 (and thus P07 acceptance).
See the [P02 entry handoff](../p02-entry-handoff.md). No FPGA or silicon claim
follows from this phase.
