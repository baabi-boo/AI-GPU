# AI-GPU requirements and traceability

This is the development contract for a Vortex-derived, programmable AI
accelerator. It describes what must be demonstrated, **not what the current
repository has already achieved**. See the [baseline](baseline.md) for inherited
capabilities and the [charter](charter.md) for scope.

The canonical phase dependencies, acceptance criteria and status live in
[roadmap.json](roadmap.json). Requirement IDs below are stable: retain an ID when
clarifying its meaning; retire it explicitly rather than reusing it for a
different obligation. Each change or evidence submission names its requirement
and acceptance IDs.

## Interpretation

- **MUST** is mandatory before the linked acceptance gate can pass. A missing
  tool, license, board or result means blocked/not run, not a waiver or a pass.
- **SHOULD** is an engineering preference. A deviation needs a recorded rationale
  and review, and cannot waive a MUST or a canonical acceptance criterion.
- Requirements for P09–P11 apply when those gated programs are activated. They do
  not imply that training, multiple devices or fabrication is authorized now.
  P09 is not a prerequisite for the bounded inference ASIC path through P10.
- Acceptance applies only to the named revision, configuration, workload,
  arithmetic backend and execution environment. “Supported” without that scope
  is not an acceptable result.
- Numerical bounds are owned by the versioned P02 contracts and workload
  manifests. This document does not introduce competing tolerances. Freeze
  thresholds before evaluation; do not loosen them to absorb a failure.

## Foundation and reproducibility

| ID | Priority | Requirement and observable proof | Acceptance IDs |
|---|---|---|---|
| RQ-001 | MUST | Preserve the existing README illustration byte-for-byte, inherited attribution and licensing. Separate project plans from verified claims and identify accountable roles. Check the protected asset hash and documentation links. | `P00-A01` |
| RQ-002 | MUST | Validate the phase graph, required project records and completion evidence with offline checks and positive/negative tests. Resolve independent review findings and verify delivery to the intended repository/default branch. | `P00-A02`, `P00-A03` |
| RQ-003 | MUST | Reproduce a clean build with source/submodule revisions, resolved toolchain identity and bundle hashes, XLEN, generated configuration, exact commands and exit results recorded. A toolchain tag or configure-only run is insufficient. | `P01-A01` |
| RQ-004 | MUST | Reproduce the declared native FP16/BF16 tensor GEMM and supported small attention baseline against its CPU reference on SimX and native processor RTL. Identify DPI arithmetic separately; it cannot satisfy native-datapath proof. | `P01-A02` |
| RQ-005 | MUST | Exercise host transfer, launch and completion through the full AFU integration path in XRT hardware emulation. Record an unavailable integration environment as blocked; processor-only RTL simulation does not substitute for this gate. | `P01-A03` |

## Correct AI computation and native software

| ID | Priority | Requirement and observable proof | Acceptance IDs |
|---|---|---|---|
| RQ-006 | MUST | Define per-format and per-backend arithmetic behavior, including rounding, accumulation, zeros/subnormals, NaN/Inf, overflow/underflow and unsupported inputs. Identify the reference oracle and freeze fixtures/tolerances before execution. | `P02-A01` |
| RQ-007 | MUST | Demonstrate native FP16/BF16 input with FP32 accumulation across normal, edge, cancellation and layout cases. Tests must enforce the numerical contract and explicitly reject unsupported formats; source enumeration alone is insufficient. | `P02-A02` |
| RQ-008 | MUST | Preserve WGMMA correctness under the supported warp/CTA geometry, synchronization, metadata dependencies and backpressure. Account for SimX/RTL differences with applicable parity evidence or a justified applicability limit, never a widened tolerance. | `P02-A03` |
| RQ-009 | MUST | Publish an operator contract covering matmul/GEMV, reductions, softmax, normalization, activations, casts/layout transformations and attention. Specify supported shapes, dtypes, strides/layouts, alignment and rejection behavior for each advertised operator. | `P03-A01` |
| RQ-010 | MUST | Compare every advertised operator with an independent CPU reference using deterministic normal and edge fixtures. Dispatch traces must show Vortex execution in the named simulator/RTL environment; record any expressly permitted CPU fallback separately. | `P03-A02` |
| RQ-011 | MUST | Verify allocation bounds, argument/pointer widths, buffer ownership, queue/event lifetime, transfer failures and repeated allocation/free behavior. Invalid inputs must produce explicit errors without leaks or out-of-bounds execution. | `P03-A03` |
| RQ-012 | MUST | Freeze a small redistributable model fixture: architecture, weights or deterministic generator, optional tokenizer, seeds, input shapes, hashes and license/provenance. Reproduction must not depend on an undocumented proprietary download. | `P04-A01` |
| RQ-013 | MUST | Execute the selected tiny model end-to-end through the native runtime and compare layer intermediates and final results with the frozen CPU reference. Passing isolated matrix multiplication does not satisfy model-level acceptance. | `P04-A02` |
| RQ-014 | MUST | Trace every declared accelerated model operation and account for host work and transfers. Silent CPU execution is forbidden; an unsupported operation must fail or use an explicitly selected, reported non-accelerated path. | `P04-A03` |

## Python access, memory and performance

| ID | Priority | Requirement and observable proof | Acceptance IDs |
|---|---|---|---|
| RQ-015 | MUST | Provide a thin Python binding with explicit tensor representation, transfers, lifetime and error contracts. Verify supported dtype/shape/stride cases, invalid calls, cleanup and installation in a clean environment. Host pointers are not device addresses. | `P05-A01` |
| RQ-016 | MUST | Demonstrate a tested PyTorch custom-op route that reproduces the native tiny-model result and produces framework-to-device dispatch evidence. Clearly distinguish this bridge from a complete PyTorch device backend or autograd implementation. | `P05-A02` |
| RQ-017 | MUST | Maintain a compatibility matrix of tested framework/tool versions, operators and limitations. Basic HIP/OpenCL examples or similarly named tensor instructions must not be presented as CUDA binary/driver compatibility. | `P05-A03` |
| RQ-018 | MUST | Freeze benchmark workloads/configurations and record raw samples, warm-up/repeat policy, operation counts, transfer bytes and relevant memory/cycle counters. Separate kernel time, transfer time and end-to-end time; simulated cycles are not measured device throughput. | `P06-A01` |
| RQ-019 | MUST | Show before/after evidence for optimizations while retaining numerical contracts and inherited gates. Any RTL timing change must have its corresponding SimX update and applicable parity evidence. Never hand-edit golden baselines to pass. | `P06-A02` |
| RQ-020 | MUST | Fit the selected scale/configuration within an explicitly approved resource/timing budget. Record achieved synthesis/implementation results and tool assumptions; label estimates, black boxes and nonphysical timing modes rather than presenting them as measured silicon. | `P06-A03` |
| RQ-021 | SHOULD | Prioritize changes using measured bottlenecks and useful end-to-end work, not core counts or theoretical peak arithmetic alone. Keep a rejected-optimization record when extra compute, caching or complexity does not improve the frozen workload. | `P06-A01`, `P06-A02` |

## Physical FPGA and experimental release

| ID | Priority | Requirement and observable proof | Acceptance IDs |
|---|---|---|---|
| RQ-022 | MUST | Select and record one supported board/platform with the required tools/licenses. Pin part, shell/firmware, usable memory map, configuration, bitstream checksum and achieved clock; board advertising does not establish usable GPU capacity. | `P07-A01` |
| RQ-023 | MUST | On physical hardware, verify host enumeration/transfer, DMA round trips, bank/address boundaries, tensor/attention operations and the tiny model against frozen references. Identify the physical device and execution target; `hw_emu` cannot satisfy this requirement. | `P07-A02` |
| RQ-024 | MUST | Complete the initial physical soak specified by the canonical gate with no unexplained numerical, transfer or reset failures. Preserve logs and report throughput, power and temperature as measured or explicitly unavailable. | `P07-A03` |
| RQ-025 | MUST | Test malformed requests, resource exhaustion, error propagation, reset/recovery and isolation against an explicit failure/threat model. Resolve critical findings before an experimental release; publish untested or unsupported security boundaries. | `P08-A01` |
| RQ-026 | MUST | Complete the release soak specified by the canonical gate on the declared physical workload matrix. Preserve raw evidence, telemetry and issue disposition; unexplained errors prevent acceptance. | `P08-A02` |
| RQ-027 | MUST | Reproduce clean installation of versioned experimental artifacts and provide their source/license inventory, compatibility matrix and reviewed evidence package. A governance CI pass must not be branded a GPU correctness or production-readiness certificate. | `P08-A03` |

## Gated research and silicon programs

| ID | Priority | Requirement and observable proof | Acceptance IDs |
|---|---|---|---|
| RQ-028 | MUST when P09 is activated | Demonstrate a small training workload with predeclared precision/optimizer settings, reference gradient checks and measured convergence. Inference success alone cannot establish training support. | `P09-A01` |
| RQ-029 | MUST when P09 is activated | Prove transport/collective correctness, ordering and recovery on the declared two-device physical topology before reporting scaling. Compare single/multi-device measurements and communication costs without implying NVLink or CUDA equivalence. | `P09-A02`, `P09-A03` |
| RQ-030 | MUST when P10 is activated | Establish qualified ownership, availability and cost evidence for a manufacturable PDK, SRAM macros, PCIe/memory controller and PHY IP, package strategy and licensed tools. A generic memory interface is not a physical DRAM/HBM implementation. | `P10-A01` |
| RQ-031 | MUST when P10 is activated | Prepare complete physical-design, DFT, timing, power-integrity and verification sign-off plans for a bounded target. Keep predictive-library, synthesis and black-box estimates distinct from foundry-qualified sign-off. | `P10-A02` |
| RQ-032 | MUST when P10 is activated | Obtain a recorded human go/no-go decision covering budget, schedule, procurement, ownership and external partners before any fabrication commitment. Repository development authorization is not purchasing or tapeout authorization. | `P10-A03` |
| RQ-033 | MUST when P11 is activated | Complete foundry-qualified verification, DFT and physical sign-off with reviewed exceptions and explicit manufacturing-release approval. Producing a GDS file alone does not satisfy sign-off. | `P11-A01` |
| RQ-034 | MUST when P11 is activated | Validate packaged silicon and its board through power/clock/reset, memory training, host/DMA, tensor and frozen-model tests. Publish measured frequency, usable capacity, performance, power and yield limits with device/board revisions. | `P11-A02`, `P11-A03` |

## Evidence and change control

Use the canonical evidence vocabulary exactly: `source_present`, `simulated`,
`rtl_verified`, `fpga_measured`, `silicon_measured`. These labels require scope:
native processor RTL, full-shell emulation and a physical FPGA are not
interchangeable. A source file, old upstream result or unexecuted test definition
does not prove a new run. Record run/not run/failed outcomes, artifact hashes and
limitations using the [acceptance process](acceptance.md).

A requirement change must identify affected acceptance IDs, architecture,
operators, tests, evidence and downstream consumers. Obtain review before
changing the contract; preserve historical evidence against the version it
actually tested. The [upstream review policy](../review/code-review-policy.md)
and [agent rules](../../AGENTS.md) remain applicable.

## Explicit non-goals of this setup

- Claiming NVIDIA-class speed, energy efficiency, memory capacity or software
  compatibility without comparable measurements.
- Creating a replacement CUDA stack as a prerequisite for first native inference.
- Claiming universal PyTorch/ONNX support, training/autograd or multi-device
  execution from one successful custom operation.
- Selecting a fabrication node, purchasing a board, licensing proprietary IP,
  or committing funds without the appropriate decision and authorization.
- Deleting inherited graphics functionality, weakening regression coverage,
  or rewriting working compute hardware merely to rename the project.

The immediate deliverable is an auditable development foundation. New AI
capabilities must earn their own acceptance evidence in later phases.
