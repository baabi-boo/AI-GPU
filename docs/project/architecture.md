# AI-GPU target architecture

This document defines the **development direction and integration boundaries**.
It does not certify a working AI product. The [baseline](baseline.md) records
inherited source, while [roadmap.json](roadmap.json) owns live phase status and
acceptance. Implemented Vortex subsystem contracts remain in
[the technical design documents](../designs/).

The target is a programmable AI accelerator: general parallel cores handle
control and ordinary arithmetic, tensor units accelerate matrix work, a memory
hierarchy feeds both, and a supported software stack makes the result usable.
“NVIDIA-style” is an architectural ambition, not a CUDA, NVLink, performance or
product-equivalence claim.

## 1. Existing foundation and planned additions

| Boundary | Inherited foundation | Planned AI-GPU work and gate |
|---|---|---|
| Application and framework | Native kernel examples; no demonstrated in-tree model/framework backend | Fixed tiny-model execution in P04, then a thin Python/PyTorch custom-op bridge in P05 |
| Operator library | [Tensor API](../../sw/kernel/include/vx_tensor.h), [GEMM](../../tests/regression/sgemm_tcu_wg/) and [attention](../../tests/regression/flash_attn_tcu_wg/) examples | Reusable, versioned operators with explicit supported shapes, formats and errors in P03 |
| Host runtime | [Runtime API](../designs/vortex_runtime_api.md), buffers, queues, events, modules and launches | Reuse the existing API; add tested operator wrappers and resource-lifetime contracts rather than replacing it |
| Work submission | [Command processor](../designs/command_processor.md) and kernel-dispatch machinery | Prove transfer, launch, completion and recovery behavior across the selected backend in P01/P07/P08 |
| Programmable compute | [SIMT cores](../designs/microarchitecture.md) and [tensor unit](../designs/tensor_core_wgmma_engine.md) | Freeze and verify native arithmetic in P02; optimize measured bottlenecks in P06 |
| On-device memory | [Caches](../designs/cache_subsystem.md), [memory fabric](../../hw/rtl/mem/) and [DXA tiled copies](../designs/dxa_async_copy_multicast.md) | Establish usable capacity, ordering, reuse and bandwidth contracts for the chosen configuration |
| Physical platform | [FPGA AFU shells](../designs/fpga_afu_shell.md), platform descriptors and synthesis flows | Select and measure one real board in P07; separately qualify ASIC memories, interfaces and packaging in P10/P11 |

“Inherited” means source is available for inspection, not that this setup has
reproduced every configuration or run it on physical hardware. Existing graphics
and ray-tracing blocks remain intact; an AI profile may disable unneeded blocks
without deleting their implementation or tests.

## 2. First end-to-end execution path

The first model path is deliberately native:

1. A fixed model executor maps each accelerated operation to a supported operator.
2. The operator validates tensor metadata, capabilities and memory requirements,
   then submits explicit transfers and a compiled native kernel through
   [`vortex2.h`](../../sw/runtime/include/vortex2.h).
3. Native kernels use the existing tensor interface, shared memory and ordinary
   SIMT instructions. Queues/events express completion and resource lifetime.
4. The executor collects results, compares them with the frozen reference and
   records dispatch/transfer evidence. A later Python layer calls the same proven
   host interface; it must not silently substitute CPU execution.

[ADR-001](decisions.md#adr-001--native-tensor-kernels-before-a-new-hip-stack)
sets this sequencing. The inherited [HIP/chipStar route](../designs/hip_on_vortex_chipstar.md)
goes through SPIR-V and PoCL and does not expose the Vortex-specific tensor
intrinsics through that path. A replacement HIP compiler is therefore **not a
prerequisite** for first native inference. Preserve existing HIP/OpenCL routes;
consider new compiler work only for a demonstrated requirement and reviewed plan.

## 3. Execution backends are not interchangeable evidence

| Execution route | What must be identified | Boundary of the result |
|---|---|---|
| SimX | Source/configuration, timing mode and arithmetic model | Simulator behavior; functional-only timing cannot establish physical speed |
| Native processor RTL | RTL configuration and native tensor arithmetic backend | Processor datapath behavior; it does not cover the complete AFU/platform surface |
| XRT integration/emulation | Shell/platform, target, command/DMA path and model versions | Full declared integration scope; `hw_emu` is not a physical board |
| Physical FPGA | Device identity, platform/firmware, bitstream hash, runtime `hw` target and achieved clock | Measurements of that board/configuration, not a manufactured custom GPU |
| Custom silicon | Qualified implementation, package/board revisions and laboratory conditions | Measurements of that fabricated device only |

DPI arithmetic calls into C and cannot stand in for native tensor-datapath
verification. Likewise, synthesis estimates and a generated layout do not
establish physical execution or foundry sign-off. See [verification](verification.md)
and [hardware](hardware.md) for the required evidence and platform obligations.

## 4. Contracts that every layer must preserve

- **Tensor and numerical contract:** declare dtype, input/accumulator/output
  formats, shape, stride/layout, alignment, exceptional-value behavior and frozen
  tolerances. An enumerated format is not automatically an advertised supported
  configuration. Reject unsupported signatures explicitly.
- **Memory and lifetime contract:** validate byte extents and integer overflow;
  distinguish host pointers from device addresses; specify ownership, transfers,
  cache visibility, ordering and completion. Retain resources until asynchronous
  work finishes, including error paths.
- **ABI and capability contract:** use explicit-width wire fields, tested RV32/RV64
  packing and capability checks. The installed runtime API is not silently
  redefined by a Python binding or operator wrapper.
- **Execution contract:** trace operator/kernel/backend placement and account for
  permitted host work separately. A CPU reference or opt-in fallback cannot
  satisfy an accelerator-execution claim.
- **Physical interface contract:** identify actual accessible memory banks and
  controller/PHY ownership, PCIe/DMA behavior, reset and error semantics. A
  simulator memory setting does not create real DDR/GDDR/HBM hardware.

The detailed software contracts are in [software.md](software.md); physical
interface, funding and sign-off obligations are in [hardware.md](hardware.md).

## 5. Architecture-review invariants

1. Preserve the bidirectional isolation of `sw/kernel`/`sw/runtime` from `hw`/`sim`.
   Shared internal definitions belong in `sw/common`; installed public headers
   stay self-contained. Do not bypass these boundaries to accelerate integration.
2. Keep RTL and SimX timing behavior synchronized. Modules communicate through
   their declared interfaces/channels, and changes satisfy applicable parity,
   numerical, performance and logic-depth obligations.
3. Keep configuration ownership in `VX_config.toml` and `VX_types.toml`, with
   regenerated build artifacts and identical application/backend settings.
   Never patch generated headers or change defaults to hide a regression.
4. Review external ABI/ISA/compiler changes together with downstream consumers
   and matching toolchain artifacts. Respect the source/prebuilt/consumer landing
   order and authorized repository boundaries.
5. Preserve golden data, tolerances, licensing and inherited regression coverage.
   Select benchmark contracts before measurements and retain failed evidence.
6. Treat a PyTorch custom-op bridge, a full device backend, autograd/training and
   multi-device operation as separate capabilities requiring separate proof.

Apply [AGENTS.md](../../AGENTS.md) and the inherited
[review policy](../review/code-review-policy.md) before accepting architectural
changes. Scope, implementation and evidence must agree in the final tree.

## 6. Decisions still required

The [decision log](decisions.md) records unresolved choices: the first native
configuration and format subset, tiny model and operator manifest, framework
versions, board/platform, performance/resource budgets, multi-device transport,
and any ASIC PDK/IP/package/funding program. No device capacity, clock, process
node, purchase or manufacturing date is selected by this document.

P05 and P06 build on accepted P04 inference. P07 adds physical FPGA proof; P08
combines that proof with framework and reliability work. P09 training/multi-device
research is a separate branch, not a prerequisite for the bounded inference-ASIC
path through P10/P11. Exact dependencies and closure evidence remain canonical in
[roadmap.json](roadmap.json).
