# Checkpoint 4268 independent original native-packet audit

## Verdict and scope

**PASS for the original packet's retained-data consistency, independently derived source inventory, immutable-Git source-byte mapping, and current trusted replay.** GitHub run `45034575685`, attempt 1, job `137245341329` completed successfully at published commit `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, tree `061ecbddc9b321edbd70c054c8efce4d188de04f`. The original contains seven passing checked/model cells, a separate passing public boundary control, and five passing public modes: **13 native diagnostic cells in total**.

This audit reads original execution evidence; it is **not a fresh native execution**. It builds no native code, executes no retained archive helper, extracts no archive member, and runs no full test discovery. Only the current trusted local parsers and this independent reviewer script execute. These diagnostics do not qualify measurement binaries or the complete managed warm caller. Qualification, readiness, warm execution, full warm coverage, acceptance, phase acceptance, and performance acceptance remain false. The historical warm-v1 blocker is unchanged.

The review found no unresolved evidence defect within this scope. The deliberate rejection by the fixed 676-name public replay route is an expected inventory-contract result, not a failed native execution.

## Original and source identity

The auditor obtained fresh artifact and job metadata through the purpose-built GitHub connector using the authorized account. The retained API responses independently confirm the artifact ID, native job success, producer SHA, size, digest, and success of the model execution, public execution, and upload steps. No signed download configuration or signed download URL is retained.

| Item | Exact observation |
| --- | --- |
| Workflow | [Run 45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685), attempt 1 |
| Job | `137245341329`, completed, success |
| Artifact | [14760051170](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685/artifacts/14760051170) |
| Original ZIP | `run-45034575685-attempt1.zip` |
| Original byte count | 4,290,949 |
| Original SHA-256 | `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb` |
| Original Git blob | `08777bb62b1454c66736c5d5c69b7ab8932bdcda` |
| File members | 1,046; all accounted for |
| Checked report SHA-256 | `df16b815351414e04cdf40433e9468aed60cabbb64a1b0ddefb4861590455613` |
| Public report SHA-256 | `3650a1e5dc8b21c3213820e312d16b986ddcafb0d7ca45531ba2b3e3172e0705` |

The archive was copied byte-for-byte only after its digest and size matched the API. Duplicate names, unsafe paths, special files, symlinks, encryption, and excessive archive expansion were checked before member inspection. Every file is explained by a retained source/configuration/probe, command log, report, workflow/job/preparation record, or root preparation/dependency log. The workflow body matches the immutable producer Git blob. The preparation checkout, job identity, source revision/tree, direct submodule pins, provisioned interpreter, dependency identities, report summaries, and source/tool stability records agree.

The source proof is external to the replay interface. Before opening the new selected ZIP, the auditor derived its complete expected catalogs from immutable Git and the producer's actual source-selection rules. It then compared **all 270 checked source bodies and all 683 public source bodies** against those independent Git bytes, including each SHA-256, exact length, regular-file mode, and Git blob identity. The local immutable commit object was also checked against its content-addressed commit SHA; its tree is the tree above. The two source counts are overlapping catalogs, not 953 unique source files.

## Why the public inventory is now 683

The checked producer still selects exactly the frozen 270 names. The public producer's `HELPERS` selection excludes test-named helpers from that helper list, but its `source_snapshot` separately retains **all tracked files under `ci/project`**, together with the other declared source roots and critical inputs. Therefore the four newly committed test files are part of the retained public source catalog as inert evidence.

The auditor compared the immutable AST of `HELPERS`, `CRITICAL`, `SOURCE_ROOTS`, and `source_snapshot` with the original producer definitions. Their selection rules are unchanged. Recomputing the original selection from immutable Git agrees exactly with the independently frozen original 676-name public catalog; recomputing the e5 corrected selection gives the same 676 names. All 676 original public source bodies remain byte-for-byte unchanged at checkpoint 4268. No original source name was removed.

Exactly these seven committed files extend the public catalog:

| Added source | Role |
| --- | --- |
| `ci/project/p06_counter_diagnostics_replay.py` | Checked diagnostic replay |
| `ci/project/p06_counter_public_replay.py` | Public diagnostic replay |
| `ci/project/p06_counter_source_inventory.py` | Caller-pinned complete source expectations |
| `ci/project/test_p06_counter_diagnostics_replay.py` | Checked replay tests, retained as data |
| `ci/project/test_p06_counter_inventory_replay.py` | Inventory/replay integration tests, retained as data |
| `ci/project/test_p06_counter_public_replay.py` | Public replay tests, retained as data |
| `ci/project/test_p06_counter_source_inventory.py` | Inventory contract tests, retained as data |

The ZIP member-name difference from the e5 original is exactly those seven files under `public-counters/artifacts/source/`. Its count therefore changes from 1,039 to 1,046. There are no removed member names. Existing execution-report and log bytes are independently checked for this new run; unchanged member names do not mean the new run's contents are identical to e5.

`w10-native-checkpoint-audit-source-derivation.json` retains every public source descriptor and Git blob identity, the checked subset, the original count/name pins, the producer-selection comparison, and the seven additions. Expectations were not inferred solely from archive descriptors.

## Separately pinned complete source manifest

The complete public manifest is generated from immutable Git bytes and retained separately from the original ZIP:

| Property | Value |
| --- | --- |
| File | `public-source-inventory-4268d2d5.json` |
| Contract | `simx-counter-source-inventory-v1` |
| Producer contract | `simx-counter-public-native-v1` |
| Expected producer revision | `4268d2d5d811063bb886cde7bd0e27e61a79c9b4` |
| Complete source descriptors | 683 |
| Exact manifest bytes | 116,997 |
| **Manifest byte SHA-256** | **`bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`** |
| Source-name SHA-256 | `10d18ee597e0cf17d9cd9ab5afcc6414e1dcc1343a1e753a8b871565ca397887` |
| Original fixed 676-name SHA-256 | `f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da` |

The manifest byte digest includes its exact JSON formatting and trailing newline. The source-name digest instead hashes the lexicographically sorted relative names, each followed by LF. They are distinct pins and are never substituted for one another. No explicit checked manifest was needed: its unchanged 270-name route passed, and this audit independently matched every retained checked body to Git.

An external manifest is a caller trust input. The reusable replayer only compares retained bytes and descriptors to that input; it does not independently establish GitHub provenance or source-to-binary origin. The separate immutable-Git and API checks in this audit supply the narrower source/original-artifact mapping, without extending it to absent executable payloads.

## Actual replay commands and inertness check

The reviewer invoked the current trusted CLI processes with canonical absolute archive/manifest paths and fresh absolute output paths. The exact argv, exit status, failure reasons, result descriptors, and false acceptance flags are retained in `w10-native-checkpoint-audit-cli-results.json`.

| Route | Exit | Observed result |
| --- | ---: | --- |
| Checked, original fixed 270-name inventory | 0 | Pass; 270 sources, 17 commands, seven cells |
| Public, original fixed 676-name inventory | 1 | Expected rejection: `versioned source inventory: value differs` |
| Public, explicit complete 683-name manifest and exact byte digest | 0 | Pass; 683 sources, 14 commands, five public modes plus boundary control |
| Public, explicit manifest with a wrong external digest | 1 | Expected rejection: `source inventory manifest SHA-256 differs from the external digest` |

The two rejected routes created no requested output file. Their actual stdout is retained in the corresponding `*-cli.json` records. The explicit correct-manifest receipt names the supplied manifest, its exact byte digest, the matched source count, and the distinct name digest. Explicit failure did not fall back to the legacy route.

A complete successful public replay also ran with filesystem and execution guards. It was allowed to read only the selected ZIP, selected manifest, current trusted local reader sources, and pinned current archive parser. It could traverse only the directories needed for those paths. The guard prohibited subprocesses, native compilation/execution, source-snapshot routines, archive extraction, retained-code execution, unrelated path access/discovery, and writes. Both selected data files were actually opened, and the guarded result exactly equals the successful actual CLI result. This checks the concrete replay path; it is not a claim to defeat an arbitrary malicious host or concurrent writer.

The checked receipt identifies 25 current trusted reader source files and the public receipt 28. All are separately pinned to immutable checkpoint-4268 Git bytes, and the full trusted local helper set remained stable throughout the review. The separately pinned archive reader is current trusted verifier code; no code was loaded from the native ZIP.

For a new public replay, use the source repository's current trusted CLI and select a new output filename:

```sh
python3 -B /workspace/scratch/98908dfa3444/AI-GPU/ci/project/p06_counter_public_replay.py \
  --archive /workspace/scratch/98908dfa3444/AI-GPU/docs/project/evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip \
  --sha256 6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb \
  --source-revision 4268d2d5d811063bb886cde7bd0e27e61a79c9b4 \
  --source-inventory /workspace/scratch/98908dfa3444/AI-GPU/docs/project/evidence/p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json \
  --source-inventory-sha256 bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c \
  --output /workspace/scratch/98908dfa3444/w10-native-checkpoint-audit-new-public-result.json
```

The full independent auditor is retained as `w10-native-checkpoint-audit.py`. Its byte/build/log checks adapt the previously reviewed wave-7 audit; its new independent immutable catalog derivation, raw arithmetic reconciliation, actual CLI routes, and guarded current replay were reviewed and executed for this packet. To rerun the full auditor, supply the retained archive/API paths and artifact ID named above, a source checkout whose trusted helpers still match 4268, and `--out` in a new existing absolute directory. Its generated CLI outputs must not already exist. No new native build is part of reproduction.

## Build, execution and raw observations

Every retained command log is rehashed against its original descriptor and checked against its argv, working directory, sanitized environment, timeout, process-start/cleanup status, exit result, and resource record. There are exactly 17 checked/model commands and 14 public commands. The complete public per-command stability chain and all nine binding groups agree. Version logs and the provisioning record identify the actual reported CPython 3.12.14 interpreter.

Both checked/model variants and the public packet's separately built checked model each have **45 exact model translation units and one model link**. Compiler logs, stamps, macro ordering, generated configuration, original-plus-footer TCU source, source/object assignments, and link records are recomputed with the trusted current parsers. The public build adds **19 translation units**, reuses **44 model objects**, and has **four links**:

| Output | Retained link role |
| --- | --- |
| `libchecked-simx.so` | 44 reused checked-model objects |
| `libvortex.so` | 14 public runtime objects |
| `libvortex-simx.so` | Three backend objects plus observation hooks and required Processor wraps |
| `checked_public_test` | Diagnostic main linked to runtime/backend |

All seven checked/model cells pass, including ordinary/checked boundary equality, actual core overflow, cache aggregate overflow, the pending primitive underflow, cache backing overflow, and TCU backing overflow. The public packet has its own passing checked boundary control. Pending-underflow remains a primitive diagnostic, not a private model pending-count injection.

| Public mode | Raw schema | Assertions | Constructed / disposed | Typed overflows | Native reads |
| --- | ---: | ---: | ---: | ---: | ---: |
| normal | 2 | 1,668 | 2 / 2 | 0 | 132 |
| immediate-overflow | 2 | 1,176 | 2 / 2 | 1 | 66 |
| delayed-overflow | 2 | 1,176 | 2 / 2 | 1 | 66 |
| cache-overflow | 2 | 1,173 | 2 / 2 | 1 | 67 |
| coherent-terminal | 2 | 1,814 | 2 / 2 | 0 | 132 |

Independent raw-log arithmetic confirms the **33-selector / 40-backing-component / 12-unavailable** inventory. The unavailable selectors remain unqueried. Seven terminal vectors reconcile **231 public selector queries and 462 successful native low/high replies**, plus one failed native read in cache-overflow. All native JSON and manifest arithmetic use Python integers/raw bytes; no native JSON passes through JavaScript. Seeds `18446744073709551615` and `18446744073709551613`, coherent backing values above `2^53`, sums, and low/high reconstruction remain exact.

Every terminal vector preserves ticks, reset generation, backing components, and exclusive ownership across readout. The coherent first vector uses the fixed independent seed formula; its fresh second context is unseeded. All ten constructed contexts have complete disposal records with zero platform ticks and idle state afterward.

The immediate and delayed failures are typed overflow observations through the real wrapped `Processor::run_checked` path. The delayed seed advances by exactly two to `UINT64_MAX`; neither asynchronous failure retires the scalar program. Cache-overflow preserves actual poisoned backing values `[UINT64_MAX, 1]`, observes the typed failed native DCR read, and leaves the public query sentinel unchanged. Source inspection confirms the wrappers call the corresponding real Processor operation and rethrow the typed exception.

All three negative modes retain an actual attempted DMA retry at address **196,608**. The attempted payload is the bitwise-inverted three-word program, status is 3, and direct RAM before and afterward remains **`[7340435, 28683, 11]`**. The two later counter queries preserve their exact 64-bit sentinel. Query/write/DMA/second-queue-launch suppression leaves the model run/read/write/overflow-entry counts unchanged. Each mode subsequently constructs a separate successful context and disposes both processors.

## CP drain interpretation and qualification limits

At each terminal vector, both CP enable controls are one, status/error are zero, and retired sequence equals the expected sequence. Across the 66 native half-read commands, retirement moves **26 → 92**, and both the runtime tail and raw tail pair move **1,664 → 5,888**, at exactly 64 bytes per retired command.

The observed head-writeback bytes remain `0` with status `not-published`; they are not an observed internal CP head. The raw tail pair combines the staged low register with committed high bits and is not an independent full committed-tail observation. Drain is a **source-backed inference under exclusive serial ownership**: `CommandProcessor::busy()` covers pending ring work, a loaded cacheline, and active command/launch engines; runtime submission stages low, commits with high, and waits for the reserved retired sequence. The audit inspects the immutable CP implementation, runtime submission, exclusive-owner harness, and real-operation wrappers. It does not broaden that directed conclusion into a general concurrency or lifetime theorem.

The packet does not contain object, executable, tool, or dependency payloads. Their reported hashes and before/after bindings establish internal producer-record consistency only. This audit cannot independently rehash those absent payloads, reproduce their builds, prove source-to-binary origin, establish cached-dependency compilation origin, or inventory every host header/compiler support file/system library. A successful native job plus matching retained source bytes does not remove that limitation.

Seed-enabled diagnostics and scalar controls do not qualify seed-free measurement binaries, GEMM, workspace reuse, the complete managed warm caller, a cumulative no-wrap bound, warm performance, or a new phase gate. Native SimX evidence remains software simulation; no processor RTL, full-AFU, vendor emulation, physical FPGA, or silicon result is inferred. The unconditional historical `P06-WARM-RV64-MPM-HIGH-HALF` v1 block remains in force.

## Preservation and retained receipts

Only a fourth artifact entry was appended to `native/index.json`. All three original ZIPs, their original report/hash index entries, and the failed job log remain byte-for-byte unchanged. The exact three-field `public-runtime-pass.json` still points to the e5 genuine original used by the existing public replay suite. No original failure or blocked cell was relabeled. The preservation snapshot and final receipt record those checks. This agent did not commit or push.

| Retained file | SHA-256 |
| --- | --- |
| `w10-native-checkpoint-audit.py` | `0e7dfdcea76004b8e2c7c5404c742050504fd48b3b2fee86cbac4bcf51639796` |
| `w10-native-checkpoint-audit.log` | `828a9e69db56b9d90a104b4a6e95309f25af22f59863ca3a5d33226ebd5b9fb3` |
| `w10-native-checkpoint-audit-receipt.json` | `5795af860fb750478b8fdb9c2c8dcb3532431f2b00e60fb55ff50a76fd76e855` |
| `w10-native-checkpoint-audit-source-derivation.json` | `fa29402ec835cb02853239083b0b98d5d908bd869f9b0da7e77e24bc10893bf2` |
| `w10-native-checkpoint-audit-cli-results.json` | `d74e537c991403f78bc4df6148748eff747f533b564e526141024a5524e1de47` |
| `w10-native-checkpoint-audit-checked-replay.json` | `cc495962693d223a6d236b0b427ab92d4aca8ce806081ece82844fb1cb041a11` |
| `w10-native-checkpoint-audit-public-replay.json` | `d30eba5f1a88ffab019a8f8dc46934ce749c1aa2b14c25605d1b50708be3165d` |
| `w10-native-checkpoint-audit-public-legacy-cli.json` | `400cee192c73a8648879f9e053cb40d1c625f97c99254e77dc114c5fa72cbf0f` |
| `w10-native-checkpoint-audit-public-wrong-digest-cli.json` | `d612aebbb55c48c546f339ab24bb6e951699fa7630d17594027cb47889e88716` |
| `w10-native-checkpoint-audit-artifacts-api.json` | `0b4f9cbfa02b103eb4ed9985628b94347fe5ce7d360b39b24e9574143f95fcdd` |
| `w10-native-checkpoint-audit-jobs-api.json` | `21787a016c2fe70d72ca3b1c68601c43990165d0d1c8b09699ba9836be56f385` |

The audit completed successfully on its first full execution. No native rebuild, new full suite, archived-code execution, source fixture change, gate change, waiver, or acceptance decision was part of this work.
