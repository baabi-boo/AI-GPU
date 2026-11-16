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

**Current stage: P01 — reproducible baseline, blocked on vendor hardware
emulation.** The baseline tooling is implemented. Its accepted historical
six-case FP16/BF16 GEMM and TF32 attention matrix passed on SimX and native
processor RTL, and its fresh generated-build check passed. [P01-A01](docs/project/evidence/p01-build.json)
and [P01-A02](docs/project/evidence/p01-native.json) are accepted after independent
review. [P01-A03](docs/project/evidence/p01-xrt-blocked.json) remains blocked by
missing qualified vendor XRT `hw_emu` tools/platform.
The authoritative [status](docs/project/status.md) and
[phase gates](docs/project/roadmap.json) separate implementation from acceptance;
P00 remains complete, P01 remains incomplete, and P02–P11 remain `not_started`.

## Start here

- Understand the goal: [project charter](docs/project/charter.md).
- See the development sequence: [roadmap](ROADMAP.md).
- Pick the next bounded task: [status](docs/project/status.md) and [backlog](docs/project/backlog.md).
- Reproduce the current phase: [P01 baseline runbook](docs/project/p01-baseline-runbook.md).
- Follow current supplemental work: [P01 tensor-oracle hardening](docs/project/p01-tensor-oracles.md)
  and its [evidence index](docs/project/evidence/p01-tensor-oracles/README.md).
- Follow earlier supplemental local coverage: [P01 local qualification](docs/project/p01-local-qualification.md)
  and [handoff](docs/project/p01-local-qualification-handoff.md) cover vendor-free
  full-AFU `xrtsim` and focused unit checks; vendor `hw_emu` remains a separate
  P01-A03 requirement.
- Review the earlier compiler-record tooling checkpoint:
  [compiler-record handoff](docs/project/p01-compiler-records-handoff.md); the
  accepted numerical baseline remains in the [P01 handoff](docs/project/p01-handoff.md).
- Check retained evidence: [packet verification guide](docs/project/p01-packet-verification.md) and [packet continuation handoff](docs/project/p01-packet-handoff.md).
- Inspect vendor preparation inputs: [hw_emu runbook](docs/project/p01-hwemu-runbook.md), [manifest contract](docs/project/p01-hwemu-manifest.md) and [preparation handoff](docs/project/p01-hwemu-handoff.md).
- Use the prepared-artifact execution route: [vendor XRT guide](docs/project/p01-xrt-integration.md).
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
branch. Python 3.12 matches the lightweight CI environment. Use Linux, Python's
standard library and Git. The full unit suite also needs a native C++17 compiler
with UBSan support/runtime libraries and at least 1 GiB free temporary storage
for bounded tensor host-oracle checks. GPU toolchains and initialized submodules
are not required.

```sh
git clone --branch master https://github.com/baabi-boo/AI-GPU.git
cd AI-GPU
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

These commands inspect prerequisites, validate project metadata/links/evidence,
and test the governance tools and bounded tensor host oracles.
**They do not build or run the GPU.** Missing GPU
dependencies are reported separately. Follow the [developer guide](docs/project/developer-guide.md)
before downloads or execution: approve a disk/RAM/job budget, use pinned tools
and separate build directories, and start with bounded cases. Do not begin with
an unrestricted toolchain install or full synthesis sweep.

## P01 supplemental tensor-oracle hardening

The [tensor-oracle guide](docs/project/p01-tensor-oracles.md) covers class-aware
nonfinite comparison, overflow-safe ULP distances, FP32 accumulator bit preservation,
independent FP16/BF16 fixtures and modular integer reference arithmetic. Strict
CLI validation rejects empty or disabled-format selections, and selected random
cases replay the full run's input stream. The
[evidence index](docs/project/evidence/p01-tensor-oracles/README.md) binds results to source.

Matrix/full-suite source: `ca8686d668ed9f2ff733ce7e3c12dd458b9776d8`; native matrix: **pass — nine builds, 62 commands and 95 CLI checks**;
full tooling suite: **1,272 tests passed, zero failures/errors/skips in 336.269 seconds**. This is supplemental P01 evidence;
P01-A03 remains blocked and P02–P11 remain `not_started`.

## P01 baseline implementation

The [frozen RV64 matrix](ci/project/p01_baseline.json) pairs FP16 and BF16 GEMM
and a small TF32 attention workload on SimX and processor RTL. It explicitly
selects TFR tensor and STD scalar arithmetic, preserving the existing numerical
references and tolerances. The [toolchain lock](ci/project/p01_toolchain.lock.json)
identifies the minimal immutable tool bundles; the
[bootstrap](ci/project/baseline_bootstrap.py) verifies their identities, and the
[runner](ci/project/baseline.py) retains configuration hashes, command results,
bounded logs and failure checkpoints.

Follow the [runbook](docs/project/p01-baseline-runbook.md) for preparation and
execution. The historical reviewed baseline delivery records 346 passing
tooling/governance tests; that count describes its recorded revision, and those
tests do not establish a numerical baseline. The attention kernel uses
shared-memory operands for both GEMMs; its original matrix prose is corrected
by the [operand coverage erratum](docs/project/evidence/p01/attention-operand-erratum.md).
P01 also requires full XRT `hw_emu` integration; unavailable vendor tools or a
missing platform remain an explicit blocker to phase closure. A supplemental
16-point integer demo passed through the full-AFU vendor-free `xrtsim` model;
that result does not close the vendor-emulation gate.

The offline [packet verifier](docs/project/p01-packet-verification.md) checks
retained evidence without running a GPU. Use `verify` and `seal` for original
bytes, or explicit `verify-export` for a published derivative. From the source
root, check the published native and clean-build packets together with:

```sh
python3 ci/project/check_baseline_packets.py
```

This consistency check is also part of Project Governance CI. It retains
`phase_complete: false` and does not prove original log bytes or their redaction
relationship. The [continuation handoff](docs/project/p01-packet-handoff.md)
tracks the packet implementation's validation, independent review and publication
state separately from the accepted execution evidence.

## P01 vendor hardware-emulation preparation

The read-only [hwemu.py](ci/project/hwemu.py) `inventory` and `plan` commands
report prerequisites and check a strict input manifest. Planning checks source
and submodule state, an existing generated build, file identities, the retained
build receipt and declared resource bounds. It launches no workload and does
not enforce execution budgets. A `planned` result describes one candidate
integer smoke; it keeps execution, launch readiness, vendor qualification and
P01-A03 acceptance unearned. Follow the
[runbook](docs/project/p01-hwemu-runbook.md) and
[manifest contract](docs/project/p01-hwemu-manifest.md).

The XRT INI now references the actual `sw/runtime/xrt/xsim.tcl` hook and uses
lean tracing defaults. Waveform collection requires an explicit debug
configuration and `VORTEX_XRT_WAVEFORM=1`. These source changes establish no new
GPU, vendor-emulation or physical-device result. The next action is to qualify a
vendor release/platform, retain an actual matching build packet, then review
and execute the DMA/launch/completion smoke under bounded supervision. P01-A03
remains blocked and P02 remains `not_started`; the
[preparation handoff](docs/project/p01-hwemu-handoff.md) records this continuation.

### Prepared-artifact execution runner

The separate [vendor integration runner](ci/project/xrt_baseline.py) implements
a prepared-artifact P01-T05 execution route. It checks a pinned platform, vendor
runtime, matching emulation artifacts and a strict reviewed build receipt,
creates a fresh host/kernel build, then runs the fixed 16-point integer demo
through XRT `hw_emu`. It records bounded commands, configuration and reference
results while keeping acceptance separate. The
[guide](docs/project/p01-xrt-integration.md) explains its manifest and budgets.
Inspect local prerequisites without invoking vendor tools with:

```sh
python3 ci/project/xrt_baseline.py probe
```

The two routes have separate manifest, receipt and report schemas, even though
both use `schema_version: 1`. There is no automatic adapter or promotion from
a preparation plan to execution. `xrt_baseline.py` requires its own independently
reviewed inputs and constructs fixed commands instead of consuming a `hwemu.py`
candidate.

The shared [compiler-record validator](docs/project/p01-compiler-records.md)
resolves the preparation planner's compiler-glob follow-up and strengthens the
execution runner. Runtime, kernel and host records must each establish the
frozen configuration; an apparent definition consumed as an include operand
does not count. The kernel must select the exact RV64 ISA/ABI, and the linker
must select the generated runtime. Ambiguous shell syntax and unsupported
record separators are rejected before launch.

The clean implementation checkpoint `f11190c87778ef049237650bbba4234ca62026b2`
passed **1,120 tooling tests, with zero failures, errors or skips**, including
real compiler-preprocessor checks, fresh Make-generated stamps, launch-blocking
regressions and helper-snapshot checks. The
[verification record](docs/project/evidence/p01-compiler-records/verification.json)
and [handoff](docs/project/p01-compiler-records-handoff.md) retain the tested
identity and evidence boundaries. These tooling results establish no new GPU
or vendor-emulation execution.
The identical source tree is published as
[`623544c`](https://github.com/baabi-boo/AI-GPU/commit/623544cdd51f9c70a4e2fcef29ed3b56d8cce3fe).

Missing prerequisites produce a blocked result and nonzero exit. The development
environment lacks the required vendor installation and platform artifacts, so
this tooling delivery does not close P01-A03 or begin P02 qualification.

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

