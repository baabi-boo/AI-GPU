# Benchmark protocol

**Status: P06-A01 accepts a frozen cold-context SimX baseline.**
The [acceptance](evidence/p06-baseline/acceptance.json) is limited to modeled
cycles/counters, checked logical accounting and retained host observations.
Physical throughput, latency, bandwidth, power and NVIDIA comparisons remain
unmeasured. A correct answer and a fast answer are separate obligations;
every speed claim needs both.
Apply the [acceptance policy](acceptance.md) and [P06 gates](phases/p06-performance.md).

## Accepted baseline scope

The original [run 44901052221, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44901052221)
at source `84b6ca0ca75fba248ba330642bbf8764db3d459c` ran three fixed matmul
shapes and the batch-16 `16 → 8 → 4` model in each of FP16/BF16. The
[contract](../designs/native_benchmark_v1.md) and
[manifest](../../ci/project/p06_benchmark_contract.json) freeze eight workloads,
each with one warm-up and five measured fresh processes: 48 processes and
72 launches, including 40 measured processes and 60 measured launches.
Each invocation starts a new device context; this does not establish warm-cache
or resident-workspace performance. The 45 counter rows retain 33 available
values and 12 explicit unavailable values.

The [qualification packet](evidence/p06-baseline/README.md) preserves original
archives, independent numerical/source/counter review and measured-only descriptive
statistics. The new [analyzer](../../ci/project/p06_analyze.py) follows the
[analysis contract](../designs/native_baseline_analysis_v1.md), replaying both
originals before deriving full-matrix diagnostics. Serial lifecycle and advance
timing totals must fit their enclosing intervals; the original measurements and
1,000 ns process allowance remain unchanged. Native event profiles overlap host
waits and are excluded from the serial sums.

The [qualification audit](p06-qualification-audit.md) records a reproduced
approximately 100 ms supervisor exit-observation delay. Original host durations
remain intact; an estimated delay must not be subtracted to infer host speedup.
Whole-context modeled counts include every model launch and cannot establish
per-kernel latency, a causal bottleneck or physical bandwidth.

Next, freeze one small-workload amortization experiment with matched before/after
criteria. Resolve native multiple-live-operation ownership before reuse or
concurrency claims, and define any warm-context boundary separately from the
accepted cold baseline. P06 and P06-T01 remain `in_progress`; A02/A03 remain open.

## Small workloads first

| Tier | Workload and purpose | Starting point; required extension |
|---|---|---|
| B1 | GEMM: matrix × matrix; compute/reuse behavior | `tests/regression/sgemm_tcu` and `sgemm_tcu_wg`; freeze supported shapes/layouts |
| B2 | GEMV: matrix × vector; low-reuse memory behavior | `tests/regression/sgemv`; distinguish GEMV from a batched GEMM |
| B3 | Softmax and attention: reductions, synchronization, transfers | `tests/regression/softmax`, `flash_attn`; declare masks, sequence length and precision |
| B4 | Tiny-model inference: useful end-to-end work | P04's fixed redistributable model; layer checks, dispatch traces and final-output quality |

These are broader benchmark candidates; P06 timing acceptance covers only the
exact suite above.
Use bounded deterministic cases before scaling; keep nominal, edge and unsupported
cases in the numerical suite even when the timing subset uses representative inputs.
No large model downloads or expensive sweeps are authorized by this document.

## Freeze the experiment before running

- Pin the exact source revision, submodules, tool versions, application binary,
  generated configuration and compile options. Hash the configuration and fixtures.
- Record shapes, batch/sequence sizes, layout/strides, input/output/accumulator
  formats, quantization/scales, sparsity pattern, seeds and dataset/model licenses.
- Pin the reference implementation, numerical contract, tolerances and model-quality
  metric. Changes require review before evaluation, not after an unfavorable result.
- Name execution driver, arithmetic implementation and simulation mode. Native TFR
  and software-delegating DPI are different experiments; do not combine their results.
- For physical runs, identify board/device, firmware/bitstream, driver, accessible
  memory banks/capacity, achieved clock, power settings and thermal conditions.
- Declare the timed boundary, cache state, allowed host work, warm-up/repeat counts,
  measurement instruments, resource budget and any target thresholds in advance.

Use [benchmark.example.json](evidence/benchmark.example.json) as a specification
starting point. Its unresolved fields must be supplied before execution. It is
**not an acceptance report** and must never be attached as passing phase evidence.

## Numerical proof is a prerequisite

Compare outputs with the frozen oracle using per-format/per-backend error rules;
include exceptional values and accumulation behavior where supported. Record max
errors and model-quality results, not only a boolean. A fast incorrect run fails.
Trace device dispatch so CPU reference calculation, permitted host operators and
unsupported-operation failures are visible. Silent CPU fallback is disqualifying.
Recheck correctness after every optimization; inherited goldens and parity tolerances
remain protected. A speedup cannot compensate for an unrelated regression.

## Timing and raw samples

- Set warm-up and measured repetition counts before execution. Exclude only the
  declared warm-up; retain all measured samples, failures and exclusion explanations.
- Define cold/warm caches, buffer reuse, allocation/JIT inclusion and synchronization.
  Wait for actual completion; host enqueue time alone is not execution latency.
- Report kernel-only time, host-to-device/device-to-host transfer time and synchronized
  end-to-end time separately. Include launch/host work as declared; overlapping
  intervals must not be naively summed. State whether validation is outside timing.
- Retain timestamped raw samples and counters; report sample count, median, range and
  variability. Declare percentile/confidence methods and avoid unsupported tail claims.
- Keep simulator host wall time separate from modeled device cycles. Report physical
  time only from identified physical hardware; clock-based projections remain estimates.
- Power/energy needs a measured boundary, instrument and sampling method. Distinguish
  board from whole-system power; unavailable telemetry remains unavailable, not zero.

## Count the same work and bytes

For dense `M×K` multiplied by `K×N`, the conventional count is `M×N×K` MACs or
`2×M×N×K` FLOPs: one multiply plus one add counts as two operations. State this
convention; count bias, activation and other operations separately. Integer work is
reported as operations, not floating-point work. Do not mix precision categories.

Separate actual sparse operations from dense-equivalent operations, with sparsity
pattern and metadata overhead. A sparse advertised peak is not dense measured speed.
Report host-transfer bytes separately from device-memory traffic; identify measured
counters versus estimated bytes, their units and which cache/memory boundary they count.
Distinguish useful payload from bus traffic and reads from writes. Arithmetic intensity
uses a stated operation count divided by bytes at the same boundary. `ci/roofline.py`
defaults to a scalar compute roof; tensor roofs require an explicit justified count.

## Do not mix evidence levels

| Execution | Permitted interpretation |
|---|---|
| SimX timing model | Modeled cycles/counters; functional-only mode is not a timing benchmark |
| Native RTL / XRT `hw_emu` | Specified RTL/integration evidence, not physical FPGA speed or power |
| XRT `hw` on an identified board | Measured FPGA results for that configuration and operating conditions |
| Identified fabricated device | Measured silicon results for that device, board and conditions |

Commercial-GPU names in inherited simulation profiles are model configurations,
not evidence that AI-GPU equals those products. Theoretical peaks and synthesis
estimates must be labelled separately from every measured result.

## NVIDIA comparisons and acceptance

A comparison needs identified physical devices, reproducible software versions,
equivalent model/weights, inputs, batch/sequence lengths, precision, sparsity and
quality requirements. Match timing boundaries, transfer/cache policy and power
boundary; disclose optimized libraries, device settings and capacity constraints.
Report both platforms' raw measurements and limitations. A vendor peak, simulator
projection or differently scoped kernel result cannot establish end-to-end parity.
No such comparison is claimed by this setup.

Archive the frozen specification, numerical checks, raw samples, analysis and
artifact hashes in a reviewed [evidence report](evidence/README.md). Associate it
with the applicable canonical gate, including P06-A01/A02 and later P07/P11 physical
gates, only within its actual scope. Missing execution stays `not_run` or `blocked`;
metadata validation alone never turns a benchmark plan into a performance result.
