# P05 copying Python binding — installed SimX evidence

The complete FP16/BF16 installed-binding matrix passes independent numerical,
dispatch and provenance review at source
[`e1420fd550f716df33a2556057b7086a03032cbe`](https://github.com/baabi-boo/AI-GPU/commit/e1420fd550f716df33a2556057b7086a03032cbe),
tree `3a168adfd345ecb3c15dc02b2583dc832bef6049`.
The [full-matrix review](qualification-review.json) binds the original hosted
execution, three complete-matrix audits and six independent per-format reviews.
It supports the bounded P05-A01 binding and clean-installation obligation.
Accepted gates remain authoritative in the [roadmap](../../roadmap.json).

**P05 remains `in_progress`.** This is `vortex-ai==0.1.0`, binding API 1,
using the existing managed matmul and fixed-model native runtime on SimX.
No PyTorch custom operator or framework version has been qualified; P05-A02
and the framework compatibility obligation in P05-A03 remain unearned.
The next bounded development action is the scoped PyTorch custom-op bridge,
with its own version pin, error/gradient policy, clean installation and native
dispatch/numerical evidence. The [binding contract](../../../designs/python_binding_v1.md),
[compatibility matrix](../../p05-python-compatibility.md) and
[development audit](../../p05-binding-audit.md) define the implemented boundary.

## Exact workload and independently derived results

Each format ran the three supported `(M, N, K)` signatures `(8, 4, 8)`,
`(8, 4, 16)` and `(16, 8, 16)` twice, with distinct output poisons.
Inputs are packed little-endian FP16 or BF16: A is row-major and B is
column-major. Output is owned FP32 data. The ten frozen P04 model cases
comprise five families per format, each repeated twice. Every model run uses
three native matmuls, the existing host ReLU/cast bridge and host row assembly.
Both the installed Python route and unchanged native executables were exercised.

| Derived count, both formats | Installed Python | Native comparison | Combined |
|---|---:|---:|---:|
| Standalone matmul runs / launches | 12 | 12 | 24 |
| Model runs | 20 | 20 | 40 |
| Model matmul launches | 60 | 60 | 120 |
| **All native launches** | **72** | **72** | **144** |
| Queried event/profile pairs | 360 | 300 | **660** |
| Standalone FP32 output words checked | 768 | 768 | 1,536 |
| Model hidden FP32 words checked | 2,560 | 2,560 | 5,120 |
| Model stage output FP32 words checked, including hidden | 3,840 | 3,840 | 7,680 |
| Assembled model FP32 output words checked | 1,280 | 1,280 | 2,560 |
| Tensor H2D bytes, including output poison | 46,848 | 46,848 | 93,696 |
| Tensor D2H bytes | 18,432 | 18,432 | 36,864 |
| Host bridge payload bytes | 5,120 | 5,120 | 10,240 |
| Host row-assembly payload bytes | 5,120 | 5,120 | 10,240 |

The twelve native P03 standalone launches do not retain event profiling.
The other 132 launches have five queried event/profile pairs each, yielding
660 pairs. Counting five profiles for all 144 launches would overstate coverage.
The 56-byte argument blocks total 8,064 bytes across both routes; they are
separate from the tensor-copy byte counts above. These counts are not a complete
accounting of every module upload, runtime configuration write or process copy.

The numerical review checks frozen expected bits, actual hidden outputs,
ReLU/cast bytes, their reuse as output-stage inputs and row assembly. The two
routes agree exactly. The dispatch review checks native argument layout,
allocator ranges, successful submission/wait/cleanup states, ordered events and
resource restoration. Host bridge and assembly work is explicitly permitted and
recorded; it does not substitute for the declared device matmuls.

## Review records

| Obligation | Complete matrix | FP16 review | BF16 review |
|---|---|---|---|
| Numerics and input lineage | [Full result](reviews/full-numerics.json) | [Result](reviews/fp16-numerics.json) | [Result](reviews/bf16-numerics.json) |
| Dispatch, ownership and accounting | [Full result](reviews/full-dispatch.json) | [Result](reviews/fp16-dispatch.json) | [Result](reviews/bf16-dispatch.json) |
| Source, build and installation provenance | [Full result](reviews/full-provenance.json) | [Result](reviews/fp16-provenance.json) | [Result](reviews/bf16-provenance.json) |

The complete auditors ran with both packet arguments and without selected-scope
mode. Each per-format audit explicitly records incomplete selected scope; its
packet result is identical to the corresponding record in the complete audit.
All 206 files in each Python packet, the original ZIPs, the auditor bodies and
22 binding inputs remained unchanged during the full review.

The [auditor guide](reviews/README.md) names exact auditor hashes, independently
tested counterexamples and replay commands. Initial auditor failures and repairs
remain under `reviews/history/`. The final bounded rechecks comprise 24 numerical
cases, 42 dispatch cases, and 26 provenance cases plus four CLI controls.
The aggregate review's wrapper initially read the wrong spelling of dispatch's
full-matrix flag; its own assertion failed after the dispatch auditor had exited
successfully. The original auditor result was preserved and the correct flag was
independently reconciled with both packets and all six per-format reviews.

These are retained-data reviews, not new accelerator executions. They check
internal consistency and source identity under a trusted-builder model. They do
not cryptographically attest that arbitrary logs or binaries were honestly
produced, or reconstruct a reproducible transitive build.

## Hosted execution and clean installation

| Evidence | Exact source and observed result |
|---|---|
| [P05 workflow](hosted/p05-run.json), [jobs](hosted/p05-jobs.json) | Run `44866368565`; both installed SimX format jobs succeeded at `e1420fd` |
| [Project Governance](hosted/governance-run.json), [raw log](hosted/governance-job.log) | Run `44866368570`; source validator and **2,174 tests in 421.584 seconds** passed at the same revision |
| [P04 workflow](hosted/p04-run.json), [jobs](hosted/p04-jobs.json) | Run `44866368512`; four existing SimX/processor-RTL model jobs succeeded; supplemental metadata observation, excluded from the P05 counts |

Each format's original execution retains 12 successful P05 commands plus the
15-command native comparison prerequisite. The provenance audit checks exact
command arguments, environment, bounded deadlines, successful exits and cleanup;
the 4 GiB polled process-group RSS cap, 16 MiB log cap, 15 GiB free-disk reserve
and recorded initial memory prerequisite remain unchanged. These are command
monitor budgets, not cgroup or whole-job limits.

The installed environment is Linux x86_64 CPython **3.12.14** with the GIL,
G++ **11.4.0**, Clang **20.1.8**, GNU Make **4.3**, setuptools **84.2.1**,
wheel **0.48.0** and packaging **26.3**. The bound sdist is rebuilt offline
outside the source checkout, and its wheel is installed without dependencies
into a fresh copied-interpreter venv. Isolated imports resolve to that installed
package and its exact five-library project closure. The inventories contain
32 bound-sdist files, 10 wheel members and 13 installed members per format.

Both variants bind the same 22 source inputs, digest
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`,
while retaining distinct bundle and extension identities. The real hosted
offline-wheel command compiles two fresh groups of six translation units and
links twice. The separate local unbound build compiled once with GCC/G++ 14.2.0;
those observations are not interchangeable.

The hosted extension retains the reported Python-toolcache RUNPATH, and SimX
retains its original Ramulator search paths. The loader checks establish the
declared project closure in the tested environment. System libraries and Python
are identified dependencies rather than copied runtime components. This is not
a manylinux or arbitrary-host portability claim. Exact dependency attribution,
license bodies and read-only ELF inspection are retained in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Original archives and replay

| Original archive | Provider artifact | Bytes | SHA-256 |
|---|---:|---:|---|
| [simx-fp16.zip](archives/simx-fp16.zip) | `14692495937` | 6,417,582 | `467122e41bee4e67f9eef285e015b2dee3a52522f0bcb3f497e3cec87e6c7380` |
| [simx-bf16.zip](archives/simx-bf16.zip) | `14692690399` | 6,417,108 | `e951f943ece1878f3767180c4ce2b859939722d2d639c1afb37b8a72c76006d8` |

[Provider metadata](hosted/p05-artifacts.json) and the complete
[member index](archive-index.json) identify 304 regular files per archive.
The original archives retain their provider bytes and hidden configuration
stamps. The top-level original native packet and its `python/native` copy are
the same comparison evidence, not two executions to count independently.

Use the [relocated replay instructions](reviews/README.md#relocated-data-replay)
to verify/extract both exact archives into a fresh directory and run the three
current auditors. Replay needs the repository's recorded Git objects and Python;
it executes no downloaded native binary. The [compatibility guide](../../p05-python-compatibility.md)
documents the separate two-stage procedure for a fresh native/package execution.
Historical development probe scripts retain their original scratch paths;
the current replay commands are the supported relocated data-review procedure.

## Host lifecycle evidence, failures and remaining limits

The [host validation history](development/host-validation.md) retains the
107 fresh compiled fake-runtime scenarios, 11 separate fresh-process probes,
eight real local packaging commands and independent publication review. Its
recorded source hashes match the hosted implementation. Fake-runtime failures
test ownership and error behavior; they do not prove accelerator arithmetic.
Those checks overlap the clean hosted suite and are not added into a new
aggregate test total.

The same history preserves the baseline configure timeout, the source-changing
local full-suite failure, an inherited workload-start assertion and its isolated
passing recheck, the setuptools metadata-leak reproduction, and packaging-harness
prerequisite corrections. The later clean hosted success does not erase these
failures or establish an unobserved cause for the inherited assertion.

The [recorded general-CI snapshot](hosted/general-jobs.json) was still incomplete;
the passing dedicated jobs above do not establish an overall-green general CI
result. Subsequent observations, if retained, have their own timestamps and scope.

One live SimX context and one outstanding matmul are supported per process.
Successful wait does not release ownership; completed explicit close is required
before resubmission. Timeout is retryable, not cancellation, and native
destructors may drain indefinitely. Failed cleanup prevents new native work.
The binding is not a hostile-process or hostile-filesystem sandbox.

No Python RTL/XRT qualification, physical FPGA speed/power, arbitrary model
loading, autograd, training, full framework device backend or CUDA binary
compatibility is established. P01-A03 vendor `hw_emu` remains blocked, and the
inherited DSP increase from 267 to 283 remains unresolved. No native runtime,
RTL, golden value or numerical bound was changed to obtain these results.

The [development receipts](development/README.md) describe actual assignments
and their source snapshots. Completion counts and publication are recorded
separately; neither an agent count nor this evidence index closes P05.
