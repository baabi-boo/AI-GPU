# AI-GPU project charter

## Mission

Develop a programmable, Vortex-derived AI accelerator with a reproducible path
from native tensor kernels to useful model inference, a measured FPGA prototype,
and, only after an approved feasibility program, custom silicon.

“NVIDIA-style” describes the architectural ambition: parallel programmable
compute, specialized matrix arithmetic, an efficient memory hierarchy and usable
AI software. It is **not** a claim of NVIDIA performance, CUDA binary
compatibility, NVLink compatibility, product equivalence or affiliation.

This charter defines the development contract. It does not certify that the
planned capabilities work. The [baseline](baseline.md) describes inherited
source; [status](status.md) and [roadmap.json](roadmap.json) record progress and
evidence. The [roadmap](../../ROADMAP.md) is the reader-facing phase guide.

## First product-shaped milestone

Run one fixed, redistributable tiny AI model through a native operator library
using Vortex tensor kernels. Compare intermediate and final results with a
frozen CPU reference and prove operator placement with device traces. Reproduce
the model on physical FPGA hardware before advertising a hardware accelerator.

The first demonstration must report its limitations: supported shapes and
number formats, explicit transfers, host-side work, unsupported operations and
measurement conditions. A successful simulator demonstration is valuable, but
is not evidence of physical throughput or energy efficiency.

## Scope

| Workstream | Intended outcome | Boundary |
|---|---|---|
| Reproducibility and verification | Pinned configuration, toolchain, tests and reviewable evidence | Source presence and inherited test definitions are not passes |
| Tensor compute and native operators | Defined arithmetic contracts and a tested inference operator library | Build on existing WMMA/WGMMA and attention code; do not recreate them blindly |
| Model and Python integration | Native tiny-model inference, then a thin Python/PyTorch custom-op path | A custom-op bridge is not a complete framework device backend |
| Memory and scaling | Measured data movement, reuse, resource use and bottlenecks | Board memory capacity and theoretical bandwidth are not usable measured values |
| FPGA prototype and reliability | Real DRAM, host transfers, model execution and recovery tests | Emulation is not a physical-board result |
| Training and multiple devices | Separately validated gradients, convergence and collectives | Inference success does not establish training support |
| Silicon feasibility and realization | An approved, bounded ASIC program and measured bring-up | Synthesis reports or a GDS file alone are not manufacturing sign-off |

Existing graphics, ray-tracing and other inherited functionality remain in the
repository. An AI configuration may disable unneeded blocks; this project setup
does not authorize deleting them or weakening their tests.

## Non-goals for the initial release

- Matching a particular commercial GPU's speed, memory capacity or power budget.
- Running arbitrary CUDA applications or replacing NVIDIA drivers.
- Supporting every model, framework, number format or FPGA listed upstream.
- Training frontier-scale models or promising linear multi-device scaling.
- Purchasing boards, licenses, IP or foundry services through automated work.
- Treating a documentation milestone, simulated result or estimated PPA result
  as a manufactured product. PPA means power, performance and area.

## How success is judged

The canonical acceptance identifiers and dependencies live in
[roadmap.json](roadmap.json). Supporting procedures are in
[acceptance](acceptance.md), [verification](verification.md) and
[benchmarks](benchmarks.md).

1. **Correctness:** freeze per-format and per-model tolerances before evaluation;
   exercise exceptional values, unsupported inputs, layouts and concurrency.
2. **Reproducibility:** retain source/configuration/tool identities, exact
   commands, backend, logs, hashes and outcomes. Missing execution is `not_run`.
3. **Usability:** make supported operations and explicit failures discoverable;
   no silent CPU fallback may satisfy an acceleration claim.
4. **Efficiency:** report fixed-workload measurements with transfer costs and
   uncertainty. Select performance targets through a reviewed decision before
   collecting acceptance measurements; do not invent market-parity targets.
5. **Physical credibility:** identify the actual board or silicon, memory map,
   bitstream, achieved clock and operating conditions for hardware claims.
6. **Maintainability:** preserve licensing, upstream attribution, engineering
   invariants, independent review and golden-baseline integrity.

Completing P00 means the project is organized and its governance checks pass.
It does not complete P01–P11. P09 training/multi-device research is not a
prerequisite for a bounded inference ASIC; P10 depends on the proven prototype
and reliability work instead.

## Accountability and decisions

The `accountable_role` field in each phase describes required responsibility,
not an assertion that a specialist has been hired. Name the actual owner in the
work item before implementation. Unassigned ownership is visible work, not an
implicit assignment to an AI agent.

- **Project maintainer:** scope, priority, accepted decisions and phase closure.
- **Subsystem leads:** technical contracts and implementation in their phase.
- **Verification/release leads:** evidence completeness, reproducibility and
  compatibility claims.
- **Independent reviewer:** review changes they did not author under the
  inherited [review policy](../review/code-review-policy.md).
- **Hardware/silicon decision owner:** explicit procurement, licensing, lab,
  partner and manufacturing approvals; agents cannot supply these approvals.

Changes to scope, numerical thresholds, compatibility claims or physical targets
require a recorded decision, impact assessment and updated acceptance contract.
Do not adjust a threshold simply to turn a failed test into a pass. See
[decisions](decisions.md), [risks](risks.md) and [requirements](requirements.md).

## Provenance

AI-GPU builds on [Vortex](https://github.com/vortexgpgpu/vortex), not on a newly
invented GPU core. Preserve the [Apache-2.0 license](../../LICENSE), source
copyright notices, third-party obligations and existing illustrations. The
README GPU/framework illustration is an inherited design illustration, not a
photograph or proof of fabricated AI-GPU hardware.
