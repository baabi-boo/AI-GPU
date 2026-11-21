# Native benchmark contract v1

This contract defines the first P06 native baseline. Its machine-readable
workloads, counter identities, configuration and measurement policy live in
[`p06_benchmark_contract.json`](../../ci/project/p06_benchmark_contract.json).
It adds observation and qualification tooling around the existing managed
applications; it changes no installed runtime ABI or native arithmetic.
Implementation or host-test success alone is not P06-A01 acceptance.

## Supported execution

The baseline uses the SimX timing model, RV64, the pinned `p02-tfr` profile,
one cluster/core, four warps of four threads and issue width one. Ordinary TFR
tensor operations and STD scalar arithmetic retain the existing numerical
contract. Both FP16 and BF16 inputs produce FP32 outputs. Functional simulation,
unqualified simulator worker configurations, debug/waveform modes and changed
arithmetic/configuration are rejected.

Two new regression applications compile the unchanged application, managed
runtime and kernel sources:

| Benchmark executable | Original application | Work per invocation |
|---|---|---|
| `ai_bench_matmul` | `ai_matmul/main.cpp` | One accepted matrix multiplication, original validation and cleanup |
| `ai_bench_mlp` | `ai_mlp/main.cpp` | One fixed model: hidden projection and two output row blocks, plus declared host bridge/assembly |

The benchmark-only observer links through exactly
`--wrap=vx_device_open` and `--wrap=vx_device_release`. It borrows the handle;
it must not retain it, replace ownership or intercept launches/transfers/waits.
Each application executes exactly one iteration in its own process. P03's two
intentional rejected submissions remain inside that original route.

## Frozen workload and repetition policy

The manifest fixes three operator fixtures and one model fixture in each format.
Their original independent reference inputs and expected outputs remain unchanged.
The complete manifest has eight workloads. Each has one retained, unmeasured
warm-up followed by five measured fresh-process invocations in canonical order.

All invocations create a fresh device context. No device-cache warming, module
reuse, allocation reuse or resident-weight reuse is implied by the warm-up.
Keep every raw sample and every failed attempt. A failed warm-up, incomplete
repeat sequence or substituted workload invalidates the affected packet.
Partial format selection can produce a scoped result, but cannot claim the
complete two-format baseline.

| Native shape / model | MACs | Conventional FLOPs | Input H2D bytes | Poison H2D bytes | Tensor D2H bytes |
|---|---:|---:|---:|---:|---:|
| `(8,4,8)` | 256 | 512 | 192 | 128 | 128 |
| `(8,4,16)` | 512 | 1,024 | 384 | 128 | 128 |
| `(16,8,16)` | 2,048 | 4,096 | 768 | 512 | 512 |
| Fixed `16 → 8 → 4` model, batch 16 | 2,560 | 5,120 | 1,152 | 768 | 768 |

One multiply plus one add counts as two FLOPs. The model separately performs
128 host ReLU decisions, 128 exact format conversions and 256 bytes of output
row assembly. These logical counts are not measured CPU instructions or memory
traffic. Tensor transfer totals exclude module, argument/control and other
runtime setup traffic. Destination poisoning is explicit extra H2D traffic.

## Counter boundary

The initial snapshot occurs immediately after successful real device open. The
final snapshot occurs before real device release, after the application's
completed operations and other owned resources have been drained. The actual
release result is retained separately. Counter-query failure or output failure
must not prevent forwarding the real release.

The selected counters accumulate over the entire device context, including all three native
launches for the model. Compute a delta only from matching monotone raw values.
Reject decreases instead of guessing a reset or wrap. Queries use the explicit
MPM class/CSR and representative core zero. Frozen single-core topology avoids
double-counting shared socket, cluster and global cache/memory counters.

The counter list covers active core cycles, retired macro instructions,
scheduler activity and stalls, TCU work, instruction/data cache activity,
local-memory activity, coalescing and external-memory requests/latency.
Disabled L2/L3 readings are explicitly unavailable with null status/value;
they are not measured zeros. Required queries must return success. Every row
retains its identity, native unit, scope, enabled state and original value.

The selected inventory contains 45 rows: 33 available counters and 12 unavailable
L2/L3 rows on the frozen profile. Cache-port bank-arbitration counters are excluded:
`CachePortArb::on_reset` clears their collision count on each launch, so a final
snapshot would lose earlier model launches. The local-memory and external-memory
bank-stall counters use different cumulative accumulators and remain included.
This selection was corrected during independent review before native execution;
the simulator and RTL remain unchanged.

Active core cycles are modeled cycles while the core has work. They exclude
some idle time and are not synchronized model latency. Instructions are macro
instructions, not lane operations or FLOPs. Stall counters overlap and cannot
be summed into a total elapsed interval. Off-chip request counts represent
their modeled boundary; they do not measure all host DMA bytes. Any derived
request-byte quantity uses the checked generated memory-block size and remains
distinct from useful payload and physical traffic.

Core load/store counts describe issued lane requests. Coalescer misses count
extra coalescing rounds, not unique source requests. Tensor tile-buffer counters
describe WGMMA buffering and may legitimately remain zero for these ordinary
WMMA workloads; zero does not establish that the tensor unit was idle.

## Host time and observation overhead

Both snapshots include steady-clock query start/end timestamps. Process wall
time comes from the bounded-process runner. The model's original host/event
profiles retain their original definitions. The begin queries occur inside
model creation and the end queries inside model close. Consequently those
durations and process wall time include instrumentation, numerical validation,
setup and cleanup.

Do not subtract the observer duration from overlapping intervals or label the
result clean device time. Do not add host wait intervals to nested event
profiles. Retain host work, transfer observations, launch observations, counter
deltas and process durations separately. Five measurements support elementary
sample summaries; they do not establish tail latency or statistical confidence
about production hardware.

Check the entire observed model span from creation start through the final query
against the process receipt. The aggregate advance duration must fit between
creation completion and final-query start. Each host bridge/assembly and native
stage duration that the original implementation nests inside advance must fit
that parent duration. These are containment checks; overlapping intervals are
never added to manufacture an elapsed total.

## Records and validation

The runner supplies a unique, bounded ASCII `P06_SAMPLE_ID` to every subprocess.
Each observation identifies that sample and the single device context.

- `P06_BEGIN` contains the initial capability/counter observations.
- `P06_END` contains the final capability/counter observations.
- `P06_RELEASE` records the actual real release status.
- `P06_FAILURE` invalidates observation, regardless of the application's result.

Snapshots contain schema version, sample/context identity, device index,
compiled memory-block size, query timestamps, ordered capability records and
ordered counter records. Capability entries contain name, API identifier,
status and value. Counter entries contain name, class, CSR, representative
core, scope, unit, enabled state, status and value. JSON keys/types, inventories,
identities, successful statuses, topology and counter bounds are strict.

The original numerical output is validated without filtering observer lines.
The matrix application prints `P03_RESULT` before `P06_END`/`P06_RELEASE`;
the model prints `P04_RESULT` after those markers. Both finish with exactly one
`PASSED!` and successful process termination. Counter observations alone never
prove numerical success, and `PASSED!` alone never proves successful observation.

## Compiler and execution provenance

The accepted numerical validators remain unchanged. P06 validates every
original runtime, backend, kernel and host compiler record independently.
`PERF=1` naturally defines `PERF_ENABLE` only for the SimX backend; the other
records must preserve its absence. No stripped, expanded or combined stamp
may replace original evidence. The effective backend header confirms the
performance-enabled native geometry.

Reject `SIMX_FUNCTIONAL` even with value zero, unqualified worker selectors,
alternate arithmetic, incorrect kernel ISA/ABI, fast math, unexpected tracing,
undefinitions and unsupported flag/link changes. Require exactly the two
observer wrapper options and the generated runtime link binding.

Include paths and their order are frozen separately for every compiler role.
Retain the small generated `#include <VX_config.h>` probe and preprocess it with
the role's actual include paths, macros, and compilation directory. Compare its
complete hardware macro map with the independently generated expected map.
Forcing an absolute canonical header would miss a shadow header selected by the
real compiler. Extra, missing, reordered, or forwarded include paths are rejected.

Use fresh generated builds with matched configuration. Retain source, tools,
dependencies, generated headers, original stamps, application/kernel/runtime
hashes, original logs, raw numerical records and the manifest. Bind the P06
workflow, observer, validators, runner and all locally imported helper sources.
Check inventories before and after execution; source or artifact drift fails.

The runner retains the P04 resource budget: two jobs, a polled 4 GiB process-group
RSS limit, a 15 GiB disk reserve, 16 MiB per-command logs and bounded build/run
deadlines. Resource polling is a practical limit, not proof of exhaustive
container accounting. Hosted qualification uses read-only repository permissions
and restored pinned inputs; incomplete/failed evidence is uploaded as well.

## Qualification and exclusions

The full suite consists of 48 invocations / 72 native launches, including
40 measured invocations / 60 measured launches. P06-A01 requires independent
review of the complete original matrix, its provenance and recomputed summaries.
Offline data replay is evidence consistency checking, not a new GPU execution.

This baseline does not establish an optimization, physical throughput, power,
energy, FPGA performance, synthesis timing or silicon. It does not use a scalar
compute roof as a tensor roof, convert a configured clock into measured latency,
or compare against commercial GPUs. P06-A02/A03 remain separate obligations;
P01 vendor integration and inherited area findings retain their existing scope.
