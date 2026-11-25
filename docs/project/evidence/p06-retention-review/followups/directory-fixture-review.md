# A57 supplement — Hosted directory-replacement test failure

## Conclusion

**The reviewed correction is a faithful test-only portability fix. No production
change or contract relaxation is required by the established evidence.** The
directory mutation is realistic; the old test's assumption that deleting and
recreating an empty directory must produce a different `(st_dev, st_ino)` tuple
is not an allocation-independent precondition. Keeping a descriptor to the
removed directory makes the intended identity-change test deterministic on the
qualified Linux/POSIX platform while preserving the real `rmdir`/`mkdir`
replacement and its rejection/retention assertions.

Confidence is high in the fixture defect, the source-level explanation and the
final test correction. **Exact inode reuse on the failed hosted execution is
an inference**, not an observed fact: the supplied failure excerpt does not
record before/after directory identities. This supplement does not convert
that inference into retained host telemetry or relabel the failed run.

This is the same A57 assignment's follow-up, not another agent. It supplements
`notes/a57.md`; that historical report and all existing evidence were left
unchanged.

## Failure and source scope

Root supplied the original hosted failure reference: published revision
`0c32d04c5d37679bb0273f07a50bd26a2e21a5e8`, Actions run `45575499141`, job
`139072298484`, original artifact `15006112807`. The reported full strict
invocation ran 5,114 tests in 2,311.191 seconds and recorded two failures from
one method:
`test_p06_qualified_warm_restore.QualifiedWarmRestoreTests.test_changed_restored_bytes_and_unexpected_entries_are_detected`.
The directory subcase failed to raise `RestoreError`, then the subsequent
incomplete-marker assertion failed. A40 is independently auditing the original
artifact. A57 did not fetch or independently authenticate that provider
artifact; those execution facts are task-supplied context, not A57 execution.

I independently observed the exact published HEAD above and a clean tree before
the correction. Relevant whole-file hashes:

| File/scope | SHA-256 |
| --- | --- |
| Published and unchanged `ci/project/p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |
| Published and unchanged `ci/project/p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |
| Published `ci/project/test_p06_qualified_warm_restore.py` | `fee089dbe7823d04ecfe7f2dc8f3e378a2e8c49a9fef307e0ad721cd93d646fe` |
| Reviewed corrected `ci/project/test_p06_qualified_warm_restore.py` | `9ef2cb211135a3b4f024056208492a9aef389823d452174c7bfdd8efcab15fb6` |
| Unchanged `docs/designs/qualified_warm_retention_review_v1.md` | `364038856334f0c4c8cf7d7a27fea4d81682a11bbcafee98f6a0a1099e794f01` |

## Source-level root cause

The production restore code records each created directory's device/inode
tuple. `_open_owned_directory` and `_directory_identity` compare reopened
directories to those tuples and require directory type and private mode.
`_verify_tree` additionally checks exact membership and each file's recorded
identity, mode, size, timestamps and digest. Directory stamps are checked for
change **during each verification visit**, not against a creation-time stamp.
The root descriptor remains held; ordinary child directory descriptors are
closed to keep descriptor use bounded by path depth.

The original fixture waits until immediately before the first tree-verification
call, removes the empty `private/empty`, and recreates it with mode `0700`.
It retains no descriptor or name for the removed inode. If the filesystem
reuses the old device/inode tuple, the observed child type, mode, tuple and
empty membership all match. The enclosing directory's new timestamps are
already present when verification takes its first local stamp, so that
within-visit stability comparison does not independently identify the earlier
replacement. There are no incorrect payload bytes or extra members in this
particular case.

Consequently, the original test requires `RestoreError` without first ensuring
that the directory identity it intends to change actually changed. Prior
focused passes are consistent with allocations that selected a different
inode. This explains a reachable filesystem-dependent test failure without
assuming a weakened production check.

The two reported failure records are also consistent with the old test's
control flow: `subTest` records the missing-exception assertion and resumes
after the combined context managers; `assert_incomplete` then runs outside
that subtest and records the second failure. They do not establish two
independent production faults.

## Contract assessment

The published contract explicitly requires stopping writers and describes
repeated descriptor, pathname, identity and digest observations. It expressly
does not guarantee exclusion of every malicious concurrent same-user writer.
It requires verified created-directory identities but does not promise a
persistent inode-generation identifier or hold one descriptor for every
retained directory. The exact file bytes, membership, private modes and named
root are still independently checked.

That limitation is relevant here because the replacement can leave **all
checked directory identity fields unchanged**. It is not a reason to excuse
unchecked content corruption or a missed observable identity mismatch. The
corrected fixture therefore continues to demand rejection of a real, observable
directory replacement, with no change to production acceptance behavior.

A stronger guarantee against this form of identity reuse would be a separate
production design change. Holding all directory descriptors would conflict
with the current depth-bounded descriptor contract. Persisting directory
timestamps would require handling legitimate parent changes during child/file
creation and marker removal; simply recording a creation stamp or taking a
fresh stamp at the first final traversal is not a general solution. No such
broader change is needed to remove this test's unproved allocation assumption.

## One independent targeted probe

I authored and ran one tiny synthetic end-to-end probe against the unchanged
published production bytes, before root changed the test. It builds its own
canonical plaintext tar using `tarfile`, with one empty directory and one inert
payload. It does not import the project's restore test fixture or execute any
retained bytes.

At the first `_verify_tree` call the probe opens the empty directory, holds
that fd, performs the same `rmdir`/`mkdir`, records both identities and calls the
real production verifier. All probe assertions run **outside**
`restore_archive` so its ordinary exception mapping cannot convert a probe
`AssertionError` into the expected `RestoreError`.

Observed once, without retry:

| Observation | Result |
| --- | --- |
| Created directory identity | `(41, 75695)` |
| Held removed directory identity | `(41, 75695)`, link count `0` |
| Replacement identity | `(41, 75697)` |
| Production result | `RestoreError.code == "output-changed"`; no success return |
| Incomplete marker | Retained, `outcome="incomplete"`, restoration false |
| Retained payload and source archive | Exact payload preserved; archive digest unchanged |
| Result scope | Native execution `not_run`; execution/authentication/native/performance/phase fields false |
| Held descriptor lifetime | Still open after rejection, then closed in the probe's `finally` |

The probe exited 0; measured body duration was 0.0024802580010145903 seconds.
Interpreter was the prepared CPython 3.12.14. Source/test hashes were identical
before and after the probe and are recorded in its JSON. These are one local
synthetic scenario's observations, not a reproduction of the original hosted
inode allocation, a new full suite, or a performance measurement.

Exact invocation from the repository root:

```sh
env PYTHONDONTWRITEBYTECODE=1 TMPDIR=/home/agent/ai-gpu-d37f66a85d88/tmp \
  /home/agent/ai-gpu-d37f66a85d88/governance-environment/venv/bin/python3 -B \
  /home/agent/ai-gpu-d37f66a85d88/tmp/a57_inode_review/held_directory_probe.py \
  > /home/agent/ai-gpu-d37f66a85d88/tmp/a57_inode_review/held_directory_probe.json
```

| Supplemental artifact | SHA-256 |
| --- | --- |
| `tmp/a57_inode_review/held_directory_probe.py` | `893a270b7415946de8f0bf67e49618f9695fb1841c21e619b486406461537c07` |
| `tmp/a57_inode_review/held_directory_probe.json` | `c81582e625de9a74f0fc6f750b946c7268fe9c22a09cdf5a62f2cdf3c17c5a8d` |

## Independent review of root's final test-only diff

Reviewed all 20 additions and seven deletions in
`ci/project/test_p06_qualified_warm_restore.py` at the corrected hash above.
**No follow-up finding identified.**

- `ExitStack` is active before the mutation hook executes. The opened directory
  fd is registered immediately, before `fstat`, removal and recreation, and
  remains alive through production rejection and the incomplete-marker check.
- Stack exit closes the test-owned fd on normal completion, assertion failure
  and exceptional unwinding. Production is never given ownership of that fd,
  and no descriptor retry or monkeypatch of the identity checks is introduced.
- The hook records old/new device/inode pairs. Capture length and inequality
  are asserted after `restore_archive` has unwound, so a fixture assertion
  cannot be sanitized into a misleading expected error.
- The directory case additionally requires the exact `output-changed` code.
  Failure to capture either observation or an unrelated fixture error therefore
  cannot satisfy the corrected test.
- All four original byte, extra-entry, symlink and directory mutation cases
  remain. The same incomplete marker and false-claim checks remain within each
  subtest. A missing required exception still fails that subtest; moving its
  marker check inside avoids the old redundant second failure after an already
  failed exception assertion.
- No skip, retry, weaker expected result, removed mutation, production change,
  resource/golden change, acceptance change or governance gate change appears
  in the patch.

`git diff --check -- ci/project/test_p06_qualified_warm_restore.py` exited 0.
The only working-tree change observed at review time was that test file; both
production hashes remained unchanged. Root owns its separate once-only
19-test restore-module execution and source-scoped evidence. A57 did not rerun
that module or count root's execution as its own.

## Limits and disposition

Preserve the original failed strict run and its original artifact. The test
correction does not make that run pass and does not qualify the corrected
revision; any required exact-source strict qualification remains a separate
actual invocation. No waiver is proposed.

A57 performed source review and the single explicitly described probe only.
No tracked file was edited by A57, no earlier report was changed, and no full
suite, repeated test retry, native execution, build, provider access, commit,
push or subagent was used. New follow-up artifacts are this note and the two
small probe files under the assigned task area.
