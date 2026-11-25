# Agent 41 — final frozen-source real-age partial-retention roundtrip

## Verdict and source scope

**PASS for one synthetic retention integration on the final frozen operational source.**
The actual production partial-packaging, encryption, strict inspection and
restoration CLIs ran with real age/age-keygen **1.3.2**. All **nine subprocess
invocations exited 0**. No production edit, repository write, monkeypatch,
fake cipher, native GPU process, network request, upload, commit or child agent
was used. The negative ciphertext controls already covered by Agent 25 were
not repeated.

The run verifies the successful retention path after the final packaging setup
lifetime correction reviewed by Agents 28/30. Agent 14's earlier positive run
used an older pack and encryption source. This new observation binds to
`validation/operational-source-freeze.json`, SHA-256
`714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb`. All **22 frozen entries** matched
hash, size and mode before execution; hashes and modes plus the exact freeze
bytes were checked again afterward. All **89 repository Python source files**
imported by the driver's helper closure were hashed before and after and
remained unchanged.

The checkout was based on `622662ad9cece6da4e3375be7e977dbe04cde862` with the final
uncommitted operational candidate. That 40-hex base is the explicitly chosen
**synthetic manifest selector**, not a claim that the changed helpers are the
clean base. The freeze and per-file hashes identify the tested source.

## Observed results

- Packaging created a **seven-member partial ZIP** containing only synthetic
  stopped-attempt evidence: failed prelaunch receipt, malformed preparation
  JSON, binary and hidden bytes, an empty file, an inert Python sentinel, and
  an explicitly selected acquisition log. The exact member inventory, member
  order and each member's bytes matched the controlled input. No native
  subtree or complete replay original was fabricated.
- The hosted-shaped encryption selection retained **8 files, 3 directories
  including its root, and 8,690 input bytes**. It included the packet and its
  receipt, synthetic closeout/log data, another inert sentinel, hidden and
  binary files, an empty file and an empty directory. A failed closeout and
  malformed inner JSON remained unchanged and opaque.
- Public output contained exactly `qualified-warm-retention.tar.age` and
  `encryption-summary.json`; the summary had exactly the ten contract keys.
  Actual ciphertext length and SHA-256 matched the summary **before** private
  decryption. No synthetic plaintext or private-key marker appeared in those
  two output files.
- Real age decryption exited 0. Strict inspection and restoration each exited
  0 with `retention_verified=true` and `summary_checked=true`; restoration also
  reported `restoration_completed=true`. Every restored file was compared
  byte-for-byte with its encryption input, and the complete restored inventory
  matched exactly. Exact manifest bytes, partial ZIP bytes and receipt bytes
  matched. No incomplete marker remained after successful restoration.
- Source/workspace/acquisition fixtures and the encryption input retained their
  exact bytes and device/inode/mode/link/size/mtime/ctime stamps; atime was
  deliberately excluded. Plaintext tar, ciphertext and tools were unchanged
  after review. All directories in the owned run tree were **0700**, all
  regular files **0600**, including both original and restored sentinels.
- The sentinel's unique execution marker remained absent. Inner ZIPs were only
  read for byte/inventory checks, never extracted; retained code was never run.
  `partial_attempt=true`, `complete_replay_original_created=false`, all
  historical qualification flags false, `native_execution="not_run"`,
  `retained_code_executed=false`, `origin_authenticated=false`, and native,
  performance and phase acceptance false remained preserved.
- The ephemeral private identity was created at **0600**, its contents were
  never printed or copied into reports, and it was unlinked in `finally`
  immediately after the decryption attempt. Its absence was rechecked.
  This is deletion evidence, not a secure-erasure claim.

## Observed artifact identities

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Original and restored inner partial ZIP | 1954 | `7249da4d1bdaae8e60261950132056e152517b21555d1c61f53ab1905bcc00c2` |
| Decrypted producer tar | 20480 | `2b20f675a52c1032120b777a9b2ebfb76c5ee1a8c81c9034252c2a546334337b` |
| Actual age ciphertext | 20680 | `953de766a3b802494dd9d92ba1cf9f09e33e0198a877eaa19c20fff70ecdbb27` |

## Reproduction and sanitized commands

The owned run directory was
`/tmp/ai-gpu-ae456f837c05/final-roundtrip-agent41`, created fresh at mode 0700
under umask 077. A one-shot driver adapted from Agent 14 created only synthetic
inputs, made assertions, and invoked the real CLIs. Its SHA-256 is
`8032a84cf0a1ac36fcb2c4beec1ffdd21e01fa709e3df3d85084f8e2212e4507`. Working directory for every child was
`/tmp/ai-gpu-ae456f837c05/AI-GPU`.

```sh
umask 077
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/final-roundtrip-agent41/validate_roundtrip.py
```

Child environment: `PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`,
`PYTHONDONTWRITEBYTECODE=1`, and
`TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`. CPython was
**3.12.14**, executable SHA-256
`fa67443527ed9647f760d807e2a38f26340757123e643c4639cf273ed15d5ea7`. The driver set `sys.dont_write_bytecode`
and supplied `-B` to Python children.

The following records are the actual argv renderings after redaction.
`<SYNTHETIC_ROOT>` denotes the owned directory above;
`<EPHEMERAL_PUBLIC_RECIPIENT>` replaces the derived public recipient.
No private-key value or private payload is included.

```sh
# age-version — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age --version

# age-keygen-version — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age-keygen --version

# package-partial — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_pack.py partial --source-dir '<SYNTHETIC_ROOT>/synthetic-source' --workspace-dir '<SYNTHETIC_ROOT>/synthetic-workspace' --output-dir '<SYNTHETIC_ROOT>/selected-retention/packet' --writers-finished --extra-root 'acquisition=<SYNTHETIC_ROOT>/synthetic-acquisition'

# keygen — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age-keygen -o '<SYNTHETIC_ROOT>/reviewer-private/ephemeral-identity.PRIVATE.txt'

# recipient — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age-keygen -y '<SYNTHETIC_ROOT>/reviewer-private/ephemeral-identity.PRIVATE.txt'

# encrypt — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_encrypt.py --input-dir '<SYNTHETIC_ROOT>/selected-retention' --output-dir '<SYNTHETIC_ROOT>/public-delivery' --recipient '<EPHEMERAL_PUBLIC_RECIPIENT>' --age-binary /tmp/ai-gpu-ae456f837c05/roundtrip-tools/age --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862

# decrypt — exit 0
/tmp/ai-gpu-ae456f837c05/roundtrip-tools/age --decrypt -i '<SYNTHETIC_ROOT>/reviewer-private/ephemeral-identity.PRIVATE.txt' -o '<SYNTHETIC_ROOT>/reviewer-private/decrypted-retention.PRIVATE.tar' '<SYNTHETIC_ROOT>/public-delivery/qualified-warm-retention.tar.age'

# inspect — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_restore.py inspect --archive '<SYNTHETIC_ROOT>/reviewer-private/decrypted-retention.PRIVATE.tar' --sha256 2b20f675a52c1032120b777a9b2ebfb76c5ee1a8c81c9034252c2a546334337b --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 --summary '<SYNTHETIC_ROOT>/public-delivery/encryption-summary.json'

# restore — exit 0
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/AI-GPU/ci/project/p06_qualified_warm_restore.py restore --archive '<SYNTHETIC_ROOT>/reviewer-private/decrypted-retention.PRIVATE.tar' --sha256 2b20f675a52c1032120b777a9b2ebfb76c5ee1a8c81c9034252c2a546334337b --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 --summary '<SYNTHETIC_ROOT>/public-delivery/encryption-summary.json' --output-dir '<SYNTHETIC_ROOT>/reviewer-private/restored'
```

The production encryption CLI itself invoked the verified absolute age binary
and streamed its producer tar over standard input. No plaintext tar existed on
disk until the separate real decryption command.

## Tool and source identities

Both tool binaries were independently hashed, version-checked, and compared
byte-for-byte with their regular members in the already verified age archive.
No tool acquisition occurred during this run.

| Tool | SHA-256 |
| --- | --- |
| `age` | `eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c` |
| `age-keygen` | `0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899` |
| `age-v1.3.2-linux-amd64.tar.gz` | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` |

| Production source | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_pack.py` | `e4cff314b8a2a0dbb277baef1bc5b3eb78b10a90f777a4d3b60ff74b682dac0e` |
| `ci/project/p06_qualified_warm_encrypt.py` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `ci/project/p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |
| `ci/project/p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |

[agent-41.json](agent-41.json) retains all sanitized command exits, production
reports, 89 imported-source hashes, 22 frozen-source hashes, tool identities,
output-log hashes and assertion outcomes. JSON SHA-256:
`55fb67aebfd122580d3ef1e44834440ed5a00c76a0ddd50ed2f2c3823fe00443`. Publish only this report and that sanitized JSON; the owned
roundtrip directory contains synthetic private working artifacts and is not a
public deliverable.

## Limits and next action

This passing local synthetic integration closes the final-source positive
roundtrip coverage gap. It does not replace setup-fault regressions, the
Agent 25 negative ciphertext controls, full strict governance, provider
upload/download evidence, producer authentication, native execution, complete
native replay, performance evidence or phase acceptance. The optional summary
check does not itself verify ciphertext; independent ciphertext identity checks
and actual successful decryption were separately observed here. Repeated
stability checks do not establish crash-atomicity or exclude every concurrent
same-user writer.

Root can bind these results into the final operational evidence packet. The
fresh qualified warm experiment remains unstarted and P06-A02/A03 remain open.
No source correction is proposed from this passing run.
