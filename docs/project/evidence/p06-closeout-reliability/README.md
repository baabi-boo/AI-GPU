# Qualified warm closeout reliability evidence

This packet accompanies the [closeout audit](../../p06-closeout-reliability-audit.md).
It records fixes for observed orchestration, cancellation and encryption
closeout failures. It does not establish a new native measurement, performance
result or phase acceptance.

## Source and work boundaries

The audited base is `43c93ce892f1f3f6c0555597da342709ec9f7e49`.
Seven production orchestration modules change. Ten new regression modules add
44 canonical methods; existing tests are preserved. Changes protect initial
checkpoints, record a proven nonstart before hosted monitor entry, guard final
pure observations, clean up interrupted CLI transfers/encryption/preparation,
and verify the final public ciphertext and summary after publication cleanup.

All **100 distinct numbered assignments are complete**. The
[assignment ledger](agent-ledger.json) records their actual task names, reports
and completion state. The integrating root is excluded; recovery follow-ups
are not new agents. At most three workers run alongside the root. Reports
under [agents](agents/) distinguish independent reviews, implementation and
source-scoped development checks. Early reports reconstructed after a temporary
runtime reset are explicitly labelled; they are not presented as original logs.

[Release source identities](release-source.json) bind the final production and
test bytes. The [packet manifest](packet-manifest.json) records each evidence
file's size and SHA-256, excluding the manifest itself.

## Verification boundaries

The base's 15 automatic workflows passed, including all 43 main CI jobs.
The original from
[Project Governance run 45707499652](https://github.com/baabi-boo/AI-GPU/actions/runs/45707499652)
reconciles 5,471 canonical tests, 38,592 successful subtests and 55,005 events.
Its recorded execution duration is 2,461.899321 seconds. The unchanged archive
has 1,386,100 bytes and SHA-256
`c2f2af74d893480c59d5e7f033e76a5f20c679bdb32b46bcc97da0b95a391437`.
[Provider evidence](validation/a029-provider-after.json) and an
[independent replay receipt](validation/a029-replay.json) retain its exact scope.
Replay imports trusted source for discovery but executes no test bodies or
retained archive code. This result qualifies only the base.

[Final focused integration](validation/a085-integration.json) passed **228 unique
tests across 27 modules**, including all 44 new methods, and 331 successful
subtests in **32.884070 seconds**. It recorded zero failures, errors, skips or
loader errors. The [raw log](validation/a085-integration.log) and
[runner](validation/a085-integration-runner.py) retain the exact selection and
completed suite invocation. All seven production files, ten new test files and selected
existing tests remained byte-identical before and after execution. Process
state was restored. This is a focused development result.

The [process-outcome record](validation/a085-process-outcomes.json) distinguishes
a failed runner startup (zero tests loaded or run) from the one completed
focused suite. The temporary receipt glob was corrected to exclude directories;
no test method was retried and no repository source changed in that repair. The
[earlier 228-test integration](validation/a052-integration.json) precedes A080
and retains the previous test-fixture identity. Retained runner code records
the original execution layout; it is not a portable strict-governance launcher.

The [final review bindings](validation/a064-review-bindings.json) confirm all
seven production identities at the final focused integration. The earlier
[independent review map](validation/a035-review-coverage.json) covers all
18 initially changed production hunks and binds their source identities to
their reviewers. The subsequent [A049 correction](agents/a049.txt) adds a final
directory-path check after both public reads; [A051](agents/a051.txt) independently
reviews that exact final identity. Four directory-movement cases failed before
and passed after it. The [earlier 227-test integration](validation/a030-integration.json)
remains historical evidence from before this correction. Supplemental controls
retain their own scope:

| Control | Observation | Evidence |
| --- | --- | --- |
| `fdopen` setup failure | Six controls preserve the original error, close the raw descriptor once and preserve a subsequently reused descriptor | [Report](agents/a032.txt), [raw result](validation/a032-fdopen.raw.txt), [probe](validation/a032-fdopen-probe.py) |
| Final public read/deadline failure | Two synthetic full-caller controls retain committed public bytes, propagate failure and close descriptors | [Report](agents/a033.txt), [log](validation/a033-public-read-probe.log), [probe](validation/a033-public-read-probe.py) |
| Scoped handler setup | 21 bounded controls restore prior handlers across all three new wrappers; no actual signals delivered by this supplemental probe | [Report](agents/a034.txt), [result](validation/a034-signal-setup.json), [probe](validation/a034-signal-setup-probe.py) |

These controls are separate observations, not additional canonical tests or
full qualification. The primary CLI regressions include actual local SIGTERM.

[Final canonical collection](validation/a086-discovery.json) finds 5,515 unique IDs: the 5,471
existing IDs and exactly 44 additions, with no loader errors. Collection is not
execution. Focused development results, source hashes, raw logs and independent
reviews are retained in this packet. They do not replace a
complete, uninterrupted strict governance invocation with zero skips under the
checked environment for the exact published revision.

Synthetic process and failure fixtures are distinct from the qualified native
population. Local subprocess controls establish cooperative first-SIGTERM
cleanup at their recorded sources. No test here establishes an improvement in
native performance.

## Preserved inputs and limitations

The 69 frozen measurement sources, 21 dependency descriptors, pins, proofs,
73 inherited goldens and 48 gate/testcase files remain unchanged. The broader
historical inventory category called `experiment_contract_or_pin` includes the
supervisor: its checkpoint relocation changes that one file, while the actual
frozen measurement and dependency contracts remain unchanged. This distinction
is recorded in the invariant review, rather than claiming that every broader
inventory entry stayed identical.

Final [measurement-source](validation/a070-measurements.json),
[golden/gate](validation/a071-goldens.json) and
[proof/dependency-pin](validation/a072-proofs.json) observations bind these
preserved inputs to the audited base. They verify local source identities;
they do not freshly validate downloaded dependency archive bytes.

Recovery depends on a working final write. The existing exclusive JSON writer
can leave a stage-specific `*.json.tmp` (for example, `report.json.tmp`) after a
mid-write failure, preventing a later save.
These changes do not remove that ownership protection or retry final writes.
Repeated interruption, unavailable persistence, `SystemExit` and uncatchable
kills can still prevent durable closeout. A retained partial ciphertext or
failed attempt never becomes a successful native result.

The [finding dispositions](finding-dispositions.json) preserve resolved findings,
known limits and follow-ups. [A080](agents/a080.txt) corrected the new hosted
test fixture so registered cleanup also runs after a late setup failure;
[A081](agents/a081.txt) independently reviewed the one-line move. The
[before/after probe](validation/a080-verification.json) observes real registered
cleanup without changing test methods or assertions.

[A076](agents/a076.txt) retains a nonblocking F1 test-isolation risk: under delayed
scheduling or filesystem operations, a daemon worker can outlive its bounded
test join and fixture cleanup. Passing integration does not qualify that failure
branch. No production regression or native/network escape was established.

The next actual experiment remains **24 processes, 792 launches and 25,344
checked FP32 words**. It has not started. Exact private control delivery and the
public age recipient were not supplied to this session; live provider secrets
were not inspected. Require the unchanged **15 GiB free-disk and 4 GiB
available-memory** admission, separate dependency/four-process prerequisites,
encrypted complete or explicitly partial retention, private restoration,
independent complete native replay and every frozen performance predicate.
P06/P06-T01 remain `in_progress`; P06-A02/A03 remain open and P01 vendor
integration remains blocked.

## Publication verification

The [prepublication checks](validation/root-publication-checks.json) record
successful structure/metadata validation and clean whitespace checks for the
changed code and current documentation. The full staged whitespace check
reports six findings in retained reports/failure logs. Those raw evidence bytes
are preserved unchanged; no workflow or enforcement gate is altered.

This prepublication packet cannot assert a future workflow result. Check all
15 automatic workflows for the exact final pushed revision and independently
replay that revision's original governance artifact against clean trusted
source. The base result, focused development checks and collected test IDs do
not qualify changed source. Keep provider identity, artifact digest, current
run attempt and replay evidence bound together before native admission.

The [trigger review](validation/a066-workflows.json) lists the expected workflow
names. The [main-CI plan](validation/a067-main-ci-plan.json) preserves the 37
SimX test cells and six orchestration/build jobs. These are expected plans and
historical base observations, not conclusions for a future publication.
