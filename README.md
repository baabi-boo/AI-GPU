<p align="center">
  <img src="docs/assets/img/vortex_framework_stack.svg" alt="Vortex framework stack" width="100%">
</p>

# AI-GPU

A Vortex-derived, programmable AI-accelerator project: **prove the math, run useful
models, validate real hardware, then evaluate custom silicon.**

In plain language, this repository contains the blueprints and software for a
parallel math engine. The development goal is to turn those building blocks into
a dependable system that runs AI models—not merely add more cores or rename a
simulator configuration. “NVIDIA-style” describes the ambition of programmable
compute, specialized matrix units, fast memory and usable software. It does not
mean NVIDIA performance, CUDA compatibility, product equivalence or affiliation.

**Current stage: P00 — project foundation accepted; P01 baseline work is next.** The authoritative
[status](docs/project/status.md) and [phase gates](docs/project/roadmap.json)
separate accepted evidence from planned work. Repository setup is not GPU
qualification; P01–P11 require their own results.

## Start here

- Understand the goal: [project charter](docs/project/charter.md).
- See the development sequence: [roadmap](ROADMAP.md).
- Pick the next bounded task: [status](docs/project/status.md) and [backlog](docs/project/backlog.md).
- Begin contributing: [developer guide](docs/project/developer-guide.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
- Find everything else: [project documentation](docs/project/index.md) and [technical documentation](docs/index.md).

## What exists, and what must be built

The inherited [Vortex](https://github.com/vortexgpgpu/vortex) source provides a
substantial foundation. The [baseline audit](docs/project/baseline.md) identifies
the exact starting revision and evidence boundaries.

| Area | Inherited building blocks | AI-GPU development work |
|---|---|---|
| Compute | RISC-V parallel cores; WMMA/WGMMA tensor units and structured sparsity | Reproduce a supported native configuration and prove its numerical behavior |
| Memory and platform | Caches, shared memory, asynchronous tile copies and FPGA integration | Measure useful data movement, usable external memory and real-board behavior |
| Software | Native tensor kernels, GEMM/attention examples, host runtime and existing OpenCL/basic HIP routes | Build a reusable operator library, a tiny-model executor, then Python/custom-op integration |
| Verification | Simulators, RTL tests and regression catalogs | Attach reproducible results to every claimed capability and preserve inherited gates |

Source presence is not a fresh passing test. Tensor acceleration is not enabled
in the inherited default configuration, and format definitions do not establish
support on every arithmetic backend. Existing graphics and ray-tracing sources,
tests, licenses and illustrations remain preserved.

The current HIP route does not expose Vortex-specific tensor intrinsics, so the
first model uses the existing **native kernel and runtime path**. A new HIP
compiler is not its prerequisite. A PyTorch custom-op bridge is a later bounded
integration—not a complete framework device backend.

## The first useful milestone

Run one small, fixed, redistributable AI model through native operators. Compare
its intermediate layers and final output against a frozen CPU reference, and
retain traces proving where each accelerated operation executed. Unsupported
operations must be explicit; silent CPU fallback cannot satisfy an accelerator
claim. This is the P04 target, after the baseline and numerical gates.

Then reproduce the workload on a selected physical FPGA: a reconfigurable chip
that lets the design be tested before manufacturing a custom chip. Real memory,
host transfers and measured behavior are P07 obligations. No board, memory
capacity, clock speed, process node or manufacturing order is approved by this
README.

## Development roadmap

The plan contains **12 phases and 36 acceptance gates**. Each phase has an owner
role, dependencies, work packages, deliverables, required evidence and stop rules.
Exact dependencies and completion records live in the
[machine-readable roadmap](docs/project/roadmap.json); see [ROADMAP.md](ROADMAP.md)
for the full reader-facing guide.

| Phases | Outcome to earn |
|---|---|
| P00–P02 | An auditable project, reproducible baseline and verified tensor arithmetic contract |
| P03–P05 | Reusable AI operators, end-to-end tiny-model inference and a tested Python/custom-op route |
| P06–P08 | Measured optimization, a physical FPGA prototype and a hardened experimental release |
| P09 | Separately demonstrated training and multi-device research |
| P10–P11 | Approved ASIC feasibility, then funded manufacturing and measured silicon bring-up |

P09 is not a prerequisite for a bounded inference ASIC. P10/P11 require qualified
hardware/IP/foundry work and explicit human funding and manufacturing decisions;
simulation or a generated layout file cannot replace them.

## Quick start: lightweight repository checks

For a new checkout, use authorized access to this repository's existing `master`
branch. Python 3.12 matches the lightweight CI environment; these checks use the
standard library and Git, without GPU toolchains or initialized submodules.

```sh
git clone --branch master https://github.com/baabi-boo/AI-GPU.git
cd AI-GPU
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

These commands inspect prerequisites, validate project metadata/links/evidence,
and test the governance tools. **They do not build or run the GPU.** Missing GPU
dependencies are reported separately. Follow the [developer guide](docs/project/developer-guide.md)
before downloads or execution: approve a disk/RAM/job budget, use pinned tools
and separate build directories, and start with bounded cases. Do not begin with
an unrestricted toolchain install or full synthesis sweep.

## Evidence and engineering rules

- Keep source inspection, simulation, native RTL verification, physical FPGA
  measurements and silicon measurements distinct. DPI software arithmetic and
  XRT `hw_emu` are not proof of a physical native accelerator.
- Freeze numerical and benchmark contracts before measurement; retain failures,
  exact revisions/configurations, commands, logs, hashes and limitations.
- Preserve existing tests, tolerances and golden data. Use independent review
  where required; update status and the next action with every milestone.
- Commercial GPU names in inherited simulation profiles are configuration labels,
  not evidence that AI-GPU matches those products.

| Engineering topic | Guide |
|---|---|
| Scope and traceability | [Requirements](docs/project/requirements.md), [decisions](docs/project/decisions.md), [risks](docs/project/risks.md) |
| Implementation direction | [Architecture](docs/project/architecture.md), [software](docs/project/software.md), [hardware](docs/project/hardware.md) |
| Development configuration | [Unqualified native AI profile](docs/project/configurations.md); no global default or hardware qualification changes |
| Qualification | [Acceptance](docs/project/acceptance.md), [verification](docs/project/verification.md), [benchmarks](docs/project/benchmarks.md), [evidence format](docs/project/evidence/README.md) |
| Safe delivery | [Release policy](docs/project/releases.md), [security policy](SECURITY.md), [review policy](docs/review/code-review-policy.md) |
| Repository operation | [CI contract](docs/project/ci-contract.md), [maintainer checklist](docs/project/maintainer-checklist.md), [changelog](CHANGELOG.md) |

## Repository map

`hw/` contains hardware sources and implementation flows; `sw/` contains kernel,
runtime and driver code; `sim/` contains simulators; `tests/` and `ci/` hold tests
and automation. `profiles/`, `VX_config.toml` and `VX_types.toml` configure the
machine. `docs/project/` holds plans and evidence; `docs/designs/` describes the
inherited implemented subsystems. See the [codebase guide](docs/codebase.md).

## License and upstream credit

AI-GPU builds on the work of the [Vortex contributors](https://github.com/vortexgpgpu/vortex)
under [Apache License 2.0](LICENSE), with third-party licenses and notices retained.
The original illustration above is preserved; it is a design illustration, not
a photograph or proof of manufactured AI-GPU hardware.

Foundational research: B. Tine et al., *Vortex: Extending the RISC-V ISA for GPGPU
and 3D-Graphics*, MICRO-54 (2021), pp. 754–766,
[doi:10.1145/3466752.3480128](https://doi.org/10.1145/3466752.3480128).
See the [upstream website](https://vortexgpgpu.github.io/index.html) and
[technical references](docs/references.md). Historical upstream results are not
measurements of this fork.

