# Governance artifact replay evidence

This packet preserves the unchanged historical governance original and its
development replay used to review independent ZIP replay and hosted admission.
It contains governance evidence, separate from private native prerequisite
archives. The [audit](../../p06-governance-replay-audit.md) records observed
verification, review and publication outcomes; the
[operator guide](../../governance-artifact-replay.md) gives the reproducible
command and the [implemented contract](../../../designs/governance_artifact_replay_v1.md)
defines the reader's trust boundary.

## Retained base original

| Identity | Retained value |
| --- | --- |
| Repository | `baabi-boo/AI-GPU` |
| Exact source revision | `f3123513bb5bc5fa1c409bf0e7366d2f47c2d85b` |
| Provider run / attempt | [45625012254](https://github.com/baabi-boo/AI-GPU/actions/runs/45625012254) / `1` |
| Provider artifact ID | `15032214051` |
| Original | [run-45625012254-attempt1.zip](originals/run-45625012254-attempt1.zip) |
| Original bytes | 1,334,981 |
| Original SHA-256 | `a7df58f9462692e9994a8a9f2a15a8c2cd4f59301272c0d446b01353620059a0` |
| Provenance metadata | [base-original.json](base-original.json) |
| Development replay receipt | [base-replay.json](base-replay.json) |
| Development reader identities | [base-reader-source.json](base-reader-source.json) |
| Recorded canonical tests / successful subtests / events | 5,167 / 37,544 / 53,045 |
| Recorded execution duration | 3,763.184129 seconds |

The ZIP is retained byte for byte, without extraction, reconstruction or
repacking. The development reader successfully replayed it against a separate
checkout of the exact base, including independent collection of all 5,167
ordered IDs with digest
`92fe769e153a9561a5ef375bdab45e41c0d99f4d9cd745b5ffdd159e8e5b6336`.
The linked receipt reconciles the recorded counts and source identity. This
used draft reader source and does not qualify the changed reader's final
published revision. Keep the reader source identity alongside the result when
recording reproducible review. Do not execute archive members or open their
recorded producer paths.

## Focused development integration

[Development validation](development-validation.json) records the selected
15-module integration run under the checked CPython 3.12.14 environment:
261 tests passed with zero failures, errors or skips. The
[unchanged test log](development-tests.log) and exact production/test hashes
are retained. All tested files stayed stable through that invocation. Its
local checkpoint is unpublished context; the file hashes identify the tested
bytes. This selected run is separate from complete strict governance.

The subsequent optional-receipt ownership correction has its own
[28-test validation record](receipt-output-validation.json) and
[unchanged log](receipt-output-tests.log), with the corrected source hashes.
Its replacement-preservation regression failed before the correction and
passed afterward. These focused observations retain their separate scopes.

[Metadata API validation](metadata-api-validation.json) records 101 affected
checks for isolated transport and hosted consumers, including actual offline
worker timeout and reaping. [Record freshness validation](records-freshness-validation.json)
and its [log](records-freshness-tests.log) record 30 receipt checks after the
live-input path correction. Existing test populations overlap across these
focused runs; their counts are not an aggregate qualification result.

[Workflow contract validation](workflow-validation.json) records the 12
existing checks after the expected trigger list gained the new design path.
Every prior trigger and test ID remains. The initial failing push/PR assertions
and the corrected result are retained in assignment 49's review report.

## Population and independent review

The [actual completion ledger](agent-ledger.md), [machine-readable index](agent-ledger.json)
and [original report archive](agent-reports.zip) record all 60 completed distinct
assignments. Each agent started with a separate fresh context; at most three
workers ran alongside the integrator. The context provenance is the integrator's
observed tool lifecycle, while every report's retained bytes are independently
checkable against the index. Follow-ups and retries add no distinct agents.

The [canonical population record](canonical-population.json) preserves the
independent collection at the recorded development checkpoint: 5,406 IDs,
including 239 additions and all 5,167 base IDs in their original relative
order. Its digest is
`b83da928ac9a00b1cb87c0b1d2b2f21d68f98ee56a57ae17a8570a6e44c469d5`.
This is collection-only evidence; no test bodies were invoked. The checkpoint
source projection is historical and must not be substituted for the published
revision's own source projection or execution result.

The [findings closure record](review-findings.json) identifies all nine corrected
findings and the original reviewer/confirmation reports. Report source hashes
and observed results retain their individual scopes. Neither the number of
reviews nor closure of these findings establishes complete strict governance
or native acceptance.

## Scope and continuation

Local replay establishes internal consistency and agreement with independently
collected canonical IDs from a trusted exact source checkout. Collection
imports that source in a bounded child without running test bodies. It does
not import archive code, reproduce recorded execution, freshly qualify the
original tool binaries or authenticate the provider. Hosted admission adds the
separate authenticated repository/revision/run/attempt/artifact joins and
reobserves provider, source and original identity before proceeding.

This historical base cannot qualify later changes. Keep focused validation,
historical-original replay, provider-bound admission and the final published
revision's complete strict governance result separately identified in the
audit. Add result references only after their records exist; do not treat this
index or a successful download as a replay or final-source qualification
receipt.

No fresh native experiment or acceptance closure is claimed. P06's frozen
**24-process, 792-launch, 25,344-word** experiment remains unstarted, with its
**15 GiB free-disk and 4 GiB available-memory** admission unchanged. P06-A02/A03
remain open, and P01's separate vendor-integration blocker remains in force.
