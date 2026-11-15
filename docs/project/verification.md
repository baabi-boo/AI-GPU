# Verification strategy

Verification answers three separate questions: **does the calculation match its
contract, does the device execute it correctly, and does the complete system meet
its measured requirements?** A passing answer to one does not answer the others.
The [roadmap](roadmap.json) defines authoritative phase gates; the
[acceptance policy](acceptance.md) defines evidence and review requirements.

## Verification pyramid

Start with small, deterministic checks; expand to integration and real hardware
only after their prerequisites pass. Preserve a failing small reproducer when a
larger workload exposes a defect.

| Layer | What it proves | What it does not prove |
|---|---|---|
| Source and governance checks | Required files, references, configuration/catalog structure and project policy are present (`source_present`). | Successful GPU compilation, numerical correctness or hardware behavior. |
| CPU reference/oracle | Expected results for a declared arithmetic contract, shapes and seeds. | GPU execution or independent validation when reference and device model share the same bug. |
| SimX | Functional behavior and modeled execution for the recorded configuration (`simulated`). | Physical clock, power, external memory bandwidth or a working native RTL datapath. |
| Native processor RTL | Native arithmetic, scheduling and memory behavior exercised through RTL simulation (`rtl_verified`, scoped to tested units/configuration). | The host/AFU integration bypassed by `rtlsim`, or physical FPGA operation. |
| Full XRT AFU integration | Host transfers, command submission, execution and completion through the AFU; record whether the target is `xrtsim` or vendor `hw_emu`. | A physical board. `xrtsim` is not a substitute for a gate that explicitly requires `hw_emu`. |
| Physical FPGA | The actual programmed board and memory system run the recorded workloads (`fpga_measured`). | Production ASIC timing, power, yield or compatibility with untested boards. |
| Fabricated silicon | Laboratory results from actual silicon (`silicon_measured`). | General performance claims beyond the tested workload, hardware and conditions. |

Record **execution driver and arithmetic backend separately**. A run through
`rtlsim` with `VX_CFG_TCU_TYPE_DPI` invokes C arithmetic; it can exercise surrounding
RTL but cannot establish native tensor arithmetic correctness. The initial native
tensor contract targets the existing TFR path. Other arithmetic implementations
need separately declared semantics and coverage, not an assumption of equivalence.
See the [tensor design](../designs/tensor_core_wgmma_engine.md) and
[baseline audit](baseline.md).

## Existing catalog and coverage to extend

These files are starting points, **not a claim that every obligation below is
already implemented or has passed**. Add bounded cases to the existing catalog
rather than creating a second disconnected test runner. Freeze the supported
dtype/shape/layout matrix and expected failures before measuring a candidate.

| Area | Required coverage | Existing starting points |
|---|---|---|
| Tensor arithmetic | FP16/BF16 inputs with FP32 accumulation first; zeros and signed zeros, extrema, cancellation, rounding boundaries, subnormal and NaN/Inf behavior where supported; integer overflow/saturation and quantization scales when enabled. | [tensor](../../ci/testcases/tensor.yaml), [MX](../../ci/testcases/tensor_mx.yaml), [sparse](../../ci/testcases/tensor_sp/tensor_sp.yaml), [sparse MX](../../ci/testcases/tensor_sp/tensor_sp_mx.yaml). |
| Layout and concurrent execution | Legal tiles/strides, transpose and packing, tail handling or explicit rejection, sparse metadata, WGMMA synchronization, multiple warps/CTAs, backpressure, reset and no lost/duplicate completion. | [WGMMA](../../ci/testcases/tensor_wg.yaml), [core](../../ci/testcases/core.yaml), [unit tests](../../ci/testcases/unittest.yaml). |
| Runtime and software surfaces | Buffer ownership/lifetime, bounds, queues/events, launch/completion, error propagation, clean installation, API compatibility and explicit unsupported-operation errors. | [runtime](../../ci/testcases/sw/runtime.yaml), [kernel](../../ci/testcases/sw/kernel.yaml), [HIP](../../ci/testcases/sw/hip.yaml), [OpenCL](../../ci/testcases/sw/opencl.yaml). |
| Memory and host integration | DMA direction/size/alignment, boundary crossing, guards, visibility/fences, cache behavior, allocation failure and host/device address validity under contention. | [regression](../../ci/testcases/regression.yaml), [cache](../../ci/testcases/cache.yaml), [DXA](../../ci/testcases/dxa.yaml), [VM](../../ci/testcases/vm.yaml); [AFU contract](../designs/fpga_afu_shell.md). |
| AI operators and whole models | Independently checked operators, attention and fixed tiny-model outputs; exact weights or generator, license, seed and dimensions; traces proving device dispatch, with host work and transfers reported separately. | [tensor catalog](../../ci/testcases/tensor.yaml), [WGMMA attention cases](../../ci/testcases/tensor_wg.yaml); extend in [P03](phases/p03-operators.md), [P04](phases/p04-inference.md) and [P05](phases/p05-framework.md). |
| Faults, longevity and implementation cost | Malformed requests, resource exhaustion, timeouts/reset/recovery, isolation and soak tests; cycle regression, logic depth, area and achieved timing without hiding tradeoffs. | [stress](../../ci/testcases/stress.yaml), [VM](../../ci/testcases/vm.yaml), [performance](../../ci/testcases/perf.yaml), [logic](../../ci/testcases/logic_gate.yaml), [FPGA](../../ci/testcases/fpga_gate.yaml), [ASIC](../../ci/testcases/asic_gate.yaml), [synthesis](../../ci/testcases/synthesis.yaml). |

Existing attention kernels are useful building blocks, not proof of complete
model or framework support. Whole-model, Python/framework, physical-board soak,
training and multi-device workloads remain phase work. Unsupported shapes or
formats must be rejected or reported explicitly; silent CPU fallback cannot
satisfy an accelerator gate. Catalog entries for an ASIC flow do not establish
foundry-qualified sign-off.

## Numerical and timing contracts

Before running acceptance tests, version the arithmetic order, rounding,
accumulation, exceptional-value and overflow behavior; the input distribution;
and exact-match or error metrics with their thresholds. Use a mathematically
independent CPU implementation for application accuracy and a backend-specific
reference for bit-level behavior. The existing [FEDP model](../../sw/common/fedp.h)
is relevant to TFR semantics; it is not a universal oracle for every backend or
proof of NVIDIA numerical equivalence. Check reference implementations with small
hand-computable cases and deterministic boundary vectors before relying on them.

Distinguish numerical acceptance from **timing-model parity**. SimX is the RTL's
timing model. Timing-changing RTL work must include the corresponding SimX change
and applicable `model_parity` cases. The current
[catalog loader](../../ci/testcase.py) restricts `model_parity` and `perf_gate` to
RV32. Parity requires identical retired-instruction counts and cycle agreement
within the case's existing tolerance; the default is 5%. A passing numerical
comparison alone does not establish timing parity.

There is a deliberate exception in
[the WGMMA catalog](../../ci/testcases/tensor_wg.yaml): its small
`flash_attn_tcu_wg-rtlsim` case is RV64 and has no generic `model_parity` case.
In RV32, `expf` uses double-precision soft-float steps whose instruction count
depends on numerical values. Do not force this workload into an invalid
instruction-count comparison or quietly waive parity for unrelated kernels.
Record parity applicability per workload and retain separate numerical checks;
a broader timing claim needs a reviewed, suitable test.

For divergent numerical or pipeline results, follow the
[SimX-as-oracle debugging procedure](../debugging.md#simx-as-oracle-for-rtl-debug):
match architectures/configurations, emit matching event traces and localize the
first divergence. Do not treat correlated model/RTL agreement as sufficient
without the independent numerical reference.

## Running bounded checks

Follow the [developer guide](developer-guide.md) and [AGENTS.md](../../AGENTS.md)
before expensive execution. Use separate configured build trees per incompatible
ISA/profile, pin tools and dependencies, reconfigure after relevant changes and
rebuild the application with the same `CONFIGS` as its backend. `blackbox.sh`
invokes the application's runtime/build/run targets with those flags; native
regression rules track resolved flags in `config.stamp` and rebuild affected
outputs. This does not regenerate stale configuration headers or prove that a
custom/prebuilt application uses matching effective settings.

Lightweight project checks run from the source root and require no GPU toolchain:

```sh
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
python3 ci/testcase.py lint
python3 ci/change_impact.py lint-policy
```

After baseline configuration and resource approval, these are illustrative
catalog slices, **not executed results or a complete acceptance suite**:

```sh
# Run from a configured build tree, not the source root.
./ci/regression.sh --test 'tensor and simx'
./ci/regression.sh --test 'tensor and rtlsim'
./ci/regression.sh --test 'tensor_wg and rtlsim'
./ci/regression.sh --test 'tensor and model_parity'
```

The current [runner source](../../ci/regression.sh.in) accepts `--test` followed
by a pytest marker expression, or `--all`; historical `--tensor`, `--regression`
and `--unittest` flags are not the current interface. Inspect selected case IDs,
XLEN and flags: a tensor slice may mix native and DPI backends, and RV64 attention
will not run in an RV32 tree. A collection with zero applicable cases, skipped
tests or expected failures does not pass a required gate.

The catalog marker for execution driver `xrt` is `xrtsim`. For explicit XRT
execution, [blackbox](../../ci/blackbox.sh) distinguishes
`--driver=xrt --target=xrtsim`, `--driver=xrt --target=hw_emu` and
`--driver=xrt --target=hw`. Use the platform's setup and matching artifacts for
the selected target. Processor `rtlsim` is fast iteration; it does not replace
the full AFU `hw_emu` proof required by `P01-A03`. Missing vendor tools, licenses
or platform access are blockers, not reasons to relabel a different run.

## Evidence, regression discipline and release

For each gate, retain the exact revision, configuration/backend, selected case
IDs, tool versions, commands, exit/results, raw logs, reference and threshold
versions, plus skipped/failed/not-run coverage. Physical reports additionally
identify the board/chip, bitstream, memory, achieved clock and measurement
conditions. Use the [evidence guidance](evidence/README.md); report unavailable
measurements explicitly rather than filling in estimates as observations.

Never hand-edit `ci/baselines/**`, loosen tolerances, drop difficult cases, add
`known_issue` labels to hide failures or regenerate goldens to make a gate green.
Intentional changes follow the inherited human-reviewed baseline process and
[review policy](../review/code-review-policy.md). Timing-affecting RTL changes
require Beacon-first analysis and appropriate synthesis confirmation, with a
resource budget; synthesis estimates are not measured silicon performance.

Close [P01](phases/p01-baseline.md) only with reproducible native and integration
evidence; use [P02](phases/p02-tensor.md) for the numerical contract and
[P06](phases/p06-performance.md) for performance acceptance. Physical milestones
are [P07](phases/p07-fpga.md) and [P08](phases/p08-reliability.md), including the
one-hour prototype and 24-hour release soak gates respectively. Consult the
[release policy](releases.md) before labeling an artifact ready for users.

**Setup limit:** this repository-preparation change supplies plans and governance
checks, not an executed GPU baseline. It does not run GPU workloads on SimX,
native RTL or XRT, synthesize/place-and-route the design, test a physical board,
or fabricate/measure silicon. Source/catalog checks must remain separate from
those future results in [project status](status.md).
