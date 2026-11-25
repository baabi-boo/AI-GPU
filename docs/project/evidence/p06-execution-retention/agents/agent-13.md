# Agent 13 — control receipt and transport cleanup follow-up

Base: `622662ad9cece6da4e3375be7e977dbe04cde862`, with agent 06's existing control changes and concurrent disjoint work preserved. Read the task brief, AGENTS, relevant phase/status/backlog/acceptance material, review/resource policies, automation retention contract and agent 06 report. No Git writes or publication.

## Ownership and changes

Owned only `ci/project/p06_qualified_warm_control.py`. Agent 12 independently owns `ci/project/test_p06_control_closeout_review.py`; no test file was edited by this agent.

- `_open_https` now preserves an active primary exception, including `KeyboardInterrupt`, while attempting response and connection cleanup. If cleanup is the first failure, its first exception still propagates to acquisition's sanitized classification.
- Receipt close now occurs inside guarded finalization. A close failure that has already released the descriptor triggers best-effort failure rewriting through a newly opened descriptor only after the named inode matches the originally owned inode. Recovery uses `O_NOFOLLOW | O_NONBLOCK`, pre-open identity/type/link/mode/owner checks, and post-open descriptor/path/ownership checks before truncation or writing. It does not retry a consumed descriptor or modify an unowned pathname replacement. A recovery-close exception cannot replace the sanitized `receipt_failed` error.
- Existing repair through a still-owned descriptor remains available when the receipt pathname has been replaced before close. Archive bytes are untouched. Existing primary failure receipts retain their earlier reason; a failed success receipt becomes `outcome=fail`, `original_verified=false`.

Root explicitly confirmed that ownership-checked recovery reopening is acceptable; opening a concurrently substituted name never makes that inode owned or authorizes mutation.

## Reproduction and validation

Agent 12 retained the pre-fix red result against `dafcef93de23adbe607dee9c4f1a439211cb2d493fae5689c66e45f253eab95b`: four new methods, five failing assertions/subtests. Actual three-byte archive writes followed by ENOSPC were reclassified as transport failures when response/connection close raised EIO; interrupted partial reads were similarly reclassified. Receipt close-then-EIO escaped as raw OSError while preserving a success-shaped receipt. See `notes/agent-12-red-tests.log`.

From the repository root, using checked CPython 3.12.14:

```sh
env PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PYTHONPATH=ci/project /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_control_closeout_review test_p06_control_operational_failures test_p06_qualified_warm_control
```

Initial run: **47 tests in 0.497 seconds, OK**. Retained rerun: **47 tests in 0.502 seconds, OK**, `notes/agent-13-tests.log`. `git diff --check -- ci/project/p06_qualified_warm_control.py` passed. Coverage includes both primary exceptions, cleanup-only transport failure, receipt close-then-EIO, receipt symlink replacement pointing to the archive, earlier receipt fsync/path-replacement regressions, production pins, bounds, privacy, exclusivity and original transport tests. No network or native execution occurred.

## Exact source identities

| Path | SHA-256 |
| --- | --- |
| Before: `ci/project/p06_qualified_warm_control.py` | `dafcef93de23adbe607dee9c4f1a439211cb2d493fae5689c66e45f253eab95b` |
| After: `ci/project/p06_qualified_warm_control.py` | `ef5c127094e8e51aa5d5cfc101135e493de13c4be25c6979002cc7e6acc11a9d` |
| `ci/project/test_p06_control_closeout_review.py` | `8502a9c800a864aaa947e3f9a68f112a5213ce8401a59121ad16514a811b72a2` |
| `ci/project/test_p06_control_operational_failures.py` | `b281681fdf158062be763ce46aecff9b18634faba937072e490636a99b494e09` |
| `ci/project/test_p06_qualified_warm_control.py` | `9dddf361cc18d72b40636156e36f40d359c36872bebae9925e6c96a063808ead` |
| `notes/agent-13-tests.log` | `b616d474c0cd7d4e6600224ea7f0d8f3e786c7ce105ba18ff3bd728b49fefdae` |

## Limits and next action

No pins, proofs, schema, gates, resource thresholds or measured/native files changed. No full strict qualification or phase acceptance is claimed. Failure repair is best effort: ongoing storage failure can prevent rewriting; an originally owned inode renamed after its last descriptor closes is not searched for or mutated through an unowned replacement. Abrupt process death and malicious same-user races are not made atomic.

Fresh independent review is pending for the newly introduced recovery reopening race and repeated recovery-close failure boundaries. Root will assign it after this slot is freed. Also inspect the pre-existing outer `acquire_control` archive/directory closes during that review: they remain outside receipt finalization and could independently raise after a receipt was written; that adjacent boundary was not altered or tested in this assigned two-finding follow-up.
