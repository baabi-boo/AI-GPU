# P06 governance artifact admission audit

## Audited starting point

The audited starting revision is `f3123513bb5bc5fa1c409bf0e7366d2f47c2d85b`.
The canonical roadmap records P00 and P02–P05 complete at their documented
scopes, P01 blocked on vendor integration, and P06 in progress. P06-A01 is
accepted; P06-A02/A03 remain open.

The next native action is the unchanged qualified warm experiment: 24
processes, 792 launches and 25,344 checked FP32 words. It requires private
control delivery, an explicit public age recipient, exact source/tool/input
binding, and unchanged native resource admission. This continuation does not
change that experiment or any acceptance record.

## Concrete finding

The starting `p06_qualified_warm_hosted.verify_governance` checks provider
workflow, run, attempt, job and step success for the selected source revision.
It explicitly returns `independent_packet_replay: false`. A successful upload
step does not reconcile the retained discovery manifest, ordered events,
source/environment receipts or log lengths. The operator runbook requires
those originals to be reviewed, leaving a manual gap before native dispatch.

The bounded development task is an independent governance-original reader and
its integration into that launch gate. It must reject incomplete, inconsistent,
replaced or differently scoped evidence; compare canonical discovery to an
explicit trusted checkout; and bind the downloaded ZIP to the exact provider
artifact, source, run and attempt. Retained archive bytes remain inert. Trusted
source collection imports only the explicitly selected checkout and runs no
test bodies.

## Starting evidence

The [base governance run](https://github.com/baabi-boo/AI-GPU/actions/runs/45625012254)
completed successfully on attempt 1. Its artifact ID is `15032214051`, with
1,334,981 bytes and SHA-256
`a7df58f9462692e9994a8a9f2a15a8c2cd4f59301272c0d446b01353620059a0`.
The original records 5,167 tests, 37,544 successful subtests and 53,045 events
in 3,763.184129 seconds, with zero failures, errors or skips. Independent
collection from a separate checkout of that exact revision matches all
ordered IDs and digest
`92fe769e153a9561a5ef375bdab45e41c0d99f4d9cd745b5ffdd159e8e5b6336`.
These observations qualify the starting source only.

All 15 observed push workflows at the starting revision completed successfully.
The project structure and published baseline consistency checks also pass
locally. Neither establishes native experiment execution or hardware readiness.

## Resource observation

The initial disk screen passed, but a later independent read-only observation
found 11.11 GiB free, below the unchanged 15 GiB reserve. The checked capacity
observer reported `observation_complete=false` and
`mapping:missing_or_ambiguous_v2_mount`. Native launch admission is therefore
not established here. No private control URL or recipient has been supplied
to this session. Provider secret configuration was not inspected.

## Implemented next step

Hosted admission now requires the original governance ZIP for the exact selected
repository, source revision, successful run and current attempt. The provider
reader checks the complete artifact listing, exact name, numeric identities,
expiry, byte count and SHA-256, then reobserves provider metadata. Its isolated
bounded download sends authentication only to GitHub's API and publishes a
verified anonymous staging inode without replacing or deleting another file.

The independent replay reader checks the entire supported ZIP container, all
member identities, the exact twelve-member governance layout, strict JSON,
ordered test and subtest lifetimes, all derived execution counts, immutable
source/interpreter/environment receipts and matching logs. It independently
binds a trusted exact Git checkout and collects its complete ordered canonical
population in a bounded child without invoking test bodies. Retained archive
members remain data; explicitly selected source imports are a separate trust
boundary.

The hosted gate then reobserves source, the original identity and the same
workflow/run/attempt/jobs before proceeding. It preserves the ZIP and separate
provider/replay receipts in the existing private attempt envelope. The local
CLI exposes the same replay without claiming provider authentication, native
execution, performance acceptance or phase closure. The
[operator guide](governance-artifact-replay.md) and
[implemented contract](../designs/governance_artifact_replay_v1.md) define the
required inputs, bounds and failure behavior.

No measured kernel, native runtime, golden data, hardware configuration or
acceptance record changes in this continuation. The governance workflow gains
only the new design-document path in its existing push and pull-request path
filters, so future contract edits trigger the same qualification workflow.

## Review findings and corrections

Independent review identified nine concrete defects or inherited gaps while
implementing and integrating this admission path:

| Finding | Correction | Relevant regression |
| --- | --- | --- |
| ZIP64 end metadata could replace prevalidated ordinary ZIP bounds inside Python's parser. | Reject unsupported ZIP64 metadata before constructing the parser. | Tiny unsupported container is rejected before parser allocation. |
| One requested executable path could claim different resolved files and hashes. | Reconcile identity across all records sharing a requested path. | Conflicting GCC/CMake requested identity is rejected. |
| A requested executable path could disagree with another tool's canonical resolved path. | Reconcile overlapping requested and resolved path maps. | Cross-role path contradiction is rejected. |
| Ownership-check-then-unlink cleanup could delete a concurrent replacement pathname. | Use anonymous staging and eliminate name-based deletion in the provider helper. | Replacement survives failed publication; admission fails. |
| A failed buffered CLI write could be retried at shutdown, producing a raw diagnostic and exit 120. | Close failed streams before returning the documented sanitized failure. | Real CLI invocation with a full output device returns exit 1 without a shutdown traceback. |
| Optional CLI receipt cleanup could delete a concurrent replacement after checking ownership. | Use anonymous receipt staging and exclusive descriptor publication without pathname deletion. | Write failure and post-publication replacement preserve unrelated bytes. |
| The inherited metadata client's socket timeout did not bound DNS resolution or total transfer time. | Supervise each metadata request with a separate execution deadline and bounded reap. | An offline blocked-resolver child is killed and reaped within the configured bounds. |
| Recorded fresh run output could overlap the prepared environment and live input files. | Reconcile output paths against the live receipt and tool identities. | Conflicting paths reject; fresh descendants and disposable preparation paths remain supported. |
| The new workflow design trigger was missing from the exact expected-path contract. | Add that one expected path while preserving every prior path and existing test ID. | All 12 existing workflow contract checks pass. |

All corrections preserve legitimate aliases and the supported historical
original. Targeted controls also cover descriptor/local-header consistency,
event population exhaustion and linked-worktree/source replacement behavior.
The change is manually treated as R3 because it adds mandatory launch
admission, even though the unchanged base classifier labels the initial
committed integration R2 through its CI-enforcement path rule. Reviewers who
did not author the components inspect the enforcement changes and corrections.

## First published qualification and procfs correction

The first published revision, `00a6c275af918b51a36dbbdb454e9b480e25bb98`,
received its own complete strict invocation in
[run 45671761974, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45671761974).
It **failed** with one error after all 5,406 canonical tests ran. The
[failed original and accounting](evidence/p06-governance-replay/first-publication-failure.json)
preserve 5,405 successful parent outcomes, one error, 38,492 successful subtests
and 54,710 events. Execution accounting reports 3,157.916707 seconds; the
unittest trailer reports 3,157.906 seconds. Source, interpreter and environment
records remained stable. None of these counts establishes strict qualification.

The error was an inherited race in
`test_command_timeout_kills_its_process_group_and_retains_output`. After the
test verified the timeout, the parent's `-SIGKILL` result and retained child PID,
the descendant disappeared between opening and reading `/proc/<pid>/stat`.
Linux reported `ProcessLookupError` rather than the already-handled
`FileNotFoundError`. The production timeout implementation and this test were
both byte-identical to the audited starting revision.

The correction recognizes those two specific disappearance errors at the
existing procfs read. Every timeout/output assertion and the rejection of
readable live process states remains. It adds no sleep, retry, skip, expected
failure, production behavior change or gate exception. All existing canonical
test IDs remain. This is a tenth finding discovered by actual published CI,
separate from the nine findings closed in the original 60-report snapshot.

The [before](evidence/p06-governance-replay/procfs-before-controls.json) and
[after](evidence/p06-governance-replay/procfs-after-controls.json) controls each
execute the real process-group timeout seven times, with tightly scoped final
procfs observations. The forced `ProcessLookupError` fails before and passes
afterward; live-state and unrelated permission-error controls still reject.
Actual procfs, absent-record and dead/zombie controls pass. The
[independent follow-up review](evidence/p06-governance-replay/procfs-review-56.md)
records the exact corrected source and preserved obligations. This follow-up
uses an existing agent context and adds no agent to the count of 60.

The [documented replay CLI rejection](evidence/p06-governance-replay/failed-original-replay.json)
rejects the actual failed original with exit 1, sanitized stderr, no success
stdout and no receipt. The failed original is retained byte for byte. The
corrected source still requires a fresh complete strict invocation and its own
successful original replay; retrying the old revision is not its qualification.

## Delivery and verification

The [historical evidence packet](evidence/p06-governance-replay/README.md)
retains the unchanged base original, its scoped replay and the development
reader identities. The recorded development reader reconciled its 5,167 canonical
tests, 37,544 successful subtests and 53,045 events against an independent base
checkout. These are historical execution observations, not freshly executed
tests in the replay process.

Implementation and independent review are complete for this bounded tooling
change. The [actual completion ledger](evidence/p06-governance-replay/agent-ledger.md)
records all 60 distinct assignments, each started in a separate fresh context,
with at most three workers alongside the integrator. Its machine-readable index
binds every completed assignment to the unchanged report bytes in the retained
archive. Follow-up turns and a report retry do not increase the distinct-agent
count. The [findings record](evidence/p06-governance-replay/review-findings.json)
links the original nine corrected findings to their independent confirmations.
The additional published-CI finding and its follow-up review are recorded above.

Focused development results retain their separate source identities: 261
integration checks, followed by scoped 28-test receipt-output, 101-test metadata
and hosted-consumer, 30-test receipt-record and 12-test workflow-contract checks.
These populations overlap and are not an aggregate qualification count. The
[collection record](evidence/p06-governance-replay/canonical-population.json)
preserves 5,406 ordered candidate IDs: 239 additions, zero removals, and all
5,167 base IDs in their original relative order. Collection runs no test bodies.

The published revision still requires its own complete, uninterrupted strict
governance invocation, exact provider original and source-bound replay. Its
Actions result is recorded separately after publication; the historical base,
focused checks and review archive cannot qualify later source. Direct live
API-to-storage admission and the separate private native workflow are not
established by the offline transport controls or connector downloads. No
performance, phase closure or physical hardware claim is made by this tooling
continuation. The next native action remains one admitted frozen qualified warm
attempt after the private inputs and unchanged runner prerequisites are verified.
