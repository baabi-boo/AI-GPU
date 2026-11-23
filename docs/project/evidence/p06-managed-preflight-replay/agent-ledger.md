# Managed-preflight replay agent ledger

**Final assignment accounting: 60 actual workers across ten waves.**
The coordinator records 59 normal completions, one substantive contribution
followed by failed final reporting turns, and 0 open or finalizing assignments.
Every requested slot has an actual assignment. This accounting does not establish
test success, native execution, approval, acceptance, or publication.

Snapshot: `2026-11-23T02:09:20+00:00`. Coordinator record SHA-256:
`a1f4b362b12ed077665970773322ef2a3e6af9adcd26bd397dd44b9c1d7996c0`. The [structured ledger](agent-ledger.json)
contains exact task IDs, dispositions, report fingerprints and authorship.
60 report files are present; 0 are missing. A report file alone is
not treated as completion. Recovery and follow-up turns add no agents.

## Ten waves and actual allocation

Each wave contains six distinct assigned workers. The coordinator is excluded.

| Wave | Work | Started | Normal completion | Contributed; final turns failed | Open / finalizing |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Audit and development-step selection | 6 | 6 | 0 | 0 |
| 2 | Reader and source-export implementation | 6 | 6 | 0 | 0 |
| 3 | Derivation, generated inputs, CI and adversarial controls | 6 | 6 | 0 | 0 |
| 4 | Independent implementation review and repairs | 6 | 6 | 0 | 0 |
| 5 | Contracts, development audit and public handoffs | 6 | 6 | 0 | 0 |
| 6 | Original evidence, plan, CI and frozen-scope review | 6 | 6 | 0 | 0 |
| 7 | Boundary review, integrity repair and CLI portability | 6 | 5 | 1 | 0 |
| 8 | Integration evidence, regression coverage and claim scope | 6 | 6 | 0 | 0 |
| 9 | Release preparation and source/evidence review | 6 | 6 | 0 | 0 |
| 10 | Final delivery verification | 6 | 6 | 0 | 0 |

## Recorded assignments

Statuses are copied from the coordinator record. Pending reviews remain open
until the coordinator records their actual final handoffs.

| Number | Actual task | Wave / slot | Status | Retained report |
| ---: | --- | --- | --- | --- |
| 1 | `w01_a01_lifetime_audit` | 1 / 1 | `completed` | [w01_a01.md](agents/w01_a01.md) |
| 2 | `w01_a02_dependency_audit` | 1 / 2 | `completed` | [w01_a02.md](agents/w01_a02.md) |
| 3 | `w01_a03_qualification_audit` | 1 / 3 | `completed` | [w01_a03.md](agents/w01_a03.md) |
| 4 | `w01_a04_original_audit` | 1 / 4 | `completed` | [w01_a04.md](agents/w01_a04.md) |
| 5 | `w01_a05_replay_security` | 1 / 5 | `completed` | [w01_a05.md](agents/w01_a05.md) |
| 6 | `w01_a06_ci_scope` | 1 / 6 | `completed` | [w01_a06.md](agents/w01_a06.md) |
| 7 | `w02_a01_replay_core` | 2 / 1 | `completed` | [w02_a01.md](agents/w02_a01.md) |
| 8 | `w02_a02_replay_build` | 2 / 2 | `completed` | [w02_a02.md](agents/w02_a02.md) |
| 9 | `w02_a03_source_export` | 2 / 3 | `completed` | [w02_a03.md](agents/w02_a03.md) |
| 10 | `w02_a04_application_commands` | 2 / 4 | `completed` | [w02_a04.md](agents/w02_a04.md) |
| 11 | `w02_a05_mutation_fixture` | 2 / 5 | `completed` | [w02_a05.md](agents/w02_a05.md) |
| 12 | `w02_a06_hosted_validation` | 2 / 6 | `completed` | [w02_a06.md](agents/w02_a06.md) |
| 13 | `w03_a01_derivation_binding` | 3 / 1 | `completed` | [w03_a01.md](agents/w03_a01.md) |
| 14 | `w03_a02_generated_headers` | 3 / 2 | `completed` | [w03_a02.md](agents/w03_a02.md) |
| 15 | `w03_a03_replay_ci` | 3 / 3 | `completed` | [w03_a03.md](agents/w03_a03.md) |
| 16 | `w03_a04_replay_contract_tests` | 3 / 4 | `completed` | [w03_a04.md](agents/w03_a04.md) |
| 17 | `w03_a05_process_rejections` | 3 / 5 | `completed` | [w03_a05.md](agents/w03_a05.md) |
| 18 | `w03_a06_archive_isolation` | 3 / 6 | `completed` | [w03_a06.md](agents/w03_a06.md) |
| 19 | `w04_a01_generated_review` | 4 / 1 | `completed` | [w04_a01.md](agents/w04_a01.md) |
| 20 | `w04_a02_application_review` | 4 / 2 | `completed` | [w04_a02.md](agents/w04_a02.md) |
| 21 | `w04_a03_build_review` | 4 / 3 | `completed` | [w04_a03.md](agents/w04_a03.md) |
| 22 | `w04_a04_source_review` | 4 / 4 | `completed` | [w04_a04.md](agents/w04_a04.md) |
| 23 | `w04_a05_ci_review` | 4 / 5 | `completed` | [w04_a05.md](agents/w04_a05.md) |
| 24 | `w04_a06_core_review` | 4 / 6 | `completed` | [w04_a06.md](agents/w04_a06.md) |
| 25 | `w05_a01_contract_packet_docs` | 5 / 1 | `completed` | [w05_a01.md](agents/w05_a01.md) |
| 26 | `w05_a02_development_audit` | 5 / 2 | `completed` | [w05_a02.md](agents/w05_a02.md) |
| 27 | `w05_a03_archive_loader_review` | 5 / 3 | `completed` | [w05_a03.md](agents/w05_a03.md) |
| 28 | `w05_a04_native_handoff` | 5 / 4 | `completed` | [w05_a04.md](agents/w05_a04.md) |
| 29 | `w05_a05_status_backlog` | 5 / 5 | `completed` | [w05_a05.md](agents/w05_a05.md) |
| 30 | `w05_a06_public_docs` | 5 / 6 | `completed` | [w05_a06.md](agents/w05_a06.md) |
| 31 | `w06_a01_original_artifact_review` | 6 / 1 | `completed` | [w06_a01.md](agents/w06_a01.md) |
| 32 | `w06_a02_native_plan_review` | 6 / 2 | `completed` | [w06_a02.md](agents/w06_a02.md) |
| 33 | `w06_a03_ci_classification` | 6 / 3 | `completed` | [w06_a03.md](agents/w06_a03.md) |
| 34 | `w06_a04_documentation_review` | 6 / 4 | `completed` | [w06_a04.md](agents/w06_a04.md) |
| 35 | `w06_a05_dependency_provenance_review` | 6 / 5 | `completed` | [w06_a05.md](agents/w06_a05.md) |
| 36 | `w06_a06_frozen_scope_review` | 6 / 6 | `completed` | [w06_a06.md](agents/w06_a06.md) |
| 37 | `w07_a01_qualification_plan_refresh` | 7 / 1 | `completed` | [w07_a01.md](agents/w07_a01.md) |
| 38 | `w07_a02_git_export_boundary` | 7 / 2 | `contributed_final_turn_failed` | [w07_a02.md](agents/w07_a02.md) |
| 39 | `w07_a03_archive_resource_boundary` | 7 / 3 | `completed` | [w07_a03.md](agents/w07_a03.md) |
| 40 | `w07_a04_git_tree_closure` | 7 / 4 | `completed` | [w07_a04.md](agents/w07_a04.md) |
| 41 | `w07_a05_git_tree_review` | 7 / 5 | `completed` | [w07_a05.md](agents/w07_a05.md) |
| 42 | `w07_a06_cli_portability` | 7 / 6 | `completed` | [w07_a06.md](agents/w07_a06.md) |
| 43 | `w08_a01_tree_repair_documentation` | 8 / 1 | `completed` | [w08_a01.md](agents/w08_a01.md) |
| 44 | `w08_a02_current_replay_workflow` | 8 / 2 | `completed` | [w08_a02.md](agents/w08_a02.md) |
| 45 | `w08_a03_full_governance_evidence` | 8 / 3 | `completed` | [w08_a03.md](agents/w08_a03.md) |
| 46 | `w08_a04_workflow_input_coverage` | 8 / 4 | `completed` | [w08_a04.md](agents/w08_a04.md) |
| 47 | `w08_a05_regression_evidence_map` | 8 / 5 | `completed` | [w08_a05.md](agents/w08_a05.md) |
| 48 | `w08_a06_claim_scope_review` | 8 / 6 | `completed` | [w08_a06.md](agents/w08_a06.md) |
| 49 | `w09_a01_source_projection` | 9 / 1 | `completed` | [w09_a01.md](agents/w09_a01.md) |
| 50 | `w09_a02_agent_ledger` | 9 / 2 | `completed` | [w09_a02.md](agents/w09_a02.md) |
| 51 | `w09_a03_native_handoff_refinement` | 9 / 3 | `completed` | [w09_a03.md](agents/w09_a03.md) |
| 52 | `w09_a04_completion_summary` | 9 / 4 | `completed` | [w09_a04.md](agents/w09_a04.md) |
| 53 | `w09_a05_recovery_evidence_review` | 9 / 5 | `completed` | [w09_a05.md](agents/w09_a05.md) |
| 54 | `w09_a06_documentation_validation` | 9 / 6 | `completed` | [w09_a06.md](agents/w09_a06.md) |
| 55 | `w10_a01_finalize_evidence_index` | 10 / 1 | `completed` | [w10_a01.md](agents/w10_a01.md) |
| 56 | `w10_a02_replay_packet_review` | 10 / 2 | `completed` | [w10_a02.md](agents/w10_a02.md) |
| 57 | `w10_a03_remaining_work_review` | 10 / 3 | `completed` | [w10_a03.md](agents/w10_a03.md) |
| 58 | `w10_a04_final_diff_review` | 10 / 4 | `completed` | [w10_a04.md](agents/w10_a04.md) |
| 59 | `w10_a05_publication_preflight` | 10 / 5 | `completed` | [w10_a05.md](agents/w10_a05.md) |
| 60 | `w10_a06_final_accounting_review` | 10 / 6 | `completed` | [w10_a06.md](agents/w10_a06.md) |

## Recovery and authorship exceptions

The six wave-1 reports were reconstructed by the coordinator from completed
audit handoffs after workspace loss. They do not claim byte-identical copies
of the lost reports, additional assignments, or new test runs. Other recovery
tags retain each assignment's narrower restoration and fresh-validation scope.

The [wave-2 core report](agents/w02_a01.md) has mixed authorship:
`assignment_report_with_coordinator_recovery_annotation`. Its historical
account and the coordinator's later recovery/version note remain distinct.

Agent 38 delivered a finding before its final and report-only turns failed
automated content screening. The [coordinator-recovered handoff](agents/w07_a02.md)
retains that disposition. The [repair author](agents/w07_a04.md) and
[independent reviewer](agents/w07_a05.md) report their own later work. The
failed final turns are not relabelled as normal completion.

Current report hashes fingerprint retained bytes; they do not prove historical
authorship, restored byte identity, test success, or independent approval.

## Refresh and finalization

1. Update the coordinator record only from actual handoffs and terminal evidence.
   Preserve the failed-turn contribution and all recovery/authorship exceptions.
2. Refresh report fingerprints after the final report edits. Require 60 unique
   task IDs and six unique actual slots in each of the ten waves.
3. Recompute summary and wave counts directly from the recorded dispositions.
   Only `completed` counts as normal completion; follow-ups add no rows.
4. Finalize the ledger only when every assignment has a documented terminal
   disposition and every report exists. This can include a failed final turn
   with its contribution and coordinator handoff preserved explicitly.
5. Retain actual test revisions, approval decisions and publication identities
   in their separate evidence. A finalized ledger does not supply those claims.
