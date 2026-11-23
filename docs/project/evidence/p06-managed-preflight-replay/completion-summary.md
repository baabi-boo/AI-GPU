# Managed-preflight replay: implementation and release summary

**The complete inert managed-preflight reader and independent Git source
exporter are implemented.** The latest dedicated local workflow passed all
203 selected tests. The earlier clean governance checkpoint passed all
**3,725 unique tests**, with independent terminal review complete. Their
different source revisions and overlapping test populations remain explicit.
The coordinator assigned **60 actual agents across ten waves**, and all
60 reports exist; final dispositions and report fingerprints belong in the
[execution ledger](agent-ledger.md).

The audit selected this step because the producer already had a successful
four-process archive, but lacked a complete reusable reader connecting its
source, build, loader, process, and lifecycle records to independently supplied
expectations. The new reader makes that historical evidence repeatable and
reviewable before future counter qualification. The [development audit](development-audit.md)
explains the decision; the [implemented contract](../../../designs/managed_counter_preflight_replay_v1.md)
contains the runnable CLI and exact pins.

## What is delivered

The [CLI and Python API](../../../../ci/project/p06_managed_preflight_replay.py)
require seven external inputs:

| Input | Purpose |
| --- | --- |
| Archive path | Select a canonical absolute regular ZIP |
| Archive SHA-256 | Identify bytes independently of their contents |
| Source revision | Select the full producer commit |
| Source inventory path | Supply independently selected source expectations |
| Inventory SHA-256 | Pin that exact inventory |
| Derivation receipt path | Bind selection to Git repositories and objects |
| Derivation SHA-256 | Pin that exact derivation |

The [exporter](../../../../ci/project/p06_managed_preflight_source_export.py)
reads explicitly selected Git objects without checking out or executing their
code. Replay checks every retained source body, complete command inventories,
generated configuration, build stages, payload identities, process observations,
stability records, and the enclosing hosted packet. Every archive file must be
accounted for. Recorded producer paths remain data; retained commands, Python,
and binaries are never executed or extracted.

## Findings closed by implementation and review

| Finding | Implemented boundary |
| --- | --- |
| A final host link could stand in for an application build. | Require the complete **30-command application graph per format**, including kernel, startup, archive, conversion, stub, and host prerequisites. |
| Matching generated copies could all contain the same incorrect value. | Reproduce four complete headers across three stages and two formats, plus all **273 flags per format**, using pinned current generator and configuration bytes. Coherently rehashed header changes reject. |
| Backend logs admitted unrelated records or impossible link order. | Require exactly **46 records per format**: nested make, 43 model compiles, model link, then backend link. Independent compile permutations remain valid. |
| A pinned current helper could load different cached bytecode. | Compile the verified current archive-parser and configuration-renderer bytes directly. Changed source rejects before compilation; cache controls exercise disposable fixtures. |
| Selected blob hashes did not close inconsistent nested Git membership. | Reconstruct the bounded canonical root tree and compare its identity. Prefix collisions and unsupported omitted empty trees reject. All four historical export files remain byte-for-byte unchanged. |

The [regression map](regression-map.md) links concrete controls and their limits.
Process, build, and header mutations repair surrounding hashes, observation
copies, and bindings before requiring their named semantic failures. Positive
serialization and compilation-order controls demonstrate that repaired fixtures
can pass. Original evidence, synthetic controls, and recorded pre-repair
demonstrations remain separately identified.

## Original evidence and its limits

The successful [run 45085300171](https://github.com/baabi-boo/AI-GPU/actions/runs/45085300171)
at producer `57248e73` covers FP16/BF16 and both allocation policies:

| Recomputed population | Count |
| --- | ---: |
| Processes / launches / exact checked words | 4 / 132 / 4,224 |
| Counter snapshots / available queries / half replies | 16 / 528 / 1,056 |
| Flush replies / total DCR replies | 132 / 1,188 |
| Unavailable rows, never queried | 192 |
| Source bodies / retained payload bodies | 999 / 17 |

The 17 payloads total **13,315,886 bytes**. Each format also describes 43 model
objects whose bodies were never retained. Their descriptors and build
relationships can be checked; absent bytes cannot be independently hashed.
Source membership and matching loader observations do not establish cached
dependency compilation provenance.

The correctly pinned failed original, run `45084009157` at `8756f400`, remains
rejected with reader exit **1** and exactly **`report.outcome: value differs`**.
Its application build failed before managed execution. The negative-control
harness accepts only that precise result, including empty stderr and exact
type-correct fields. Missing inputs or an unrelated failure do not satisfy it.
The [independent original review](agents/w06_a01.md) reconciles both archives
with their intake records and observed service metadata.

## Verification and exact source attribution

The [latest local workflow packet](local-replay/f88cccff/files.json) records
execution of the four unmodified shell blocks from the dedicated workflow:

| Block | Exit | Wall seconds |
| --- | ---: | ---: |
| Verify pinned inputs and retain identity | 0 | 0.066 |
| Replay successful original | 0 | 4.248 |
| Require exact failed-original rejection | 0 | 0.819 |
| Execute five required test groups | 0 | 352.466 |

The unittest summary reports **203 tests in 351.775 seconds**, with no failures,
errors, skips, or expected failures. Git status stayed clean and all 335 recorded
current input identities stayed unchanged; all 46 trusted source rows matched
the executed Git blobs. This is local workflow-step execution using an
explicitly synthetic CI identity; checkout/upload actions and hosted Actions
were not executed. Earlier focused reviews overlap these methods and must not
be added as distinct test populations. See the [execution report](agents/w08_a02.md).

Two checkpoints have independently verified, complete tree-equivalent remote
commits. Their different commit metadata do not change the executed revision:

| Validation scope | Local executed checkpoint | Remote equivalent | Result |
| --- | --- | --- | --- |
| Latest dedicated replay workflow | `f88cccff087671ac91507565ed61fa664b34dd67` | `9c9a8ec6c99a05d1f0ea9528a61bf29a389a46ba` | 203 methods passed |
| Broader clean project governance | `5d2b2df53a619e9cde11ae9a4c3337a019a40434` | `150f9d551a6227d112e3bd9c23c4646971390a4a` | 3,725 unique methods passed; independent terminal review complete |

The later computational change is the exporter's 35-line tree check and eight
new tests. Its independent 31-method exporter review passed and all four
historical output digests were preserved; those tests are also included in the
latest workflow selection. The earlier full-suite run does not become a run
of that later change. The [source projection](agents/w09_a01.md) records both
tree equivalences and the exact delta.

The [broader-suite reviewer](agents/w08_a03.md) verified all four zero command
exits, clean pre/post Git status, and **3,725 unique successful methods in
2,528.577 seconds** with terminal `OK`. There were no failures, errors, skips,
expected failures, or unexpected successes. The suite's controller wall time
was 2,530.878 seconds. All ten indexed files in the
[retained governance packet](local-governance/5d2b2df/files.json), totaling
762,466 bytes, matched the original outputs, and every gzip matched its raw
log. These results are local; the 3,725 and 203 populations cannot be summed
as unique tests or relabeled as a complete suite at the later revision.

The refreshed source projection twice matched **5,727 tracked entries**,
excluding nine named narrative documents and the replay evidence directory.
It explicitly reviewed and excluded the later handoff clarification without
changing implementation scope. The inventory digest is
`2c9f763544c692fb634a2274db0dea3aa7a8b1118b7da0ef1b2bf8eedec02cf4`.
Completed [workflow coverage](agents/w08_a04.md),
[replay-packet review](agents/w10_a02.md), and
[documentation checks](agents/w09_a06.md) retain their own scope. Consult the
[committed-diff review](agents/w10_a04.md) for exact candidate classification
and protected-source checks.

## Next bounded native development

The [native handoff](../../p06-managed-preflight-handoff.md) identifies the missing
observation: reset clears transient pending reads, while the original witness
does not retain every run/reset boundary. Add a read-only pending-balance
observation and a separately versioned witness for all **33 run/reset pairs**.
Require zero balance before reset, after successful runs and required flushes,
at terminal observation, and immediately before destruction. Record exactly
one reset per admitted run and 33 beyond the observed construction baseline,
with ownership, worker joins, and actual disposal reconciled.

Apply the source-bound **33-selector/40-component** lifetime argument with its
zero-origin, monotonic-update, terminal-sum, and stable-storage premises.
Pending balance remains a separate transient quantity. Preserve existing
completion/error and legacy model-register semantics when adding observations:
`Processor::run_checked()` returns `void`, and observed x3/`gp` data may validly
be nonzero, including `-1`. Retain the actual post-run model field and actual
exception, upstream completion, and API outcomes. A valid nonzero-`gp` control
must remain distinguishable from a real asynchronous failure. Do not infer an
integer return status from the checked call, compare clocks globally across
resets, or read destroyed processor storage.

Fresh dependency configure/compile/link/product receipts must independently
bind selected sources to the actual loaded libraries and static SoftFloat
contribution; nested build parallelism also needs its declared budget.

These obligations precede complete qualification and a fresh admitted warm
attempt of **24 processes, 792 launches, and 25,344 checked words**. All seven
qualification/readiness/warm/coverage/acceptance flags remain false. The three
unresolved lifetime, dependency-provenance, and independent-qualification
obligations remain explicit in the contract.

## Release accounting and project boundaries

**60 actual assignments across ten waves; all 60 reports exist.** The
[accounting review](agents/w10_a06.md) reconciles the distinct task IDs and six
slots per wave. Follow-up turns add no assignments. Use the
[execution ledger](agent-ledger.md) and [structured record](agent-ledger.json)
for final dispositions and fingerprints. Preserve agent 38's substantive
contribution followed by failed final reporting turns; report presence does
not establish 60 normal handoffs. Seven reports were reconstructed by the
coordinator: the six wave-1 reports and agent 38's delivered finding. The early
core report additionally preserves its mixed-author recovery/version
annotation, separately from that reconstruction count.

**Publication identity:** the immutable packet is identified by its
**containing Git commit**. The
coordinator's delivery response supplies the actual published `master` SHA and
the post-push Actions state observed after that branch update. Prepared commit
objects and local results alone do not establish publication or a hosted pass;
the publication observation does not require a second push to insert the first
commit's own identity into this packet.

P06/P06-T01 remain in progress, with P06-A01's existing simulated acceptance and
A02/A03 still open. P05-A02/A03 remain unearned; vendor XRT `hw_emu`, physical
FPGA, silicon, and the earlier RV64 area/DSP finding retain their separate
limits. Warm v1 keeps unconditional `P06-WARM-RV64-MPM-HIGH-HALF` rejection and
`absolute_no_wrap_bound="not_established"`. Replay supplies no new native GPU
execution or performance acceptance. See [current status](../../status.md).
