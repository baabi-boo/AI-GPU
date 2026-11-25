# Agent 21 — independent final control lifecycle review

Base HEAD: `622662ad9cece6da4e3375be7e977dbe04cde862`. Read the brief, AGENTS, agents 06/12/13/16, applicable project status/roadmap/backlog/acceptance context, review policy, and automation retention contract. Reviewed the entire control diff against HEAD, the response fixture adjustment, and all three existing new control test modules. Production remained read-only for this agent; root made the final correction below. No Git writes or publication.

## F2 found and closed

**High confidence; static proof and executed integration reproduction.** Recovery after a consumed output-directory close calls `_open_directory`. Its preexisting traversal opened a child, closed its parent, and on close failure attempted to close the same consumed parent again while leaking the child. This helper newly participates in the recovery path. At reviewed source `edb6c8e65191087da0278d5235d31cc4080d3b4e6f9f30c2147d3f5de4fa4ccc`, the scratch integration probe injected real directory close plus EIO, then real intermediate recovery close plus EIO. Opening `/dev/null` between consumption and error delivery modeled another thread reusing the descriptor. Observed close attempts were `[3, 3]`: the unrelated reused descriptor was closed and recovery child 4 leaked. Archive bytes and sanitized `storage_failed` were preserved. Reported immediately to root; exact observations are in `notes/agent-21-recovery-probe.log`.

Root corrected traversal by transferring tracked ownership to the opened child before closing the parent. Exceptional cleanup attempts that currently owned child once and preserves the primary exception if cleanup also fails. Independently reviewed the correction and added only `ci/project/test_p06_control_final_review.py`: its integration regression verifies the actual reused unrelated descriptor stays open, opened recovery children close, and the error/archive remain sanitized/intact. **F2 closed; no remaining F2/F3 identified in the reviewed changed lifecycle.**

## Review conclusions

Transport cleanup preserves the first transfer/storage/interruption exception while attempting both resources. Archive closure precedes receipt publication. Receipt and directory close failures are sanitized, preserve existing reasons, and attempt required later cleanup. Recovery reopening is bounded and checks saved inode, regular-file type, link count, owner and private mode before opening; `O_NOFOLLOW | O_NONBLOCK` and post-open descriptor/path checks precede any truncation. Replaced paths are not granted ownership. Recovery endpoint close errors cannot suppress the other cleanup attempt or replace the primary failure. Direct descriptor repair remains anchored to the exclusively created inode. Pins, schemas, resource limits and acceptance gates are unchanged.

## Executed validation

Checked CPython 3.12.14 at `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`; source-root working directory; `PYTHONDONTWRITEBYTECODE=1`; `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`; `PYTHONPATH=ci/project`.

- Initial four modules: **55 tests in 0.763 seconds, OK**, zero failures/errors/skips; `notes/agent-21-tests.log`.
- Independent scratch recovery probe on the initial hash reproduced the F2 above; every leaked test descriptor was explicitly released afterward.
- Final five modules: `python3 -m unittest -v test_p06_control_final_review test_p06_control_finalization test_p06_control_closeout_review test_p06_control_operational_failures test_p06_qualified_warm_control`: **56 tests in 0.602 seconds, OK**, zero failures/errors/skips; `notes/agent-21-final-tests.log`.
- Scoped `git diff --check` passed. Final source hash rechecked after tests.

## Exact final identities

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_control.py` | `a303c3dc56076bbb203376521534e465c5d97b997c9ae1b93e6375e98d298fcd` |
| `ci/project/test_p06_control_final_review.py` | `2726f9b782f94b2e4cc5d9ec4df2c3335981ab9f2af6fcf642e96274c5429368` |
| `ci/project/test_p06_control_finalization.py` | `7020fea4b05a002f8d6353aed429d66e4162f9e2d4f202a0ca401edfb2c6e06c` |
| `ci/project/test_p06_control_closeout_review.py` | `8502a9c800a864aaa947e3f9a68f112a5213ce8401a59121ad16514a811b72a2` |
| `ci/project/test_p06_control_operational_failures.py` | `b281681fdf158062be763ce46aecff9b18634faba937072e490636a99b494e09` |
| `ci/project/test_p06_qualified_warm_control.py` | `9dddf361cc18d72b40636156e36f40d359c36872bebae9925e6c96a063808ead` |
| `notes/agent-21-final-tests.log` | `558ba696050b944f782ccaba9c356ca05365d4debf92f87724bd62942eee775a` |
| `notes/agent-21-recovery-probe.py` | `2888dde918bad0bd9fc3c06a01f2d316a5c2b7246bf6c2d1fa0c6c5e2caf48f1` |
| `notes/agent-21-recovery-probe.log` | `d8bc276f51a5e40210b6919eae35adde0245de83c54117afb98f988ce4aecdba` |

## Limits and next action

Only inert fixtures and injected host failures were used. No native execution, live network/storage, private original/key, hosted dispatch, full strict governance, or phase acceptance occurred. Receipt repair remains best effort under continuing storage failure or renamed unreachable owned inodes; invocation failure remains authoritative. No crash atomicity or malicious same-user isolation is claimed. Root should qualify the final combined frozen source through strict governance and retain these exact review/results before authorized publication.
