# W09E final supplement — P02-A03 engineering evidence approval

## Decision

**APPROVE the completed bounded engineering evidence for P02-A03. No blocking engineering finding remains.** The actual native unit, complete paired processor matrix, sparse metadata witness, native arithmetic/assertion binding, provenance checks and frozen model-parity comparisons jointly satisfy the stated gate within the configuration and coverage limits below.

**Canonical closure remains pending delivery:** finish the immutable export, independently review its integrity, attach its actual artifact identities, and reconcile the acceptance record, canonical roadmap, phase, status and backlog. This review does not claim that the export is finished, A03 is already recorded as accepted, or P02 is already complete. It supplies the independent engineering approval needed to perform that reconciliation.

The canonical requirement remains unchanged: “WGMMA synchronization, metadata, multi-warp and backpressure cases preserve correctness with no unexplained model divergence.” Verification remains concurrency tests plus model-parity evidence or documented applicability limits, at `rtl_verified`. No waiver, fixture change, golden change, tolerance increase or invented human approval is used.

The interim `w09e.md` and `w09e.json` remain byte-for-byte intact. This final supplement supersedes their pending engineering disposition only after receipt of the complete actual proof and root GO.

## Exact approved evidence identities

| Evidence | Identity |
|---|---|
| Processor execution source | `4af2307e57202c1269e20f893267a5583ad3cba0` |
| Processor execution tree | `42e5d6f2c9c0c2035c4d3ec8c86125e8cca45192` |
| Finished original report | SHA-256 `b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78`; 2,952,368 bytes |
| Independent completion anchor | `formal-completion-anchor.json`; independently supplied digest matches the original report |
| Historical native unit | Source `9006939aa123452b198bc0987e34aae8fab45fdd`; tree `c815d75bcd13395618b7fbd9924bcedf6347c6c8` |
| Corrected verifier local execution | `5e3b74fd569169ad921315223c121a037ae656b7` |
| Corrected verifier publication receipt | `359a8c007f450a8146540f795cb576b29818fa03`, with identical tree `97116818da872f43f952a351eb6616fc327be438` |
| Corrected verifier source | SHA-256 `11497b57db50c4c1e690d38c406d0de94f86b2017cec036f7ed79008151e72a4` |

The unit and processor executed different, explicitly retained source revisions. The later verifier correction and publication do not rewrite either execution identity. The interim JSON used `rootformal-completion-anchor.json` as task-message shorthand; the actual file relied on and hash-checked here is `formal-completion-anchor.json`.

## Completed proof and independent corroboration

| Scope | Actual completed result |
|---|---:|
| Processor commands | 113/113 pass, exit 0, successful start and complete process-group cleanup |
| Backend/configuration builds | 12/12 pass |
| Case/backend executions | 24 |
| Processor launches | 48 |
| Actual FP32 words compared exactly | 24,576 |
| Case-level backend pairs | 12 |
| Per-launch instruction/cycle comparisons | 24/24 pass |
| Native sparse launches | 4 |
| Complete sparse metadata transactions | 64, all with an observed real wait |
| Metadata records | 256 |
| Historical unit commands/groups | 9 passing commands / 8 groups |
| Historical unit transactions | 392 accepted and 392 committed |
| Historical unit exact arithmetic checks | 3,072 words, including intermediate feedback |

I independently rehashed all 113 raw command logs and their receipts, reparsed all 24 case logs, checked every actual and logged expected word against the frozen corpus, verified complete launch/PASS framing, recomputed cumulative counter deltas and all 24 backend comparisons, and independently joined all 64 sparse metadata transactions from their raw records. This corroboration imports no production arithmetic/witness parser and performs no compiler, simulator, GPU or test-suite execution.

The same read-only audit checked all 38 source snapshots, 740 current source identities, 45 retained source copies and 903 retained variant artifacts. It checked the corrected verifier invocation and output identities, the independent correction review and its retained artifacts, the clean 22-test receipt, and the sparse compiled-native binding. It rechecked all **1,908 consumed file identities** at the end with no change. The reproducible reader is `w09e-final-audit.py`; its complete bounded observations are in `w09e-final-proof-data.json`.

The reader initially compared two equivalent verifier-source lists in incidental list order. Direct comparison established exact path-to-identity equality; the reader now compares those inventories by path. This was an analysis-helper ordering assumption, not a failed packet, changed gate or GPU discrepancy.

## Scope of the approved configuration

The processor matrix is RV64 with one cluster/core, eight threads per warp, eight warps, issue width four and four TCU blocks. Arithmetic uses native TFR tensor and STD scalar floating point. Local memory is 16 KiB with eight banks, tensor latency is four, DSP use is off, and the declared format bank supports FP16/BF16. Every processor case uses M=64, N=8, K=16, NRC8, KUNROLL=1, initial C=+0, two four-warp CTAs, two K8 tiles, two distinct fixture patterns and two output-poisoned launches per pattern.

| Variant | Approved operand/layout scope |
|---|---|
| `dense-fp16-ss` | FP16 to FP32; shared A/B, block-major shared A |
| `dense-fp16-rs` | FP16 to FP32; register A/shared B |
| `dense-bf16-ss` | BF16 to FP32; shared A/B, block-major shared A |
| `dense-bf16-rs` | BF16 to FP32; register A/shared B |
| `dense-fp16-ss-row-major-a` | FP16 to FP32; row-major shared A |
| `sparse-fp16-ss` | Sparse FP16 to FP32; compressed row-major shared A and metadata witness |

The independent bounded integer fixture corpus targets protocol and data-layout sensitivity with exact FP32 sums. P02-A01/A02 continue to establish their accepted numerical-contract and ordinary-WMMA normal/edge/cancellation scopes. A03 does not extend qualification to arbitrary exceptional values or other rounding behavior.

## Final obligation matrix

| ID | Obligation | Disposition | Evidence and boundary |
|---|---|---|---|
| A03-01 | Entry and P02 prerequisites | `satisfied` | P00 complete; P01-A01/A02 staged entry and P02-A01/A02 accepted. All 159 referenced prerequisite artifact hashes match; separate P01-A03 blocked record remains intact. |
| A03-02 | Frozen arithmetic, geometry and parity contract | `satisfied` | Frozen six-variant RV64 matrix, independent fixture hashes, exact output comparison, exact per-launch instructions and unchanged 5% RTL-denominator cycle rule are preserved. |
| A03-03 | Historical unit applicability to frozen source | `satisfied` | 417 named bridge entries and all 436 original unit source-snapshot entries match current source; all eight checkout inputs match. Reviewed original unit identity is preserved; current bridging is not a rerun. |
| A03-04 | Descriptor and layout correctness | `satisfied_bounded_scope` | Unit descriptor reuse/replacement and poison checks pass; all dense SS/RS FP16/BF16 rows and FP16 row-major-A processor rows pass exact arithmetic with matched configuration and binaries. |
| A03-05 | Synchronization and multiple warps | `satisfied_bounded_scope` | Directed unit observes staggered overlap, CTA conflict exclusion followed by entry, stable commits and drain. Processor runs cover two four-warp CTAs; sparse raw witness confirms stable ownership in every per-warp load pair. |
| A03-06 | Directed backpressure and bounded progress | `satisfied_bounded_scope` | Native dense NRC16 RS isolated pressure observes two causal conjunctions, ten held cycles, and eight further stable cycles. Separate LMEM stalls/delays and bounded drain pass. Forced sparse compute pressure is not claimed. |
| A03-07 | Metadata transaction behavior | `satisfied_bounded_scope` | Native unit metadata tests pass eight requests, sixteen split writes and sixty-four lanes with delays, reload, exact output and proper drain. Processor dependency order is separately established below. |
| A03-08 | Matched complete processor arithmetic | `satisfied` | 113 commands and all 12 variants pass; 24 case executions, 48 launches and 24,576 exact words. This reviewer rehashed every command log and reparsed every actual/expected output against the frozen corpus. |
| A03-09 | Actual processor metadata scoreboard dependency | `satisfied` | All four native sparse launches have sixteen complete reserve/wait/release/issue transactions across eight physical warps and two stable CTA groups. All 64 transactions actually wait; assertions and passive monitors are bound into the exact executed native library. |
| A03-10 | Model parity within frozen scope | `satisfied_frozen_parity_scope` | All 24 launch pairs have exact retired-instruction equality and pass the unchanged 5% cycle rule. Maximum observed gap is 50/3686*100 = 1.3564839934888768%. Auxiliary TCU event counts retain their observed differences; no event-level equivalence is claimed. |
| A03-11 | Native arithmetic, compiler roles and assertions | `satisfied_bounded_native_scope` | All native variants select TFR tensor and STD scalar arithmetic with exactly one --assert. Sparse hierarchy has 32 native FEDP instances, four bound monitors/eight local-warp pairs, and compiled assertion diagnostics. Inherited integer/utility DPI remains; unit no-DPI evidence is separate. |
| A03-12 | Provenance, stability and retained failures | `satisfied` | 38 source snapshots, 740 source identities, 22 selected tools, three reused libraries and 137 dependency headers remain stable. All 113 commands succeed with complete cleanup and no recorded resource stop. Historical unit, environment attempts and verifier failure remain separate preserved evidence. |
| A03-13 | Corrected packet verifier and independent acceptance | `satisfied` | W09C approves the exact strict checkout-input fix; clean 22 focused tests pass. The official corrected CLI with --require-witness and external report SHA-256 exits 0, checks 1,103 packet files, and reports packet_valid=true. Its independent_review_required state is addressed by this engineering assessment. |
| A03-14 | Immutable publication and state reconciliation | `pending_canonical_delivery` | Engineering evidence is approved. Canonical closure still requires finalized immutable export/index, independent publication-integrity review, accurate acceptance artifact hashes, and reconciled roadmap/phase/status/backlog. This review does not claim that export or closure has occurred. |

## Historical native unit applicability and pressure

The four unit publication artifact hashes and all 498 published member hashes/sizes match. Both retained original arithmetic/protocol reviews are passing without findings. All 417 named bridge files—414 RTL and three harness files—match original unit source-snapshot identities and current frozen bytes. All 436 original unit source entries and all eight generic checkout inputs also remain unchanged, including the configuration generation inputs. The original Git object is unavailable locally; the independently checked retained-snapshot bridge and original reviewers' commit checks establish historical applicability. This is not a claim of a fresh unit run.

The original unit supplies the directed evidence that passing processor arithmetic alone cannot: descriptor reuse/replacement and poisoned unused descriptors, staggered multiwarp overlap, conflicting-CTA exclusion followed by entry, delayed and split metadata, local-memory stalls/delayed responses, stable blocked commits, exactly-once accounting and bounded drain. The raw log reconciles all eight groups and all 392 transactions.

The isolated dense **NRC16 RS** pressure group records two observations of the complete same-slot conjunction: a blocked pending compute result, blocked execute and dispatch, ready tensor operands, admission blockage and no CTA conflict. It has ten held cycles and eight additional stable cycles. Those eight tail cycles do not each prove the full conjunction. Forced sparse-compute pressure is explicitly unclaimed. The processor matrix uses NRC8; the unit pressure result is a separate bounded protocol proof on the unchanged common compute path.

## Processor metadata obligation is closed

The final W07F review, its independent raw correlator and native binding pass. My separate raw join confirms all four native sparse launches, each with sixteen completed transactions across eight physical warps, four issue instances with both local-warps, two loads per physical warp and two stable four-warp CTA groups. **All 64 transactions actually wait**, exceeding the frozen requirement of at least one real wait in each launch.

The event identity combines launch framing, instance, local warp, reset epoch and sequence, with matching load/dependent PCs, physical warp, CTA and UUID. All observed UUID values are zero; UUID alone is not used as identity. Every chain has reservation, a real wait before release, matching release and eventual issue. The same logs pass complete exact arithmetic. CTA IDs change between launches but remain stable within each warp's load pair.

The 2,748 summed warp-wait cycles are a sum over potentially concurrent warps, not elapsed processor stall time. No same-cycle release/issue was observed; legal zero-gap handling is not misreported as runtime coverage. Actual ELF bytes show the metadata load at `0x18000017c` and dependent sparse WGMMA at `0x180000180`. The raw witness uses those PCs, providing observed scheduling evidence beyond binary adjacency.

The generated sparse hierarchy contains four bound scoreboard monitors/eight issue-local-warp pairs and 32 native FEDP instances across four TCU blocks. The native runtime log and compiler stamp contain exactly one `--assert`; monitor diagnostics occur in generated C++ and in the exact executed library. Runtime assertions are explicitly reenabled after reset. The checked native library hash is `bdc184db89509e581b465efbe9ad7ca5fe1f9cfea34c95e4d89174c60ec98472` and its size is 16,367,312 bytes.

Native TFR tensor and STD scalar floating-point arithmetic are established. Integer multiply/divide and utility DPI imports remain in processor RTL. The historical unit's no-DPI claim stays separate; this review does not call the whole processor DPI-free.

## Frozen model-parity obligation is closed

Every one of the 24 launch pairs has exact retired-instruction equality. After subtracting consecutive cumulative samples, every pair satisfies:

`abs(SimX_cycles - RTL_cycles) * 100 <= RTL_cycles * 5`

The largest observed difference is **50 cycles / 3,686 RTL cycles = 1.3564839934888768%**, on the second sparse launch of either pattern. This is below the unchanged 5% bound. No averaging, denominator change, tolerance increase or timing-applicability waiver is used.

Auxiliary TCU counts retain their observed differences. RS examples have 119 RTL cache hits versus 118 SimX hits, and some stall/read deltas also differ. Those fields were not frozen equality predicates, and their causes are not claimed as established. Acceptance therefore establishes no unexplained deviation from the **frozen numerical, concurrency, retired-instruction and cycle expectations**. It does not establish event-by-event timing-model identity. This scope follows the predeclared comparison contract and introduces neither a new metric nor a waiver.

## Verifier correction and completed provenance

W09A preserved the old verifier's concrete eight-checkout/seven-execution-input mismatch and its original partial-report failure. W09C independently approved the correction: require the exact eight trusted checkout paths, allow only unused `ci/blackbox.sh` to remain outside the execution inventory, compare every overlap strictly, and leave all eleven mandatory consumer-source requirements, retained-copy guards and source-stability guards intact. The original packet and running source were not edited to make it verify.

The clean corrected source passed all 22 focused packet/adversarial tests. The official full-packet command used `--require-witness` and the externally pinned final report digest, exited zero with empty stderr, checked **1,103 packet files**, and returned `packet_valid=true`. Arithmetic, witness and parity outcomes all passed. Its `qualification_status=independent_review_required` correctly reserved the engineering acceptance judgment now supplied by this review. It did not autonomously close a gate.

W08E's completed independent audit confirms all 113 command outcomes, 38 equal source snapshots, 22 stable selected tools, three stable reused dependency libraries and 137 stable external headers. No resource stop or unsuccessful cleanup was recorded. All twelve build trees remain present and all six native builds have assertions enabled and waveforms disabled. The 6 GiB sampled RSS and 15 GiB disk reserve remain polled budgets; the measured maximum RSS is 3,140,571,136 bytes and the run timestamp interval is 46 minutes 50 seconds. These are host observations, not physical-device performance or hard resource quotas.

## Required canonical closure and handoff

1. Finish the immutable evidence export with unchanged selection/size limits, preserved original hashes and separately identified normalized published bytes. Retain explicit omitted-body limitations and all historical failed/blocked attempts.
2. Obtain the separate independent publication-integrity review of the finalized components/index and both original-plus-published and published-only verification. Populate the acceptance record with the actual finalized artifact hashes, this approval and the exact historical/execution/verifier identities.
3. Reconcile A03 and P02 status only while all prerequisites, records and final export remain valid. No original runner acceptance flag needs to be rewritten; its completed evidence remains independent of the later decision.
4. Keep P01/P01-A03 blocked on the unchanged vendor integration requirement. Preserve the distinct full-AFU, vendor `hw_emu`, physical FPGA, synthesis/PPA and silicon boundaries.
5. P03 remains `not_started` unless separately beginning its next bounded native operator contract/manifest/ABI task. The P02 handoff establishes the supported configuration and numerical/protocol evidence; it does not invent P03 operator launches or acceptance.

There is no remaining engineering request for changes to the reviewed A03 proof. The final export and canonical reconciliation remain concrete delivery conditions. No physical/vendor/AFU/synthesis qualification, forced sparse pressure, arbitrary-format/geometry qualification, universal IEEE claim, waiver or human approval is inferred.

## Review artifacts

- `w09e-final.json`: machine-readable approval, final obligation matrix, exact scope, closure conditions and critical artifact identities.
- `w09e-final-proof-data.json`: independent raw-log/counter/witness and hash-binding corroboration.
- `w09e-final-audit.py`: standard-library-only read-only audit used for that corroboration.
- `w09e.md` and `w09e.json`: preserved original interim review.

Only review artifacts were written. This acceptance reviewer ran no compiler, GPU workload, test suite or subagent.
