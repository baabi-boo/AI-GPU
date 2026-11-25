# Agent 47 — independent whole-production-diff review

## Disposition

**One remaining F2 finding: final packaging output close masks an active primary failure.** High confidence; evidence type **static-proof**, supported by six executed real-descriptor fault cases. Reported immediately to the coordinator, who assigned a separate implementation and independent review. This report does not approve that future correction.

Reviewed every changed production hunk against base `622662ad9cece6da4e3375be7e977dbe04cde862` under `docs/review/code-review-policy.md`. Read BRIEF, AGENTS, the automation/retention contract and audit, reports 21/23/27/28/30/34/38/42, the frozen manifest, affected functions and their callers/cleanup consumers. No production, repository test, contract, proof or Git mutation. Only outside-repository reviewer artifacts were written.

## Finding and concrete reproduction

At frozen `ci/project/p06_qualified_warm_pack.py:594–595`, the newly added unconditional `finally: os.close(output_fd)` runs after `_package` re-raises its primary error. If that close consumes the descriptor and reports EIO, Python raises the EIO instead. This escapes the primary-error protection already present in the setup guard and directory-traversal corrections.

The retained `agent-47-final-close-probe.py` calls **both** public packaging APIs with separate real temporary source/workspace/output directories. It injects `KeyboardInterrupt`, `ValueError` or `RuntimeError` at inventory, then really closes the owned output descriptor and raises the same secondary EIO instance. Real `open` plus `dup2` assigns `/dev/null` to the consumed descriptor number before error delivery.

**Six cases reproduced the defect:** all exposed secondary EIO, none exposed the primary; the primary survived only as exception context. Each failed private receipt retained the correct primary type and `outcome=fail`. Output closure was attempted once; the unrelated reused descriptor survived. Thus the demonstrated defect is exception precedence, not false success, foreign-descriptor mutation or evidence deletion. No native process or network action was involved.

The initial reuse harness assumed that the next `open` would naturally reuse output fd 4; it instead selected the already-free fd 3. Those initial script/log artifacts remain separately retained as `agent-47-initial-harness.*` and are **not** the six-case evidence. The corrected probe explicitly assigns the consumed number and rejects unexpected harness exceptions.

Command, source-root cwd, prepared CPython 3.12.14:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PYTHONPATH=ci/project /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/notes/agent-47-final-close-probe.py
```

Exit 0 records successful reproduction; it is **not** a passing regression result. JSON stdout is retained in `agent-47-final-close-probe.log`.

## Complete production-hunk coverage

Counts use `git diff --unified=0`: **65 hunks**, all inspected with surrounding control flow.

| Helper | Hunks | Reviewed changes and result |
| --- | ---: | --- |
| `control` | 16 | Response/connection closure and exception precedence; traversal ownership; write/readback storage classification; owned receipt repair, reopen validation and close-error sanitization; archive/receipt/directory finalization. No further F2/F3 demonstrated. |
| `encrypt` | 9 | Documented observation limits, traversal ownership, complete directory-chain verification and four inventory/publication/cleanup checkpoints. Traced precommit summary-first withdrawal and committed-pair preservation: later checks do not remove the last encrypted copy. |
| `hosted` | 4 | Signal import/decorator, matching terminal native-disposition reader and guarded failure recovery. Stable selected sources plus resolved outer/nested writers are required; recovery changes no success boolean. |
| `inputs` | 4 | Signal import/decorator, explicit unknown command intent and prelaunch checkpoint failure state. The catch ends before `run_bounded`; executor uncertainty cannot become known-unstarted. |
| `pack` | 28 | Traversal ownership; descriptor-anchored read/create/receipt helpers; setup cleanup; output inode/mode checks around writes, verification and publication; anchored rollback and failure inventory. Final descriptor close has the F2 above; no additional reachable F2/F3 demonstrated. |
| `run` | 4 | Signal import/decorator, retained signal-helper population and prelaunch stage correction. Only the not-entered warm stage resets to `not_run`; prior stage observations remain. |

The new signal dependency is included in runner `SOURCE_FILES`, inherited by hosted inventory, and covered by existing live/copied/before/after identity checks. No source-binding omission found. Observational checks are not hostile-writer exclusion or crash transactions; those documented limits were not treated as bugs.

## Exact reviewed identities

All **22** manifest rows independently matched SHA-256, size and mode after reproduction. Manifest SHA-256: `714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb`. This is the pre-correction freeze; later fixes need a distinct snapshot.

All production paths below are `ci/project/p06_qualified_warm_<helper>.py`.

| Helper | SHA-256 |
| --- | --- |
| control | `a303c3dc56076bbb203376521534e465c5d97b997c9ae1b93e6375e98d298fcd` |
| encrypt | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| hosted | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| inputs | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| pack | `e4cff314b8a2a0dbb277baef1bc5b3eb78b10a90f777a4d3b60ff74b682dac0e` |
| run | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |

Probe SHA-256: `245402ecbf431aa40dd5ad2f3cd9945175159b157edfb28528f62a0ae8efed56`. Reproduction log SHA-256: `eedfb7170d83e4103967a15ed3c5a3f4ff07c1cf0dc3b05299596c832bb50cf4`.

## Limits and next action

Agent42's 325 focused passes are prior source-bound development evidence, not rerun here and not coverage of this missing exceptional boundary. No broad tests, native work, strict governance or phase acceptance occurred. Preserve the primary on exceptional cleanup, keep a standalone close failure fatal, attempt each owned close once, and independently validate the correction. Root owns final snapshot, strict qualification and publication.
