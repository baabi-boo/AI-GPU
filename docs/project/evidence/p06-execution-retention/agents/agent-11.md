# Agent 11 — independent encryption publication review

## Scope and verdict

Reviewed every changed hunk in `ci/project/p06_qualified_warm_encrypt.py` against
HEAD `622662ad9cece6da4e3375be7e977dbe04cde862`, the entire new operational test
module, the existing encryption test module, and the complete encryption,
publication, rollback and nonblocking pump implementation. Read `AGENTS.md`,
the task brief, agent 05's report, current project/acceptance context, review
policy and the applicable automation/retention delivery contracts.

**No unresolved F2/F3 finding.** Production and previously existing test files
were read-only. No commits or git publication occurred. The sole repository
addition is `ci/project/test_p06_encrypt_publication_review.py`.

## Independent boundary analysis

- `_verify_directories` performs no-follow traversal of each complete named
  chain and compares every original device/inode pair. Source binding uses the
  chain captured before inventory; destination/private binding uses the
  originally opened parent chain plus each retained leaf identity. It therefore
  rejects a replacement ancestor even if the original leaf is restored below it.
- The initial post-inventory check precedes age launch. The pre-publication
  check precedes either public link. The post-fsync check precedes `committed =
  True`. The final check can report a failed invocation after private-link
  cleanup, but cannot revoke an already committed public pair.
- Ownership is registered before potentially interruptible hardlinks. Before
  commit, rollback withdraws its owned pass summary first and removes public
  ciphertext only if the private inode still exists. Unrelated replacements
  survive. After commit, either private unlink can complete and then raise
  without deleting the last public ciphertext.
- The patch does not change the nonblocking three-pipe pump, bounded chunk
  sizes, exact tar count, ciphertext/stderr caps, disk margin, deadline checks,
  process-group cleanup, summary schema or encryption recipient validation.
  Existing overflow, stalled child, descendant cleanup and disk-failure checks
  passed during this review.

## New critical regression and negative control

The additional test challenges the combination missing from the prior tests:
after the first real public hardlink succeeds, remove the private ciphertext
link and move the public directory, either leaving its original name absent or
replacing it with a directory containing unrelated bytes. The second hardlink
and directory fsync still run against the retained directory descriptor.

Both scenarios must reject the named-path drift, retain the public ciphertext
as the last valid copy, preserve the private summary's exact ciphertext
size/digest, report `publication_committed=false`, write a failed public
summary in the displaced owned directory, leave source bytes unchanged and
leave an unrelated replacement directory untouched. Both pass on the candidate.

As a negative control, loaded the unchanged HEAD encryption source into an
isolated Python module without changing repository files and ran this new test.
Both subcases failed specifically with **`EncryptionError not raised`**: the
old code returned success at the displaced location. The negative-control log
is `notes/agent-11-head-control.log` (one method, two expected failures, 0.070 s).

## Commands and actual results

Working directory: `/tmp/ai-gpu-ae456f837c05/AI-GPU`.

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PYTHONPATH=ci/project /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_encrypt_operational_failures test_p06_qualified_warm_encrypt
```

**51 tests passed in 3.393 s**, zero failures/errors/skips; exact output in
`notes/agent-11-focused.log`.

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PYTHONPATH=ci/project /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_encrypt_publication_review test_p06_encrypt_operational_failures test_p06_qualified_warm_encrypt
```

**52 tests passed in 3.469 s**, zero failures/errors/skips; exact output in
`notes/agent-11-validation.log`. `git diff --check` for the reviewed tracked
production change passed. The added test's no-index whitespace inspection
reported no diagnostics (exit 1 is the expected new-file difference).

All `notes/` paths above are beneath `/tmp/ai-gpu-ae456f837c05`, outside the
repository.

## Reviewed source SHA-256

| File | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_encrypt.py` | `015ef01b1418ef5ef5328859c905854c928ab7c996aba9352603383ef648ca24` |
| `ci/project/test_p06_encrypt_operational_failures.py` | `5804c519149e3131c6183286c3c599d1b27f9849a4139d24765c311691169e88` |
| `ci/project/test_p06_qualified_warm_encrypt.py` | `10a104f429e47584339e3bcc0cf77ed6bf3ad13b054b1233de7253c0d8323b4c` |
| `ci/project/test_p06_encrypt_publication_review.py` | `94167a1faada5d880d73e4f89006c3fd96c65f859cdd75c3fe89ceecdf77d5ed` |

## Limits and next action

These checks use the explicit synthetic age subprocess fixture. They establish
orchestration and filesystem behavior, not cryptographic security, real age
roundtrip, native execution or phase acceptance. Full strict governance was not
run by this reviewer. The documented exclusions remain: no atomic multi-file
crash transaction, no hard exclusion of concurrent same-user mutation, and no
guarantee that failed storage or abrupt termination permits rollback. The
initially green base does not qualify these changed bytes. Root should include
the review regression in final frozen-source strict qualification; the native
qualified warm experiment remains unstarted.
