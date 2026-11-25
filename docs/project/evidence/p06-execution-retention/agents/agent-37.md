# Agent 37 — independent regression-quality review

## Verdict and scope

**No blocking regression-quality finding.** Reviewed the six production diffs,
all fourteen new test modules, their reused fixtures, and the existing
`Response.close()` fixture addition against base
`622662ad9cece6da4e3375be7e977dbe04cde862`. Read the brief, repository instructions,
code-review skill/policy, applicable automation contract, and earlier author and
reviewer evidence. Production and tests remained read-only; no Git writes.

All **22 paths** match `validation/operational-source-freeze.json`, including
size and SHA-256. Static enumeration finds **50 new test methods**. Independent
AST comparison confirms all **37 existing control test methods are unchanged**.
The only existing fixture delta adds `close()` to set its already-existing
`closed` flag; it supplies the real response interface now used by production.
It neither removes assertions nor manufactures closure in the new real
`HTTPResponse` test.

`agent-37.json` retains the complete source identities, method/line mapping,
defect-versus-companion-control roles, and hashes/provenance of reviewed evidence.

## Sensitivity to actual defects

| Boundary | Assertion that detects the defect | Reviewed pre-fix evidence |
| --- | --- | --- |
| Acquisition launch checkpoint | `process_started` must be `False`; no child/log exists | Agent04 retained red log: eight subcases fail `None is not False` |
| Supervisor checkpoint | Known unstarted stage is blocked, closed out, and native `not_run` | Agent02 reported six red subcases; source inspection confirms the missing update |
| Hosted failed supervisor | Finished `not_run`/`run` survives in both selected closeout receipts | Agent01 reported two failed disposition subcases; the real hosted observer is not mocked |
| Control storage/transport | Actual partial bytes/digest, sanitized storage reason, real response body closed | Agent06 reported eight failed assertions; real HTTP parser and real writes are exercised |
| Control receipt/outer cleanup | Failed receipt cannot stay successful; first error and later cleanup survive | Agent12/16 retained red logs show stale `pass`, overwritten reason, and skipped directory close |
| Directory ownership | Reused descriptor survives; opened child closes; original exception identity survives | Agent21 retained integration probe, Agent23 retained ten failed assertions |
| Packaging output/setup | Replacement stays unchanged; owned failure retained; output descriptor released | Agent03 baseline/candidate JSON; Agent28 retained six leaked-output failures |
| Encryption publication | Path drift raises before success; last ciphertext remains intact | Agent11 retained base run: both subcases fail `EncryptionError not raised`; Agent05 reported earlier path-drift reproductions |
| SIGTERM scope | Completed child followed by signal still produces finished failure and restores handler | Agent10 retained red log: three processes exit `-15`; bounded-child case lacks outer handler |

Not all 50 methods are independent base failures. Invalid hosted receipts,
unobserved command errors, completed failed-child byte retention, and committed
ciphertext interruption include **companion controls** preserving correct
existing behavior or rejecting unsafe alternative fixes. The mapping marks
those separately; their presence is useful coverage, not evidence that every
addition failed the base. Some earliest red runs exist only as author-reported
results, which the mapping distinguishes from retained raw logs/results.

## Mock and cleanup assessment

Mocks isolate admission, capacity, transport or command fixtures while leaving
the asserted production checkpoint, observation, descriptor, receipt and
publication logic active. Hosted packaging/encryption are explicit composition
doubles; assertions prove selected records and authorization behavior, not real
encryption. Encryption fault tests use the existing explicitly synthetic age
subprocess; real filesystem links, renames, bytes and digests remain observed.

Consumed-descriptor tests perform real `close`, synchronously reopen `/dev/null`,
and assert exact numeric reuse. Their real `fstat`, close-count and exception
identity checks expose both double-close and leak defects. They create no
concurrent opener; finalizers release only recorded test-created descriptors
after patches exit. No `dup2` into an unowned descriptor or cleanup path that
targets a fixture-unowned live descriptor was found in the reviewed scenarios.

The real-signal harness (`test_p06_operational_cancellation.py:171`) waits for a
readiness marker, observes completed-child reaping and retained running
checkpoints, then sends SIGTERM. Startup and completion each have eight-second
bounds; final process wait is three seconds with process-group cleanup. The
bounded case calls the real monitor, and all cases assert enclosing-handler
restoration. The sole new skip guard at line 168 is POSIX plus Linux `/proc`,
true on the checked environment. No new expected-failure marker or weakened old
assertion was found.

## Evidence limits and next action

This agent executed **no test bodies**, broad suites, native work or additional
fault probes: static review plus retained focused evidence resolved the assigned
questions. No current-tree pass is claimed from this review. Conservative impact
is R3 for externally observable failure/termination behavior; this is a scoped
independent test review, not whole-project approval. **Land after the
coordinator's final frozen-source qualification**, with no test-quality fix
requested here. Native execution and phase acceptance remain outside this work.
