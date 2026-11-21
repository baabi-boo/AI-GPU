# PyTorch custom operators v1

Contract ID: `p05-torch-custom-ops-v1`. This is the bounded P05 framework
interface above [the copying binding](python_binding_v1.md). Qualification is
recorded separately; source presence never establishes execution or acceptance.

## Supported environment and registration

The version selected for this contract is Linux x86_64, little-endian CPython
3.12 with the GIL, and the CPU distribution **PyTorch 2.15.0+cpu**. Qualification
pins CPython 3.12.14 and the complete framework wheel closure. The base package
continues to have no runtime dependencies. `import vortex_ai` does not import
Torch; `import vortex_ai.torch_ops` explicitly opts into this interface.

The registered schemas are:

```text
vortex_ai::matmul_v1(Tensor a, Tensor b, int session_token, int poison) -> Tensor
vortex_ai::fixed_mlp_v1(str case_id, int session_token, int poison) -> Tensor
```

`TorchSession` borrows an already opened qualified `vortex_ai.Session`. Its
process-local token identifies that existing owner. It supplies neither a device
address nor a caller-created qualification claim. The registry retains the owner
until explicit successful adapter close. Tokens are not portable or persistent.
Closing the adapter detaches it; the caller still explicitly closes the native
session. Native one-context, one-outstanding-matmul and post-fork restrictions
remain in force. Concurrent/reentrant adapter calls are rejected.

Only eager inference is supported. Ordinary eager, `no_grad` and
`inference_mode` calls with non-differentiable inputs may execute. Tensor
subclasses, meta/FakeTensor, TorchScript tracing, fullgraph compilation,
functionalization, vectorization, forward-mode AD and autocast are not supported.
The registration explicitly rejects the relevant dispatch keys; original inputs
are also checked before reinterpretation. No fake kernel or backward formula
pretends to execute the native operation. User-supplied dispatch overrides and
arbitrary graph-break behavior are outside this version's qualification.

The guards cover the enumerated dispatch paths and original tensor
preconditions. Higher-level APIs can evaluate an ordinary eager call before
entering a detectable transform. In the pinned version, `torch.func.linearize`
first evaluates ordinary primal tensors; FX symbolic tracing can evaluate the
input-free fixed model as a constant; a scripted TorchScript graph can invoke
a registered operator. These contexts are unqualified and may submit and finish
native work. A later transform exception does not prove that no work ran;
retained owners and execution records remain authoritative.

## Representation and placement

A and B must be ordinary CPU `torch.Tensor` objects with rank two and the same
`torch.float16` or `torch.bfloat16` dtype, matching the qualified bundle format.
They must have storage offset zero, exact packed strides and accessible storage.
No gradient request or forward-AD tangent is accepted, including a tensor with
`requires_grad=True` supplied within `torch.no_grad()`. Unresolved negative and
conjugate views are rejected before any copy.

| Property | A | B | Result |
|---|---|---|---|
| Shape | `(M,K)` | `(K,N)` | `(M,N)` |
| Element strides | `(K,1)` | `(1,K)` | `(N,1)` |
| Physical layout | Row major | Column major | Row major |
| Element representation | Little-endian FP16/BF16 bits | Same input format | Little-endian FP32 bits |
| Placement at framework boundary | CPU storage | CPU storage | Newly owned CPU storage |

The only `(M,N,K)` values are `(8,4,8)`, `(8,4,16)` and `(16,8,16)`.
Broadcasts, padding, arbitrary strides, sparse/quantized tensors, mixed formats,
CUDA tensors and implicit conversion are rejected. B may be prepared explicitly
by the caller with `b_row_major.t().contiguous().t()`; this caller-requested copy
is separate from adapter execution. The adapter's own `b.t()` only exposes its
already packed physical column order and performs no reorder.

Integer reinterpretation and explicit little-endian packing preserve each input
bit. No Python float or NumPy conversion is used. The native binding then copies
those bytes into its owned buffers before submission returns. A CPU tensor is
host-side storage at this boundary; matrix arithmetic executes through
`Session.submit` on the qualified SimX bundle. There is no CPU matmul fallback.

After successful completion and explicit native close, the adapter obtains
`output_bytes()`, copies them into an independent CPU FP32 tensor and returns its
row-major view. No output aliases native memory, an input, another result or a
shared cached buffer. This contract makes no zero-copy or physical-performance
claim. Exact signed zero, subnormal and nonfinite bit behavior is preserved.

## Fixed model

`fixed_mlp_v1` accepts one of the ten compiled P04 case IDs and executes it through
`Session.model`. It has no tensor input because the fixed qualification executor
owns its frozen inputs, weights and comparisons. The result has shape `(16,4)`.
It does not load arbitrary weights or run an arbitrary user model.

The native owner performs three matmuls per case. ReLU, exact format conversion
and output-row assembly remain declared host work. The actual hidden result is
checked and feeds the bridge; the bridge's actual bytes feed the output launches.
Expected arrays are comparison data and never substitute for actual execution.
The [P04 record contract](mlp_execution_records_v1.md) remains unchanged.

## Completion, errors and recovery

A framework call either returns a successful independent tensor or raises while
preserving ownership. Successful wait alone is insufficient: matmul must finish
explicit close before another call can begin. A model must report terminal
success, finish close, and retain successful model status before output is read.
Validation, primary execution, cleanup and model mismatch outcomes stay distinct.
No error returns a poison, reference or partial tensor as a successful result.

The adapter uses a configurable aggregate retry deadline, checked between native
calls, and bounded individual waits. This is not a strict whole-call time limit:
model advance can contain multiple native waits. Timeout is not cancellation.
Native destructors can drain indefinitely, so dropping references is not a
bounded cleanup operation.

On timeout or interruption, retain the adapter and native session. Query
`pending_operations()` and explicitly retry the retained owners' bounded wait,
advance and close operations. Submission can complete before Python assigns its
return value; pending owners are the authoritative recovery inventory.
`last_operation` is diagnostic access to the actual most recently retained owner,
not an alternative to checking pending work. Adapter close rejects pending work;
cleanup failure retains the binding's process recovery restriction.

Attachment rejects a session whose opening or identity validation did not
finish. Close that retained native owner before opening a new session. If an
interruption occurs after an adapter registers but before its constructor result
is assigned, retry `TorchSession(session)`: the duplicate-attachment
`BindingError.adapter` identifies the existing adapter for recovery and detach,
including when the native session already closed or still owns pending work.
Duplicate lookup precedes new-attachment readiness validation. A new adapter
still requires a fully initialized open session without pending work.

Representation/type errors fail before native submission. Native/bundle/process,
state, ownership, cleanup and numerical failures preserve the binding error and
available owner/status details. The schema's scalar argument conversion follows
the pinned PyTorch dispatcher; convenience calls additionally validate their
Python arguments. A session token is an identity, not a security credential.

## Qualification contract

For each format, run the three frozen P02 matmul selections and five P04 model
families twice with output poisons `0x7fc0dead` and `0xdeadbeef`. Compare actual
returned framework bits with the unchanged fixtures and a fresh independent
native executable. Retain actual operand bytes/strides, dispatch arguments,
launches, event/profile results, intermediate/final model observations, explicit
host work and restored resources. The framework must really invoke `torch.ops`;
plain binding execution alone does not qualify this caller.

Each format has six standalone launches and ten three-launch model runs: 36
framework-route native launches. Across both formats this is 72 launches and 360
event/profile pairs. A complete workflow also performs 72 native-reference and
72 plain-Python regression launches: 216 distinct launches and 1,020 pairs.
Copied packets add no executions. These are planned counts until observed.

Build a new source-bound bundle, sdist and wheel after the adapter enters the
binding source inventory. Install in an isolated external environment with the
hash-locked framework closure. Preserve original raw packets, failed attempts,
version/ELF/package/source identities and independent reviews. Keep actual
installed checks separate from relocated offline data replay. Acceptance of
P05-A02/A03 is a recorded independent decision, not a runner side effect.

## Sources

PyTorch's [2.15 library API](https://docs.pytorch.org/docs/2.15/library.html)
documents schemas, explicit dispatch registration and custom-op aliasing.
The chosen dispatcher policy also follows actual pinned-version probes retained
in the development evidence. This contract establishes no full framework device
backend, autograd/training, ONNX execution, CUDA binary compatibility, processor
RTL qualification, vendor emulation, physical FPGA result or fabricated silicon.
