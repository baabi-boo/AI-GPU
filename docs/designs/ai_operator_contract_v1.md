# Native AI operator contract v1

## Implemented scope

The internal C++17 [planner](../../sw/runtime/ai/contract.h) validates a bounded
ordinary WMMA matmul request and produces checked device-argument bytes. The
[manifest](../../ci/project/p03_operator_manifest.json) is the machine-readable
contract. These files implement P03-T01's input and argument boundary; acceptance
and phase state remain in the [canonical roadmap](../project/roadmap.json).

**Planning success does not mean execution availability.** Every returned
`MatmulPlan` has `execution_available == false`. There is no runtime dispatch,
allocation, transfer, CPU computation, CPU fallback, device argument reader or
installed API in this module. `sw/runtime/ai/` is experimental internal source;
it changes no existing runtime header, runtime symbol or install rule.

The first model-facing operation is a small dense linear projection. Its inputs
and outputs can become building blocks for a later fixed model, but composition,
activations, casts, bias, model selection and inference remain separate work.

## Operator availability

| Family | Current state | Boundary |
|---|---|---|
| Matmul | `contract_only` | Validated descriptors and argument encoding for the signatures below; no launches |
| GEMV | `unavailable` | No vector signature or implicit vector padding |
| Reductions | `unavailable` | No axis, reduction-order or numerical contract |
| Softmax | `unavailable` | No reusable reduction/exp signature |
| Normalization | `unavailable` | No formula, epsilon or parameter signature |
| Activations | `unavailable` | No implicit or fused activation |
| Layout conversion / casts | `unavailable` | Input layout and dtype must already match |
| Attention | `unavailable` | No reusable masking, layout or launch contract |

`plan_matmul` returns `unsupported_operator` for every non-matmul operator ID,
including unknown enum values. Availability never follows merely from inherited
example source being present.

## Frozen matmul signature

The supported **contract** tuples `(M, N, K)` are exactly `(8, 4, 8)`,
`(8, 4, 16)` and `(16, 8, 16)`, for each of FP16 and BF16 inputs. They are the
union of the accepted P02 [layout fixtures](../../ci/project/fixtures/p02_layout_v1.json)
and [numerical fixtures](../../ci/project/fixtures/p02_wmma_numerical_v1.json).
They are not independent dimension ranges: `(16, 8, 8)`, for example, is rejected.

| Operand | Logical dimensions | Dtype | Storage | Exact byte strides |
|---|---|---|---|---|
| A | `[M, K]` | FP16 or BF16 | Compact row-major | `[K * 2, 2]` |
| B | `[K, N]` | Same dtype as A | Compact column-major | `[2, K * 2]` |
| D | `[M, N]` | FP32 | Compact row-major | `[N * 4, 4]` |

All descriptors have rank two. Batch count is one. Transpose flags, padding,
noncompact strides, mixed input dtypes, zero dimensions, arbitrary shapes and
nonzero request flags are rejected. Initial accumulation is the exact FP32
positive-zero word `00000000`; negative zero and nonzero initial C are rejected.
There is no input-C tensor, alpha/beta scaling or in-place accumulation.

Arithmetic is the [P02 TFR contract](tensor_numerics_v1.md), with its ordered
four-product reductions, finite alignment window, RNE behavior, input subnormal
handling, signed output flush-to-zero, infinities and canonical NaNs. The
[ordinary WMMA acceptance record](../project/evidence/p02-wmma/acceptance.json)
defines the existing execution evidence. This planner introduces no arithmetic
implementation, reference values, new tolerances or broader IEEE guarantee.
P03 operator execution must still be independently demonstrated after launch
wrappers are implemented.

The plan records grid `[N / 4, M / 8, 1]`, block `[4, 1, 1]` and zero dynamic
local-memory bytes, matching the ordinary `8 x 4 x 8` tile origin. These are
planned launch dimensions, not a submission to the runtime.

## Device and profile binding

`DeviceCapabilities` represents explicit caller-obtained runtime information.
It must identify a nonzero registered device and the exact bounded profile:
64-bit ISA/address representation, four threads per warp, four warps per core, one core, one
cluster, issue width one, 16,384 bytes of local memory, and enabled tensor and
local-memory extensions. A changed value returns `unsupported_profile`.

`ProfileBinding` must identify `p02_tfr_wmma_v1` and set both
`verified_kernel_profile` and `verified_device_profile`. These flags are
**caller attestations**, not a verification performed by the planner. They may
be set only after the actual kernel/module configuration and actual device
configuration have been bound to the accepted
[`p02-tfr` profile](../../profiles/p02-tfr.json). In particular, the selected
native tensor/scalar arithmetic, tensor-format bank and excluded features must
match. A future wrapper must retain that provenance alongside its module.

The existing [`vortex2.h`](../../sw/runtime/include/vortex2.h) queries expose
geometry, memory size, architecture and feature flags. They do not expose the
full numerical backend/format configuration. The TCU feature bit alone cannot
verify this profile. This contract does not invent a query or change the runtime
ABI to conceal that limitation.

`address_bits` denotes the ISA/address representation width, **not** the device's
physical aperture or the validity of a virtual mapping. RV64 can have a narrower
device address space; the current configuration derives a 48-bit memory address
width for RV64 in [`VX_config.toml`](../../VX_config.toml). The allocation registry
and profile binding must separately establish actual addressability, aperture
limits and valid mappings before any dispatch. The planner cannot authenticate
those properties from the supplied integer addresses.

## Allocation views and bounds

`AllocationView` is a snapshot from the caller's allocation registry. Its
nonzero `device_id` and `allocation_id` are stable registry identities, never
host addresses or automatically inferred handle values. The registered device
must match the selected `DeviceCapabilities.device_id`.

The registry supplies the true allocation base device address, byte extent and
read/write permissions. A/B require read access; D requires write access.
`TensorView.offset_bytes` selects a subrange. Both allocation base and view
offset must be four-byte aligned, including packed FP16/BF16 inputs.

The planner checks dimension multiplication and byte-size multiplication for
unsigned overflow, then checks `offset <= allocation_size` and
`required_bytes <= allocation_size - offset`. Device-address addition is checked
before constructing the accessed address. **The entire tracked allocation**
must fit the address representation width, including an unused tail, and the accessed subrange
must also fit. A final byte at the maximum representable device address is
valid for representation; a wrapped end or truncated address is not. Passing
this check does not establish that the physical or virtual address is usable on
the device.

The A, B and D accessed ranges must be pairwise disjoint, including read-only
A/B overlap. Adjacent ranges are permitted. Disjoint subviews may share one
allocation, but repeated allocation IDs must have identical base address,
extent, device identity and permission metadata. Conflicting metadata returns
`invalid_argument`. Aliasing is checked by absolute device address even when
different allocation IDs are supplied.

The runtime currently has no general buffer-extent or buffer-owner query.
Consequently this module cannot authenticate arbitrary caller-supplied metadata
or prove that the referenced memory exists. The later managed wrapper must
record metadata when it creates/reserves buffers and prevent unverified views
from entering dispatch. The pure planner takes no ownership and retains no
buffer handles.

## Internal argument ABI

`MatmulArguments` is a **new internal 56-byte schema** for a later reader. It is
not compatible with the existing regression `kernel_arg_t`, and its bytes must
not be submitted to that kernel. P03-T02 must implement and review the matching
kernel reader or explicit adapter before any launch. If the definition becomes
shared with a kernel, move the shared definition into `sw/common/` through the
normal contract review; do not introduce a cross-layer include.

| Offset | Field | Width | Required value |
|---:|---|---|---|
| 0 | `abi_version` | u32 | 1 |
| 4 | `byte_size` | u32 | 56 |
| 8 | `input_dtype` | u32 | 1 = FP16; 2 = BF16 |
| 12 | `flags` | u32 | 0 |
| 16 | `m` | u32 | M from an accepted tuple |
| 20 | `n` | u32 | N from the same tuple |
| 24 | `k` | u32 | K from the same tuple |
| 28 | `reserved` | u32 | 0 |
| 32 | `a_address` | u64 | Validated device address |
| 40 | `b_address` | u64 | Validated device address |
| 48 | `d_address` | u64 | Validated device address |

The structure has explicit eight-byte alignment and static assertions for size
and every offset. `encode_matmul_arguments` writes each scalar explicitly in
little-endian order; it does not copy native struct representation, implicit
padding, `size_t`, pointer values or host endianness into the output.

The encoder accepts an address representation width of 32 or 64 and verifies complete
operand ranges, alignment, shape, dtype and pairwise disjointness before writing.
For example, a 128-byte operand beginning at `0xffffff80` fits 32-bit addresses;
moving it four bytes higher does not. Addresses remain u64 fields in both
encodings. These boundary values prove representability, not an actual device
aperture or memory mapping. The width-32 encoding is an ABI representation check only:
`plan_matmul` still rejects an RV32 execution profile.

## Errors and atomic output

Both entry points are `noexcept`, allocate no resources and leave their output
object unchanged on every failure. A null output pointer returns
`invalid_argument`. Successful output is constructed locally and assigned only
after every check passes. Callers must obey ordinary C++ object-lifetime rules;
these functions cannot validate a forged or dangling host pointer.

`Status` distinguishes malformed arguments/version, unavailable operators,
unsupported dtype/shape/layout/profile, wrong rank, empty inputs, mismatched
devices, access denial, alignment, buffer bounds, arithmetic overflow, address
width and aliasing. `status_string` returns their stable lowercase names and
`unknown_status` for an unknown status value. No failure silently changes dtype,
pads a shape, substitutes a host implementation or launches a partial request.

For multiply-invalid requests the first failing check is returned. Validation
proceeds through top-level identity/version/operator/options, profile checks,
tensor description/size/strides, shape compatibility, allocation-identity
consistency, per-view memory checks, then address aliasing and encoding. Exact
error precedence is not an execution or allocation ordering guarantee.

## Required ownership and completion implementation

P03-T02 must place an actual wrapper over `vx_device_h`, `vx_buffer_h`,
`vx_queue_h`, `vx_module_h`, `vx_kernel_h` and `vx_event_h`. It must query
capabilities, obtain device addresses through the runtime, maintain trusted
allocation metadata and bind the accepted module/profile. No such wrapper is
implemented by this contract checkpoint.

Before asynchronous submission, the wrapper must retain every buffer, module,
kernel, queue and dependency event needed by the operation. Kernel argument
staging must use the runtime's host-blob contract and the reviewed device reader;
host pointers are never device addresses. Copies, waits, launches and completion
must remain explicit and appear in dispatch records. A successful enqueue is
not successful completion.

Release resources only after completion or an established terminal failure.
A timeout means work may still be outstanding: returning a timeout must not
free in-flight resources. Partial-submit cleanup must preserve the original
runtime failure and separately report cleanup failures. The wrapper must also
test allocation exhaustion, transfer errors, failed dependency events, device
loss, repeated allocation/free and completion ownership. Those results belong
to P03-A02/A03 and cannot follow from host-only planning tests.
