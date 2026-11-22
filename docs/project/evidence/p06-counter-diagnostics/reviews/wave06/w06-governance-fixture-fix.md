# Wave 6 agent 35 — public governance fixture repair

## Result and scope

The owned change is only `ci/project/test_p06_counter_public_execute.py` (+55 / -2 lines).
The inspected base is `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`; concurrent shared-tree changes in other files were preserved.
This is controlled host orchestration evidence. No native build, native execution, workflow change, production runner change, commit, or push was performed.

## Root cause and design

Hosted run 45029135196, job 137228604836 ran 3,146 methods with 18 failures and 6 errors. Every failure in this fixture stopped at the strict executing-interpreter guard instead of the intended branch. The fixture already supplied synthetic source files, process results, compiler records, and executable identities, but did not supply the matching interpreter observations. The supported system Python patch used by governance therefore leaked into the controlled native-runner input.

`PublicFixture` now replaces only the runner module's `sys` and `platform` references with scoped `ModuleObservations` proxies. Each proxy supplies the three synthetic inputs the real validator requires: version `(3, 12, 14)`, platform `linux`, and implementation `CPython`. Other attributes are resolved dynamically against the original module. This includes `sys.stderr`, so `redirect_stderr` continues to capture the runner's real validation error. The fixture's existing `ExitStack` restores the original module references.

The real `interpreter_identity` function is never replaced or bypassed. Its strict CPython 3.12.14/Linux guard and executable path/hash/size comparison remain untouched. The native workflow's exact Python pin remains untouched. Synthetic observations are explicitly labeled as non-native evidence in the fixture.

## Focused coverage

- Preserved the existing path, version, and implementation mismatch rejection cases.
- Added a platform mismatch case, with no process start allowed.
- Added a regression that supplies mismatched outer version/platform/implementation observations, proves the real validator rejects them before entry, runs all 14 controlled command records successfully inside the fixture, checks all nonqualifying report flags, and proves the original mismatched observations are restored and rejected after exit. The real host observations remain unchanged.
- Added a validation-error regression that proves the proxy sees the currently redirected stderr stream and the invalid revision stops before any controlled process.

## Verification

| Check | Result |
|---|---|
| Pre-fix alternate observed patch 3.12.3 | Reproduced hosted fixture failures: 10 methods, 18 failures, 6 errors |
| Post-fix actual host CPython 3.12.14/Linux | 12 methods passed in 15.156 seconds |
| Post-fix alternate observed patch 3.12.3 | 12 methods passed in 14.396 seconds; outer observation and real host restoration asserted |
| Owned-file `git diff --check` | Passed |
| Production public runner and native workflow vs HEAD | No diff |

The alternate run used a module namespace proxy on actual CPython 3.12.14; this is not a claim that an actual CPython 3.12.3 binary was executed. The fixed module retains the ten existing methods and adds two methods. This worker did not rerun the full governance suite or native job; parent integration review and hosted execution remain separate.

## SHA-256

| File | SHA-256 |
|---|---|
| `ci/project/test_p06_counter_public_execute.py` | `d2603a8c02127166d3c79ac481b3bed0ad726225db46f0257b3e42ac98a63fd8` |
| `ci/project/p06_counter_public_execute.py` | `0da2aba310b5451ef1bff54195bb831a64c416ae6fd62abb69d8333d5da269b6` |
| `.github/workflows/p06-checked-counters.yml` | `3d96c976076c91dfda3cb0262506d48be6501ecd187eae1f217d42234a4de8f0` |

## Scratch evidence

- `w06-governance-fixture-fix.log`: combined reproduction, actual-host, alternate-observation and diff verification log.
- `w06-governance-fixture-fix.patch`: exact owned-file diff for independent review.
- `w06-governance-fixture-before.log`, `w06-governance-fixture-actual.log`, `w06-governance-fixture-alternate.log`: raw individual logs.

Read `AGENTS.md`, the code review policy and applicable project/acceptance guidance. The fixture-only diff is R1 under the default path policy; parent independent review was explicitly requested and remains the publication review boundary. No gate or acceptance waiver was requested or applied.
