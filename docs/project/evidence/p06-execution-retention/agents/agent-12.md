# Agent 12 — independent control-intake closeout review

Reviewed base HEAD: `622662ad9cece6da4e3375be7e977dbe04cde862`, with concurrent operational edits. Read the task brief, repository AGENTS instructions, author report `agent-06.md`, current status/backlog/roadmap/acceptance context, review severity policy, and qualified-warm automation failure/retention and private-artifact contract. Reviewed every changed production hunk, the three-line existing `Response.close()` fixture change, and the complete new operational-failure module. Production remained read-only; no commits or Git publication.

## Findings requiring correction

### F2 — cleanup overwrites the primary transfer/storage disposition

Confidence: **high**. Evidence: **static-proof plus executed synthetic reproduction**. In `_open_https`, either `response.close()` or `connection.close()` raising replaces the pending exception from the transfer body. A real three-byte write followed by injected archive `ENOSPC`, followed by injected response and/or connection `EIO`, produces retained `reason_code="transport_failed"` instead of `storage_failed`. A partial `KeyboardInterrupt` followed by both close errors likewise becomes `transport_failed` instead of `interrupted`. Both cleanup attempts occur, and the actual partial archive remains intact, but the original operational diagnosis is lost. Preserve the first failure while attempting both cleanups; a cleanup failure with no prior failure must still fail the intake.

### F2 — receipt close failure bypasses success invalidation

Confidence: **high**. Evidence: **static-proof plus executed synthetic reproduction**. `_write_receipt` handles writes, file/directory fsync and identity checks in its guarded body, but its final `os.close(descriptor)` runs outside that handler. Injecting one receipt close that calls the real close and then raises `EIO` makes `acquire_control` raise raw `OSError` while the retained receipt still reports `outcome="pass"` and `original_verified=true`. The archive remains exact. This is the same success-shaped failure record the new finalization invalidation seeks to prevent. Repair must remain anchored to the originally owned inode even when the close has already released the fd; reopening an unchecked pathname is unacceptable. Continuing storage failure and process death remain distinct limits.

Both F2 findings were sent immediately to root. Root assigned Agent 13 to the production correction; Agent 13 received the exact red-test hash and confirmation that the production source was frozen for reproduction before edits began. No F3 finding was identified in this scope.

## New independent regression coverage

Owned new file only: `ci/project/test_p06_control_closeout_review.py`.

- Three cleanup combinations exercise real partial archive writes and preservation of the first `storage_failed` reason.
- Partial interruption exercises both failing cleanup calls and retention of the `interrupted` reason.
- Receipt close after actual fd release must invalidate the owned success and expose sanitized `receipt_failed`.
- A receipt pathname replaced with a symlink to the sole retained archive must remain unchanged; invalidation must change only the renamed owned receipt inode and preserve the archive byte-for-byte. This boundary already passes.

The reviewed ordinary receipt-fsync and directory-fsync repair correctly uses the exclusively created descriptor. Existing regular replacement preservation passes. `_write_all` and `_retained_identity` translate local `OSError` failures without translating `IntakeError` ownership failures, and do not print the private URL or exception details. The fixture `.close()` implementation is an appropriate response-ownership stub.

## Executed checks

Environment: checked CPython 3.12.14 at `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`; source-root working directory; `PYTHONDONTWRITEBYTECODE=1`; `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`; `PYTHONPATH=ci/project`.

1. `python3 -m unittest -v test_p06_control_operational_failures test_p06_qualified_warm_control`: **43 tests in 0.510 seconds, OK**, zero skips/errors/failures. Includes the unchanged production historical pin/proof check and existing sanitization, resource bounds and private-permission cases.
2. `python3 -m unittest -v test_p06_control_closeout_review`: **4 tests in 0.023 seconds; FAILED (failures=5)**. The symlink-to-archive case passes; receipt-close, three storage/close combinations and interruption/close fail as described. Full output retained in `/tmp/ai-gpu-ae456f837c05/notes/agent-12-red-tests.log`.
3. Separate inert probes confirmed raw `OSError` from receipt close, retained `pass/true`, exact archive preservation, and one response/connection cleanup attempt each after disk-full injection.
4. Scoped `git diff --check` passed for the reviewed tracked hunks. No full strict suite, GPU build or native experiment was run.

## Exact red-source identities

These hashes identify the source tested before Agent 13 was released to edit production. They do not qualify a later correction.

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_control.py` | `dafcef93de23adbe607dee9c4f1a439211cb2d493fae5689c66e45f253eab95b` |
| `ci/project/test_p06_qualified_warm_control.py` | `9dddf361cc18d72b40636156e36f40d359c36872bebae9925e6c96a063808ead` |
| `ci/project/test_p06_control_operational_failures.py` | `b281681fdf158062be763ce46aecff9b18634faba937072e490636a99b494e09` |
| `ci/project/test_p06_control_closeout_review.py` | `8502a9c800a864aaa947e3f9a68f112a5213ce8401a59121ad16514a811b72a2` |

## Limits and next action

All transfers used inert fixture bytes and synthetic signed-looking URLs through mocked connections. No live network, private control original, key, hosted dispatch, source-pin change, gate change, acceptance decision or performance measurement occurred. Fault injection establishes reachable Python control flow, not actual filesystem or provider fault incidence. The four new methods are development regressions, not strict governance qualification. Agent 13 must correct both F2 findings while preserving inode ownership, first-error semantics and all private bytes; an independent reviewer must then rerun the focused suite on the new exact hash. Root retains responsibility for complete frozen-source strict governance and authorized publication.
