# Agent 25 — real ciphertext negative controls

## Result and scope

**Pass: 40/40 fresh probe assertions**, plus five independent post-run checks. Pinned real `age` and `age-keygen` v1.3.2 executed locally under CPython 3.12.14. The actual current encryption CLI created a retention archive from four synthetic files (180,215 payload bytes), three directories including the root, an empty file/directory and a non-ASCII filename. No mocks, production edits or new production helper/tests. The pack file was source-pinned but its packaging API was not executed.

Valid output: 194,792 ciphertext bytes and 194,560 decrypted plaintext bytes. Producer summary size/hash/counts matched; private decryption and strict inspect both exited 0. An independent standard-library tar read confirmed exact inventory and payload hashes without extracting or executing content.

## Layer-specific observations

| Control | Real age result | Plaintext result | Strict inspection |
| --- | --- | --- | --- |
| Unmodified producer output, correct private identity | Exit 0 | Complete 194,560-byte tar | Exit 0; retention verified |
| Independent wrong private identity | Exit 1: no identity matched | No plaintext file created | Not run; no plaintext file |
| Remove 37 ciphertext tail bytes | Exit 1: payload authentication failed | 131,072-byte partial file remains | Exit 1; retention rejected |
| Flip one payload bit at ciphertext offset 194,759 | Exit 1: payload authentication failed | 131,072-byte partial file remains | Exit 1; retention rejected |
| Append 20 ciphertext bytes | Exit 1: payload authentication failed | 131,072-byte partial file remains | Exit 1; retention rejected |
| Append one all-zero 10,240-byte plaintext tar record, then legitimately encrypt | Exit 0 | Exact malformed plaintext roundtrip | Exit 1; API `archive-format`, even with its matching digest and no summary |

The three ciphertext mutations also fail comparison against the unchanged public summary. Their private partial plaintext was inspected only as an explicit rejection control after age failed; it was not treated as usable output. The final row establishes a separate structural boundary: cryptographic success alone does not establish retention format validity.

## Preservation and commands

All original synthetic inputs, original ciphertext/summary and valid plaintext are retained byte-for-byte. Every owned directory was 0700 and file 0600 under umask 077. Both disposable private identities were deleted in a finally block; no private-key bytes appear in reports or remaining owned artifacts. Deletion does not claim secure erasure.

Run from `/tmp/ai-gpu-ae456f837c05/cipher-agent25`:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/cipher-agent25/probe.py
```

Exit 0. Exact subprocess argv, cwd, versions, return codes, diagnostics, source/tool hashes, ciphertext/plaintext identities and sanitized CLI reports are retained in `notes/agent-25.json`. The child environment removed `PYTHONPATH`; both CLIs ran from outside the checkout. Revision `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` is an explicitly synthetic caller-selected label. HEAD was `622662ad9cece6da4e3375be7e977dbe04cde862` with the concurrent repaired candidate uncommitted.

## Exact tested identities

All four source and all three pinned tool hashes matched before and after execution.

| Source | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_encrypt.py` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `ci/project/p06_qualified_warm_pack.py` | `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a` |
| `ci/project/p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |
| `ci/project/p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |

| Tool | SHA-256 |
| --- | --- |
| `age` | `eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c` |
| `age-keygen` | `0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899` |
| `release` | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` |

Probe SHA-256: `4499ca2f078f0c1402a88eb0f25dfdde23cd072e1e8b1798a22b94f7131a0b52`.
Compact JSON SHA-256: `01dbc7c6e9462c4432cd4de929cf3f5e38d5682cec0ba763db22a6080951978a`.

## Limits and next action

No genuine private/user/vendor/control-original data, native GPU execution, network/GitHub action, restore operation, provider delivery or strict governance qualification occurred. Every inspect report retains native execution as not run and false retained-code execution, origin authentication and native/performance/phase acceptance. These controls do not accept P06-A02/A03 or establish producer origin.

No defect requiring another production change was found. Root should retain this source-bound negative-control evidence with the repaired candidate, complete its independent reviews/full strict gate, and preserve the operator requirement to check age exit status before trusting any emitted plaintext.
