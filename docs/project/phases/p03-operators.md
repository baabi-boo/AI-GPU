# P03 — AI operator library

**Goal:** provide reusable native AI operators over the existing tensor API and
runtime, without requiring a replacement HIP compiler. **P03 is in progress.**
P03-T01 is complete with [source-level A01 acceptance](../evidence/p03-operators/acceptance.json)
and an implemented [input/argument contract](../../designs/ai_operator_contract_v1.md),
[manifest](../../../ci/project/p03_operator_manifest.json) and checked host planner.
P03-T02 now implements the matching device reader, managed wrapper, qualified
execution runner and common-runtime lifecycle fixes. A02/A03 execution and
independent acceptance remain pending at this checkpoint. The
[handoff](../p03-operators-handoff.md) separates implemented behavior, host/target
compilation checks and the remaining formal run. Live state and canonical gates
are in [roadmap.json](../roadmap.json); the accountable role is Kernel and runtime lead.

## Entry and boundaries

- P02 must supply accepted numerical contracts, supported configurations and
  reproducible native verification evidence.
- Reuse [vx_tensor.h](../../../sw/kernel/include/vx_tensor.h),
  [vortex2.h](../../../sw/runtime/include/vortex2.h),
  [tensor GEMM](../../../tests/regression/sgemm_tcu_wg/) and
  [tensor attention](../../../tests/regression/flash_attn_tcu_wg/).
- Follow the [software plan](../software.md). A native library is not a complete
  model executor, PyTorch device backend, autograd engine or CUDA implementation.
- Unsupported accelerated work fails explicitly by default. Any permitted host
  operation or opt-in fallback is visible and excluded from acceleration claims.

## Ordered work packages

1. Freeze a versioned operator manifest covering matmul/GEMV, reductions,
   softmax, normalization, activations, layout/casts and attention. Choose the
   exact initial variants needed by the intended tiny model; mark unsupported
   signatures explicitly instead of implying unrestricted coverage.
2. Specify each signature's dtype, accumulator/output type, rank, dimensions,
   strides, layout, alignment, aliasing, padding, empty-input semantics and
   numerical contract. Define size-overflow and out-of-range rejection behavior.
3. Define a small host interface over the existing runtime. Query device
   capabilities, validate memory/local-memory requirements and use explicit-width
   argument layouts. Test RV32/RV64 packing; host pointers are not device addresses.
4. Extract reusable launch wrappers and kernels from inherited examples without
   weakening their regression checks. Preserve software/hardware/simulator
   isolation and the installed runtime ABI; shared internal definitions belong
   in `sw/common/`, not cross-layer includes.
5. Specify ownership and completion: allocation, module/kernel handles, queues,
   events, host/device copies, waits and cleanup after partial failure. Keep
   resources alive until asynchronous operations have actually completed.
6. Add independent CPU-reference checks and boundary/invalid-input tests for
   every advertised signature. Trace actual Vortex submissions in the named
   simulation/native-RTL backend; the CPU oracle must not replace device work.
7. Exercise repeated allocation/free, insufficient memory, transfer errors,
   malformed arguments and asynchronous failures. Publish actionable errors,
   explicit synchronization and a minimal native caller example.

## Deliverables and acceptance

| Gate | Required deliverable and proof | Evidence level |
|---|---|---|
| `P03-A01` | Versioned operator manifest, interface/ABI review and rejection tests covering declared dtype/shape/layout ranges | `source_present` |
| `P03-A02` | Deterministic and edge-case CPU-reference comparisons for every supported operator, with SimX/native-RTL dispatch traces | `rtl_verified` |
| `P03-A03` | Host integration tests proving buffer bounds, queue/event lifetimes, transfer-error handling and repeated resource cleanup | `simulated` |

Retain exact revision/configuration, operator signature, reference and numerical
contract versions, inputs/seeds, launch/transfer records, raw results and resource
accounting. Apply the [acceptance](../acceptance.md) and
[verification](../verification.md) policies. CPU time, copies and explicit host
work remain separate from any accelerator performance report.

## Stop conditions and handoff

Block acceptance for a numerical mismatch, undeclared fallback, unsafe size
arithmetic, ABI ambiguity, premature free, leak or unsupported-input success.
Do not rewrite installed interfaces without independent contract review or
broaden the support matrix before its tests pass.

Hand P04 the versioned operator/support manifest, native caller, build recipe,
error/lifetime contract and evidence references. Update [status](../status.md)
and [backlog](../backlog.md). After P03-A02/A03 are accepted, the P04 handoff
selects a fixed, redistributable tiny model composed from the accepted operators.
The current next action is P03-T02 qualification: freeze the reviewed source,
run the full managed SimX/native-RTL matrix and actual lifecycle tests, retain
their results, and independently review A02/A03 acceptance. Source presence and
host stub tests do not close those gates.
