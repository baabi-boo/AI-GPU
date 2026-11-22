# Wave 6 checked diagnostic raw-output repair

## Outcome and ownership

Agent 32 repaired the concrete mixed-result-family F2 found by independent
agent 29 and the adjacent explicit `FAIL` / `ERROR` contradiction found by the
root reviewer. Final isolated runs passed **42 checked runner/parser methods
with 909 subtests** and **43 author-disjoint archive replay methods with 167
subtests**. Both runs had zero failures, errors, failed subtests or skips; source
identities were unchanged before and after each run.

Only these repository files were edited:

- `ci/project/p06_checked_execute.py`
- `ci/project/test_p06_checked_execute.py`

The change is 107 inserted lines and 5 removed lines across those two files.
`git diff --check` on the owned files passed. Repository HEAD remained
`81ed6871634fefbf5c78fb27cf10dce913bd4d9c`; the final hashes below identify the
uncommitted tested source. The review followed `AGENTS.md`, the project
acceptance policy and `docs/review/code-review-policy.md`. This author report
does not substitute for the required independent review or maintainer decision.

No replay implementation, independent replay test, public parser, production
model/runtime, gate, golden data or historical evidence was edited. No native
execution, configure/build, full project-governance run, commit or push was
performed.

## Failure reproductions preserved

The original author-disjoint regression appends a genuine
`CHECKED_COUNTERS_FAILURE_RESULT` log from `checked-core-overflow` to the valid
ordinary boundary log, updates the command digest/size and supplies the new
ZIP's external SHA-256. The old boundary parser accepted that contradictory
raw output. Before repair, the exact existing regression ran as **1 test, 1
failure, 0 errors**, in 0.313 seconds. Its failure is retained in the combined
log, alongside the unchanged earlier wave-5 failure notes and log.

The first result-family repair passed 40 checked methods / 737 subtests in
35.593 seconds and all 43 independent replay methods / 167 subtests in 20.694
seconds. Those are intermediate results, not the final tested source. The root
review then found valid checked records could still coexist with explicit
`FAIL diagnostic contradiction` or `ERROR diagnostic contradiction` lines.
Two pre-repair methods reproduced this in both parsers: **4 failing subtests,
0 errors**. Those failures are also retained. The final runs below supersede
the intermediate runs without deleting them.

## Repair design

Both checked validators retain their exact canonical-prefix line selection and
strict JSON/schema/type validation. A small local `_unique_result_family`
predicate now requires exactly one occurrence of the expected reserved result
token, and no occurrence of either other reserved token, across the entire raw
log:

- `CHECKED_COUNTERS_RESULT`
- `CHECKED_COUNTERS_FAILURE_RESULT`
- `COUNTER_PUBLIC_RESULT`

Counting the bare token also detects malformed or embedded records that an
exact trailing-space prefix filter would otherwise ignore. A duplicate,
bare token, tab/colon delimiter, missing delimiter, suffix-appended token,
indented record or prefixed record cannot hide beside a valid result. This
enforces the same family boundary in ordinary/checked boundary results and
all five negative scenarios. No new helper file or retained source-family
inventory entry was needed.

Both checked parsers now use the public parser's existing failure-line rule:
`(?:^|\n)[ \t]*(?:FAIL(?:ED)?\b|ERROR\b)|SIMX_CHECKED_COUNTER_FAILURE`.
Thus explicit `FAIL`, `FAILED` and `ERROR` lines are rejected before or after
the valid result, including leading spaces/tabs. The existing typed counter
failure marker remains rejected anywhere. Neutral dependency/statistics text,
including `ERROR_COUNT`, `FAILED_COUNT` and inline mentions of those words,
remains allowed. Checked results do not acquire a new final-line requirement;
benign dependency noise can still precede or follow them.

The two public-family gaps were coordinated with the disjoint public-parser
owner. That owner applied equivalent reserved-token handling in its own file;
this agent made no public-parser edit.

Seven focused test methods were added to the owned test file. They cover both
boundary variants, all five negative scenarios, mixed-family records in both
orders, malformed/embedded reserved markers, failure-line whitespace/order,
and benign dependency noise. Fake-process runner tests also verify rejection
stops the attempt and preserves all nonqualification flags.

No schema, selector order, count, process-result requirement or acceptance flag
was relaxed. Boundary expectations remain 33 available selectors, 40 source
components, 400 component vectors, 14 split vectors, 33 reset selectors, 10
vectors per selector, 6,389 checks and 1,788 half-reads per variant; unavailable
selectors remain 12. Negative scope/containment expectations are unchanged.

## Final verification

| Isolated test file | Methods | Subtests | Failures / errors / skips | Duration |
| --- | ---: | ---: | --- | ---: |
| `ci/project/test_p06_checked_execute.py` | 42 | 909 | 0 / 0 / 0 | 35.758 s |
| `ci/project/test_p06_counter_diagnostics_replay.py` | 43 | 167 | 0 / 0 / 0 | 18.833 s |

Each run used a fresh `python3 -I` interpreter, prepended the exact absolute
`/workspace/scratch/98908dfa3444/AI-GPU/ci/project` directory, and asserted the
imported test module's absolute path. The logging wrapper used
`unittest.defaultTestLoader.loadTestsFromModule`, counted subtests, and hashed
all four checked/parser/replay/test sources before and after execution. The
wrapper changes reporting only. Equivalent isolated test invocations are:

```sh
python3 -I - <<'PY'
from pathlib import Path
import importlib
import sys
import unittest
root = Path('/workspace/scratch/98908dfa3444/AI-GPU/ci/project')
sys.path.insert(0, str(root))
name = 'test_p06_checked_execute'
module = importlib.import_module(name)
assert Path(module.__file__).resolve() == root / (name + '.py')
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromModule(module))
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
```

Run the same isolated invocation separately with
`name = 'test_p06_counter_diagnostics_replay'` for the independent replay suite.
Whitespace checking used the exact command:

```sh
git diff --check -- ci/project/p06_checked_execute.py ci/project/test_p06_checked_execute.py
```

The original ZIP still passes the unchanged author-disjoint positive test:
7 cells, 17 commands, 270 retained source files, 327 archive files, 45
translation units and 1 link per variant, plus the exact counts above.
`native_execution` remains `not_run`; qualification, readiness, warm execution,
full warm coverage, all acceptance flags and retained-code execution remain
false. This validates retained-data consistency and host parser behavior,
not new native execution or phase acceptance.

## Final identities

| File / input | SHA-256 |
| --- | --- |
| `ci/project/p06_checked_execute.py` | `86ba0b3fd2bbfa97ebb2346e69fed85968fd3da8bf267d4dc1a13aaacf8b358e` |
| `ci/project/test_p06_checked_execute.py` | `90dca95d90108c26c8e8d76658d1d93973d24b46426b1d92cfc1d0f1521c61ad` |
| Unchanged `ci/project/p06_counter_diagnostics_replay.py` | `6284fda2985533e327bddcfa02c2341b8f7c17b1ba123d0a66b3d263187e5b75` |
| Unchanged `ci/project/test_p06_counter_diagnostics_replay.py` | `f954840178f739f21ef7f352985e9bbd3f6080d762bdf6fba72bd7665ac1956a` |
| Original `docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip` | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` |
| Combined `w06-checked-log-fix.log` | `8257859c40386a9825ac18d4a1abb7c10eaba3f86552f8bf92a7b00fdfc9f567` |
| Preserved `w05-checked-replay-tests.md` | `88aaf3c976a080be726bc2cab1874b7159d1b9624b10473bb67108ae8dd7a92c` |
| Preserved `w05-checked-replay-tests.log` | `a14a85aad2d7dd5253c88c816cee9f7d56f51926fba9bb7f782d4b2fcbbe9b6e` |

The externally supplied original producer revision remains
`407ab9fea5e4f793a2a5088f566a87f3e631aa84`. All logs and this note reside under
`/workspace/scratch/98908dfa3444/`; the complete combined record is
`w06-checked-log-fix.log`. Final individual run logs are
`w06-checked-final-focused.log` and `w06-checked-final-replay.log`.
