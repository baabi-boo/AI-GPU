# Counter diagnostics retained reviews

The current [actual-task ledger](../agent-ledger.json) records **54 distinct task names** and **51 root-confirmed completed tasks** at `2026-11-22T15:05:32+00:00`. 3 recorded tasks remain in progress; 6 of the requested 60 tasks are not yet recorded. Only names and completion states actually present in the root-maintained ledger are represented. The request is for six distinct tasks per wave across ten waves; the final-completion flag is `false`.

The unchanged [47-task historical snapshot](session-agents-wave08.json), captured at `2026-11-22T14:47:26+00:00`, retains 42 tasks under completed wave 1–7 states and five under the then-active wave 8 state. Its [historical catalog](history/wave08-catalog/retained-files.json) and [historical task map](history/wave08-catalog/task-artifact-map.json) remain intact. Later status is recorded separately; original reports retain their own tested/reviewed source identities.

## Browse and verify

- [Actual task ledger](../agent-ledger.json): wave, slot, exact task name, assigned purpose, root-confirmed state and explicit evidence availability.
- [Current task-to-artifact map](task-artifact-map.json): direct originals, related independent reviews, integrated source pointers and missing notes.
- [Current root-ledger snapshot](ledgers/session-agents-54-tasks-1d165ac4b3cd.json): unchanged captured source for current task names and states.
- [Readable artifact inventory](ARTIFACTS.md) and [SHA-256/byte manifest](retained-files.json): source filenames, normalized retained paths, later original versions and inert packaging.
- [Integrity receipt](integrity-receipt.json) and [reproducible verifier](wave09/w09-evidence-finalization-verify.py): byte/hash, ledger, membership, link and sensitive-pattern checks; no native build or full-suite execution.
- [Wave 8 retention handoff](wave08/w08-evidence-retention.md) and [packet evidence overview](../README.md): scope, original failures and execution/qualification distinctions.

The frozen intake had 176 pre-existing scratch originals: 172 copied files totaling 9,046,841 bytes, plus four existing identical packet references. Subsequent original notes, receipts, audit scripts and catalog/ledger snapshots are appended with separate identities. Current counts are in `retained-files.json`; generated catalogs are excluded from original-evidence counts. Original ZIPs, build trees, extracted archives and downloaded tools are not duplicated here.

## Actual task mapping

A retained note is original text, not a conversation transcript. Related independent reviews do not replace missing author notes. Task and wave names come from the captured root ledger; filename associations alone do not establish authorship or completion.

| Wave/slot | Actual task and purpose | Root state | Original standalone note | Direct artifacts | Related reviews |
|---|---|---|---|---:|---:|
| 1/1 | `w01_lifetime` — Audit terminal ownership and context-lifetime proof prerequisites. | completed | [w01-lifetime.md](wave01/w01-lifetime.md) | 1 | 0 |
| 1/2 | `w01_selectors` — Audit all 33 available selectors and actual backing components. | completed | [w01-selectors.md](wave01/w01-selectors.md) | 1 | 0 |
| 1/3 | `w01_public` — Audit the native public-runtime diagnostic gap and failure route. | completed | [w01-public.md](wave01/w01-public.md) | 1 | 0 |
| 1/4 | `w01_build` — Audit the all-selector and public diagnostic build/evidence route. | completed | [w01-build.md](wave01/w01-build.md) | 1 | 0 |
| 1/5 | `w01_reader` — Audit requirements for an inert diagnostic retained-data reader. | completed | [w01-reader.md](wave01/w01-reader.md) | 1 | 0 |
| 1/6 | `w01_dependency` — Audit pinned Ramulator finalization source and its counter effects. | completed | [w01-dependency.md](wave01/w01-dependency.md) | 3 | 0 |
| 2/1 | `w02_access` — Implement diagnostic access to actual backing-counter storage. | completed | [w02-access.md](wave02/w02-access.md) | 8 | 0 |
| 2/2 | `w02_harness` — Implement the all-selector model diagnostic harness. | completed | **Missing original note** | 0 | 1 |
| 2/3 | `w02_runner` — Extend the all-selector execution runner and its host checks. | completed | **Missing original note** | 0 | 2 |
| 2/4 | `w02_harness_review` — Independently review the model harness implementation. | completed | [w02-harness-review.md](wave02/w02-harness-review.md) | 1 | 0 |
| 2/5 | `w02_access_review` — Independently review backing access and its build integration. | completed | [w02-access-review.md](wave02/w02-access-review.md) | 2 | 0 |
| 2/6 | `w02_runner_review` — Independently review the all-selector runner and host tests. | completed | [w02-runner-review.md](wave02/w02-runner-review.md) | 2 | 0 |
| 3/1 | `w03_public_hooks` — Implement test-only public diagnostic hooks and observations. | completed | [w03-public-hooks.md](wave03/w03-public-hooks.md) | 2 | 0 |
| 3/2 | `w03_public_main` — Implement actual public-runtime diagnostic process cases. | completed | [w03-public-main.md](wave03/w03-public-main.md) | 2 | 0 |
| 3/3 | `w03_public_build` — Implement the isolated public diagnostic build contract. | completed | [w03-public-build.md](wave03/w03-public-build.md) | 11 | 0 |
| 3/4 | `w03_public_runner` — Implement the public diagnostic execution runner and host tests. | completed | [w03-public-runner.md](wave03/w03-public-runner.md) | 2 | 1 |
| 3/5 | `w03_public_build_records` — Implement strict public build-record validation and tests. | completed | [w03-public-build-records.md](wave03/w03-public-build-records.md) | 3 | 1 |
| 3/6 | `w03_public_records` — Implement the pure public observation verifier and tests. | completed | [w03-public-records.md](wave03/w03-public-records.md) | 2 | 1 |
| 4/1 | `w04_hooks_review` — Independently review public diagnostic hooks. | completed | [w04-hooks-review.md](wave04/w04-hooks-review.md) | 2 | 0 |
| 4/2 | `w04_main_review` — Independently review the public diagnostic main and controls. | completed | [w04-main-review.md](wave04/w04-main-review.md) | 1 | 4 |
| 4/3 | `w04_build_ci_review` — Independently review public build and CI integration. | completed | [w04-build-ci-review.md](wave04/w04-build-ci-review.md) | 4 | 0 |
| 4/4 | `w04_runner_review` — Independently review the public execution runner. | completed | [w04-runner-review.md](wave04/w04-runner-review.md) | 3 | 0 |
| 4/5 | `w04_build_records_review` — Independently review public build-record parsing. | completed | [w04-build-records-review.md](wave04/w04-build-records-review.md) | 3 | 0 |
| 4/6 | `w04_records_review` — Independently review public records, DMA evidence and caller lifetime. | completed | [w04-records-review.md](wave04/w04-records-review.md) | 5 | 0 |
| 5/1 | `w05_lifetime_proof` — Author the conditional lifetime source argument and manifests. | completed | **Missing original note** | 1 | 2 |
| 5/2 | `w05_native_all33_audit` — Independently audit the original seven-cell native model archive. | completed | [w05-native-all33-review.md](wave05/w05-native-all33-review.md) | 4 | 0 |
| 5/3 | `w05_checked_replay` — Implement the inert all-selector diagnostic replay reader. | completed | [w05-checked-replay-api.md](wave05/w05-checked-replay-api.md) | 4 | 0 |
| 5/4 | `w05_public_replay` — Implement the inert public diagnostic replay reader. | completed | **Missing original note** | 0 | 3 |
| 5/5 | `w05_checked_replay_tests` — Author independent all-selector replay rejection tests. | completed | [w05-checked-replay-tests.md](wave05/w05-checked-replay-tests.md) | 3 | 0 |
| 5/6 | `w05_public_replay_tests` — Author independent public replay tests and preserve skipped coverage. | completed | [w05-public-replay-tests-handoff.md](wave05/w05-public-replay-tests-handoff.md) | 3 | 0 |
| 6/1 | `w06_cp_drain_fix` — Repair CP terminal observations without assuming unsupported head writeback. | completed | [w06-cp-drain-fix.md](wave06/w06-cp-drain-fix.md) | 2 | 0 |
| 6/2 | `w06_checked_log_fix` — Reject mixed-result and contradictory checked diagnostic logs. | completed | [w06-checked-log-fix.md](wave06/w06-checked-log-fix.md) | 2 | 0 |
| 6/3 | `w06_cp_drain_review` — Independently review the CP terminal-observation repair. | completed | [w06-cp-drain-review.md](wave06/w06-cp-drain-review.md) | 1 | 0 |
| 6/4 | `w06_lifetime_review` — Independently review the conditional lifetime source argument. | completed | [w06-lifetime-review.md](wave06/w06-lifetime-review.md) | 2 | 0 |
| 6/5 | `w06_governance_fixture_fix` — Isolate synthetic interpreter observations in the host fixture. | completed | [w06-governance-fixture-fix.md](wave06/w06-governance-fixture-fix.md) | 6 | 0 |
| 6/6 | `w06_checked_replay_review` — Independently review checked-log repair and all-selector replay. | completed | [w06-checked-replay-review.md](wave06/w06-checked-replay-review.md) | 6 | 0 |
| 7/1 | `w07_public_replay_review` — Independently review public replay and identify stale schema mutations. | completed | [w07-public-replay-review.md](wave07/w07-public-replay-review.md) | 1 | 2 |
| 7/2 | `w07_source_inventory` — Implement the explicit externally pinned source-inventory helper. | completed | [w07-source-inventory.md](wave07/w07-source-inventory.md) | 2 | 0 |
| 7/3 | `w07_source_inventory_tests` — Author independent source-inventory parser and rejection tests. | completed | [w07-source-inventory-tests.md](wave07/w07-source-inventory-tests.md) | 2 | 0 |
| 7/4 | `w07_replay_inventory_integration` — Integrate explicit source inventories into both inert readers. | completed | [w07-replay-inventory-integration.md](wave07/w07-replay-inventory-integration.md) | 12 | 0 |
| 7/5 | `w07_public_replay_integration_tests` — Repair schema mutations and run genuine-original public replay coverage. | completed | [w07-public-replay-integration-tests.md](wave07/w07-public-replay-integration-tests.md) | 17 | 0 |
| 7/6 | `w07_native_public_audit` — Independently audit corrected and failed original native/public packets. | completed | [w07-native-public-audit.md](wave07/w07-native-public-audit.md) | 12 | 0 |
| 8/1 | `w08_source_inventory_review` — Independently review source-inventory enforcement and tests. | completed | [w08-source-inventory-review.md](wave08/w08-source-inventory-review.md) | 1 | 0 |
| 8/2 | `w08_replay_integration_review` — Independently review both reader integrations and rejection checks. | completed | [w08-replay-integration-review.md](wave08/w08-replay-integration-review.md) | 10 | 0 |
| 8/3 | `w08_public_design` — Document the implemented public diagnostics and conditional CP argument. | completed | [w08-public-design-after-snapshot.md](wave08/w08-public-design-after-snapshot.md) | 8 | 1 |
| 8/4 | `w08_evidence_retention` — Preserve original task evidence and the frozen 47-task snapshot. | completed | [w08-evidence-retention.md](wave08/w08-evidence-retention.md) | 6 | 0 |
| 8/5 | `w08_qualification_plan` — Update the remaining measurement qualification and warm-caller plan. | completed | [w08-qualification-plan.md](wave08/w08-qualification-plan.md) | 1 | 0 |
| 8/6 | `w08_governance_review` — Independently reconcile historical hosted governance and fixture repair. | completed | [w08-governance-review.md](wave08/w08-governance-review.md) | 2 | 0 |
| 9/1 | `w09_project_status` — Update project-facing status while preserving unearned acceptance gates. | completed | [w09-project-status.md](wave09/w09-project-status.md) | 1 | 0 |
| 9/2 | `w09_audit_handoff` — Document diagnostic audit conclusions and the next qualification handoff. | completed | [w09-audit-handoff.md](wave09/w09-audit-handoff.md) | 1 | 0 |
| 9/3 | `w09_lifetime_dependency_review` — Independently review the lifetime/dependency argument and its provenance limits. | completed | [w09-lifetime-dependency-review.md](wave09/w09-lifetime-dependency-review.md) | 3 | 0 |
| 9/4 | `w09_evidence_finalization` — Preserve later originals, repair inert packaging and derive actual task/evidence ledgers. | in_progress | [w09-evidence-finalization.md](wave09/w09-evidence-finalization.md) | 2 | 0 |
| 9/5 | `w09_documentation_review` — Independently review final narrative documentation, evidence claims and qualification boundaries. | in_progress | **Missing original note** | 0 | 0 |
| 9/6 | `w09_hosted_checkpoint_review` — Independently review the later hosted governance checkpoint and preserve actual result evidence. | in_progress | **Missing original note** | 6 | 0 |

## Retained historical errors, failures and limitations

The original `w04-build-records-review.md` contains a prose typo reversing the runtime/stub and backend/hook library names. It remains unchanged. The correct mapping is:

| Artifact | Actual contents |
|---|---|
| `libchecked-simx.so` | 44 reused model/access objects |
| `libvortex.so` | 14 runtime/stub objects |
| `libvortex-simx.so` | Three backend objects plus `public_hooks.o` (four objects); the five Processor wrappers are applied at this backend link |
| `checked_public_test` | `main.o`, linked with its declared libraries |

See the [original erroneous note](wave04/w04-build-records-review.md), the [independent native/public artifact audit](wave07/w07-native-public-audit.md), and the [public diagnostic contract](../../../../designs/simx_counter_public_diagnostics_v1.md). This index corrects the prose while preserving the source note's bytes.

The early checked-replay negative test and its contradictory-log follow-ups remain in [the wave-5 note](wave05/w05-checked-replay-tests.md) and [wave-6 repair evidence](wave06/w06-checked-log-fix.md). The public replay's earlier 29 success-dependent methods were genuinely not run, as retained in [its early handoff](wave05/w05-public-replay-tests-handoff.md). The later [stale schema mutation finding](wave07/w07-public-replay-review.md), [pre-intake partial handoff](wave07/w07-public-replay-integration-tests-before-genuine-intake.md), [test-delta review](wave07/w07-public-replay-test-delta-review.md), and [complete genuine-original replay handoff](wave07/w07-public-replay-integration-tests.md) remain distinct.

The W08 reviewer initially wrote an incorrect expected count of 36 reused model objects; the original packet's count is 44. The [initial failure log](wave08/w08-replay-integration-review-initial.log), [initial receipt](wave08/w08-replay-integration-review-initial.json), and [final corrected review](wave08/w08-replay-integration-review.md) are all retained. A later pass never deletes a failed attempt.

Original notes retain contemporaneous pending claims, command paths and spelling. Their scratch paths are historical provenance, not portable paths to execute. Use this index for the normalized retained locations. Exact configuration, tested source and omission statements remain in the original notes; retention does not upgrade them to qualification or human approval.


The raw CP tail-register pair is staged low plus committed high; it is not independently a complete committed-tail observation. The three backend objects plus `public_hooks.o` make four objects in `libvortex-simx.so`. Earlier author text, including the wave 8 retention handoff's older three-object wording, remains unchanged; these current indexes state the correction.

### Historical lifetime-manifest status

The unchanged [lifetime source manifest](../lifetime-source-manifest.json) is a `407ab9f`-bound source-audit snapshot. Its `observed_native_evidence` describes the earlier seven-cell model packet. Its `public_diagnostic_checkpoint` and `remaining_obligations[0]` predate the corrected public-native pass at `e5f1524`, run `45031746149`; those fields retain historical status. The `phase_state` spelling `P06-T01-A02/A03` is an original typo and must be read against the actual open gates **P06-A02/P06-A03**. The manifest bytes are preserved. Actual seed-free measurement qualification, complete warm-caller qualification, loaded dependency provenance and performance acceptance remain open.

## Shared records, missing notes and continuation

The [observed generator](shared/build_lifetime_manifests.py) retains unverified authorship. The [task brief](shared/COUNTER_DIAGNOSTIC_TASK.md) is planning context, and the [baseline 64-test log](shared/baseline-checked.log) lacks a standalone source/command binding. The [earlier lifetime text](wave08/w08-lifetime-before.md.txt) preserves its original filename `w08-lifetime-before.md` and exact bytes in inert packaging: its designs-relative links are historical text, not current navigation.

The frozen intake's missing qualification-plan note is now supplied by its [actual later author note](wave08/w08-qualification-plan.md). The historical gaps for `w02_harness`, `w02_runner`, `w05_lifetime_proof` and `w05_public_replay` remain explicit. The lifetime author has a real validation JSON. Related independent reviews are indexed separately, and no missing author testimony or conversation transcript is reconstructed. Any other currently missing note is listed in the task ledger.

The [captured public-design note](wave08/w08-public-design.md) and [subsequent author correction](wave08/w08-public-design-after-snapshot.md) both remain unchanged. The [root change-impact receipt](shared/checkpoint4-change-impact.json) records the actual base-to-published automated R2 classification; the continuation conservatively retained independent R3 review for contract/enforcement changes. It is a root receipt, not an agent-authored note.

Append only actual later outputs and completion confirmations. Preserve every historical snapshot, failed or skipped attempt, and source-specific receipt. All diagnostic qualification, readiness, warm execution and acceptance flags remain false. `P06-WARM-RV64-MPM-HIGH-HALF` remains unconditional.
