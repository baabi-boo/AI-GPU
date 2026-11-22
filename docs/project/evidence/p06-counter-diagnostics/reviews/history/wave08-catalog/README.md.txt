# Counter diagnostics retained reviews

This is an auditable **partial snapshot of 47 actual task names**, captured at `2026-11-22T14:47:26+00:00`. The root-maintained original ledger marks 42 tasks in waves 1–7 under completed wave states and five tasks in wave 8 under an in-progress wave state. The request was for 60 agents across ten waves; this snapshot does not assert that work is complete. The repository HEAD at capture was `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`. Each original report retains its own tested/reviewed source identity.

## Browse and verify

- [Original ledger snapshot](session-agents-wave08.json): unchanged bytes from `session-agents.json` at capture.
- [Task-to-artifact map](task-artifact-map.json): every actual captured task name, direct task-named artifacts, related reviews, integrated source pointers and explicit gaps.
- [Readable artifact inventory](ARTIFACTS.md): links, exact byte lengths and SHA-256 digests.
- [Machine-readable retained-file manifest](retained-files.json): original scratch paths, normalized repository locations, copy/reference disposition and integrity metadata.
- [Retention author handoff](wave08/w08-evidence-retention.md): exact scope and work reserved for the continuation.
- [Packet evidence overview](../README.md): native, replay, synthetic/host and governance outcomes.

The frozen intake contains 176 pre-existing scratch originals: 172 copied files totaling 9,046,841 bytes, plus four byte-identical references to evidence already retained elsewhere in this packet. The ledger, retention author's handoff and public-design author's subsequent correction are additional records. Final counts are in `retained-files.json`. Original native ZIPs, build trees, extracted archives, tools and large objects are not duplicated here.

## Actual task mapping

A retained note is original text, not a reconstructed conversation transcript. A related reviewer note is not substituted for a missing author note. File-prefix associations are navigational evidence and do not independently establish authorship. All task and wave names below come from the retained ledger.

| Actual task | Original standalone note | Task-named artifacts | Scope or explicit gap |
|---|---|---:|---|
| `w01_lifetime` | [w01-lifetime.md](wave01/w01-lifetime.md) | 1 | Original scoped report; see map for related evidence. |
| `w01_selectors` | [w01-selectors.md](wave01/w01-selectors.md) | 1 | Original scoped report; see map for related evidence. |
| `w01_public` | [w01-public.md](wave01/w01-public.md) | 1 | Original scoped report; see map for related evidence. |
| `w01_build` | [w01-build.md](wave01/w01-build.md) | 1 | Original scoped report; see map for related evidence. |
| `w01_reader` | [w01-reader.md](wave01/w01-reader.md) | 1 | Original scoped report; see map for related evidence. |
| `w01_dependency` | [w01-dependency.md](wave01/w01-dependency.md) | 3 | Original scoped report; see map for related evidence. |
| `w02_access` | [w02-access.md](wave02/w02-access.md) | 8 | Original scoped report; see map for related evidence. |
| `w02_harness` | **Missing at snapshot** | 0 | No standalone author note was established; related reviewer evidence and integrated source are not substituted author testimony. |
| `w02_runner` | **Missing at snapshot** | 0 | No standalone author note was established; related reviewer evidence and integrated source are not substituted author testimony. |
| `w02_harness_review` | [w02-harness-review.md](wave02/w02-harness-review.md) | 1 | Original scoped report; see map for related evidence. |
| `w02_access_review` | [w02-access-review.md](wave02/w02-access-review.md) | 2 | Original scoped report; see map for related evidence. |
| `w02_runner_review` | [w02-runner-review.md](wave02/w02-runner-review.md) | 2 | Original scoped report; see map for related evidence. |
| `w03_public_hooks` | [w03-public-hooks.md](wave03/w03-public-hooks.md) | 2 | Original scoped report; see map for related evidence. |
| `w03_public_main` | [w03-public-main.md](wave03/w03-public-main.md) | 2 | Original scoped report; see map for related evidence. |
| `w03_public_build` | [w03-public-build.md](wave03/w03-public-build.md) | 11 | Original scoped report; see map for related evidence. |
| `w03_public_runner` | [w03-public-runner.md](wave03/w03-public-runner.md) | 2 | Original scoped report; see map for related evidence. |
| `w03_public_build_records` | [w03-public-build-records.md](wave03/w03-public-build-records.md) | 3 | Original scoped report; see map for related evidence. |
| `w03_public_records` | [w03-public-records.md](wave03/w03-public-records.md) | 2 | Original scoped report; see map for related evidence. |
| `w04_hooks_review` | [w04-hooks-review.md](wave04/w04-hooks-review.md) | 2 | Original scoped report; see map for related evidence. |
| `w04_main_review` | [w04-main-review.md](wave04/w04-main-review.md) | 1 | Original scoped report; see map for related evidence. |
| `w04_build_ci_review` | [w04-build-ci-review.md](wave04/w04-build-ci-review.md) | 4 | Original scoped report; see map for related evidence. |
| `w04_runner_review` | [w04-runner-review.md](wave04/w04-runner-review.md) | 3 | Original scoped report; see map for related evidence. |
| `w04_build_records_review` | [w04-build-records-review.md](wave04/w04-build-records-review.md) | 3 | Original scoped report; see map for related evidence. |
| `w04_records_review` | [w04-records-review.md](wave04/w04-records-review.md) | 5 | Original scoped report; see map for related evidence. |
| `w05_lifetime_proof` | **Missing at snapshot** | 1 | Original author validation receipt exists, but no standalone author handoff was established. Independent reviewer evidence is separate. |
| `w05_native_all33_audit` | [w05-native-all33-review.md](wave05/w05-native-all33-review.md) | 4 | Original scoped report; see map for related evidence. |
| `w05_checked_replay` | [w05-checked-replay-api.md](wave05/w05-checked-replay-api.md) | 4 | Original scoped report; see map for related evidence. |
| `w05_public_replay` | **Missing at snapshot** | 0 | No standalone author note was established; independently authored tests and later reader review are separate evidence. |
| `w05_checked_replay_tests` | [w05-checked-replay-tests.md](wave05/w05-checked-replay-tests.md) | 3 | Original scoped report; see map for related evidence. |
| `w05_public_replay_tests` | [w05-public-replay-tests-handoff.md](wave05/w05-public-replay-tests-handoff.md) | 3 | Original scoped report; see map for related evidence. |
| `w06_cp_drain_fix` | [w06-cp-drain-fix.md](wave06/w06-cp-drain-fix.md) | 2 | Original scoped report; see map for related evidence. |
| `w06_checked_log_fix` | [w06-checked-log-fix.md](wave06/w06-checked-log-fix.md) | 2 | Original scoped report; see map for related evidence. |
| `w06_cp_drain_review` | [w06-cp-drain-review.md](wave06/w06-cp-drain-review.md) | 1 | Original scoped report; see map for related evidence. |
| `w06_lifetime_review` | [w06-lifetime-review.md](wave06/w06-lifetime-review.md) | 2 | Original scoped report; see map for related evidence. |
| `w06_governance_fixture_fix` | [w06-governance-fixture-fix.md](wave06/w06-governance-fixture-fix.md) | 6 | Original scoped report; see map for related evidence. |
| `w06_checked_replay_review` | [w06-checked-replay-review.md](wave06/w06-checked-replay-review.md) | 6 | Original scoped report; see map for related evidence. |
| `w07_public_replay_review` | [w07-public-replay-review.md](wave07/w07-public-replay-review.md) | 1 | Original scoped report; see map for related evidence. |
| `w07_source_inventory` | [w07-source-inventory.md](wave07/w07-source-inventory.md) | 2 | Original scoped report; see map for related evidence. |
| `w07_source_inventory_tests` | [w07-source-inventory-tests.md](wave07/w07-source-inventory-tests.md) | 2 | Original scoped report; see map for related evidence. |
| `w07_replay_inventory_integration` | [w07-replay-inventory-integration.md](wave07/w07-replay-inventory-integration.md) | 12 | Original scoped report; see map for related evidence. |
| `w07_public_replay_integration_tests` | [w07-public-replay-integration-tests.md](wave07/w07-public-replay-integration-tests.md) | 17 | Original scoped report; see map for related evidence. |
| `w07_native_public_audit` | [w07-native-public-audit.md](wave07/w07-native-public-audit.md) | 12 | Original scoped report; see map for related evidence. |
| `w08_source_inventory_review` | [w08-source-inventory-review.md](wave08/w08-source-inventory-review.md) | 1 | Original scoped report; see map for related evidence. |
| `w08_replay_integration_review` | [w08-replay-integration-review.md](wave08/w08-replay-integration-review.md) | 10 | Original scoped report; see map for related evidence. |
| `w08_public_design` | [w08-public-design-after-snapshot.md](wave08/w08-public-design-after-snapshot.md) | 8 | Original scoped report; see map for related evidence. |
| `w08_evidence_retention` | [w08-evidence-retention.md](wave08/w08-evidence-retention.md) | 1 | Author handoff added after frozen intake; no native or replay test claimed. |
| `w08_qualification_plan` | **Missing at snapshot** | 0 | Task was newly recorded and active at the frozen intake; no task artifact was then present. Later retention must append its actual output. |

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

## Shared artifacts and continuation gaps

The [observed generator](shared/build_lifetime_manifests.py) has **unverified authorship** and was not executed during retention. The [task brief](shared/COUNTER_DIAGNOSTIC_TASK.md) is planning context. The [baseline 64-test log](shared/baseline-checked.log) has no standalone source/command binding and is not an immutable-governance claim. The [earlier lifetime text](wave08/w08-lifetime-before.md) is a historical comparison snapshot, not the current design contract. Other unattributed scratch receipts remain listed explicitly in the machine-readable map.

Five captured tasks lack standalone notes: `w02_harness`, `w02_runner`, `w05_lifetime_proof`, `w05_public_replay`, and the then-active `w08_qualification_plan`. The lifetime author has a real validation JSON; the others have only the exact related artifacts described in the table/map, or no artifact yet. No missing transcript or test result has been fabricated.

The [captured public-design note](wave08/w08-public-design.md) and [subsequent author correction](wave08/w08-public-design-after-snapshot.md) are both retained. The correction updates document hashes and explains the permitted gate-name typo fix; it does not rewrite original test receipts.

The continuation must append actual remaining task artifacts and a new final ledger snapshot, preserving this partial snapshot. It must bind any later reader/governance results to their actual source revision and keep the already-retained failed native/host attempts. All diagnostic qualification, readiness, warm execution and acceptance flags remain false, and `P06-WARM-RV64-MPM-HIGH-HALF` remains unconditional.
