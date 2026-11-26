# Qualified warm closeout reliability audit

## Development decision

The audited `master` base is `43c93ce892f1f3f6c0555597da342709ec9f7e49`.
The next actual development experiment remains one complete qualified warm
attempt. Its frozen population is **24 processes, 792 launches and 25,344
checked FP32 words**, and it remains unstarted. P06/P06-T01 remain
`in_progress`; P06-A01 retains its accepted simulated scope, P06-A02/A03 remain
open, and P01 vendor integration remains blocked.

All 15 workflows passed at the base. Its
[Project Governance run 45707499652](https://github.com/baabi-boo/AI-GPU/actions/runs/45707499652)
records **5,471 canonical tests, 38,592 successful subtests and 55,005 events
in 2,461.899321 seconds**. The original artifact SHA-256 is
`c2f2af74d893480c59d5e7f033e76a5f20c679bdb32b46bcc97da0b95a391437`.
Independent original replay was completed for that base. These results qualify
the exact base only; the changed published revision's own strict governance
and independent original replay remain required before native admission. The
[evidence packet](evidence/p06-closeout-reliability/README.md) retains the
source-scoped observations and their limitations.

## Production boundaries addressed

The seven changed production files extend the
[preceding launch-readiness work](p06-launch-readiness-audit.md):

| Boundary | Implemented behavior | Scope |
| --- | --- | --- |
| First report checkpoint | The qualified runner, input acquisition, local preparation and dependency builder enter their existing protected execution path before attempting the first report write. | A recoverable first-write failure can reach failed-attempt finalization when the final write remains possible. Setup before that protected path is outside this guarantee. |
| Cooperative CLI cancellation | Local preparation, private control acquisition and encryption temporarily translate `SIGTERM` into the existing interruption path and restore the prior handler in `finally`. | Direct library calls retain their existing signal behavior; child-process cleanup keeps its existing owner. |
| Hosted prelaunch status emission | Failure while emitting a stage's running status records an explicit nonstart before the only child-launch call. | The original failure is preserved; earlier launches and unresolved outcomes after monitor entry remain distinct. |
| Hosted final observations | Writer-completion and native-disposition observations record failures and revoke positive orchestration claims. An interrupted pure observation permits one further observation. | Ordinary exceptions are not retried; no stage, native launch or performance sample is repeated. Missing observations remain false or unknown, and already reconciled native facts retain their scope. |
| Encryption descriptor setup | Failure after exclusive descriptor creation closes that descriptor once before propagating the original error. | The close is not retried against a potentially reused descriptor number. |
| Published encrypted outputs | Ciphertext and sanitized summary are reopened and checked for expected identity, bytes and stable metadata after publication; directory paths are checked again after both reads. | Mutation or replacement fails closed; cleanup remains restricted to owned files. This check is not durable delivery, decryption or native replay. |

## Validation and durability limits

The [final focused integration](evidence/p06-closeout-reliability/validation/a085-integration.json)
passed **228 unique tests across 27 modules**, including all 44 new methods,
and 331 successful subtests. It completed in **32.884070 seconds** with zero
failures, errors, skips or loader errors. Before/after SHA-256 records confirm
unchanged bytes for all seven production modules, ten new test modules and
every selected existing test. Cwd, environment, signal handlers and thread
inventory were restored. The [raw log](evidence/p06-closeout-reliability/validation/a085-integration.log)
retains one completed, uninterrupted focused suite; no test was retried. The
[process outcomes](evidence/p06-closeout-reliability/validation/a085-process-outcomes.json)
also preserve a failed temporary-runner startup with zero tests loaded or run:
its receipt glob included a directory. Filtering receipt paths to files repaired
that temporary harness; no repository source changed in that repair.

The preceding [228-test integration](evidence/p06-closeout-reliability/validation/a052-integration.json)
passed before the one-line test-fixture cleanup. [A080](evidence/p06-closeout-reliability/agents/a080.txt)
moved the hosted fixture setup inside its existing cleanup guard; its real
setup-failure control observed six leaked cleanup states before and automatic
restoration afterward. [A081](evidence/p06-closeout-reliability/agents/a081.txt)
reviewed the exact change; method IDs and assertions remain unchanged.

The earlier [227-test integration](evidence/p06-closeout-reliability/validation/a030-integration.json)
passed before the final directory-identity correction. The next review found
that a directory renamed during the new full-file reads could escape the
earlier directory check. Four deterministic cases failed before the added final
pathname check and passed afterward; [A049](evidence/p06-closeout-reliability/agents/a049.txt)
retains the reproduction, and [A051](evidence/p06-closeout-reliability/agents/a051.txt)
independently reviewed the final sources. Committed bytes and unrelated
replacements remain preserved. The final observation cannot prevent later
concurrent mutations.

The earlier focused selection passed **120 tests in 22.692 seconds**; the later
affected selection passed **92 tests in 13.901 seconds**, each with zero
failures, errors or skips. These overlapping development selections are not
summed and do not qualify the final changed revision.

[Release discovery](evidence/p06-closeout-reliability/validation/a086-discovery.json)
collects **5,515 unique IDs**, comprising the existing
5,471 and **44 new methods across ten modules**, with no loader errors.
Discovery executes no test bodies. Synthetic fixtures, injected host faults and
small local processes establish tooling behavior at their recorded source
identities; they do not execute the frozen native population or establish a
performance result.

**A functioning final report write remains necessary.** The existing shared
writer opens a stage-specific `*.json.tmp` exclusively (for example,
`report.json.tmp` or `dependency-preparation.json.tmp`). A fault after creating that
temporary, including during write, flush, fsync or replacement, can leave it
present and prevent the final save from publishing a finished report. The
first-checkpoint changes cover recoverable boundaries where final persistence
is possible; they do not repair this pre-existing mid-write limitation. No
report-write retry or ownership weakening is introduced. Repeated interruption,
uncatchable kills and final persistence failure are not promised durable
closeout. A missing finished report remains unresolved evidence, never success.

## Preserved experiment and next action

The **69 frozen measurement sources, 21 dependency descriptors**, source proofs,
goldens, sampling order, numerical comparisons and performance predicates remain
unchanged. Historical evidence and the inherited README SVG remain preserved.
These implementation changes grant no phase, physical-device, timing, resource
or performance acceptance.

Before native admission, obtain the selected published revision's own complete,
uninterrupted strict governance result with zero skips under the
[checked environment](governance-runbook.md), then independently replay its
original through the [governance-original admission](governance-artifact-replay.md)
path. The base pass and focused checks cannot substitute for that result.

Verify or configure private delivery of the exact historical control archive
and the explicit public age recipient, keeping the matching private identity
outside Actions. Those operational inputs were not supplied to this session;
live provider secrets were not inspected. Admit the actual runner through the
unchanged **15 GiB free-disk and 4 GiB available-memory** gates; a capacity
observation does not reserve resources or establish hidden cgroup capacity.

Use the [hosted operator guide](p06-hosted-warm-guide.md) and
[qualified warm handoff](p06-qualified-warm-handoff.md) for one complete fresh
attempt. Preserve the separate dependency/four-process prerequisites and
encrypted complete or explicitly partial originals. After private restoration,
independently replay a complete native original before evaluating every frozen
performance predicate. The native experiment remains the next actual
development step; synthetic closeout checks provide no substitute measurement.
