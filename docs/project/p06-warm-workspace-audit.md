# P06 warm workspace development audit

## Audited checkpoint and selected work

This continuation starts at `13dc0d1fdb6d5322104e381aa342dc139c7bb80c` on the
authorized `baabi-boo/AI-GPU` `master` branch. The initial checkout was clean.
The current roadmap keeps P00/P02/P03/P04 complete, P01 blocked on vendor
integration, P05/P06 in progress and P07–P11 not started. No phase state is
changed by this audit.

The selected next step is to qualify the already implemented serial workspace
and implement its separately specified warm-context measurement route. The
existing correctness workflow has produced successful results at this source,
but the handoff still describes them as pending. A workflow success is an input
to original-artifact review, not the review itself.

The seven workflows observed at this checkpoint all concluded successfully:
CI, Project Governance, P04 Native Model, P05 Installed Python, P05 Installed
PyTorch, P06 Frozen Baseline Replay and P06 Serial Workspace. The workspace
originals come from [run 44925627664, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44925627664).
Their downloaded ZIP bytes were verified against GitHub's reported sizes and
SHA-256 digests before inspection. Original archive identities are retained in
[the new packet](evidence/p06-warm-workspace/originals/artifacts.json).

## Audit findings that determine implementation

| Finding | Consequence and selected action |
|---|---|
| The current runtime already contains both allocation policies and serial ownership guards. | Use the same clean source and executable for both arms, varying only policy and sample identity. No production arithmetic or scheduling change is necessary. |
| The correctness parser checks individual process outputs, but there is no complete offline workspace archive verifier. | Add a separate replay path that binds raw logs, source, compiler records, job identity and the complete backend/format matrix. |
| The rich correctness observer performs additional native memory queries on every allocation and release. | Preserve it for correctness. Use minimal fixed-storage accounting for timed runs; otherwise policy-dependent measurement work would confound results. |
| Its 16-row allocation history cannot hold the 99 allocations of a primed 32-operation default batch. | Give the new measurement observer a bounded design appropriate to its frozen batch, without a growing history scan in the timed region. |
| Both runtime policies share the kernel, inputs, transfers and explicit-close requirements. | Measure buffer lifetime only. Keep numerical comparisons, all input/poison writes, output downloads and operation cleanup in both arms. |
| The cold baseline measures fresh process/context invocations, with a known supervisor observation limitation. | Retain it unchanged. Measure the new primary host interval inside the process and do not subtract a guessed supervisor delay. |
| Existing selected SimX counters persist across launches. | Capture counters after the closed prime and after the final closed operation; validate monotonicity, statuses and unavailable rows before computing batch deltas. |

The first three independent audit receipts are
[runtime](evidence/p06-warm-workspace/agents/w01_a01.md),
[records](evidence/p06-warm-workspace/agents/w01_a02.md) and
[measurement design](evidence/p06-warm-workspace/agents/w01_a03.md).
They record actual inspections, targeted host checks and source hashes.
The full host suite and independent original numerical/resource/provenance
reviews are separate qualification work; their final results belong in the
delivery packet, not an inferred pass here.

## Development boundaries

Freeze the new sampling/record contract before evaluating performance. Retain
one excluded warm-up batch and five measured batches for each format/policy,
with one excluded prime followed by 32 validated serial operations per process.
Alternate paired arm order and keep both arms on the same host and binary.
Report instrumented host time, modeled counters and requested payload with
their actual scopes. Preserve every failed attempt and reject incomplete or
replaced samples. An unsuccessful speedup hypothesis is a valid outcome.

Use the existing two-job, 4 GiB polled process-group RSS, 15 GiB disk reserve,
16 MiB command log, 1,800-second build and 180-second invocation bounds.
The development checkout has sufficient disk/RAM for host work but lacks the
pinned RISC-V/Verilator simulation toolchain; existing hosted preparation is the
native execution route. No local tool absence relaxes the declared budgets.

P06-A01 retains the original cold SimX acceptance at
`84b6ca0ca75fba248ba330642bbf8764db3d459c`. This work does not itself close
P06-A02/A03, qualify a physical FPGA or silicon, resolve vendor P01-A03, or
resolve the inherited 267-to-283 DSP area finding. All protected fixtures,
numerical tolerances, benchmark goldens and upstream assets remain protected.

## Work accounting

The requested execution consists of ten waves of six actual agent assignments.
Three workers run alongside the primary agent, so each wave uses two batches.
Each completed assignment retains a named receipt under
`docs/project/evidence/p06-warm-workspace/agents/`. The final packet reconciles
completed receipts and hashes; this planning record does not predeclare sixty
completed agents or turn a requested count into evidence.
