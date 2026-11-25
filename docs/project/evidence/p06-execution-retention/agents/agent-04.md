# Agent 04 — frozen input acquisition operational failures

## Scope and disposition

Reviewed `AGENTS.md`, project status/backlog/roadmap/acceptance, the qualified warm automation contract and handoff, acquisition, bounded-process cleanup, and the hosted writer guard. Base revision: `622662ad9cece6da4e3375be7e977dbe04cde862`; other agents' edits were present and left untouched. No commits or publication performed.

Owned changes only:

- `ci/project/p06_qualified_warm_inputs.py`
- New `ci/project/test_p06_input_operational_failures.py`

## Confirmed issue and minimal fix

**F2, high confidence, reproduced:** acquisition `run()` appended a command, then saved its launch checkpoint before calling `run_bounded`. An `OSError` or `KeyboardInterrupt` during that save caused a final failure receipt containing a command without `process_started` or cleanup status even though the bounded executor had never been invoked. The hosted writer guard correctly rejected that unknown command, preventing available failure closeout.

The pre-fix regression failed all eight combinations of `OSError`/`KeyboardInterrupt` at `yaml-cpp-init`, `yaml-cpp-fetch`, `toolchain-part-01`, and `toolchain-part-02`. Each failure occurred after checking that exactly the preceding commands had run; observed status was `None`, expected known unstarted `False`.

The fix leaves launch intent explicitly unknown until observed. Only a failure inside the prelaunch checkpoint sets `process_started=false`, `cleanup_complete=true`, command `outcome=blocked`, `exit_code=null`, and the original nonempty reason. It rethrows for existing failure retention. Exceptions after entering the executor retain unknown status and still block closeout. No retry, fabricated log, resource change, or native execution was introduced.

## Failed-transfer review

No additional defect found in completed unsuccessful transfer retention. Two real local bounded child processes (no network) wrote invalid-UTF-8/NUL/CRLF log bytes and partial archive bytes, then exited 28. Controls with and without a one-time completion-checkpoint failure retained the exact bytes, actual SHA-256/length, nonzero status, cleanup result, earlier verified part, and `network_acquisition=true` for the observed transfer command. No later command ran; the failed part was not renamed into a verified input. These controls passed before and after the production fix.

## Validation

Runtime: prepared CPython 3.12.14, `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, `PYTHONPATH=ci/project`; source-root execution.

Before fix:

```sh
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_input_operational_failures
```

Result: 3 tests, 8 failing subtests, 0.785 s, exit 1. Log: `/tmp/ai-gpu-ae456f837c05/notes/agent-04-before.log`.

After fix:

```sh
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_input_operational_failures test_p06_qualified_warm_inputs test_p06_qualified_warm_writer_receipts
```

Result: **50 tests passed**, zero skips, 3.605 s, exit 0. Log: `/tmp/ai-gpu-ae456f837c05/notes/agent-04-after.log`. Owned tracked diff passed `git diff --check`. This is focused development evidence, not full strict qualification.

## Source SHA-256 identities

| File | SHA-256 |
| --- | --- |
| `p06_qualified_warm_inputs.py` before fix | `e030d5d05abb5d4fdcfd144a25781fbc4a901f51622f88c81a2966df7814e6d7` |
| `p06_qualified_warm_inputs.py` after fix | `56d65c98d543757d0d42bc85e90d7377ffcd2976f6343da12f1e4eefd29e9834` |
| `test_p06_input_operational_failures.py` new | `2f3867cb359dd9fa5a499f66b0aeb9633f81827969cc45b5a9853421f5de50ce` |
| `test_p06_qualified_warm_inputs.py` reviewed fixture | `b396baf71d274919798f54eb9ef5a49dbebf62909b7bdeab548fa28ce441a5f7` |
| `baseline_process.py` reviewed executor | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `p06_qualified_warm_hosted.py` writer-guard dependency at test time; contains agent 01 changes | `eba46917d1cdc7dafea97c98ac92a41313f7ce86b62db40f66de36356651cda5` |
| `xrt_signals.py` reviewed signal helper | `a9531608094a233e5336a35e9fa7ebd028aaa3fc6dd7d3ed0f6f4d3f83a94fb8` |

All file rows are under `ci/project/`.

## Limits and next action

Independent review remains required. Root owns consolidation, strict governance, commits, and publication. No real Git/curl acquisition, original prerequisite archive, GPU execution, encryption, or hosted delivery was exercised. Pins, proofs, budgets, runtime/kernel/simulator code and acceptance claims are unchanged.

Separate static observation, not included as a new reproduced defect: acquisition has no lifetime `terminate_as_interrupt` scope, so SIGTERM outside `run_bounded` may leave its last checkpoint unfinished. The contract already limits cancellation retention to best effort. Root directed this patch to stay narrow. A later cancellation owner should reproduce the signal boundary and, if reusing `xrt_signals.terminate_as_interrupt`, include `ci/project/xrt_signals.py` in the explicit operational helper closure. It is currently absent from `p06_qualified_warm_run.SOURCE_FILES` and therefore from the inherited `p06_qualified_warm_hosted.SOURCE_FILES` (observed 112 entries). Adding it to the run helper inventory would propagate into hosted source retention; no frozen proof or dependency pin needs modification for that operational change.
