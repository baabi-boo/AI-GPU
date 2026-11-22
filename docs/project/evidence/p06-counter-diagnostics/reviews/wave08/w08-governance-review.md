# Wave 08 independent governance and fixture review

Reviewer: Agent 48, `/root/w08_governance_review`.

## Assessment

No open F1, F2 or F3 finding was identified in the bounded review of the retained
`e5f152464dda5e488d6d1a030c1fcdc49b5a9701` Project Governance pass and the controlled
interpreter fixture repair. The retained host index represents the three attempts
correctly and keeps hosted test evidence separate from native execution and warm
qualification. This is independent advisory review, not maintainer approval or a
waiver.

The reviewed hosted source is tree `74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`.
Workspace HEAD was `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`; its later replay and
inventory additions are not covered by the historical 3,158-test pass. Run
`45034575638`, job `137245340992`, is expressly outside this review.

## Hosted evidence and failed attempts

| Attempt | Source scope | Actual result | Interpretation |
|---|---|---|---|
| Local concurrent development | No trustworthy immutable source identity in the retained log | 3,070 tests in 1,517.531 s; 149 failure events; no errors | Development failure. Logged helper-byte drift and blocked fixtures are consistent with the stated concurrently changing workspace. It cannot establish a revision-bound full-suite result. |
| Hosted run 45029135196, job 137228604836 | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`, clean tracked checkout, Python 3.12.3 | 3,146 distinct tests in 1,333.263 s; 18 failures and 6 errors | All 24 failure/error headers belong to `test_p06_counter_public_execute.PublicExecuteTests`; fixture interpreter observations cause premature native-validator rejection. The six errors then index an empty command history. |
| Hosted run 45031746158, job 137236633104 | `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`, clean tracked checkout, Python 3.12.3 | 3,158 distinct tests in 1,305.183 s; all 3,158 results `ok`; no failures, errors, skips, expected failures, or unexpected successes | Successful hosted governance and bounded host-test execution at the repaired checkpoint. |

The success log explicitly identifies the repository, exact fetched revision and
checkout, records Python 3.12.3 at line 146, and reports the same source with
tracked changes false at line 154. It records successful preflight, project
metadata validation, published baseline packet consistency, and the exact
verbose unittest discovery command. Lines 3371–3373 contain the total and `OK`;
post-job cleanup follows. There are 3,158 unique method IDs and 3,158 successful
result terminals. One test prints its docstring on a second line, so a simplistic
single-line regex would undercount by one; this was reconciled explicitly.

All three retained log hashes and byte sizes match `host/index.json`:

| Log | SHA-256 | Bytes |
|---|---|---:|
| `local-concurrent-governance-attempt.log` | `eee213aeb2cbe8446b39c9862dc8309218e6d6b527b28b2a79d999bb8c612a1e` | 124677 |
| `run-45029135196-job-137228604836.log` | `b67117ecc27ab323ae9b622ec3cb8607d6d8d910db2f3a7ba9c7fedd8251abed` | 687856 |
| `run-45031746158-job-137236633104.log` | `c789496a9e29f55df97ff54da55595397cdb33f0c64f9839b0d612a3a9dbe59f` | 657711 |

The 149 local failure headers are distributed over simulator runner failures
(48), warm runner (55), and workspace runner (46); they are not the clean hosted
PublicFixture failure. The raw local log records `executing runner/helper bytes
changed after import`, while the hosted 81ed log records the strict CPython
3.12.14 mismatch. Neither failed attempt is silently promoted or discarded.

## Fixture repair and native interpreter enforcement

`ci/project/test_p06_counter_public_execute.py` has SHA-256
`d2603a8c02127166d3c79ac481b3bed0ad726225db46f0257b3e42ac98a63fd8` at both the tested
`e5f1524` checkpoint and current `4268d2d` HEAD/workspace. The change introduces a
small `ModuleObservations` proxy (lines 20–28), then uses `mock.patch.object` on
the public runner's module references (lines 37–40). Synthetic version,
implementation and platform observations belong only to that runner reference;
shared host `sys` and `platform` modules are not mutated. `__getattr__` delegates
other observations dynamically, preserving current redirected stderr.

The real `runner.interpreter_identity` function remains installed. Production
`ci/project/p06_counter_public_execute.py:97–106` still strictly requires CPython
3.12.14 on Linux and equality of PATH and executing interpreter resolved path,
SHA-256 and size. That runner and the governance workflow are unchanged between
81ed687, e5f1524 and 4268d2d. The native workflow separately provisions 3.12.14 and
verifies version, implementation, platform and executable location; the host
workflow intentionally checks only Python major/minor 3.12.

Negative interpreter tests retain path, version and implementation rejection and
add platform rejection. The two new tests verify restoration across mismatched
outer observations and redirected validation errors. Their `ok` records appear
in the successful hosted log at lines 2279–2280; the combined interpreter
negative-path test passes at line 2284. Existing build, cleanup, source/input
stability, output rejection and malformed invocation tests remain in place.
The fixture still marks all acceptance and warm-related claims false.

The full-suite count rises by exactly 12 methods: seven added checked-result
rejection tests, two fixture-isolation tests, and net three public-record tests
(four additions replacing one CP-drain expectation). This matches 3,146 → 3,158.

## Future replay discovery and original success receipt

This narrow supplementary check addresses current fixture availability only;
it does not extend the historical e5 governance result to later replay code.
`unittest` discovery with `test_p06_counter_public_replay.py` finds 40 unique
methods: 8 input, 3 failed-original, and 29 successful-original replay methods.
None has a skip decorator. No test method was executed during this review.

The success receipt and both referenced original ZIPs are git-tracked in
4268d2d. Calling `successful_original()` returns without `SkipTest`. The receipt
identifies `run-45031746149-attempt1.zip`, SHA-256
`05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276`, revision
`e5f152464dda5e488d6d1a030c1fcdc49b5a9701`; hashing the retained archive matches.
The failed original remains present with matching SHA-256
`d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5`.

The successful archive's `public-counters/report.json` hashes to
`a81c6a997a2a220b4db6d2ddecac21e08dfa32a522de0fabc2e0f89acfb2d925`. Read as data, it
records a finished producer pass, five passing public cells, no errors, CPython
3.12.14 Linux, and before/after source checkout records for the same e5 revision
and tree with no dirty or untracked paths. Its qualification and warm/acceptance
flags are false. This is the separate native run `45031746149`, not governance
run `45031746158`, and not a new native run by this reviewer.

With the present committed receipt/archive, missing-fixture skip predicates are
false. Existing malformed receipt, bad digest and missing referenced ZIP paths
fail rather than skip. The later hosted execution log is still required to prove
that all 40 methods actually ran and passed; discoverability alone is not a pass.

## Findings and provenance limitations

No actionable finding was identified. The following F0 observations define the
review's limits; confidence is high and evidence type is static-proof:

- `host/index.json` plus the three retained logs: all declared result counts,
  durations, hashes and host versions reconcile. Source identity is available
  directly in both hosted logs. The local concurrent log lacks a usable immutable
  source identity; no source revision is invented for that attempt.
- `host/run-45031746158-job-137236633104.log` and the governance workflow: the log
  proves the initial checkout and tracked cleanliness. There is no retained
  post-suite complete source manifest or untracked-input attestation. Interpret
  “immutable hosted checkout” as the isolated clean hosted revision scope; this
  review does not claim cryptographic attestation of every byte during execution.
- Run/job attribution was checked against retained filenames and the local
  index. No live GitHub API metadata or independently downloaded platform log was
  retrieved by this reviewer, so artifact origin is not independently reattested.
- Native archive intake was inspected as retained data only. No native build,
  execution, exhaustive native archive replay, or binary-origin attestation was
  performed here.
- The latest 4268d2d changes add seven replay/inventory source and test files plus
  evidence. Those changes are outside the e5 full-suite receipt. No result from
  run 45034575638 is claimed.

## Release scope

The e5 governance pass and fixture repair are correctly represented as a scoped
host-governance success. All false qualification/warm/acceptance flags remain
false. The warm analyzer, frozen warm-v1 contract and roadmap are unchanged across
these checkpoints; `P06-WARM-RV64-MPM-HIGH-HALF` remains unconditional. This review
confers no P06-A02/A03 acceptance, warm readiness, warm performance result, or
physical hardware qualification.

No repository file was edited. Verification consisted of static source/diff
review, retained-log parsing and hashes, narrow unittest discovery, receipt intake
and ZIP report reading. Full governance, focused suites and native builds were
not rerun. The companion JSON records exact file identities and observations.
