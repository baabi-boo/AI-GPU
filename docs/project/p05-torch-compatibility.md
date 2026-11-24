# P05 eager PyTorch compatibility and qualification

Contract **`p05-torch-custom-ops-v1`** is implemented by the optional
`vortex_ai.torch_ops` module. **Installed FP16 and BF16 execution passed** at
`c6fb039e706e812b6b3f4d2a5db1828076fe50df`,
[run 45349805332, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45349805332).
The exact tested environment is **PyTorch 2.15.0+cpu, little-endian CPython
3.12.14 with the GIL and main interpreter, Linux x86_64, and RV64 SimX**.
The [primary intake](evidence/p05-torch-replay/fresh-seam-intake.json) pins the
originals independently. The source-scoped
[P05-A02 simulation decision](evidence/p05-torch-replay/acceptance-torch.json)
and [P05-A03 compatibility decision](evidence/p05-torch-replay/acceptance-compatibility.json)
accept this bounded matrix after independent review. The
[canonical roadmap](roadmap.json) marks P05 complete for that scope.

The [operator contract](../designs/torch_custom_ops_v1.md) defines representation,
registration, ownership and error behavior. The
[package guide](../../python/README.md#optional-pytorch-installation) supplies
installation commands and an eager matmul/model example. The
[replay evidence index](evidence/p05-torch-replay/README.md) and
[operator handoff](p05-torch-replay-handoff.md) distinguish recorded execution,
later inert review and the separate acceptance decision. The historical
[copying-binding acceptance](evidence/p05-python/acceptance-binding.json)
remains a separate P05-A01 result.

## Implementation and observed evidence

The two c6 rows below are the selected tested-execution matrix. Historical c0
originals corroborate their own source revision and are not pooled with c6.

| Route or check | Observed result | Scope and limit |
|---|---|---|
| Historical copying Python binding | Accepted P05-A01 at `e1420fd550f716df33a2556057b7086a03032cbe` | Original installed SimX FP16/BF16 packages and their 22-input source identity; those packages contain no Torch adapter |
| Installed native/Python/Torch FP16 at `c6fb039e706e812b6b3f4d2a5db1828076fe50df` | Passed in run 45349805332; original digest matched; complete retained replay passed | 16 framework calls, 36 framework-route launches and 108 distinct recorded launches; separate native and plain-Python comparisons; copies add zero launches |
| Installed native/Python/Torch BF16 at `c6fb039e706e812b6b3f4d2a5db1828076fe50df` | Passed in the separate format job of run 45349805332; original digest matched; complete retained replay passed | Same bounded population as FP16, in its own process, wheel, bundle and environment; one format does not replace the other |
| Historical FP16/BF16 execution at `c0b44ce64665fe11895f869eea8c38c9b820d6f7` | Passed in run 45244780331; both original digests and retained consistency reviewed | [Separate intake](evidence/p05-torch-replay/intake.json); 108 distinct recorded launches per format at that revision, not additional coverage of c6 |
| Actual-PyTorch host failure and ownership checks in each c0/c6 original | 45 unique scripted host definitions and nine compiled host scenarios passed; zero scripted failures, errors or skips | Independently reconciled source identities, raw logs and child results; host arithmetic is synthetic or fixture supplied; complete internal host assertions cannot be reconstructed from retained data |
| Historical adapter development tests | A retained development run passed 43 actual-PyTorch host tests | [Historical host receipt](evidence/p05-torch/development/integrated-torch-host.json); this earlier selection is not the newer 45-definition evidence and is not added to it |
| Package/source closure | Host checks and scoped review retained; selected installed executions now exist | [Package review](evidence/p05-torch/development/reviews/w03_a3.md) checks 23 source inputs, lazy base import and stale-payload rejection; original installed evidence supplies the separate execution scope |
| Original-input, dispatch and interruption corrections | Host regressions and scoped review retained | [Dispatch review](evidence/p05-torch/development/reviews/w03_a1.md) and [ownership review](evidence/p05-torch/development/reviews/w03_a2.md) preserve their original failures and corrections |
| Installed checker result independence | Corrected; host adversarial tests passed | [Checker review](evidence/p05-torch/development/reviews/w03_a4.md) verifies storage-range overlap rejection; installed observations separately record actual result bytes |
| Physical FPGA, vendor `hw_emu`, silicon and physical performance | Not established by this work | The recorded accelerator work establishes only its named SimX simulation scope |

The [historical source-retention record](evidence/p05-torch/a01-retained-binding.json)
preserves exact old bytes for four package paths changed by the framework
continuation. It does not claim that the old copying-binding run tested the
adapter. The 45 scripted definitions and nine compiled scenarios recur across
formats and revisions; repetitions are not additional unique tests or native
launches. Independent host review supports the enumerated failure modes while
the public replay correctly retains `host_fault_semantics_revalidated=false`.

## Version, placement and operator matrix

| Boundary | Implemented contract | Qualification limit |
|---|---|---|
| Framework distribution | Exactly `torch==2.15.0+cpu`; no CUDA or HIP build | Other framework versions/builds are unsupported |
| Interpreter and platform | Adapter requires Linux x86_64, little-endian CPython 3.12 with the GIL; recorded installed execution uses exactly 3.12.14/main interpreter | Other patch versions have no installed qualification; other interpreter/platform families are unsupported |
| Dependencies | Eleven exact wheels in the [hash lock](../../ci/project/p05_torch_requirements.lock) and [manifest](../../ci/project/p05_torch_contract.json) | The core `vortex-ai` metadata still has no runtime dependencies; users install the optional closure explicitly |
| Package and native bundle | Current 23-input source-bound wheel, exact canonical bundle manifest and native artifacts | Each FP16/BF16 wheel accepts only its matching bundle; the old 22-input package cannot be reused as the framework implementation |
| Tensor placement | Ordinary exact `torch.Tensor` objects on CPU at input/output boundaries | CPU storage is not a CPU matmul fallback; no full framework device backend or CUDA binary compatibility is provided |
| Execution placement | Existing native `Session.submit` and `Session.model` owners on the recorded RV64 SimX route | No new native arithmetic, hardware, kernel or numerical fixture is supplied by this adapter |
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
| Ordinary eager, `no_grad`, `inference_mode` with valid non-differentiable inputs | Supported contract; recorded eager SimX execution passed at the named scope; `no_grad`/`inference_mode` context coverage comes from pinned-Torch host tests |
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

## Recorded installed execution and replay boundary

The [dedicated workflow](../../.github/workflows/p05-torch.yml) completed separate
FP16 and BF16 jobs in the selected c6 run. Each job finished its fresh native
P04 comparison and plain-Python P05 regression before the framework stage
consumed their exact live packets. The framework runner built no replacement
native comparison and counted no copied packet as another execution.

The framework stage installed the newly bound wheel and hash-locked CPU
framework into a fresh external venv. It ran the copied installed checker
through `vortex_ai.launch` under `-I -B`, recording actual `torch.ops`
operand/result bytes, native owner traces, closure, source/package/tool
identities and raw logs. Returned tensors reconciled with actual native results
and independent comparisons. The result storage was independent of inputs and
earlier live results. Original installed-path validation remains distinct from
later relocated archive replay.

The observed per-format workload was six standalone matmul calls and ten fixed
model calls, with each selected case repeated using poisons `0x7fc0dead` and
`0xdeadbeef`: **16 framework calls and 36 framework-route native launches**.
Each format also recorded 36 native-comparison and 36 plain-Python launches,
for **108 distinct launches per format** and **zero launches added by copies**.
Both c6 formats together record 32 framework calls, 72 framework-route launches,
360 framework event/profile pairs and 216 distinct launches. These counts name
recorded c6 execution; replay performs none of those launches. The historical
c0 pair has its own separate population.

The [inert replay contract](../designs/torch_archive_replay_v1.md) reconciles
retained raw numerical results, actual operand/intermediate/result lineage,
dispatch, explicit close, resource restoration and package/source identities.
It reads all 663 members of each original without importing, executing or
extracting retained code or opening recorded producer paths. Its successful
result still states `native_execution="not_run"`,
`retained_code_executed=false`, `acceptance_claimed=false` and
`phase_acceptance=false`.

First-party retained bytes and independently joined Git identities support the
reviewed source scope. Receipt-only source paths, third-party wheel/payload
bytes, interpreter/tool/seed bytes and some generated metadata cannot all be
freshly hashed from these originals. The host packets also omit intermediate
capture/status data needed to reconstruct every internal assertion. Retained
consistency and the bounded independent host/source reviews do not establish
complete absent-byte qualification, reproducible compilation or full host
semantic reconstruction.

The criterion-specific records make the acceptance decision under
[the evidence policy](acceptance.md); the successful reader still grants none.
The [validation summary](evidence/p05-torch-replay/validation-summary.json)
preserves source-specific successes, the local host-suite resource failure,
hosted skips and pending/cancelled CI distinctions. P01-A03 and P06-A02/A03
remain outside this result, including the unchanged 15 GiB resource guard and
single full zero-skip governance requirement for the separate P06 experiment.
