# Archive ownership continuation evidence

This packet accompanies the [audit](../../p06-archive-ownership-audit.md).
Its scope is source review, host fault checks and evidence-reader validation.
It establishes no native execution, performance improvement or phase acceptance.

The continuation began at
`81d7a35c641f3a969c23c8e604f7468a4d88644a`. Actual independent assignments,
their report identities and completion states are recorded in the
[agent ledger](agent-ledger.json) as the work proceeds;
the requested count of 100 is not itself a completion claim.

## Verified checkpoint

The [combined focused result](validation/focused-result.json) passed **134
unique tests and 436 successful subtests**, with zero failures, errors or skips.
All **681 observed source files** remained identical across the invocation;
the [before](validation/source-before.json) and
[after](validation/source-after.json) inventories bind those bytes. The
[execution log](validation/focused-tests.log),
[executed IDs](validation/executed-ids.json) and
[invocation harness](validation/focused_validation.py) are retained.
These are host development checks, not a complete strict-governance result.

[Canonical discovery](validation/discovery-comparison.json) finds **5,594
unique IDs**: 19 additions, no removals, and unchanged relative order for all
5,575 base IDs. Discovery executes no test bodies. The
[preservation record](validation/preserved-inputs.json) verifies the frozen 69
measurement files and unchanged 21 dependency descriptors; it does not claim
fresh observation of uninitialized external dependency bytes.

The [packer review](reports/a010.md),
[governance-reader review](reports/a012.md) and
[workspace test review](reports/a014.md) independently cover the changed code
and regressions. The [original packer controls](controls/a005/review-results.json)
and [governance controls](controls/a009/results.json) retain baseline failures.
The governance baseline has three semantic error-masking reproductions; its
additional raw-close-instrumentation test failure is not another baseline bug.

## Original governance artifact

The selected [base original](base-governance/original.zip),
[provider observation](base-governance/provider.json) and
[independent replay](base-governance/replay.json) reconcile **5,575 canonical
tests, 39,419 successful subtests and 56,144 events** at the exact starting
revision. Its SHA-256 is
`5596e541ebf8eb272d813ee353b8e5eb998a641aef7b675f5b014cfd8e2ef045`.
This historical result does not qualify the changed revision. The provider
snapshot shows 14 successful workflows with main CI still queued.

## Scope and retained controls

The private packer's input and output stream-construction failures were
reproduced with real CPython audit hooks. Governance reader cleanup failures
were reproduced using real descriptors, consuming close faults and recycled
descriptor witnesses. Regressions preserve primary failures, verify remaining
cleanup, and ensure an otherwise successful call cannot hide a cleanup error.
Successful output, borrowed-directory ownership and partial-output retention
remain covered.

The [workspace addition](reports/a011.md) covers only the previously missing post-create resident
address-query faults. The trace-ownership follow-up combines source review with
a [reduced host probe](native-trace-investigation/probe.cpp) and
[recorded results](native-trace-investigation/results.json); it is not evidence that native Core teardown was executed
or repaired. Frozen source/proof bytes and all acceptance gates are preserved.

Focused logs, original-failure controls, independent review reports, source
inventories and delivery observations are retained alongside this index. Final
validation and publication records identify their exact tested source scope.
Historical governance replay is distinct from execution of the changed revision.
