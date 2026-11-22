# Wave 7 independent original native/public artifact audit

## Verdict and exact scope

**PASS for the consistency and immutable-source binding of the original corrected hosted diagnostic packet.** Run `45031746149`, attempt 1, job `137236632765` completed with GitHub conclusion `success` at producer commit `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`, tree `74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`. The original ZIP contains seven passing model cells, a passing public boundary control, and five passing public diagnostic modes.

This review is an independent **data replay of original native execution evidence**, not another native execution. The auditor did not build or run native code, extract the archive, execute retained code, change production or test files, edit the native index, commit, or push. All public JSON was decoded with Python integers. The original successful archive was saved byte-for-byte into `AI-GPU/docs/project/evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip` only after its size and SHA-256 matched the GitHub artifacts API.

The earlier original failed packet remains a failure. Its successful evidence-integrity review is recorded with `audit_outcome=pass` and **`native_outcome=fail`**; no failed or blocked execution is promoted.

## Original archive identities

| Property | Corrected original | Earlier failed original |
|---|---|---|
| Producer | `e5f152464dda5e488d6d1a030c1fcdc49b5a9701` | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c` |
| Workflow run / attempt | `45031746149` / 1 | `45029135146` / 1 |
| Job | `137236632765`, success | `137228604864`, failure |
| Artifact ID | `14758252829` | `14756979623` |
| ZIP bytes | 4,228,429 | 4,193,299 |
| ZIP SHA-256 | `05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276` | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` |
| Archive members | 1,039 | 1,035 |
| Model report SHA-256 | `f33058445b0ce4e7284baaa2c2c49c4819c2708ddff0fc49bc6854cf20f75d18` | `9f57ded33597ae5dda914d4b0b2203b79dd62beebd92f5361bed77bfd07e4df1` |
| Public report SHA-256 | `a81c6a997a2a220b4db6d2ddecac21e08dfa32a522de0fabc2e0f89acfb2d925` | `c0b889295eba1dec1ab102fb480399fb596c1362bfd6550992d8279c7a593e8b` |

Source: the purpose-built GitHub artifacts/jobs API responses retained as `w07-corrected-artifacts-api.json`, `w07-corrected-jobs-api.json`, `w07-failed-artifacts-api.json`, and `w07-failed-jobs-api.json`; exact originals and the independent receipt/log pair for each run. The jobs API confirms both execution steps and upload succeeded for the corrected run. For the older run it confirms model execution success, public execution failure, and artifact upload success.

## Checks completed

The reproducible `w07-native-public-audit.py` checks the API digest and byte count before opening a ZIP. It rejects duplicate or unsafe member names, special files, encryption, excessive member size and excessive expansion. It never extracts files. Every original archive file is accounted for as a retained source/configuration/probe, command log, report, workflow/job/preparation metadata, or root dependency log.

For each original, the audit compares **270 model source bodies and 676 public source bodies byte-for-byte with immutable Git blobs at that original's revision**. It checks the exact tracked source inventory; report revision/tree; clean checkout declaration; direct submodule pins; preparation source identities; before/after source and tool identities; and retained descriptor digests. It first pins every tracked non-test local `ci/project/*.py` helper used for the trusted parsing environment to corrected commit `e5f1524`. Retained artifact code is never imported.

The corrected model packet has **17 commands**, and the corrected public packet has **14 commands**. The failed packet has 17 model commands and only 10 public commands. Each retained command log is rehashed and bound to its descriptor, actual argv, working directory, environment, timeout, process-start/cleanup outcome, exit result and bounded duration/resource record. The public packet's complete before/after command stability sequence and nine execution-binding groups are reconciled. Top-level execution summaries are compared with their reports. CPython version output is exactly `Python 3.12.14`; the provisioning record, selected executable paths and report identity chain agree.

Model compile/link logs are parsed as inert command records: each build has **45 exact translation units and one link**, including the original-plus-footer generated TCU source. The public build has **19 newly compiled translation units, 44 reused model objects and four exact links**. Compiler-stamp definitions, ordered macro inventories, source-to-object mapping, dependency targets, wraps, link arguments and generated configuration are rechecked. The actual role mapping is:

| Linked output | Role established by the retained link record |
|---|---|
| `libchecked-simx.so` | Model, using the 44 reused checked-model objects |
| `libvortex.so` | Public runtime, 14 runtime objects |
| `libvortex-simx.so` | Three backend objects plus the observation hooks, with required Processor wraps |
| `checked_public_test` | Public diagnostic main, linked to the runtime and backend |

Object and binary hashes are compared for internal stability and binding only. Their bytes are absent from the packet, so this review does **not** independently rehash or authenticate those executable/object payloads or prove cached dependency compilation origin.

## Corrected native observations

All seven model cells pass: ordinary boundaries, checked boundaries, actual core overflow, cache aggregate overflow, pending primitive underflow, cache backing overflow, and TCU backing overflow. The ordinary/checked raw boundary observations agree after removing the expected checked-mode flag. The public build's separate checked boundary control also passes.

| Public mode | Raw schema | Assertions | Contexts constructed / disposed | Typed overflow observations | Native DCR read entries |
|---|---:|---:|---:|---:|---:|
| normal | 2 | 1,668 | 2 / 2 | 0 | 132 |
| immediate-overflow | 2 | 1,176 | 2 / 2 | 1 | 66 |
| delayed-overflow | 2 | 1,176 | 2 / 2 | 1 | 66 |
| cache-overflow | 2 | 1,173 | 2 / 2 | 1 | 67 |
| coherent-terminal | 2 | 1,814 | 2 / 2 | 0 | 132 |

The exact inventory remains **33 selectors, 40 backing components, and 12 unavailable selectors left unqueried**. Seven successful terminal snapshots reconcile 231 selector queries and their 462 low/high native replies; the cache-overflow mode retains one additional failed native read. Every low/high reconstruction uses exact integer arithmetic. Per-query ticks/reset generations and before/after model state agree. The coherent mode's seeded first snapshot equals the fixed independent seed formula for every backing component; its later fresh context is unseeded.

The asynchronous immediate and delayed cases reach typed `PerfCounterError::Overflow` in the real wrapped `Processor::run_checked` route. The delayed case advances the seeded cycle counter by exactly two to `UINT64_MAX` before failing; neither case retires the scalar program. The cache case poisons actual backing components with `UINT64_MAX` and one, observes a typed failed native DCR read, preserves those source values, and returns the public error while leaving the query sentinel unchanged. Hook source calls the corresponding `__real__` Processor operation and rethrows the typed exception.

All three negative modes retain a genuine DMA retry using the inverted three-word program payload at address 196,608. The attempted words differ from the original, status is 3, and direct RAM observations before and after both remain `[7340435, 28683, 11]`. Two subsequent counter queries preserve their 64-bit sentinel, and the later query/write/DMA/second-queue-launch attempts do not increase model run/read/write/overflow entry counts. This establishes the retained directed no-reentry and no-RAM-change observations. Every mode then has an actual separate successful context and complete disposal of both constructed processors; disposal records show zero remaining platform ticks and idle state.

## CP drain interpretation and repaired source

The historical failure text is exactly `FAIL native public counter diagnostic: terminal CP ring is not drained`. The older harness incorrectly compared initialized head-writeback storage to its submitted tail even though this backend does not publish its internal head to that storage.

The corrected source keeps the head bytes as `head_writeback_raw=0` with `head_writeback_status="not-published"`. It does not call those bytes an observed internal head. The raw tail pair is explicitly the **staged low register plus committed high register**, not an independent read of the complete internal committed tail.

At every corrected terminal snapshot, both CP enable controls are one; status and error are zero; retired sequence equals expected sequence. Before/after terminal queries, the sequence advances **26 → 92** and both runtime tail and raw tail pair advance **1,664 → 5,888**, exactly 64 bytes per retired command and 66 new half-read commands.

The drain conclusion is a source-backed inference under the harness's exclusive serial ownership: `CommandProcessor::busy()` includes unconsumed ring work (`head < tail`), a loaded cacheline, and active command/launch engines; runtime submission stages the low tail, commits both halves by writing high, and waits for the reserved retirement sequence. The source inspection covers `sim/common/cmd_processor.cpp`, `sw/runtime/common/device.cpp`, the private ownership checks in `public_main.cpp`, and the real-operation wrappers in `public_hooks.cpp`. No production CP implementation was changed by the six-file `81ed68716..e5f152464` correction.

## Failure preservation, limitations and review status

The failed `81ed687` original has seven passing model cells and the public boundary control, followed by public normal **fail**, then four **blocked** modes. Its failing raw log is rejected by the trusted public parser and has no result record or reported passing observations. Its job/report/top-level execution summaries agree on failure. The earlier `407ab9f` all-selector original is a separate historical scope and was not re-audited as new native execution in this wave.

All retained qualification, readiness, warm-execution, full-warm-coverage, phase-acceptance, performance-acceptance and acceptance-claimed flags remain false. These seed-enabled diagnostic binaries and scalar controls do not qualify seed-free measurement binaries, GEMM, workspace reuse, a complete cumulative warm lifetime, warm performance, or any new P06 gate. Native SimX evidence is software simulation; no processor RTL, full-AFU, vendor emulation or physical hardware result is inferred.

Within this audit's original-data, source-binding and repaired-observation scope, no unresolved F2/F3 evidence defect was found. The inherited mechanical classifier reports `R1` for the six-file correction (`path:default`, `path:tests`); this narrow evidence review is not a complete code/contract review, maintainer approval, waiver or publication decision. Native artifact intake is no longer pending. Broader lifetime/source proof, replay adversarial validation and any later seed-free warm execution remain separately scoped work.

## Reproduction and retained work

Run the independent auditor from the source repository, with immutable helper bodies still matching `e5f1524`:

```sh
python3 -I /workspace/scratch/98908dfa3444/w07-native-public-audit.py --zip docs/project/evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip --api /workspace/scratch/98908dfa3444/w07-corrected-artifacts-api.json --jobs-api /workspace/scratch/98908dfa3444/w07-corrected-jobs-api.json --artifact-id 14758252829 --out /workspace/scratch/98908dfa3444/w07-native-corrected-receipt.json
python3 -I /workspace/scratch/98908dfa3444/w07-native-public-audit.py --zip docs/project/evidence/p06-counter-diagnostics/native/run-45029135146-attempt1.zip --api /workspace/scratch/98908dfa3444/w07-failed-artifacts-api.json --jobs-api /workspace/scratch/98908dfa3444/w07-failed-jobs-api.json --artifact-id 14756979623 --out /workspace/scratch/98908dfa3444/w07-native-failed-receipt.json
```

Both audit commands completed successfully. `w07-native-corrected-audit.log` and `w07-native-failed-audit.log` retain their summaries. The successful receipt reports native pass; the historical receipt reports native fail. The four API response files, auditor source, receipts and logs accompany this note in the scratch workspace; only the untouched original successful ZIP was added to the repository evidence directory. The root agent was notified before any shared native index or receipt update; this agent made none.
