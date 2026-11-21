# P05 entry handoff — bind the qualified native path

**Current bounded action:** independently qualify the implemented copying Python
binding to the managed matmul owner and frozen P04 case runner. The
[development audit](p05-binding-audit.md),
[implemented contract](../designs/python_binding_v1.md) and
[compatibility matrix](p05-python-compatibility.md) record this continuation.
Keep the native executable as an independent comparison path.
The [P05 phase guide](phases/p05-framework.md) defines the complete phase;
this handoff retains the entry requirements for its first work package.

## Readiness and retained inputs

Implementation entry requires P04 to be `complete` in the
[canonical roadmap](roadmap.json), with compatible passing evidence linked for
**P04-A02 and P04-A03**, in addition to the existing
[P04-A01 fixture acceptance](evidence/p04-fixture/acceptance.json).
Review the [executor evidence](evidence/p04-executor/README.md) and its independent
qualification decision before changing phase status. Individual passing CI jobs,
an incomplete packet, or this handoff do not satisfy that condition. P05 is now
`in_progress`; its acceptance gates require their own evidence and are not earned
by P04 execution.

Use these versioned inputs without broadening their accepted behavior:

| Input | Binding consequence |
|---|---|
| [Operator manifest](../../ci/project/p03_operator_manifest.json) and [contract](../designs/ai_operator_contract_v1.md) | Exactly six matmul signatures: FP16 or BF16 for each `(M,N,K)` in `(8,4,8)`, `(8,4,16)`, `(16,8,16)`; FP32 accumulation/output |
| [Managed matmul API](../../sw/runtime/ai/runtime.h) and [implementation](../../sw/runtime/ai/runtime.cpp) | Internal C++ owners copy module bytes and submitted host inputs; operations own their outputs and may outlive the session owner |
| [Managed MLP API](../../sw/runtime/ai/mlp_runtime.h) and [implementation](../../sw/runtime/ai/mlp_runtime.cpp) | A fixed graph copies `MlpCase`, including expected hidden, bridge and final words; it is a qualification executor with internal comparisons |
| [Frozen model contract](../designs/tiny_mlp_fixture_v1.md) and [fixture manifest](../../ci/project/p04_model_manifest.json) | Batch 16, bias-free `16 → 8 → 4`, five input families in each format, three native matmuls, explicit host ReLU/exact cast and row assembly |
| [Execution record contract](../designs/mlp_execution_records_v1.md) | Preserve actual-input lineage, native placement, separate host work, completion, cleanup, profiling and source/build identities |
| [P03 handoff](p03-operators-handoff.md) and [P04 executor plan](p04-executor-plan.md) | Keep their lifecycle and provenance obligations when adding another caller |

The operator manifest explicitly has `installed_api: false`; the C++ wrappers
are not a stable installed C ABI. The native test app builds those implementation
sources alongside its host executable. A Python package must therefore define
its own reviewed build and version boundary. Do not treat C++ class layout,
`std::vector`, `std::string` or `unique_ptr` as a `ctypes` ABI, or confuse the
56-byte device launch argument block with a host extension ABI.

## First implementation slice

Start with a small C++ extension that owns the existing C++ objects and exposes
opaque Python session/operation objects. Choose and pin the extension mechanism
and Python build environment in a reviewed package contract before adding its
dependency. This keeps the first slice on the existing native implementation;
introducing a general installed C facade is a separate external-contract decision.

The first vertical test should create a qualified session, submit one supported
FP16 matmul, obtain and explicitly close its operation, and compare its actual
FP32 bits with the unchanged native executable/reference. This is an integration
checkpoint only. Expand to all six accepted signatures and both model formats
before claiming the package's declared support matrix.

The entry design has three responsibilities. Their implemented names and exact
behavior are now versioned in the [binding contract](../designs/python_binding_v1.md):

1. **Qualified session.** Load the identified module/runtime/backend through a
   trusted package or launcher configuration, then create `ManagedMatmul`.
   Verify source/build/profile compatibility before setting `ExecutionBinding`.
   Python callers must not establish provenance by supplying a plausible
   qualification string or setting `verified_*` flags themselves.
2. **Owned matmul operation.** Validate representations, copy input buffers,
   submit the native request, and retain the operation through partial failure,
   wait, result publication and explicit close. Expose validation, primary,
   cleanup and completion separately. A convenience exception must preserve an
   incompletely drained operation; throwing it away loses the lifetime contract.
3. **Fixed-case model qualification.** Select a named case from the hash-pinned
   fixture and call `ManagedMlp`. Keep expected arrays internal comparison data.
   Expose actual outputs and traces only with their validity/completion status.
   Do not accept arbitrary caller-provided reference arrays as proof of model
   correctness. Arbitrary weights, model loading and a reference-free inference
   interface require their own design and numerical qualification.

## Freeze representations and ownership before code

| Boundary | Initial binding policy to specify and test |
|---|---|
| Input representation | Explicit `fp16`/`bf16` tag plus exact little-endian 16-bit element bytes; no implicit Python-float conversion or invented NumPy BF16 behavior |
| Shapes/layouts | Rank two; A row-major `(M,K)`, B column-major `(K,N)`; exact accepted shape tuples, byte extents and strides; reject broadcasting, padding, transpose and unsupported views |
| Copies | Copy into native-owned storage before submission returns, as the current wrapper does; document any explicit layout conversion separately; make no zero-copy claim |
| Addressing | Python buffers are host storage, never device addresses; device allocations, four-byte alignment, disjoint ranges and wire encoding stay under native validation |
| Output | Return an owned copy of actual row-major FP32 words after successful completion; keep a raw-bit view for exact comparison and define any convenience numeric view explicitly |
| Partial failure | Keep a returned native operation even when submission failed; preserve its first error and cleanup result; publish no successful tensor from incomplete or failed work |
| Timeout | Retain the operation/session after a timed-out wait or close; a timeout is not cancellation; `ManagedMlp::advance` applies its timeout per wait/drain, not as a whole-call deadline |
| Release | Require explicit close/drain and define context-manager, interpreter-shutdown and interrupted-wait behavior; native destructors can drain indefinitely, so garbage collection cannot promise bounded cancellation |
| Concurrency | Preserve the native single-caller rule; serialize access to each owner and operation; specify GIL release and Python object retention before allowing waits outside the GIL |
| Errors | Version the mapping for unsupported dtype/shape/layout/profile, invalid extent, native failure, incomplete work, numerical mismatch and cleanup failure; preserve their separate underlying codes |

Initially accept packed byte buffers with explicit metadata, so the package's
core correctness does not depend on a framework dtype adapter. Add NumPy or
framework adapters only after their byte order, stride, copy and conversion rules
are declared and tested. Preserve references to Python exporters until copying
finishes; return independent output ownership so closing a native operation
cannot invalidate a Python result.

## Package and qualification work

Record exact tested Python, compiler, extension mechanism, native runtime,
backend, profile and optional framework versions. Select the actual versions in
the implementation environment; this plan does not guess a supported release.
Define how the clean package finds its matched runtime library and module,
records their identities, and rejects missing or mismatched prerequisites.
Build in fresh generated trees, keep incompatible native variants separate, and
test installation from a built artifact in a clean environment outside the source
checkout. Do not silently install or rebuild an entire GPU toolchain at import.

The binding's first qualification packet must cover:

- All six matmul signatures, exact bit agreement with the native comparison path,
  and the frozen model families in FP16/BF16 on the declared backends.
- Invalid tags, ranks, shapes, strides, lengths and overflow; read-only inputs;
  unsupported layout/implicit-conversion requests; wrong profile or module.
- Input mutation/release after submission, operation results surviving close,
  session release while operations remain, repeated calls and resource accounting.
- Partial submission, allocation failure, timeout/retry, explicit drain,
  interrupted waits and cleanup failure, with host-injected cases identified
  separately from actual native observations.
- Clean package build/install/import, matched module/backend loading, actionable
  missing-dependency errors, package identity and a reproducible native invocation.
- Actual three-launch model traces and exact hidden/bridge/final comparisons;
  no substituted reference tensors and no CPU matmul fallback after native error.

Use source-bound fixtures and preserve exact native comparisons. Adding Python
does not authorize regenerating the frozen fixture or widening numerical bounds.
The Python route needs its own evidence; existing native records are its baseline,
not proof that the binding ran. Apply independent review to the new external API,
build surface and any changed enforcement before acceptance.

After the plain Python route is qualified, add only the declared PyTorch custom
operators and reproduce the fixed model through them. Report their native
matmuls and the explicitly allowed host bridge separately. Unsupported autograd
must fail explicitly. A scoped custom operator does not establish a full device
backend, arbitrary model support, training, ONNX execution or CUDA compatibility.
All three [P05 acceptance gates](phases/p05-framework.md#deliverables-and-acceptance)
remain necessary: binding/install proof, framework model dispatch, and a tested
compatibility matrix with explicit limits.

## Separate obligations

[P06](phases/p06-performance.md) can proceed from accepted P04 independently of
Python. Its first task is a frozen benchmark and unchanged baseline with validated
cycle/counter meaning, warm-up and repetition policy, work/traffic counts, and
source/tool/configuration identity. The P04 host steady-clock profiles support
accounting; they do not measure physical GPU latency, bandwidth, throughput or
energy. Event intervals overlap host waits, and `advance_ns` contains nested
host work; do not sum those categories into a manufactured total.

[P01-A03](evidence/p01-xrt-blocked.json) remains blocked on the declared vendor
XRT `hw_emu` integration prerequisites and is still required before P07 can close.
Processor `rtlsim` bypasses the AFU and cannot satisfy that obligation.
The [initial CI record](evidence/p04-executor/initial-ci.json) also preserves the
existing tensor DSP increase from **267 to 283**, beyond the unchanged 5% area
gate. Attribute and resolve that regression in its own measured investigation;
Python work, smaller green jobs and unchanged simulator numerics do not resolve
it. Preserve goldens and thresholds, and follow the paired SimX/RTL and resource
rules for any subsequent hardware change.
