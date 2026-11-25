# Agent 01 — hosted failure disposition audit

## Scope and actual work

Reviewed hosted composition, exact-governance admission, provisioning environment/tool selection, selected-source stability, stage/cleanup ordering, and public encrypted-output authorization against the automation contract and existing hosted regressions. Base revision: `622662ad9cece6da4e3375be7e977dbe04cde862`. Edited only `ci/project/p06_qualified_warm_hosted.py` and new `ci/project/test_p06_hosted_operational_failures.py`; no commits. Other agents concurrently changed their owned files.

## Reproduced finding and fix

A started native supervisor that returns nonzero causes `stage()` to raise before the hosted wrapper reads its finished raw receipt. The previous closeout then replaced every such attempt's native disposition with `unknown`. A preparation/build failure with recorded `native_execution=not_run`, or a completed native failure with recorded `native_execution=run`, therefore lost its observed disposition in both the hosted envelope and encrypted closeout selection. The automation contract requires native disposition according to observed child evidence, separately from pass/fail.

Pre-fix fixture reproduction produced the two exact pairs `not_run -> unknown` and `run -> unknown`; both attempts remained failed, had `writers_finished_observed=true`, and reached mocked encrypted retention. The first new regression run executed 4 tests in 3.368 seconds and failed the two corresponding disposition subtests before implementation.

Added a bounded receipt observation for finished exact-revision, expected-contract supervisor reports. Closeout consults it only after selected operational source stability and existing complete writer/cleanup observations succeed. It preserves the observed `not_run`, `run`, or `unknown` without changing failure outcomes, orchestration/qualification booleans, stage admission, performance decisions, budgets, source proofs, or encrypted delivery requirements. Missing/malformed/nonterminal/wrong-revision/wrong-contract dispositions remain unknown. Unknown outer launch, unresolved inner writer, and source drift still prevent borrowed certainty and delivery.

This composes with Agent 02's explicit no-launch checkpoint failure: the supervisor can finish with `not_run`, a never-invoked inner stage records `process_started=false` and completed cleanup, and no child report is fabricated.

## Actual validation

Runtime: `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`; environment included `PYTHONDONTWRITEBYTECODE=1` and `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`. Commands ran from the source root.

- `python3 -m unittest discover -s ci/project -p 'test_p06_hosted_operational_failures.py' -v`: **6 tests passed**, 3.629 seconds; zero skips/errors/failures. Covers preserved dispositions in the selected receipts, exact report binding, nonterminal reports, unknown outer launch, unresolved nested writer, observed nested prelaunch failure, and source drift.
- `python3 -m unittest discover -s ci/project -p 'test_p06_qualified_warm_hosted.py' -v`: **34 tests passed**, 4.186 seconds; zero skips/errors/failures. Existing trusted governance, source cleanliness/stability, budgets, failure packaging, public output integrity/privacy and upload authorization checks remain passing.
- `git diff --check -- ci/project/p06_qualified_warm_hosted.py ci/project/test_p06_hosted_operational_failures.py`: passed.

These are host fixture development checks; no apt/package download, native run, real encryption, upload, or new strict full governance qualification was performed. Existing fixtures mock external provisioning and native command execution. No concrete additional provisioning or governance-admission defect was demonstrated in this bounded audit.

## Source identities

Original hosted helper SHA-256 before edits: `0ce58a094ae924ef81ec05a8d6bfcec50ddea27dd1a5b6e6522f63a6e5519d25`.

Final changed-file and principal reviewed-file SHA-256 observations:

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_hosted.py` | `eba46917d1cdc7dafea97c98ac92a41313f7ce86b62db40f66de36356651cda5` |
| `ci/project/test_p06_hosted_operational_failures.py` | `ad165dd0ec63cc7e0b6e547ba1b504f06f0ba3876e29aa6d75163ab442033eb9` |
| `ci/project/test_p06_qualified_warm_hosted.py` | `d14fef2b03981987b8d313cad56a3d0085c577a5a6c615832acd3422d6f5ea6f` |
| `ci/project/p06_dependency_local_prepare.py` | `c810f31cf6106a5bbcd6eddcf8d818560cb94222da057fe9491a8e1dbc99316f` |
| `ci/project/p06_dependency_build.py` | `ec40c043aba91c68fafe1b15449b3df466fb6a0decbabd5a9c21cac38ca39f94` |
| `ci/project/baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `.github/workflows/p06-qualified-warm.yml` | `261efa4bcf9c2ca7a9bca8a25dcb03eefd70848426a4c6c61ca55b68a14a7b2e` |
| `.github/workflows/project-governance.yml` | `bf4c2a469772b8beccaf9e3d973b268305bf7605be545f4a0b477cfd0b17cb56` |
| `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |
| `docs/project/p06-hosted-warm-guide.md` | `03de73f6d4dd6c5c5c25d350f21c35bc1534d9f71214988703b7cc84c100c47c` |

## Remaining action and limitations

Root should independently review this operational disposition change, consolidate source-scoped evidence, and obtain the final published revision's full strict governance result. The fresh 24-process/792-launch/25,344-word experiment remains unstarted and still needs the private original, configured public age recipient with separately held key, and unchanged capacity/native admission. Preserving failed-stage observations grants no replay, performance, phase, FPGA, or vendor qualification.
