# Native AI operator contract v1

## Implemented scope

The internal C++17 [planner](../../sw/runtime/ai/contract.h) validates a bounded
ordinary WMMA matmul request and produces checked device-argument bytes. The
[manifest](../../ci/project/p03_operator_manifest.json) is the machine-readable
contract. P03-T02 adds a [managed runtime wrapper](../../sw/runtime/ai/runtime.h),
[matching device kernel](../../sw/kernel/ai/matmul.cpp) and
[qualification runner](../../ci/project/p03_execute.py). Acceptance and phase
state remain in the [canonical roadmap](../project/roadmap.json).

**Planning success does not mean execution availability.** Every returned
`MatmulPlan` has `execution_available == false`; the pure planner performs no
allocation, transfer or dispatch. The separate managed wrapper executes the
declared matmul signatures through `vortex2.h` when supplied a qualified runner
binding. Source availability does not establish execution acceptance.
`sw/runtime/ai/` remains experimental internal source, with no installed API,
CPU fallback, implicit arithmetic conversion or new arithmetic implementation.

The first model-facing operation is a small dense linear projection. Its inputs
and outputs can become building blocks for a later fixed model, but composition,
activations, casts, bias, model selection and inference remain separate work.

## Operator availability

| Family | Current state | Boundary |
|---|---|---|
| Matmul | `implemented` | Checked planning, managed transfers/launch/completion and matching device reader for the six signatures below; execution qualification is separate |
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

The supported tuples `(M, N, K)` are exactly `(8, 4, 8)`,
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
The new kernel reuses the same ordinary WMMA K traversal, fragment loads,
positive-zero initialization and output stores. The independently reviewed [P03 execution evidence](../project/evidence/p03-managed-matmul/acceptance-numerics.json)
qualifies this managed path at the exact source and scope recorded below.

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
match. The managed wrapper retains the supplied module bytes and execution
binding alongside its runtime context.

The existing [`vortex2.h`](../../sw/runtime/include/vortex2.h) queries expose
geometry, memory size, architecture and feature flags. They do not expose the
full numerical backend/format configuration. The TCU feature bit alone cannot
verify this profile. This contract does not invent a query or change the runtime
ABI to conceal that limitation.

The internal `ExecutionBinding` is supplied by the trusted qualification runner,
not inferred from the tensor-feature bit. Before launching the native caller,
the runner independently validates runtime, arithmetic backend, kernel and host
compiler records; reproduces generated configuration headers; hashes the actual
host, module and runtime/backend artifacts; and selects the corresponding
`VORTEX_DRIVER` and exact runtime library directory. A SHA-256 identifier over
that binding accompanies each recorded operation. The wrapper accepts the
qualified input dtype and module bytes, loads those bytes, and separately
checks the queried device geometry and required features.

This is an internal trusted-build boundary. A 64-character binding identifier
is not proof by itself, and directly constructing `ExecutionBinding` does not
perform the runner's provenance checks. It does not authenticate arbitrary
hardware or protect against a malicious concurrent filesystem writer.

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
or prove that the referenced memory exists. `ManagedMatmul` therefore accepts
compact host input spans and creates its own three buffers. It records each
returned device address, exact allocated extent, access permission and context
identity before calling the planner. Arbitrary handles, allocation metadata and
caller-created subviews cannot enter this dispatch API. The pure planner keeps
its broader checked-view contract and takes no ownership of buffer handles.

## Internal argument ABI

`MatmulArguments` is an internal 56-byte schema now shared through
[`sw/common/ai_matmul_args.h`](../../sw/common/ai_matmul_args.h). Its layout is
unchanged from the accepted P03-T01 contract. The new device reader matches the
explicit host encoder. These bytes remain incompatible with the inherited
regression `kernel_arg_t` and must not be submitted to that kernel.

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
`decode_matmul_arguments` reconstructs each field from little-endian bytes and
validates version, byte count, reserved fields, compiled input dtype, exact shape
tuple, alignment, representation and pairwise range separation. Failure leaves
the decoder output unchanged. The kernel also checks launch geometry. A rejected
raw invocation returns without touching D; this schema has no device error-result
field. Managed calls reject unsupported requests before launch.

The encoder accepts an address representation width of 32 or 64 and verifies complete
operand ranges, alignment, shape, dtype and pairwise disjointness before writing.
For example, a 128-byte operand beginning at `0xffffff80` fits 32-bit addresses;
moving it four bytes higher does not. Addresses remain u64 fields in both
encodings. These boundary values prove representability, not an actual device
aperture or memory mapping. The width-32 encoding is an ABI representation check only:
`plan_matmul` still rejects an RV32 execution profile.

## Errors and atomic output

The planner and encoder are `noexcept`, allocate no resources and leave their output
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

## Managed execution and completion

`ManagedMatmul::create` copies the supplied module image, opens device index zero,
queries capabilities, loads the image and resolves the public `.vxbin` entry
`main` (the image packer maps the device symbol `kernel_main` to that name). Its context
owns the device, module and kernel. Each `submit` creates a separate queue and
three buffers, copies both input byte spans into owned host storage, and prepares
explicit little-endian output poison. The operation enqueues three writes, one
kernel launch and one read, with dependency events between commands. The launch
uses the runtime's host-blob argument staging; host pointers are never encoded
as device addresses.

The objects support one caller at a time. An operation shares the context and
may outlive its `ManagedMatmul` owner. It owns input/output staging, queue,
buffers and events until terminal completion is established. `MatmulTrace`
records the execution binding, actual addresses and sizes, exact argument bytes,
poison, enqueued command counts, wait counts and observed event results.

| API/result | Required caller behavior |
|---|---|
| `create(binding, &owner)` | Supply a pointer to an empty `unique_ptr` and a binding already validated by the trusted runner; inspect validation, primary and cleanup statuses |
| `submit(..., &operation)` | Supply a pointer to an empty `unique_ptr`; retain a returned operation even when submission reports a primary runtime error, because earlier commands may already be queued |
| `wait(timeout_ns)` | Inspect both status and `complete`; a successful enqueue is not completion, and a timeout leaves ownership intact for a later wait |
| `output_words()` | Read output only after successful completion; unavailable output is an empty vector |
| `operation.close(timeout_ns)` | Release only after established completion; if `complete` is false, keep the operation alive and retry |
| `owner.close()` | Close after operations release their contexts; outstanding operation ownership returns timeout/incomplete without destroying the context |

`ExecutionResult.validation` describes request rejection, `primary` preserves the
first runtime failure, and `cleanup` separately records release failures.
`complete` describes whether submitted work is terminal. Timeout is not a
terminal failure and never authorizes early release. Completion checks use both
the event wait result and completion value, then collect individual event
results before exposing output.

The operation destructor drains indefinitely to avoid freeing resources still
in use. Applications requiring bounded latency must use explicit timed waits and
retain ownership when `close(timeout_ns)` is incomplete; destroying that object
does not cancel device work. Explicit close is also how callers observe cleanup
errors instead of discarding them during destruction.

The common queue owns retained resources even when dependency failure or a
sticky queue error skips command execution. It destroys those captures before
signaling completion. Linear buffer bounds reject unsigned wraparound, failed
map submissions cancel their staging, and scratch recycling handles host
allocation failure without abandoning a device allocation. Actual runtime
tests, fault-injection tests and arithmetic executions remain distinct evidence
scopes; see the [handoff](../project/p03-operators-handoff.md).

## Qualified execution scope

At clean source `319ad63532cee17ae88fa75757a5ac87ed5c6a77`, the managed operator matrix
executed all 88 unchanged independent P02 layout/numerical fixtures on both
SimX and native processor RTL: **176 case/backend executions, 352 launches and
14,336 exact FP32 output-word comparisons passed**. Each launch used separately
poisoned output storage and retained actual argument, transfer, dispatch,
completion and memory-accounting records. The independent CPU-produced fixture
words remain the oracle; the production simulator does not generate expected
answers, and no tolerance or golden value was relaxed.

The [numerical acceptance](../project/evidence/p03-managed-matmul/acceptance-numerics.json) covers only the
six declared FP16/BF16-to-FP32 signatures and accepted RV64 profile. Separate
[lifecycle acceptance](../project/evidence/p03-managed-matmul/acceptance-lifecycle.json) records the actual
RV64 `p02-tfr` SimX and default RV32 SimX executions, each passing 12 groups, together with
explicitly scoped host fault-injection tests. RV32 common-runtime lifecycle
coverage does not extend the matmul execution profile to RV32. The RV32
receipt's `cache_enabled=false` records disabled compiler caching; the actual
processor configuration had instruction and data caches enabled.

Transfer-failure tests inject host allocation failures at identified simulated
DMA staging and software command-processor stages. They check propagation,
resource release, preserved seeded output and subsequent recovery at those
points. They do not establish atomic rollback for arbitrary partially completed
DMA, real device removal, physical reset/recovery or hardware transport failures.
A failed or partially submitted operation can have performed earlier work;
this API does not provide transactional cancellation.

Native processor RTL bypasses the AFU and retains integer DPI helpers while
using native TFR tensor and STD scalar arithmetic. No physical FPGA throughput,
power, synthesis/PPA, vendor `hw_emu` or fabricated-silicon result follows.
P01-A03 remains a separate blocked vendor-integration obligation before P07.
