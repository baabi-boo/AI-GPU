# Wave 6 independent checked diagnostic replay review

## Verdict

**No F2 or F3 finding remains in the reviewed checked-log repair or the new
all-33 retained-data replay reader. No new F1 defect was found.** Confidence is
**high** within the stated consistency-only contract. The narrow checked-log
repair received an early independent positive verdict before this broader
review completed; that verdict supports the bounded native retry and is not
native execution evidence or a maintainer acceptance decision.

Reviewer: agent 36, `/root/w06_checked_replay_review`, author-disjoint from the
reader, independent replay tests, and checked-log repair. This was a read-only
repository review. Only review notes, logs, a probe script, and its source
receipt were written outside the repository. No repository file was edited;
no native configure/build/run, project-wide governance run, commit, or push was
performed by this reviewer.

Read policies: `AGENTS.md`, `docs/review/code-review-policy.md`, and
`docs/project/acceptance.md`; checked current project status, P06 roadmap gates,
roadmap, and backlog. Initial repository HEAD was
`81ed6871634fefbf5c78fb27cf10dce913bd4d9c`. The parent published while this review
ran, and final observed HEAD was
`e5f152464dda5e488d6d1a030c1fcdc49b5a9701`. All four reviewed source file hashes
below stayed identical before and after both complete test runs and at final
verification; these hashes identify the reviewed implementation independently
of that concurrent publication.

## Scope and immutable identities

| Input | SHA-256 |
| --- | --- |
| `ci/project/p06_counter_diagnostics_replay.py` | `6284fda2985533e327bddcfa02c2341b8f7c17b1ba123d0a66b3d263187e5b75` |
| `ci/project/test_p06_counter_diagnostics_replay.py` | `f954840178f739f21ef7f352985e9bbd3f6080d762bdf6fba72bd7665ac1956a` |
| `ci/project/p06_checked_execute.py` | `86ba0b3fd2bbfa97ebb2346e69fed85968fd3da8bf267d4dc1a13aaacf8b358e` |
| `ci/project/test_p06_checked_execute.py` | `90dca95d90108c26c8e8d76658d1d93973d24b46426b1d92cfc1d0f1521c61ad` |
| Original `docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip` | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` |
| Trusted `docs/project/evidence/p05-torch/reviews/archive_reader.py` | `4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3` |

The external producer revision remains
`407ab9fea5e4f793a2a5088f566a87f3e631aa84`. Original ZIP size is 1,137,709 bytes.
Its 327 data files include exactly 270 retained source bodies. The sorted
source-name digest is
`d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108`.
Neither the original ZIP nor its producer revision was replaced by a synthetic
mutation in the positive control.

## Narrow checked-log repair

Reviewed every changed hunk in `p06_checked_execute.py` and its test file.
The new reserved-result-family predicate counts the bare tokens over the
entire raw text, while the existing exact-prefix line selection and strict
JSON/value/type contracts still select the result. A valid boundary cannot
coexist with a negative/public result; a valid negative result cannot coexist
with a boundary/public result. Duplicate, bare, indented, embedded, malformed
delimiter, and suffixed reserved tokens also reject.

Both parsers reject line-leading `FAIL`, `FAILED`, and `ERROR`, including
horizontal whitespace, and retain rejection of
`SIMX_CHECKED_COUNTER_FAILURE` anywhere. Benign dependency output before or
after a result remains valid, including `ERROR_COUNT`, `FAILED_COUNT`, and
inline mentions used as ordinary statistics. This is the deliberate explicit
failure-line rule, not a claim that every possible natural-language failure
message can be classified.

The early focused run executed the complete `CheckedOutputParserTests` class
plus the two new fake-runner failure-family/failure-line methods: **18 methods
passed in 2.492 seconds**. These are a subset of the complete checked suite
below, not an additional distinct-suite method count. Fake-runner regressions
confirm rejection stops the attempt at the contradictory command and preserves
the nonqualification claims. The earlier failures described in
`w06-checked-log-fix.md` and its retained logs were read and left intact.

## Independent replay and byte reconstruction

The complete replay source and independent test source were reviewed, along
with the pure checked parser, trusted structural helpers, and pinned bounded
archive reader on their reachable paths.

The independent probe script does not call the reader's build parser to
reconstruct the original records. It reads the externally pinned ZIP as bytes,
hashes each retained source and command log, parses compiler records with
`shlex`, separates compile/link records, and compares the recorded summaries
against its own reconstruction:

- Ordinary and checked each have **45 distinct translation units, 45 distinct
  objects, and exactly one link**. Every compile record uses the matching
  stamp flags and exact dependency target. Each link consumes exactly its
  freshly compiled object set and the identified softfloat, Ramulator, and
  Ramulator extension library arguments.
- The generated TCU translation unit equals the retained production body,
  one LF byte, and the retained access footer. The production wrappers and
  source/object mappings are additionally checked by the independent replay
  suite's mutation cases.
- All **270 source bodies** hash to their descriptors; the full sorted name
  set matches the versioned digest. Source before/after and tools/dependency
  before/after records agree. Configuration, stamp, generated diagnostic body,
  object, and binary before/after identities agree per variant.
- All **17 commands** occur in their exact expected order. Original log bytes
  match recorded hashes and sizes; success, zero integer exit, process start,
  cleanup, and no failure reason agree. The complete suite additionally checks
  argv, cwd, sanitized environment, compiler/header/configuration bindings,
  and mutations of those fields.
- Fixed limits remain two build jobs, one execution thread, 4 GiB RSS,
  15 GiB initial free-disk reserve, and 16 MiB log size, with version/configure/
  build/run limits of 30/120/1800/180 seconds as appropriate. Original maximum
  recorded RSS is **903,798,784 bytes** and maximum log is **106,413 bytes**.
- All **7 cells** are revalidated from raw output. The original positive
  control retains both all-33 boundary variants and all five directed negative
  cases. Per boundary variant: 33 selectors, 40 backing source components,
  400 component vectors, 14 split vectors, 33 reset selectors, 6,389 checks,
  and 1,788 half-reads. The 12 unavailable selectors remain outside the query
  scope.

The name-list pin correctly rejects omitted noncritical headers even when
synthetic descriptors and source lists are rewritten consistently. Its
compatibility restriction for future producer inventories is a known
versioning limitation, not a reason to weaken current coverage.

## Trusted reader closure, bounded input, and integer probes

An independent AST walk followed only local imports reachable from the
diagnostic reader. Its complete static local closure contains **24 modules**;
the reader receipt contains exactly those 24, with no omitted or extra local
module. The separately loaded archive helper is pinned to its exact SHA-256.
The full identity receipt is retained as
`w06-checked-replay-review-reader-sources.json`.

The closure consists of `baseline_inventory`, `baseline_matrix`,
`baseline_packet_contract`, `baseline_packet_io`, `baseline_process`,
`compiler_records`, `p02_fixture_oracle`, `p02_layout_fixture_oracle`,
`p02_matrix_records`, `p02_wmma_fixtures`,
`p02_wmma_numerical_fixture_oracle`, `p03_execution_records`,
`p04_execution_records`, `p04_fixture_adapter`, `p04_model_contract`,
`p04_reference`, `p06_checked_execute`, `p06_compiler_records`, `p06_contract`,
`p06_counter_diagnostics_replay`, `p06_mpm_execute`, `p06_records`,
`p06_replay`, and `preflight`.

For each of those 24 modules, a read-only mock made its observed source bytes
drift after archive entry. Every mutation raised the trusted-source-stability
error on exit. No repository file was changed to run this probe.

Seven additional complete synthetic-archive probes verified recorded identity
integer semantics. Exact integers **9,007,199,254,740,993** (`2^53 + 1`) and
**18,446,744,073,709,551,615** (`UINT64_MAX`) survive without floating-point
rounding. Boolean `True`, floating `1.0`, negative `-1`, zero, and `2^64` reject
as invalid recorded file sizes. The two accepted cases concern absent payload
identity records only; they do not authenticate a binary of that size and do
not change the scope or acceptance flags. Total supplemental probes: **31
passed** (24 source-stability mutations and 7 integer cases).

The archive helper bounds compressed bytes, central directory size, member
count, expanded bytes, member reads, aggregate read volume, JSON size and
structure. It rejects noncanonical paths, symlink/special members, duplicate
names, unsupported ZIP forms, original-path substitution, and changed archive
identity. Member closure is checked within the selected packet prefix.
Producer roots and recorded files use syntactic `PurePosixPath` handling.

The independent suite instruments producer-path filesystem operations,
process creation, extraction, and retained-code execution. It substitutes a
retained producer module that would raise immediately if executed and still
passes replay, with only the current pinned archive helper imported. This
establishes that the tested reader path treats retained producer code as inert
data; it does not open producer tools/objects/binaries on this host.

## Executed verification

Both full suites used separate `python3 -I` interpreters, explicitly prepended
the exact repository `ci/project` directory, asserted the imported test
module's absolute path, and compared all four reviewed file hashes before and
after the run. A `unittest.TextTestResult` subclass counted subtests without
changing test behavior. Results were read from the completed commands and
retained logs, not inferred from launch status.

| Verification | Methods | Subtests / probes | Result | Duration |
| --- | ---: | ---: | --- | ---: |
| `test_p06_checked_execute.py` | 42 | 909 subtests | PASS; 0 failures, errors, or skips | 39.946 s |
| `test_p06_counter_diagnostics_replay.py` | 43 | 167 subtests | PASS; 0 failures, errors, or skips | 20.665 s |
| Independent raw-byte reconstruction and targeted probes | — | 31 probes | PASS | Not separately timed |

The supplemental reproducible command is:

```sh
python3 -I /workspace/scratch/98908dfa3444/w06-checked-replay-review-probes.py
```

## Finding disposition and scope

There is no concrete remaining F2/F3 defect identified by this review. The
previous mixed-result and explicit failure-line F2 scenarios are closed on the
exact tested checked-parser hashes. Confidence is **high**; evidence is
`static-proof` plus observed passing original-packet controls and adversarial
mutations. There is no waiver and no invented maintainer decision.

F0 scope observation, high confidence, `static-proof`: successful replay is
only `retained-data-consistency-only`. `qualified`, `ready_for_warm`,
`warm_execution`, `acceptance`, `acceptance_claimed`, `phase_acceptance`,
`performance_acceptance`, `full_warm_coverage`, and `retained_code_executed`
remain false, and `native_execution` remains `not_run`. The same invariant is
applied to CLI failure. The native producer's historical prerequisite pass
does not grant warm execution readiness or a new P06 acceptance.

External archive/revision pins do not authenticate GitHub origin, prove a Git
tree, or prove that synthetic records represent real execution. Absent object,
binary, compiler, and dependency payloads are not independently rehashed.
Before/after records are not a defense against a malicious concurrent producer
writer. These limitations are explicit in the reader and remain preserved.
This review establishes no terminal lifetime proof, fresh native GPU result,
warm performance result, RTL result, hardware result, or phase acceptance.

## Retained review artifacts

All artifacts below are under `/workspace/scratch/98908dfa3444/`.

| Artifact | SHA-256 |
| --- | --- |
| `w06-checked-replay-review-suite.log` | `f6161c017195bb476c692ad6b4ea8fea5bfcac2ae115b1ed654665996e80ba07` |
| `w06-checked-replay-review-checked-suite.log` | `d9a49de70dc2166a771991d0e2509d160fc42611e6668cd1d606a9727e3e0bd8` |
| `w06-checked-replay-review-probes.py` | `6a778ed22abe153d01310faaf6e399a7e71b07f22743f98a55cf1df8894fb206` |
| `w06-checked-replay-review-probes.log` | `cb9a1b8c229e6920b01d3f0356c40c9ef7ae1cc440fbdc0dd263f39316a1e604` |
| `w06-checked-replay-review-reader-sources.json` | `a2111e8f4d66f07631b4bfbba9da5f846331d474eaba75b829fa0408281d9c86` |
