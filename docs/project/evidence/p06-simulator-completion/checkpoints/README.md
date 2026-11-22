# Checkpoint archives

These archives retain original evidence bytes and their explicit source scope. The root [evidence README](../README.md) is the current result summary; this index is the extraction map. No archive is an acceptance record.

Every archive contains an internal `MANIFEST.json`, byte-identical to its adjacent sidecar. That manifest lists every original member and digest, excludes itself to avoid a recursive hash, and records intentional omissions. Archive metadata is normalized; original content is not rewritten. No retained script was executed by assembly.

| Archive | Original members | Compressed bytes | Principal original records |
|---|---:|---:|---|
| [Historical root index](development-index-db5ebb3.tar.gz) ([manifest](development-index-db5ebb3.manifest.json)) | 2 | 7,922 | `root-at-db5/README.md`, `root-at-db5/manifest.json` |
| [Initial clean host receipt](host-db5ebb3.tar.gz) ([manifest](host-db5ebb3.manifest.json)) | 8 | 840,983 | `receipt/report.json`, `receipt/focused-suite.log` |
| [Repaired-code clean host receipt](host-4781ca9.tar.gz) ([manifest](host-4781ca9.manifest.json)) | 8 | 841,857 | `receipt/report.json`, `receipt/focused-suite.log` |
| [Initial compiled-parent replay](parent-db5ebb3.tar.gz) ([manifest](parent-db5ebb3.manifest.json)) | 118 | 300,369 | `report/report.json`, `report/logs/`, `report/inputs/` |
| [Repaired-code compiled-parent replay](parent-4781ca9.tar.gz) ([manifest](parent-4781ca9.manifest.json)) | 117 | 300,455 | `report/report.json`, `report/logs/`, `report/inputs/` |
| [Recoverable CP allocation repair](cp-allocation-repair.tar.gz) ([manifest](cp-allocation-repair.manifest.json)) | 266 | 653,399 | `w08-a04-consumer-error-scope.md`; `w08-a05/REPORT.md`; `w08-a06/README.md`; `w09-a02/REPORT.md` |
| [Original pre-repair native and governance packet](native-db5ebb3.tar.gz) ([manifest](native-db5ebb3.manifest.json)) | 12 | 2,840,795 | `w09-a01-native-ci/review.md`; original ZIP, metadata and both original job logs in that directory |
| [Original existing warm-workspace execution](warm-db5ebb3.tar.gz) ([manifest](warm-db5ebb3.manifest.json)) | 13 | 5,768,856 | `w07-a06-warm-ci-review.md`; original ZIP and `replay.json` beneath `w07-a06-warm-ci/` |
| [Earlier checkpoint/provenance reviews](checkpoint-reviews.tar.gz) ([manifest](checkpoint-reviews.manifest.json)) | 33 | 92,690 | Original `w06-a01`, `w06-a03`, `w06-a04`, `w06-a06`, `w08-a01`, `w08-a02`, `w08-a03` review files; `w06-a02/` repair records |
| [Five read-only next-development audits](next-development-audits.tar.gz) ([manifest](next-development-audits.manifest.json)) | 5 | 29,400 | `w07-a01-counter-coverage.md` through `w07-a05-dsp-attribution.md` |
| [Current status and technical handoff reconciliation](documentation-reconciliation.tar.gz) ([manifest](documentation-reconciliation.manifest.json)) | 28 | 157,594 | `w09-a03/README.md`, `w09-a03/report.json`, `w09-a04/REPORT.md`, original/applied documents and patches |
| [Independent repaired host and parent review](host-4781ca9-review.tar.gz) ([manifest](host-4781ca9-review.manifest.json)) | 5 | 12,269 | `w09-a06/REPORT.md`, `w09-a06/audit-summary.json`, original audit log and manifest |
| [Fresh repaired native packet](native-4781ca9.tar.gz) ([manifest](native-4781ca9.manifest.json)) | 17 | 2,938,126 | `w10-a03-native-ci/review.md`, original ZIP, original job/API/audit records |
| [Late reviews and early originals](late-reviews-4781ca9.tar.gz) ([manifest](late-reviews-4781ca9.manifest.json)) | 65 | 678,093 | `w10-a01/`, `w10-a02/`, `w10-a04/`, `ci-management/` and seven original early report basenames |
| [Governance, ledger and closure records](closure-4781ca9.tar.gz) ([manifest](closure-4781ca9.manifest.json)) | 122 | 1,438,927 | Original current governance log/review; completed ledger/history; final documentation; preflight and CI/assembly observations |

## Source and interpretation

The repaired code checkpoint is `4781ca96db15a1d130626edc7a73411a4f6c2e7c`. Its clean host receipt and parent replay are separate from the earlier `db5ebb3a16770004423f2456ec6d0caaa0aced6d` native packet. The CP repair archive retains the later source hashes and an independent review; it does not relabel the earlier native execution.

The first native packet includes original ZIP `p06-simulator-completion-run45006726571-artifact14748468420.zip`. Its complete extracted content is inside that ZIP; extract it under `w09-a01-native-ci/packet/` to reconstruct paths in the original manifest. The original warm ZIP is retained similarly. Duplicate extracted trees are omitted without removing any ZIP member.

Parent packet archives contain the report, every declared retained candidate/parent input, configuration file and command log. Temporary build copies, tool symlinks and compiled executables are excluded. Each original receipt states its tool and binary identities and limits. The same scope distinction applies to controlled-model host fixtures, actual-framework checks and native processor execution.

The documentation archive records the first reconciliation after the clean host receipt; its original text still says repaired native verification is pending. Later documentation changes must receive their own record. The historical development root README and manifest are preserved verbatim in a separate archive.

The complete compressed-file digests and source contexts are in [index.json](index.json). The initial assembly/credential-scan receipt is [assembly.json](assembly.json). Later native results, late reviews and the completed assignment ledger are separate additions; these frozen archives must remain unchanged.

## Repaired native follow-up

The added `native-4781ca9` archive is fresh native PASS evidence for the repaired
code, executed through same-tree merge `e929c52d05bad80b28dd4085a97838d7fe2de354`.
All original bytes, including the ZIP and the independent review, are retained.
The initial 12 archives were not rebuilt. `late-reviews-4781ca9` adds the stated
frozen reviews, seven early originals and incomplete CI-management data. The
seven early reports use their original basenames at the archive root.

The closure archive below now supplies completed current governance and all 60
initial-assignment records. Earlier pending observations are preserved. Final
evidence-delta and immutable publication/readback reviews remain separate. The follow-up assembly
receipt is [assembly-native-4781ca9.json](assembly-native-4781ca9.json).

## Closure follow-up

The [closure archive](closure-4781ca9.tar.gz) adds the original repaired
governance result and independent review, completed 60-assignment ledger/history,
final documentation records and initial source/ref preflight. Every prior
archive remains unchanged. Source-time pending statements in original reports
are historical; the current result is stated in the root README and index.
No broad-CI, phase, final-publication or self-review claim is added.

The assembly receipt is [assembly-closure-4781ca9.json](assembly-closure-4781ca9.json).
