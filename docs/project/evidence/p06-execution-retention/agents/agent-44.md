# Agent 44 — final canonical test population

## Result

**5,164 unique canonical IDs: all 5,114 baseline IDs retained in their original
relative order, plus exactly 50 IDs from 14 new modules.** No removed IDs,
duplicates, loader errors, import-failure cases, imported `TestCase` bindings,
active skip flags or expected-failure flags were found. Added IDs and their order
exactly match Agent40's independently collected additions. No blocking population
finding.

Read BRIEF, AGENTS, canonical collection/runbook requirements, and Agent19/37/40
reviews. This final collection occurred **2026-11-25 12:51:02–12:51:04 UTC**.
HEAD stayed at base `622662ad9cece6da4e3375be7e977dbe04cde862`; candidate operational
edits were uncommitted. The original `notes/base-governance.zip` supplied
`run/discovered.json`; its 5,114 unique IDs, recorded count, ordered digest and
source revision independently validated.

## Method and stability

From the repository source root, used the prepared
`/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B`
(CPython **3.12.14**), with `PYTHONDONTWRITEBYTECODE=1`, task-specific
`TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, and the prepared venv plus `/usr/bin:/bin`
on PATH. One ordinary `unittest.TestLoader().discover("ci/project",
pattern="test_*.py")` call supplied the unchanged runner's `collect_test_ids` and
newline-delimited `_ids_digest`. Exit **0**, approximately **2.6 seconds**.
No runner, setup/teardown or test body was called.

All **22 paths** in `validation/operational-source-freeze.json` matched their
recorded size, mode and SHA-256 before and after collection. The freeze record
itself stayed unchanged. All **492 `ci/project/**/*.py` files** also retained
identical SHA-256 inventories before/after. Individual frozen-source identities,
aggregate hashes, interpreter details and all comparison predicates are retained
in `agent-44-population.json`.

| Added module, under `ci/project/` | IDs |
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
| `test_p06_pack_operational_failures.py` | 4 |
| `test_p06_pack_setup_cleanup.py` | 2 |
| `test_p06_prelaunch_review.py` | 2 |
| `test_p06_warm_supervision_failures.py` | 1 |

## Retained identities

| Record | SHA-256 |
| --- | --- |
| Original baseline ZIP | `928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156` |
| Baseline ordered IDs | `a33e6215dd12a601aefe3161615083699a8e9fef0ef22a9faaef0331939a71cd` |
| Candidate ordered IDs | `d154be26f6e4c82cb1da4d58d7c0901ad552829415dd36315c73695b4368794f` |
| Complete `agent-44-discovered.json` | `70ddd7339544a865137583625575b833e27c08e81dd398a8ab39fee2d75fbf6d` |
| Comparison `agent-44-population.json` | `dae45f1feea95040b63b43e779e5d941373a56d930d02835cfbbe52265c8e53b` |
| Operational freeze record | `714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb` |
| Unchanged `governance_run.py` | `5fcb877775e5e35fd859686e875d0597d534326c679ff68b29f2151203d0bfdc` |

## Limits and next action

This establishes **collection preservation only**, not runtime test success or
full strict qualification. The four new signal tests' POSIX plus `/proc/self/stat`
guard is enabled here; collection cannot rule out runtime skips or failures.
No repository test/source edits, Git mutations, native work, test executions or
child agents occurred. Only external review artifacts were written.

Use this manifest to reconcile the final candidate's actual unchanged, complete,
uninterrupted strict invocation and retained closure evidence. Any later test
change requires a new population record. Native execution, P06-A02/A03 and phase
acceptance remain outside this audit.
