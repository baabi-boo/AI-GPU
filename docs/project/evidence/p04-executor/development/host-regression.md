# Initial development regression checks

The initial full source suite completed successfully: 1,733 tests in
1,421.575 seconds, with no failures, errors or skips. The command was
`python3 -m unittest discover -s ci/project -p 'test_*.py'` and its exact output
is retained in `initial-development-suite.log`.

This run began at starting HEAD `041f0981b2648dd5ec1494f4c1ca0300da8b9ca6`
while the new executor was being developed. It discovered the starting suite;
production files changed during the overall run. It is a development regression
observation, not clean-source acceptance or a claim that all later tests ran.

A subsequent P04-focused development run passed 99 tests in 45.891 seconds:
`python3 -m unittest discover -s ci/project -p 'test_p04_*.py'`.
Its exact output is retained in `p04-development-suite.log`. Later tests and
changes require their own frozen-source validation. The separately rerun ten
managed-runtime host tests passed in 7.855 seconds; individual author/reviewer
receipts retain the tested input identities and scopes.

After the runner's final recorded-tool-snapshot correction, the integrated P04
suite passed **139 tests in 75.397 seconds**, with no failures, errors or skips:
`python3 -m unittest discover -s ci/project -p 'test_p04_*.py'`.
The exact output is retained in `p04-integrated-host-tests.log`. This includes
the model, adapter, strict records, C++ app boundary, CI preparation and runner
tests together with the historical fixture tests. It was run in the implementation
worktree before its first commit; the independent receipts identify tested
production hashes. A complete clean-source hosted regression remains required.

The first published implementation, `7167ce17d335ec1f50e26da9b4832c1c27013ada`,
then passed the complete hosted governance suite: **1,809 tests in 491.547
seconds**, with plain `OK` and no failures, errors or skips. The job took
505 seconds and completed successfully under its existing 600-second limit.
The exact decoded GitHub job log is preserved as
`../host-tests/7167ce1-governance.log.gz`, with its raw/archive hashes, step
outcomes and source/run identity in `../host-tests/7167ce1-governance.json`.
Independent review is in `w07a.md`. Subsequent preparation corrections still
require their own exact-source governance run; this result does not qualify
later edits or native execution.

All of these observations are source/host checks. They do not demonstrate a
native model launch, timing performance, hardware behavior or acceptance of
P04-A02/A03. Do not add overlapping suite/subset counts together.

## Published preparation and retention corrections

The later preparation correction and the following retention correction each
passed their own exact-source hosted governance run:

| Published source | Tests | Test duration | Job duration / budget |
|---|---:|---:|---|
| `f4c6a323ab1696ac487fd86489ad7ed7836a558d` | 1,816 | 340.461 s | 359 / 600 s |
| `c9d139cc9f84839b6a56b6228dd304460cbfe45c` | 1,816 | 366.568 s | 378 / 600 s |

Both ran `python3 -m unittest discover -s ci/project -p 'test_*.py'` and ended
with plain `OK`, with no failures, errors or skips. The seven additional test
methods cover strict cached-product quarantine boundaries. The checkout,
preflight and final job metadata agree on each exact source, and preflight
reports no tracked changes. The workflow does not retain a complete post-suite
source inventory, so these results do not assert one.

The exact logs and source/job metadata are retained in
`../host-tests/f4c6a3-governance.*` and
`../host-tests/c9d139c-governance.*`. Independent rehashing, source-change review,
timeout assessment and precise limitations are recorded in [W08F](w08f.md).
Neither host result is native-model qualification or a claim that general CI is
entirely green. W08F also preserves the first implementation's failed general-CI
model preparation: it stopped at dirty `third_party/cocogfx` provenance before
running the catalog cell; it does not describe the corrected revision's model
execution outcome.
