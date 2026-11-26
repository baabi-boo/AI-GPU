# A008 acquisition checkpoint integration

## Scope

Added only `ci/project/test_p06_checkpoint_input_recovery.py` in the repository.
No production files or existing tests were changed by this agent. No commit,
push, download, native workload, provisioning, or subagent was performed.

Original base revision: `858090410a992756808256ace90d36b9b3b88dd3`.
Tests ran on the shared working tree containing the repaired `p02_matrix.py`.
Its SHA-256 at verification was
`e652ba17b6f97a5945d2753ee822e67e73f19a5fb3c79d18c4d21b21eb37cc7a`.
The new test file SHA-256 was
`d448b778848504a1c837fd822f13c57b49ac34ad803a41f0ea6c4d119af95d19`.

## Coverage

Two test methods contain six subtests: one-shot `OSError` and
`KeyboardInterrupt` at the initial receipt, first Git-fetch prelaunch receipt,
and first toolchain-download prelaunch receipt. They reuse the existing
`QualifiedWarmInputAcquisitionTests` inert Git fixtures and synthetic command
runner.

The fault is injected into `os.fsync` only after matching the real descriptor's
device/inode to the acquisition receipt's real temporary file and reading its
flushed JSON. `_write_json` is wrapped solely to observe publication state;
all writes execute the actual shared writer.

Assertions cover preservation of the previous receipt, removal of the owned
temporary file after failure, one ordinary finished finalization save, the
original failure reason, blocked first-save and failed later-save outcomes,
hosted writer completion, and no native/acceptance/cache success claims.
The prelaunch cases retain completed command rows and log bytes, identify the
pending command as never started, and prove no command retry or archive
download occurred. Network accounting is false before the first synthetic
fetch and true only after the fixture has reported completed synthetic fetches.

## Validation

1. `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/project -p 'test_p06_checkpoint_input_recovery.py' -v`
   — PASS, 2 methods / 6 subtests, 0 failures/errors/skips, 0.294 seconds.
2. `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -m unittest test_p06_checkpoint_input_recovery test_p06_input_initial_closeout test_p06_qualified_warm_inputs`
   — PASS, 38 methods, 0 failures/errors/skips, 3.192 seconds.
3. AST-loaded only the original `_write_json` function from revision
   `858090410a992756808256ace90d36b9b3b88dd3`, substituted it in memory, and reran
   the new class. The extraction command used `git show HEAD:ci/project/p02_matrix.py`
   before the repaired writer became local commit `ba88572`; this result is
   bound to the original revision above, not to the subsequently changing HEAD.
   Both methods produced the expected six subtest errors:
   every original-writer case escaped finalization with `FileExistsError`
   because `input-acquisition.json.tmp` remained. No repository mutation was
   used for this comparison.
   The original `ci/project/p02_matrix.py` SHA-256 is
   `e65eca7ac42705f175c296165d9579389d7db8a2deb7542d6eded8337bc83c17`.
   The original function source SHA-256 (the UTF-8 bytes returned by
   `ast.get_source_segment`, without an added newline) is
   `02196c8d6a11f0cef0ac4a153878d4b80535cca6bf3a2afdbf6e5f8ba64ee1df`.
   These historical hashes were checked from the explicit immutable revision
   during evidence clarification; the test suite was not rerun.
4. `git diff --check` — PASS for tracked working-tree edits.

These are focused synthetic development checks, not strict governance
qualification or native/performance acceptance evidence.
