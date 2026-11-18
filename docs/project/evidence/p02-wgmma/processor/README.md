# P02-A03: bounded WGMMA processor qualification

The [acceptance record](acceptance.json) accepts **P02-A03** for the declared
processor and directed-unit scope. Together with the existing P02-A01 numerical
contract and P02-A02 ordinary WMMA acceptance, this completes **P02**. The
[canonical roadmap](../../../roadmap.json) records phase state. P01-A03 vendor
`hw_emu` remains blocked; P03 remains `not_started`, with P03-T01's bounded
ordinary FP16/BF16 operator contract as the next development task.

## Results and source identities

The clean, stable processor execution used commit
`4af2307e57202c1269e20f893267a5583ad3cba0`, tree
`42e5d6f2c9c0c2035c4d3ec8c86125e8cca45192`. Its original report is
`wgmma-gcc12-formal-evidence/report.json`, 2,952,368 bytes, SHA-256
`b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78`.
[summary.json](summary.json) contains the configuration, complete paired timing
records, witness totals, resource observations and applicability limits.

| Check | Observed result |
|---|---|
| Processor execution | 113 successful commands; 12 backend/configuration builds; 24 case executions |
| Arithmetic | 48 launches; 24,576 exact FP32 output-word comparisons; all pass |
| Metadata ordering | 256 raw events; 64 complete reserve/wait/release/issue transactions across four native launches; every transaction actually waited |
| Frozen model parity | 24 launch comparisons with exact retired instructions and cycle difference at most 1.356484%, within the unchanged 5% RTL-denominator bound |
| Historical native unit | Nine commands, eight groups, 392 accepted/committed transactions and 3,072 exact arithmetic checks; separate unchanged-source bridge |
| Corrected offline packet verifier | Complete original packet accepted as internally consistent; 1,103 files verified with an independently supplied report digest |
| Corrected tooling regression | 22 focused tests at clean local `5e3b74f`; 1,624 hosted tests at equivalent published `359a8c0`, zero failures/errors/skips |
| Execution-source general CI | All 42 jobs passed at `4af2307`; later CI snapshots are recorded separately by source |

The six configurations are dense FP16 SS, dense FP16 RS, dense BF16 SS, dense
BF16 RS, FP16 SS with row-major A, and sparse FP16 SS. They use RV64, one core,
eight threads per warp, eight warps, four issue slots and TCU blocks, native
TFR tensor and STD scalar floating-point arithmetic, 16 KiB/eight-bank LMEM,
latency four, and DSP off. Each runs M64/N8/K16, NRC8/KUNROLL1, initial C=+0,
two four-warp CTAs, two independent signature patterns and two launches.

| Variant | Exact instructions per launch | SimX cycles, launches 0 / 1 | RTL cycles, launches 0 / 1 |
|---|---:|---:|---:|
| FP16 SS | 5,584 | 6,840 / 6,833 | 6,836 / 6,798 |
| FP16 RS | 5,688 | 7,028 / 7,017 | 7,028 / 6,949 |
| BF16 SS | 5,584 | 6,840 / 6,833 | 6,836 / 6,798 |
| BF16 RS | 5,688 | 7,028 / 7,017 | 7,028 / 6,949 |
| FP16 row-major A | 4,072 | 5,494 / 5,477 | 5,455 / 5,424 |
| Sparse FP16 SS | 2,544 | 3,744 / 3,736 | 3,720 / 3,686 |

Both signature patterns produce these per-launch counts. Comparisons use
differences between cumulative process counters. Auxiliary TCU event counters
retain their observed differences; they are not frozen equality predicates,
and no event-level equivalence or parity waiver is claimed.

Each sparse launch contains 16 completed metadata transactions across all eight
physical warps. The two launches per case sum 723 and 651 warp-wait cycles;
overlapping waits mean these sums are not elapsed stall time. Same-cycle
release/issue was permitted by the contract but was not observed. Native
hierarchy, enabled assertions, exact executed library, and actual compiled
metadata-load/WGMMA adjacency are independently bound in the retained reviews.

## Review and acceptance

- [W09E final engineering review](reviews/w09e-final.md) approves the bounded
  evidence after independent arithmetic, source, unit-bridge, native-witness,
  parity and verifier checks. Its machine record is
  [w09e-final.json](reviews/w09e-final.json).
- [W10B publication review](reviews/w10b.md) independently checks original and
  published bytes, normalization, caps, desired-member coverage, formal text,
  command logs, binary omissions and historical failure preservation.
- [W10D corrected-source CI review](reviews/w10d.md) binds the actual
  [1,624-test log](reviews/w10d-governance.log) to the corrected verifier tree.
- [Continuation closure review](reviews/closure-review.md) independently rechecks
  the execution, final review mapping and reconciled phase records. The earlier
  W10C audit is retained with its mapping failures; no missing approval is inferred.
- [W10F consumer review](reviews/w10f.md) and its [final data](reviews/w10f-final-data.json)
  retain the successful published-only verification and final documentation observation.
- [agent-execution.json](agent-execution.json) reconciles the 60 historical assignments from the prior continuation. The
  unfinished original closure approval and interim coordination record remain
  explicit; current reviewers finish the remaining work. Agent counts are
  separate from technical proof and do not assert human or maintainer approval.

[review-inventory.json](review-inventory.json) maps original review identities
to archive members or standalone published files. Earlier reviews, including
blocking findings and interim observations, remain unchanged. Later supplements
record their resolution without overwriting the original result. The
[mapping recovery](mapping-recovery.json) preserves the earlier map and W10F
standalone while binding the final review and the exporter’s shared-parent
normalization role. All four compressed archives remain byte-for-byte unchanged.

## Publication layout

[publication.json](publication.json) binds the delivery components and their
scopes. Each archive stays below the existing **4 MiB compressed** cap, with
the existing 96 MiB expanded-JSON, 64 MiB original/published-text, 16 MiB member,
4,096-member and 256-selector limits unchanged.

| Component | Members | Gzip bytes | Contents |
|---|---:|---:|---|
| [processor-core](processor-core/component-index.json) | 349 | 2,758,791 | Completed report, all command logs, original source/snapshots, W01–W08 reviews, corrected verifier and final original-packet verification receipts |
| [processor-artifacts](processor-artifacts/component-index.json) | 869 | 1,547,002 | Complete selected generated text artifacts from every backend/configuration build |
| [processor-historical-verifier](processor-historical-verifier/component-index.json) | 22 | 374,643 | Original verifier rejection, reproducer, failing regression, historical code and captured running report |
| [compiler-recovery-v2](compiler-recovery-v2/component-index.json) | 133 | 425,678 | Original GCC14 failure, Clang probe, official GCC12 package metadata and recovery receipts |

The first three components jointly contain 1,238 unique members: all 1,236
desired members and two additional component selections. The formal directory's
1,103 files are accounted for by 1,066 text members at original packet names,
one exact `.gitmodules` body mapped through a `.txt` copy, and 36 omitted binary
bodies with original hash/size identities. All 113 command logs are present.
The [union coverage record](processor-union-coverage.json) lists exact mappings;
the [component index](processor-component-index.json) preserves packaging
decisions and receipts. The historical native unit remains in its original
[separate component](../unit/README.md).

Original and published identities have different purposes. Embedded historical
hashes identify original bytes. Archive inventories also hash the published
UTF-8 bodies after literal `${SOURCE}`, `${WORK}` and `${TOOLS}` substitutions.
No original digest is rewritten to describe normalized bytes. Omitting binary
bodies from this text publication does not recreate them or permit binary
replay. Tool archives, complete build trees and system dependency bodies are
not embedded.

## Verify the retained evidence

For these normalized publication components, run the retained, unchanged
exporter from the repository root:

```sh
python3 docs/project/evidence/p02-wgmma/processor/tools/package_wgmma_evidence.py verify --published-only --output docs/project/evidence/p02-wgmma/processor/processor-core
python3 docs/project/evidence/p02-wgmma/processor/tools/package_wgmma_evidence.py verify --published-only --output docs/project/evidence/p02-wgmma/processor/processor-artifacts
python3 docs/project/evidence/p02-wgmma/processor/tools/package_wgmma_evidence.py verify --published-only --output docs/project/evidence/p02-wgmma/processor/processor-historical-verifier
python3 docs/project/evidence/p02-wgmma/processor/tools/package_wgmma_evidence.py verify --published-only --output docs/project/evidence/p02-wgmma/processor/compiler-recovery-v2
```

The new `ci/project/p02_wgmma_packet.py` instead validates a complete original
runner packet at its retained locations, including available source/build
bodies. The independently reviewed invocation used:

```sh
python3 -B ci/project/p02_wgmma_packet.py /path/to/wgmma-gcc12-formal-evidence --require-witness --report-sha256 b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78
```

The exact invocation, environment, source identities and result are in
[w09a-final-command.json](reviews/w09a-final-command.json) and
[w09a-final-output.json](reviews/w09a-final-output.json), also copied into the
core component. The CLI does not execute copied packet code or turn a valid
packet into acceptance automatically. Failed qualification can be valid
evidence. Without an external trusted report digest, it establishes internal
consistency only; it is not origin authentication. Its supported input is not
a relocated or normalized publication archive.

## Applicability and resource limits

The historical no-DPI native unit ran at
`9006939aa123452b198bc0987e34aae8fab45fdd`. The 417-path named bridge and all
original unit source identities remain unchanged. This is applicability of
existing evidence, not a new unit run. Forced compute pressure is dense NRC16
RS; no forced sparse-compute-pressure result is claimed. The subsequent eight
stable pending-commit cycles do not each repeat the complete causal blocked
conjunction.

The processor corpus uses independently generated bounded integer inputs and
exact outputs. It does not extend general rounding/exceptional-value coverage,
format support, matrix shapes, tails, arbitrary initial C, scaled formats or
long reductions beyond the separately accepted numerical contracts. Native
processor TFR/STD floating-point arithmetic still uses inherited integer and
utility DPI helpers. No AFU/vendor integration, physical FPGA, synthesis/PPA,
silicon or framework qualification follows.

The first formal attempt failed under GCC14's unchanged warning-as-error
policy; Clang also failed in inherited formatting headers. A task-local
GCC12.2 toolchain from six official Debian packages succeeded without warning
suppression or source changes. Package hashes are bound through retained
official metadata; the InRelease GPG signature was not verified. The failure
and recovery records retain these distinctions.

The formal run used two compiler workers, a 6 GiB sampled process-RSS budget,
a 15 GiB free-disk reserve, and no waveforms. Peak sampled process-group RSS
was 2.925 GiB. Minimum recorded free disk was 51.634 GiB, leaving 36.634 GiB
above the reserve. These are sampled observations and enforced polling budgets,
not hard quotas or physical-device measurements. All 113 commands completed
with cleanup and no resource stop. All 12 successful build trees remained
available for independent inspection.
