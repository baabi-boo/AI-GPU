# Governance and qualified-warm readiness audit

**The next bounded step is a full strict governance rerun of the independently
reviewed, published correction. Fresh qualified-warm native execution remains
unstarted.** The first strict hosted invocation failed. The current change
repairs its identified harness/environment problems and implements a read-only
advisory screen for the separate native prerequisites. Neither focused test
success nor a readiness report changes phase acceptance.

This audit describes the 2026-11-24 continuation based on
`457ddaa06b07e439b6f5ef2d15c09ef24131f6fe`. The
[evidence index](evidence/governance-readiness/README.md) records current source
identities, retained logs, independent review and publication status. Tests of
the corrected working tree are scoped to those file identities, not attributed
to the earlier hosted revision. The [handoff](p06-qualified-warm-handoff.md),
[governance runbook](governance-runbook.md) and
[native/readiness runbook](evidence/p06-qualified-warm/runbook.md) define the
remaining sequence.

## First strict hosted invocation: failed and preserved

The strict runner and checked environment were published at `2b9a18`; a
workflow-context correction followed at `457ddaa06b07e439b6f5ef2d15c09ef24131f6fe`.
[Run 45405383871](https://github.com/baabi-boo/AI-GPU/actions/runs/45405383871),
[job 138484567565](https://github.com/baabi-boo/AI-GPU/actions/runs/45405383871/job/138484567565),
attempt **1**, executed the latter source using hosted CPython **3.12.3**.

| Retained observation | Result and scope |
| --- | --- |
| Canonical discovery and execution | 4,744 methods; all 4,744 starts and stops observed. |
| Original unittest terminal | `Ran 4744 tests in 3116.381s`; `FAILED (failures=50, errors=11)`; zero skips. These failure/error totals include subtest events. |
| Strict accounting | `strict_success=false`; eight canonical parent outcomes were missing from the accounting record. Those are accounting defects, not eight unexecuted bodies. |
| Finalization | Rejected `ci/project/__pycache__/baseline_inventory.cpython-312.pyc` as unbound to HEAD. |
| Final receipt | `status="incomplete"`, `execution_completed=true`, `governance_passed=false`; no final source, interpreter or environment snapshots. |
| Original artifact | GitHub artifact `14932106620`; **1,261,073 bytes**, SHA-256 `06c1184f7d2bd4806108cb1584fe155cfe005fca6c8d8a056f374129646e8c2d`. |

The [unchanged original](evidence/governance-readiness/hosted/first-attempt-original.zip)
contains the environment receipt, discovery, event stream, unittest log, outer
log and final summary. Its raw identity was rechecked during this audit. Test
execution finishing does not establish a qualifying run: both successful
accounting and final source/tool stability remain required. Preserve this
failed original even after a later successful rerun.

## Identified corrections and their validation

| Correction | Preserved boundary |
| --- | --- |
| Use the checked private `venv/bin/python3` launch alias and bind both its requested path and resolved binary identity. | An alternate alias to identical executable bytes does not satisfy contracts that bind the exact selected launch path. |
| Require and retain `--environment-receipt` in the strict runner. | No receipt-free qualifying CLI path; tool and environment checks remain mandatory before and after execution. |
| Represent oversized dynamic subtest IDs with a digest of their complete UTF-8 bytes plus encoding/length metadata. | The 4,096-byte limit for canonical discovered IDs remains unchanged; IDs are not truncated and failing subtests remain failures. |
| Pass `-I -B` to the affected isolated Python test children. | Existing source/bytecode rejection remains enforced; isolated mode alone ignores environment bytecode settings. |
| Check the attempted injection's marker and import origin, with a positive control. | Ambient injection must still be rejected; the test no longer assumes a distribution has no legitimate `sitecustomize` module. |

Fresh focused results on Linux CPython **3.12.14** are retained separately:

| Selection | Observed result | Retained evidence |
| --- | --- | --- |
| Strict runner, receipt and source regressions | **78 passed in 15.504 seconds** | [Log](evidence/governance-readiness/validation/runner-integration.log) |
| Checked environment, workflow and three actual isolated-import checks | **42 passed in 30.527 seconds** | [Log](evidence/governance-readiness/validation/environment-and-imports.log) |
| Advisory readiness tests | **57 passed in 1.794 seconds** | [Log](evidence/governance-readiness/validation/readiness-integration.log) |
| Exact 46 canonical parent methods implicated in the hosted failure, rerun under `StrictResult` with checked Python/CMake | **46 passed in 142.758 seconds**, zero failures, errors or skips | [Log](evidence/governance-readiness/validation/failed-parent-rerun.log); [summary/events](evidence/governance-readiness/validation/failed-parent-rerun.summary.json) |

The selected rerun used checked **CMake 3.22.6**. These selections overlap and
are not added into a new full-suite result. The 46-method rerun is a targeted
development check, not a qualifying canonical invocation.

Independent discovery of the corrected source observes **4,812 canonical IDs**,
SHA-256 `d885b2614c828d4c673960b052bbae35fba0239521a59c8092c399f735334095`.
All 4,744 published IDs remain in their original relative order. The 68 additions
comprise 57 readiness methods and 11 runner/receipt/alias regression methods.
Discovery establishes the population to run; it does not establish that all
4,812 methods passed.

The earlier [4,527-ID reconciliation](evidence/p06-qualified-warm/validation/coverage/final-reconciliation.json)
is preserved at `c0b44ce64665fe11895f869eea8c38c9b820d6f7`: 4,491 hosted passing
IDs plus 59 supplemental passing IDs, less 23 overlaps. That historical union
crosses two environments and is neither the current population nor one full
zero-skip invocation. Earlier skips, failures and unfinished invocations retain
their original disposition.

## Advisory readiness implementation

The recovered [observer](../../ci/project/p06_qualified_warm_readiness.py) has
SHA-256 `843916e3b7eb0a2bd4e50d0bf2d4a3e4bcf102db62a3a66f1af5bd5e743463ec`
and **31,672 bytes**. Its three recovered test files contain 20, 15 and 22 test
methods, matching the 57-method fresh validation above. This is a new bounded
observation tool; the frozen source proofs, measurements and native contracts
remain unchanged.

The CLI requires seven explicit paths—source, planned/existing workspace,
toolchain archives, dependency repositories, host aliases and both original
archives—plus a lowercase 40-character expected revision. The source path must
identify the trusted checkout containing the executing script. The
[runbook commands](evidence/p06-qualified-warm/runbook.md#read-only-readiness-screen)
preserve stdout JSON, stderr, timestamps and the original exit code externally.

The observer checks canonical/disjoint roots and fresh stage destinations,
source/index/gitlink state, frozen proofs and projected inputs, raw original and
fifteen locked archive-part identities, local dependency Git objects, selected
host tools and versions, disk reserve and host memory. It uses bounded local
Git and version probes. It performs no network acquisition, extraction,
dependency compilation or native workload launch.

Independent checks report `observed`, `blocked`, `not_checked` or `unknown`.
The tool intentionally marks the `resources.cgroup_capacity` row `unknown`:
host `MemAvailable` cannot prove effective process allocation or hidden ancestor
margins. A real report from this implementation therefore cannot be all clear.
It returns nonzero while any blocker or incomplete check remains. Its JSON is
not a preparation receipt or an admission input and never authorizes execution.
It keeps `native_execution="not_run"`, `counter_qualification_passed=false`,
`qualified_warm_passed=false` and all historical qualification/acceptance fields
false.

The observations are bounded, non-atomic snapshots. They reserve no capacity,
do not authenticate provider transport, and do not establish archive member
safety, full historical replay, installed native tools, compiler support files,
shared runtimes or a successful build. Shared filesystems cannot be counted as
independent capacity. Production preparation, build and process admission must
still revalidate their complete unchanged requirements.

## Recovery and remaining native blockers

An execution-service reset removed the earlier temporary working area. Exact
readiness source/tests were recovered, but unretained pre-reset raw JSON and
unpublished reviewer reports were not. They have not been reconstructed or
presented as retained current evidence. The coordinator's 13:53 UTC readiness
observation on 2026-11-24 is historical only; it reported source/input and
capacity blockers, not native admission.

A new actual screen ran on the restored dirty checkout from **14:57:19.780907
to 14:57:22.109671 UTC on 2026-11-24**, using the checked CPython 3.12.14
interpreter. It returned **exit 1, `outcome="blocked"`**, with **254 rows: 224
observed, 26 blocked, three not checked and one unknown**. The
[raw report](evidence/governance-readiness/validation/readiness-restored-smoke.json)
is **114,687 bytes**, SHA-256
`a46a2bd6d18989fdaa0f62fa5757339bcd1d1dabae7558d6a2759bd4df01d7f6`;
the [observation receipt](evidence/governance-readiness/validation/readiness-restored-smoke.proof.json)
retains the exact command, timing and selected before/after invariants.

| Fresh observation | Meaning |
| --- | --- |
| All 69 frozen measurement source identities match; the diagnostic original's raw identity matches. | These selected inputs match; complete source admission is still blocked. |
| Dirty source and five uninitialized top-level gitlinks. | The restored checkout is not a clean complete native execution checkout. |
| Fifteen locked toolchain parts and five dependency repositories unavailable at the selected paths. | The screen reports absence; it does not download, extract or build them. |
| Control original absent at the explicitly selected local path. | This is local unavailability, not deletion or invalidation of the historical original. |
| Source/workspace share one filesystem with **2,877,046,784 free bytes**. | Against the **16,106,127,360-byte (15 GiB)** reserve, the deficit is **13,229,080,576 bytes**, before additional growth. |
| Host `MemAvailable` is **6,389,817,344 bytes**. | The host snapshot exceeds **4,294,967,296 bytes (4 GiB)**; effective cgroup capacity remains unknown. |
| `native_execution="not_run"`; nine qualification/acceptance flags false. | The screen establishes no native execution or qualification. |

Eight selected invariants stayed unchanged: HEAD, diagnostic hash, control and
workspace absence, empty archive/dependency directories, `ci/project` Python
source bytes, and the absence of Python bytecode. Other assigned agents could
edit documentation concurrently. This is not a whole-checkout no-write or
source-stability proof. The report reserves no capacity and cannot authorize
launch.

The historical local attempt-04 control original remains **47,632,218 bytes**,
SHA-256 `d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`.
Stable hosted delivery of those exact original bytes is unresolved. A summary,
repacked ZIP or historical source checkout does not replace it. Provision an
adequately sized environment, restore the exact local prerequisites and clean
complete source/gitlink closure, then independently establish effective memory
capacity and satisfy production admission. None of those requirements is waived
by this useful blocked observation.

## Frozen experiment and project gates

The [qualified-warm contract](../designs/qualified_warm_workspace_v1.md) still
requires **24 processes, 792 launches and 25,344 exact FP32 words**, retained with
**57 native command receipts**. The measured subset is **20 processes, 640
operations and 20,480 words**. Every prime and both warm-up pairs remain in the
original, excluded only from the frozen measured decision.

For each format independently, require
`100 * candidate_median <= 95 * reference_median`, nonincreasing host time for
every measured candidate/reference pair, and nonincreasing modeled cycles for
every measured pair. Do not remove outliers, replace samples or stop early.
A complete valid result can be unfavorable and remains useful evidence. No
fresh native performance outcome exists in this continuation.

P06-A01 retains its accepted simulated baseline; P06 and P06-T01 remain
`in_progress`, with P06-A02/A03 open. P01-A03 vendor XRT `hw_emu` remains blocked.
P07–P11 remain `not_started`. The original warm-v1 high-half block and all seven
historical false fields remain unchanged. No general CUDA compatibility,
PyTorch device backend, physical hardware performance, synthesis closure or
phase completion is claimed. The protected SVG, frozen pins and design contracts
remain unchanged. The [canonical phase manifest](roadmap.json) preserves every
phase state, dependency, criterion and evidence requirement; its P05-A01 evidence
pointer selects a new historical source-retention record as described below.

## Preserve the accepted Python API test identity

The final project check detected that the bytecode correction changes a test
file pinned by P05-A01. The accepted file is preserved as exact inert historical
source rather than assigned a new expected digest. The
[retention-only successor](evidence/governance-readiness/a01-retained-binding.json)
redirects only artifact 9's path to the original 50,638 bytes, SHA-256
`af6b5ed1aaeff080e9011bea9723e51119473bbcd900a80ed4591d5d37167165`.
Those bytes match both accepted revision
`e1420fd550f716df33a2556057b7086a03032cbe` and the pre-change published file.

The [chained mapping](evidence/governance-readiness/a01-source-retention.json)
retains the five previous historical mappings and adds this sixth one. All 58
artifact hashes, commands, configuration, source revision, acceptance IDs,
outcome and evidence level remain unchanged. The original acceptance and both
earlier successor files remain byte-for-byte unchanged. Only the P05-A01
canonical evidence pointer and current overview links select this successor.
The live test's new `-I -B` behavior remains separately tested development work;
no new native execution or acceptance is claimed by historical source retention.

After independent review and publication, allow the corrected full strict
hosted invocation to finish uninterrupted and retain its entire original.
Resolve native artifact delivery and adequate effective capacity, then rerun the
advisory screen and unchanged production admission before one fresh native
attempt. Preserve the original result, obtain complete independent inert replay,
and only then evaluate the frozen performance predicates and separate acceptance
obligations.
