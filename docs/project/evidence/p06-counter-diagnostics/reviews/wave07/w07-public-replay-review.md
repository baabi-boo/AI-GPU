# Wave 7 public replay independent review

## Disposition

One **F2 / high-confidence / static-proof** finding remains in the focused replay tests: two raw-result mutation cases still target schema 1 after the public observation schema changed to 2. Their replacements are no-ops and will fail the test method when a genuine successful schema-2 packet is retained. No additional F2/F3 reader defect was found in the reviewed bytes and exercised scope.

This review does **not** establish a successful complete public replay or a new native execution. The successful-original receipt was absent at closeout. The existing failed original was rejected, and its complete build portions were inspected separately without changing its outcome or manufacturing a successful replacement.

Reviewer: `/root/w07_public_replay_review`, independent read-only review, agent 37 / wave 7. Repository: `/workspace/scratch/98908dfa3444/AI-GPU`. Working-tree HEAD: `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`; tree: `74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`. The primary replay implementation and test file were untracked inputs at review time; the content hashes below, not HEAD alone, identify the reviewed implementation.

No repository files were edited. No native builds, broad test discovery, commits, pushes, archive extraction, or retained-code execution were performed. The report is outside the repository. A newly appeared `p06_counter_source_inventory.py` belongs to a separate author/review and was not imported by or included in this tested reader closure.

## Required finding

### F2 — Schema-1 byte replacements silently stop exercising raw-number rejection

**Confidence:** high. **Evidence type:** static-proof, corroborated by a focused parser-unit probe.

`test_public_result_duplicate_keys_numbers_and_record_boundaries_are_strict` in `ci/project/test_p06_counter_public_replay.py` contains two transformations with the search token `b'"schema_version":1'`. Their intended replacements are floating-point `1.0` and `NaN`. The test first canonicalizes the original raw observation JSON through `edit_observation`, while `p06_counter_public_records.verify_record` now requires integer schema version 2. Therefore a valid native record contains `"schema_version":2`; neither schema-1 transformation matches.

I applied those exact transformations to a canonical schema-2 record from the existing, explicitly synthetic raw-record unit fixture. Both search tokens matched zero times, both transformations returned unchanged bytes, and `verify_output` continued to accept schema version 2. This is a parser unit probe only; it is not a synthetic native packet or replacement execution result.

**Concrete impact:** once `native/public-runtime-pass.json` identifies a genuine successful schema-2 archive, the two subtests will pass unchanged valid archive contents to `self.reject(...)` and fail because the expected `ValueError` is not raised. The defect is currently hidden by the successful-original class skip.

**Required correction:** target the current raw schema-2 token, and make each byte-level mutation assert that it changed its intended input before relying on rejection. Keep the successful-original intake requirement; do not replace it with synthetic pass evidence.

### F0 observation — One CP mutation uses an obsolete field name

The terminal ownership/retirement replay test changes `terminal_snapshots[0].cp_after.head`, although schema 2 no longer contains `head`. The helper assigns a new unknown key, so strict field checking rejects it. The test still fails closed, but it does not exercise the intended current CP observation. Consider changing this case to an existing schema-2 field and retaining explicit unknown-field coverage separately. The focused raw-record unit suite already covers `head_writeback_raw`, `head_writeback_status`, `drain_basis`, `runtime_tail`, and `tail_register_pair_raw`; this observation is not an additional merge-blocking finding.

## Evidence and results

All commands ran from the source root with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH=ci/project`.

| Check | Result | Scope |
| --- | --- | --- |
| `python3 -m unittest -v test_p06_counter_public_replay` | 11 methods passed in 0.159 seconds; one class skipped | The 29 successful-original methods did not run because the intake receipt was absent |
| `python3 -m unittest -v test_p06_counter_public_records` | 33 methods passed in 2.062 seconds | Explicit synthetic parser unit records; no native execution |
| Trusted helper inventory comparison | 27 repository modules; no imported repository helper omitted | Compared `_reader_sources()` with imported repository modules; interpreter `<stdin>` was excluded |
| Exact schema mutation probe | Both schema-1 replacements were no-ops; schema 2 remained accepted | Confirms the F2 finding without creating a pass archive |
| Guarded partial inspection of original failed packet | Source/configuration/tool/model/public-build chain validated through nine commands, then failed normal-cell schema rejected | No outer outcome was altered; producer-path IO, process launch, live object hashing and extraction primitives were guarded |
| Seven pure-public-build mutations against original failed-attempt compiler data | All seven rejected | No filesystem reads or process starts were allowed in the parser invocation |

The seven build mutations removed a public compile, duplicated a public compile, substituted the wrong source for an object, changed `SIMX_CHECKED_COUNTERS=1` to `0`, omitted a required Processor linker wrap, substituted a foreign model library, and omitted one reused model object. The positive parser control used the original completed build records and reconstructed 19 public translation units, four links, and 44 reused model objects after recomputing the 45-translation-unit model summary.

During review-probe development, one assertion expected a narrower error message than the failed cell actually emitted; the actual rejection was `public diagnostic cell: missing or unknown fields`. A later mutation helper also caught its own no-op when replacing a logical multiline link in unnormalized physical log text. Both probe issues were corrected and rerun. The final guarded partial inspection and all seven parser mutations completed as stated above; neither probe changed repository or archive bytes.

The original failed packet is `docs/project/evidence/p06-counter-diagnostics/native/run-45029135146-attempt1.zip`, externally supplied SHA-256 `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5`, producer revision `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`. Full replay rejects `producer outcome`; its normal public cell failed and the other four public modes remained blocked. The partial build inspection retained the frozen 676-name inventory digest `f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da`.

## Reviewed boundaries

- **Raw observations:** The public reader reparses original command logs through the strict schema-2 raw validator and recursively compares decoded observations with the stored summaries. The raw validator requires exact fields/types, bounded integer values, a unique final result, no duplicate JSON keys, and no floating-point or nonfinite raw numbers. The CP contract labels `head_writeback_raw` as not published and the tail pair as staged-low/committed-high data whose correspondence depends on completed serialized submissions.
- **Source and tool provenance:** The shared packet helper binds original retained source bytes to the reported before/after inventories, required source bodies, clean-checkout fields, profile hash, declared pins and submodule records. The reviewed public reader still freezes all 676 source-relative names, including uncompiled headers. The known later-inventory compatibility work was reserved for a separate author and must retain omitted-header rejection.
- **Configuration and build composition:** Retained configuration copies, `config.mk` template expansion, configure stamp, exact header probe, original model stamp, generated TCU body/footer and effective-header observations are bound. The original model log is reparsed before its objects are reused in the public parser. Public compilation roles, ordered stamp macros, flags/includes, exact source/object mappings, four link roles, model dependencies, five Processor wraps and the 44-object reuse inventory are checked as inert data.
- **Identity and stability:** The public reader requires nine exact before/after binding groups and compares them with the identities derived from the retained/configured/model/public records where payloads exist. Source review confirms the required 14-command inventory and 28 ordered stability rows. The failed packet allowed independent exercise through the complete nine-command build prefix; the final five successful public-run cells and complete stability sequence still await real successful evidence.
- **Archive and IO boundary:** The pinned archive helper checks the externally supplied SHA-256 before interpretation and again on close, enforces canonical non-symlink archive paths, rejects unsafe/duplicate/special members and unsupported ZIP formats, bounds archive/directory/member/expanded/read sizes, strictly decodes JSON, and checks member closure within the selected packet prefix. Producer paths remain `PurePosixPath` data. Public replay calls `parse_build_records`, never the live `validate_build` routine.
- **Current reader closure:** All 27 imported repository helpers were included in the reader source inventory, with trusted-repository path checks and before/after source hashing. The separately loaded archive helper is pinned to SHA-256 `4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3`.

## Explicit limitations and next action

A consistent packet is not proof of genuine execution, GitHub origin, an authentic Git tree, or absent object/binary/tool/dependency payloads. Object and executable digests are reported identities; replay does not rehash their missing payloads. Before/after observations do not defeat malicious concurrent producer writers. The reader correctly keeps all qualification, readiness, warm execution and acceptance claims false and reports `native_execution="not_run"`.

No successful original public packet was available for this review. The 29 success-dependent replay tests, complete 14-command replay and all six successful cells remain **not run**, rather than passed. Native SimX evidence, when received, will remain distinct from processor RTL, full-AFU vendor emulation, physical hardware, a complete lifetime theorem, or a warm performance experiment.

**Next bounded action:** fix the two stale schema mutation cases, retain and independently identify the genuine corrected native packet, then run the focused public replay module against that original. Review the separately authored source-inventory contract update without dropping omitted-header coverage. No synthetic pass receipt is authorized by this review.

## Final content identities

The primary files below matched their opening review hashes at closeout.

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_counter_public_replay.py` | `6a89c103f7e2bc79b0f51af44754bf378f87ac1ffc847dafe0edc67a5066c18b` |
| `ci/project/test_p06_counter_public_replay.py` | `0bcc97736f976849f71c981dd6cca4fb61572ca3d6f9160593f9669529926f7b` |
| `ci/project/p06_counter_diagnostics_replay.py` | `6284fda2985533e327bddcfa02c2341b8f7c17b1ba123d0a66b3d263187e5b75` |
| `ci/project/p06_counter_public_build.py` | `22982ed2264626fb1be2b86785fddb89655c9e0f82a2257ce0e9ab7c89eab758` |
| `ci/project/p06_counter_public_records.py` | `d947be071b670edcbc0b7d613860c288ee1b013f16e256679747afe0353a7e78` |
| `ci/project/p06_checked_execute.py` | `86ba0b3fd2bbfa97ebb2346e69fed85968fd3da8bf267d4dc1a13aaacf8b358e` |
| `ci/project/p06_replay.py` | `9a5e68de45ec923c56e39a05697d9f93b3d0fdd91c81d38d6637c12ba153d991` |
| `ci/project/test_p06_counter_public_records.py` | `6db25cdc71e58c2458c61007e1e616fe19adf91f771cfe5cfbe398ce99bd2a84` |
| `docs/project/evidence/p05-torch/reviews/archive_reader.py` | `4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3` |
| `docs/project/evidence/p06-counter-diagnostics/native/run-45029135146-attempt1.zip` | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` |

### Complete trusted replay-source inventory

| Path | SHA-256 | Bytes |
| --- | --- | ---: |
| `ci/project/baseline_inventory.py` | `ae98afa10a19703c4247b22bdf3d7218cba12ef37b95da8a7caefb788ad7b259` | 20466 |
| `ci/project/baseline_matrix.py` | `165f0d091fa842617471405fb046247d893c8a0c5a2245b16bb4257ad300ebdc` | 8890 |
| `ci/project/baseline_packet_contract.py` | `0cbdbebbceac67440fa1baa9ac9951f9f705aed9476275955815d6cb867e58df` | 53680 |
| `ci/project/baseline_packet_io.py` | `53ac39e541628a68b3d405201734195e8ed606b26eab5ee72746e96b3148515d` | 14315 |
| `ci/project/baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` | 12627 |
| `ci/project/compiler_records.py` | `7a7088deb078eaa58016fc09dacd0f2a3415aaeac18a6dec8c8304de22bf66b4` | 7143 |
| `ci/project/p02_fixture_oracle.py` | `12e546864a4fef5b05e10c7a04b1006bcd59376e5921ea1221c4d42668490145` | 23351 |
| `ci/project/p02_layout_fixture_oracle.py` | `34e78c0313e2b032930615f02a790729d1c49293349728b55f7d04a29a2568a7` | 10910 |
| `ci/project/p02_matrix_records.py` | `b32804945e687c6a02debddc6fad2b7aaf4bd87aa7a8e2315b92605fdfa0c8d9` | 12332 |
| `ci/project/p02_wmma_fixtures.py` | `4a672a5d3357f220120f43e5f5d7e880f7d0ba36df380d69cd1873ea4879835e` | 16440 |
| `ci/project/p02_wmma_numerical_fixture_oracle.py` | `083450dc11712e5fc6dce7d19fb854bd9ef25b738347efd56bd07e81b079570b` | 15556 |
| `ci/project/p03_execution_records.py` | `b26449105f17f9487cc4fbaab36884ceea42be9f502a26aa58331ed4cf1140de` | 6961 |
| `ci/project/p04_execution_records.py` | `abddfb06fb48bbd064c09d61879b278bca22778f5a8289f4c1ac93fb882b33e0` | 16283 |
| `ci/project/p04_fixture_adapter.py` | `37a50f6f0f80fd79b926b7ed5d13a233de6bf518590da7fa7d40800dcc91094a` | 5364 |
| `ci/project/p04_model_contract.py` | `c184d980d57aec54567d79025845c5fb34887741697ac78a66692a65da02e4b3` | 15901 |
| `ci/project/p04_reference.py` | `115a7db51948d69fc6267d5fe658d1a8e68c22e9f200d5ddc3f0a5181d7140a9` | 11855 |
| `ci/project/p06_checked_execute.py` | `86ba0b3fd2bbfa97ebb2346e69fed85968fd3da8bf267d4dc1a13aaacf8b358e` | 38609 |
| `ci/project/p06_compiler_records.py` | `f441c12f4c9e4b9ef10eca13f8b5291fc41ffb86f1f42e42dfd320056dedd6da` | 13614 |
| `ci/project/p06_contract.py` | `780086070739b6d3586f9b3695ad4dc31d209a7817cf1af3651160a9fe6e1376` | 31500 |
| `ci/project/p06_counter_diagnostics_replay.py` | `6284fda2985533e327bddcfa02c2341b8f7c17b1ba123d0a66b3d263187e5b75` | 33316 |
| `ci/project/p06_counter_public_build.py` | `22982ed2264626fb1be2b86785fddb89655c9e0f82a2257ce0e9ab7c89eab758` | 15413 |
| `ci/project/p06_counter_public_records.py` | `d947be071b670edcbc0b7d613860c288ee1b013f16e256679747afe0353a7e78` | 20774 |
| `ci/project/p06_counter_public_replay.py` | `6a89c103f7e2bc79b0f51af44754bf378f87ac1ffc847dafe0edc67a5066c18b` | 20954 |
| `ci/project/p06_mpm_execute.py` | `c9524652c24121401f7d2cb044cae72c4f6dece7f8d8357d886d7b1ef63fcea0` | 23153 |
| `ci/project/p06_records.py` | `cb5740ae915a0c383fd41c9f67d4f40a02875487383c67d22cf211f1a9ba3fb7` | 28046 |
| `ci/project/p06_replay.py` | `9a5e68de45ec923c56e39a05697d9f93b3d0fdd91c81d38d6637c12ba153d991` | 44626 |
| `ci/project/preflight.py` | `102c174cb6e3baa082957a88e05080f9b18e80340e663702f8585586eecf6032` | 15124 |

Report recorded at 2026-11-22T14:23:28+00:00.
