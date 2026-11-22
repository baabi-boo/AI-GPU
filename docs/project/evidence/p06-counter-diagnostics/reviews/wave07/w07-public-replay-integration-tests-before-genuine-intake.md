# Wave 7 public replay integration test correction

## Disposition

The concrete schema-mutation F2 in `w07-public-replay-review.md` is corrected in
`ci/project/test_p06_counter_public_replay.py`. The before-edit transformations
were reproduced as no-ops on the existing explicitly synthetic schema-2 raw
fixture. The corrected mutation code now reaches the raw parser's rejection
paths and asserts that the selected input changes.

**A successful original public replay is still pending.** The genuine
`native/public-runtime-pass.json` receipt is absent. The focused module declares
40 methods, executes and passes 11 methods / 19 subtests, and has one class skip
covering the remaining 29 original-success methods. None of those 29 methods is
claimed as an original-archive pass. Six of their mutation method bodies were
also exercised separately against synthetic raw parser fixtures, without an
archive, a fabricated success report, or native execution.

Author: `/root/w07_public_replay_integration_tests`, agent 41 of 60, wave 7.
Repository HEAD: `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`. The test file is an
untracked working-tree input, so the content identities below bind these edits.
Read `AGENTS.md`, the review policy, current P06 project state, roadmap and
acceptance requirements. Only the assigned repository test file was edited.
No reader, producer, source-inventory helper, archive or receipt was edited.
No native build, broad discovery, commit or push was performed.

## Corrections

- The raw floating-point and `NaN` cases now select the unique
  `"schema_version":2` token. A raw `Infinity` case was added. All seven raw-log
  transformations assert that they changed their input; duplicate keys, extra
  trailing text, unrelated failure output and repeated records remain rejected.
- Intended structured replacements now resolve the complete existing path before
  assignment and reject a same-type, same-value replacement. The obsolete
  `cp_after.head` therefore cannot silently become an unknown-field test.
  Intended build-line and retained-payload replacements also reject no-ops.
- The terminal CP mutation selects `head_writeback_raw`,
  `tail_register_pair_raw` and `runtime_tail`. The two tail values remain valid
  unsigned values at the lower bound while violating real retirement/tail
  accounting. Unknown CP-field coverage remains explicit in the schema test.
- DMA suppression tests corrupt each of all three words in `before`,
  `attempted` and `after`, in all three overflow modes; status rejection remains.
  This retains exact program-byte and complemented-attempt obligations.
- Teardown tests now cover both destruction records, including `reset_after`,
  completed state, post-destruction ticks/idle state and the pre-destruction
  generation.
- The original completeness method asserts schema 2 and exact per-mode checks:
  normal 1,668; immediate overflow 1,176; delayed overflow 1,176; cache overflow
  1,173; coherent terminal 1,814. The original 40 method names are unchanged.

The successful receipt remains exactly `{archive, sha256, source_revision}`.
The corrected producer still has the original 676-name source inventory, so
this suite keeps its exact original-inventory expectations. Optional external
manifests are covered by agent 40's separate integration suite, not by expanding
this receipt contract.

## Executed checks and accounting

Commands ran from the source root with `PYTHONDONTWRITEBYTECODE=1` and
`PYTHONPATH=ci/project`. The focused runner records every executed method,
successful subtest, skip event, unexecuted method and before/after source hash.

| Check | Executed / declared methods | Successful subtests | Result and scope |
| --- | ---: | ---: | --- |
| Direct raw-parser mutation probes | 8 / 8 | 108 | Pass, 3.924 seconds. Six existing mutation method bodies plus two fixture/guard controls; 116 deliberately corrupted raw observations rejected. Explicit synthetic parser data only. |
| `test_p06_counter_public_records` | 33 / 33 | 232 | Pass, 2.017 seconds. Existing synthetic raw-record suite; no native execution. |
| `test_p06_counter_public_replay` | 11 / 40 | 19 | Pass for executed scope, 0.158 seconds. One class skip accounts for 29 unexecuted original-success methods. |
| Original test method inventory comparison | 40 names before / 40 names after | — | Exact class/name inventory preserved. |

There were no test failures or errors in these three executions. Source hashes
were stable across each execution. The two historical stale byte replacements
were separately extracted from the preserved before-edit AST, returned unchanged
bytes and left schema 2 accepted; this reproduces the reported F2 rather than
rewriting its history.

The exact commands were:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 /workspace/scratch/98908dfa3444/w07-public-replay-raw-mutation-probes.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 /workspace/scratch/98908dfa3444/w07-public-replay-integration-runner.py test_p06_counter_public_records --label synthetic-raw-record-suite --log /workspace/scratch/98908dfa3444/w07-public-replay-integration-tests.log --result /workspace/scratch/98908dfa3444/w07-public-replay-raw-record-suite-result.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 /workspace/scratch/98908dfa3444/w07-public-replay-integration-runner.py test_p06_counter_public_replay --label corrected-focused-public-replay-before-genuine-intake --log /workspace/scratch/98908dfa3444/w07-public-replay-integration-tests.log --result /workspace/scratch/98908dfa3444/w07-public-replay-focused-result.json
```

The probe adapter presents five known synthetic raw records directly to the
current parser. Its minimal command/cell mapping serves only the test mutation
helpers. It contains no producer success outcome, is never serialized as an
archive and never runs `replay_archive`. Exactly the deliberately mutated mode
must fail each probe. These results do not replace original-only test execution.

## Review of all 29 original-success method assumptions

Every row below remains **pending on the genuine original archive**. “Raw probe”
means the existing mutation method body ran against synthetic parser data only.

| Method suffix after `test_` | Assumption review / available corroboration |
| --- | --- |
| `original_completeness_and_nonacceptance_are_exact` | Retains 676 sources, 14 commands, 6 cells, 9 bindings, 28 stability rows, 33 selectors and 40 components; explicitly checks five schema-2 counts. |
| `replay_never_extracts_executes_or_opens_producer_paths` | Retains data-only source mutation and IO/process guards; source inventory uses the original no-manifest route. |
| `consistency_does_not_authenticate_git_or_absent_binary_payloads` | Keeps tree-label and absent-binary identity limitations; no outcome promotion. |
| `external_digest_revision_and_prefix_are_mandatory` | External archive digest/revision and canonical prefix checks unchanged. |
| `all_producer_acceptance_flags_must_be_false` | Boolean/type rejection unchanged for report and all five raw modes. |
| `report_keys_types_and_limits_are_strict` | Exact schema-1 report contract remains distinct from schema-2 raw observations; selected replacements now guard no-ops. |
| `duplicate_report_json_keys_and_nonfinite_numbers_are_rejected` | Report-level duplicate and nonfinite insertions already change bytes; retained. |
| `command_order_resources_cleanup_and_environment_are_bound` | Command 9 is still the first public run after the nine-command build prefix; command/cell order and resource checks retained. |
| `all_nine_binding_groups_require_exact_before_after_identity` | Nine original binding groups retained; descriptor and equality mutations unchanged. |
| `all_twenty_eight_stability_rows_are_required_in_order` | Two observations for each of 14 commands remain required; fixed indices still within 28 rows. |
| `source_revision_cleanliness_and_before_after_must_agree` | Both recorded source observations still require equal, clean revision/tree records. |
| `full_source_inventory_cannot_drop_an_uncompiled_header` | Original 676-name route remains pinned and omitted-header rejection retained. |
| `retained_source_bytes_and_frozen_profile_are_verified` | Raw corruption and coherently rehashed profile change retained; payload helper now rejects no-ops. |
| `tools_interpreter_dependencies_and_paths_require_closure` | Fixed executing interpreter remains CPython 3.12.14; replacement patch version 13 is a genuine mismatch. |
| `configuration_copies_template_expansion_and_header_probe_are_bound` | RV64/p02-tfr configuration and copied source/header probes retained; no-op payload replacement is now an assertion failure. |
| `generated_tcu_must_equal_original_plus_exact_footer` | Generated-source append changes bytes and identities, preserving semantic rejection. |
| `prior_model_summary_is_recomputed_from_original_log` | Original 45-TU model and 44 reused model objects retained; actual selected compile line must change. |
| `public_summaries_cannot_replace_original_build_commands` | 19 public compiles/four links retained; replaced build summary still lacks original command evidence. |
| `public_dso_links_require_exact_object_roles_and_libraries` | All four exact link-role mutations retained; helper requires one selected command and changed bytes. |
| `all_five_processor_wraps_are_required_on_backend_dso` | All five required wraps retained; each removal must change the selected backend link. |
| `public_compilation_roles_cannot_use_other_source_or_flags` | Public/runtime/backend compile roles and guarded flags retained; each selected command must change. |
| `suppressed_dma_requires_original_ram_and_complemented_attempt` | Raw probe passed; all three words of all three observations across all three failure modes now mutated. |
| `terminal_counters_components_halves_and_clock_are_verified` | Raw probe passed; coherent nonzero high halves and 33-selector/40-component inventory avoid zero-value no-ops. |
| `terminal_requires_exclusive_ownership_retired_cp_and_destruction` | Raw probe passed with current CP fields and both destruction records. |
| `overflow_requires_original_callback_and_fresh_context_evidence` | Raw probe passed; overflow counts, suppression entry invariance, real progress, failed reads and fresh context remain bound. |
| `observation_types_keys_and_integer_bounds_are_strict` | Raw probe passed; bool/int distinctions, range checks and explicit unknown CP fields retained. |
| `public_result_duplicate_keys_numbers_and_record_boundaries_are_strict` | Raw probe passed; schema-2 token is exact and unique, every mutation changes bytes, all seven corruptions rejected. |
| `raw_observations_cannot_be_replaced_by_a_summary_only` | Original log remains mandatory and recomputed observations must match summary; summary-only mutation changes checks to 0. |
| `extra_missing_duplicate_and_unsafe_members_are_rejected` | Full member closure, canonical names, duplicate and symlink/special-member rejection retained. |

## Original evidence and coordinated reader freeze

The failed original remains
`docs/project/evidence/p06-counter-diagnostics/native/run-45029135146-attempt1.zip`,
producer `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`, SHA-256
`d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5`.
It still has a failed normal cell and four blocked modes, and full replay still
rejects `producer outcome`. No bytes or outcome were transformed into a pass.

Agent 40 froze both readers before the focused public suite ran. Its public
reader SHA-256 is
`6489dff8b39bda3d18df97fb72092fd2014d86d8c0129bcd56a13f08acd942a0`;
the diagnostics reader SHA-256 is
`4d959363229859bd1ac5f4ede4f09937b8418e50f85a1c2eab3f131956532f0b`.
The optional source helper is
`8961331993ceb112f80a83314ee7a6a3020163a89ca1b8781139c103e98f6862`.
All three identities were unchanged during this work's focused execution.

## Content identities and retained local records

| File | Before SHA-256 | After SHA-256 |
| --- | --- | --- |
| `ci/project/test_p06_counter_public_replay.py` | `0bcc97736f976849f71c981dd6cca4fb61572ca3d6f9160593f9669529926f7b` | `6d9c4c541a0e68acd021a3d2bf3ffb989ed4300b8339314e80551947498df6e0` |
| `ci/project/p06_counter_public_records.py` | `d947be071b670edcbc0b7d613860c288ee1b013f16e256679747afe0353a7e78` | unchanged |
| `ci/project/test_p06_counter_public_records.py` | `6db25cdc71e58c2458c61007e1e616fe19adf91f771cfe5cfbe398ce99bd2a84` | unchanged |
| Original failed ZIP | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` | unchanged |

The scratch directory retains the original independent review, the complete
before-edit test file, before/after JSON hash/method inventories, this report,
the append-only `w07-public-replay-integration-tests.log`, three machine-readable
execution receipts and every direct raw-parser rejection reason. The original
review was not edited; its SHA-256 remains
`eef3a8714a6d5f69306190f9f41623b358e3732d78a1b79d541a5cd96e871370`.
The bounded patch is retained as `w07-public-replay-integration-tests.patch`.
The successful receipt was still absent at the final local audit,
`2026-11-22T14:33:50.196237+00:00`.

## Remaining action and evidence limits

The corrected native producer is
`e5f152464dda5e488d6d1a030c1fcdc49b5a9701`, run `45031746149`, job
`137236632765`. Root reported it running at toolchain restore; this report does
not infer a native outcome. After independent intake confirms and pins a genuine
successful original, rerun the focused public module against the frozen readers
and retain all 40 method outcomes, subtest counts, original archive hash and raw
assertion totals. If any reader changes first, record the new reader identities
and rerun at a stable freeze.

The current results establish local test correction and raw-parser behavior
only. They establish no new native execution, complete original success replay,
qualification, readiness, acceptance, complete counter lifetime bound or warm
performance result. The independent-review request for this bounded test diff
has been sent to agent 40; no maintainer approval or waiver is claimed.
