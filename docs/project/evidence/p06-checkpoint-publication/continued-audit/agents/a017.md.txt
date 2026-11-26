# A017 — checkpoint directory permission correction review

**Verdict: no blocking findings; high confidence for the supported Linux environment.**

Independent read-only review of the `O_RDONLY` → `O_PATH` correction, both real-filesystem regressions, and `docs/designs/checkpoint_publication_v1.md`. The reviewed working-tree contents were subsequently committed by another actor as `93bb3f0342eff0b469a0da06cb067916af7c539e`. This reviewer did not edit repository files, commit, push, or rerun the full suite.

## Findings and reasoning

- **Correct directory handle and Linux compatibility.** `ci/project/p02_matrix.py:96–97` now opens the parent with `O_PATH | O_DIRECTORY`, removing the accidental requirement to read/list a directory. Linux supports `O_PATH` since 2.6.39, permits it as the directory descriptor for the `*at()` operations used here, and permits closing it. The documented qualification environment already requires Linux CPython 3.12 on x86-64 glibc (`docs/project/governance-runbook.md:37–41`; `ci/project/governance_env.py:190–200`). No non-Linux compatibility is established or claimed by this review.
- **Descriptor operations remain valid.** The parent handle is only an anchor for create/stat/replace/unlink (`p02_matrix.py:104–105,115,118,132–134`) and is closed at `:138–144`. The separately created ordinary file descriptor supplies `fstat`, buffered output, and `fsync` (`:106–114`); no operation requiring an ordinary readable/writable directory descriptor was moved onto the `O_PATH` handle. Directory anchoring and exclusive temporary ownership remain intact.
- **Access controls remain enforced at filesystem operations.** `O_PATH` can acquire a handle without permissions on the final directory itself, but creation, stat, replacement, and unlink still perform their appropriate search/write checks. Bounded real-system probes confirmed this even after permissions were revoked on an already-open directory handle. The correction adds no `chmod`, permission widening, retry, or fallback. New-file mode remains `0666` subject to the process umask (`:104–105`). Permission loss can still prevent cleanup; the existing best-effort limit accurately covers that (`:129–137`; design `:42–47`).
- **Regression coverage exercises the reported compatibility failure.** `ci/project/test_checkpoint_directory_access.py:27–39` performs initial publication and replacement inside a mode-`0300` directory, verifies content and temporary absence, and asserts that publication preserves the mode. The real consumer test at `:41–60` exercises `p04_ci_prepare.prepare()` accepting an existing evidence directory (`p04_ci_prepare.py:113–118`) and writing its blocked receipt (`:198–201`). It explicitly verifies invalid revision, no native execution, and no tool relocation. Both tests use real filesystem operations and the real writer.
- **Test cleanup survives failure paths.** The helper saves the previous mode before mutation and restores it in `finally` (`test_checkpoint_directory_access.py:16–23`). Its scopes exit before either `TemporaryDirectory` cleanup (`:28–39,42–60`), so directory enumeration/removal is not left dependent on mode `0300` when a write or assertion raises. Direct injected `OSError` and `KeyboardInterrupt` probes both restored the original mode. As with any DAC permission test, regression sensitivity depends on running without permission-bypass privileges; this review ran as uid 1000 and verified that the old `O_RDONLY` open fails.
- **Contract remains accurate.** The publication sequence (`docs/designs/checkpoint_publication_v1.md:19–38`), ownership/cleanup limits (`:42–47`), directory-rename anchoring (`:49–52`), and explicit absence of directory durability (`:53–54`) all remain consistent with this correction. No additional durability or concurrency guarantee is introduced.

## Bounded validation

Environment: uid/gid 1000; Linux 6.18.57; Python 3.12.14.

Command: `python3 -m unittest discover -s ci/project -p 'test_checkpoint_directory_access.py' -v` — **2 tests passed**.

Additional temporary-directory probes passed:

1. Writer denied mode `0100`, `0200`, and `0000` parents with `EACCES`; previous target bytes and directory modes preserved; no temporary or descriptor leak.
2. Old `O_RDONLY | O_DIRECTORY` parent open denied mode `0300`, confirming regression sensitivity under this account.
3. An already-open `O_PATH` directory handle did not bypass revoked write/search permission: create, replace, and unlink denied modes `0500` and `0600`; stat denied absent search permission.
4. Test helper restored mode `0700` after injected `OSError` and `KeyboardInterrupt`.

`git diff --check` for the reviewed paths produced no errors. These are focused host checks, not full governance qualification or GPU execution evidence.

## Linux references

- [Linux open(2)](https://man7.org/linux/man-pages/man2/open.2.html): `O_PATH`, allowed descriptor operations, and `openat()` permission errors.
- [Linux rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html): directory-relative replacement and search/write permission checks.
- [Linux unlink(2)](https://man7.org/linux/man-pages/man2/unlink.2.html): directory-relative deletion and search/write permission checks.

## Reviewed content digests

- `ci/project/p02_matrix.py`: `c7544854b1fda853fad7c382e6e51605e812f5a377128fa6198f4da8662d7432`
- `ci/project/test_checkpoint_directory_access.py`: `3fc9d9b3ccb7ffd6b0b1eef0580d0a720a07c0bef95db7f0ef64524da4f2a5e2`
- `docs/designs/checkpoint_publication_v1.md`: `729e640d86b866191266aa86e4689a0dab83cad3127be126f299d51922c885e8`
