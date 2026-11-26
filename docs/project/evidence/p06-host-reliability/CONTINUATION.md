# Continued host reliability review

## Delivery and scope

Published code revision: `81d7a35c641f3a969c23c8e604f7468a4d88644a`, tree
`9da606f541ecb85248ef00995e8288c1266eea88`, with parent
`4c9c612ba17e8b69b29083ad9743fe0e1710f0bc`. The parent repaired cached checkout
metadata, required-job completion semantics and two bundle-reader descriptor
leaks. The follow-up repaired encrypted-reader and governance-directory ownership
and preservation of primary errors. The [publication review](reports/a055.md)
matched every remote tree entry and selected actual source/test bytes.

This documentation branch retains the same production code, the continuing
review record and a clarified [native handoff](../../p06-qualified-warm-handoff.md).
It does not replace the published code revision as the CI/replay subject.

## Review ledger

The [continuation ledger](continuation-ledger.json) binds **all 100 completed
assignments** from 100 distinct spawned agents, A001–A100. At most three child
workers ran concurrently. Supplemental provider and replay work reused those
agents and is not counted as additional agents. The [completion receipt](completion-receipt.json)
records the final report-hash and task-name reconciliation.
The initial fourteen-assignment [ledger](review-ledger.json) keeps its original
historical scope. Findings, independent assessments and remaining work are
recorded in [finding dispositions](finding-dispositions.json). Reports describe
actual source review, implementation, execution or observation; source inspection
is not a test run.

## Verification already retained

| Scope | Completed development evidence |
| --- | --- |
| Initial host and CI repair | 131 tests, 1,059 subtests; real cache topology and old-source controls |
| Encrypted-reader repair | 73 tests, 211 subtests; eight new methods and 51 old-source assertion failures |
| Governance directory repair | 40 tests; seven new methods, five failing old-source controls and a passing normal control |
| Canonical discovery | 5,575 unique IDs; 28 additions from the session baseline, no removed IDs |
| Preservation | 69 measurement files, 21 dependency descriptors, old proofs/acceptances/goldens and protected SVG |

Discovery ran no test bodies. The focused receipts bind their source bytes and
precede publication; their scopes overlap and their counts must not be summed.
Complete strict governance and the later original replay are recorded below. The
[two observed cached test cells](reports/a066.md) at the earlier `4c9c612` revision
show successful recursive checkout/cache restoration/cleanup without the old
fatal-128 markers. Their results are not attributed to changed source.

## Open native ownership finding

[A071](reports/a071.md) and independent [A073](reports/a073.md) establish a
source-level F2 ownership gap on the direct-Processor bounded-RAM first-fetch
exception. A pending trace can lose its owner without destruction/deallocation.
Intentional pool retention is distinct from this unreclaimed object/vector
storage. No runtime leakage magnitude or new native execution was measured.
The implicated code is unchanged from the starting baseline. Existing joined
teardown, accounting and fresh-context observations retain their narrower scope.

The [scope assessment](reports/a074.md) and [verification plan](reports/a076.md)
require coordinated ownership coverage, a successor reviewed source/proof pin
and corresponding controls before native repair publication. The finding remains
open. Frozen measurement inputs were not changed to work around it.

## Current provider observation

The [post-replay observation](reports/a087-after-replay.md) during
**2026-11-26 11:02:26–11:02:45 UTC** found 15 attempt-1 workflows for the
published revision: **fourteen successful and main CI still queued**. Main CI
`45796538630` has only the queued `change-impact` and `plan` jobs, with no
executed steps or final aggregate `Gate` result. Earlier [A092](reports/a092.md)
and [raw responses](a092-provider/) remain historical observations.

Project Governance **`45796540254`, attempt 1**, completed successfully. Its
single job and all thirteen steps succeeded. The selected original, artifact
**`15109565376`**, is **1,414,721 bytes**, SHA-256
`5596e541ebf8eb272d813ee353b8e5eb998a641aef7b675f5b014cfd8e2ef045`.
Provider size and digest were selected before download; independent terminal
selection and post-replay observations agree. The unchanged original is retained
in the [current governance packet](governance-current/README.md).

The [single independent replay](reports/a088-current-replay.md) passed at
**10:59:00–10:59:10 UTC**, reconciling **5,575 canonical tests, 39,419 successful
subtests and 56,144 ordered events** from the original execution. Trusted source,
reader/runtime and original identities were unchanged. Replay ran no test bodies;
these counts describe the recorded execution. The [receipt](governance-current/replay.json)
keeps `provider_authenticated:false` and all native, phase and performance
acceptance flags false. Authenticated provider observations are separate evidence;
this connector-assisted procedure does not establish full hosted admission.

The native warm experiment remains unstarted. P06-A02/A03 and P01 vendor
integration remain open. Exact private control delivery, the intended public age
recipient and an admitted **15 GiB disk / 4 GiB memory** runner remain unavailable.
Any native attempt must use the selected source's own qualification and the
prescribed complete admission procedure. No phase, performance or physical-hardware
acceptance is claimed.

## Publication normalization

Retained report hashes are in the ledger. Terminal blank-line changes, the two
A078 publication-relative link corrections and omission of account-specific
connector locators are explicitly recorded with original hashes. A078's exact
original is retained as inert [text](reports/originals/a078.txt). Exact provider
response bodies are unchanged. A079 originally captured ten files; its published
packet has eleven after adding the metadata [normalization record](a079-provider/publication-normalization.json).
Locally authored request metadata omits the account connector locator.
