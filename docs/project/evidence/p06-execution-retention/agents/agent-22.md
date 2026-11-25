# Agent 22 — frozen contract audit

## Scope and disposition

Read-only review of working tree based on `622662ad9cece6da4e3375be7e977dbe04cde862`, on 2026-11-25. Read `AGENTS.md`, task brief, canonical acceptance/status material and relevant P06 contracts. **No frozen-contract/admission regression found in the reviewed operational diff.** This report is the only authored file.

## Exact observations

- Independently recomputed SHA-256/size for all **69 distinct measurement-source rows**. Every row equals both `p06_qualified_warm_proof.json` and `validation/measurement-sources-before.json`. Canonical sorted-key compact-JSON row-list digest: `21ba69d11a9bdb91eab4abee75589710cd3dcc092895ec251350f4f4ce215d8b`.
- All five `frozen-inputs-before.json` identities match current files and HEAD: qualified proof, historical counter proof, warm JSON contract, protected framework SVG and roadmap JSON. Warm contract: 25,793 bytes, byte SHA-256 `893d85401b1d5f7757d82cb7c743a89b36264fe19c7d08c239b7f216b7a8cbbd`, independently computed semantic SHA-256 `03d745772e59b987c7983c17998feabf1d4e8af0935a50bb3ed14b6d03340d2f`.
- Qualified proof: 21,505 bytes; byte digest `172721c671ddaa79541dde9c37c154b5ab5a99b8abb0caabf2e07036dd429efb`; semantic digest `cd3a355495ee79d147b579cbd84cb58c8b6e0eb0743eb98f080b0ccc10d57a0e`. Historical proof: 123,781 bytes; byte digest `d12718e9b182a3c93eab346901b380031516d556dd823017a63831d4a0304b4e`; semantic digest `b91a7f84411bfd9a05058e54b50904812406c5699b76b582674d835399a6025e`. Both independent semantic calculations match hardcoded contract pins. Both repository proof validators and the warm-contract validator pass.
- Independently reconstructed FP16-then-BF16, pairs 0–5, alternating policy order. Population remains **24 processes / 792 launches / 25,344 checked FP32 words**: one prime plus 32 serial explicitly closed operations/process; four warm-up and 20 measured processes; 640 measured operations/20,480 measured words. Native/reader comparisons still require all 32 exact expected FP32 words and zero mismatches per operation.
- Five measured batch means per format/policy remain fixed. Both formats require candidate median <=95% of reference, every paired host total <=reference and every paired modeled-cycle count <=reference, using exact integer cross-products. Primes/warm-up remain retained and excluded. No replacement, outlier removal, optional stopping or implicit resume was added. All seven frozen claim fields remain false; analysis leaves performance/phase acceptance false.
- Runner `stage_specs`, `clean_environment`, `validate_stage_report`, `report_terminal`, `_observe_stage` and `selected_sources` ASTs exactly equal HEAD. Native producer/admission/record/analysis files below are byte-identical to HEAD. Child argv retains explicit lifetime/qualified-warm mode, fixed sample identities and unchanged budgets. Failed launch-checkpoint handling records that no child started and aborts. Hosted `native_execution` reconciliation requires a finished matching-revision report after source stability/completed-writer checks; it does not grant acceptance.
- `xrt_signals.py` already exists byte-identically in HEAD; the diff newly uses it in operational CLIs. Its SIGTERM-to-KeyboardInterrupt context restores enclosing handlers and does not select samples or change native argv. It is added to runner `SOURCE_FILES`, inherited by hosted inventory, with unchanged repeated before/after/copied-source checks; it is absent from frozen measurement sources. Exact proof pins, live dependency admission and all 69 source checks remain mandatory. Expanded operational retention does not loosen native admission.
- Concurrent late edits to encryption/packaging `_directory` cleanup were detected before report writing and reviewed: descriptor ownership advances before closing the parent, preserving the active exception if cleanup also fails. These edits remain operational and do not change this frozen-boundary conclusion.

## Bounded validation

Ran from source root using pinned CPython 3.12.14:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PYTHONPATH=ci/project /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_qualified_warm_contract test_p06_qualified_warm_admission test_p06_warm_contract
```

**44 tests in 4.519 seconds; OK; no failures/errors/skips.** Admission tests explicitly mock original-archive replay. Independent hash/population/predicate checks also passed. The tested contract/admission sources did not change; later packaging/encryption cleanup edits were inspected, not exercised by this test command. Frozen identities and reviewed hashes were rechecked immediately before writing this note.

## Reviewed source identities

SHA-256 values bind this review. Paths are repository-relative. Only the six operational `p06_qualified_warm_{control,encrypt,hosted,inputs,pack,run}.py` files differ from HEAD.

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_control.py` | `a303c3dc56076bbb203376521534e465c5d97b997c9ae1b93e6375e98d298fcd` |
| `ci/project/p06_qualified_warm_encrypt.py` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `ci/project/p06_qualified_warm_hosted.py` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `ci/project/p06_qualified_warm_inputs.py` | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `ci/project/p06_qualified_warm_pack.py` | `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a` |
| `ci/project/p06_qualified_warm_run.py` | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `ci/project/xrt_signals.py` | `a9531608094a233e5336a35e9fa7ebd028aaa3fc6dd7d3ed0f6f4d3f83a94fb8` |
| `ci/project/p06_qualified_warm_contract.py` | `f8984c8f286094e7853410c2a8c67bc9aecf81aea860b3ffaff0bcd2aebac112` |
| `ci/project/p06_qualified_warm_admission.py` | `849b3cf591d419bf50eea02b94f6801499859208f802b376a81a2c2b3bca28e2` |
| `ci/project/p06_counter_qualification_contract.py` | `d445b9447aefb4f2917f827105df9b5722c461f10f68629176f2dc2d2321fd0d` |
| `ci/project/p06_warm_contract.py` | `d311c5fb77e651a93fde368f0e41d517f40199a3bd43e27c302d4d00888cc31e` |
| `ci/project/p06_managed_preflight_execute.py` | `2aa330b428852b3b0f0acc9bcc32cc464959b7f255d709f13cde310319b2fe4e` |
| `ci/project/p06_qualified_warm_execute.py` | `2eea05ae66b070bbdd1c6e48201d5108e4b9cc0bcd1f71c5fd8c23e8bea25dce` |
| `ci/project/p06_qualified_warm_records.py` | `100a513d0e34b358c4f2676f9fc4d565160bd0b3b7499d9ae51f6ce1cbe3e29b` |
| `ci/project/p06_warm_records.py` | `28d7e2c1553fc0929a106bc24a62fa2d612e415449ee0e9ac84ad582289381e7` |
| `ci/project/p06_qualified_warm_analyze.py` | `7443625aefbefbdb749527c333ff13b4e9e1144ce256acee460247187acbc28f` |
| `ci/project/p06_warm_analyze.py` | `ac273f587f759900d16ad41c7c63c2d2b10ca0864d5018f8403572f75e5a3e88` |

## Limits and next action

Source/contract tooling evidence only: no native attempt, fresh prerequisite replay, strict full-governance pass, producer authentication or phase/performance acceptance. No private control/decryption inputs were acquired; no native build/hardware workload ran. Broader operational closeout fault behavior belongs to separate assigned reviews. Later source changes require rechecking changed identities. Next: preserve these pins through consolidation and exact-revision qualification; native execution still needs genuine inputs/resources and unchanged admission.
