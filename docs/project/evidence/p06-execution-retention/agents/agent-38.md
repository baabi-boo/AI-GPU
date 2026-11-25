# Agent 38 — cross-layer writer accounting review

## Scope and verdict

Independent read-only review of acquisition `run()`, supervisor `execute()` / `_observe_stage()`, and hosted `writers_finished()` / `observed_native_execution()` / closeout. Read BRIEF, AGENTS, relevant canonical status/roadmap/backlog/acceptance, the automation contract, reports 01/02/04/07/08/15, current regressions, and underlying bounded/native command accounting. Base HEAD: `622662ad9cece6da4e3375be7e977dbe04cde862`.

**No new reachable F2/F3 defect demonstrated.** No repository changes, native execution, acquisition, strict suite, encryption, publication, or repeat test run. The three operational helper hashes below match `validation/operational-source-freeze.json` and Agent 15's independently reviewed cancellation version.

## State table

“Eligible” means only writer accounting permits attempted partial retention; source checks, tools, recipient, capacity, packaging and encryption must independently succeed.

| Situation | Observed launch / cleanup | Hosted native disposition and retention |
| --- | --- | --- |
| Acquisition or supervisor prelaunch checkpoint fails | Appended row becomes `false` / `true`; executor not entered | `not_run`; eligible if every preceding writer resolved; no child file invented |
| Started child returns failure and finishes cleanup | `true` / `true`; original status/log/report retained | Finished, matching supervisor observation preserves `not_run`, `run`, or `unknown`; partial retention eligible, attempt failed |
| Executor raises without returning its observation | `null`; no completed cleanup observation | Hosted `unknown`; packaging/encryption blocked even when child files exist |
| Required stage/command inventory absent or non-list | Writer completion cannot be reconstructed | Guard false; no borrowed native certainty or retention |
| Supervisor or command-producing child receipt nonterminal | Child completion unresolved | Guard false; disposition cannot authorize retention |
| Finished supervisor has wrong revision/contract | Writers may independently be finished | Native `unknown`; partial retention can remain eligible, never qualification |
| Selected live/retained helper source changes before failure closeout | Selected-source stability fails | No borrowed disposition; packaging/encryption source checks block execution |
| Any outer row or started nested command lacks completed cleanup | Writer completion unresolved | Guard false; retention blocked |
| Failed hosted attempt observes finished native `run` | Writer guard and exact supervisor binding pass | Native stays `run`; final outcome stays `fail`, orchestration/qualification remain false |

Explicit empty inventories are valid for attempts that stopped before children. Preparation legitimately lacks command/state fields; dependency-build and qualified-warm do not receive this exception.

## Cross-layer reasoning

The new catches enclose only the prelaunch checkpoint. They cannot intercept an error raised inside `run_bounded`, so started or uncertain children cannot be reclassified as known unstarted by those catches. Completion-checkpoint errors retain the already returned launch and cleanup observations.

`native_execution=not_run` describes native workload execution, not acquisition/build/supervisor process creation. The selected native producer checkpoints `unknown` before a possible first native launch; `native_execution_state()` sets `run` on observed native start and preserves it thereafter. The supervisor's only explicit prelaunch reset applies to its single warm stage, after preparation/build stages that launch no native workload.

`_observe_stage()` may retain a child disposition even after monitor failure. Hosted closeout first resets a failed/uncertain supervisor to `unknown`, and borrows its disposition only after source stability and the complete writer guard succeed. Recovery changes no success boolean. Final hosted success still requires native success, packaging and encryption together; retained failure evidence does not satisfy that conjunction.

Nested `process_started=false` rows are treated as having no writer without separately requiring their cleanup field. All reachable selected producers emit `false` with `cleanup_complete=true`; no producer path emitting the contradictory pair was found. This guard is not a general validator of fabricated receipts.

## Evidence and exact identities

Existing reports supply the executed checks: Agent 07's 20 reader/10 nested-composition cases and Agent 08's two integrated review tests cover the key intersections, alongside author regressions. I inspected those tests and production control flow; **no new tests were executed or counted**. No concrete uncovered composition gap justified another scratch probe.

All paths below are under `ci/project/`; hashes were independently read using `sha256sum`.

| File | SHA-256 |
| --- | --- |
| `p06_qualified_warm_inputs.py` | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `p06_qualified_warm_run.py` | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `p06_qualified_warm_hosted.py` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `p06_managed_preflight_execute.py` | `2aa330b428852b3b0f0acc9bcc32cc464959b7f255d709f13cde310319b2fe4e` |
| `baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `test_p06_hosted_operational_failures.py` | `ad165dd0ec63cc7e0b6e547ba1b504f06f0ba3876e29aa6d75163ab442033eb9` |
| `test_p06_prelaunch_review.py` | `c02d423ca1a3533fcf5ec7fe055ff6ff5e012f5010e5d6c0fbf35309568411ae` |
| `test_p06_qualified_warm_writer_receipts.py` | `c64e6d85b9c09dbd6a92e996cfb148bc24e5c67d14f8ea4770a7faed8a05458f` |

## Remaining limits

Receipt observations are not complete descendant containment, malicious-writer defense, or recovery from persistent checkpoint failure, repeated interruption, SIGKILL or provider loss. Earlier fixture results do not qualify the final published source. Root still owns final strict qualification/publication. The 24-process/792-launch/25,344-word experiment remains unstarted; P06-A02/A03 and the separate vendor-XRT blocker remain unchanged.
