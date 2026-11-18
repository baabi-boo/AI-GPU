# W09A final supplement — Official original-packet verification

**Result: PASS.** The corrected, clean committed verifier returned **exit code 0**, `packet_valid=true`, and an external-report trust anchor for the finished original formal matrix packet. Arithmetic, metadata witness, and paired-performance outcomes all passed. This verifies the retained packet within the verifier's stated scope; independent P02-A03 acceptance remains a separate decision.

This supplement preserves `w09a.md`, the original failure, minimal reproduction, partial data, and sampled running report. Their hashes were captured before the official invocation and confirmed unchanged afterward.

## Frozen identities

| Item | Verified identity |
|---|---|
| Original executed matrix revision | `4af2307e57202c1269e20f893267a5583ad3cba0` |
| Original report state | `finished`, `pass`, formal/nondevelopment, clean and source-stable |
| Original report SHA-256 | `b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78` |
| Original report size | 2,952,368 bytes |
| Independently supplied anchor | `${WORK}/formal-completion-anchor.json` |
| Anchor file SHA-256 | `116d815fc5e52e0b3df79260c20200775e49471f9f7ffe4404f2a708f911aaa2` |
| Corrected verifier revision | `5e3b74fd569169ad921315223c121a037ae656b7` |
| Corrected verifier tree | `97116818da872f43f952a351eb6616fc327be438` |
| Verifier checkout state | Clean before and after execution; same revision and tree |
| Verifier SHA-256 | `11497b57db50c4c1e690d38c406d0de94f86b2017cec036f7ed79008151e72a4` |
| Verifier file size | 34,281 bytes |
| Associated test-source SHA-256 | `b22daed1c623ae72389da7bf9ab12c242e92ef300d7a7762e3946ec1d38271bf` |

The report digest was supplied independently by the integration owner and matched the completion anchor. This review also hashed the original report before and after execution. The corrected verifier's source revision is separate from the unchanged revision that actually produced the GPU evidence.

## Exact invocation and command result

Working directory:

```text
${WORK}/verifier-candidate
```

Exact command, shown with shell line continuations for readability:

```sh
env \
  PYTHONPATH=${WORK}/verifier-candidate/ci/project \
  PYTHONDONTWRITEBYTECODE=1 \
  /opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 -B \
  ci/project/p02_wgmma_packet.py \
  ${WORK}/wgmma-gcc12-formal-evidence \
  --require-witness \
  --report-sha256 b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78
```

The receipt records the actual argument vector, working directory, and environment overrides. The invocation ran on **2026-11-18 from 05:03:44.009837 to 05:03:46.272335 UTC**, taking **2.262 seconds**. Exit code was **0**; stderr was empty.

| Retained command artifact | SHA-256 | Bytes |
|---|---|---:|
| `w09a-final-output.json` — exact stdout | `e63e8641b7a4fd9908dcd744eb31dd873055ddff8989ce5190b649d6567536e8` | 5,386 |
| `w09a-final.stderr` — exact stderr | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 |
| `w09a-final-command.json` — receipt | `3e7d2dea1e3a383945990a30e02729e635ee46ea7b8e10da64b10dd1ac382475` | 10,845 |

`w09a-final-data.json` records the independently evaluated result assertions and embeds the parsed official output. The command receipt contains all 15 verifier/helper source identities measured both before and after execution. These independent measurements exactly matched the official output's `verifier_sources` inventory. The associated test file's hash also remained unchanged. This review did not rerun the test suite.

## Official verified result

| Field / count | Result |
|---|---:|
| `packet_valid` | `true` |
| `trust_anchor` | `external_report_sha256` |
| `full_matrix` | `true` |
| `development` | `false` |
| Recorded overall outcome | `pass` |
| Arithmetic outcome | `pass` |
| Witness outcome | `pass` |
| Paired-performance outcome | `pass` |
| Backend/configuration variants | 12 |
| Case executions | 24 |
| Launches | 48 |
| Exact output-word comparisons | 24,576 |
| Commands | 113 |
| Performance pairs | 12 |
| Required witness case executions | 2 |
| Verified packet files | 1,103 |
| Qualification status | `independent_review_required` |

The finished report's source stability, tool/dependency stability, full variant and command inventory, fixture reproduction, retained build/source bodies, compiler records, exact invocation bindings, arithmetic-log observations, witness observations, performance comparisons, and final consumed-file stability checks completed through the official entry point.

## W09A-F01 resolution

The corrected verifier requires the exact eight trusted generic checkout input paths, compares all execution-inventory overlaps strictly, and permits only explicit checkout-only `ci/blackbox.sh` to lack an execution-source identity. The seven overlapping inputs and the eleven mandatory consumer-input requirements remain enforced.

The actual original packet now verifies, with the checkout-only evidence exposed explicitly in stdout:

```json
{
  "path": "ci/blackbox.sh",
  "sha256": "c9c204b3f54a7865c3a41218d5541ea8c3c00a704ec038acd35e460e541cf621",
  "size_bytes": 9153
}
```

Thus W09A-F01 no longer blocks verification of this real packet. The earlier failure is retained as a historical result against verifier `ba12d66e14771be32dbed7a67a988b839cd41e23`; it has not been relabelled as a pass. No original source, report, evidence packet, fixture, or build was changed to obtain this result.

## Scope and remaining decisions

The verifier checks retained bodies and consistent identities. Original tool binaries, dependency bodies, omitted source bodies, and four omitted build-library bodies per variant remain identity-only evidence. The checkout-only `ci/blackbox.sh` body is not verified. Native hierarchy metadata presence is checked; semantic hierarchy and disassembly review remain independent obligations. This invocation performs no GPU execution or binary replay, and establishes no full-AFU, vendor hardware-emulation, physical FPGA, synthesis/PPA, or silicon qualification.

All asserted result fields, all independently measured source hashes, report stability, clean candidate stability, explicit checkout-only reporting, and preservation of the interim review artifacts passed. Candidate publication was pending the integration owner at the time of this invocation; this review makes no publication claim.

The official result retains **`acceptance_claimed=false`, `qualifies_P02_A03=false`, `phase_complete=false`**, and **`qualification_status=independent_review_required`**. The next integration action is to combine this consistency result with the required independent engineering evidence and acceptance decision.
