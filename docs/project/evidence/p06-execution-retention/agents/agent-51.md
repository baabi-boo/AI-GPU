# Agent 51 — final publication canonical population

## Result

**5,167 unique canonical IDs**, retaining all **5,114 baseline IDs**
and all **5,164 Agent 44 IDs** in their original relative order.
The actual delta is **53 IDs across 15 new modules** against baseline,
including **3 new IDs** since Agent 44. All comparison checks passed:
**True**. Failed checks: `[]`.

No duplicate IDs, loader errors, import-failure cases, active skip flags,
expected-failure flags or imported test-bearing `TestCase` bindings were found.
Inspected all 319 loaded local test modules for imported bindings.

## Method and stability

Read BRIEF, AGENTS, Agent 44/48 reports, the strict runner's collection contract,
the governance runbook and the 23-file publication freeze. Collected from the
repository source root at **2026-11-25T13:06:40.570861+00:00–2026-11-25T13:06:44.709808+00:00**.
Used prepared CPython **3.12.14** with explicit `-B`,
`PYTHONDONTWRITEBYTECODE=1`, task-specific `TMPDIR`, and the prepared venv plus
`/usr/bin:/bin` on PATH. The retained collector is `agent-51-collect.py`.

Exactly one ordinary `unittest.TestLoader().discover("ci/project", pattern="test_*.py")`
call supplied unchanged `governance_run.collect_test_ids` and `_ids_digest`.
Call observation independently recorded **1 discovery call**,
**0 test-body calls** and
**0 fixture calls**. No runner was invoked.
No repository edits, Git writes, native execution or child agents occurred.

All **23 frozen paths** matched size, mode and SHA-256 before and after collection.
All **493 `ci/project/**/*.py` files** retained identical SHA-256 inventories.
The canonical runner matched baseline and Agent 44. HEAD remained `622662ad9cece6da4e3375be7e977dbe04cde862`.
The publication freeze, historical 22-file freeze and all three Agent 44 result
files remained byte-for-byte unchanged. Full inventories and checks are retained
in `agent-51-population.json`.

## Additions against baseline

| Module under `ci/project/` | IDs |
| --- | ---: |
| `test_p06_control_closeout_review.py` | 4 |
| `test_p06_control_final_review.py` | 1 |
| `test_p06_control_finalization.py` | 8 |
| `test_p06_control_operational_failures.py` | 6 |
| `test_p06_directory_cleanup_review.py` | 2 |
| `test_p06_encrypt_operational_failures.py` | 6 |
| `test_p06_encrypt_publication_review.py` | 1 |
| `test_p06_hosted_operational_failures.py` | 6 |
| `test_p06_input_operational_failures.py` | 3 |
| `test_p06_operational_cancellation.py` | 4 |
| `test_p06_pack_final_cleanup.py` | 3 |
| `test_p06_pack_operational_failures.py` | 4 |
| `test_p06_pack_setup_cleanup.py` | 2 |
| `test_p06_prelaunch_review.py` | 2 |
| `test_p06_warm_supervision_failures.py` | 1 |

The three additional IDs since Agent 44 are:

- `test_p06_pack_final_cleanup.PackagingFinalCleanupTests.test_final_output_close_failure_is_fatal_after_success`
- `test_p06_pack_final_cleanup.PackagingFinalCleanupTests.test_final_output_close_failure_is_fatal_inside_callers_except`
- `test_p06_pack_final_cleanup.PackagingFinalCleanupTests.test_primary_failure_survives_final_output_close_failure`

## Retained identities

| Record | SHA-256 |
| --- | --- |
| Baseline ZIP | `928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156` |
| Baseline ordered IDs | `a33e6215dd12a601aefe3161615083699a8e9fef0ef22a9faaef0331939a71cd` |
| Prior Agent 44 manifest | `70ddd7339544a865137583625575b833e27c08e81dd398a8ab39fee2d75fbf6d` |
| Candidate ordered IDs | `92fe769e153a9561a5ef375bdab45e41c0d99f4d9cd745b5ffdd159e8e5b6336` |
| Complete `agent-51-discovered.json` | `4201c48b402751b856bf30e3b36fac7f6cbdf4a0f489e73c23afd49e64b3e99b` |
| `agent-51-population.json` | `369338367d0a78efaf8636c8981b02fbc794c7766949085b28b503046912224d` |
| Publication freeze record | `6c90e8e2c097b1d8db3534835d4f8ae94c4f6dc2c20b1c59283342c0b1c2dbf8` |
| Canonical runner | `5fcb877775e5e35fd859686e875d0597d534326c679ff68b29f2151203d0bfdc` |

## Limits and next action

This establishes population preservation only. It does not establish runtime
test success, zero runtime skips or complete strict qualification. The signal
guard is enabled on this Linux host. Root should reconcile this actual manifest
with the subsequent complete uninterrupted strict invocation and retained closure
evidence. Native execution, P06-A02/A03 and phase acceptance remain outside scope.
