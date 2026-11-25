# Agent 14 — real age synthetic partial-retention round trip

## Scope and verdict

**PASS at synthetic retention scope; no new defect demonstrated.** Ran the real pinned age 1.3.2 executables through the existing production packaging, encryption, inspection and restoration CLIs. No monkeypatch, fake encryption child, network request, owner credential, native GPU work, production edit, repository test addition or git mutation was used. All work was isolated beneath a fresh owned `roundtrip-agent14/` directory with umask `077`.

The checkout remained based on `622662ad9cece6da4e3375be7e977dbe04cde862` with the audit's uncommitted candidate edits. That SHA is the synthetic manifest's explicit revision selector, **not a claim that the changed helpers are the clean base**. The four source identities below and the 89-module import-source manifest identify the actual tested candidate. Every imported repository Python source was rehashed after the run and remained unchanged. Read the project guide, relevant status/backlog/roadmap/acceptance context, automation and retention contracts, operator decryption guide and review policy.

## Observed results

- **Twelve subprocess invocations completed with their expected exits:** two version observations, packaging, key creation, public-recipient derivation, encryption, decryption, inspection, restoration and three negative CLI checks. CPython was 3.12.14. This is one integration validation with explicit assertions, not a claimed unittest or strict-governance run.
- The stopped fixture retained seven partial-ZIP members: a failed prelaunch orchestration receipt, an intentionally truncated preparation JSON, a binary payload, a hidden binary file, an empty file, an inert `.py` sentinel and an explicitly selected synthetic acquisition log. Neither native subtree was fabricated. Partial packaging succeeded while `partial_attempt=true`, `complete_replay_original_created=false`, and every historical qualification/acceptance flag stayed false.
- The encryption selection used a hosted-shaped `packet/` directory plus synthetic closeout/log data, a direct sentinel, binary/hidden/empty files and an empty directory: **8 files, 3 directories including the root, 8,680 input bytes**. Its production public output contained exactly `qualified-warm-retention.tar.age` and `encryption-summary.json`. The summary had exactly the ten contract keys. No plaintext marker or private-key marker appeared in those selected public outputs.
- The actual ciphertext was checked against its summary before private decryption: **20,680 bytes**, SHA-256 `a3b56b00aaf2cd8207ba435c4a9b2b23796e0f70796e1a2a92e797e8e0d3fd85`. The decrypted producer tar was **20,480 bytes**, SHA-256 `9e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613`.
- Inspection and restoration both exited **0** with `retention_verified=true`, `summary_checked=true`; restoration also returned `restoration_completed=true`. Every restored relative entry, directory and file digest matched the encryption input. The exact manifest bytes also matched. The original and restored inner ZIPs were byte-equal: **1,950 bytes**, SHA-256 `f4488c71f9573976a75f8380ca8d16f8d575ffa1ec9b46f3ad3e561c7aafcb03`.
- Original source/workspace/acquisition trees and the encryption selection retained identical content and identity stamps (device, inode, mode, links, size, mtime and ctime; atime intentionally excluded). The tar and ciphertext were unchanged after review. The malformed report and failed/partial closeout status remained opaque and unchanged.
- The executable-mode input sentinel stayed `0700`; its restored copy became `0600`. Every restored regular file was `0600`, every directory `0700`, and the sentinel's unique execution marker remained absent after all operations. No inner ZIP was extracted or retained code executed. No incomplete marker remained after the successful restore.
- Wrong plaintext SHA-256 and wrong expected revision each exited **1** with `retention-rejected`; the wrong-revision destination was never created. Reusing the successful destination exited **1** with `output-exists`, leaving the restored tree unchanged. Success and failure reports all retained `native_execution="not_run"`, `retained_code_executed=false`, `origin_authenticated=false`, and native/performance/phase acceptance false.
- The ephemeral identity was created privately at mode `0600`, never printed or committed, and unlinked immediately after the decryption attempt. It is absent. There is no secure-erasure claim.

## Exact commands

Working directory: `/tmp/ai-gpu-ae456f837c05/AI-GPU`. The one-shot validation invocation was:

```sh
umask 077
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/validate_roundtrip.py
```

The driver used the existing production CLIs without patching their APIs. Every child ran with the explicitly constructed environment `PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`, `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, in the same working directory. Below are the actual sanitized argv renderings. `<EPHEMERAL_PUBLIC_RECIPIENT>` replaces the public value derived by `age-keygen -y`; the identity path is displayed, its contents are never included.

```sh
# age-version — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age --version

# age-keygen-version — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age-keygen --version

# package-partial — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_pack.py partial --source-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/synthetic-source --workspace-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/synthetic-workspace --output-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/selected-retention/packet --writers-finished --extra-root acquisition=/tmp/ai-gpu-ae456f837c05/roundtrip-agent14/synthetic-acquisition

# keygen — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age-keygen -o /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/ephemeral-identity.PRIVATE.txt

# recipient — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age-keygen -y /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/ephemeral-identity.PRIVATE.txt

# encrypt — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_encrypt.py --input-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/selected-retention --output-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/public-delivery --recipient '<EPHEMERAL_PUBLIC_RECIPIENT>' --age-binary /tmp/ai-gpu-ae456f837c05/roundtrip-tools/age --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862

# decrypt — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age --decrypt -i /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/ephemeral-identity.PRIVATE.txt -o /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/decrypted-retention.PRIVATE.tar /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/public-delivery/qualified-warm-retention.tar.age

# inspect — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_restore.py inspect --archive /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/decrypted-retention.PRIVATE.tar --sha256 9e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613 --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 --summary /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/public-delivery/encryption-summary.json

# restore — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_restore.py restore --archive /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/decrypted-retention.PRIVATE.tar --sha256 9e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613 --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 --summary /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/public-delivery/encryption-summary.json --output-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/restored

# inspect-wrong-digest — exit 1
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_restore.py inspect --archive /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/decrypted-retention.PRIVATE.tar --sha256 0e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613 --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 --summary /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/public-delivery/encryption-summary.json

# restore-wrong-revision — exit 1
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_restore.py restore --archive /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/decrypted-retention.PRIVATE.tar --sha256 9e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613 --expected-revision 0000000000000000000000000000000000000000 --summary /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/public-delivery/encryption-summary.json --output-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/wrong-revision-must-not-exist

# restore-existing-output — exit 1
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_restore.py restore --archive /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/decrypted-retention.PRIVATE.tar --sha256 9e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613 --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 --summary /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/public-delivery/encryption-summary.json --output-dir /tmp/ai-gpu-ae456f837c05/roundtrip-agent14/reviewer-private/restored
```

The production encryption helper itself launched the verified absolute age binary with `--encrypt --recipient <EPHEMERAL_PUBLIC_RECIPIENT>` and streamed its deterministic tar over stdin; no plaintext tar existed on disk until the separate decrypt command.

## SHA-256 identities

| Tool | SHA-256 |
| --- | --- |
| `age` | `eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c` |
| `age-keygen` | `0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899` |
| `age-v1.3.2-linux-amd64.tar.gz` | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` |

| Production source | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_pack.py` | `b67c66bace419f08fa57ae244e81af21477f634d2d9d3be853393ea8f287fd6f` |
| `ci/project/p06_qualified_warm_encrypt.py` | `015ef01b1418ef5ef5328859c905854c928ab7c996aba9352603383ef648ca24` |
| `ci/project/p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |
| `ci/project/p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |

| Read contract | SHA-256 |
| --- | --- |
| `AGENTS.md` | `2173e534f2f4b757508ccc335e1e271e778e86e11fbccc53d5ea39f90d4cd309` |
| `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |
| `docs/designs/qualified_warm_retention_review_v1.md` | `364038856334f0c4c8cf7d7a27fea4d81682a11bbcafee98f6a0a1099e794f01` |
| `docs/project/p06-hosted-warm-guide.md` | `03de73f6d4dd6c5c5c25d350f21c35bc1534d9f71214988703b7cc84c100c47c` |

- Python executable SHA-256: `fa67443527ed9647f760d807e2a38f26340757123e643c4639cf273ed15d5ea7`.
- One-shot driver SHA-256: `6e3b256499a6b4ec86bbd4d284e10ea712e4c03356342dfd9bf712b5df8fd468` (owned local reproduction script, not a new production tool).
- `agent-14-source-hashes.json`: 89 imported repository Python source identities, SHA-256 `32607c834c597529fa27b96136e9b3d2f44a577626c23bbca566f1a75e9a307a`.
- `agent-14-validation.json`: compact sanitized outcomes and identity data, SHA-256 `7b2a0a446cdf10e736c01b676f41ed257426f7994b90063ff7240a1049edef42`.
- Full sanitized detail retained locally at `roundtrip-agent14/validation-detail.json`, SHA-256 `d4a118e2132efd7907beb3fbadec23f201c1be8ecee4292c2c7676e48a38f5e8`; child stdout/stderr remains beneath the private owned validation directory. Root should publish only the sanitized report/JSON/source manifest, not that directory or the synthetic plaintext packet.

## Limitations and next action

This validates a small synthetic partial packet with the real age implementation and the tested host filesystem. It is not a cryptographic implementation audit, producer authentication, provider upload/download evidence, complete native replay, full strict governance, performance result or phase acceptance. The optional summary check alone does not verify ciphertext; the independent pre-decrypt hash/size checks and real decryption are separate observed steps here. Repeated identity checks do not exclude hostile concurrent writers or establish crash-atomic recovery. The randomly generated key and age ciphertext vary on rerun; this report records the actual observed artifact identities.

Root should include these sanitized observations in the operational evidence packet and bind any final integrated qualification to the final frozen source. The fresh qualified warm native experiment remains unstarted and P06-A02/A03 remain open. No production correction is proposed from this passing integration.
