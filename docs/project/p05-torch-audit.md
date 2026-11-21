# P05 scoped PyTorch development audit

## Starting state and selected milestone

The audited `master` revision is `bdd3485243f820947df94f7962641d10f2169834`.
The repository's canonical roadmap records P00/P02/P03/P04 complete, P01 blocked
on vendor XRT, P05 in progress, and later phases not started. P05-A01 accepts the
copying Python binding at its historical implementation revision
`e1420fd550f716df33a2556057b7086a03032cbe`; no PyTorch version or custom operator
was qualified at the start of this continuation.

The latest base-revision hosted jobs were all successful:
[Project Governance](https://github.com/baabi-boo/AI-GPU/actions/runs/44872445151),
[P05 Installed Python](https://github.com/baabi-boo/AI-GPU/actions/runs/44872445146),
and [CI](https://github.com/baabi-boo/AI-GPU/actions/runs/44872445142).
Those successes are scoped to their selected jobs; they do not erase the
historical DSP area finding retained in the P04 executor audit.

The selected next milestone is the existing P05-T01 custom-operator obligation:
a thin, versioned eager PyTorch route over the accepted native owners. It adds
actual framework-callable matmul for the six bounded dtype/shape signatures and
access to the fixed tiny-model qualification executor. It is justified by the
accepted P04 dependency and the P05 handoff, without requiring a hardware or
arithmetic redesign. Full framework backends, new operators/shapes, autograd,
training and arbitrary-model loading remain different development contracts.

## Findings that determine the implementation

| Finding | Evidence and practical consequence |
|---|---|
| Native context ownership is deliberately narrow | The Python extension protects process-wide SimX state and requires explicit matmul close before reuse. A functional operator cannot discard temporary owners on timeout. |
| Fixed-model output is gated on explicit close and valid cleanup | `ModelOperation.output_bytes()` is the authoritative publication boundary. A diagnostic trace cannot substitute for successful output publication. |
| Tensor layout is a correctness boundary | Native B is physically column major. Ordinary `b.contiguous()` reorders it. Exact element strides `(1,K)` and physical-order copying preserve the accepted native ABI. |
| Integer views erase differentiation metadata | Actual PyTorch probes show `view(int16)` removes reverse-gradient state and forward tangents. Validate original operands before reinterpretation. |
| Registration choice affects hidden execution | A guarded high-level `custom_op` still executed counted dummy bodies under several unsupported transforms. Explicit dispatch registrations rejected all selected unsupported probes before execution. |
| Package source identities are strict | Adding a module changes `_bundle.SOURCE_PATHS` and bound package pins. Historical bound artifacts cannot be combined with changed adapter sources. Fresh matching builds are required. |
| Historical acceptance artifacts reference live paths | Preserve exact original bytes and a reviewed historical mapping when package paths change; never update old hashes to pretend the previous execution tested new code. |
| Existing P05 observations alone cannot qualify Torch | They capture native owners but not actual returned framework tensors. New records must bind framework operand/result bytes to the native traces and independent comparison route. |

Six distinct W01 reviewers examined ownership/API, numerics, packaging/CI,
actual dispatcher behavior, raw-bit transport, and acceptance/provenance. Their
reports and probe originals are retained under the development packet; no
requested worker count is treated as evidence of completed work.

## Actual framework probes before implementation

PyTorch `2.15.0+cpu` was available from the official CPU index for Linux x86_64
CPython 3.12. Its downloaded wheel SHA-256 is
`0955c7e3446326293f48af18fad67872fa31dee5a36a87690eb9e5be8b465be3`.
The complete dependency closure is frozen in
[the framework lock](../../ci/project/p05_torch_requirements.lock) and
[contract manifest](../../ci/project/p05_torch_contract.json).

The explicit Library registration probe ran 23 selected scenarios: three eager
calls reached their counted dummy body once each; twenty unsupported cases
raised with zero body calls. This tests dispatch behavior only. The original
alternative-registration failures and an initial output-formatter defect remain
retained with their actual scope.

The transport probe checked every 16-bit encoding for FP16/BF16 and both operand
orders: 262,144 words across four routes. It separately checked all six supported
signatures and 200,729 FP32 output patterns, including signed zero, subnormals,
infinities and NaNs. These tests used no NumPy and no accelerator arithmetic.
They establish copying behavior, not native numerical execution.

## Bounded implementation and qualification

The [operator contract](../designs/torch_custom_ops_v1.md) freezes representation,
registration, ownership, errors and exact version/platform support. The optional
module leaves ordinary `import vortex_ai` independent of PyTorch. The native
runtime, kernel, numerical fixtures, installed native ABI and hardware remain
unchanged.

A fresh qualification builds the unchanged native comparison, the new matching
copying package and its plain-Python regression, then installs that wheel and the
hash-locked framework into another isolated external environment. The third
stage invokes actual registered operators, observes returned tensor bits and
native dispatch, and retains strict request/record/raw-log reconciliation.
Host fault injection is separately labelled and cannot supply native arithmetic
acceptance. Offline archive replay reads retained data; it does not relax the
live installed-path checks or execute retained binaries.

Before the first framework qualification push, independent review found and
resolved these concrete defects:

| Defect | Correction and evidence |
|---|---|
| Inference mode hid a pre-existing forward tangent | Inspect the original tangent with inference mode temporarily disabled; retain ordinary inference-tensor support. W03 A1 supplied the regression and W04 A1 independently approved it. |
| Incomplete or interrupted adapter attachment could lose useful recovery access | Reject uninitialized native identities, expose the existing registered adapter on duplicate attachment, and perform duplicate lookup before new-owner readiness checks. W04 A6 independently approved the final adapter after 45 actual-Torch host tests. |
| The installed checker missed overlapping buffers with distinct start addresses | Compare full storage intervals and retain inputs across all calls. Both frozen formats reproduced the original false acceptance with scripted native owners; W04 A1 independently approved the correction. |
| Vendored setuptools metadata was mistaken for an installed distribution | Limit entrypoint and installer-rewrite rules to top-level distribution metadata. Nested payloads remain immutable. W03 A5 independently approved the fix; a fresh offline dependency install passed full before/after inventory checks. |
| The optional compiled-host test runner lost malformed output and accepted unrelated JSON | Preserve original stdout/stderr bytes before parsing and require the child's scope, scenario, format and success marker. Root reviewed the W04 A6 correction and its 15-test orchestration/CI recheck. |

The untouched local baseline ran 2,172 tests with one class-setup error when
unchanged configure exceeded its 15-second deadline; two tests in that class did
not run. An isolated retry also failed. A separate diagnostic completed in
16.324 seconds, explaining the local timeout without changing the gate or
converting the failed runs into passes. The original logs remain retained.

These reviews and host probes establish readiness for fresh qualification.
Installed SimX framework acceptance remains pending at this implementation
publication. The [development originals](evidence/p05-torch/development/README.md)
retain failed and corrected probes with their actual source identities.

The user authorized direct commits and pushes to `master`. Independent contract,
implementation and evidence reviews remain required; no waiver or additional
human approval is inferred. The 60 distinct workers run in ten six-worker waves,
with at most three workers beside the root integration owner. Publication checks
the remote head and preserves concurrent changes without force pushing.

## Retained limitations

P01-A03 still needs qualified vendor tools/platform and XRT `hw_emu`; it blocks
P01 closure and P07 acceptance. Processor-only RTL is not that result. The
inherited tensor DSP increase from 267 to 283 remains unresolved. This adapter
work changes no hardware or golden thresholds and cannot resolve that gate.
SimX qualification is not physical GPU performance, a board result or silicon.
Final observed test results, source identities and the next bounded action are
recorded in the evidence packet and current status after independent review.
