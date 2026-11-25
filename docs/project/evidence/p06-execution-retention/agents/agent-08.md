# Agent 08 — independent launch-boundary and retention review

## Scope and verdict

Base HEAD: `622662ad9cece6da4e3375be7e977dbe04cde862`. Read `BRIEF.md`,
`AGENTS.md`, agent 02/04 notes, the qualified warm automation contract,
the review policy, and relevant project status/backlog/roadmap/acceptance.
Reviewed every changed hunk in `p06_qualified_warm_run.py` and
`p06_qualified_warm_inputs.py`, both new operational test modules, the bounded
executor, existing fixture tests, and hosted `writers_finished` interoperability.

**No F2/F3 finding in the reviewed changes.** The new catches enclose only
the checkpoint immediately before `run_bounded`. Their known-unstarted
`process_started=false` and `cleanup_complete=true` statements are justified
because control cannot have entered the executor. Exceptions after entering
the monitor do not reach either new catch. Existing native observations remain
separate from whether the wrapper received an executor result.

Production files were read-only. The only repository addition is
`ci/project/test_p06_prelaunch_review.py` (two tests, four independent scenarios).
No commits or publication were performed.

## Independent controls and observations

- An integrated third-stage prelaunch checkpoint failure leaves exactly the
  earlier preparation/dependency stages observed, records the warm stage as
  known unstarted with `native_execution=not_run`, creates no warm child report
  or log, and permits the actual hosted writer guard to close out.
- A real bounded local Python child writes a finished failure receipt with
  trailing space/CRLF plus an invalid-UTF-8/NUL/CRLF combined log, then exits 23.
  Both exact byte strings and their SHA-256/length remain retained. The child
  launches no GPU, compilation or network operation.
- The same completed child followed by a one-time completion-checkpoint error
  retains every field of the returned executor result, including
  `process_started=true`, actual exit 23 and completed cleanup. The hosted
  writer guard accepts the finished failed attempt.
- If the same completed child leaves files but the monitor raises before
  returning its result, the wrapper retains `process_started=null` and no
  observed cleanup result. Existing child files cannot authorize hosted
  closeout: `writers_finished` returns false. The child report's observed
  `native_execution=not_run` does not invent an executor observation.

The authored acquisition regression independently passed its real local
failed-transfer controls: both with and without a completion-checkpoint error,
the exact failed log/partial bytes, earlier verified part, exit 28, cleanup and
observed network-command classification remain intact. The checkpoint-before-
launch cases and monitor interruption controls also passed.

## Actual commands and results

All commands ran from `/tmp/ai-gpu-ae456f837c05/AI-GPU` with:

```sh
PYTHONDONTWRITEBYTECODE=1
TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp
PYTHONPATH=ci/project
PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin
```

Interpreter: `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`
(prepared CPython 3.12.14).

```sh
python3 -B -m unittest -v test_p06_warm_supervision_failures test_p06_input_operational_failures test_p06_qualified_warm_run test_p06_qualified_warm_inputs test_p06_qualified_warm_writer_receipts
```

Result: **71 tests in 9.199 seconds, OK**, exit 0; zero failures/errors/skips.

```sh
python3 -B -m unittest -v test_p06_prelaunch_review
```

Result: **2 tests in 0.568 seconds, OK**, exit 0; zero failures/errors/skips.

```sh
git diff --check -- ci/project/p06_qualified_warm_run.py ci/project/p06_qualified_warm_inputs.py
```

Result: exit 0, no diagnostics.

```sh
git diff --no-index --check /dev/null ci/project/test_p06_prelaunch_review.py
```

Result: exit 1 because the new file differs from `/dev/null`; no whitespace
diagnostics. Source identities below were collected with `sha256sum`; base HEAD
was observed with `git rev-parse HEAD`.

## Source SHA-256 identities at review/test time

| File | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_run.py` | `7108581a9317f4dc22741975173e8fd7dd6bfcbfacbd80ac35e30622320b9337` |
| `ci/project/p06_qualified_warm_inputs.py` | `56d65c98d543757d0d42bc85e90d7377ffcd2976f6343da12f1e4eefd29e9834` |
| `ci/project/test_p06_warm_supervision_failures.py` | `c8f81e415fd9a9625403cba2a4c767a45ec1883919b13c7992be59e39f77e264` |
| `ci/project/test_p06_input_operational_failures.py` | `2f3867cb359dd9fa5a499f66b0aeb9633f81827969cc45b5a9853421f5de50ce` |
| `ci/project/test_p06_prelaunch_review.py` | `c02d423ca1a3533fcf5ec7fe055ff6ff5e012f5010e5d6c0fbf35309568411ae` |
| `ci/project/p06_qualified_warm_hosted.py` | `eba46917d1cdc7dafea97c98ac92a41313f7ce86b62db40f66de36356651cda5` |
| `ci/project/baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `ci/project/test_p06_qualified_warm_run.py` | `6d695dcc9f4217a999033f38e5594e3efb1072e432a92288143bf11be1bccf27` |
| `ci/project/test_p06_qualified_warm_inputs.py` | `b396baf71d274919798f54eb9ef5a49dbebf62909b7bdeab548fa28ce441a5f7` |
| `ci/project/test_p06_qualified_warm_writer_receipts.py` | `c64e6d85b9c09dbd6a92e996cfb148bc24e5c67d14f8ea4770a7faed8a05458f` |
| `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |

## Limits and next action

This review covers the listed identities. After testing, root assigned agent
10 additive CLI SIGTERM handling in inputs/run/hosted. Those subsequent changes
require their own review; this note does not claim them. All production hashes
above matched the original authors' reviewed versions when collected.

Focused checks use controlled source/resource admission and synthetic child
receipts. They do not establish actual network acquisition, native execution,
full strict qualification, encryption/delivery, full descendant containment or
recovery from persistent write failure/forced process death. The frozen proof,
counts, resource thresholds, native implementation and acceptance claims are
unchanged. Root should retain the new independent regression, review the later
signal changes separately, then qualify the final complete source revision.
