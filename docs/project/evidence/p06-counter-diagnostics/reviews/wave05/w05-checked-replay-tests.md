# Wave 5 independent all-33 checked-counter replay tests

## Outcome

**43 test methods ran: 42 passed, 1 failed; 0 errors, 0 skipped.** The final
bounded run took **20.134 seconds** and recorded **167 subtests**, none of which
failed. The single failed method is outside a subtest loop and deliberately
retains the concrete unresolved finding below. This is not a green test result.

The positive original archive replays successfully as retained-data consistency:
**7 cells, 17 commands, 270 retained source files, 327 archive files**, 33 selectors
per variant, 40 source components per variant, 6,389 checks per variant, 1,788
half-reads per variant, and 45 translation units / 1 link per variant.
`native_execution` remains `not_run`; qualification, readiness, warm execution,
full warm coverage, all acceptance flags and retained-code execution remain false.

Owned repository change only:
`ci/project/test_p06_counter_diagnostics_replay.py` (748 lines). The reader and
producer implementations were not edited. No native execution, configure/build,
commit or push was performed.

## Source and original evidence

- Repository HEAD: `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`.
- Original archive: `docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip`.
- Original ZIP SHA-256: `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f`.
- Independently supplied expected producer revision: `407ab9fea5e4f793a2a5088f566a87f3e631aa84`.
- Reader SHA-256 during the final run: `6284fda2985533e327bddcfa02c2341b8f7c17b1ba123d0a66b3d263187e5b75`.
- Test SHA-256 during the final run: `f954840178f739f21ef7f352985e9bbd3f6080d762bdf6fba72bd7665ac1956a`.

Both reader/test source identities were recorded before and after the final run
and were unchanged. The review followed `AGENTS.md` and
`docs/review/code-review-policy.md`; the reviewer did not author the reader.

## Unresolved finding F2: mixed diagnostic result families accepted

**Severity:** F2. **Confidence:** high. **Evidence:** executable regression and
static proof of an unchecked result-family combination.

Append the original member `checked-counters/logs/checked-core-overflow.log` to
the original member `checked-counters/logs/ordinary-boundaries.log`. The latter
still contains its valid `CHECKED_COUNTERS_RESULT ` record, but now also includes
the separate `CHECKED_COUNTERS_FAILURE_RESULT ` record from the core-overflow
cell. The resulting raw log is 1,390 bytes and has SHA-256
`b701727dbc683edec004979e3b20924f517240e4ff161ea0210a23669f35050c`.

Update the ordinary-boundaries command's `log_sha256` and `log_size_bytes`, write
a new ZIP, and supply the new ZIP's own SHA-256 externally. The reader returns
`outcome=pass`. This reaches the result semantics after all integrity checks;
it is not a stale-digest test. The claimed ordinary boundary log now contains a
result from a checked negative scenario, yet the conflicting record is ignored.

Regression:
`CounterDiagnosticsReplayTests.test_boundary_log_cannot_also_claim_a_negative_failure_result`.

The current `checked.verify_output` selects one positive result and rejects
specific failure-text markers, but does not reject the negative result prefix.
The replay reader delegates boundary parsing to it. The implementation owner
and audit lead received this exact finding. Per the audit lead, the regression
remains failing for the next wave's explicitly owned fix. Reject mixed result
families before accepting a boundary observation; do not waive or weaken this
test.

## Covered behavior

- Original evidence preserves all nonacceptance claims, including CLI failure.
- External digest/revision/contract/prefix mismatch; unsafe, duplicate and
  symlink ZIP members; archive aliases and mid-read mutation; trailing ZIP data.
- Duplicate JSON keys, nonfinite values and excessive depth; strict boolean vs.
  integer types and unknown fields in reports, commands, cells, variants,
  descriptors, compiler summaries and raw results.
- Required and complete versioned source inventory; absent retained source and
  generated bodies; clean checkout/submodules/pins and frozen profile identity.
- Source/tool/dependency/generated-config/compiler-stamp/diagnostic-source/
  object/binary before-after drift; strict file identities and PATH/executing
  Python consistency; original version-log identity.
- Rehashed generated TCU concatenation and access-wrapper production includes;
  missing/repeated fresh translation units, missing links/objects/libraries;
  mixed guards and compiler flags; generated template/copy/probe validation;
  raw header vs. report configuration; recomputed compiler/object summaries.
- Missing/reordered/duplicated selectors; the real older 19-selector split and
  counts relabeled as schema 2; report/raw-result disagreement; duplicate or
  repeated raw JSON results; negative-log contradictions.
- Malformed process status, cleanup, duration/RSS/log budgets, exact fixed
  timeouts, initial memory/disk limits, command argv/environment/cwd/log identity,
  exact cell order and unconsumed diagnostic members/trailing commands.

Semantic mutation helpers update the relevant source/build descriptor copies
and command log digests/sizes, and every synthetic archive receives a freshly
calculated external ZIP digest. A dedicated helper test verifies those updates.

## Inert-data and provenance boundaries

The filesystem/process test guards producer roots and recorded tool identities
across open/stat/resolve/list operations. It forbids subprocess execution,
process creation, exec-family calls, archive extraction, live source snapshots
and the live build validator. It changes the retained producer Python module to
an immediate `AssertionError`, updates its descriptors, and still replays the
packet without executing that retained module.

The test permits and records exactly one trusted Python module startup: the
current digest-pinned archive-reader source. Trusted current replay helpers are
also read to identify and check reader stability. These operations are separate
from executing or opening producer inputs; the test does not claim zero local
filesystem reads or zero execution of trusted reader code.

A separate positive test changes both reported Git tree identities consistently
and confirms the result still explicitly disclaims a Git-tree proof. This is an
internal-consistency reader, not independently authenticated Git origin. Object,
binary, tool and dependency payloads are absent, so tests validate recorded
identity syntax and agreement without claiming their contents were rehashed.

## Commands and logs

Run from repository root:

```sh
PYTHONPATH=ci/project python3 -m unittest -v test_p06_counter_diagnostics_replay
git diff --no-index --check /dev/null ci/project/test_p06_counter_diagnostics_replay.py
```

The initial suite log is `/workspace/scratch/98908dfa3444/w05-checked-replay-tests-initial.log`
(43 tests, 42 pass / 1 fail, 20.090 seconds). The final source-bound suite log is
`/workspace/scratch/98908dfa3444/w05-checked-replay-tests.log` (same test suite
through a `unittest.TextTestResult` subclass that only counts subtests and emits
before/after source identities; 43 tests, 42 pass / 1 fail, 20.134 seconds).
Whitespace checking produced no findings. A full project governance run and
native execution were outside this agent's scope and were not run.
