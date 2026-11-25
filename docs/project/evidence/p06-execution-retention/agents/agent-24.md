# Agent 24 — hosted public-output/privacy audit

## Result and ownership

No new privacy F2 reproduced. Read-only review and focused validation; no production or test edits, no commits. Reviewed `AGENTS.md`, the continuation brief, `docs/designs/qualified_warm_automation_v1.md`, the operator boundary, actual workflow, and current control/hosted/pack/encrypt implementation. Base HEAD was `622662ad9cece6da4e3375be7e977dbe04cde862`; operational files already contained concurrent work. Scope is the exact hashes below, which remained unchanged across my test runs. Any subsequent Agent23 directory-cleanup change needs its own validation.

## Exact boundary evidence

- `.github/workflows/p06-qualified-warm.yml` supplies the control URL through the named secret/environment channel, uses no shell tracing, redirects preflight/entry stderr to private runner files, and uploads exactly `public/qualified-warm-retention.tar.age` plus `public/encryption-summary.json`. There is no directory/glob upload. The upload requires `steps.hosted.outputs.encrypted_retention_ready == 'true'`; cancellation can upload a previously validated pair only if the `always()` upload step is reached.
- `hosted._execute` removes the URL and GitHub token from the process environment, creates a new allowlisted environment for each child, and forwards the URL only to the control-intake child. Recorded argv contain no URL. `baseline_process.run_bounded` pipes combined child output into exclusive mode-0600 private logs without echoing it. `hosted._public` emits only contract ID, validated revision, fixed stage and outcome.
- `control.acquire_control` consumes the named environment value; transport/error/finalization paths use allowlisted reason codes and fixed messages. It retains raw/partial original bytes privately without extracting them. The HTTPS path disables debug output, does not follow redirects or use proxy overrides, and constructs its TLS context without ambient session-key logging. New closeout repairs retain sanitized failure receipts instead of exception text.
- Packaging retains vendor-containing originals, hidden/opaque files, raw logs and failure receipts as PRIVATE evidence. Hosted packaging selects hosted/control/originals/acquisition evidence; encryption consumes the `retention/` tree, including partial packaging and the pre-encryption closeout record. Private runner inputs and post-encryption diagnostics are not public upload paths. Failure receipts use exception class names, not exception messages; private packaging contents remain inside encrypted retention.
- Encryption accepts a validated public X25519 recipient, never a decryption identity. The child receives only `SAFE_ENV`. Tar plaintext streams to trusted age stdin; stderr/incomplete output stay under the sibling `public.PRIVATE`. Public summaries have exactly ten fixed fields: schema/contract/revision, outcome/encryption status, file/directory/input-byte counts, ciphertext bytes and digest. No source names, URLs, recipient, key bytes or log text are included.
- Hosted delivery additionally requires successful encryption exit and cleanup, exact summary fields/types/counts, matching ciphertext size/hash, matching terminal JSON, and exactly the two expected public entries. Private extra files, symlinks and mismatched summaries fail validation. A failed invocation with a surviving pass-shaped local pair does not set readiness. Unresolved writers block packaging/encryption; successful encrypted retention of a failed/partial attempt does not make native work pass.

## Validation

From the source root, with `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, `PYTHONPATH=ci/project`, and `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B -m unittest -v`:

1. `test_p06_qualified_warm_control test_p06_qualified_warm_hosted test_p06_qualified_warm_encrypt test_p06_encrypt_operational_failures test_p06_encrypt_publication_review test_p06_operational_cancellation` — **127 tests, 10.598 s, OK, zero skips**. Log: `notes/agent-24-tests.log`.
2. `test_p06_control_closeout_review test_p06_control_finalization test_p06_hosted_operational_failures` — **18 tests, 3.075 s, OK, zero skips**. Log: `notes/agent-24-closeout-tests.log`.

These exercise inert secret-bearing URL/error/log sentinels, private-key-shaped recipient rejection, sanitized CLI argument errors, fixed child environments, exact upload paths, publication rollback/commit interruptions, private receipt repair, and real SIGTERM with inert children. The new control finalization tests explicitly assert that signed URL and synthetic private detail strings are absent from repaired receipts. No real secret or private key was used.

## Source identities (SHA-256)

| File | Reviewed SHA-256 |
| --- | --- |
| `.github/workflows/p06-qualified-warm.yml` | `261efa4bcf9c2ca7a9bca8a25dcb03eefd70848426a4c6c61ca55b68a14a7b2e` |
| `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |
| `ci/project/p06_qualified_warm_control.py` | `a303c3dc56076bbb203376521534e465c5d97b997c9ae1b93e6375e98d298fcd` |
| `ci/project/p06_qualified_warm_hosted.py` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `ci/project/p06_qualified_warm_pack.py` | `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a` |
| `ci/project/p06_qualified_warm_encrypt.py` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `ci/project/baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `ci/project/xrt_signals.py` | `a9531608094a233e5336a35e9fa7ebd028aaa3fc6dd7d3ed0f6f4d3f83a94fb8` |

## Limits and next action

Offline development checks establish the reviewed control flow and disclosure boundary. Synthetic age fixtures are not cryptographic evidence. I did not inspect live Actions configuration/logs, download the native control original, use a decryption identity, execute real age roundtrips or native GPU work, dispatch/upload an artifact, or run full strict governance. No protection is claimed against malicious same-user writers, modified trusted executables, arbitrary secret material incorrectly placed in a public Actions variable, or provider-runner compromise. Abrupt termination may prevent cleanup and durable delivery; runner-local files are not delivered artifacts. Freeze final operational edits, retain independent review of changed hashes, and run root-owned strict qualification before an authorized hosted attempt with the actual private control and public recipient.
