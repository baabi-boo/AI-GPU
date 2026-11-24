# P05 — Python and framework integration

**Accountable role:** Framework integration lead. Assign an owner before work.
Use [roadmap.json](../roadmap.json) for live status, dependencies and exit criteria.
The accepted deliverable is a thin binding and a scoped PyTorch custom-op bridge.
P05 is **complete for its bounded inference scope**: the
[retained copying-binding result](../evidence/p06-serial-workspace/a01-retained-binding.json)
supports A01, and the [A02 execution](../evidence/p05-torch-replay/acceptance-torch.json)
and [A03 compatibility](../evidence/p05-torch-replay/acceptance-compatibility.json)
records accept PyTorch 2.15.0+cpu / CPython 3.12.14 / Linux x86_64 / RV64 SimX at
`c6fb039e706e812b6b3f4d2a5db1828076fe50df`. See the
[matrix](../p05-torch-compatibility.md), [audit](../p05-torch-replay-audit.md)
and [inert replay handoff](../p05-torch-replay-handoff.md).
The ordered packages below preserve the qualification obligations for any
extension; this result does not establish a complete framework device backend.

## Goal and boundaries

Make the proven native runtime and tiny-model path usable from Python without
changing their numerical contract or hiding placement. Register only declared
PyTorch custom operators. Inference support does not imply autograd, optimizer,
training, arbitrary CUDA application or NVIDIA-driver compatibility.

Full device-backend dispatch, ONNX import/execution and replacement HIP tooling
need separate decisions and qualification; they are not prerequisites here.
See the boundary definitions in [software](../software.md).

## Entry conditions

- P04 is accepted with a fixed model fixture and native reference outputs.
- Public operator signatures, supported tensor representations, transfer and
  synchronization semantics, error handling and resource ownership are versioned.
- Select and record exact Python/framework versions and packaging dependencies.
- Keep native-runtime execution available as the comparison path, independent of
  the new binding; the CPU reference is validation machinery, not acceleration.

## Ordered work packages

1. **Specify the binding contract.** Define dtype, shape, strides, alignment,
   accessible extent, mutability and ownership. Host pointers are not device
   addresses. Reject unsupported layouts or require explicit documented copies.
2. **Bind the native API.** Expose allocation, copies, supported operators and
   completion/error handling through the accepted runtime. Keep objects alive
   until asynchronous work finishes and clean up partially failed operations.
3. **Test Python independently.** Compare supported calls with native outputs;
   exercise invalid types/shapes/strides, size overflow, allocation failure,
   premature release and repeated execution. Verify actionable exception mapping.
4. **Add scoped framework operators.** Register the accepted signatures, run the
   fixed model and trace framework-to-native dispatch. Unsupported differentiation
   must fail explicitly; do not present an inference-only bridge as training.
5. **Package and document.** Prove clean-environment installation and reproduction;
   publish tested versions, operator coverage, explicit transfer/sync costs and
   limitations. Do not advertise zero-copy behavior without corresponding proof.

## Deliverables and acceptance

Deliver the binding API/package, native comparison tests, framework registration
and integration tests, reproducible install metadata, compatibility matrix and
evidence bundle. Their existence and correctness must be established in this
phase; repository planning does not implement them.

| Gate | Required proof | Evidence level |
|---|---|---|
| `P05-A01` | Supported representations, lifetimes and errors pass binding tests; installation succeeds in a clean environment | `simulated` |
| `P05-A02` | The supported PyTorch custom-op route reproduces the native tiny-model result with device-dispatch evidence and no silent CPU fallback | `simulated` |
| `P05-A03` | A versioned compatibility matrix names tested framework versions, operators, unsupported behavior and absence of CUDA compatibility claims | `source_present` |

Capture source/configuration/tool/package identities, installation commands,
test results, trace artifacts and hashes using [acceptance](../acceptance.md).
Explicitly permitted host operations remain listed and separately measured;
they cannot satisfy accelerator acceptance for a declared device operator.

## Stop conditions and handoff

Block acceptance for numerical drift, hidden fallback, unsupported gradients
presented as supported, lifetime leaks, missing dependency provenance or a
clean-install failure. Missing hardware results remain outside this phase's scope.

Hand the versioned package, support matrix and reproducible model invocation to
[P08](p08-reliability.md), whose other dependency is physical FPGA acceptance in
P07. Training/autograd and multi-device work remain separately gated by P09.
