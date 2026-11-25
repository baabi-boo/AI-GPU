# P06 execution and retention audit

## Development decision

The audit started at `622662ad9cece6da4e3375be7e977dbe04cde862` on
2026-11-25. The next native milestone remains the frozen qualified warm
experiment: **24 processes, 792 launches and 25,344 checked FP32 words**, followed
by independent original-artifact replay and the frozen performance decision.
P06-A02/A03 remain open. P01-A03 vendor XRT, physical FPGA qualification and
unresolved resource gates remain separate obligations.

The [frozen experiment](../designs/qualified_warm_workspace_v1.md) compares
`per_operation` with `reusable_single_tile` for FP16 and BF16. After the excluded
prime operations and warm-up pairs, each format has five measured batch means
per policy. The candidate median must be at most 95% of the reference median;
every measured candidate pair must also avoid increases in host time and
qualified modeled cycles. Both formats must satisfy the predicates. A rejected
hypothesis is a valid result to retain, and does not justify replacing samples
or relaxing thresholds.

The current continuation fixes concrete orchestration and retention failures
found while auditing that next step. It does not change the measured workload,
kernel, runtime, simulator, numerical oracle, proof, sampling, performance
thresholds or resource admission. All 69 measurement-source identities were
checked against the frozen qualified-warm proof before implementation.

## Audited base

The live base had 15 successful Actions workflows. Its complete Project
Governance original was downloaded from
[run 45583904526](https://github.com/baabi-boo/AI-GPU/actions/runs/45583904526),
[job 139100502944](https://github.com/baabi-boo/AI-GPU/actions/runs/45583904526/job/139100502944).
The 1,320,535-byte original matched provider SHA-256
`928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156`.
Independent event reconciliation verified 5,114 canonical tests, 37,449
successful subtests and 52,791 ordered events in 3,122.11397 seconds, with no
failures, errors or skips and stable source, interpreter and environment.
This qualifies that exact base only. Changed source requires its own complete
qualification; focused development results are not a substitute.

## Reproduced findings

| Finding | Observed consequence | Correction |
| --- | --- | --- |
| Supervisor launch checkpoint failed before invoking the child | The finished receipt left an unknown process and blocked failure closeout although that child never started | Record the known unstarted child only at the prelaunch checkpoint boundary; preserve unknown status for exceptions after entering execution |
| Acquisition launch checkpoint failed before invoking the command | The terminal acquisition command lacked a determinate start/cleanup result and unnecessarily blocked retention | Preserve explicit unstarted/cleanup-complete failure state while retaining earlier completed command records and partial bytes |
| Hosted supervisor exited unsuccessfully with a valid finished receipt | The wrapper discarded observed native `run` or `not_run` status and wrote `unknown` into retained closeout records | Recover only a matching finished receipt after source-stability and writer-cleanup checks; keep the attempt failed |
| Packaging output directory was renamed and recreated | Packaging returned success after writing into a replacement directory | Retain the created directory descriptor, recheck its identity and mode, and anchor failure recovery to the original directory |
| Encryption source or output directory ancestry changed | Ciphertext publication could report success despite targeting displaced directories | Revalidate the complete no-follow directory chains at inventory and publication boundaries; preserve the committed ciphertext on later failure |
| A directory close consumed its descriptor and then failed | Cleanup retried the old descriptor number, potentially closing an unrelated file and leaking the newly opened child directory | Transfer ownership to the child before closing the parent, clean up the currently owned descriptor once and preserve the original error |
| Packaging opened its output before completing parent-directory cleanup | A failing parent close left the output descriptor outside its cleanup lifetime | Cover output acquisition failures with one owned-descriptor cleanup, preserving the original exception and any unrelated reused descriptor |
| Final packaging output closure failed while a primary packaging exception was active | The secondary close error replaced the original exception although the failure receipt retained its original type | Track failure within the invocation, preserve its primary exception, keep a standalone close failure fatal and attempt the owned close once |
| Control receipt finalization failed after writing a success-shaped record | The invocation failed but left a contradictory success receipt | Invalidate and repair only the owned receipt inode; preserve the archive and unrelated replacement files, and keep finalization failure fatal |
| Control archive storage failed during transfer or readback | Storage errors were reported as transport errors | Use the existing storage-failure classification and retain the actual partial-byte identity when readable |
| A rejected or interrupted HTTP response owned an unread body | Connection cleanup did not necessarily close that response | Explicitly close the response and always close the connection, including when response closure fails |
| SIGTERM arrived between bounded child commands | Default process termination bypassed the wrappers' existing failure-finalization paths | Reuse the existing scoped signal handler at the acquisition, supervisor and hosted CLI boundaries; retain the helper in the operational source inventory |

These checks detect observed changes. They do not isolate hostile processes
running as the same user or make multi-file publication crash-atomic. Failed,
partial and interrupted attempts keep their original scope; no correction
turns an unsuccessful execution into a successful experiment.

The final output-close F2 was reproduced in
[Agent 47's production-diff review](evidence/p06-execution-retention/agents/agent-47.md),
corrected by [Agent 48](evidence/p06-execution-retention/agents/agent-48.md), and
independently resolved by
[Agent 49](evidence/p06-execution-retention/agents/agent-49.md).
The unchanged six-case probe then preserved every original exception across
both public packaging APIs. Seven independently executed regression and positive
test methods passed with zero failures, errors or skips. The original red
evidence remains retained; the independent review covers this bounded correction.

A real-tool synthetic partial-attempt round trip also exercised the existing
packaging, encryption, inspection and restoration CLIs with the pinned age
v1.3.2 binaries. The 1,950-byte ZIP was restored byte-for-byte; the selected
retention contained eight files and three directories, including binary,
hidden, empty and intentionally inert Python content. Wrong digest, wrong
revision and existing-output controls failed as required. This is tool
interoperability evidence on recorded source hashes, not a native experiment
or producer-authentication result. Only sanitized validation records are public;
the ephemeral test identity was removed after decryption.

Separate real-age controls on the recorded candidate rejected a wrong identity,
truncation, a payload bit flip and appended ciphertext. The three payload
mutations left private partial plaintext despite nonzero decryption exits;
strict inspection also rejected those files. A valid age envelope containing a
tar with an extra zero record decrypted successfully but failed strict archive
validation even with a matching plaintext digest. These observations support
the operator guide's requirement to check decryption success and then validate
the complete plaintext archive before restoration.

## Verification and publication

Implementation reports, independent reviews, exact source identities and
completed validation are collected in the
[execution and retention packet](evidence/p06-execution-retention/README.md).
The [publication source snapshot](evidence/p06-execution-retention/validation/publication-source-freeze.json)
binds **23 files** after the final output-close correction, with SHA-256
`6c90e8e2c097b1d8db3534835d4f8ae94c4f6dc2c20b1c59283342c0b1c2dbf8`.
It retains the corrected packaging helper and its three-method regression module.
The earlier [22-file snapshot](evidence/p06-execution-retention/validation/operational-source-freeze.json)
remains unchanged at SHA-256
`714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb`.

The [focused invocation on the publication source](evidence/p06-execution-retention/agents/agent-50.md)
passed **328 distinct test methods across 26 modules** in **73.452944 seconds**,
with zero failures, errors or skips and exit 0. Its
[exact command, IDs, events and source identities](evidence/p06-execution-retention/agents/agent-50.json)
and [complete log](evidence/p06-execution-retention/agents/agent-50-tests.log)
record one invocation with stable frozen and selected source snapshots.
[Independent evidence reconciliation](evidence/p06-execution-retention/agents/agent-53.md),
with [machine-readable checks](evidence/p06-execution-retention/agents/agent-53.json),
reconstructed all **984 start/success/stop events for the parent test methods**
and their ordered IDs. The runner's **645 successful subtests** are a reported
aggregate; that count and individual subtest labels and outcomes cannot be
independently reconstructed from the parent test events.

[Canonical collection](evidence/p06-execution-retention/agents/agent-51.md) found
**5,167 unique IDs**, retaining all **5,114 base IDs** and all **5,164 earlier
candidate IDs** in their original relative order. The
[comparison](evidence/p06-execution-retention/agents/agent-51-population.json)
and [ordered IDs](evidence/p06-execution-retention/agents/agent-51-discovered.json)
record **53 additions across 15 modules** against the base, including three
since the earlier collection, with no duplicates, loader errors or active skip
flags. Collection executed no test bodies or fixtures. These focused and
collection results do not replace an actual complete strict governance result
for the exact published revision.

Only actual completed assignments count toward the requested 60 agents.
Agents use separate fresh contexts and nonoverlapping file ownership; root
integration and publication remain separate from their individual checks.

### Evidence before the final output-close correction

The earlier [325-test invocation](evidence/p06-execution-retention/agents/agent-42.md)
passed across 25 modules in 67.066 seconds with zero failures, errors or skips.
The earlier [5,164-ID collection](evidence/p06-execution-retention/agents/agent-44.md)
preserved all 5,114 base IDs in relative order and added 50 IDs across 14 modules.
Both remain evidence for their retained 22-file source snapshot; they were not
combined with or substituted for the later results.

The [earlier positive retention round trip](evidence/p06-execution-retention/agents/agent-41.md),
with [command and identity records](evidence/p06-execution-retention/agents/agent-41.json),
passed all nine actual tool invocations, preserving eight files, three directories
and 8,690 selected bytes through restoration. All 22 frozen operational/test
identities and 89 imported repository source hashes remained stable during that
run. The disposable private identity was removed, and the retained Python
sentinel was never executed. The packaging helper changed afterward for the
final output-close correction, so this successful real-age pipeline does not
establish a round trip for the 23-file publication source.

## Remaining native action

Use the [operator guide](p06-hosted-warm-guide.md) after verifying the selected
published revision's complete strict governance result. Supply the unchanged
private control original and the owner's public age recipient; retain the
matching private identity outside Actions. The runner must pass the unchanged
15-GiB free-disk and 4-GiB available-memory admission before native work.

This session has no admitted native runner. The owner's public recipient and
private control delivery were not supplied to this session; live provider secret
configuration was not inspected. The reviewer retains the matching private
identity outside Actions. The available GitHub connector supports
source publication and Actions inspection but exposes no secret configuration
or workflow dispatch operation. Those limits must not be bypassed by changing
workflow triggers, publishing private originals or weakening admission.

Run one complete admitted attempt, preserve both successful and unsuccessful
original evidence, confirm encrypted delivery, privately decrypt and restore,
then replay a complete original from a separate trusted reader checkout. The
performance predicates and phase/resource decisions remain separate from
retention, restoration and governance success.
