# Independent hosted governance review — checkpoint 4268d2d failed

Reviewer: Agent 54, `/root/w09_hosted_checkpoint_review`.

## Actual result

**The immutable checkpoint failed Project Governance.** Run
[45034575638](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575638), attempt 1,
job `137245340992`, executed **3,312 distinct tests in 1,811.712 seconds**:
**3,310 `ok`, two `FAIL`, zero errors and zero skips**. There are no expected
failures or unexpected successes. The original log ends the suite with
`FAILED (failures=2)` and explicitly records **process exit code 1**. Successful
preceding checks and the successful individual methods do not convert this
failed attempt into a pass.

The independently fetched run/jobs API responses and purpose-built jobs result
agree that the run/job completed with `conclusion=failure`. The sole failed step
is `Test governance tooling`. Checkout, Python verification, prerequisite
inspection, project structure/evidence validation, published-baseline consistency,
and post-job cleanup completed successfully. The job ran from 14:47:27 to
15:17:56 UTC on 2026-11-22.

## Source, interpreter and command identity

The live API identifies commit
`4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, tree
`061ecbddc9b321edbd70c054c8efce4d188de04f`, repository `baabi-boo/AI-GPU`, branch
`master`, push event and the Project Governance workflow. The retained log
independently records fetching that exact commit, checking it out and printing it
with `git log -1 --format=%H`. Preflight then reports the same source with
`tracked changes: False` at line 148.

Line 140 records host Python **3.12.3**. Line 194 records the actual command:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

The shell is `/usr/bin/bash -e` with `PYTHONDONTWRITEBYTECODE=1`. Summary lines
3565–3568 record the exact count, duration, failed result and exit code. The
complete original decoded log continues through post-job cleanup.

Production native execution remains separately pinned to **CPython 3.12.14 on
Linux**. Immutable `p06_counter_public_execute.interpreter_identity` requires
that version/implementation/platform and identical resolved PATH/executing
interpreter path, hash and size. The native workflow provisions and verifies
3.12.14. Those production files, the controlled interpreter fixture repair and
the governance workflow were unchanged from e5 to checkpoint4268. The host
workflow's Python 3.12 major/minor requirement is not a native-pin waiver.

## Independent discovery and complete outcome reconciliation

The earlier review at **15:03:33 UTC** compared all **353 tracked files** under
`ci/project` and `.github/workflows` against immutable 4268 with exact byte
equality, and observed no tracked or untracked changes in that scope. AST method
inventory and unittest loader discovery found 3,312 unique IDs without running a
test method or `setUpClass`. Those original pending reports and the complete
source/discovery receipt are retained unchanged alongside this report.

The completed-log parser strips timestamp/terminal decoration only in its
analysis view; the log file is never normalized. It associates the one multiline
test description/result correctly, obtains exactly one terminal result per
unique ID, and matches the entire ID set against that preserved discovery.
No ID is missing or extra. Independently parsing the e5 log gives 3,158 unique
`ok` methods and 1,305.183 seconds; all those IDs remain in 4268. The exact added
set and actual outcomes are:

| New module | Executed distinct methods | `ok` | `FAIL` | Skipped |
|---|---:|---:|---:|---:|
| `test_p06_counter_diagnostics_replay` | 43 | 42 | 1 | 0 |
| `test_p06_counter_public_replay` | 40 | 39 | 1 | 0 |
| `test_p06_counter_inventory_replay` | 23 | 23 | 0 | 0 |
| `test_p06_counter_source_inventory` | 48 | 48 | 0 | 0 |
| **Added coverage** | **154** | **152** | **2** | **0** |

The public replay group executes all 8 input, 3 failed-original and 29
successful-original methods. The retained successful-public receipt and ZIP,
failed public original, and checked all-33 original are committed and hash-correct
at 4268. No missing-original or POSIX skip occurs in the hosted log. This proves
actual execution of those archive-based methods, while retaining the two failed
outcomes; it does not establish that every archive guard passed.

## Finding: test guards confuse current and recorded source paths

**F2; high confidence; evidence type `static-proof`, corroborated by the hosted
failure traces.** The concrete supported-host trigger is an equal absolute
pathname for the current trusted checkout and a previous native producer checkout.

The only two failed IDs are:

- `test_p06_counter_diagnostics_replay.CounterDiagnosticsReplayTests.test_replay_never_opens_producer_paths_extracts_or_executes_retained_code`
- `test_p06_counter_public_replay.OriginalPublicReplayTests.test_replay_never_extracts_executes_or_opens_producer_paths`

Both retained producer reports name `/home/runner/work/AI-GPU/AI-GPU` as their
source root. GitHub places the current governance checkout at that same pathname.
At immutable 4268, both test guards reject paths beneath the recorded producer
root without distinguishing current trusted helper access. The production reader
constructs its helper path from the currently loaded `sys.modules` entry, then
calls `Path(module.__file__).resolve()` and checks the trusted repository location.
The first such module is current `ci/project/baseline_inventory.py`.

The checked trace at lines 3519–3540 and public trace at lines 3543–3562 both end
at that resolution, with the test's assertion rejecting
`/home/runner/work/AI-GPU/AI-GPU/ci/project/baseline_inventory.py`. Immutable source
inspection and inert ZIP report reads corroborate the pathname collision. The
path is derived from the current reader module, not from an archived path used
to load producer code.

These traces identify a test-guard portability defect. They do not demonstrate
archived producer-code execution or a native runtime regression. They also do not
prove successful completion of either failed guard: both stop early. A separate
test-only repair, independent delta review and repaired-checkpoint execution are
required and are outside this original-result receipt. No waiver is recorded.

## Retention and earlier attempts

The complete log was fetched independently through
`github_fetch_workflow_job_logs` only after completion. Its retained UTF-8 bytes
match the root reviewer's independently fetched copy exactly:

- File: [run-45034575638-job-137245340992.log](run-45034575638-job-137245340992.log)
- Bytes: **696,999**
- SHA-256: `1d093819f62493536a2444b6efec31a75e522e7e3a3cfc197a0a101c833160a8`

The leading UTF-8 BOM and all decoded content are preserved. This is the exact
UTF-8 encoding of the connector-returned **decoded log text**. The connector
follows GitHub's temporary redirect and decodes its response; this review does
not claim access to or identity with an unobserved original HTTP byte stream.
Completed run/jobs API response text and the purpose-built jobs metadata are
retained separately, with hashes and byte sizes in [receipt.json](receipt.json).

The previous host index is retained byte-for-byte as
[host-index-before.json](host-index-before.json). The new attempt is appended to
[the host index](../index.json); previous entries and log bytes are preserved:

| Attempt | Original retained result | Scope retained |
|---|---|---|
| Local concurrent development | 3,070 tests, 149 failures, 1,517.531 s | Concurrent changing workspace; no immutable revision claimed |
| Hosted `81ed687` | 3,146 tests, 18 failures, 6 errors, 1,333.263 s | Clean hosted interpreter-fixture failure |
| Hosted `e5f1524` | 3,158 tests, all `ok`, 1,305.183 s | Historical repaired checkpoint; excludes later replay/inventory additions |
| Hosted `4268d2d` | 3,312 tests, two failures, 1,811.712 s | This failed immutable replay/inventory checkpoint |

The earlier failure explanations retain their prior independent review scope;
this pass through the evidence does not reclassify them. The original pending
review and its metadata are preserved as historical observations. The completed
failed review uses new filenames.

## Provenance limits and current work

The clean source claim covers the initial hosted checkout and tracked-file
preflight. No post-suite complete source manifest or exhaustive untracked-input
attestation is retained. API metadata and the complete log provide consistent
source/job attribution, not independent cryptographic attestation of every byte
throughout execution.

The 353-file equality observation is an earlier snapshot. Repair authoring is now
allowed in the two affected test modules, and narrative/evidence files are also
being edited. **This receipt does not claim that the current mutable workspace
still equals 4268, or that its later edits were tested by this failed run.**

Archive replay/inventory success checks retained originals and synthetic
consistency/rejection fixtures as inert data. It does not rerun the native
producer, authenticate missing binary payloads or qualify seed-free measurement
binaries. No full local suite, focused suite, native build or native execution was
performed in this review. Qualification, warm readiness, warm execution and
acceptance remain **false**. No warm speedup or P06 phase acceptance follows from
this result. This is independent advisory review, not maintainer approval.
