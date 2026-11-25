# Agent 17 — retention reader boundary

**Verdict:** no concrete uncovered defect reproduced; no production or repository-test changes. Reviewed the assigned `ci/project/p06_qualified_warm_retention.py`, producer serialization, existing reader/integration tests, `AGENTS.md`, current project constraints and retention contract. Base HEAD was `622662ad9cece6da4e3375be7e977dbe04cde862`; other agents' candidate edits were present and preserved. No git writes.

## Actual validation

From `/tmp/ai-gpu-ae456f837c05/AI-GPU`, with `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, and `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3` (CPython 3.12.14):

- `-m unittest discover -s ci/project -p 'test_p06_qualified_warm_retention*.py' -v`: **23 tests, 0 failures/errors/skips**, exit 0, 0.114 seconds.
- `-B /tmp/ai-gpu-ae456f837c05/notes/agent-17-probes.py`: **21 observations passed**, exit 0. Nineteen negative mutations rejected: oversized/negative/negative-zero/4,301-digit integers, exponent token, nested duplicate key, sharp-s and final-sigma casefold collisions, Boolean directory, malformed PAX length/terminator/fallback, summary count/type/size/extra-key/duplicate-key errors, and actual 64-KiB summary overflow. Two positives confirmed syntactically valid ciphertext metadata remains consistency-only and agent 14's genuinely decrypted synthetic tar reinspects successfully.
- Reinspection independently matched plaintext SHA-256 `9e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613`, 20,480 archive bytes, 8 files, 3 directories, 8,680 input bytes. Subprocess creation and tar extraction were patched to raise during this read. All native/origin/execution/acceptance claim fields retained their required false/not-run values. I did not repeat encryption/decryption.

The reader compares exact producer headers/PAX records, validates canonical manifest bytes and declared parents, rejects duplicate/casefold aliases, verifies each opaque payload, enforces exact archive length and zero framing, and rehashes inputs on normal exit. Existing tests establish 64-KiB bounded reads and short-write handling. Reports contain fixed aggregate metadata and no retained path/payload claims.

## Source SHA-256

Paths below are relative to the repository; unchanged during this review:

| Source | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |
| `ci/project/p06_qualified_warm_encrypt.py` | `015ef01b1418ef5ef5328859c905854c928ab7c996aba9352603383ef648ca24` |
| `ci/project/p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |
| `ci/project/test_p06_qualified_warm_retention.py` | `5dfcd4d19743a64d000b58eaeff9f87e3ba74ba13dfe1827bbc0f784faa5efe2` |
| `ci/project/test_p06_qualified_warm_retention_integration.py` | `5cac800ffceebaf7729bd23ef29a9694d54e561834283b642b0a029837143f20` |
| `docs/designs/qualified_warm_retention_review_v1.md` | `364038856334f0c4c8cf7d7a27fea4d81682a11bbcafee98f6a0a1099e794f01` |

Supplementary probe source: `notes/agent-17-probes.py`, SHA-256 `fe1ae24cdc55c3f394c64722e5a3663415c77076a123db343fc57b4612965f98`; actual results: `notes/agent-17-probes.json`, SHA-256 `2aac3949fb68673d587fe4bd06aff0abcf044f13bbb0972a7db7c09c3f5e166a` (both outside repository).

## Limits and next action

Linux/POSIX development checks only; no maximum-size RSS stress, hostile-writer exclusion, cryptographic audit, provider delivery validation, full strict governance or native run. JSON parsing is byte-bounded but peak object overhead was not measured. Reader success does not authenticate ciphertext or complete native work. Keep production unchanged for this boundary and bind root's integrated verification to final frozen sources. P06-A02/A03 remain open.
