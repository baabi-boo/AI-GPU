# Agent 009 — preparation and dependency-builder checkpoint integration

## Delivered scope

Added only `ci/project/test_p06_checkpoint_prepare_build.py` (205 lines), reusing
`test_p06_preparation_initial_closeout.PreparationInitialCloseoutTests` and
`test_p06_builder_initial_closeout.BuilderInitialCloseoutTests` setup/cleanup.
No production code, other test modules, commits, or pushes were changed by this
agent. The test file is left for the parent to integrate.

The file contains five test methods, each with `OSError` and empty
`KeyboardInterrupt` subtests (10 interruption cases):

| Checkpoint | Required observed outcome |
|---|---|
| Initial local preparation | Blocked report; zero source/tool/provision observations; no tools directory |
| Preparation immediately after provisioning | Failed report; exactly one synthetic provisioning call; tool receipt retained; no post-provisioning source/tool rechecks |
| Initial dependency builder | Finished blocked report; no source collection, materialization, tools, or command launch |
| Builder command launch intent | Finished blocked report; one explicit unstarted command with completed cleanup; no launch or log |
| Builder command completion | Finished failed report; one synthetic launch result and original log retained; no additional launch |

Failures are injected into `os.fsync` on the actual report temporary inode after
the real writer has opened, written, and flushed it. The `_write_json` wrapper
only records calls and exception observations, delegating every write to the
real implementation; it does not inject a top-level writer exception.

Every case checks original exception object identity, the caller's original
failure reason (`interrupted` for empty `KeyboardInterrupt`), exact failure
inventory, final on-disk report equality, owned temporary cleanup before the
failure leaves the writer, no extra publication attempt, unchanged budgets and
false claims, and absence of a success outcome. Later cases compare the last
committed report bytes before and immediately after the failing writer call,
then verify the terminal write begins from those same committed bytes. Builder
cases additionally prove the hosted reader accepts finished writers only after
terminal publication and still reports native execution as `not_run`.

The builder's command checkpoints run the real `Builder.command` and
`Builder.execute` closeout paths via a synthetic source-observation callback,
consistent with the existing dependency failure-state test pattern. Its
supervisor is mocked and its log/result are synthetic. No native tools,
downloads, compiler processes, or GPU execution were performed.

## Validation

Repository base at validation: `ba88572af0bea1e355af08038abcc1f62773a438`
plus the uncommitted new test file. Original shared writer reference:
`858090410a992756808256ace90d36b9b3b88dd3`.

New test source SHA-256:
`89a9a60da92d4a1510d213e8331360b0546c92b2739ae09c859c50187e4eb15c`.

From the repository root, ran:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/project -p 'test_p06_checkpoint_prepare_build.py' -v
```

Result: **5 methods / 10 interruption subtests passed**, 0.142 seconds, no skips.

Also ran the new module and both reused closeout modules together:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import sys
import unittest
sys.path.insert(0, 'ci/project')
names = ['test_p06_checkpoint_prepare_build', 'test_p06_preparation_initial_closeout',
         'test_p06_builder_initial_closeout']
suite = unittest.defaultTestLoader.loadTestsFromNames(names)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
PY
```

Result: **15 methods passed**, 0.550 seconds, zero failures, errors, or skips.
`git diff --no-index --check /dev/null ci/project/test_p06_checkpoint_prepare_build.py`
also exited 0 with no whitespace findings.

## Original-writer negative control

Using `PYTHONDONTWRITEBYTECODE=1`, parsed
`git show 858090410a992756808256ace90d36b9b3b88dd3:ci/project/p02_matrix.py`
with `ast.parse`, extracted only the `_write_json` function definition, compiled
it with the current module globals, and temporarily patched the function in
memory while running the new test module. No repository file was replaced.

The control reported:

```json
{"errors": 10, "failures": 0, "methods": 5, "revision": "858090410a992756808256ace90d36b9b3b88dd3", "subtest_errors": {"FileExistsError": 10}}
```

Each original-writer case failed terminal publication with `FileExistsError` on
`dependency-preparation.json.tmp` or `report.json.tmp`. This directly reproduces
the retained-temporary defect through both real caller closeout paths. The
control's outer assertions required exactly these 10 errors and exited 0.

An earlier control used the moving `HEAD` name after the parent had committed the
repair, so it selected the repaired function and yielded no regression failures;
its expectation assertion failed. Pinning the observed original revision fixed
the control selection and produced the decisive results above.

These are focused host synthetic checks. They do not claim full governance
qualification, native dependency build acceptance, performance acceptance, or
phase completion.
