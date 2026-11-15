# P01 reproducible baseline handoff

## Current disposition

P01-A01 and P01-A02 are **accepted after independent review**. All six frozen
numerical executions pass: FP16/BF16 GEMM and TF32 attention on both SimX and
native processor RTL. A separate fresh generated FP16 SimX build and the
supplemental full-AFU integer `xrtsim` smoke also pass.

P01 remains **blocked solely on P01-A03**, because qualified vendor XRT `hw_emu`
tools/platform are unavailable. P02 remains `not_started`. The canonical
[roadmap](roadmap.json) owns gate state; the accepted
[clean-build](evidence/p01-build.json) and [native numerical](evidence/p01-native.json)
reports define the bounded scope earned by this continuation.

## Identity and bounded scope

| Item | Recorded identity or boundary |
|---|---|
| Repository / intended branch | `baabi-boo/AI-GPU`, `master` |
| GPU source revision | `03181532b81fe95b1cfeac2ffb25d8597af689b2`, clean separate execution worktree |
| GPU source tree | `1d281d25f72787ed3545285580b4c390d2f7eb3a` |
| Published baseline instrumentation | `e9c9ac01f93b0d84915340999100260f2599ec44` |
| Instrumentation tree | `fbafa8e643aa935a1103e0d49ce2268b32f12c1e` |
| Execution / integration owner | Primary agent `/root`; independent scoped reviews are recorded separately |
| Toolchain tag / immutable commit | `v3.0.2` / `e3db4bcdf819a17f618ad9fc2472f8f7dea3192b` |
| Work boundary | Implement reproducible P01 baseline tooling and retain named native numerical results; no native hardware behavior, inherited golden, tolerance or toolchain-pin change |

The six executing helper snapshots match the published instrumentation commit.
Later documentation and evidence attachment do not change the GPU source tested.
Both checkouts and their distinct identities are required for exact reproduction;
the older GPU source predates the new runner. Follow the
[runbook](p01-baseline-runbook.md) for the pinned fetch/worktree commands.

## Implemented changes

The implementation adds a frozen six-case RV64 matrix, an immutable minimal
toolchain lock and safe bootstrap, source/tool/host/generated-build inventory,
and sequential bounded execution. The runner retains exact commands, failures,
configuration stamps, binary identities and helper snapshots. It rejects
missing or drifting prerequisites and records partial coverage without promoting
it to phase completion.

Independent tests and reviews closed concrete defects in manifest trust,
duplicate JSON fields, generated-input validation, native enum aliases,
dependency/helper/host drift, and cancellation at process completion. The
[review record](evidence/p01-review.md) identifies authors, independent reviewers,
regressions and scope limits. The separate [P01 ledger](p01-agent-execution.json)
records completed assignments; the original P00 ledger is preserved.

## Configuration, references and resources

All six cases use RV64, explicit TFR tensor arithmetic and STD scalar arithmetic.
SimX remains a software model; processor `rtlsim` exercises the native datapath
but bypasses the AFU. The full frozen flags and catalog derivations are in the
[matrix](../../ci/project/p01_baseline.json).

| Workload | Shape / geometry | Unchanged reference |
|---|---|---|
| FP16 → FP32 GEMM | `M=N=K=64`; NT8, NW4, issue width2 | Seed50; double accumulation of converted-input products; strict relative error `<0.01`, with equal zero pairs accepted |
| BF16 → FP32 GEMM | `M=N=K=64`; NT16, NW4, issue width1 | Same seeded GEMM comparison |
| TF32 → FP32 attention | `N=32`, `D=16`, `c=8`, `t=8`; NT4, NW4, issue width4, NRC8 | Seed50; quantized Q/K/V and unnormalized P; unscaled attention reference; `atol=rtol=0.001` |

The attention kernel uses **SS operands** for both GEMMs. The recorded
`WGMMA_RS` macro is inert for this kernel. Read old matrix snapshots with the
[operand coverage erratum](evidence/p01/attention-operand-erratum.md); preserving
the executed flags does not establish RS coverage. Only the current matrix's two
attention descriptions were corrected after the full run. The
[correction record](evidence/p01/matrix-description-correction.json) verifies that
all executable fields remain unchanged and that the original executed matrix
snapshot is retained.

The immutable tool lock covers 18 compressed parts totaling 720,873,529 bytes.
Actual initial provisioning preceded the production bootstrap; its own script
and manifest are retained, and no later installer receipt is fabricated.

| Build stage | Observed compiler |
|---|---|
| Initial SoftFloat / Ramulator dependencies | Host GCC 14.2 |
| Native simulator, runtime and application | Verified host GCC 11.3.0-12 |
| Device libraries | Pinned RISC-V GNU 12.2.0 |
| Device application kernels | Vortex LLVM 20.1.8 |

The execution budget is two compile workers, a 15 GiB free-disk reserve,
6 GiB sampled process-group RSS, 16 MiB per-command logs and a 1,800-second
per-command timeout. These are monitored budgets, not hard filesystem or memory
quotas. The environment does not expose a certified cgroup memory allocation.
No debug traces, whole-GPU synthesis or physical hardware measurement is claimed.
The final [resource observation](evidence/p01/resource-observation.json) records
no budget stop across the three sequential packets. The highest sampled
process-group RSS was 3,494,166,528 bytes (about 3.25 GiB), and 57,420,263,424 bytes
(53.48 GiB) of disk space remained free after execution. These host-resource
observations and simulated durations do not measure physical accelerator speed.

## Completed verification

The primary agent invoked the frozen runner from the instrumentation checkout,
with GNU 11 and the prepared Python environment first on PATH. Its path-redacted
form is:

```sh
python3 ci/project/baseline.py run \
  --source "$AI_GPU_SOURCE" --build-dir "$AI_GPU_BUILD" \
  --tool-dir "$AI_GPU_TOOLS" --output "$AI_GPU_OUTPUT"
```

The output directory was new for this invocation. The generated build was reused
from earlier FP16 attempts, reconfigured and checked around every case. The
separate [fresh generated-build packet](evidence/p01/clean-build/report.json)
then executed the selected FP16 SimX case in a new build directory. It records
five successful configure/build/run commands and zero reference errors, with
the reused dependency libraries and their original compiler provenance explicitly
identified. This is a clean application/simulator build, not a hermetic rebuild
of every dependency or a second full numerical matrix.

| Observation / command scope | Outcome | Exit | Evidence boundary |
|---|---|---|---|
| `python3 -I -S -B -m unittest discover -s ci/project -p 'test_*.py' -q` from source root | `pass` — 346 tests | 0 | Tooling/governance only |
| `python3 ci/project/check_project.py` from source root | `pass` | 0 | Project structure and metadata only |
| `gemm-fp16-simx` | `pass` | 0 | Unique CPU-reference success marker; software model |
| `gemm-fp16-rtlsim` | `pass` | 0 | Unique CPU-reference success marker; native processor RTL |
| `gemm-bf16-simx` | `pass` | 0 | Unique CPU-reference success marker; software model |
| `gemm-bf16-rtlsim` | `pass` | 0 | Unique CPU-reference success marker; native processor RTL |
| `attention-tf32-simx` | `pass` | 0 | Unique CPU-reference success marker; software model |
| `attention-tf32-rtlsim` | `pass` | 0 | Unique CPU-reference success marker; native processor RTL, actual SS operand coverage |
| Fresh generated-build FP16 SimX smoke | `pass` — five commands, zero reference errors | 0 | Clean generated-build provenance with pinned reused dependencies |
| Supplemental integer `xrt --target=xrtsim` smoke | `pass` — four commands, 16 reference points | 0 | Full-AFU vendor-free RTL smoke; cannot substitute for vendor emulation |
| Vendor `xrt --target=hw_emu` DMA/launch/completion | `blocked` | `null` | Required tools/platform unavailable; workload unexecuted |

The completed [native packet](evidence/p01/native/report.json) records
`full_native_matrix_passed=true` and retains `phase_complete=false` because vendor
integration remains unqualified. It contains 15 successful commands and six
unique CPU-reference passes. Its [export manifest](evidence/p01/native/export-manifest.json)
maps original hashes to the 41 published artifacts, including all 18 effective
configuration snapshots. The selected clean-build packet does not claim full
matrix coverage.

The [supplemental AFU packet](evidence/p01/xrtsim/report.json) records the local
XRT shim's integer demo through ordered upload, launch, download, completion and
reference markers. Its actual runtime/model stamps select `XRTSIM`/`NOXRT` and
native STD scalar arithmetic. The shim's no-op `xrtBOSync`, always-ready simulated
AXI surface and lack of a vendor platform limit that evidence. Vendor runtime,
PCIe transport, coherence, broad backpressure behavior and physical hardware
remain unqualified; `qualifies_P01_A03=false` is retained unconditionally.

The [historical packet](evidence/p01/history/README.md) separately preserves the
GCC 14 spdlog/fmt compilation failure and missing-`ccache` RTL build failure.
The latter outer command exited 2; 127 was the nested missing-executable error.
The failed invocation retains four `not_run` cases. A standalone successful RTL
retry is retained with its narrower provenance; newer helper checks are not
attributed retroactively. [Hash mappings](evidence/p01/history-manifest.json)
distinguish original bytes from path-sanitized publication copies.

## Review and gate disposition

The base-policy classifier reports R1 for the implementation. Independent reviews
cover source/native selection, numerical references, tooling trust boundaries,
failure preservation, source/build identity, historical artifact integrity and
reproduction instructions. Agent reviews are scoped engineering evidence, not
human waivers. The user authorized implementation and publication to `master`.

| Gate | Current disposition | Remaining evidence |
|---|---|---|
| P01-A01 | [Accepted](evidence/p01-build.json) | No outstanding obligation within the stated clean generated-build scope; dependencies retain separate pinned build provenance |
| P01-A02 | [Accepted](evidence/p01-native.json) | No outstanding obligation within the six frozen ordinary numerical cases; P02 numerical edge semantics are later work |
| P01-A03 | Blocked | Identified vendor tool/platform environment and full `hw_emu` DMA/launch/completion execution |

`/root/w09f_clean_build_acceptance_review` independently accepted A01 after
235 artifact/provenance assertions. `/root/w09e_native_acceptance_review`
independently accepted A02 after reconciling all 15 command logs, 18 configuration
snapshots and 41 exported artifacts. Root integrated those scoped decisions in
the acceptance reports and roadmap. The actual completion count for the requested
agent waves is recorded in the [P01 ledger](p01-agent-execution.json); task counts
do not qualify hardware.

The [vendor prerequisite report](evidence/p01-xrt-blocked.json) records actual
absence within inspected locations. License readiness remains unverified.
Processor RTL and vendor-free `xrtsim` cannot replace that obligation. P01
remains incomplete, P02 remains not started, and no FPGA/silicon qualification
follows from these results.

## Source control and delivery

The primary agent published and read back implementation commit
[`e9c9ac01f93b0d84915340999100260f2599ec44`](https://github.com/baabi-boo/AI-GPU/commit/e9c9ac01f93b0d84915340999100260f2599ec44)
on `master`. Its [Project Governance workflow](https://github.com/baabi-boo/AI-GPU/actions/runs/43766628895)
passed. That hosted observation identifies the implementation checkpoint and
does not predict workflow status for a later delivery revision.

The evidence delivery revision is the commit containing this handoff, the
accepted reports and the blocked A03 record. Its exact identifier comes from
the repository commit and remote readback; it must not replace the tested GPU
source or executing-helper identities above. Hosted CI must be checked for that
delivered head independently of local numerical results. Native sources,
inherited goldens and tolerances, the protected SVG and README embedding,
upstream attribution, and all P00 evidence remain preserved.

## Next bounded action

Verification owner `/root`: resolve P01-T05's qualified vendor `hw_emu`
environment/platform prerequisite. Identify a compatible vendor release and
supported platform, freeze their identities and an explicit resource budget,
then build matching `xclbin`/`emconfig` artifacts and execute the declared
DMA/launch/completion smoke. Retain exact commands, reference results and hashes
for independent A03 review. Stop while a required prerequisite is missing or if
execution fails, identities drift or a budget is exceeded. The supplemental
`xrtsim` pass cannot close this gate. Keep P01 blocked and P02 not started until
the required vendor evidence is earned; update [status](status.md),
[backlog](backlog.md) and [roadmap](roadmap.json) together.

## Completed P01 collaboration

The separate [P01 execution ledger](p01-agent-execution.json) records **60 completed
distinct agent assignments across 10 logical waves**, scheduled with at most three
subagents active concurrently. The original P00 ledger remains unchanged. The
completed assignments support the implementation and review; vendor A03 remains
blocked independently of the agent count.
