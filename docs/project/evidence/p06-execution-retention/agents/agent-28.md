# Agent 28 — packaging output setup cleanup

## Scope and result

Implemented the concrete output descriptor leak independently reproduced by
Agent 27, on the shared dirty tree over HEAD
`622662ad9cece6da4e3375be7e977dbe04cde862`. Read `BRIEF.md`, repository
`AGENTS.md`, relevant status/backlog/roadmap/acceptance context, the qualified
warm automation retention contract, and Agent 27's report and source identities.

Only two repository files were edited by this agent:

- `ci/project/p06_qualified_warm_pack.py`: the `_package` output setup block only.
- New `ci/project/test_p06_pack_setup_cleanup.py`: focused real-descriptor regression.

The existing setup acquired `output_fd`, then closed its parent descriptor
before entering the later `output_fd` lifetime guard. A parent close that
consumed its descriptor and raised EIO escaped with the output descriptor open.
The fix initializes the output descriptor sentinel and encloses setup in a
failure cleanup guard. If setup fails after output acquisition, it attempts
output close exactly once, preserves the original exception even if that close
raises, and never retries the consumed parent. Successful setup continues into
the existing packaging lifetime and recovery behavior.

The regression uses actual directory descriptors and actual `close`, then
immediately reopens `/dev/null` at the consumed parent's exact descriptor number
before raising the injected EIO instance. Both complete and partial public APIs
must preserve that instance and the unrelated descriptor, release output, and
make exactly one close attempt per owned descriptor. Additional cases inject
OSError and KeyboardInterrupt after output cleanup consumes its descriptor.
The tests also establish that inventory has not started at this boundary.

## Reproduction and validation

All commands ran from `/tmp/ai-gpu-ae456f837c05/AI-GPU` under prepared CPython
3.12.14, `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`,
with `PYTHONDONTWRITEBYTECODE=1` and
`TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`. The affected-module run additionally used
`PYTHONPATH=ci/project` and the prepared environment's `bin` first in `PATH`.

```sh
python3 -m unittest discover -s ci/project -p test_p06_pack_setup_cleanup.py -v
```

- Before production edit: **2 tests, 6 failed subcases, 0.008 seconds, exit 1**.
  Every failure was the same concrete leaked-output-descriptor assertion.
  The parent EIO and unrelated reused descriptor assertions already passed.
  Log: `agent-28-red.log`.
- After production edit: **2 tests, 6 passed subcases, 0.006 seconds, exit 0**.
  Log: `agent-28-green.log`.

```sh
python3 -m unittest -v test_p06_pack_setup_cleanup test_p06_qualified_warm_pack test_p06_pack_operational_failures test_p06_directory_cleanup_review test_p06_qualified_warm_encrypt test_p06_qualified_warm_retention_integration
```

**90 tests passed, zero failures/errors/skips, 4.006 seconds, exit 0**.
Log: `agent-28-affected.log`.

`git diff --check -- ci/project/p06_qualified_warm_pack.py ci/project/test_p06_pack_setup_cleanup.py`
returned exit 0. Final source hashes were rechecked after validation.

## Source identities

| File / state | SHA-256 |
| --- | --- |
| `p06_qualified_warm_pack.py`, before | `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a` |
| `p06_qualified_warm_pack.py`, after | `e4cff314b8a2a0dbb277baef1bc5b3eb78b10a90f777a4d3b60ff74b682dac0e` |
| `test_p06_pack_setup_cleanup.py` | `206756440cdfc4bbac6370d8f664db5c4dfdb9acc4b2eb3f644a48817ed85991` |

## Limits and next action

The correction and focused evidence were sent promptly to the coordinator for
fresh independent review. This report is implementation evidence, not independent
approval. No other production behavior, native code, thresholds, proof, golden
data, acceptance records, or tooling gates were changed. No commits or pushes
were made. No native/hardware run, full strict governance qualification, fresh
warm performance result, or phase acceptance is claimed. Full strict governance
and publication remain the coordinator's work on the final frozen tree.
