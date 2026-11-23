# Native managed counter lifetime observations

This continuation implements the next bounded task identified at
`6130a2f7424932a6f3b7377ef8ae4816da2b304f`. The
[development audit](development-audit.md) explains the missing pre-reset
observation and the selected scope. The
[versioned contract](../../../designs/managed_counter_lifetime_v1.md) defines
the new opt-in transcript; the old preflight contract and historical archive
reader retain their original interpretation.

## Implementation

The production `Processor` now exposes a const value observation of its actual
pending-read balance. The managed observer records 33 run boundary pairs,
pending balance around every MPM and output-flush read, four snapshots,
construction and actual destruction. It rejects an outstanding read before
the real run can reset that balance, and checks an exact reset increment.

The new transcript reader verifies the complete original v1 prefix first,
then checks the additional observations and their exact chronological joins.
A separate native accessor probe requires actual nonzero request/reply activity,
read-only observations and successful nonzero legacy `gp` values. Its always-zero
control is compiled into a separate probe executable and must fail for the
specific missing-observation reason.

## Verification state

The implementation is undergoing final integration and independent review.
Compiled host controls, transcript rejection tests, mocked orchestration and
historical archive replay have executed in their separately recorded scopes.
Fresh native lifetime execution and the full governance result are pending at
this implementation checkpoint. Neither is inferred from the host controls.

The [dedicated workflow](../../../../.github/workflows/p06-native-lifetime.yml)
retains the unchanged four-process FP16/BF16 by allocation-policy matrix:
132 launches and 4,224 checked words. Its separate accessor probe follows that
matrix and is excluded from those counts. Failure evidence is uploaded even
when a required command fails. Native execution uses the existing 15 GiB disk,
4 GiB memory, two build-job and one simulation-worker limits.

## Qualification boundary

All seven qualification/readiness/warm/acceptance flags remain false. All three
prior unresolved obligations remain explicit: full source/binary-bound lifetime
of the 40 backing components, fresh dependency compilation through the actual
loaded products, and independent complete counter qualification.

The observations do not establish an absolute no-wrap bound, a warm speedup,
P06-A02/A03 acceptance, vendor XRT hardware emulation or physical hardware
performance. P06 and P06-T01 remain `in_progress`. The next prerequisite after
the new native witness is validated is the separate dependency compilation and
loaded-product provenance chain.
