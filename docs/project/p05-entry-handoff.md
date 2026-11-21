# P05 handoff — from the copying binding to scoped custom operators

**Current bounded action:** freeze and implement the supported PyTorch custom-op
route through the existing Python/native owners, then qualify the fixed model
against the independent native executable. No PyTorch version or custom operator
is qualified yet. P05 remains `in_progress`; A02 and A03 are unearned.

[P05-A01 accepts the copying binding](evidence/p05-python/acceptance-binding.json)
on SimX at `e1420fd550f716df33a2556057b7086a03032cbe`. The
[packet](evidence/p05-python/README.md) retains both installed formats, all six
matmul signatures, ten frozen model cases, exact outputs and native dispatch,
clean packaging and independently reviewed host lifecycle/error tests. Its full
matrix has 144 combined launches and 660 event/profile pairs; the clean hosted
suite passed 2,174 tests. This is the tested implementation scope, not a new run
at the later documentation commit.

The [development audit](p05-binding-audit.md),
[implemented contract](../designs/python_binding_v1.md),
[compatibility matrix](p05-python-compatibility.md) and
[P05 phase guide](phases/p05-framework.md) define the boundary to preserve.
The entry requirements and first-slice responsibilities below remain the design
history and obligations for any new caller.

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

## Implemented first slice and preserved boundary

The C++17 CPython extension owns the existing C++ objects and exposes opaque
Python session/operation objects. Its reviewed package contract pins the build
environment and source/native identities; it adds no NumPy or PyTorch runtime
dependency. Introducing a general installed C facade remains a separate
external-contract decision.

The installed qualification now covers all six supported matmul signatures and
both frozen model formats, including explicit operation close and comparison of
actual FP32 bits with the unchanged native executable/reference. Extending that
caller into a framework still requires its own representation and dispatch proof.

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

## Binding boundaries to preserve in the framework adapter

| Boundary | Binding policy to preserve and test |
|---|---|
| Input representation | Explicit `fp16`/`bf16` tag plus exact little-endian 16-bit element bytes; no implicit Python-float conversion or invented NumPy BF16 behavior |
| Shapes/layouts | Rank two; A row-major `(M,K)`, B column-major `(K,N)`; exact accepted shape tuples, byte extents and strides; reject broadcasting, padding, transpose and unsupported views |
| Copies | Copy into native-owned storage before submission returns, as the current wrapper does; document any explicit layout conversion separately; make no zero-copy claim |
| Addressing | Python buffers are host storage, never device addresses; device allocations, four-byte alignment, disjoint ranges and wire encoding stay under native validation |
| Output | Return an owned copy of actual row-major FP32 words after successful completion; keep a raw-bit view for exact comparison and define any convenience numeric view explicitly |
| Partial failure | Keep a returned native operation even when submission failed; preserve its first error and cleanup result; publish no successful tensor from incomplete or failed work |
| Timeout | Retain the operation/session after a timed-out wait or close; a timeout is not cancellation; `ManagedMlp::advance` applies its timeout per wait/drain, not as a whole-call deadline |
| Release | Require explicit close/drain and define context-manager, interpreter-shutdown and interrupted-wait behavior; native destructors can drain indefinitely, so garbage collection cannot promise bounded cancellation |
| Concurrency | One live native context and one outstanding matmul until completed explicit close; main interpreter with the GIL held during native calls; no new queue or out-of-GIL concurrency claim |
| Errors | Version the mapping for unsupported dtype/shape/layout/profile, invalid extent, native failure, incomplete work, numerical mismatch and cleanup failure; preserve their separate underlying codes |

The core API accepts packed byte buffers with explicit metadata. A framework
adapter must declare and test its byte order, strides, copies and conversions
before using that boundary. Preserve references to tensor exporters until copying
finishes; return independent output ownership so closing a native operation
cannot invalidate a framework result.

## Completed binding qualification and remaining framework proof

The hosted binding environment is CPython 3.12.14, G++ 11.4.0, Clang 20.1.8 and
GNU Make 4.3; local unbound packaging used GCC/G++ 14.2.0. The package-build pins
are setuptools 84.2.1, wheel 0.48.0 and packaging 26.3. Exact identities, hosted
RUNPATH entries, external dependencies and redistribution notices remain in the
[packet](evidence/p05-python/README.md) and
[compatibility matrix](p05-python-compatibility.md). These are qualified
environments, not a manylinux or arbitrary-host portability claim.

The accepted binding-source digest is
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.
Its source archive preserves the compiled bundle/source pins for offline wheel
rebuilding. The installed package rejects mismatched artifacts and does not
install a GPU toolchain at import. Each framework addition must retain fresh
separate builds, exact version identities and installation outside the checkout.

The binding packet covers these obligations, with injected failures identified
as host-only evidence:

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

Preserve the source-bound fixtures and exact native comparisons. The accepted
Python route does not authorize regenerating fixtures, widening numerical bounds
or relabelling host-injected failures as accelerator observations. The new
framework caller, external operator schemas and any changed enforcement require
independent review and their own evidence.

## Next bounded framework slice

1. Freeze one supported PyTorch version and platform. Specify the operator
   schemas, accepted tensor devices/dtypes/shapes/strides, packing/copy policy,
   result ownership and explicit errors. No supported release is guessed here.
2. Implement only those custom operators through the qualified binding and
   existing owners. Reject unsupported layouts and gradients explicitly. Keep
   the fixed model and its expected arrays inside the trusted qualification
   boundary; arbitrary model loading is a separate contract.
3. In a fresh framework installation, reproduce all declared signatures and the
   ten frozen model cases against the native comparison path. Retain actual
   input/output bits, native launches, ownership/error tests, host ReLU/exact cast,
   assembly and transfer accounting. A reference result cannot replace execution.
4. Earn P05-A02 from the supported framework route's simulated execution and
   P05-A03 from its tested-version/operator/failure matrix. Preserve A01's exact
   source scope; keep P05 in progress until all three gates are satisfied.

A scoped custom operator establishes no full device backend, arbitrary model
support, autograd, training, ONNX execution or CUDA binary compatibility.

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
