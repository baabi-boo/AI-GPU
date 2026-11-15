# AI software development plan

This is a **planned integration contract**, not a claim that a model runtime,
Python package or framework backend already exists. Current evidence is recorded
in [the baseline](baseline.md); phase status and exit gates are authoritative in
[roadmap.json](roadmap.json). Accountable roles below describe responsibilities,
not appointed staff.

## 1. Start with the native path

The first supported path will be: native tensor kernels, an operator library over
the existing runtime, one reproducible tiny-model executor, a thin Python
binding, then a narrowly scoped PyTorch custom-op bridge. A replacement HIP
compiler or runtime is **not a prerequisite**.

| Existing foundation | What it provides | What it does not establish |
|---|---|---|
| [`vx_tensor.h`](../../sw/kernel/include/vx_tensor.h) | Native WMMA/WGMMA kernel interfaces | General framework dispatch or correctness for every configuration |
| [`vortex2.h`](../../sw/runtime/include/vortex2.h) | Device/buffer/queue/event/module handles, explicit transfers and launches | A model graph executor or a Python API |
| [Native tensor GEMM](../../tests/regression/sgemm_tcu_wg/) and [tensor attention](../../tests/regression/flash_attn_tcu_wg/) | Host/kernel examples and numerical test building blocks | A reusable operator library or complete language model |
| [OpenCL through PoCL](../designs/opencl_on_vortex.md) | An inherited general compute route | Automatic use of all native tensor extensions |
| [HIP through chipStar](../designs/hip_on_vortex_chipstar.md) | HIP → SPIR-V → PoCL → Vortex | Vortex-specific tensor-intrinsic access through that route, complete HIP conformance, or CUDA binary compatibility |

The actual HIP catalog is [`ci/testcases/sw/hip.yaml`](../../ci/testcases/sw/hip.yaml).
Its examples and inherited documentation are starting evidence, not fresh passing
results. Compiler, PoCL and chipStar components are external dependencies; changes
must respect the source/prebuilt/consumer landing order in [AGENTS.md](../../AGENTS.md).

## 2. Deliver software in bounded stages

| Phase and owner role | Deliverable | Acceptance focus |
|---|---|---|
| P03 — Kernel and runtime lead | Versioned operator manifest, native kernels and host launch wrappers | `P03-A01`–`P03-A03`: supported inputs, numerical correctness, bounds and lifetimes |
| P04 — Model runtime lead | A deterministic executor for one fixed, redistributable tiny model | `P04-A01`–`P04-A03`: model provenance, layer/final accuracy and device dispatch evidence |
| P05 — Framework integration lead | Thin Python package followed by supported PyTorch custom operators | `P05-A01`–`P05-A03`: clean installation, typed errors, compatibility matrix and no hidden fallback |
| P09 — Research lead | Separately qualified training and multi-device capabilities | `P09-A01`–`P09-A03`: gradients/convergence, collectives and measured physical scaling |

P01/P02 first establish the reproducible configuration and numerical contract.
P03 should initially support only an explicit, testable subset of shapes and
formats. Extend that subset through reviewed evidence; do not advertise every
format named in the tensor design as production-ready.

## 3. Operator and runtime contracts

Before implementing the public operator surface, review a contract with these
fields and failure behaviors:

| Boundary | Required contract and test |
|---|---|
| Tensor description | Dtype, rank, dimensions, byte strides, layout, alignment, device, accessible byte extent and mutability. Validate size arithmetic and bounds before enqueueing work. |
| Shape support | State supported tiles, padding, batches, transposes and aliasing. Unsupported or empty shapes have documented results or errors, never accidental reads. |
| Numerics | Input/accumulator/output formats, rounding and exceptional-value behavior; use the frozen P02 per-operation tolerances and independent references. |
| Device capabilities | Query the runtime and match the selected kernel configuration. Reject missing tensor features, insufficient local memory or unsupported address widths. |
| ABI | Version argument layouts and operator metadata. Use explicit-width wire fields; test RV32/RV64 conversion and host/device argument packing. A Python host pointer is not a device address. |
| Ownership | Define who retains and releases buffers, modules, queues, kernels and events. Keep dependencies alive until completion, including asynchronous errors and cancellation paths. |
| Transfers and ordering | Make host↔device copies, stream/queue ordering, waits and synchronization explicit. State whether each API is synchronous or returns a completion object. |
| Errors | Preserve actionable runtime errors for invalid inputs, allocation failure, timeout, failed events and lost devices. Test partially completed work and cleanup. |
| Dispatch | Record operator, selected kernel/module, device backend and transfers. A CPU reference is validation machinery, not evidence of accelerator execution. |

Use the existing installed runtime API rather than silently changing its ABI.
Any necessary public ABI or compiler change follows the inherited independent
review and downstream-consumer obligations. Software, hardware and simulator
layer boundaries remain intact; internal shared definitions belong in
`sw/common/`, and installed public headers remain self-contained.

**No silent CPU fallback:** unsupported accelerated work fails explicitly by
default. An intentionally permitted host operation or opt-in fallback must be
listed in the model manifest, visible in dispatch records and counted separately
in performance reporting. It cannot satisfy an accelerator gate for that
operation.

## 4. Implementable next work packages

These packages describe future work; their source modules are not created by this
repository-setup change.

1. Freeze the initial native configuration and reproduce the inherited GEMM and
   small attention cases. Capture exact code, toolchain, generated configuration,
   arithmetic backend, seed and tolerances; distinguish DPI from native RTL.
2. Specify a small operator manifest covering matmul/GEMV, reductions, softmax,
   normalization, activations, layout/casts and attention. Link each supported
   signature to its independent reference, kernel, negative tests and gate.
3. Extract reusable launch/resource-management code from the existing examples
   without changing their regression expectations. Add lifecycle, bad-shape,
   overflow, insufficient-memory and asynchronous-failure tests.
4. Compose the accepted operators into a deterministic tiny model. Pin the model
   structure, fixture generator or redistributable weights, seeds and license;
   compare intermediate layers before accepting the final output.
5. Bind the proven host interface to Python. Test contiguous and unsupported
   strided inputs, copies, object lifetime, exception mapping and repeated runs
   in a clean installation. Do not imply zero-copy transfers without evidence.
6. Register the declared PyTorch custom operators and reproduce the native model
   result with dispatch traces. Publish exact tested versions, limitations and
   unsupported-operation behavior alongside the result.

See [verification](verification.md), [benchmarks](benchmarks.md) and
[acceptance](acceptance.md) for evidence policy. A simulator run may prove the
integration at its stated scope, but physical FPGA claims remain gated by P07.

## 5. Capabilities that require separate decisions

- **Full PyTorch device backend:** custom operators using explicit host/device
  transfers are not a complete device backend. Allocator integration, dispatch,
  tensor placement, streams/events, serialization and broad operator coverage
  need their own design and compatibility tests before such a claim.
- **Autograd and training:** inference does not imply backward kernels, correct
  gradients, optimizer support or convergence. These belong to P09 evidence;
  unsupported differentiation must fail explicitly.
- **ONNX execution:** an importer or execution provider is a later, separately
  scoped integration with pinned opsets, shape semantics and an operator support
  matrix. It is not required to complete the first native model or P05 bridge.
- **Compiler and HIP improvements:** new native HIP, MLIR or tensor-intrinsic
  exposure work may follow a documented bottleneck and reviewed design. Coordinate
  external source and prebuilt artifacts before consuming changed interfaces.
- **Multi-device execution:** transport, collectives, synchronization, ordering,
  failures and recovery require independent P09 tests. Do not equate this work
  with NVIDIA NVLink or CUDA compatibility.

The [decision log](decisions.md) records accepted sequencing and unresolved
framework/configuration choices. Update the [compatibility evidence and release
record](releases.md), not marketing language, when a capability is demonstrated.
