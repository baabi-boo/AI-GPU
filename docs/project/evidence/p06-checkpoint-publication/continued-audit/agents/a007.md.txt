# A007 — checkpoint ownership tests

## Result and scope

Added only `ci/project/test_checkpoint_ownership.py` in the repository. The seven
test methods exercise 22 subcases with real temporary directories, regular
files, symlinks, file descriptors and device/inode identities. No production or
design changes were made, and no commits, pushes or subagents were created by
A007.

Reviewed `AGENTS.md`, the project status/roadmap/backlog/acceptance entry points,
`p02_matrix._write_json`, and `docs/designs/checkpoint_publication_v1.md`. No
concrete flaw was found in the repaired implementation within this ownership
scope. Its documented observation-versus-lock and best-effort-cleanup limits
remain necessary.

## Coverage

| Test boundary | Subcases | Evidence checked |
|---|---:|---|
| Foreign temporary replacement before publication | 2 | Regular file and symlink replacement raise the ownership error; previous destination bytes/inode and foreign temporary bytes/inode/link target remain unchanged. |
| Foreign temporary replacement during failure cleanup | 4 | Regular file/symlink, each after `OSError` and `KeyboardInterrupt`; replacement occurs at cleanup's real stat boundary, the created descriptor is still open during the observation, foreign entry survives, original exception identity is retained, and the owned descriptor is subsequently closed. |
| Renamed destination directory with replacement at the old pathname | 4 | Real-directory/symlink replacement, each after `OSError` and `KeyboardInterrupt`; the owned temporary is removed from the moved original directory, while the replacement directory's destination and temporary remain untouched. |
| `fdopen` failure | 2 | `OSError` and `KeyboardInterrupt`; both opened descriptors report `EBADF`, the previous destination survives, and the owned temporary is removed. |
| Unlink cleanup failure | 4 | Each original exception class crossed with `OSError`/`KeyboardInterrupt` cleanup failure; cleanup cannot mask the original exception, failed cleanup leaves the same owned inode, and the owned descriptor still closes. |
| Descriptor close failure and reuse | 4 | File/directory close, each after `OSError` and `KeyboardInterrupt`; actual close followed by `dup2` reuses the descriptor number, the reused descriptor remains valid, both owned close attempts occur once, and the original exception survives. |
| Pre-existing temporary collision | 2 | Regular file and symlink are never adopted, truncated or removed; previous destination survives. |

Only concrete syscall boundaries are patched. Data writes, directory renames,
entry replacement, inode observations, descriptor close/reuse, and filesystem
postconditions use real kernel objects.

## Focused validation

Working directory: `/tmp/ai-gpu-2bfab0261c05/repo`.

Command:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/project -p 'test_checkpoint_ownership.py' -v
```

Result after the final test edit: **7 tests passed in 0.011 seconds**, no failures,
errors or skips. All 22 declared subcases ran.

`git diff --check` reported no whitespace diagnostics. The separate untracked
file check (`git diff --no-index --check /dev/null
ci/project/test_checkpoint_ownership.py`) likewise produced no diagnostics; its
exit status 1 reflects the new-file difference.

## Explicit original-writer negative control

The final negative control binds the original revision explicitly to
`858090410a992756808256ace90d36b9b3b88dd3`, not to moving `HEAD`. It extracts only
that revision's `_write_json` AST node into a copy of the current module's
namespace, installs that function for the isolated Python process, and runs
the three relevant test methods. Other source files and the working tree are
not modified.

Exact command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 - <<'PY'
import ast
import subprocess
import unittest
import p02_matrix as matrix
from test_checkpoint_ownership import CheckpointOwnershipTests

revision = '858090410a992756808256ace90d36b9b3b88dd3'
source = subprocess.check_output(['git', 'show', revision + ':ci/project/p02_matrix.py'], text=True)
function = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == '_write_json')
namespace = dict(vars(matrix))
exec(compile(ast.Module(body=[function], type_ignores=[]), revision + ':_write_json', 'exec'), namespace)
matrix._write_json = namespace['_write_json']
names = ['test_foreign_entry_before_publication_is_preserved',
         'test_renamed_directory_cleanup_uses_opened_directory',
         'test_preexisting_temporary_is_not_adopted']
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(
    CheckpointOwnershipTests(name) for name in names))
assert result.testsRun == 3, result.testsRun
assert len(result.failures) == 6, len(result.failures)
assert not result.errors, result.errors
assert not result.skipped, result.skipped
print('EXPECTED NEGATIVE CONTROL at ' + revision + ': six failing subcases, collision preservation passes.')
PY
```

Observed result: **three methods ran in 0.005 seconds, with exactly six expected
failing subcases and no errors/skips**. The two foreign-entry publication cases
failed because the old writer did not raise an ownership error. The four moved
directory cleanup cases failed because its owned temporary remained. Both
pre-existing collision subcases passed. The outer assertion command exited 0
because those exact negative-control results matched expectations; this is not
a passing result for the old writer.

## Tested source identities

Root advanced the shared repository from the original revision to
`ba88572af0bea1e355af08038abcc1f62773a438` during this task. The repaired writer,
design document and new test file were unchanged between the hash snapshots
taken alongside the final focused execution and during subsequent review.

| File | SHA-256 |
|---|---|
| `ci/project/p02_matrix.py` | `e652ba17b6f97a5945d2753ee822e67e73f19a5fb3c79d18c4d21b21eb37cc7a` |
| `ci/project/test_checkpoint_ownership.py` | `f1d46852480c007f60b88ae617f4cf3cd96e6bec6b01bf5f80e59960a95c2663` |
| `docs/designs/checkpoint_publication_v1.md` | `729e640d86b866191266aa86e4689a0dab83cad3127be126f299d51922c885e8` |

These are focused host filesystem development checks. They do not establish
strict governance qualification, independent original-artifact replay, native
GPU execution, warm-performance measurement, or any phase acceptance.
