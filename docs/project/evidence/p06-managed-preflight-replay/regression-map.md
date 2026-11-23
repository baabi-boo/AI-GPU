# Managed-preflight replay regression map

Static review at `f88cccff087671ac91507565ed61fa664b34dd67`: **14 new test files,
203 declared test methods**. These counts are neither mutation counts nor a new
passing-run claim. All 14 files and the shared mutation helper matched that
commit byte-for-byte. Executed results retain their individual revision and
scope in the [evidence index](README.md).

Table links identify files under `ci/project/test_p06_managed_preflight_*.py`;
method names omit the common `test_` prefix. “Original” means the independently
pinned successful archive; modified archives are authored fixtures.

| Boundary | Concrete controls | Evidence and limits |
| --- | --- | --- |
| Original positive and exact negative | [replay](../../../../ci/project/test_p06_managed_preflight_replay.py): `original_recomputes_population_payloads_builds_and_external_pins`; `failed_original_is_rejected_at_its_failed_outcome` | Original: four processes, 132 launches, 4,224 words. Failed original must produce exactly `report.outcome: value differs`. |
| External pins, schema, source derivation | [replay](../../../../ci/project/test_p06_managed_preflight_replay.py): `cli_requires_each_explicit_external_input`; `report_schema_unknown_fields_and_contract_are_exact`. [derivation](../../../../ci/project/test_p06_managed_preflight_derivation.py): `invalid_external_expectations_reject_before_open`; `external_digest_is_checked_before_json`; `rehashed_git_blob_mutation_reaches_blob_check` | Seven mandatory inputs; independent bytes/revision, exact schema, 999 original source bodies. Rehashed blob mutation reaches its named derivation check. |
| Exporter reads and bounds | [source_export](../../../../ci/project/test_p06_managed_preflight_source_export.py): `reads_git_bytes_and_ignores_changed_checkout_and_untracked_files`; `complete_synthetic_export_derives_origins_and_riscv_headers`; `actual_subprocess_timeout_is_enforced` | Disposable Git repositories and controlled subprocesses; the synthetic export is not the original 999-source export. |
| Complete Git root | [replay_git_tree](../../../../ci/project/test_p06_managed_preflight_replay_git_tree.py): `modified_nested_tree_bytes_cannot_keep_original_root_identity`; `git_canonical_order_modes_and_shared_object_ids_are_supported` | Actual Git identities in synthetic stores; changed nested membership rejects, valid modes/order/shared objects pass. |
| Complete application commands | [application_build](../../../../ci/project/test_p06_managed_preflight_application_build.py): `every_command_is_required_in_both_formats`; `final_host_line_alone_no_longer_establishes_application_build`. [replay_application_review](../../../../ci/project/test_p06_managed_preflight_replay_application_review.py): both methods | Original 30-command logs per format. Two review methods contain 81 same-record mutations; they are not 81 methods. |
| Backend command closure | [replay_build](../../../../ci/project/test_p06_managed_preflight_replay_build.py): `extra_command_and_same_count_unknown_command_reject`; `model_link_cannot_precede_its_object_compiles`; `valid_parallel_compile_permutations_keep_both_build_bindings` | Rehashed complete archives require 46 records and prerequisites; valid reordered 43-compilation groups pass. |
| Build stages, payloads, bindings | [replay_build](../../../../ci/project/test_p06_managed_preflight_replay_build.py): `coherently_rehashed_generated_configuration_cannot_drift`; `rehashed_binary_payload_must_match_its_frozen_artifact`; `rehashed_common_build_binding_cannot_change_worker_contract` | Stage copies/descriptors/bindings repaired before named configuration, artifact or worker-contract rejection. |
| Generated headers and flags | [generated](../../../../ci/project/test_p06_managed_preflight_generated.py): `original_four_headers_reproduce_in_all_stages_and_formats`; `original_full_generated_flags_reproduce_for_both_formats`; `coherently_rehashed_generated_header_mutation_rejects` | Four headers, three stages, two formats; 273 flags per format. Coherently changed six header copies reach independent reproduction failure. |
| Numeric and counter semantics | [replay_processes](../../../../ci/project/test_p06_managed_preflight_replay_processes.py): `forged_fp32_word_rejects_despite_matching_observation_copies`; `low_high_reply_pairing_remains_exact`; `equivalent_witness_serialization_with_repaired_copies_passes` | Raw logs, observations and hashes agree before semantic rejection; equivalent witness serialization passes. |
| Lifecycle, loader, process identity | [replay_processes](../../../../ci/project/test_p06_managed_preflight_replay_processes.py): `terminal_runtime_ownership_is_closed`; `lifecycle_counts_cannot_hide_incomplete_runs_or_disposal`; `loaded_library_inventory_and_bound_paths_are_exact`; `process_bindings_cannot_be_reassigned_or_crossed` | Named ownership, lifecycle, loader and process-binding failures; no complete component-lifetime qualification. |
| Hosted outer closure | [replay_hosted](../../../../ci/project/test_p06_managed_preflight_replay_hosted.py): `workflow_mutation_is_rejected_even_with_matching_job_digest`; `host_installation_log_is_retained_without_provenance_promotion` | Outer inventory, preparation and execution consistency. Opaque installation-log changes remain admissible without compilation-provenance claims. |
| Inert replay and path isolation | [replay_isolation](../../../../ci/project/test_p06_managed_preflight_replay_isolation.py): `original_reads_only_explicit_current_inputs_and_executes_no_payloads`; `guard_rejects_collocated_source_and_directory_relative_bypasses`; `nested_hosted_wrapper_closes_whole_archive_inventory` | Guarded original replay prohibits retained execution, binary loading, extraction and producer-path reads; guard negatives exercise bypass attempts. |
| Current helper cache boundary | [replay_archive_helper](../../../../ci/project/test_p06_managed_preflight_replay_archive_helper.py): `matching_timestamp_and_size_bytecode_is_not_executed`. [replay_generated_security](../../../../ci/project/test_p06_managed_preflight_replay_generated_security.py): `matching_timestamp_bytecode_is_not_loaded` | Disposable matching caches select harmless sentinels through ordinary loaders; managed pinned-source loading bypasses those entry points. |
| Exclusive CLI outputs | [replay](../../../../ci/project/test_p06_managed_preflight_replay.py): `cli_output_creation_is_exclusive`; `cli_failed_original_returns_the_original_failure_without_a_receipt`. [source_export](../../../../ci/project/test_p06_managed_preflight_source_export.py): `paired_output_failure_preserves_existing_and_removes_new_file` | Existing bytes survive; failed replay emits no success receipt; exporter cleans only newly created paired output. |
| CI failure propagation | [replay_ci](../../../../ci/project/test_p06_managed_preflight_replay_ci.py): `failed_original_harness_accepts_only_its_semantic_rejection`; `actual_shell_pipelines_retain_both_streams_and_propagate_failure`; `all_focused_test_groups_are_required_and_failure_reaches_exit` | Local workflow-body harnesses, controlled real Bash pipelines and mocked discovery results; not a hosted workflow run. |

## Sensitivity assessment

The [mutation helper](../../../../ci/project/p06_managed_preflight_replay_test_support.py)
repairs descriptor, binding and nested warm-log identities explicitly. Reviewed
process/build/header controls assert intended error text, not merely failure;
positive permutation/serialization controls establish that repaired fixtures
can pass. No actionable false-confidence defect was found in this bounded review.

Actual earlier acceptance is documented separately for
[headers](agents/w03_a02.md), [backend logs](agents/w04_a03.md) and
[Git root membership](agents/w07_a04.md). The application control directly
compares the historical host parser with the complete parser. Other negative
controls alone do not demonstrate old-code acceptance. Cache and tree execution
evidence has separate [cache](agents/w05_a03.md) and
[independent tree](agents/w07_a05.md) scope. Model-object bodies remain absent;
dependency compilation provenance, complete counter qualification, warm
execution and phase acceptance remain unestablished. All seven unearned claims
remain false.
