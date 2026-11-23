# W09 A03 follow-up — hosted governance completed with skips

**GitHub reports success, but this run does not prove all 4,527 canonical tests executed without skips.** The completed original returned log reports `Ran 4512 tests in 3555.657s` and `OK (skipped=23)`.

## Exact revision and timing

- Revision: `c0b44ce64665fe11895f869eea8c38c9b820d6f7`; tree `13450812d279d55f36a172fcf38653ff567f6c86`; attempt 1.
- [Run 45244780344](https://github.com/baabi-boo/AI-GPU/actions/runs/45244780344) and [job 137938581226](https://github.com/baabi-boo/AI-GPU/actions/runs/45244780344/job/137938581226).
- Job started 2026-11-23T19:36:08Z and completed successfully at 2026-11-23T20:35:47Z. The tooling step ran from 19:36:26Z through 20:35:45Z.
- Completion was observed by the jobs endpoint at 2026-11-23T20:36:40.291Z. Completed run and original job-log readbacks were requested at 2026-11-23T20:36:55.169Z.
- The monitor stopped on completion before the 20:40 UTC cutoff. Individual timestamped readbacks remain in this directory.

## Independent ID comparison

| Measure | Count |
|---|---:|
| Canonical discovered IDs | 4,527 |
| Distinct method rows in hosted log | 4,512 |
| Passed methods | 4,491 |
| Individually skipped methods | 21 |
| Skipped class-setup events | 2 |
| Canonical methods omitted by those class skips | 15 |
| unittest skip events in summary | 23 |
| Canonical test bodies unexecuted | 36 |
| unittest failures / errors | 0 / 0 |
| Duplicate / unexpected method IDs | 0 / 0 |
| Unexplained population differences | 0 |

The arithmetic is exact: **4,527 − 15 = 4,512 method rows**; **4,491 passes + 21 method skips = 4,512**; **21 method skips + 2 class skips = 23 skip events**. The two class skips suppress 15 method executions, so **21 + 15 = 36 canonical test bodies did not execute**. All canonical IDs are accounted for without treating skipped bodies as executed.

Parsing handled three multiline unittest descriptions and one test that intentionally emits a compiler diagnostic before its separate `ok` line. That compiler diagnostic is not a unittest error. Every parsed method had exactly one terminal outcome. The ID population digest remains `5fd7fbf2f57425467c8124307dbe6ad951e48fe2526a531c87023b58626761fc`.

## Exact invocation and Python

Canonical and logged command match exactly:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

The workflow requires Python major/minor 3.12. The log records `3.12.3 (main, Aug 31 2026, 10:18:26) [GCC 13.3.0]`, which satisfies that requirement. Independent discovery used `3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]`; its patch/build version differs. This difference does not explain the 15 missing rows: all 15 are explicitly covered by the two class-setup skips.

## Why the skips occurred

The log explicitly reports `Tool cmake: available (optional)` during preflight at 19:36:23.9528295Z. The frozen source constructs a separate dependency-fixture tool inventory using `shutil.which` against its clean environment. That PATH includes the executing interpreter's directory, `/usr/bin`, and `/bin`; these fixture calls supply no optional `host_bin`. The observed skip guards fire when that inventory has no `cmake` entry.

The evidence therefore supports an ambient-versus-clean-PATH visibility mismatch. The actual hosted CMake executable location is not logged, so this audit does not claim CMake was absent from the runner. The preflight also warns that submodules are not fully initialized, but neither missing class is skipped for submodules. All 15 population omissions are explained by the two CMake class-setup skips; no unexplained dynamic-generation or submodule population gap remains. See [the exact frozen source excerpts](w09_a03-skip-source-evidence.json).

## All 23 skip events

Reason A: `CMake is required for the actual launcher integration fixture`.
Reason B: `CMake identity is required for the reviewed recipe metadata fixture`.

| Event | Exact method or class | Reason |
|---|---|---|
| method | `test_p06_dependency_build.DependencyBuildTests.test_actual_cmake_records_static_archive_index_and_shared_link_only` | A |
| setUpClass | `test_p06_dependency_option_controls.ActualGeneratedOptionControls` | A |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_cmake_archiver_and_indexer_cannot_bypass_retained_wrappers` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_cmake_cannot_enable_fetches_even_with_matching_configure_arguments` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_cmake_cannot_select_another_local_fetched_source` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_cmake_language_pic_and_selected_library_modes_cannot_change` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_extension_compiler_and_linker_selection_remain_fixed` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_extension_map_substitution_reaches_its_exact_link_recipe` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_external_and_standard_fmt_changes_update_declared_and_invoked_settings` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_positive_fixture_reaches_complete_outer_recipe_validation` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_selected_cmake_compiler_make_and_link_map_cannot_change` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_softfloat_archiver_and_archive_mode_cannot_change` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_softfloat_compiler_substitution_reaches_reviewed_launcher_recipe` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_softfloat_round_odd_and_fast_division_removal_reach_recipe_gate` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_softfloat_tls_removal_changes_both_declaration_and_compile_recipe` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_softfloat_tls_replacement_changes_both_declaration_and_compile_recipe` | B |
| method | `test_p06_dependency_option_controls.OuterRecipeOptionControls.test_wrong_softfloat_specialization_changes_make_and_include_together` | B |
| setUpClass | `test_p06_dependency_receipt.ActualCMakeReviewTests` | A |
| method | `test_p06_dependency_receipt.OuterRecipeReviewTests.test_cmake_launcher_cannot_be_consistently_substituted_in_options_and_outer_argv` | B |
| method | `test_p06_dependency_receipt.OuterRecipeReviewTests.test_make_target_specialization_and_nested_job_changes_are_rejected` | B |
| method | `test_p06_dependency_receipt.OuterRecipeReviewTests.test_retained_archive_wrapper_must_execute_the_exact_recorder` | B |
| method | `test_p06_dependency_receipt.OuterRecipeReviewTests.test_reviewed_exact_command_metadata_and_wrapper_bytes_pass` | B |
| method | `test_p06_dependency_receipt.OuterRecipeReviewTests.test_unbounded_environment_resources_and_extra_fields_are_rejected` | B |

## All 15 canonical IDs omitted by class setup

### test_p06_dependency_option_controls.ActualGeneratedOptionControls

6 canonical IDs:

- `test_p06_dependency_option_controls.ActualGeneratedOptionControls.test_actual_tiny_records_and_generated_recipes_pass_without_semantic_patches`
- `test_p06_dependency_option_controls.ActualGeneratedOptionControls.test_generated_archive_and_index_commands_cannot_bypass_wrappers_after_rehash`
- `test_p06_dependency_option_controls.ActualGeneratedOptionControls.test_generated_release_and_linker_flags_reject_after_descriptor_rehash`
- `test_p06_dependency_option_controls.ActualGeneratedOptionControls.test_self_consistent_archive_argv_change_reaches_generated_recipe_join`
- `test_p06_dependency_option_controls.ActualGeneratedOptionControls.test_self_consistent_executable_substitution_reaches_selected_tool_identity`
- `test_p06_dependency_option_controls.ActualGeneratedOptionControls.test_self_consistent_map_argv_changes_reach_retained_link_map_join`

### test_p06_dependency_receipt.ActualCMakeReviewTests

9 canonical IDs:

- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_actual_generated_cache_flags_archives_and_links_pass`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_actual_shared_maps_and_equivalent_relative_loads_pass`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_changed_cmake_cache_configuration_is_rejected_after_rehash`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_changed_cmake_link_recipe_is_rejected_after_rehash`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_changed_cmake_target_flags_are_rejected_after_rehash`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_omitted_or_duplicate_generated_target_is_rejected`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_only_already_admitted_compiler_archives_are_exempt_inside_owned_roots`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_rehashed_unplanned_source_workspace_and_alias_loads_reject`
- `test_p06_dependency_receipt.ActualCMakeReviewTests.test_relative_duplicate_direct_load_rejects`

## Preserved artifacts and limits

- [Exact returned log text, gzip](w09_a03-job.log.gz). Its UTF-8 representation is 955728 bytes with SHA-256 `14bbd104e3ce5bf16f0241055b5975f417e2abb6e818f025fe8ccdeae7de1ba8`; the initial UTF-8 BOM and all newline/content bytes of that returned text are preserved.
- [Connector response envelope, gzip](w09_a03-job-log-connector.json.gz), [analysis metadata](w09_a03-log-analysis.json), [all 4,527 canonical outcomes, gzip](w09_a03-canonical-outcomes.json.gz), and [parsed method rows, gzip](w09_a03-test-rows-analysis.json.gz).
- The connector exposes decoded text rather than original HTTP transfer bytes. The retained log is an exact UTF-8 re-encoding of that returned text; transport-byte identity is not claimed.
- The original observation JSON remains unchanged. The current report appends this follow-up without replacing that earlier dated observation.
- The local corrected governance run was not touched or audited here. The native 24-process experiment remains **UNSTARTED / RESOURCE BLOCKED**. No source/workflow change, gate relaxation, rerun, cancellation, dispatch, installation, commit or push was performed.

## Next bounded action

Use the distinct corrected local harness as separately scoped evidence when it finishes. Hosted full no-skip governance remains unproven until an authorized run provides every canonical ID with an actual passing outcome and no method or class skips. Investigate the hosted clean-PATH CMake visibility before proposing a new run; this read-only audit does not change the workflow or frozen source.
