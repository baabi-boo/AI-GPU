# Qualified warm launch-readiness evidence

This packet accompanies the [development audit](../../p06-launch-readiness-audit.md).
It retains scoped evidence for production launch accounting, cooperative
cancellation, final observations/counts and fresh capacity admission. It does
not establish execution of the frozen warm population or phase acceptance.

## Audited base

- Revision: `e3ad6bd1e2b002aa234d57cd8a02519cec915830`.
- [Provider observation](validation/base-governance-provider.json): all 15
  base workflows passed; exact governance artifact and digest are recorded.
- [Independent original replay](validation/base-governance-replay.json):
  5,406 canonical tests, 38,492 successful subtests and 54,710 events.
- Replay imports the explicitly trusted source for discovery; it runs no test
  bodies and no retained archive code.

## Work and review

Actual independent assignments are retained under [agents](agents/) and bound
by the [assignment ledger](agent-ledger.json). Numbered task agents receive fresh
contexts, with at most three workers alongside the integrating root. The ledger
separately discloses A31's additional read-only support reviewer; that reviewer
is not counted as a numbered assignment. Root owns integration and publication.

Findings
distinguish known unstarted commands, observed launches and unresolved process
dispositions. Capacity controls preserve the existing predicate and explicitly
retain the limits of point-in-time observations.

The production changes are confined to seven orchestration files. Independent
reviews cover each change and its interactions with supervisors, process cleanup,
partial retention, historical readers and protected experiment inputs. The eleven
new regression modules contribute 65 methods; no existing test is removed or
rewritten. The CI contract documentation now describes the existing strict
runner and 90-minute total job budget accurately; the workflow is unchanged.

## Development verification

| Evidence | Observed result | Scope |
| --- | --- | --- |
| [Final integrated receipt](validation/integration-final.json) and [log](validation/integration-final.log) | 184 unique tests passed; zero failures, errors, skips or loader errors; 152.862583 seconds; source identities stable | All seven final production identities and selected tests; development verification only |
| [Earlier CLI integration receipt](validation/signal-setup-focused.json) and [log](validation/signal-setup-focused.log) | 29 unique tests passed; zero failures, errors, skips or loader errors; 15.446788 seconds; source identities stable | After the handler-setup correction, before the managed-family CLI correction |
| [Integrated focused receipt](validation/focused.json) and [log](validation/focused.log) | 173 unique tests passed; zero failures, errors, skips or loader errors; 156.502231 seconds; source identities stable | Integrated implementation before the final handler-setup correction |
| [Earlier focused receipt](validation/focused-before-final-counts.json) and [log](validation/focused-before-final-counts.log) | 167 tests passed | Earlier managed-runner identity, before the additional final-count fix |
| [Release canonical discovery](validation/test-discovery-release.json) | 5,471 unique IDs: all 5,406 baseline IDs plus 65 new methods | Final seven production identities and eleven new modules; collection only, no test bodies executed |
| [Intermediate canonical discovery](validation/test-discovery-final.json) | 5,462 unique IDs | After the two handler-setup tests, before the nine managed CLI tests; historical collection only |
| [Earlier canonical discovery](validation/test-discovery.json) | 5,460 unique IDs: all 5,406 baseline IDs plus 54 new methods | Before the two handler-setup tests; collection only, no test bodies executed |
| [A31 before](validation/a31-final-counts-before.log) and [after](validation/a31-final-counts-after.log) | Identical six methods: eight failures before, six passing methods after | Reproduced final-count interruption defect and bounded recovery; synthetic native observations |
| [A34 independent control](validation/a34-final-counts-control.log) | Partial and zero warm controls passed, including interruption inside aggregation | Exact counts, unchanged observations/commands, prior failure reason and false claims |
| [A43 handler-setup controls](validation/a43-signal-setup/run-summary.json) | Identical two methods fail before and pass after the correction | Real SIGTERM during installation; no command body entered; exact previous handler restored |
| [A54 managed CLI controls](validation/a54-managed-cli/after.json) and [independent A56 control](validation/a56-independent-control.json) | Identical nine methods: 14 assertion failures before, nine passes after; independent four-route control passed | Actual managed CLI SIGTERM closeout and all four entry wrappers; synthetic native observations |
| [A55 fixture containment](validation/a55-fixture-containment/forced-exit-probe.json) and [A51 correction](agents/a51.md) | Forced-SIGKILL containment passed on unchanged source; parent cleanup removed the fixture | Withdrawn finding after complete inheritance review; no containment fix or permanent regression added |
| [Protected invariants](validation/protected-invariants.json) | 253 protected files verified against base, including both measurement proofs and 73 goldens; helper name inventories remain 49 and 81 | 69 measurement-source bytes and 21 dependency descriptors preserved; downloaded dependency bytes are not verified by this check |

[Retained log identities](validation/retained-log-identities.json) bind the
unmodified logs. Test fixtures use synthetic native observations and, where
specified in individual reports, real small local Python children and SIGTERM.
Neither category executes the qualified native population. Failure and
partial records are never promoted to performance or phase acceptance.

## Publication verification

This prepublication packet records source-scoped work, not a successful future
workflow result. The published commit must receive its own complete strict
governance invocation with zero skips and stable checked source/tools. Verify
all 15 automatic workflow conclusions for that exact commit, then independently
replay its retained governance original against a clean exact checkout, bound
to the provider artifact digest, run and current attempt. The historical base
and focused results cannot qualify the changed revision.

Final report writes are not retried. Repeated interruption, uncatchable kills
or unavailable final persistence can prevent durable closeout; the records do
not promise otherwise. Capacity observations are point-in-time checks and do
not reserve resources or establish hidden cgroup ancestry.

## Scope that remains open

The native experiment is unstarted: 24 processes, 792 launches, 25,344 checked
FP32 words. No performance improvement, P06-A02/A03 acceptance, vendor XRT
integration or physical-hardware result is inferred from this packet. Required
private inputs and unchanged resource admission precede a real hosted attempt.
