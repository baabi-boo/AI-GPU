# P05 eager PyTorch compatibility and qualification

The current source implements contract **`p05-torch-custom-ops-v1`** through
the optional `vortex_ai.torch_ops` module. The selected qualification environment
is **PyTorch 2.15.0+cpu on Linux x86_64, little-endian CPython 3.12.14 with the
GIL and main interpreter**. Actual host tests exercise this framework version
with scripted native owners. **Fresh installed SimX framework qualification is
pending; P05-A02 and P05-A03 remain unearned.** The
[canonical roadmap](roadmap.json) owns acceptance state.

The [operator contract](../designs/torch_custom_ops_v1.md) defines representation,
registration, ownership and error behavior. The
[package guide](../../python/README.md#optional-pytorch-installation) supplies
installation commands and an eager matmul/model example. This matrix does not
extend the historical [copying-binding acceptance](evidence/p05-python/acceptance-binding.json)
to a framework caller that has not yet completed installed qualification.

## Implementation and observed evidence

| Route or check | Current result | Scope and limit |
|---|---|---|
| Historical copying Python binding | Accepted P05-A01 at `e1420fd550f716df33a2556057b7086a03032cbe` | Original installed SimX FP16/BF16 packages and their 22-input source identity; those packages contain no Torch adapter |
| Current optional registration and tensor/owner behavior | Implemented; a retained run passed 43 actual-PyTorch host tests | [Host receipt](evidence/p05-torch/development/integrated-torch-host.json) uses scripted native responses, without native numerical execution |
| Current package/source closure | Host checks passed | [Independent package review](evidence/p05-torch/development/reviews/w03_a3.md) checks 23 current source inputs, lazy base import and stale-payload rejection; this does not replace a new bound installed run |
| Original-input, dispatch and interruption corrections | Host regression tests and scoped review retained | [Dispatch review](evidence/p05-torch/development/reviews/w03_a1.md) and [ownership review](evidence/p05-torch/development/reviews/w03_a2.md) preserve their original failures and corrections |
| Installed checker result independence | Corrected; host adversarial tests pass | [Checker review](evidence/p05-torch/development/reviews/w03_a4.md) verifies storage-range overlap rejection, with scripted native observations |
| Fresh native/Python/Torch FP16 matrix | Pending | Requires the dedicated installed workflow and independent result review |
| Fresh native/Python/Torch BF16 matrix | Pending | Same requirement in a separate fresh process, wheel, bundle and environment |
| Physical FPGA, vendor `hw_emu`, silicon and physical performance | Not established by this work | SimX execution, when obtained, will establish only its named simulation scope |

The [historical source-retention record](evidence/p05-torch/a01-retained-binding.json)
preserves exact old bytes for four package paths that this continuation changes.
It does not claim that the old run tested the new adapter or current package.

## Version, placement and operator matrix

| Boundary | Implemented contract | Qualification limit |
|---|---|---|
| Framework distribution | Exactly `torch==2.15.0+cpu`; no CUDA or HIP build | Other framework versions/builds are unsupported |
| Interpreter and platform | Adapter requires Linux x86_64, little-endian CPython 3.12 with the GIL; the selected installed target is exactly 3.12.14/main interpreter | Other patch versions have no installed qualification; other interpreter/platform families are unsupported |
| Dependencies | Eleven exact wheels in the [hash lock](../../ci/project/p05_torch_requirements.lock) and [manifest](../../ci/project/p05_torch_contract.json) | The core `vortex-ai` metadata still has no runtime dependencies; users install the optional closure explicitly |
| Package and native bundle | Current 23-input source-bound wheel, exact canonical bundle manifest and native artifacts | Each FP16/BF16 wheel accepts only its matching bundle; the old 22-input package cannot be reused as the framework implementation |
| Tensor placement | Ordinary exact `torch.Tensor` objects on CPU at input/output boundaries | CPU storage is not a CPU matmul fallback; no full framework device backend or CUDA binary compatibility is provided |
| Execution placement | Existing native `Session.submit` and `Session.model` owners on the selected SimX route | No new native arithmetic, hardware, kernel or numerical fixture is supplied by this adapter |
| Concurrency and lifetime | One live native SimX context; explicit operation close before reuse; borrowed session with process-local token | Concurrent/reentrant calls, fork reuse and portable/persistent tokens are unsupported |

The schemas are versioned and require all shown arguments for raw `torch.ops`
calls. `TorchSession.matmul` and `TorchSession.fixed_mlp` supply the default
poison `0x7fc0dead` and validate their Python scalar arguments before dispatch.

```text
vortex_ai::matmul_v1(Tensor a, Tensor b, int session_token, int poison) -> Tensor
vortex_ai::fixed_mlp_v1(str case_id, int session_token, int poison) -> Tensor
```

| Operator | Accepted input | Result and declared work |
|---|---|---|
| `matmul_v1` | Matching FP16 or BF16 A/B, matching the bundle format; only the three signatures below | Independent row-major CPU FP32 tensor of shape `(M,N)`; one native matmul submission |
| `fixed_mlp_v1` | One of the five frozen case families for the current bundle format | Independent CPU FP32 tensor `(16,4)` from the bias-free batch-16 `16 → 8 → 4` MLP; three native matmuls plus declared host work |

| `(M,N,K)` | A shape / element strides | B shape / element strides | Result shape |
|---|---|---|---|
| `(8,4,8)` | `(8,8)` / `(8,1)` | `(8,4)` / `(1,8)` | `(8,4)` |
| `(8,4,16)` | `(8,16)` / `(16,1)` | `(16,4)` / `(1,16)` | `(8,4)` |
| `(16,8,16)` | `(16,16)` / `(16,1)` | `(16,8)` / `(1,16)` | `(16,8)` |

Each signature is implemented in both FP16 and BF16, for six combinations.
Both operands must have rank two, storage offset zero and exactly their packed
backing extent. A is row major and B physically column major. A caller can
explicitly prepare B with `b_row_major.t().contiguous().t()`; the adapter does
not silently repair an unsupported layout. Input copying uses integer
reinterpretation and little-endian packing, preserving raw FP16/BF16 bits.
Returned FP32 bytes are copied into independent tensor storage after successful
native close.

The fixed families are `seeded_dense`, `negated_dense`, `zero`, `signed_basis`
and `split_boundary`, prefixed with `fp16-` or `bf16-`. The executor owns the
frozen model inputs and weights; callers cannot supply arbitrary models,
weights or shapes. ReLU, exact format conversion and output-row assembly remain
explicit host work under the unchanged
[P04 execution contract](../designs/mlp_execution_records_v1.md). Actual hidden
and bridge results feed subsequent native launches; expected arrays are only
comparison data.

## Unsupported inputs and execution contexts

| Request or condition | Implemented behavior / evidence boundary |
|---|---|
| Ordinary eager, `no_grad`, `inference_mode` with valid non-differentiable inputs | Supported contract; actual pinned-Torch host tests pass; installed SimX proof remains pending |
| Original `requires_grad=True` or a forward-AD tangent, including under `no_grad` or `inference_mode` | Rejected before native submission; original operands are checked before integer views can erase gradient metadata |
| Wrong shape/dtype/device/layout, mixed formats, storage padding/offsets, arbitrary strides, unresolved negative/conjugate views or tensor subclasses | Rejected; no implicit conversion, repacking or substitute result |
| Autocast, meta/FakeTensor, tested `vmap`, functionalization, forward differentiation, fullgraph compilation and TorchScript tracing | Unsupported; enumerated host probes reject before native entry |
| `torch.func.linearize`, FX symbolic tracing of the input-free model, scripted TorchScript execution, arbitrary dispatch overrides or graph breaks | Unqualified; these callers can evaluate ordinary eager work before a detectable transform or invoke the registered operator directly |
| Autograd/training, arbitrary models, broadcasting, sparse/quantized operations, zero-copy execution, CUDA binaries or multi-device execution | No supporting implementation/acceptance contract |

Unsupported does not mean every possible higher-level caller is universally
detectable before execution. In particular, the retained dispatch review shows
ordinary primal evaluation inside `linearize`, constant evaluation of the fixed
model in FX tracing, and registered-op invocation from a scripted graph. Such
contexts may submit and finish native work. A later transform exception is not
evidence of zero submissions; retained native owners and execution records are
authoritative.

## Errors, shutdown and recovery

A successful operator return means native work completed, explicit close
succeeded, and output bytes became available. Output tensors keep their own
CPU storage after the adapter detaches and the caller closes the native session.
`TorchSession.close()` detaches the adapter only; it refuses outstanding native
owners and does not close the borrowed `Session`.

On failure or interruption, keep both objects and inspect
`session.pending_operations()`. Submission can finish before Python assigns a
return value, so that inventory is authoritative even when `last_operation` or
an exception's diagnostic attributes are absent. Explicitly retry the retained
operation's bounded wait/advance/close methods and inspect separate validation,
execution, cleanup and model-status channels. No error publishes reference,
poison or partial output as a successful result. Cleanup failure can retain the
binding's process recovery restriction.

The default retry deadline is 30 seconds, configurable up to 300 seconds. It is
checked between bounded native calls; model advancement may perform multiple
waits. It is not a strict whole-call deadline or cancellation facility.
Destructors can drain indefinitely, so dropping the owner is not bounded
cleanup.

An incompletely initialized `Session` is rejected at adapter attachment. Close
the native owner retained by a failed `Session.open` before opening another
session. If adapter construction registered successfully but an interruption
prevented assignment, retry `TorchSession(session)`. The duplicate-attachment
`BindingError.adapter` identifies the registered adapter even if the native
session has pending work or is already closed. Complete any pending operation
before detaching the adapter. This recovers the registered owner without
reopening a closed session. The token is a process-local identity, not a
security credential or caller-created qualification claim.

## Fresh installed qualification required

The [dedicated workflow](../../.github/workflows/p05-torch.yml) runs separate
FP16 and BF16 jobs. Each job must finish the fresh native P04 comparison and
current plain-Python P05 regression before the third framework stage consumes
their exact live packets. The framework runner builds no new native comparison
and never counts a copied packet as another execution.

The third stage installs the newly bound wheel and hash-locked CPU framework
into a fresh external venv. It runs the copied installed checker through
`vortex_ai.launch` under `-I -B`, recording actual `torch.ops` operand/result
bytes, native owner traces, closure, source/package/tool identities and original
raw logs. Returned tensors must match actual native results and independent
comparisons; all returned storage ranges must be independent of inputs and
earlier live results. Original installed-path validation remains distinct from
any later relocated archive replay.

The planned per-format workload is six standalone matmul calls and ten fixed
model calls, each selected case repeated with poisons `0x7fc0dead` and
`0xdeadbeef`: **36 framework-route native launches**. Both formats would total
72 framework launches and 360 event/profile pairs. Including fresh native and
plain-Python comparisons, the complete workflow would contain **216 distinct
launches and 1,020 event/profile pairs**. These are workload requirements, not
observed completed framework runs at this publication stage.

Acceptance requires original successful packets, independent numerical,
dispatch and provenance review, and the source-scoped decision required by
[the evidence policy](acceptance.md). Host mocks, a dependency installation,
source presence or passing project-governance checks cannot supply that proof.
