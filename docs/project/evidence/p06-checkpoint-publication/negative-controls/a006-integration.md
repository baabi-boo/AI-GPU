# A006: qualified warm checkpoint recovery integration

## Scope and ownership

Added only `ci/project/test_p06_checkpoint_run_recovery.py` to the repository.
No production or existing test edits, commits, pushes, native execution,
downloads, or full governance run. Existing synthetic `QualifiedWarmRunTests`
fixtures provide inert children and reports. This is host fault-path evidence,
not native qualification or performance evidence.

Base revision: `858090410a992756808256ace90d36b9b3b88dd3`.

Test module SHA-256:
`c167c3c478caa3cc43bdd7995a8f5a0a85c12a2d27efa79de55a5e56f4176074`.

Shared writer source SHA-256 during the passing run (stable before/after):
`e652ba17b6f97a5945d2753ee822e67e73f19a5fb3c79d18c4d21b21eb37cc7a`.

## Cases and observable assertions

Four test methods cover eight scenarios: each boundary receives one `OSError`
and one `KeyboardInterrupt` from the actual `fsync` call. Injection requires
the descriptor's device/inode to match the actual receipt temporary file and
the serialized document to match the selected event state. No checkpoint
ordinal is used.

| Boundary | Synthetic children completed | Final outcome | Final native disposition |
| --- | --- | --- | --- |
| Initial save | None | `blocked` | `not_run` |
| Preparation launch intent | None | `blocked` | `not_run` |
| Qualified-warm launch intent | Preparation and dependency build | `fail` | `not_run` |
| Post-qualified-warm observation | All three | `fail` | `run` |

Each scenario asserts that the failing writer propagates the same exception
object, leaves the last committed receipt bytes unchanged (or absent for the
initial save), and removes its temporary file. At this boundary hosted
`writers_finished` remains false and `observed_native_execution` remains
`unknown`; pending temporary state never becomes authoritative.

The only subsequent write must be the existing, distinct final failure
receipt. It must finish with the sticky original reason and false orchestration
and acceptance flags, unchanged expected counts/budget, exact child sequence
(no replay), preserved child report/log bytes, and accurate launch/cleanup
facts. Prelaunch failures explicitly preserve nonstart. The post-child case
preserves observed `run` from the child and the last committed `unknown` before
failure. Wrapper `completed_counts` and qualified-report validation digest
remain unset because the selected fault precedes those validation steps.
Hosted final observation must then report `writers_finished=true` and the
final `not_run`/`run` disposition.

## Old-writer reproduction

Command from the source root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/ai-gpu-2bfab0261c05/a006-run-baseline.py > /tmp/ai-gpu-2bfab0261c05/a006-baseline.log 2>&1
```

The scratch launcher extracts only `_write_json` from the exact base revision
with Python AST and installs it in the already imported module in that process.
It does not overwrite shared repository files. The surrounding new test suite
and existing fixture code are unchanged. This isolates old writer behavior;
it is not a complete execution of the old revision.

Result: exit 1, **4 methods / 8 scenario errors in 0.849 seconds**. Every case
ends in `FileExistsError` at the existing final save because the interrupted
checkpoint leaves `qualified-warm-run.json.tmp` behind. Full tracebacks are in
`/tmp/ai-gpu-2bfab0261c05/a006-baseline.log`.

## Repaired-writer result

Command from the source root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s ci/project -p test_p06_checkpoint_run_recovery.py -v > /tmp/ai-gpu-2bfab0261c05/a006-current.log 2>&1
```

Result: exit 0, **4 methods / 8 scenarios passed in 0.884 seconds**, no failures,
errors, or skips. Full output is in `/tmp/ai-gpu-2bfab0261c05/a006-current.log`.
An earlier identical focused invocation also passed in 0.871 seconds.
`git diff --check` passed. Strict governance and independent final-source
review remain outside this task's completed scope.
