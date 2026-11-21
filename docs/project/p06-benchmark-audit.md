# P06 native performance baseline audit

## Selected development step

The continuation starts at `21f24602b01dc798fa11066c13bc8ed60a06b7ee` on
`baabi-boo/AI-GPU`'s `master` branch. The next bounded implementation is the
first part of P06-T01: a reproducible, frozen native performance baseline for
the six accepted matrix signatures and the fixed tiny model.

P04 is complete and supplies P06's required native-model dependency. P05's
copying Python binding is accepted, and the newer eager PyTorch implementation
has successful installed qualification jobs at the starting revision. Its
remaining independent artifact review and phase closure are separate from
this work. P06 does not depend on P05. No framework result is silently promoted
to acceptance by choosing this native development path.

The existing P03/P04 execution packets prove numerical results, dispatch,
ownership and explicit host/tensor-transfer observations. They do not provide
the frozen repeated performance experiment required by P06-A01. Optimizing
allocation, reuse, geometry or launch overhead before that baseline would lack
an agreed before/after measurement boundary. The benchmark must precede the
choice of an optimization.

## Findings that determine the implementation

| Finding | Source and consequence |
|---|---|
| The existing workloads already cover the required arithmetic | The P03 operator manifest accepts three matrix shapes in FP16/BF16. The P04 fixture defines the bias-free batch-16 `16 → 8 → 4` model. Reuse those exact inputs and independent numerical readers. |
| Counter lifetimes must be checked individually | SimX core, cache-bank statistics, local-memory, tensor-unit and processor-memory accumulators survive launches. Cache-port arbitration collisions do not: independent review found that reset clears them on every launch. Exclude all three cache-port bank-arbitration descriptors and retain only monotone whole-context counters. |
| Core cycles have a narrower meaning than wall time | `Core::tick` increments active-work cycles; retired instructions count macro instructions. Neither is a physical GPU latency or a count of floating-point operations. |
| Counter classes are directly queryable | `vx_device_mpm_query` includes the performance class in each DCR request. Multiple classes can be read from one invocation without replaying the workload for each class. |
| Shared counters cannot be summed once per core | Cache scope differs by socket/cluster/global hierarchy. Freeze one core, one cluster and one-core sockets, with a single representative query for each scope. |
| The managed owners hide their device handles deliberately | A benchmark-only linker observer around device open/release can observe the borrowed handle without changing runtime ownership, installed ABI or production source bodies. |
| Original app record ordering differs | P03 prints its numerical result before runtime close; P04 closes the model before printing its result. Validate each route's actual chronology. |
| Observer cost is inside some existing host intervals | Initial queries occur during model creation and final queries during close. Keep those durations and subprocess wall time explicitly instrumentation-inclusive; do not subtract overlapping intervals. |
| Timing intervals require joint containment | Independent synthetic probes showed that separately bounded creation and context intervals could jointly exceed process duration, and child durations could exceed their enclosing advance. Validate the complete observed model span and the original implementation's proven nesting, without adding overlapping intervals. |
| The accepted numerical runner excludes performance builds | P02/P03/P04 compiler validation rejects `PERF_ENABLE`. P06 needs its own strict, independently reviewed contract over the original records; removing flags from evidence is not valid reuse. |
| `PERF=1` affects only the SimX backend compiler record | Runtime, kernel and host stamps naturally lack `PERF_ENABLE`. Require the macro in `backend_cpp` and preserve its absence in the other records. |
| Functional simulation can produce correct but untimed results | `SIMX_FUNCTIONAL` selects a different simulation kernel through `#ifdef`, even when defined as zero. Reject it explicitly; also reject unqualified worker-mode overrides. |
| Header search is part of effective configuration | Independent host preprocessing reproduced an accepted extra include path selecting a shadow header that enabled `SIMX_FUNCTIONAL=0`, while the original forced-header probe passed. Freeze actual include order and probe the real search from each role's compilation directory; retain the probe body. |
| Resource and provenance gates remain necessary | Reuse the bounded-process and clean-source/tool/build inventory helpers. The P06 packet must retain its own workflow, observer, contract, validators and transitive helper sources. |
| Configuration could report success after a generation error | Independent generated-stamp tests found that `configure` attempted to parse root packaging metadata as hardware configuration, printed a traceback, and continued. Restrict generation to the existing three hardware inputs and propagate both generator exit statuses. Required hardware inputs now fail when missing. No parser, hardware default, profile, or arithmetic definition changes. |

## Frozen experiment

For each of FP16 and BF16, select the existing `single-dense_boundaries`,
`numerical-cross_tile_rounding_positive`, and `multi-dense_boundaries` operator
fixtures, and the `seeded_dense` model fixture. They cover `(8,4,8)`, `(8,4,16)`
and `(16,8,16)` matrix multiplication and the model's three composed launches.

Each workload has one retained warm-up invocation followed by five measured
fresh-process invocations, always with one application iteration. The complete
suite therefore has 48 invocations and 72 native launches: 40 invocations / 60
launches are measured, while eight invocations / 12 launches are warm-up. A
fresh-process warm-up does not create warm device caches for later processes.

Counter changes cover the whole device-context lifetime, including the relevant
module/setup, transfer and cleanup activity before final release. The model
counter changes encompass all three launches. They are not per-kernel or
per-stage measurements. Native matrix operation counts, useful input bytes,
destination poison, output bytes and host bridge/assembly work remain separate
from measured memory requests and host timing.

Every sample must pass the original exact numerical and cleanup checks as well
as the new observation checks. A failed warm-up, missing repeat, query failure,
functional-mode build, source drift or incomplete release invalidates the
corresponding qualification. No cherry-picking, silent retry or fabricated zero
counter may repair a failed packet.

## Execution and review

The initial checkout passed the project metadata validator. Its simulation
preflight was blocked by unavailable local toolchain/submodule inputs and
insufficient disk for the inherited 15 GiB reserve. Available memory also varied
below the native runner's 4 GiB prerequisite. These are prerequisite observations,
not failed arithmetic and not permission to lower a gate. Host-only regression
tests run locally; native execution uses the reviewed hosted qualification path.

The user authorized implementation and direct commits/pushes to `master`.
Sixty distinct assignments are organized in ten six-assignment waves, with at
most three subagents executing beside the integration owner. The development
receipts record actual completed work, authorship, tests and independent review.
No agent review is represented as an invented human approval or a waiver.

The configuration failure was reproduced with CPython 3.12.14. Selecting a newer
Python interpreter does not fix it: `gen_config.py` uses its own hardware-TOML
parser. The original failing test log is retained. A focused regression checks
packaging metadata exclusion, all six real generated headers, missing required
inputs, both language-generation failures, and failure during reconfiguration
with old headers still present. Independent generated-header comparison checks
that the valid hardware outputs are unchanged.

Independent observer review also corrected the original 48-counter draft. The
data-cache bank-arbitration count resets per launch and would silently report
only the final model launch. The equivalent L2/L3 descriptors share that lifetime,
although those caches are disabled in this profile. All three were removed before
native execution, leaving 45 rows: 33 available and 12 explicitly unavailable.
Other selected counter families were checked through their reset paths. The
original draft reviews and host-test receipts remain historical development
evidence; they do not qualify the corrected final counter inventory.

The compiler-search defect was also demonstrated before native execution. The
correction validates every role's exact include list and rejects forwarded
include options whose order could differ from their parsed representation.
Effective probes now use the real search, including the runtime's relative
`../common` path. Regression tests cover both extra directories and shadow
headers placed in already permitted directories. The original reproduction and
the corrected tests remain distinct development evidence.

## Acceptance boundary and remaining work

The first integrated host run retained 2,304 executed tests in 991.084 seconds
with nine setup errors and no assertion failures. Every error identified the
same old minimal hardware-emulation fixture: it copied two hardware TOMLs but
omitted the now-required `vortex_opae.toml`. Adding that source input preserves
the strict configuration check and restores the 100 affected tests; it changes
no simulated or vendor execution contract. The original failed run remains
development evidence, and the corrected full suite must qualify separately.

The new modules add 149 tests to the starting hosted suite of 2,252. The
starting hosted run took 394.779 seconds; the new focused receipts came from
different environments and cannot be added into an exact hosted prediction.
Independent review nevertheless found the previous ten-minute host-job budget
too tight for the expanded coverage. Project Governance now has a bounded
twenty-minute allowance, with all three strict budget assertions updated
together. Every checker and test remains unconditional. Native process limits,
memory/disk prerequisites, numerical tolerances and performance gates are
unchanged. The exact-checkpoint hosted run supplies the corrected full-suite
result before any P06 acceptance.

P06-A01 requires the actual frozen execution matrix and independent review of
its original results. A source or host-test pass cannot earn it. The baseline
alone does not implement an optimization, qualify native RTL performance,
establish a synthesis budget or complete P06-A02/A03.

The missing vendor XRT integration remains P01-A03's separate blocker before
P07. The inherited tensor area finding of 267 → 283 DSPs also remains unresolved.
This continuation changes neither RTL nor timing-model behavior, golden data,
toolchain pins or gate tolerances. Physical FPGA speed, power and silicon
measurements remain unavailable. The final evidence packet and handoff record
the exact tested source, completed commands, failed attempts and next bounded
optimization hypothesis.
