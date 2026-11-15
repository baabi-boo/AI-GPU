# Current project status

**Checkpoint: P01 reproducible baseline is in progress.** P00 remains accepted
on `master`. The native baseline tooling is implemented, and execution is being
reproduced from a clean source checkout. **No P01 gate is accepted yet.**
[roadmap.json](roadmap.json) remains authoritative for phase state and evidence;
this handoff is an execution checkpoint, not independent acceptance proof.

## Where the project stands

| Area | Current state | Meaning |
|---|---|---|
| P00 — project foundation | `complete` | Its three source-level acceptance gates and verified default-branch delivery remain preserved |
| P01 — reproducible baseline | `in_progress` | Frozen native matrix, tool bootstrap and bounded runner implemented; numerical execution and reviewed evidence outstanding |
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

| Frozen workload | Dimensions | Required executions |
|---|---|---|
| FP16 → FP32 GEMM | `M=N=K=64` | SimX and native processor RTL |
| BF16 → FP32 GEMM | `M=N=K=64` | SimX and native processor RTL |
| TF32 → FP32 attention | `N=32, D=16, c=8, t=8` | SimX and native processor RTL |

Each pair explicitly selects **TFR tensor and STD scalar arithmetic**. SimX
remains a software model. Processor `rtlsim` and supplemental full-AFU `xrtsim`
remain distinct from vendor `hw_emu`, physical FPGA execution and silicon.

## Execution checkpoint awaiting the reviewed packet

The GPU source checkout is pinned to
**`03181532b81fe95b1cfeac2ffb25d8597af689b2`**, separately from the evolving
baseline tooling. Source/tree, recursive submodule and generated-build identities
are retained. The toolchain tag `v3.0.2` resolves to immutable commit
`e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`; the lock covers 18 archive parts,
**720,873,529 compressed bytes**.

| Observation | Outcome and boundary |
|---|---|
| Pinned source, recursive submodules and minimal RV64 tool provisioning | Prepared; inventory checks passed against the clean execution checkout |
| Memory-model dependencies, kernel library and host runtime | Built successfully; this does not prove a GPU workload result |
| Initial FP16 SimX attempt with GCC 14.2 | Failed during compilation of pinned spdlog/fmt with `-Werror=dangling-reference`, before the numerical workload ran; the failed command and log are retained |
| Dedicated GCC 11.3 compiler and FP16 pair | Compiler smoke and the 64×64×64 FP16 GEMM CPU-reference checks passed on SimX and native processor RTL; BF16 and attention executions remain outstanding |
| First FP16 processor-RTL build | Stopped because the supplied Verilator Makefile expected an absent `ccache` executable; the runner now explicitly sets `OBJCACHE=''`, and the bounded direct-compile retry passed. Both attempts are retained |
| Frozen six-case numerical matrix | Execution work underway; no complete passing matrix or P01-A02 acceptance is claimed at this checkpoint |
| Full vendor XRT `hw_emu` | Blocked by missing vendor tools/platform; no P01-A03 pass is claimed |
| Synthesis, physical FPGA and silicon qualification | Not performed by this baseline continuation |

The execution budget uses two compile workers, a 15 GiB free-disk reserve,
6 GiB sampled process-group RSS and bounded logs/time. Host available-memory
observations do not certify a cgroup limit; the execution environment does not
expose that limit. Keep this limitation in the packet.

## Next bounded action

**Finish P01-T03 using the recorded compatible host compiler and a fresh build
directory, then execute P01-T04's six frozen cases sequentially.** Retain the
GCC 14 failure, all later results, configuration stamps and artifact hashes.
Complete P01-T06's independent evidence review before attaching any passing gate.
Vendor `hw_emu` access and an identified platform remain necessary for P01-A03;
a supplemental `xrtsim` result cannot close it. Follow the
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
The protected README illustration, upstream attribution and inherited golden
results remain preserved; see the [baseline inventory](baseline.md).

## Required handoff for every continuation

Read [AGENTS.md](../../AGENTS.md), this page and the canonical roadmap against
the current checkout. Use the [handoff template](handoff.example.md) to record
exact changes, tested source/tooling identities, commands, results, not-runs,
review findings, publication state and one next bounded action. Update status
and phase evidence together. Preserve failures and never convert missing native
or integration evidence into a passing gate.
