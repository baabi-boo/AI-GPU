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

**Latest completed phase: P04 — tiny-model inference (`complete`).**
The frozen synthetic, bias-free batch-16 **16 → 8 → 4 MLP** now runs through
three native matmuls per model on SimX and native processor RTL, in FP16 and BF16.
The fresh matrix at
[`c9d139c`](https://github.com/baabi-boo/AI-GPU/commit/c9d139cc9f84839b6a56b6228dd304460cbfe45c)
passed **20 case/backend pairs, 40 model runs and 120 launches**, with exact
hidden, bridge and final-output comparisons and 600 event/profile pairs.
The complete host suite also passed **1,816 tests** at that revision.
[P04-A02](docs/project/evidence/p04-executor/acceptance-numerics.json) and
[P04-A03](docs/project/evidence/p04-executor/acceptance-dispatch.json) accept this
bounded native processor RTL scope after independent review.

ReLU, exact format conversion and output-row assembly remain explicit host work;
there is no CPU matmul fallback or native activation claim. The
[executor packet](docs/project/evidence/p04-executor/README.md) retains original
archives, build provenance, independent audits and replay instructions. The
earlier [P04-A01 fixture acceptance](docs/project/evidence/p04-fixture/acceptance.json)
and [hashed manifest](ci/project/p04_model_manifest.json) remain unchanged.

**Current work: P05-T01 — the Python/custom-op bridge (`in_progress`).**
[P05-A01 now accepts the copying Python binding](docs/project/evidence/p05-python/acceptance-binding.json)
on SimX at
[`e1420fd`](https://github.com/baabi-boo/AI-GPU/commit/e1420fd550f716df33a2556057b7086a03032cbe).
Both fresh installed formats passed the six supported matmul signatures and ten
frozen model cases: **144 combined Python/native launches and 660 event/profile
pairs**, plus **2,174 clean hosted source tests**. The
[Python evidence packet](docs/project/evidence/p05-python/README.md) retains exact
source/build/package identities, independent reviews and earlier failures.

The next bounded step is to freeze, implement and qualify the scoped PyTorch
custom-op route. **P05-A02/A03 remain unearned; no PyTorch version is qualified.**
Start with the [handoff](docs/project/p05-entry-handoff.md),
[API contract](docs/designs/python_binding_v1.md) and [package guide](python/README.md).
This simulated binding result establishes no Python RTL/XRT qualification,
physical FPGA performance or full framework backend. The
[executor audit](docs/project/p04-executor-audit.md) preserves the unresolved
inherited tensor DSP area-gate failure.

**Earlier completed phase: P03 — native AI operator library (`complete`).**
The [v1 operator contract](docs/designs/ai_operator_contract_v1.md) now has a matching
device reader and managed matmul wrapper over the native runtime. Its six bounded
FP16/BF16 signatures passed **176 case executions, 352 launches and 14,336 exact
output-word comparisons** on SimX and native processor RTL. Actual RV32/RV64
lifecycle checks and all **1,669 host tests** passed; independent review accepts
[P03-A02/A03](docs/project/evidence/p03-managed-matmul/README.md).
The [handoff](docs/project/p03-operators-handoff.md) records the accepted scope and
ownership/error behavior used by the P04 contract.

**Completed milestone: P02 — tensor numerical contract (`complete`).**
P02-T01 is complete with [source-level P02-A01 evidence](docs/project/evidence/p02-numerics/acceptance.json).
[P02-A02 is accepted](docs/project/evidence/p02-wmma/acceptance.json) for matching
full SimX/native processor ordinary WMMA arithmetic and layout checks.
The full witnessed WGMMA matrix has finished with passing arithmetic, metadata
ordering and paired performance checks: 12 builds, 24 case executions, 48 launches
and 24,576 exact output-word comparisons.
[P02-A03 is accepted](docs/project/evidence/p02-wgmma/processor/acceptance.json)
after independent engineering and publication-integrity review, completing
P02-T02 and P02; see the
[WGMMA handoff](docs/project/p02-wgmma-handoff.md).
The accepted P01 clean-build (`A01`) and native numerical (`A02`) results now
unlock software/RTL development without waiting for a vendor FPGA emulator.
**P01 remains `blocked` on `A03`**, and that proof is required before the
physical-FPGA stage (P07) can close. The baseline tooling is implemented. Its
accepted historical
six-case FP16/BF16 GEMM and TF32 attention matrix passed on SimX and native
processor RTL, and its fresh generated-build check passed. [P01-A01](docs/project/evidence/p01-build.json)
and [P01-A02](docs/project/evidence/p01-native.json) are accepted after independent
review. [P01-A03](docs/project/evidence/p01-xrt-blocked.json) remains blocked by
missing qualified vendor XRT `hw_emu` tools/platform.
The authoritative [status](docs/project/status.md) and
[phase gates](docs/project/roadmap.json) separate implementation from acceptance;
P00, P02, P03 and P04 are complete, P01 is blocked, P05 is in progress,
and P06–P11 are not started.

## Start here

- Understand the goal: [project charter](docs/project/charter.md).
- See the development sequence: [roadmap](ROADMAP.md).
- Build on the accepted native operators: [P03 handoff](docs/project/p03-operators-handoff.md)
  and [operator manifest](ci/project/p03_operator_manifest.json).
- Inspect the accepted [P04 tiny-model contract](docs/designs/tiny_mlp_fixture_v1.md),
  [manifest](ci/project/p04_model_manifest.json) and
  [source qualification](docs/project/evidence/p04-fixture/README.md), then follow the
  [executor packet](docs/project/evidence/p04-executor/README.md),
  [executor plan](docs/project/p04-executor-plan.md) and [phase guide](docs/project/phases/p04-inference.md).
- Review the accepted WGMMA results:
  [WGMMA handoff](docs/project/p02-wgmma-handoff.md) and
  [P02-A03 evidence](docs/project/evidence/p02-wgmma/processor/README.md).
- Review the accepted ordinary processor checks: [WMMA handoff](docs/project/p02-wmma-handoff.md)
  and [P02 WMMA evidence](docs/project/evidence/p02-wmma/README.md).
- Read the earlier contract checkpoint: [P02 numerical handoff](docs/project/p02-numerics-handoff.md)
  and [A01 evidence](docs/project/evidence/p02-numerics/README.md).
- Start the next bounded task: [P05 binding handoff](docs/project/p05-entry-handoff.md),
  [status](docs/project/status.md) and [backlog](docs/project/backlog.md).
- Reproduce the accepted baseline: [P01 baseline runbook](docs/project/p01-baseline-runbook.md).
- Follow current supplemental work: [P01 tensor-oracle hardening](docs/project/p01-tensor-oracles.md)
  and its [evidence index](docs/project/evidence/p01-tensor-oracles/README.md).
- Follow earlier supplemental local coverage: [P01 local qualification](docs/project/p01-local-qualification.md)
  and [handoff](docs/project/p01-local-qualification-handoff.md) cover vendor-free
  full-AFU `xrtsim` and focused unit checks; vendor `hw_emu` remains a separate
  P01-A03 requirement, not an entry requirement for P02.
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

| Area | Current building blocks | AI-GPU development work |
|---|---|---|
| Compute | RISC-V parallel cores; WMMA/WGMMA tensor units and structured sparsity | Reproduce a supported native configuration and prove its numerical behavior |
| Memory and platform | Caches, shared memory, asynchronous tile copies and FPGA integration | Measure useful data movement, usable external memory and real-board behavior |
| Software | Accepted bounded matmul library, fixed tiny-model execution and copying Python binding; native tensor kernels and existing OpenCL/basic HIP routes | Add scoped PyTorch custom operators while preserving explicit placement/lifetimes |
| Verification | Simulators, RTL tests and regression catalogs | Attach reproducible results to every claimed capability and preserve inherited gates |

Source presence is not a fresh passing test. Tensor acceleration is not enabled
in the inherited default configuration, and format definitions do not establish
support on every arithmetic backend. Existing graphics and ray-tracing sources,
tests, licenses and illustrations remain preserved.

The current HIP route does not expose Vortex-specific tensor intrinsics, so the
first model uses the existing **native kernel and runtime path**. A new HIP
compiler is not its prerequisite. A PyTorch custom-op bridge is a later bounded
integration—not a complete framework device backend.

## The first model milestone

Run one small, fixed, redistributable AI model through native operators. Compare
its intermediate layers and final output against a frozen CPU reference, and
retain traces proving where each accelerated operation executed. Unsupported
operations must be explicit; silent CPU fallback cannot satisfy an accelerator
claim. P04 now satisfies this milestone for the fixed MLP and the accepted
SimX/native processor RTL configuration.

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

## P02 numerical contract and processor milestones

The contract and A01 results below preserve the original numerical checkpoint;
the subsequent ordinary WMMA and WGMMA processor results follow it.

The [v1 specification](docs/designs/tensor_numerics_v1.md) defines native TFR
FP16/BF16-to-FP32 arithmetic for a fixed four-product unit profile. Its
[machine manifest](ci/project/p02_tensor_contract.json) binds 98 deterministic
fixtures to an independent integer/rational producer and strict bit comparisons.
The contract describes the fixed alignment window, RNE rounding, cancellation,
input subnormals, signed output flush-to-zero, infinities and canonical NaNs.
It does not promise an exact real dot product or universal IEEE behavior.

The runnable [p02-tfr profile](profiles/p02-tfr.json) also freezes one core,
four warps of four threads, native TFR/STD arithmetic and the ordinary
`8 x 4 x 8` WMMA tile. Twenty independently generated
[matrix-layout fixtures](ci/project/fixtures/p02_layout_v1.json) define compact
row-major A, column-major B and row-major output across single and multiple
tiles. Their source-level checks do not claim that those matrices ran on a GPU.

The [unit harness](hw/unittest/tcu_contract/main.cpp) checks those constants on
native TFR RTL and separately on the production model function. Its enable-stall
checks cover the leaf pipeline. Native WMMA/WGMMA C++ contexts now reject input
formats absent from the compiled TFR configuration; this compile-boundary check
does not create a hardware trap for unsupported raw instructions.

Formal validation used clean source
[`a25321496d802f43830c1658487f1adf79c838c3`](https://github.com/baabi-boo/AI-GPU/commit/a25321496d802f43830c1658487f1adf79c838c3):

| Check | Observed result | Scope |
|---|---|---|
| Full offline suite | 1,343 tests passed; zero failures, errors or skips | Project tooling, source contracts and host model-function checks |
| Native TFR leaf | 98 dense cases and the same 98 stalled cases passed; 306 hold checks passed | Exact-bit direct FEDP RTL, without DPI arithmetic |
| Production model function | 98 cases passed | Host `TfrFedp`; full SimX processor execution remains separate |
| Actual RISC-V API matrix | 47 cases passed: 17 positive compilations and 30 intended rejections | Both WMMA and WGMMA contexts, 94 context checks |
| Existing native kernels | Four FP16/BF16 WMMA/WGMMA objects compiled | Compile-only; WGMMA overrides are outside the ordinary profile |

The [evidence packet](docs/project/evidence/p02-numerics/README.md) preserves
the initial stall-context failure and the first clean profile-build failure,
their corrections, independent reviews and exact source/tool/configuration
identities. The profile build now passes resolved enum selectors to C++ while
preserving raw disabling and diagnostic flags. Production arithmetic, inherited
goldens and accepted P01 tolerances remain unchanged.

```sh
python3 ci/project/p02_fixture_oracle.py --check
python3 ci/project/p02_layout_fixture_oracle.py --check
python3 -m unittest discover -s ci/project -p 'test_p02_*.py'
```

The subsequent [P02-A02 record](docs/project/evidence/p02-wmma/acceptance.json)
binds ordinary WMMA processor validation to clean source
`58faf6d68879e1db92122df493172eab59c02458`: 88 cases, 176 case/backend
executions, 352 launches and 14,336 exact output-word checks passed. The scope is
RV64 FP16/BF16-to-FP32, initial C = +0, K = 8 or 16 and the `8 x 4 x 8` tile,
using native TFR tensor and STD scalar floating-point paths with integer DPI
helpers still present. The separate API matrix met 47 expectations in 94
contexts, including 30 intended compiler rejections.

The first 1,448-test offline run retained one source-contract failure. A
reporting-only child restores the legacy host report; its full-suite rerun and
new-host fixture revalidation passed at `c9cf9ba`: 1,448 offline tests and
352 repeated launches with 14,336 exact word comparisons; see [status](docs/project/status.md).
The [WMMA handoff](docs/project/p02-wmma-handoff.md) separates those checks from
the formal processor result.

The completed [WGMMA processor packet](docs/project/evidence/p02-wgmma/processor/README.md)
uses clean source `4af2307e57202c1269e20f893267a5583ad3cba0`: all 113 commands,
12 backend/configuration builds, 24 case executions, 48 launches and 24,576 exact
output-word comparisons passed. All 12 performance pairs have exact instruction
counts and cycle differences within the unchanged 5% bound; the largest observed
difference is 1.356484%. The two sparse RTL cases record 64 completed metadata
transactions, all with observed waits. The separately reviewed
[native unit](docs/project/evidence/p02-wgmma/unit/README.md) retains its original
`9006939` execution: 392 accepted/committed transactions and 3,072 checked words.
Its forced compute-pressure case is dense NRC16 RS; sparse forced compute
pressure is unclaimed.

The corrected offline verifier validates 1,103 retained packet files against the
independently supplied report digest. Independent engineering and publication
reviews support the [P02-A03 acceptance](docs/project/evidence/p02-wgmma/processor/acceptance.json),
completing P02-T02 and P02. P01-A03 remains blocked and required before P07.

## P03 accepted native operators

**P03-T01 is complete and P03-A01 is [accepted at source scope](docs/project/evidence/p03-operators/acceptance.json).**
The frozen implementation passed all 1,636 offline tests; four actual RV32/RV64
object compilations passed separately. [Evidence and source mapping](docs/project/evidence/p03-operators/README.md)
keep those historical source checks distinct from the later accepted device
execution and lifetime results.

The [internal C++17 planner](sw/runtime/ai/contract.h) validates FP16/BF16-to-FP32
matmul for exactly `(M,N,K) = (8,4,8), (8,4,16), (16,8,16)`. It checks tensor
shape, layout, strides, allocation extents and permissions, device/profile
identity, alignment, overflow and overlapping accessed ranges. Rejections leave
the caller’s output unchanged. A separate encoder produces a versioned 56-byte
little-endian argument block with checked 32/64-bit address representation.

The pure planner still reports `execution_available=false`. The separate
[managed wrapper](sw/runtime/ai/runtime.h) now supplies owned allocations,
transfers, dispatch and completion, and the [device reader](sw/kernel/ai/matmul.cpp)
consumes the shared argument bytes. The trusted runner binds the actual compiled
profile and module to each launch; a timeout retains in-flight resources.
GEMV, reductions, softmax, normalization, activations, conversions and attention
are explicitly unavailable in the [manifest](ci/project/p03_operator_manifest.json).
**P03-T02 and P03 are complete** after the clean-source matrix and independent
review. [P03-A02](docs/project/evidence/p03-managed-matmul/acceptance-numerics.json)
accepts the four SimX/native-RTL format builds and exact arithmetic checks;
[P03-A03](docs/project/evidence/p03-managed-matmul/acceptance-lifecycle.json)
accepts twelve actual lifecycle groups in each of RV32/RV64 SimX, with host mocks
separately scoped. The [packet](docs/project/evidence/p03-managed-matmul/README.md)
retains raw results, compiler records, source identities and earlier failed or
interrupted attempts. See the [handoff](docs/project/p03-operators-handoff.md).

```sh
python3 -m unittest discover -s ci/project -p 'test_p03*.py'
```

## P01 supplemental tensor-oracle hardening

The [tensor-oracle guide](docs/project/p01-tensor-oracles.md) covers class-aware
nonfinite comparison, overflow-safe ULP distances, FP32 accumulator bit preservation,
independent FP16/BF16 fixtures and modular integer reference arithmetic. Strict
CLI validation rejects empty or disabled-format selections, and selected random
cases replay the full run's input stream. The
[evidence index](docs/project/evidence/p01-tensor-oracles/README.md) binds results to source.

Matrix/full-suite source: `ca8686d668ed9f2ff733ce7e3c12dd458b9776d8`; native matrix: **pass — nine builds, 62 commands and 95 CLI checks**;
full tooling suite: **1,272 tests passed, zero failures/errors/skips in 336.269 seconds**. This is supplemental P01 evidence;
the later staging decision opened P02 without accepting P01-A03.

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
remains blocked; P02 was `not_started` at that earlier checkpoint. The
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
this earlier tooling delivery did not close P01-A03 or begin P02 qualification;
the subsequent staged-entry decision is recorded in [ADR-004](docs/project/decisions.md#adr-004--staged-native-development-entry-with-vendor-integration-retained).

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

