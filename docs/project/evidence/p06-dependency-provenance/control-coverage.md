# P06 dependency provenance: control coverage before hosted closure

This is the wave 4 assignment 5 read-only coverage audit against the
[handoff](../../p06-dependency-provenance-handoff.md). It maps reachable controls
to their enforcement and tests. It does not report completion of the first full
hosted original, independent native replay, or broader P06 qualification.

## Evidence levels at this audit

The [recovery validation](validation/foundation-recovery.json) records 177
passing tests. [Wave 4 assignment 2](agents/w04_a02.md) reports 21 passing receipt
tests and reconstruction of the actual pinned source manifest: 1,294 files,
10,938,128 bytes, and 406 selected translation units. Its actual bounded CMake
configure produced 97 compilation-database rows and zero selected execution
receipts. Configuration is not a completed selected dependency build.

[Wave 4 assignment 3](agents/w04_a03.md) reports 35 passing substitution/replay
tests after fixing the source-control derivation and uncertain-start handling.
The tiny host-library control really compiles and loads different libraries;
its value 42 is not the SIMX result. The managed favorable transcript used by
unit controls is synthetic. Neither establishes execution of the full pinned
dependency graph or the four-process native original.

The full selected dependency graph requires 406 compile, three archive, two
index, and two link records: **413 records**. The native original requires four
FP16/BF16 × policy processes, 132 launches, and 4,224 exact FP32 result words.
The alternate-dependency control is a separate one-process, 33-launch,
1,056-word population. These populations must remain distinguishable in the
original packet and independent review.

## Required controls and concrete enforcement

Paths below are relative to `ci/project/`. Test names identify actual tests
inspected for this audit; positive tests with reduced fixtures do not imply a
passing complete original.

| Handoff requirement | Enforcement | Meaningful existing evidence | Remaining actual hosted evidence |
| --- | --- | --- | --- |
| Favorable cached library without fresh build evidence must reject | `p06_dependency_prepare.prepare` rejects stale selected inputs; `p06_dependency_receipt.verify_document` requires the exact source, record and product graph; `p06_dependency_admission.Admission.__init__` validates the caller-pinned receipt before commands | Preparation: `test_cached_selected_product_is_rejected_even_when_status_omits_it`; admission: `test_bad_receipt_prevents_any_commands_and_native_execution`. The latter uses controlled fixtures, not a completed graph | A passing fresh 413-record packet, plus missing-build-evidence mutation of that original with its favorable native observation retained as data |
| Changed top-level or fetched source under the same cache name must reject | `p06_dependency_sources.materialize_sources`, `validate_manifest`, and `verify_sources` bind fixed Git objects, file identities, modes and exact inventory; preparation verifies checkout and input cleanliness; receipt and admission rejoin frozen sources | Sources: `test_wrong_commit_rejects_without_falling_back_to_checkout_head`, `test_changed_source_bytes_mode_or_missing_source_reject`; admission: `test_staged_product_and_nonstaged_pinned_source_drift` | Actual source manifest retained with the complete original; source substitutions must fail the source/record join even after deliberately updating the mutation packet's descriptors |
| Populated cache, old object, unexpected fetch, or post-freeze mutation must fail with the first reason preserved | Preparation rejects cached/ignored/fetched products; recorder requires fresh outputs and observes prepass/compile input stability; receipt `_verify_source_stability`; builder `stable` and `fail`; admission `verify_stable` | Preparation: `test_ignored_submodule_cache_is_rejected_before_relocation`, `test_prepopulated_fetched_sources_are_rejected`; recorder: `test_stale_object_blocks_before_any_child`, `test_header_changed_after_prepass_is_rejected`; sources: `test_unlisted_stale_object_and_unexpected_empty_directory_are_rejected` | Boundary snapshots and generated inputs from the original; real retained source-to-build evidence. Local source overrides and `FETCHCONTENT_FULLY_DISCONNECTED` do not establish OS network isolation |
| Wrong specialization, TLS/options, external fmt, compiler, archiver, or linker must reject | Recorder `_load_config` pins selected tools; receipt `_validate_record`, `_verify_compile_graph`, `_verify_outer_commands`, and `_verify_generated_build` enforce selected argv, options, generated recipes, and wrappers | Recorder: `test_wrong_tool_identity_is_rejected`; receipt: `test_make_target_specialization_and_nested_job_changes_are_rejected`, `test_changed_cmake_cache_configuration_is_rejected_after_rehash` (external fmt), `test_cmake_launcher_cannot_be_consistently_substituted_in_options_and_outer_argv`, `test_retained_archive_wrapper_must_execute_the_exact_recorder` | Full actual recipes/commands and tools. Add an explicit original-based SoftFloat TLS-option mutation: exact option checks exist, but no dedicated TLS mutation was observed in the inspected suite |
| Missing, duplicate, reordered, fabricated or echo-only command evidence must reject | Recorder `_claim_record` prevents replacing receipts; `run` records actual bounded children and outputs; receipt `_validate_record` checks child identities and outcomes; `verify_document` requires the exact global inventory, order and prerequisite timing | Recorder: `test_duplicate_invocation_cannot_replace_original_receipt`, `test_echo_only_selected_tool_cannot_supply_compilation_evidence`, `test_real_compile_observes_prepass_actual_child_and_isystem_header`; receipt: `test_missing_duplicate_reordered_or_invented_children_are_rejected`, `test_failed_not_started_or_cross_group_children_are_rejected` | Existing receipt mutations target an individual record's child list, not the actual complete 413-record inventory. Mutate missing/duplicate/reordered global records and a prerequisite timing edge on the complete original |
| Substituted archive member, stale static input, or library drift across build/link/launch must reject | `p06_dependency_binary.validate_archive` compares ordered member bytes; `validate_link_map` requires selected members/input sections and exact loads; receipt joins compile→archive/index→link→staged product; admission `validate_model`, `verify_model_stable`, `verify_stable` bind model objects and selected libraries | Binary: `test_real_object_substitution_rejects_after_valid_rearchive`, `test_missing_extra_and_reordered_members_fail_exact_join`, `test_load_only_cannot_establish_archive_consumption`; admission: `test_model_map_requires_selected_member_and_every_object`, `test_companion_map_and_object_drift_fail_before_native` | Actual 43 model-object payloads, complete dependency archives/maps, final products, model link and native loader observations; a semantically reachable object/archive/product substitution against the original |
| Actual alternate loader selection must reject despite favorable numerics | `p06_dependency_substitution.prepare_source`, `derived_source`, `verify_records`, `verify_observation`, and `Control` build a fresh different extension outside the admitted product, verify exact source derivation and original stability, then require the original loader contract's expected rejection | `test_actual_fresh_marker_library_preserves_tiny_numerics_and_is_byte_different` performs real tiny-library builds and loads; `test_same_favorable_transcript_passes_numeric_and_rejects_original_dependency` uses a synthetic managed transcript; `test_unmodified_loader_path_and_wrong_rejection_reason_fail` checks rejection specificity | Fresh actual selected GDDR6-derived extension, its real compile/link/map receipts, one actual native control process with all 33 launches/1,056 words, and exact rejection `loaded library libramulator-vortex.so: differs from the fixed contract`; retain the unchanged original dependency identities |
| Diagnostic mutation or reduced counter limit must remain rejected | Existing `p06_managed_preflight_build` production grammar remains active; dependency admission adds exact model link evidence and calls the complete application validator without replacing production guard checks | Existing managed build tests: `test_guards_reject_missing_disabled_duplicate_and_worker_override` includes reduced `SIMX_TEST_LIMIT`; `test_foreign_diagnostic_source_substitution_rejects`; `test_extra_diagnostic_object_in_model_link_rejects`; admission `test_exact_opt_in_flag_and_historical_false_claim` | Actual unchanged production build/options, complete 30-command application graph and 14-source stub; fault controls must remain outside the admitted native population |
| Earlier failure cannot be repaired by cleanup, a favorable prefix or a later process | Builder `fail` retains first failure and clears pass; managed/admission route checks final stability even after failure while retaining the primary error; substitution `Control.command` conservatively handles uncertain starts | Recorder: `test_compiler_failure_survives_later_config_failure`; admission: `test_full_matrix_final_receipt_failure_cannot_pass`, `test_earlier_failure_remains_primary_when_final_receipt_also_changes`; substitution: `test_unreturned_native_start_receipt_remains_unknown_and_retains_partial_log` | First-attempt hosted logs, start receipts, exit/supervision results and failure evidence; a replacement run must not be described as repairing an incomplete original |
| Reusable independent reader must consume bounded caller pins and inert retained bytes | Receipt `PacketReader`/`load_receipt` and replay `CachedPacket`, `verify_view`, `replay_archive` use exact schemas/inventories, external archive/receipt/source pins, bounded caches and retained payloads; existing archive reader rejects unsafe ZIP inputs | Receipt: `test_actual_compile_archive_index_and_link_pass_as_inert_data` forbids subprocess/path access to producer files; replay: `test_retained_code_commands_binaries_and_producer_paths_remain_inert`, `test_exact_source_pin_bypasses_matching_timestamp_bytecode_cache`, ZIP integrity/inventory controls | A complete original replay with no semantic verifier mocked. ZIP transport positives deliberately mock dependency semantics; `test_synthetic_transport_packet_cannot_pass_real_dependency_semantics` prevents treating that synthetic packet as an original. Complete native-original replay is separate work under assignment 1 |
| Exact bounded population and resource envelope must remain enforced | Preparation/builder/managed supervision retain existing limits; receipt `_verify_outer_commands` checks nested jobs, environment and resource metadata; managed validators require exact case/population order; separate control keeps its own count | Receipt: `test_unbounded_environment_resources_and_extra_fields_are_rejected`; substitution: `test_control_population_is_separate_and_bounded_with_exact_loader_environment`, `test_resource_block_precedes_admission_and_any_execution`; existing population test rejects partial/duplicate/reordered/relabelled cases | Actual measurements and supervisor outcomes within two jobs, one worker, 15 GiB disk reserve, 4 GiB available RAM and RSS, 120-second configure, 1,800-second build, 180-second native, 16 MiB command logs and 90-minute job ceiling |

## Concrete evidence gap to close after the first original

No new reachable enforcement bypass was demonstrated by this read-only audit.
The concrete outstanding coverage gap is **whole-original semantic mutation**.
The current positives exercise real selected-tool operations on tiny host inputs,
generated CMake fixtures, controlled managed reports, and strict ZIP transport.
They do not establish that `verify_document` accepts the complete pinned graph,
or that each global inventory/order/join rejection is reached on that graph.

Once the first complete original passes, retain it unchanged and construct
separate mutation packets for missing/duplicate/reordered global records,
compile-before-link timing, and a source/object/archive/product join. Update the
affected retained descriptors and supply an explicit digest for each mutation
as the test caller. Otherwise an outer digest rejection masks the intended
semantic control. Require the named semantic rejection and preserve the
unchanged original as the positive. This is a test of consistency under
caller-selected mutation pins, not a proposal to relax original caller pins.

The actual alternate-dependency native run is an additional required control;
the tiny numeric value and synthetic transcript cannot replace it. Complete
native-original replay must reconcile the identified run, dependency receipt,
model/backend/application/kernel products, four managed processes, separate
probe/control populations and original logs before hosted closure is claimed.

## Claim boundary

All seven fields remain false: `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance`, and
`performance_acceptance`. The 40-component lifetime/pending-balance premise,
independent complete-counter qualification, no-wrap proof, warm performance,
P06-A02/A03, P01 hardware emulation and physical hardware remain separate gates.

Even successful inert review establishes consistency of a named original. It
does not authenticate an untrusted producer, close the entire host toolchain,
or establish defense against a malicious concurrent writer. Actual execution
must come from the identified hosted run and its retained evidence.
