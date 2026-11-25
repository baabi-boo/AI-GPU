# Agent 18 — restore operational review

## Disposition

No F2/F3 finding and no repository edits. Reviewed actual restore and retention-helper control flow at HEAD `622662ad9cece6da4e3375be7e977dbe04cde862` with other agents' uncommitted packaging/encryption fixes present. Owned scope was `p06_qualified_warm_restore.py` and, only if justified, a new `test_p06_restore_operational_review.py`; neither changed. Frozen contracts, proofs, thresholds and phase state remain untouched.

Confirmed validation before output creation; absent-only destination; descriptor-relative no-follow exclusive writes; private 0700/0600 modes; bounded descriptor ownership; source and copied-byte rechecks; fsync and marker ordering; fixed failure reports; preserved partial bytes and foreign replacements. Existing cleanup tests explicitly cover late close failures after marker removal: output may remain complete without a marker, but no success report escapes. This matches the documented non-transactional marker semantics.

## Executed checks

All commands ran from the repository root with `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, and `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3` (CPython 3.12.14).

| Command suffix | Actual result |
| --- | --- |
| `-m unittest discover -s ci/project -p 'test_p06_qualified_warm_restore.py' -v` | 19 passed, 0 failures/errors/skips; 0.441 s |
| `-m unittest discover -s ci/project -p 'test_p06_qualified_warm_retention*.py' -v` | 23 passed, 0 failures/errors/skips; 0.112 s; includes four package-to-restore integration methods |
| `-m unittest discover -s ci/project -p 'test_p06_qualified_warm_cleanup.py' -v` | 15 passed, 0 failures/errors/skips; 0.038 s |
| `/tmp/ai-gpu-ae456f837c05/agent18/probe.py` | 15 synthetic cases passed: baseline, one-shot EIO at each of 12 fsync boundaries, real source mutation during multi-chunk copying, foreign marker inserted after owned marker unlink plus late EIO |

The independent probe fills missing fsync/mid-copy/foreign-marker coverage. Every injected failure returned sanitized false-scope JSON, preserved the unrelated sentinel, retained incomplete output without recursive cleanup, and left descriptor identities unchanged. All output entries had effective-user ownership and 0700/0600 modes. The source remained byte-identical except for the intentionally mutated case; the baseline original and all synthetic failure fixtures remain under `agent18/fixtures/`. Probe observations: `agent18/probe.json`.

## SHA-256 identities

Paths below are relative to the repository unless prefixed `agent18/` (task directory). Restore's initial and final hash matched. Dependency hashes were recorded after the checks; root must qualify the final frozen combined source independently.

| File | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |
| `ci/project/p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |
| `ci/project/p06_qualified_warm_pack.py` | `b67c66bace419f08fa57ae244e81af21477f634d2d9d3be853393ea8f287fd6f` |
| `ci/project/p06_qualified_warm_encrypt.py` | `015ef01b1418ef5ef5328859c905854c928ab7c996aba9352603383ef648ca24` |
| `ci/project/test_p06_qualified_warm_restore.py` | `9ef2cb211135a3b4f024056208492a9aef389823d452174c7bfdd8efcab15fb6` |
| `ci/project/test_p06_qualified_warm_retention.py` | `5dfcd4d19743a64d000b58eaeff9f87e3ba74ba13dfe1827bbc0f784faa5efe2` |
| `ci/project/test_p06_qualified_warm_retention_integration.py` | `5cac800ffceebaf7729bd23ef29a9694d54e561834283b642b0a029837143f20` |
| `ci/project/test_p06_qualified_warm_cleanup.py` | `465be3759f5450809202f4a5be548ea8880cb8e737e1881fba72457d63da75de` |
| `agent18/probe.py` | `db35c69eea56c9a57aadad1e120d851c78008e0c119e8089dc65c88b11e0856d` |
| `agent18/probe.json` | `3ac8dfe1e9de8ec07dd607e35abfec9644c9efd87ad3f55b65a1c2dd389360b7` |

## Limits and next action

Linux synthetic host checks only: no real decryption/key, native run, full strict qualification, power-loss durability test, or exclusion of malicious concurrent same-user writers. No acceptance claim. Next action: include this unchanged-source review and probe in the consolidated packet, then run the required full strict suite against the final combined revision before admission of the real experiment.
