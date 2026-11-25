# Agent 23 — directory traversal ownership

## Scope and finding

Reviewed `p06_qualified_warm_pack._directory` and
`p06_qualified_warm_encrypt._directory` against the repaired control helper.
Both sibling helpers opened the child, closed the parent, then transferred
the local descriptor variable to the child. If parent close consumed the
descriptor and subsequently reported EIO, exception cleanup retried the
consumed number and leaked the opened child. A different opener could already
own that number. A second close failure also replaced the original exception.
This is a concrete F2 finding, high confidence, demonstrated by real local
file descriptors and deterministic injected post-close errors.

The new regression opens real ancestor directories, really closes the parent,
immediately opens `/dev/null` to reuse its descriptor number, then raises EIO.
It checks preservation of the unrelated descriptor, release of the opened
child, and identity of the original exception even when child cleanup consumes
its descriptor and reports ENOSPC. Both production helpers failed before the
repair: 2 test methods, 10 failed subtest assertions, zero skips.

## Changes

- `ci/project/p06_qualified_warm_pack.py`: transfer the owned descriptor to the
  child before closing the parent; best-effort failure cleanup preserves the
  active exception.
- `ci/project/p06_qualified_warm_encrypt.py`: the same ownership correction,
  retaining ancestor identity collection and existing success semantics.
- New `ci/project/test_p06_directory_cleanup_review.py`: two targeted methods
  exercising both production helpers with real descriptors.

No control, retention-reader, restore, format, gate, threshold, resource-budget,
publication, ciphertext-cleanup or measured-kernel edits. Existing concurrent
changes in the owned production files were preserved. No commits were made.

## Validation

Run from `/tmp/ai-gpu-ae456f837c05/AI-GPU` with
`PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`,
`PYTHONPATH=ci/project`, and prepared CPython 3.12.14 at
`/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`.

Before repair:

```sh
python3 -m unittest -v test_p06_directory_cleanup_review
```

Expected failing reproduction, exit 1; complete log: `notes/agent-23-before.log`.

After repair:

```sh
python3 -m unittest -v test_p06_directory_cleanup_review test_p06_qualified_warm_pack test_p06_qualified_warm_encrypt test_p06_pack_operational_failures test_p06_encrypt_operational_failures test_p06_encrypt_publication_review
```

**91 tests passed, zero skips, 4.662 seconds, exit 0.** This includes existing
tests of packaging failure retention, directory replacement, publication rollback,
and preserving the last ciphertext. Complete log: `notes/agent-23-after.log`.
`git diff --check` on the three owned paths passed.

## Source identities

| File | Before this change SHA-256 | After this change SHA-256 |
| --- | --- | --- |
| `ci/project/p06_qualified_warm_pack.py` | `b67c66bace419f08fa57ae244e81af21477f634d2d9d3be853393ea8f287fd6f` | `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a` |
| `ci/project/p06_qualified_warm_encrypt.py` | `015ef01b1418ef5ef5328859c905854c928ab7c996aba9352603383ef648ca24` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `ci/project/test_p06_directory_cleanup_review.py` | New file | `0ae6b592c82c81b7191280137c73a7f5109cded9f0fa5e377eb2315f30ab32aa` |

## Limits and next action

Host filesystem fault injection establishes these descriptor-ownership paths;
it does not establish real filesystem EIO frequency, native execution,
encryption authentication, performance or phase acceptance. Full strict
governance remains root's final-tree obligation. Root should obtain independent
review of these two added production hunks and refresh any consolidated source
hashes to the after-change identities above.
