# Agent 06 — exact private control intake operational review

Reviewed base: `622662ad9cece6da4e3375be7e977dbe04cde862`, with concurrent worker changes outside this assignment. Read the repository AGENTS instructions, task brief, current phase/status/backlog/acceptance material and the qualified-warm automation failure/retention contract. No Git writes or publication performed.

## Owned changes

- `ci/project/p06_qualified_warm_control.py`
- New `ci/project/test_p06_control_operational_failures.py`
- With root's explicit follow-up authorization, only the three-line `Response.close()` fixture addition in `ci/project/test_p06_qualified_warm_control.py`.

## Reproduced defects and correction

1. **Receipt finalization failure retained success.** A synthetic `EIO` from either the receipt file's fsync or the output directory's fsync raised `receipt_failed`, but the retained JSON still said `outcome=pass`, `original_verified=true`. A pathname replacement after writing similarly left the owned, renamed receipt with a success claim. Failure handling now truncates and rewrites only the exclusively created receipt descriptor with a sanitized failure disposition. Original archive bytes remain untouched; a replacement at the receipt pathname is not opened, overwritten or removed. Existing primary failure reports retain their failure details.
2. **Local storage faults were mislabeled as transport faults.** Synthetic `ENOSPC` after three actual archive bytes produced `transport_failed`; archive fsync `EIO` did likewise. Writes and retained-byte fsync/readback now translate `OSError` into the existing `storage_failed` reason. Partial bytes and their actual digest remain retained when readable; failed readback remains explicitly unavailable.
3. **Unread response ownership was lost.** Using the real `http.client` response parser with an in-memory socket and `Connection: close`, rejection/interruption left the response body open after `_open_https` exited. It now explicitly closes the response and attempts connection closure even if response closure raises. No network is used in this reproduction.

## Validation

Environment: checked CPython 3.12.14 interpreter at `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`; `PYTHONDONTWRITEBYTECODE=1`; `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`; `PYTHONPATH=ci/project`; repository root working directory.

Before changes, `python3 -m unittest -v test_p06_control_operational_failures` ran 6 tests and failed 8 assertions (including subtests), reproducing the faults above.

After changes, `python3 -m unittest -v test_p06_control_operational_failures test_p06_qualified_warm_control` ran **43 tests in 0.491 seconds, OK**. This includes the existing exact production pin/proof test, timeout/interruption/partial-byte checks, URL/secret rejection, exclusivity, private permissions, and bounded intake checks. `git diff --check` passed.

## Source identities

Before implementation:

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_control.py` | `ab064f9716fd3ede94991acc2f03d4eb6a1510048d22b2eedbed7ccc77d1713b` |
| `ci/project/test_p06_qualified_warm_control.py` | `39a4e526f441df7201d3d901edcf6ed24b411b79ceb29da4b482da96659f2056` |

Validated changed sources:

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_control.py` | `dafcef93de23adbe607dee9c4f1a439211cb2d493fae5689c66e45f253eab95b` |
| `ci/project/test_p06_qualified_warm_control.py` | `9dddf361cc18d72b40636156e36f40d359c36872bebae9925e6c96a063808ead` |
| `ci/project/test_p06_control_operational_failures.py` | `b281681fdf158062be763ce46aecff9b18634faba937072e490636a99b494e09` |

## Limits and next action

Only inert fixture bytes and synthetic signed-looking URLs were used. No live storage, real private controls, secrets, native GPU execution, acceptance evaluation or full strict suite was accessed/run. Archive pins, proofs, byte/time/resource bounds, gates, and receipt schema are unchanged. If continuing storage failure also prevents descriptor truncation or failure-record rewriting, receipt repair cannot be guaranteed; the API still raises `receipt_failed` and the existing requirement to observe successful invocation remains necessary. Abrupt process death is not an atomic receipt transaction. Root should independently review these source changes, consolidate evidence and run full strict governance on the frozen combined revision before publication.
