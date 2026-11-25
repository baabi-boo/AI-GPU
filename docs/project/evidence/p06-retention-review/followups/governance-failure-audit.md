# A40 follow-up — published-source governance invocation FAILED

## Verdict

**FAIL: Project Governance run `45575499141`, job `139072298484`, attempt 1 completed unsuccessfully for published source `0c32d04c5d37679bb0273f07a50bd26a2e21a5e8`.** The original retained summary has `status: completed`, `execution_completed: true`, `strict_success: false`, and `governance_passed: false`. A complete invocation ran; it did not qualify.

This is the same A40 reviewer following up on the later published source, not a new independent agent. The prior BASE-only reports `notes/a40.md` and `notes/a40.json` remain byte-for-byte unchanged. No public evidence file was rewritten, and the earlier BASE pass was not relabeled as a pass for this revision.

The failure is supported by original artifact receipts and the full provider job log. Forty-eight provenance, integrity and accounting checks passed; five success requirements correctly remain false because this invocation failed. These audit checks are not additional governance tests and do not override the failed test result.

## Exact execution and failure

| Observation | Result |
| --- | --- |
| Canonical discovery | `ci/project`, `test_*.py` |
| Discovered unique test IDs | 5,114 |
| Ordered starts / terminal parent outcomes / stops | 5,114 / 5,114 / 5,114 |
| Successful parent tests | 5,113 |
| Failed parent tests | 1 |
| Successful subtests | 37,448 |
| Failed subtests | 1 |
| Total ordered events | 52,791 |
| Skips / loader errors / fixture events / abort | 0 / 0 / 0 / none |
| Missing, unexpected or duplicate IDs | None |
| Unittest log result | `Ran 5114 tests in 2311.191s`; `FAILED (failures=2)` |
| Strict runner receipt duration | 2311.201039 seconds |
| Invocation started | `2026-11-25T08:21:57.162591+00:00` |
| Invocation finalized | `2026-11-25T09:00:33.831804+00:00` |
| Provider step result | `Test governance tooling`: failure, exit 1 |
| Packet upload | Success |

The two unittest failure records belong to one parent test and its directory subtest, not two distinct canonical test IDs:

`test_p06_qualified_warm_restore.QualifiedWarmRestoreTests.test_changed_restored_bytes_and_unexpected_entries_are_detected`

1. The `(change='directory')` subtest expected `RestoreError`, but no exception was raised. The provider traceback points to `ci/project/test_p06_qualified_warm_restore.py:272`.
2. The parent test then failed `assert_incomplete(output)` because the expected incomplete marker was absent. The traceback points to the call at line 275 and the marker assertion at line 90.

Original `run/events.jsonl` records the subtest failure at sequence **41420**, elapsed **1489.939591** seconds, and the parent failure at sequence **41421**, elapsed **1489.939899** seconds. Those are the only non-successful outcome events. The same parent ID appears in `summary.execution.non_successful_ids`.

All 5,114 tests still have their exact ordered start/outcome/stop records. Events have consecutive sequence numbers, nondecreasing elapsed timestamps, complete nonoverlapping parent lifecycles, and subtests within their active parent. The manifest's ordered-ID digest was independently recomputed as `a33e6215dd12a601aefe3161615083699a8e9fef0ef22a9faaef0331939a71cd`, matching both retained manifest and summary fields. The internal log is untruncated and its 917,850-byte size matches the summary. The outer governance log is retained too.

## Provider and original-artifact integrity

| Field | Value |
| --- | --- |
| Repository | `baabi-boo/AI-GPU` |
| Published source | `0c32d04c5d37679bb0273f07a50bd26a2e21a5e8` |
| Source tree | `e20c21c8aeeaa1751f49f43de3b38e7872bbcaa6` |
| Run / job / attempt | `45575499141` / `139072298484` / `1` |
| Artifact ID | `15006112807` |
| Artifact name | `project-governance-0c32d04c5d37679bb0273f07a50bd26a2e21a5e8-run45575499141-attempt1` |
| Original ZIP bytes | 1,316,303 |
| Original ZIP SHA-256 | `bc40f99327415fc753cf49749b6b4e75b3186d98ec218485f5aef505c735392d` |
| Members / uncompressed bytes | 12 / 21,538,419 |
| Artifact created | `2026-11-25T09:00:36Z` |
| Artifact expiry | `2026-12-25T09:00:34Z`; not expired when retrieved |

The ZIP hash and size match both provider artifact metadata and the full job upload log. The artifact's own workflow metadata binds the run and source SHA. All preceding environment/project/baseline steps succeeded, and artifact retention succeeded after the failed suite.

Static provider links:

- https://github.com/baabi-boo/AI-GPU/actions/runs/45575499141
- https://github.com/baabi-boo/AI-GPU/actions/runs/45575499141/job/139072298484
- https://github.com/baabi-boo/AI-GPU/actions/runs/45575499141/artifacts/15006112807

| Original member | SHA-256 |
| --- | --- |
| `run/summary.json` | `92865456427b10d776e86e74d42d891b77abae457a3105561fc02394014604b9` |
| `run/discovered.json` | `db8665fccccf134902c1739d8c5eb55d8f2021cd9d394c43e39f0f615d2836cd` |
| `run/events.jsonl` | `25a5d701d10f129a4c49f4d5e86efc35fed104604966e7e8b25b68b4bc4d77ea` |
| `environment/environment.json` | `1ab71b58d89a32ca612f9f47d0e505498d50d8f4dd163cf2535fb8289e321a5e` |
| `run/started.json` | `f355ba39f30c257d06aa2d93756b92960f74722e394b809f7e47e0c67a7185b7` |

All 12 original member sizes and hashes are in `a40-final-governance.json`.

## Source and environment remain bound despite the test failure

Provider head, checkout log, source-revision file, started receipt and both summary source snapshots name the exact published SHA. The source snapshots are identical, clean, and free of mismatches. The recorded tree is the expected `e20c21c8aeeaa1751f49f43de3b38e7872bbcaa6`.

I independently enumerated the exact published Git tree from fetched immutable local objects. Its 7,688 entries reproduce `b810d5bcdc2b58ddfba2cf99e468de3fc6d85bfe6213cd44c1d17f7fc863c052`, matching retained tracked, index and materialized-worktree digests. The final source has sole parent `ae23147501bbe91a5b92caa09ddf4fcde3b8148e`; that checkpoint has sole parent BASE `25543e1cf96530264746c0e2d130018dd0dba465`. The checkpoint tree was independently observed as `72dc5c78acb8f117780abd269d6d5d8158f7dbf1`.

Environment preparation reports ready with no error, all eight required probes true, Python 3.12.3, and native CMake 3.22.6. The exact environment receipt hash/size match the summary; all 11 tool identities match preparation and before/after snapshots. Interpreter and environment snapshots are identical before/after/started. All three source/environment/interpreter stability flags are true. Nineteen preparation commands return zero; the intentional UBSan rejection probe returns one; none time out.

These observations rule out a missing population, skipped population, unbound source, recorded tool drift, interrupted invocation or missing final receipt as explanations for the failed qualification. They do not identify the software defect by themselves. Five uninitialized gitlinks remain explicitly scoped to governance and establish no native submodule closure.

## Read-only diagnostic clue, not a proven root cause

The exact published test removes `private/empty` and immediately recreates it for the failing directory case (lines 267–269). The production verifier compares retained directory identity tuples; it acquires the per-visit before/after stamp only when verification begins. Immediate inode reuse is a plausible explanation consistent with this miss, but no reproduction or filesystem-inode trace was performed by A40. The failure must remain a failure pending diagnosis; this hypothesis is not a waiver or a claim that the test is merely flaky.

## Retrieval, monitoring and preserved files

The previously documented supported path worked again: the GitHub artifact-download tool returned a reusable reference, and a bounded HTTPS GET of its exact returned download URL produced the original ZIP. I checked an 8 MiB download cap, a 100-entry/32 MiB uncompressed archive cap, path safety, symlinks, provider size and digest before parsing. Archive members were read as data; no retained payload was executed. Temporary signed URLs, file tokens and connector IDs are absent from these notes.

The monitoring record contains 42 job polls at approximately 55-second intervals, from `08:23:32.918Z` through `09:01:26.445Z`. I immediately reported the actual provider failure once observed, then reported the exact traceback and original receipt counts. No dispatch, retry, source edit, publication, governance/native test launch, phase claim or new agent was performed by A40.

Private working materials:

- Original ZIP: `/home/agent/ai-gpu-d37f66a85d88/tmp/a40/final/final-governance-45575499141.zip`.
- Sanitized provider metadata/poll history: `/home/agent/ai-gpu-d37f66a85d88/tmp/a40/final/provider-metadata.json`.
- Local data-only audit reader: `/home/agent/ai-gpu-d37f66a85d88/tmp/a40/final/audit_final_governance.py`.
- Requested final audit JSON: `/home/agent/ai-gpu-d37f66a85d88/notes/a40-final-governance.json`.

**Disposition: exact-source strict governance remains failed for `0c32d04c5d37679bb0273f07a50bd26a2e21a5e8`.** Preserve this completed failure packet. A corrected source requires its own newly published revision and complete strict invocation; neither the successful BASE run nor focused diagnosis can substitute for that qualification.
