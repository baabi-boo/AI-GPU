# Qualified warm launch-readiness audit

## Development decision

The audited `master` base is `e3ad6bd1e2b002aa234d57cd8a02519cec915830`.
The next development step remains one complete qualified warm-workspace
experiment. Its frozen population is 24 processes, 792 launches and 25,344
checked FP32 words. P06-A01 retains its accepted simulated scope; P06-A02/A03
remain open. P01 vendor integration and later physical-hardware obligations
are unchanged.

The base's 15 workflows passed. Independent replay of the original from
[Project Governance run 45682754592](https://github.com/baabi-boo/AI-GPU/actions/runs/45682754592)
reconciled 5,406 canonical tests, 38,492 successful subtests and 54,710 events.
That original qualifies only the base revision. The
[provider receipt](evidence/p06-launch-readiness/validation/base-governance-provider.json)
and [replay receipt](evidence/p06-launch-readiness/validation/base-governance-replay.json)
retain its exact identities and replay scope.

## Reproduced production boundaries

| Finding | Reachable failure | Required behavior |
| --- | --- | --- |
| Dependency command checkpoint | Saving the command record fails before entering the process monitor; the finished report nevertheless retains an unknown start state, preventing safe partial retention. | Record the proven absence of a launch and preserve the original failure. Exceptions after monitor entry remain unresolved unless a returned receipt establishes the disposition. |
| Native command checkpoint | The first native launch is marked unknown before its prelaunch checkpoint succeeds; failure can overstate execution and block closeout. | Restore the previous aggregate native state and record that this command did not start. Preserve actual prior launches and uncertain monitor outcomes. |
| Unresolved command disposition | A missing or unknown launch observation can be classified as blocked because its value is false-like. | Classify an attempt as blocked only when every recorded command is explicitly known not to have started. An unresolved command remains a failure. |
| Cooperative CLI cancellation | SIGTERM outside the process monitor can terminate dependency building or a managed-executor CLI before the normal failure path retains observations. | Install temporary handlers for dependency building and all five managed-executor CLI entries, including qualified warm. Enter existing interruption handling and restore the previous handler while preserving the monitor's child cleanup ownership. |
| Interrupted handler installation | A first SIGTERM immediately after installing a handler can unwind before entering its restoration guard, leaving the new handler installed even though no command started. | Capture the previous handler first and perform installation inside the existing `try/finally` guard. Both real-signal controls fail before and pass after the correction. |
| Interrupted final observations | A first interrupt during managed final source, artifact, admission, log or resource observation can escape before failed-attempt accounting finishes. | Retain the interruption as a failure, preserve prior observations and revoke positive claims. An initial checkpoint failure also enters protected closeout. |
| Interrupted final count aggregation | An interrupt in the final pure count calculation can leave completed observations behind a running report with zero totals. | Record a final-count failure and recompute once from the unchanged observations. A second interruption propagates; no launch or sample is repeated. |
| Stale capacity observation | The visible cgroup has sufficient headroom before provisioning but develops a known shortfall during acquisition; the old observation still admits the supervisor. | Retain a fresh observation immediately before the native supervisor and enforce the same admission predicate. |

The [agent records](evidence/p06-launch-readiness/agents/) contain concrete
reproductions, reviewed changes and scoped validation. Development probes use
small local processes or explicitly synthetic dependency/native fixtures. They
do not execute the qualified native population or establish a performance gain.

Recovery remains bounded by the available observations and a functioning final
write. Repeated interruption, `SystemExit`, an uncatchable kill or final report
persistence failure can still prevent durable closeout. Final writes are not
retried. A partial packet is retained evidence of the attempt; it cannot become
a successful native result or authorize performance acceptance.

## Preserved experiment

The 69 frozen measurement sources, 21 dependency source inputs, source proofs,
sampling order, numerical checks, performance predicates and golden data remain
protected. The required reserves remain 15 GiB free disk and 4 GiB available
memory. A repeated observation does not reserve memory or establish visibility
of hidden cgroup ancestors.

The exact private control archive and public age recipient are operational
inputs. This continuation does not establish their live provider configuration.
Local resource observations do not admit the native experiment. The
[operator guide](p06-hosted-warm-guide.md) and
[qualified warm handoff](p06-qualified-warm-handoff.md) continue to govern a
real attempt, encrypted complete or partial delivery, independent restoration,
complete original replay and evaluation of the frozen predicates.

## Publication and continuation

The final integrated selection passed **184 distinct tests**, with zero
failures, errors, skips or loader errors in **152.862583 seconds**. Its
[receipt](evidence/p06-launch-readiness/validation/integration-final.json)
binds all seven changed production files and selected test modules before and
after execution; their bytes remained stable. The eleven new regression modules
contribute 65 methods. Existing test sources remain unchanged.

[Release discovery](evidence/p06-launch-readiness/validation/test-discovery-release.json)
collects **5,471 unique canonical IDs**, preserving all 5,406 baseline IDs and
their order. It adds exactly those 65 methods, with no removals, duplicates or
loader errors. Collection runs no test bodies and is not full strict governance.

The earlier integrated selection passed **173 distinct tests**, with zero
failures, errors or skips in **156.502231 seconds**. Its
[receipt](evidence/p06-launch-readiness/validation/focused.json) binds the four
production files and selected test modules before and after execution; their
bytes remained stable. That result precedes the final handler-setup correction.
After that correction, the affected CLI/cancellation selection passed **29
distinct tests**, with zero failures, errors or skips in **15.446788 seconds**;
its [receipt](evidence/p06-launch-readiness/validation/signal-setup-focused.json)
binds the four production files at that point and selected tests with stable
identities. Both results precede closure of the standalone managed-family CLI
finding by A54/A56. The earlier 167-test result, final-count controls,
handler-setup controls and managed CLI controls remain separate historical
development records.

The forced-kill fixture cleanup concern raised by A51 was withdrawn after A55
and A51 traced the complete inheritance chain and verified actual parent-owned
cleanup. The passing control, original finding and reviewed correction are all
retained; no containment fix or permanent test was added for that concern.

The CI review also corrected the current
[CI contract](ci-contract.md): Project Governance uses the checked strict runner
and a 90-minute total job budget. Ordinary unittest success does not qualify a
revision. Neither the workflow nor its acceptance predicate changed.

The [evidence packet](evidence/p06-launch-readiness/README.md) records scoped
validation and publication checks. Each changed published revision requires its own
complete strict governance invocation and independent original replay before
native admission. Focused tests and the historical base result do not satisfy
that requirement.
