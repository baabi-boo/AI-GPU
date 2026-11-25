# Agent 02 — qualified warm supervisor failure accounting

Base revision: `622662ad9cece6da4e3375be7e977dbe04cde862`.

## Finding and correction

Confirmed a reachable prelaunch checkpoint failure misclassifies an unstarted
stage as an unresolved launch. Injecting one `OSError` immediately before the
qualified-warm child call produced a finished outer receipt with
`native_execution="unknown"`, `process_started=null`, and no stage
`cleanup_complete`, `finished_at`, `outcome` or `reason`; observed child calls
were only preparation and dependency-build. A first-stage checkpoint failure
also incorrectly changed the overall disposition to `fail` despite no launch.
Unknown starts block writer-finished closeout even though the failed checkpoint
made invoking the child impossible.

The wrapper now catches errors only around its prelaunch checkpoint and marks
the known unstarted stage `process_started=false`, `cleanup_complete=true`,
`outcome="blocked"`, finished, with the original reason. A qualified-warm stage
in this condition records `native_execution="not_run"`. The exception continues
through existing failure closeout. No child report or log is synthesized. Errors
inside `run_bounded` retain the existing unknown-start behavior.

Owned changes:

- `ci/project/p06_qualified_warm_run.py` — eight added lines around the launch checkpoint.
- `ci/project/test_p06_warm_supervision_failures.py` — one focused test with six subcases (all three stages, `OSError` and `KeyboardInterrupt`), reusing the existing controlled orchestration fixture.

## Reproduction and validation

All commands ran from the source root with `PYTHONDONTWRITEBYTECODE=1`,
`TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, `PYTHONPATH=ci/project`, and
`PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin`.
Interpreter: `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`.

1. Baseline: `python3 -B -m unittest test_p06_qualified_warm_run -q` — 20 tests, 4.084 seconds, OK.
2. Before implementation: `python3 -B -m unittest test_p06_warm_supervision_failures.QualifiedWarmSupervisionFailureTests -v` — one test, six failing subcases, 0.806 seconds. Failures reproduced incorrect first-stage `fail`, unresolved launch state, and incorrect native `unknown`.
3. After implementation: `python3 -B -m unittest test_p06_warm_supervision_failures test_p06_qualified_warm_run test_p06_qualified_warm_writer_receipts -q` — 34 tests, 4.893 seconds, OK, zero failures/errors/skips. Existing interrupted-monitor regression still requires unknown native execution and retains partial report/log bytes.
4. `git diff --check -- ci/project/p06_qualified_warm_run.py ci/project/test_p06_warm_supervision_failures.py` — exit 0.

## Reviewed boundaries and limitations

Read AGENTS, project status/roadmap/backlog/acceptance and the qualified warm
automation contract. Inspected selected source/input hashing, successful report
population reconciliation, native source snapshot descriptors, child terminal
binding, bounded process cleanup, and the native producer's checkpoint order.
Rejected the initial suspicion that a natural interrupted native launch leaves
the child disposition at `not_run`: that producer checkpoints `unknown` before
each possible first launch. No change was justified there.

Tests use controlled child records and fault injection, not native execution or
strict qualification. Persistent write failures, incomplete temporary checkpoint
files, forced process death and descendant groups remain outside this focused
correction. The 24-process/792-launch/25,344-word population, immutable proofs,
kernel/runtime/simulator/numeric/performance contracts and every resource bound
are unchanged. No commits or publication were performed.

Next action: independently review the narrow launch-boundary correction, combine
it with hosted terminal-disposition reconciliation, and run the final revision's
required full strict qualification before an admitted native experiment.

## SHA-256

| File | SHA-256 after review/change |
| --- | --- |
| `ci/project/p06_qualified_warm_run.py` | `7108581a9317f4dc22741975173e8fd7dd6bfcbfacbd80ac35e30622320b9337` |
| `ci/project/test_p06_warm_supervision_failures.py` | `c8f81e415fd9a9625403cba2a4c767a45ec1883919b13c7992be59e39f77e264` |
| `ci/project/baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `ci/project/p06_managed_preflight_execute.py` | `2aa330b428852b3b0f0acc9bcc32cc464959b7f255d709f13cde310319b2fe4e` |
| `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |
