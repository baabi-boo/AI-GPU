# Host validation and hosted execution history

## Qualified source and scope

The clean hosted implementation is
`e1420fd550f716df33a2556057b7086a03032cbe`, tree
`3a168adfd345ecb3c15dc02b2583dc832bef6049`. Its Project Governance job passed
the source-root validator and **2,174 tests in 421.584 seconds**. The retained
[run](../hosted/governance-run.json), [job](../hosted/governance-jobs.json) and
[raw log](../hosted/governance-job.log) identify the same revision; the test log
ends with `OK`, with no failure, error or skip summary.

The source-root commands were:

```sh
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

These checks establish the declared host contracts and project metadata.
Host fault injection uses the real binding with fake runtime libraries; it does
not establish accelerator arithmetic. Actual installed SimX execution and the
independent numerical, dispatch and provenance audits have their own records.
This history review does not grant a phase acceptance or a review-policy waiver.

## Hosted jobs at that revision

| Workflow | Run / jobs | Observed result | Evidence boundary |
|---|---|---|---|
| Project Governance | Run `44866368570`; job `136730846161` | Success; 2,174 host tests | Clean integrated source validation |
| P05 Installed Python | Run `44866368565`; FP16 `136730846147`, BF16 `136730846328` | Both successful; each packet declares 12 passing P05 commands | Fresh bound package installation and SimX execution; independent packet review is separate |
| P04 Native Model | Run `44866368512`; RTL FP16 `136730845993`, SimX BF16 `136730846133`, RTL BF16 `136730846172`, SimX FP16 `136730846213` | All four jobs successful | Supplemental existing native regression; its executions are not added to P05 packet counts |
| General CI | Run `44866368514` | In progress in the retained observation | Plan, impact, setup and both builds had passed; an overall green result is not established by this snapshot |

The [P05 run](../hosted/p05-run.json), [P05 jobs](../hosted/p05-jobs.json),
[P04 run](../hosted/p04-run.json), [P04 jobs](../hosted/p04-jobs.json) and
[general-CI observation](../hosted/general-jobs.json) preserve the specific
scope of each statement. The four P04 outcomes here are job-metadata observations;
this review did not independently audit new P04 execution archives.

The two original P05 archives match the sizes and SHA-256 digests reported by
[GitHub artifact metadata](../hosted/p05-artifacts.json):

| Archive | Bytes | SHA-256 |
|---|---:|---|
| FP16 | 6,417,582 | `467122e41bee4e67f9eef285e015b2dee3a52522f0bcb3f497e3cec87e6c7380` |
| BF16 | 6,417,108 | `e951f943ece1878f3767180c4ce2b859939722d2d639c1afb37b8a72c76006d8` |

The P05 report snapshots name the clean revision/tree above, stable source,
two iterations, successful starts/exits/cleanup and no acceptance or phase-complete
claim. The archives contain a separate original native packet and its copied
`python/native` packet; these copies are not additional executions.

## Fresh host ownership and failure-path checks

[W06 A1](w06_a1.md) ran **107 maintained scenarios: 99 FP16 and 8 BF16**, all
passing in 79.371 seconds, followed by **11 separate fresh-process probes**.
The [run record](host/w06_a1_run.json),
[suite log](host/w06_a1_native_suite.log),
[scenario results](host/w06_a1-native/results.json) and
[probe results](host/w06_a1-probes/results.json) retain commands, source hashes,
statuses and raw child stdout/stderr. The total is 118 top-level scenario/probe
children; internal fork checks are not counted again.

The maintained run compiled two sequential C++17/UBSan host variants. The
additional probes rejected six unsafe loader paths before mapping any project
library, accepted one safe-copy control, and checked four state/recovery paths.
Those state paths recorded eight direct native rejections and fourteen public
error mappings. They completed with zero fake resources and at most one live
fake device. No real SimX library, kernel or device was executed in this run.

This was an uncommitted development snapshot based on
`6aac9c421180805a5621156e3d914c685fc6f4a5`, not a clean-source qualification.
Its 64 separately recorded source hashes match the later hosted commit exactly.
Its generated source-inventory digest remains the original
`036b193974df2be875ffdb368b719818f6edf05073efd701ecec0ab2bc7c08da`;
it is not relabelled as the subsequent packaging build.

## Actual host packaging and installation

[W06 A2](w06_a2.md) ran **eight real commands** for a source archive, one offline
wheel build, a post-build archive, a fresh isolated install/import and ELF checks.
The [commands and log descriptors](host/w06_a2-checks/commands.json),
[result](host/w06_a2-checks/result.json),
[source inventory](host/w06_a2-checks/source-inventory.json) and
[compiler-stage record](host/w06_a2-checks/compiler-staging.json) retain this scope.
All 22 pinned source inputs match the hosted implementation. Their original
digest is `c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.

The build used CPython 3.12.14, GCC/G++ 14.2.0, setuptools 84.2.1, wheel 0.48.0
and packaging 26.3. It compiled six translation units and linked once, using
single-job controls and a 2 GiB child address-space bound. The wheel command
took 8.864 seconds and recorded 185,264 KiB maximum child RSS. The source archive
and post-build repack each had exactly 31 permitted regular members. Three
unpinned stale-header `#error` sentinels remained outside the verified compiler
stage, and the real wheel build succeeded.

The offline installed payload contained four Python files and one extension,
with no runtime package requirements. The outside-checkout isolated interpreter
resolved imports inside the new venv; NumPy, torch and setuptools were absent.
The unbound package rejected execution and mapped no project library. Its ELF
needed only `libstdc++.so.6`, `libgcc_s.so.1` and `libc.so.6`, with no RPATH,
RUNPATH or exported `vx_*`. This is actual host packaging evidence, separate
from the later bound SimX installations.

The original [metadata reproduction](host/w06_a2-metadata-probe/metadata-probe.json)
found six absolute temporary source paths leaking into setuptools metadata.
The [recheck](host/w06_a2-metadata-recheck/metadata-probe.json) found zero after
restoring the original Extension lists in `finally`. An initial packaging
harness prerequisite check failed because `/usr/bin/time` was absent, before
compilation. Python resource telemetry replaced that optional dependency.
The original result and a later symlink-aware retained-byte accounting correction
remain alongside the final result. Neither is represented as a successful
initial attempt or a product failure.

## Failed development runs remain failures

The earlier [baseline log](host/baseline-host.log) records **1,813 tests in
1,576.307 seconds, with one setup error**: generated-compiler-record setup
exceeded its 30-second configure deadline. The isolated
[three-test recheck](host/baseline-generated-records-recheck.log) passed in
22.605 seconds. The initial failure is preserved; these two log files alone do
not establish a clean source snapshot or an overall passing baseline rerun.

The later [development full suite](host/full-host-development.log) records
**2,163 tests in 1,164.874 seconds, 49 failures and two errors**. Its
[wrapper record](host/full-host-development.json) retains exit code 1,
1,172.241 seconds of outer elapsed time, before/after file inventories and
54 changed paths. It ran while the shared source was being edited and cannot
qualify the final implementation.

Of the 51 failure/error blocks, **43 explicitly report helper bytes changing
after import**. Seven additional P05 assertions show execution stopping before
the expected copy/validation stage, consistent with that guard; their inner
reports were not retained, so a separate exact cause is not asserted for each.
The remaining inherited test is
`test_oracle_failure_does_not_verify_a_successful_workload_command`: its
`workload_command_started` assertion observed `False` instead of `True`.
The [isolated recheck](host/full-host-first-failure-recheck.log) passed in
10.956 seconds. Its original inner report is unavailable; no timing root cause
or waiver is inferred. The later clean hosted suite passed all 2,174 tests and
provides the integrated source qualification without erasing either failure.

## Independent review and retention limits

[W06 A3](w06_a3.md) compared all 74 first-publication blobs with the actual
candidate and checked protected inputs, workflow exposure and prior independent
reviews. The immutable-base classifier returned **R2, `ci-enforcement`**;
manual review conservatively covered the external Python boundary at R3 scope.
Its [raw classifier output](host/w06_a3-classifier/stdout.txt) and
[execution record](host/w06_a3-classifier/result.json) preserve that distinction.
Five focused governance/metadata checks passed with a mocked compiler boundary;
they are not additional build or device qualification.

The retained host subset contains original reports, logs, source hashes and
specific reproduction scripts, not every temporary build directory or fake DSO.
Absolute scratch paths identify the original run; they are not portable replay
locations. No lifetime, packaging or governance count in this history proves
physical GPU speed, PyTorch support, vendor XRT `hw_emu`, or closure of the
inherited 267 → 283 DSP area finding.
