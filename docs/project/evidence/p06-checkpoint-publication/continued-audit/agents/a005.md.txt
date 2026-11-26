# A005: Direct checkpoint writer fault regression

Completed only `ci/project/test_checkpoint_write_failures.py` in the repository.
No commits, pushes, native execution, builds or changes to other owned files.

## Tested source

- Repository base: `858090410a992756808256ace90d36b9b3b88dd3`.
- Fixed working-tree `ci/project/p02_matrix.py` SHA-256:
  `e652ba17b6f97a5945d2753ee822e67e73f19a5fb3c79d18c4d21b21eb37cc7a`.
- New `ci/project/test_checkpoint_write_failures.py` SHA-256:
  `0d08db14a774b24dff87acba44d2b43622bf88aa3ed81bf35e4a0a6ce8adb420`.

## Coverage and isolation

The four methods have 27 explicit subtests. All fixtures use real temporary
directories, each scoped to its individual fault/input subtest. Context managers
restore every patch before verifying output and performing a caller-requested
second write. The baseline's retained temporary files are also removed by these
fixture context managers; a failed assertion cannot contaminate the next case.

1. Sixteen fault subtests exercise partial write, flush, fsync and replacement
   with `OSError` and `KeyboardInterrupt`, both with and without an existing
   checkpoint. They check the exact exception object, one failing stage call,
   closed real streams, actual partial/full temporary bytes at the fault, a
   byte-for-byte preserved old final or absent new final, removal of the owned
   temporary, and a successful later explicit write with no extra files.
2. Five serialization subtests exercise an unsupported object, NaN, positive
   and negative infinity, and a circular list. All file-opening boundaries fail
   if reached, establishing rejection before file I/O while preserving the old
   checkpoint and directory entries.
3. Two key-order subtests verify literal expected bytes, indenting, sorting,
   escaped non-ASCII text and final newline. An actual 16 MiB encoded JSON string
   succeeds; 16 MiB plus one byte fails before opening anything. Boundary checks
   use stat and two-byte edge reads rather than retaining another full-sized
   expected byte buffer.
4. Four pre-existing temporary-entry subtests cover a regular file, valid
   symlink, dangling symlink and directory. Each must raise `FileExistsError`
   and preserve the entry's inode, its content/link target, foreign content and
   previous final bytes.

Stream injection intercepts ordinary binary open boundaries (`io.open` and
`builtins.open`) and wraps only the real writable stream matching the temporary
inode. The suite works unchanged with the baseline's `Path.open` and the fixed
writer's descriptor-based `os.fdopen`; it asserts neither implementation's open
call counts. `fsync` and `replace` injection occurs at their actual operation
boundaries and delegates unrelated calls.

## Fixed result

From `/tmp/ai-gpu-2bfab0261c05/repo`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -m unittest -v test_checkpoint_write_failures
```

Result: **4 tests passed in 0.226 seconds**, with 27 successful subtests and zero
failures, errors or skips. `git diff --check` also passed. These are focused host
development checks; they do not qualify the changed revision or establish
native GPU evidence.

## Baseline reproduction

The baseline's `_json_bytes` and `_write_json` function ASTs were extracted from
`git show 858090410a992756808256ace90d36b9b3b88dd3:ci/project/p02_matrix.py` and
compiled into a copy of the imported module namespace. Only the writer function
reference was replaced in that isolated Python process. The same new test suite
was then run without changing its fixtures or assertions.

Exact reproduction command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 - <<'PY'
import ast
import subprocess
import unittest
import p02_matrix as matrix
import test_checkpoint_write_failures as tests

revision = '858090410a992756808256ace90d36b9b3b88dd3'
source = subprocess.check_output(['git', 'show', revision + ':ci/project/p02_matrix.py'], text=True)
nodes = [node for node in ast.parse(source).body
         if isinstance(node, ast.FunctionDef) and node.name in ('_json_bytes', '_write_json')]
assert len(nodes) == 2
namespace = vars(matrix).copy()
exec(compile(ast.Module(body=nodes, type_ignores=[]), revision + ':ci/project/p02_matrix.py', 'exec'), namespace)
matrix._write_json = namespace['_write_json']
with open('/tmp/ai-gpu-2bfab0261c05/a005-baseline.log', 'w') as log:
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(tests))
print('baseline_revision=' + revision)
print('tests=%d failures=%d errors=%d skips=%d' % (
    result.testsRun, len(result.failures), len(result.errors), len(result.skipped)))
assert result.testsRun == 4
assert len(result.failures) == 16
assert not result.errors and not result.skipped
assert all('test_io_faults_preserve_final_and_allow_a_later_explicit_write' in case.id()
           and 'self.assertFalse(os.path.lexists(temporary))' in failure
           for case, failure in result.failures)
print('All 16 failures expose the retained owned temporary; the other three methods pass.')
PY
```

Observed: **4 tests run, exactly 16 failing fault subtests, zero errors or skips**.
Every failure is the assertion that the owned temporary no longer exists; the
baseline leaves it behind at all four injected stages for both exception kinds
and both previous-final states. The other three methods pass. The wrapper exits
zero only after confirming that exact expected baseline failure pattern.

Full unittest failure output is retained at
`/tmp/ai-gpu-2bfab0261c05/a005-baseline.log`.

Detailed concurrent replacement and descriptor adversaries are assigned
separately by the parent agent and are outside this file's bounded scope.
