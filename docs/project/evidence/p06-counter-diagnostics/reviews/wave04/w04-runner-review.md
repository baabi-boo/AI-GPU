# Wave 4 independent public diagnostic runner review

## Scope and verdict

Reviewed every line of the two new runner/orchestration-test files in the worktree based on published `407ab9fea5e4f793a2a5088f566a87f3e631aa84`. The runner includes root's later workflow-file addition to `CRITICAL`. This reviewer did not author or edit either file.

**No F1, F2 or F3 findings.** Treat the coupled execution/enforcement contract as **R3** even if path classification alone is lower. Independent review is fulfilled for this runner scope. Verdict: **land from this static and host-orchestration scope**, with native execution and the separate C++/build/parser reviews remaining independent obligations. This is not a warm qualification or phase-acceptance decision.

## Exact reviewed identities

| File | SHA-256 | Bytes |
|---|---|---:|
| `ci/project/p06_counter_public_execute.py` | `0da2aba310b5451ef1bff54195bb831a64c416ae6fd62abb69d8333d5da269b6` | 21557 |
| `ci/project/test_p06_counter_public_execute.py` | `71cd970d283bbbbc69e7ea1ca5ae6fc2d308d01166482830e44bf9fa4131892c` | 18347 |

Both hashes were unchanged at completion. The new files are not part of the published base commit; their worktree identities above define this review.

## Checked execution chain

- The runner admits a fresh nonoverlapping work/output pair, requires a clean source checkout with tracked critical inputs and initialized pinned submodules, and enforces a caller-supplied expected revision when provided. The hosted command supplies that revision. There is no development/scope/resource bypass.
- Source retention covers the actual model, full runtime, kernel/public headers, all diagnostic sources, frozen counter inventory, profile/configuration inputs, workflow body, and every tracked `ci/project` source. Every non-test top-level Python helper is hashed at import; the actual local import chain stays in that retained closure. No archived helper is imported or executed.
- The initial checked build is fresh and feeds the strict existing 45-TU parser. Exact generated TCU bytes and their source inputs are validated. The boundary control and preprocessed effective configuration must pass before the public build begins.
- The public build receives the original validated model identities and stamp, then the separately reviewed build parser validates 19 new objects, 44 reused model objects and four links. Binding capture must match the validated object identities. Every established source, tool, dependency, configuration, generated source, header probe, stamp, object and executable/library binding is rechecked before and after every command and again at completion.
- The actual executing interpreter must be CPython 3.12.14 on Linux and have the same resolved path, digest and size as PATH `python3`. Recorded tool binaries and three selected dependency libraries are bound by the shared tool snapshot. The environment omits inherited build controls, preloads and library search overrides; public cells add only the explicit SimX driver selection.
- All five public modes execute as separate bounded processes through the identified interpreter/core-dump-suppression wrapper. Each requires an actual started process, integer zero exit, completed cleanup, pass outcome, absent failure reason, and acceptance of its original log by the public-records validator.
- Resource policy remains 15 GiB free disk, 4 GiB available-memory entry requirement and RSS cap, 16 MiB per-command log cap, two build jobs and one model worker. Configure/build/run deadlines remain 120/1800/180 seconds. No reserve, warning or qualification gate is weakened.
- Failures stop later scenarios, preserve logs and failure records, and finish pending cells as blocked. Final source/tool/input/log/retained-copy drift prevents overall success. Both summary success fields depend on the completed control/cells and final pass outcome; all warm/qualification/performance/phase-acceptance fields remain false.

## Verification actually run

Independent command from the source root:

```sh
python3 -m unittest discover -s ci/project -p 'test_p06_counter_public_execute.py' -v
```

**10 tests passed in 13.344 seconds.** The author's initial handoff estimated 11 methods, but the actual discovered and executed count is 10. The root's earlier receipt independently records the same 10-test inventory passing in 12.702 seconds.

The tests exercise the complete orchestration path, source/resource/interpreter blockers, process and cleanup failures, invalid result rejection, all nine input-binding groups, final source/dependency/log/retained-copy drift, preexisting/overlapping output preservation, and empty/symlink artifact rejection. Their process and public-validator boundaries are deliberately controlled fixtures; they do not establish native execution or independently validate the C++ model results. Strict compiler/result parser tests are separately owned.

Raw independent test log: `w04-runner-review-tests.log`. Machine-readable identity/test receipt: `w04-runner-review-checks.json`. Whitespace inspection and the requested `git diff --check` command found no issue; the current new files are untracked, so the content review and SHA-256 receipt are the definitive scope.

## Limits

No native library/executable was built or run by this reviewer. Hosted native results, dynamic library loading, all actual failure/terminal observations, the mathematical lifetime argument and pinned dependency finalization remain separate evidence. Recorded binary/tool/dependency identities do not authenticate an arbitrary producer or rehash absent archived payloads; the runner explicitly preserves those limitations. Source/artifact rehashing does not claim protection from malicious concurrent filesystem writers.

No repository edit, commit, push, checkout, reset, stash or clean operation was performed.
