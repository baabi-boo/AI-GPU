# Wave 10 replay-guard repair — executable-identity addendum

## Final candidate

The reopened fixture repair passes **89 complete-module tests in 139.141 seconds**, with zero failures, errors or skips. Its focused scope passes **8 methods in 5.412 seconds**, with 670 recorded path/resolve/write negative subtests and two explicit whole-fixture forged-parser rejections before any real `exec` dispatch or marker effect. The actual interpreter remains CPython **3.12.14** on Linux. Both source files are frozen at the hashes below.

This addendum supersedes the earlier candidate's publication readiness. The earlier **87-test passing run remains a valid historical test result**, preserved in `w10-replay-guard-fix.md`, the unchanged original `w10-replay-guard-fix.patch`, and the earlier portion of `w10-replay-guard-fix.log`. Independent review subsequently found an executable-identity gap in those test witnesses. Approval was withheld and the candidate was repaired before publication. The newly discovered gap is not evidence that the current production reader executes retained code.

No production reader, helper, workflow, manifest, original archive, index or intake receipt changed. Root retains publication ownership. A clean hosted retry remains required, and the failed hosted receipt retains its failed disposition.

## Independent finding and retained reproduction

The earlier callbacks checked only `code.co_filename`. Agent 60 showed that a different code object compiled under that filename was accepted. The strongest reproduction compiled the exact current pinned parser body plus one appended builtins-list marker statement, then patched only `SourceFileLoader.get_code` for the parser's exact path. In both complete collocated checked/public fixtures, genuine replay still passed, the expected parser-execution count remained one, the marker executed, and the on-disk digest-pinned parser stayed unchanged.

Agent 59 independently reproduced both complete-fixture bypasses before editing. Both records are appended as `reproduced_exec_identity_gap` in `w10-replay-guard-fix.log`; agent 60's original independent evidence remains in `w10-replay-guard-review.log`. No earlier reproduction or passing result was removed.

## Repair and executable trust boundary

A shared test-only `ArchiveReaderExecGuard` now reads the exact current parser file and verifies its independently enumerated literal SHA-256:

```text
4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3
```

It independently compiles those bytes using the real trusted filename, mode `exec`, `flags=0`, `dont_inherit=True`, and `optimize=sys.flags.optimize`. The incoming object must have exact type `CodeType` and match the resulting compiled-code identity before the guard records an execution or calls the original real `exec`.

CPython code equality omits `co_filename`, `co_stacksize` and `co_qualname`. The guard includes those three fields explicitly and recursively includes the identity of every nested code object. It therefore retains full code equality while closing these omitted-field cases. Source bytes, filename and module-global tags cannot independently authorize a different executable body. Genuine loader-produced current parser code still executes exactly once in each successful guarded replay.

Both original test classes gained `test_replay_rejects_forged_archive_parser_before_any_execution`. Each runs the complete existing collocated fixture with the exact parser body plus the appended marker substituted at the loader. It requires the specific compiled-code identity assertion, verifies that the real underlying `exec` was never called, verifies an empty marker list, and rechecks unchanged parser bytes. A later incidental replay error cannot satisfy the test. The callable observing `exec` wraps the real function; it neither returns mock success nor blocks an otherwise allowed dispatch.

The precise current-file allowlists, read-only opens, scope-limited ancestor probes, sibling/producer denials, original successful ZIP controls, original failed ZIP rejection, source/manifest closure and drift checks, extraction prohibition, subprocess prohibition and all nonacceptance assertions remain active.

## Final validation

From `/workspace/scratch/98908dfa3444/AI-GPU`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B -m unittest -v \
  test_p06_counter_diagnostics_replay test_p06_counter_public_replay
```

| Execution | Result |
|---|---|
| Before repair: exact pinned parser body plus appended marker, same filename, loader substituted in both whole collocated fixtures | Both genuine replay fixtures passed and both markers executed; concrete witness gap reproduced |
| Final focused scope: previous six methods plus both new forged-parser negatives | **8 passed in 5.412 s**, 0 failures/errors/skips |
| Final complete affected modules | **89 passed in 139.141 s**, 0 failures/errors/skips |
| Final two-file `git diff --check` | Passed |

The focused run observed these parameterized path-guard checks, in addition to its two method-level executable-identity rejection assertions:

| Method | Passing negative subtests |
|---|---:|
| `test_p06_counter_diagnostics_replay.CounterDiagnosticsReplayTests.test_replay_allows_only_current_helpers_when_producer_root_is_current_checkout` | 160 |
| `test_p06_counter_diagnostics_replay.CounterDiagnosticsReplayTests.test_replay_rejects_forged_archive_parser_before_any_execution` | 160 |
| `test_p06_counter_diagnostics_replay.ProducerPathGuardTests.test_active_helper_resolution_rejects_sibling_access_and_ancestor_reads` | 6 |
| `test_p06_counter_diagnostics_replay.ProducerPathGuardTests.test_current_helper_allowance_rejects_write_capable_opens` | 24 |
| `test_p06_counter_public_replay.OriginalPublicReplayTests.test_replay_allows_only_current_helpers_when_producer_root_is_current_checkout` | 160 |
| `test_p06_counter_public_replay.OriginalPublicReplayTests.test_replay_rejects_forged_archive_parser_before_any_execution` | 160 |

The forged-parser methods also run the existing 160-denial collocation matrix, yielding the increased total of 670 path/resolve/write subtests. Every observed subtest parameter set is retained in the log. Compared with base `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, six test methods have been added and none removed. No full local discovery or native build/execution was run.

Agent 60 reports independent passes for the final eight-method/670-subtest scope, both complete forged-loader regressions, eleven direct code/body/type/metadata mutants, and genuine original checked/public replays under the final guards, including the public external-manifest path. Its final explicit disposition is recorded separately by that independent reviewer; this author report does not grant review approval.

## Source identities and retained artifacts

| File | Historical 87-test candidate SHA-256 | Final executable-identity candidate SHA-256 |
|---|---|---|
| `ci/project/test_p06_counter_diagnostics_replay.py` | `e5ac78f0662d8d32c93b3d518a934b7dd57c6d04af81fe1264fae8f3a8754874` | `c8d213737b6332a5e6c924114b3e403a2ddcea3e0a2eac2f1fd431a5f4842430` |
| `ci/project/test_p06_counter_public_replay.py` | `f1c5f13b34794f3cb53c96fce68236445591ac6446436ecbed27d3566be776ec` | `241299ec7abfbbafe857c9d23ea10a0350b2606b10af4d942912780068d01a5d` |

All **29 production reader/closure files**, all **four original ZIPs**, and the successful-public intake receipt match the original pre-repair hash map. The source-inventory validator is included in that unchanged production closure. The failed original public ZIP remains unchanged at `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5`.

The historical patch remains byte-for-byte at SHA-256 `4aec1eb3041e04805260973849c9e287252c26546ebe1398a2ac9c0d57523a76`. The new complete two-file patch against base `4268d2d5d811063bb886cde7bd0e27e61a79c9b4` is `w10-replay-guard-fix-exec-identity.patch`, SHA-256 **`31b2f389479187f15fd1c4698100220d619eb653affb8fe2de608aedf5179585`**. The log's `exec_identity_after_sha256` and `exec_identity_final_integrity` records retain the complete final map and test disposition.

Qualification, warm readiness/execution and all acceptance claims remain false. Replay remains retained-data consistency checking with `native_execution=not_run`. No commit or push was performed by agent 59.
