# Host preparation and CI completion evidence

This packet accompanies the [host reliability audit](../../p06-host-reliability-audit.md).
It covers source changes and host checks, not native warm-experiment execution,
counter qualification, performance acceptance or phase completion.

## Current continuation

The [continued review](CONTINUATION.md), [100-assignment ledger](continuation-ledger.json)
and [resumption handoff](RESUME.md) retain the completed continuation. All **100
distinct requested agents** completed their assignments in bounded waves. The
initial fourteen-assignment ledger below remains its unchanged historical subset.

Published source **`81d7a35c641f3a969c23c8e604f7468a4d88644a`** passed Project
Governance run **`45796540254`, attempt 1**. Its independently verified original
and [replay receipt](governance-current/README.md) reconcile **5,575 tests, 39,419
successful subtests and 56,144 events**. These are recorded original execution
counts; local replay ran no test bodies. At the retained post-replay observation,
**14 of 15 workflows had succeeded and main CI remained queued**. This separate
audit branch preserves the code revision as the qualification subject.

The [inherited native trace-ownership finding](CONTINUATION.md#open-native-ownership-finding)
remains open. Native warm execution and phase/performance acceptance remain
unstarted and unclaimed.

## Retained development result

The single [combined focused invocation](a013-validation/receipt.json) passed
**131 unique tests and 1,059 successful subtests**, with zero failures, errors
or skips. Its [executed IDs](a013-validation/focused-result.json),
[source hashes](a013-validation/source-before.json),
[test log](a013-validation/focused-tests.log) and [counting harness](a013-run.py)
are retained. All twelve selected source/test files remained unchanged across
the run. Project and baseline-packet metadata checks and `git diff --check`
also passed. These results cover the base plus the identified working changes.

The [initial review ledger](review-ledger.json) records fourteen completed
assignments, not the requested total of one hundred. It binds each retained
report by SHA-256. The [checkout review](reports/a009.md),
[bundle ownership review](reports/a010.md), [CI-gate review](reports/a011.md)
and [frozen-input review](reports/a012.md) found no blocking issue in their
specified scopes. The [documentation review](reports/a014.md) required these
reports and receipts to be linked before publication; this packet supplies them.

The [descriptor negative-control log](reports/a007-baseline-tests.log.gz) retains
the original failures in lossless gzip storage; its [identity record](reports/a007-baseline-tests.identity.json) binds the unchanged decompressed bytes. The [CI cancellation controls](controls/a008/) and
[complete gate truth table](a005/verify.py) retain independent checks of the
aggregate gate. The real cache-topology reproduction is also an executable
regression in `ci/project/test_ci_submodule_checkout.py`.

## Encryption-reader follow-up

A continuing independent review found a matching raw-descriptor leak in the
encrypted-evidence source reader and a cleanup failure that could hide the
original read error. The [follow-up packet](encrypt-reader-ownership/README.md)
retains its original source, reproductions, focused regressions and independent
review. This later repair has its own source identities and does not extend the
initial 131-test result to changed code.

The [governance directory follow-up](governance-directory-ownership/README.md)
also repairs a reproduced descriptor leak during the archive reader's initial
directory identity check. Its source-bound focused checks and independent
review are retained separately from the encryption-reader result.

## Reproduced failures

- Restoring cached submodule gitfiles into an ordinary checkout leaves their
  `.git/modules` targets absent. Recursive Git traversal fails with exit 128;
  recursive checkout before restoration passes the equivalent check.
- The previous CI aggregate accepts cancelled/skipped mandatory work because it
  rejects only `failure`. The replacement accepts exactly the complete-run and
  deliberate-empty-plan states and rejects all other tested combinations.
- Real CPython audit-hook rejection of `os.fdopen` leaves one raw descriptor per
  failed call in each original bundle reader. The repaired readers close their
  descriptors on those same failures and preserve successful bounded reads.

## Evidence boundaries

Independent agent reports and the delivery ledger identify actual completed
assignments; a requested agent count is not a completion claim. Test records
identify their source scope, invocation and result. Focused tests and source
discovery do not replace one complete strict-governance invocation.

The base `30b2e8ca69fba47646392c0cf6650cbb75155843` had all 15 workflows and 43
main-CI jobs passing when checked. That result qualifies the base only. A later
publication needs its own CI result and strict original replay before native
admission.

All 69 frozen measurement sources, dependency descriptors, proofs, historical
acceptance records, resource floors and performance predicates are preserved.
The native warm experiment remains unstarted. The full population stays at
24 processes, 792 launches and 25,344 checked FP32 words. Private control
delivery, the intended public age recipient and adequate native-run capacity
remain prerequisites.
