# Current project status

**P01-A01 and P01-A02 are accepted; P01 remains blocked on vendor `hw_emu`.**
All six frozen numerical executions pass from a clean GPU source checkout.
The fresh generated FP16 SimX build and supplemental full-AFU integer `xrtsim`
smoke also pass. Independent reviews accept the clean-build and native numerical
packets. Qualified vendor tools/platform are still missing for P01-A03. P00
remains complete and P02 remains not started.
[roadmap.json](roadmap.json) remains authoritative for phase state and evidence;
the linked reports define the exact accepted scope.

## Where the project stands

| Area | Current state | Meaning |
|---|---|---|
| P00 — project foundation | `complete` | Its three source-level acceptance gates and verified default-branch delivery remain preserved |
| P01 — reproducible baseline | `blocked` | A01 clean-build and A02 six-case numerical reports accepted; A03 vendor integration is the remaining blocker |
| P02–P11 | `not_started` | Later numerical, software, hardware and silicon gates have not been earned |
| Full vendor XRT `hw_emu` | `blocked` | Required vendor tools, identified platform and matching integration artifacts are unavailable |
| Physical FPGA / custom silicon | Not qualified | No physical board or fabricated silicon measurements are established |

Execution and integration owner for this continuation: the primary coding agent
(`/root`). Independent agent reviews supply scoped engineering evidence; they
are not invented human approvals or waivers.

## Implemented P01 work

The [P01 runbook](p01-baseline-runbook.md) supplies the reproduction sequence.
The implementation contains:

- An immutable [toolchain lock](../../ci/project/p01_toolchain.lock.json) and
  [bootstrap](../../ci/project/baseline_bootstrap.py) for the minimal RV64 tool
  set, with verified archive identities, bounded extraction and install receipts.
- A [six-case matrix](../../ci/project/p01_baseline.json) and strict
  [loader](../../ci/project/baseline_matrix.py), preserving catalog provenance,
  dimensions, random seeds and inherited numerical tolerances.
- [Source/tool/build inventory](../../ci/project/baseline_inventory.py) and
  [bounded process execution](../../ci/project/baseline_process.py), retaining
  exact identities, logs, failures and resource-stop reasons.
- A [sequential runner](../../ci/project/baseline.py) with read-only planning,
  fresh output directories, atomic progress records, effective configuration
  checks and CPU-reference success-marker checks.
- Independent tooling tests for provenance, matrix integrity, shell-token
  rejection, resource limits, descendant cleanup, archive safety and failure
  retention. Passing these tests does not demonstrate GPU numerical correctness.

| Frozen workload | Dimensions | Observed SimX / processor RTL results |
|---|---|---|
| FP16 → FP32 GEMM | `M=N=K=64` | `pass` / `pass` |
| BF16 → FP32 GEMM | `M=N=K=64` | `pass` / `pass` |
| TF32 → FP32 attention | `N=32, D=16, c=8, t=8` | `pass` / `pass` |

Each pair explicitly selects **TFR tensor and STD scalar arithmetic**. SimX
remains a software model. Processor `rtlsim` and supplemental full-AFU `xrtsim`
remain distinct from vendor `hw_emu`, physical FPGA execution and silicon.
Attention uses SS operands for both GEMMs. The unused `WGMMA_RS` command macro
does not establish RS coverage; the [erratum](evidence/p01/attention-operand-erratum.md)
preserves and corrects the original matrix's descriptive error.

## Reviewed execution packet

The GPU source checkout is pinned to
**`03181532b81fe95b1cfeac2ffb25d8597af689b2`**, separately from the evolving
baseline tooling published at **`e9c9ac01f93b0d84915340999100260f2599ec44`**.
All six executing helper snapshots match that implementation commit. Source/tree,
recursive submodule and generated-build identities are retained. The toolchain
tag `v3.0.2` resolves to immutable commit
`e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`; the lock covers 18 archive parts,
**720,873,529 compressed bytes**.

| Observation | Outcome and boundary |
|---|---|
| Pinned source, recursive submodules and minimal RV64 tool provisioning | Prepared; inventory checks passed against the clean execution checkout |
| Memory-model dependencies, kernel library and host runtime | Built successfully; this does not prove a GPU workload result |
| Initial FP16 SimX attempt with GCC 14.2 | Failed during compilation of pinned spdlog/fmt with `-Werror=dangling-reference`, before the numerical workload ran; the failed command and log are retained |
| Dedicated GCC 11.3 compiler and completed numerical cases | Compiler smoke and all three paired workloads passed their CPU-reference checks |
| First FP16 processor-RTL build | Stopped because the supplied Verilator Makefile expected an absent `ccache` executable; the runner now explicitly sets `OBJCACHE=''`, and the bounded direct-compile retry passed. Both attempts are retained |
| Frozen six-case numerical matrix | [P01-A02 accepted](evidence/p01-native.json): all six cases pass; review reconciled 15 command logs, 18 configuration snapshots and 41 exported artifacts |
| Separate fresh generated-build smoke | [P01-A01 accepted](evidence/p01-build.json): fresh FP16 SimX generated build, five successful commands and zero reference errors; reused dependency libraries remain explicitly pinned |
| Supplemental full-AFU `xrtsim` smoke | [Pass](evidence/p01/xrtsim/report.json): four successful commands and all 16 integer reference points; vendor `hw_emu` remains a separate obligation |
| Source-root project/tooling checks | 346 tests and governance validation pass; these checks do not certify numerical execution |
| Full vendor XRT `hw_emu` | Blocked by missing vendor tools/platform; no P01-A03 pass is claimed |
| Synthesis, physical FPGA and silicon qualification | Not performed by this baseline continuation |

The execution budget uses two compile workers, a 15 GiB free-disk reserve,
6 GiB sampled process-group RSS and bounded logs/time. Host available-memory
observations do not certify a cgroup limit; the execution environment does not
expose that limit. Keep this limitation in the packet.
The final [resource observation](evidence/p01/resource-observation.json) records
no budget stops, a highest sampled process-group RSS of **3,494,166,528 bytes
(about 3.25 GiB)**, and **53.48 GiB free disk** after all three packets completed.
Simulation durations and these host-resource measurements do not establish
physical accelerator performance.

The [historical packet](evidence/p01/history/README.md) retains failures and old
instrumentation with [raw-to-published hash mappings](evidence/p01/history-manifest.json).
The [implementation review](evidence/p01-review.md) records concrete findings,
independent corrections and acceptance reviews. The [P01 handoff](p01-handoff.md)
records the delivered scope and remaining vendor-integration obligation.

## Offline packet verification continuation

The published [offline packet verifier](p01-packet-verification.md) implements
P01-T06 evidence checks: original-byte verification, a separate unsigned
inventory, and an explicit published-export mode. It also adds a bounded
[CI consistency check](../../ci/project/check_baseline_packets.py) for the
retained native and clean-build exports. Run from the source root:

```sh
python3 ci/project/check_baseline_packets.py
python3 ci/project/baseline_packet.py verify-export docs/project/evidence/p01/native \
  --require-native-records
```

The [packet continuation handoff](p01-packet-handoff.md) records the initial
`e9c9ac0` checkpoint, incorporation of baseline delivery `25ca2e6`, and published
implementation [22c545c](https://github.com/baabi-boo/AI-GPU/commit/22c545c632628f9da9f18ccf8fb512a8bfac7f81).
Its immutable release checkout passed all 591 governance/tooling tests, the
project checker, preflight and both published-packet checks. The handoff records
exact identities, independent review and hosted CI observations. This
continuation performed no new GPU execution and grants no new acceptance.
The six-case and clean-build evidence above remain the reviewed execution record;
P01-A01/A02 remain accepted and P01-A03 remains blocked. Published verification
checks public bytes and retained records, without proving original log bytes or
the asserted redaction relationship.

The separate [packet continuation ledger](p01-packet-agent-execution.json)
records this delivery's actual assignments and dispositions. The original P00
and P01 execution ledgers remain separate historical records.

## Vendor integration tooling continuation

The [vendor XRT runner](../../ci/project/xrt_baseline.py) now implements the
prepared-artifact P01-T05 route. Its [guide](p01-xrt-integration.md) defines the
fixed RV64 integer smoke, pinned platform/runtime/artifact manifest, reviewed
build receipt, fresh host/kernel build and tracing-disabled direct launch.
Independent tooling tests exercise blocked prerequisites, provenance drift,
configuration mismatches, process failures and reference-result handling.
The [continuation handoff](p01-xrt-handoff.md) records verification and delivery.

The current environment still lacks the vendor executables, vendor roots and
qualified platform/artifact packet. No vendor `hw_emu` job ran in this
continuation. Passing tooling tests or a read-only plan does not accept P01-A03;
all existing accepted native evidence and phase states remain unchanged.

## Next bounded action

**Resolve P01-T05's qualified vendor `hw_emu` environment/platform blocker.**
Identify a compatible vendor release and supported platform, freeze their
identities and resource budget, then build matching emulation artifacts and run
the required DMA/launch/completion smoke through the
[vendor integration guide](p01-xrt-integration.md). Stop while any prerequisite is absent;
the supplemental `xrtsim` pass cannot close P01-A03. The accepted numerical
matrix and fresh selected-case build remain separate packets with explicit
dependency provenance. Follow the
[backlog](backlog.md), [P01 guide](phases/p01-baseline.md) and
[acceptance policy](acceptance.md).

## Preserved P00 history

P00 was authorized and merged through
[pull request 1](https://github.com/baabi-boo/AI-GPU/pull/1). The original source
baseline is `da55a516a48b49013724f697d3c12a48932b449f`; the reviewed source candidate
was `5a97e59ed95163c585106250194f816353d6ca4e`, tree
`9f65ae6e2bce7adeaec2432c11756510028c8bc0`. The reviewed PR head was
`bebef861742165db1d0d78352ac008b079a35fdd`, and the verified merge commit was
`106b01945d102eec169e68400b2cb8df985236cb`.

The [accepted delivery record](evidence/setup-accepted.json),
[merge observation](evidence/setup-merged.json),
[source validation](evidence/setup-validation.json),
[command log](evidence/setup-validation.log),
[independent review](evidence/setup-review.md),
[publication observation](evidence/setup-publication.json) and earlier
[blocked delivery record](evidence/setup-delivery.json) remain unchanged.
Their historical checks and workflow observations do not qualify P01.
The original [P00 agent ledger](agent-execution.json) records its 60 completed
assignments across 10 waves; it is not the ledger for this P01 continuation.
The separate [P01 ledger](p01-agent-execution.json) records actual completed
assignments as this continuation progresses; requested totals do not establish
completion or hardware evidence.
The protected README illustration, upstream attribution and inherited golden
results remain preserved; see the [baseline inventory](baseline.md).

## Required handoff for every continuation

Read [AGENTS.md](../../AGENTS.md), this page and the canonical roadmap against
the current checkout. Use the [handoff template](handoff.example.md) to record
exact changes, tested source/tooling identities, commands, results, not-runs,
review findings, publication state and one next bounded action. Update status
and phase evidence together. Preserve failures and never convert missing native
or integration evidence into a passing gate.

## Completed P01 collaboration

The separate [P01 execution ledger](p01-agent-execution.json) records **60 completed
distinct agent assignments across 10 logical waves**, scheduled with at most three
subagents active concurrently. The original P00 ledger remains unchanged. The
completed assignments support the implementation and review; vendor A03 remains
blocked independently of the agent count.
