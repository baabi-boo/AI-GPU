# Inherited engineering baseline

This document records the starting point for AI-GPU, not a claim that the
development roadmap is complete. The audit is **source inspection plus lightweight
metadata checks**. No GPU build, simulator workload, FPGA synthesis, physical-board
test or silicon test was executed for this baseline audit.

## Identity and provenance

| Item | Recorded value |
|---|---|
| Project repository | `baabi-boo/AI-GPU` |
| Default branch | `master` |
| Inspected source commit | `da55a516a48b49013724f697d3c12a48932b449f` |
| Git tree | `0048cb4137f1c873b347ae87650ef46a9647479f` |
| Audit date | 2026-11-14 |
| Inherited project | [Vortex GPGPU](https://github.com/vortexgpgpu/vortex) |
| License | [Apache License 2.0](../../LICENSE), with existing third-party terms retained |

The source commit and tree are identical to the corresponding upstream Vortex
revision. Its hardware, simulators, runtime, kernels, tests and diagrams are
inherited engineering by the upstream contributors; the AI-GPU project setup does
not claim authorship of those components. Preserve copyright headers, third-party
notices and [upstream research attribution](../references.md). Historical
upstream paper results are not measurements of this fork.

Current phase state is maintained in [roadmap.json](roadmap.json), not inferred
from the amount of source code or documentation in this baseline.

## Capability inventory

`source_present` means that the named implementation or integration exists in the
inspected tree. It does **not** establish that it builds, passes its tests or works
on a physical device in the selected configuration.

| Inherited capability | Source evidence | Audit evidence | Gap and next phase |
|---|---|---|---|
| Programmable RISC-V parallel GPU | [Core RTL](../../hw/rtl/core/), [microarchitecture](../designs/microarchitecture.md) | `source_present` | Freeze a supported AI configuration and reproduce it in P01. |
| WMMA/WGMMA tensor arithmetic and structured sparsity | [Tensor RTL](../../hw/rtl/tcu/), [tensor design](../designs/tensor_core_wgmma_engine.md) | `source_present` | Verify the selected native arithmetic backend, formats, layouts and concurrency in P01–P02. |
| Floating, integer and block-scaled tensor format definitions | [Tensor configuration](../../sw/common/tensor_cfg.h), [tensor package](../../hw/rtl/tcu/VX_tcu_pkg.sv) | `source_present` | Format identifiers are not universal backend support. Freeze exact numerical behavior and supported combinations in P02. |
| Native tensor-programming interface | [Tensor kernel API](../../sw/kernel/include/vx_tensor.h), [WGMMA GEMM example](../../tests/regression/sgemm_tcu_wg/) | `source_present` | Build a stable, tested AI operator library on this path in P03. |
| Native attention building blocks | [SIMT attention](../../tests/regression/flash_attn/), [WGMMA attention](../../tests/regression/flash_attn_tcu_wg/) | `source_present` | Reproduce their tests; compose and validate a complete tiny model in P04. |
| Host buffers, queues, modules, launches and events | [Runtime API](../../sw/runtime/include/vortex2.h), [runtime design](../designs/vortex_runtime_api.md) | `source_present` | Specify shape, lifetime, transfer and failure contracts for the operator/model runtime in P03–P05. |
| OpenCL and basic HIP integration | [OpenCL design](../designs/opencl_on_vortex.md), [HIP design](../designs/hip_on_vortex_chipstar.md), [actual HIP catalog](../../ci/testcases/sw/hip.yaml) | `source_present` | Basic examples do not establish general framework or CUDA compatibility; use the native kernel route first. |
| Caches, shared memory and asynchronous tile copies | [Memory fabric](../../hw/rtl/mem/), [cache RTL](../../hw/rtl/cache/), [DXA RTL](../../hw/rtl/dxa/) | `source_present` | Measure traffic, useful bandwidth, stalls and scaling on pinned configurations in P06. |
| FPGA shells and board-platform descriptions | [AFU RTL](../../hw/rtl/afu/), [Xilinx platforms](../../hw/syn/xilinx/platforms/), [FPGA guide](../fpga_setup.md) | `source_present` | Choose one supported board, then prove real host transfers, usable external memory and model execution in P07. |
| Simulation and regression infrastructure | [Simulators](../../sim/), [test catalog](../../ci/testcases/), [testing guide](../testing.md) | `source_present` | Attach actual run evidence to each claimed capability; preserve native/DPI and integration distinctions. |
| ASIC synthesis and estimation flows | [Yosys flow](../../hw/syn/yosys/), [Synopsys flow](../../hw/syn/synopsys/), [synthesis guide](../synthesis_analysis.md) | `source_present` | Foundry-qualified IP, physical sign-off, manufacturing and laboratory validation remain P10–P11 work. |

## Important boundaries

- **Tensor acceleration is not enabled by default.** The inspected
  [configuration](../../VX_config.toml) sets `VX_CFG_EXT_TCU_ENABLE` and
  `VX_CFG_TCU_WGMMA_ENABLE` to false. A reproducible AI profile must explicitly
  select its extensions and use matching application/backend settings.
- **Native arithmetic and DPI are different evidence.** TFR is the default
  native tensor backend. DPI delegates arithmetic to C and is simulation-only.
  The inherited tensor catalogs include both. A passing DPI case cannot certify
  a synthesizable native datapath. BHF, DSP, FPNEW and TFR also have different
  numerical and implementation properties; do not combine their results under
  one unnamed backend.
- **Format breadth is not a product guarantee.** The design enumerates
  FP32/TF32/FP16/BF16/FP8/BF8, integer and block-scaled formats. Floating inputs
  accumulate to FP32 and integer inputs to INT32. Backend-specific rounding,
  accumulation and exceptional-value behavior must be tested; NVFP4
  subnormal-scale semantics remain an explicit open question in the inherited
  design.
- **HIP is not CUDA compatibility.** The current route is chipStar → SPIR-V →
  PoCL → Vortex. Its documented limitation is access to Vortex-specific tensor
  intrinsics through that route. Native kernels already have such access. The
  four HIP samples, two excluded from the default sweep, are not evidence of a
  complete CUDA/HIP application ecosystem.
- **A complete AI model/framework stack is new work.** No in-tree end-to-end
  PyTorch/ONNX model executor or general device backend was identified in the
  baseline software/test inventory. Existing GEMM and attention kernels are
  building blocks, not evidence of complete model execution or training.
- **Memory descriptors are not measured capacity.** The selected FPGA shell
  supplies physical memory and PCIe infrastructure. Usable banks and addresses
  depend on the platform configuration; for example, the inspected U250
  description binds DDR bank 0 only. No memory capacity, bandwidth or clock
  performance is accepted from a descriptor alone.
- **Evidence stages stay separate.** SimX, processor `rtlsim`, full XRT
  integration/emulation, physical FPGA operation and silicon measurements must
  be named explicitly. Functional-only SimX mode cannot support timing claims.
  Synthesis estimates, black-box SRAM area and generated layout files do not
  constitute foundry sign-off or a manufactured GPU.

## Dependency pins and reproducibility

The inspected [VERSION](../../VERSION) contains:

| Key | Value |
|---|---|
| `VORTEX_VERSION` | `3.0` |
| `TOOLCHAIN_REV` | `v3.0.2` |
| `GEM5_REV` | `v25.0.0.1` |
| `FIRESIM_REV` | `57bb93f1e23daf46198659ddd93608f70121fee0` |

Tags are not a sufficient reproducibility record by themselves. P01 must also
record resolved toolchain commits, bundle checksums, exact submodule commits,
generated configuration, host environment, commands and exit statuses. At this
audit, all five local third-party submodules were uninitialized; their Git links
still identify the required revisions. This is a local checkout condition, not
an assertion that upstream dependency repositories are missing.

## Preserved README image

- Asset: [vortex_framework_stack.svg](../assets/img/vortex_framework_stack.svg)
- SHA-256: `db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`
- Treatment: preserve its bytes and README embed; retain all other inherited
  diagrams and images as well.

The illustration communicates the inherited GPU/framework concept. It is not a
photograph or proof of a fabricated AI-GPU product.

## What was checked, and what was not

The source identity, dependency declarations, relevant source paths, default
tensor switches and image checksum were inspected. The lightweight command
`python3 ci/testcase.py lint` passed with **945 test cases across 28 categories**.
That checks catalog structure; it does not run those test cases.

GPU compilation, SimX workloads, native RTL workloads, XRT emulation, FPGA
implementation, physical measurements and silicon validation are **not run** for
this audit. Project metadata validation must never be reported as any of those
results. See [acceptance](acceptance.md), [verification](verification.md) and the
[developer guide](developer-guide.md) for the evidence required to advance beyond
this baseline.
