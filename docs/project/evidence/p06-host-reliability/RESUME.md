# Resumption handoff — host reliability

## Revision and pending qualification

The published code and current CI/replay subject is
`81d7a35c641f3a969c23c8e604f7468a4d88644a`, tree
`9da606f541ecb85248ef00995e8288c1266eea88`. The audit continuation preserves
that production source and is published separately on
`audit/host-reliability-100-reviews`. Resolve that branch to its published commit
for readback; the document does not embed its own commit hash. These run
identities do not qualify the later audit commit. Use the [continuation ledger](continuation-ledger.json)
for all **100 completed assignments**, reconciled against the actual unique spawned
task names and final report hashes in the [completion receipt](completion-receipt.json).
Supplemental follow-ups reused these agents and are not extra agents.

The [post-replay provider observation](reports/a087-after-replay.md) spans
**2026-11-26 11:02:26–11:02:45 UTC**. It found 15 attempt-1 workflows for that
exact revision: **fourteen successful and main CI queued**. These are dated,
non-atomic observations. The earlier [A092 observation](reports/a092.md) is
retained unchanged as history.

| Workflow | Exact run / attempt | Observed state |
| --- | --- | --- |
| Main CI | `45796538630` / `1` | Queued; only `change-impact` and `plan` jobs materialized, both queued. No final matrix count or aggregate `Gate` result. |
| Project Governance | `45796540254` / `1` | Completed/success; job `139828665982` and all 13 steps succeeded. Artifact `15109565376` is retained unchanged and its independent replay passed. |

**Next bounded action:** refresh the exact main CI identity and retain complete
paginated observations before claiming its outcome. Main CI must complete its
selected graph and strict aggregate `Gate`. Preserve failed or incomplete attempts.
A later governance attempt or source revision requires fresh identity selection.

The [current governance packet](governance-current/README.md) retains the original
ZIP, authenticated before/after provider responses, preselected size/digest,
exact bounded invocation, resource checks and unchanged source/original identities.
The [independent replay](reports/a088-current-replay.md) ran once at
**10:59:00–10:59:10 UTC** and reconciled **5,575 tests, 39,419 successful subtests
and 56,144 events** from the recorded execution. It ran no test bodies.

For any successor acquisition, follow [A084's procedure](reports/a084.md) and
the [governance-original guide](../../governance-artifact-replay.md): use a clean,
complete trusted source, select size/digest independently before download,
retain unchanged originals outside that source, satisfy the storage reserve,
and bind before/after identities and authenticated provider reobservations.
The A084 connector route establishes local independent replay with separate
provider observations; it does not establish full hosted admission. Preserve
the emitted `provider_authenticated:false` and all other acceptance flags.

## Native prerequisites and frozen scope

The qualified warm experiment remains **not run**. Follow the
[native handoff](../../p06-qualified-warm-handoff.md),
[hosted operator guide](../../p06-hosted-warm-guide.md) and
[execution/replay runbook](../p06-qualified-warm/runbook.md). Before dispatch,
require the selected published revision's own strict qualification and original
replay, exact private control delivery, the intended public age recipient with
its private identity retained outside Actions, complete source/dependency inputs,
and fresh actual-runner admission at **15 GiB free disk / 4 GiB available memory**.
Current local admission is not established; effective allocation cannot be
inferred from host memory alone. Keep the separate dependency/four-process
prerequisites and every existing build, process, RSS and log limit.

Preserve all **69 measurement sources, 21 dependency descriptors**, proofs,
goldens, thresholds and the **24-process, 792-launch, 25,344-word** population.
Run one fresh admitted attempt, retain complete or explicitly partial originals
through the prescribed encrypted delivery, and independently replay complete
native evidence before the frozen performance decision. P06/P06-T01 remain
`in_progress`; P06-A02/A03 remain open and P01 vendor integration remains blocked.

## Open inherited trace-ownership F2

[A071](reports/a071.md) and independent [A073](reports/a073.md) establish a
static pending-`instr_trace_t` ownership gap after the direct-Processor
bounded-RAM first-fetch exception. It is inherited, open and outside the host
repairs; runtime leakage magnitude and a repair have not been demonstrated.
Follow the [scope assessment](reports/a074.md) and existing
[A076 diagnostic/repair plan](reports/a076.md): establish an allocation-generation
ownership oracle, retain eight fault-to-fresh-success pairs and 16 healthy
controls, prove parent sensitivity, then review complete ownership and teardown
ordering. A native repair needs coordinated independent review and a successor
source/proof contract before adoption. Do not repin frozen inputs to admit it.

## Preserve and publish

Keep originals, partial attempts, reports, raw observations, hashes, recovery
refs and the source repository's common Git objects until verified delivery;
the audit worktree depends on those objects ([A080](reports/a080.md)). Do not
publish private control/plaintext dependency archives, credentials, signed URLs,
private identities or connector identifiers.

[A088](reports/a088.md) checked the audit boundary at **2026-11-26 10:37:19 UTC**:
all original objects remained unchanged apart from the expressly permitted
native-handoff clarification. Recheck the final diff after integration. Keep
additions within this evidence packet and preserve production/test/workflow,
dependency, proof, golden, acceptance, roadmap and protected-SVG identities.
Source changes target **baabi-boo/AI-GPU, `master`** with fresh expected-head
non-force updates. This audit instead publishes on the separate branch above,
with `81d7a35` as its parent and code/CI subject. Preserve concurrent work and all
local authoring refs; require exact local/API tree equality, an unused branch
(or a valid non-force update of an existing owned history), and remote readback. Update dated CI observations,
the actual completion ledger and the final publication receipt from retained
evidence; do not attribute code qualification or phase acceptance to the audit
commit.
