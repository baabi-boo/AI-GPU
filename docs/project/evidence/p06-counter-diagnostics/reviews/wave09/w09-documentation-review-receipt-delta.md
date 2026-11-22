# W09 documentation review — receipt-only delta

Reviewer: `/root/w09_documentation_review`, agent 53.
Review checkpoint: `2026-11-22T16:05:06.760100+00:00`.
HEAD: `142b2d6aaea2fa4226118b857514113032d2e26c`, tree `754ef8577f9a72785c0809048762c70b16cb4857`.

## Disposition

**The native and failed-host receipt facts are verified. This is an interim checkpoint, not final publication approval.** No new F2/F3 receipt defect was found. One known F1 stale-status action remains assigned to agent 56: eight narratives still say that repair review is open, while the exact repair has now completed independent review and been published. The packet README and refreshed ledger correctly distinguish that completed repair from the pending full hosted gate.

Final publication requires the actual full hosted retry receipt and its review, agent 56's final receipt prose, and final assembled accounting. This review does not treat the repair's focused tests, expected test inventory or queued retry as a full-host pass. It does not qualify counters, a warm run or any phase gate.

The original `w09-documentation-review.md` and `.json` remain unchanged at SHA-256 `102a97934c54cf6232291a079074e3b0b0d5bf2a95049a53783592c6d3704799` and `d1480f35262c0e4f09905cfdde5897ea63714777133f8eacf093dc5cd945c35b`. This is a new report covering the narrow changes after that baseline.

## Scope and method

Read every combined receipt-only hunk in the nine agent 56 narratives against the captured baseline, both preserved author notes/patches, agent 55's fourth-native audit and receipts, agent 54's completed failed-host receipt/log, the final author 59/reviewer 60 repair records, and agent 52's frozen pre-retry packet/ledger/crossreferences. Independently inspected original ZIP/JSON/log bytes, source bodies against immutable Git, protected section equality and Markdown targets. No repository files were edited; no test, discovery, replay, build or native command was executed. Standard-library data inspection did not import archived code.

## New native original: exact facts corroborated

Run **45034575685**, attempt 1, job **137245341329**, artifact **14760051170** belongs to `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, tree `061ecbddc9b321edbd70c054c8efce4d188de04f`. Its retained ZIP is **4,290,949 bytes**, **1,046 members**, SHA-256 `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb`.

Direct report/log inspection confirms seven model cases, one public-build boundary control and five public modes: **13 passing diagnostic process cases**, with 17 model and 14 public command records. Public assertions remain 1,668 / 1,176 / 1,176 / 1,173 / 1,814. Totals remain **ten constructions/disposals**, **seven terminal vectors**, **231 selector queries**, **462 successful half reads plus one failed cache half read**. All vectors retain 33 selectors, 40 components and twelve unavailable rows unqueried, with the same scoped CP 26→92 and 1,664→5,888 observations.

All **270 model and 683 public source bodies** independently match retained descriptors and immutable 4268 Git bytes. The model catalog is a subset; these counts are not 953 unique files. All 676 earlier public bodies remain byte-identical. The separately supplied manifest has 683 exact descriptors, 116,997 bytes, SHA-256 `bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`; every descriptor matches the original archive and immutable Git.

The retained current-reader receipts support the stated distinction: fixed 270 model replay passes, explicit 683 public replay passes, fixed 676 public replay rejects with `versioned source inventory: value differs`, and a wrong explicit digest rejects without fallback. This reviewer read those original receipts rather than rerunning them. No manifest or retained-source consistency claim authenticates absent binary/tool/dependency payloads or loaded dependency compilation origin.

The public design's introduction is now correctly attributed: observations were established by the corrected e5 original and independently confirmed by the separately identified 4268 original. Their source/run/archive identities remain separate. The e5 three-field pass locator and the first three native index entries remain unchanged; neither earlier failure is relabelled.

## Completed failed host original: exact facts corroborated

Run **45034575638**, job **137245340992**, at 4268 executed **3,312 distinct test IDs in 1,811.712 seconds**, with **3,310 ok, two FAIL, zero errors/skips, exit 1**. The exact retained connector-decoded UTF-8 log is 696,999 bytes with its BOM preserved, SHA-256 `1d093819f62493536a2444b6efec31a75e522e7e3a3cfc197a0a101c833160a8`. This review checked all 11 canonical receipt artifact descriptors against their files.

An independent raw-log recount finds all 3,312 unique method IDs, 3,310 successful result lines and the two failed lines. The actual ID set equals the previously retained discovery set. All 154 added methods executed; discovery is no longer being used as a substitute for the result. The four new-module outcomes are 42/43 checked replay, 39/40 public replay, 23/23 inventory integration and 48/48 source-inventory methods successful.

The two original isolation guards failed while resolving current trusted `baseline_inventory.py` because its checkout root coincided with a recorded producer pathname. Both guarded checks stopped before completion. The original remains **failed**; native 4268 success and separately passing inert replays do not alter that disposition. The concurrent local failure, clean 81ed fixture failure, 81ed native CP-assumption failure and e5 historical pass remain separately scoped.

## Published repair, pending full gate and open prose action

Local immutable commit inspection confirms that **142b2d6aaea2fa4226118b857514113032d2e26c** changes exactly two test files from 4268. Their current hashes match reviewer 60's frozen identities:

| Test source | SHA-256 |
|---|---|
| `ci/project/test_p06_counter_diagnostics_replay.py` | `c8d213737b6332a5e6c924114b3e403a2ddcea3e0a2eac2f1fd431a5f4842430` |
| `ci/project/test_p06_counter_public_replay.py` | `241299ec7abfbbafe857c9d23ea10a0350b2606b10af4d942912780068d01a5d` |

Production readers, workflows, simulator/runtime/RTL implementation and gates did not change in that commit. The retained final author scope is 89 passing affected-module tests in 139.141 seconds. Reviewer 60's distinct scopes are 8 methods/670 subtests in 4.956 seconds and 3 methods/15 subtests in 4.437 seconds. These are recorded executions by their authors/reviewer, not reruns here and not a combined full suite. The historical 87-test candidate and discovered filename-only witness bypass remain retained separately.

Reviewer findings F2-01 and F2-02 are resolved in those exact test bytes. Agent 52 clarified their explicit mapping to root-ledger aliases in the packet README; no ambiguous claim of resolving differently named findings remains.

**DOC-53-DELTA-01 — F1, high confidence, static-proof, interim open action assigned to agent 56.** These current passages still contain the earlier repair-under-review/approval-withheld status:

- `README.md:158`: pathnames coincided. A test-only repair remains under independent review; no
- `ROADMAP.md:237`: repair remains under independent review, and a clean full-suite retry is not
- `docs/project/status.md:70`: remains under independent review, with no clean full-suite retry established.
- `docs/project/status.md:227`: is still under independent review, and no clean full-suite retry is claimed.
- `docs/project/backlog.md:112`: test-only repair remains under independent review; a clean full-suite retry is
- `docs/project/phases/p06-performance.md:107`: test-only repair remains under independent review; no clean full-suite retry
- `docs/project/p06-mpm-qualification-plan.md:110`: did not complete. The test-only repair remains under independent review and
- `docs/project/p06-counter-diagnostics-audit.md:134`: The candidate test-only repair remains under independent review and is not
- `docs/project/p06-counter-diagnostics-audit.md:135`: approved. Its execution witness must enforce exact pinned code identity,
- `docs/project/p06-counter-diagnostics-handoff.md:176`: exact pinned code identity for the execution witness. Approval is withheld

Those statements are now stale beside the completed final review and published test-only checkpoint. They must be updated in agent 56's final receipt prose. This review **does not pass them as final prose**. Updating them must still distinguish completed repair review from the outstanding full-host result.

Full retry **45040805357**, job **137264592244**, remains pending in the supplied checkpoint; root's last supplied state was queued. **3,318 is the expected inventory, not an executed count or pass.** No completed retry outcome was observed or polled here. The only remaining publication delta is the actual reviewed retry result, agent 56's resulting final prose/status corrections and the final actual-task/accounting refresh. Final handoff prose should distinguish the tested 142b code checkpoint and completed documentation preparation from root's authorized final publication and remote verification, which can be reported in chat. It need not embed the final evidence commit's own SHA or require a later receipt commit to authenticate itself. Agent 52 owns the final 60/60 ledger spans; that count is not claimed at this checkpoint.

## Protected scope and accounting

The lifetime design and model-diagnostic design are byte-identical to the baseline. The public route/scenarios/terminal obligations and resource/offline contract sections are byte-identical. The qualification work sequence, arithmetic/lifetime proof and complete `Fresh matched attempt` section are also byte-identical. Warm contract/analyzer/replay, machine roadmap and protected SVG retain the exact baseline hashes.

Thus the separate seed-free binary/full managed caller/actual loaded dependency obligations remain open. The four-process preflight remains prior to the unchanged 24-process/792-launch/25,344-word matrix. Statistics, resource limits, goldens, 267→283 DSP/5% finding, P01/P05 separation, P06/P06-T01 in_progress and P06-A02/A03 open are preserved. Warm-v1 remains unconditionally blocked and all qualification/readiness/warm/acceptance claims remain false.

Agent 52's frozen pre-retry ledger has **60 actual names, six per wave across ten waves, 58 root-confirmed completed and two in progress**; final-completion remains false. Ledger SHA-256 is `21d5bd7322799bc2cf731e51938b26fe1345fcbc6c76b3bfaa8194a7755914c0`. The original 407-bound manifest clarification and historical 47-task snapshot remain intact.

After the owner finished assembly, this review checked **862 local file targets and 9 heading targets** across all 12 scoped documents, with zero missing/unmatched targets. Earlier transient not-yet-copied guard-note links were resolved before this capture. Agent 52's separate integrity receipt reports 282 retained records, 178 preserved historical originals and no metadata errors; that receipt is scoped to retention and supplies no full-host or GPU pass.

## Fixed current documentation identities

These identities bind the reviewed pre-retry checkpoint. Later actual retry/result/accounting changes require the planned narrow followup.

| File | SHA-256 |
|---|---|
| `README.md` | `d8c3e1b42c62a0a24d9e15935410ee90390c5c91de56c260c6a13b6af1ffb4f9` |
| `ROADMAP.md` | `4a605f407d9278c84cb9459f1383db31bb978dbea833ab82117815b67859983f` |
| `docs/project/status.md` | `9f4be95c92dcf789062c8731cc6c0b60680fd1946fc9c76b1679d1cd9576c517` |
| `docs/project/backlog.md` | `54dc0f210f9a3366147aa897dc466f0222277c18e46d30731404b63555e28e18` |
| `docs/project/phases/p06-performance.md` | `751abffc3400b4a47b7a6248eeda5b451a32330efea8dcf5fae4e600cb03bca3` |
| `docs/project/p06-mpm-qualification-plan.md` | `b964a80e1b5daa9ff4a7e0ed5f8864bee361eaf555e02255c1fd470eb6fe449e` |
| `docs/project/p06-counter-diagnostics-audit.md` | `9693d68e15c4aa53d58f9e74fe58cf01981ed32f70db9f8468819203b4f49284` |
| `docs/project/p06-counter-diagnostics-handoff.md` | `bfc88efa59e8f49123e3931d260fac85858c64a997891657745e32bd9f649181` |
| `docs/designs/simx_counter_diagnostics_v2.md` | `1d46c118522ef2c67b7046a8f9538f3fc3d305963efeff350b75898dd3b2e199` |
| `docs/designs/simx_counter_public_diagnostics_v1.md` | `3c1a387f23eca9de6fbf84d73ad42ad4aee90daf9da3518d788149c00deaa920` |
| `docs/designs/simx_counter_lifetime_v1.md` | `6b555d2920af3405c4af588de7e43d46e77619dc43dad263bf92141a60a4672d` |
| `docs/project/evidence/p06-counter-diagnostics/README.md` | `415331192c935285a3d4c7de69aebb1657366e6dbb2af6a02277cc2be90e0b6b` |

The companion JSON includes baseline/current identities, exact original-data observations, supporting receipt/source identities, protected equality checks and the unresolved interim prose locations. All original baseline reports were left unchanged.
