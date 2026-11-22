# P06 checked-counter diagnostic evidence

This packet retains the all-selector and public-runtime diagnostic development,
original hosted SimX artifacts, independent reviews, replay receipts and failed
attempts. It advances the counter prerequisite; it does not qualify a measurement
binary, a warm attempt or a new P06 acceptance gate. Diagnostic qualification,
readiness, full warm coverage, warm execution and acceptance remain false.
**`P06-WARM-RV64-MPM-HIGH-HALF` remains unconditional.**

The actual compiled native executions here run the SimX model and runtime in
hosted processes. They are separate from processor RTL, physical FPGA and silicon
measurements. These seeded diagnostics and directed scalar controls do not
establish the complete seed-free measurement route or a warm speedup.

## Start with the original evidence

| Evidence | Exact source or scope | Observed outcome |
|---|---|---|
| [Original all-selector archive](native/run-45026112992-attempt1.zip), [run 45026112992](https://github.com/baabi-boo/AI-GPU/actions/runs/45026112992) | `407ab9fea5e4f793a2a5088f566a87f3e631aa84`; original ZIP SHA-256 `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` | Seven native model cells pass. The [independent original-artifact review](reviews/wave05/w05-native-all33-review.md) binds the 33 available selectors and retained source/build evidence. |
| [Original failed public archive](native/run-45029135146-attempt1.zip), [run 45029135146](https://github.com/baabi-boo/AI-GPU/actions/runs/45029135146) | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`; ZIP SHA-256 `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` | Seven model cells pass; `public-normal` fails and four later public modes are blocked. The original normal check incorrectly required a published host head writeback that SimX does not provide. The failed archive and [job log](native/run-45029135146-job-137228604864.log) remain unchanged. |
| [Corrected original archive](native/run-45031746149-attempt1.zip), [run 45031746149](https://github.com/baabi-boo/AI-GPU/actions/runs/45031746149) | `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`; ZIP SHA-256 `05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276` | Seven model cells and six public-runner cases pass. The six public-runner cases are one boundary control plus five public modes. The [independent native/public audit](reviews/wave07/w07-native-public-audit.md) preserves both this pass and the prior failure. |
| [Fourth original archive](native/run-45034575685-attempt1.zip), [run 45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685) | `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`; 4,290,949 bytes; ZIP SHA-256 `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb` | Seven model cells, one public boundary control and five public modes pass: thirteen diagnostic process cases. The [independent original-packet audit](native/w10-native-checkpoint-audit.md) verifies all 1,046 members and matches 270 model/683 public source bodies to immutable Git. |

The [native index](native/index.json) records original IDs, byte counts, hashes,
report outcomes and scope. [public-runtime-pass.json](native/public-runtime-pass.json)
is an archive/revision/digest locator; its presence is not a qualification decision.
The original ZIPs contain the execution packet. Reviews and replays never replace
those originals with reconstructed successful packets.

The fourth packet's public inventory includes seven newly committed Python files
in addition to the original 676 unchanged source bodies. The independently
Git-derived [complete 683-source manifest](native/public-source-inventory-4268d2d5.json)
has 116,997 bytes and SHA-256
`bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`.
Its [derivation receipt](native/w10-native-checkpoint-audit-source-derivation.json)
keeps this external expectation separate from the archive's own descriptors.
The model and public catalogs overlap; their counts are not unique-file totals.

The supported terminal drain statement uses the recorded CP-before-disable state,
raw tail-register pair (staged low plus committed high), enabled idle status,
exact retirement and the source-backed completion/ownership argument. The pair
is not an independent complete committed-tail observation, and unsupported host
head writeback is not treated as a live retirement witness.
See the [CP repair](reviews/wave06/w06-cp-drain-fix.md), its
[independent review](reviews/wave06/w06-cp-drain-review.md), the
[public diagnostic contract](../../../designs/simx_counter_public_diagnostics_v1.md)
and the [conditional lifetime argument](../../../designs/simx_counter_lifetime_v1.md).

## Host governance and replay are separately scoped

| Evidence level | Retained evidence | Actual result and limitation |
|---|---|---|
| Concurrent local host governance | [Original local failure log](host/local-concurrent-governance-attempt.log) | 3,070 tests, 149 failures. The workspace changed during the run; this is not an immutable-checkout pass. |
| Hosted governance at `81ed687` | [Run 45029135196 job log](host/run-45029135196-job-137228604836.log) | 3,146 tests, 18 failures and six errors. The controlled fixture exposed an unpinned host interpreter observation. The production native CPython 3.12.14 pin remained unchanged. |
| Hosted governance at `e5f1524` | [Run 45031746158 job log](host/run-45031746158-job-137236633104.log) | 3,158 tests pass in 1,305.183 seconds. This immutable hosted checkout predates the later replay/source-inventory additions. It is not a full-suite result for those additions. |
| Hosted governance at `4268d2d5` | [Completed failed receipt](host/checkpoint-4268d2d/receipt.json), [original log](host/checkpoint-4268d2d/run-45034575638-job-137245340992.log) and [independent review](host/checkpoint-4268d2d/failed-review.md) | Run `45034575638`, job `137245340992`: **3,312 distinct tests; 3,310 `ok`, two failures, zero errors/skips; 1,811.712 seconds; exit 1.** This is a failed immutable hosted checkpoint. Both failures are replay-test guard pathname collisions. |
| Complete genuine-original public replay | [Wave 7 handoff](reviews/wave07/w07-public-replay-integration-tests.md) and [machine receipt](reviews/wave07/w07-public-replay-genuine-result.json) | 40 methods and 247 subtests pass against the corrected original e5 archive, with zero failures, errors or skips. Replay runs no new native execution and executes no retained code. |
| Independent inventory/replay integration review | [Wave 8 review](reviews/wave08/w08-replay-integration-review.md) and [receipt](reviews/wave08/w08-replay-integration-review.json) | Final reviewer run passes 37 methods and 110 subtests; genuine original archives, externally pinned source inventory, failed-original rejection and synthetic mutation checks remain distinct. |
| Fourth-original inert replay | [Independent replay/CLI receipt](native/w10-native-checkpoint-audit-cli-results.json), [checked result](native/w10-native-checkpoint-audit-checked-replay.json) and [public result](native/w10-native-checkpoint-audit-public-replay.json) | The checked fixed-270 route and public externally pinned complete-683 route pass. The [fixed-676 public route](native/w10-native-checkpoint-audit-public-legacy-cli.json) and wrong explicit digest reject as required. These are retained-data checks, with no new native execution or retained archive code execution. |
| Synthetic and focused host checks | [Per-task original notes and logs](reviews/README.md) | Parser mutations, mocked observations, syntax checks and dry runs establish their declared host/source properties only. They are not native execution or warm qualification. |

The [host index](host/index.json) binds governance logs and original outcomes.
The [controlled interpreter-fixture repair](reviews/wave06/w06-governance-fixture-fix.md)
explains the 81ed failure without weakening the native interpreter pin. Replay
and source-inventory implementation was later committed separately at
`4268d2d5d811063bb886cde7bd0e27e61a79c9b4`; earlier execution is not relabelled as
execution of that later tree.

The completed fourth host receipt independently reconciles all 3,312 executed
method IDs, including 154 additions over e5. Its exact retained decoded-log text
is 696,999 bytes, SHA-256
`1d093819f62493536a2444b6efec31a75e522e7e3a3cfc197a0a101c833160a8`;
root's separately fetched copy matches those bytes. Earlier pending observations
remain historical evidence alongside the completed failure.

The [hosted failure review](host/checkpoint-4268d2d/failed-review.md) and
[integrated code review](reviews/wave10/w10-integrated-code-review.md) identified
the test guards' confusion between an actual current helper pathname and a
recorded producer pathname when both checkouts occupy
`/home/runner/work/AI-GPU/AI-GPU`. Their observed failures do not show archived-code
execution or a native runtime regression. The original failed run retains its
failed outcome.

### Published test-only repair and pending full retry

Root published checkpoint `142b2d6aaea2fa4226118b857514113032d2e26c`, tree
`754ef8577f9a72785c0809048762c70b16cb4857`, changing only
`test_p06_counter_diagnostics_replay.py` and `test_p06_counter_public_replay.py`.
The [final author addendum](reviews/wave10/w10-replay-guard-fix-exec-identity.md)
and [independent exact-delta review](reviews/wave10/w10-replay-guard-review.md)
resolve reviewer findings **F2-01** (root-ledger alias
`F2-REPLAY-GUARD-PATH-COLLISION`) and **F2-02** (root-ledger alias
`F2-REPLAY-EXEC-FILENAME-WITNESS`) in the exact reviewed bytes. Exact trusted
helper-path permissions preserve producer-path denials, and compiled parser-code
identity is checked before execution. Production readers, workflows and original
native/host evidence remain outside this test-only change.

| Separately scoped repair evidence | Observed result |
|---|---|
| [Complete affected modules](reviews/wave10/w10-replay-guard-fix.log) | **89 tests pass in 139.141 seconds**, zero failures/errors/skips |
| [Independent final changed/new-method review](reviews/wave10/w10-replay-guard-review.json) | **Eight methods / 670 subtests pass** in 4.956 seconds |
| [Independent compiled-identity and genuine-original probes](reviews/wave10/w10-replay-guard-review.json) | **Three methods / 15 subtests pass** in 4.437 seconds |

The unchanged [87-test candidate note](reviews/wave10/w10-replay-guard-fix.md)
and [earlier patch](reviews/wave10/w10-replay-guard-fix.patch) remain historical.
Independent review then demonstrated a harmless forged-code marker bypass of the
filename-only test witness. The [full appended author log](reviews/wave10/w10-replay-guard-fix.log)
and [review log](reviews/wave10/w10-replay-guard-review.log) preserve that
reproduction, initial reviewer-instrumentation failures/corrections and subsequent
pre-dispatch rejection under the final repair. No historical result was erased
or silently relabelled as the final candidate.

At this retained **60-name/58-completion** checkpoint, full hosted retry
[run 45040805357](https://github.com/baabi-boo/AI-GPU/actions/runs/45040805357),
job `137264592244`, is pending; root's latest supplied state was queued. The
**expected 3,318 methods are an inventory count, not an executed pass**. No full
retry outcome is claimed, and the focused counts above are not summed into a
full-suite result. The 3,312-test failure remains unchanged while actual retry
receipt prose and final assembled-ledger certification are outstanding.

## Retained source argument and task audit trail

The [lifetime source manifest](lifetime-source-manifest.json),
[dependency source manifest](dependency-source-manifest.json) and
[dependency source bodies](dependency-source-bodies.json) bind the source argument
and pinned dependency audit. The [independent lifetime review](reviews/wave06/w06-lifetime-review.md)
records the conditional theorem and its limits. Source proof, directed terminal
observations and complete warm-caller qualification remain separate obligations.

<!-- actual-task-ledger:start -->
The unchanged lifetime manifest is a **historical `407ab9f`-bound source-audit
snapshot**. Its `observed_native_evidence` describes the original seven-cell model
packet, while `public_diagnostic_checkpoint` and `remaining_obligations[0]` predate
the later corrected public-native pass at `e5f1524`, run `45031746149`. Those fields
retain their original historical meaning. Its `phase_state` spelling
`P06-T01-A02/A03` is an original typo; the actual open acceptance gates are
**P06-A02/P06-A03**. The manifest bytes remain unchanged. Complete warm-caller
qualification, actual loaded dependency provenance, seed-free measurement
qualification and performance acceptance remain open.

The [current actual-task ledger](agent-ledger.json) records **60 distinct
task names**, of which **58 are root-confirmed completed**, at `2026-11-22T16:01:44+00:00`.
It contains 2 recorded tasks in progress and no fabricated
rows for the 0 requested tasks not yet recorded.
The six-per-wave, actual-60/ten-wave completion flag is `false`.
Each row names its purpose, actual wave/slot, root-confirmed state, direct original
evidence, related independent reviews and any missing original note. Requested
work and the presence of a note do not independently establish completion.

The [reviews index](reviews/README.md), [task map](reviews/task-artifact-map.json),
[readable inventory](reviews/ARTIFACTS.md), [byte/hash manifest](reviews/retained-files.json)
and [integrity receipt](reviews/integrity-receipt.json) cover current retention.
The **47-task historical snapshot**, captured at `2026-11-22T14:47:26+00:00`, remains
unchanged in its [original ledger](reviews/session-agents-wave08.json) and
[frozen catalog](reviews/history/wave08-catalog/retained-files.json). Later root
ledger states and actual wave 8–10 outputs are separate appended evidence.

Original-note gaps remain explicit for `w02_harness`, `w02_runner`,
`w05_lifetime_proof` and `w05_public_replay`. The lifetime author has an original
validation JSON; related independent reviews are not substituted author testimony.
The qualification-plan note missing at the frozen intake is now retained as its
[actual later author output](reviews/wave08/w08-qualification-plan.md). Other
currently missing notes and unfinished actual tasks are listed in the ledger.
No conversation transcript or missing result was reconstructed.

The historical [lifetime comparison text](reviews/wave08/w08-lifetime-before.md.txt)
is packaged as inert `.md.txt` because its original designs-relative links are
not portable from the evidence directory. Original bytes, source filename,
byte length and SHA-256 are preserved. The public-design author's
[subsequent correction](reviews/wave08/w08-public-design-after-snapshot.md) and
its original predecessor likewise remain separate unchanged records.
<!-- actual-task-ledger:end -->

### Historical library-role typo

The preserved [wave 4 build-records review](reviews/wave04/w04-build-records-review.md)
reverses the runtime/stub and backend/hook library names in one prose list. Its
original bytes remain unchanged. The actual mapping, also confirmed in the later
native/public audit and public design contract, is:

| Artifact | Correct role |
|---|---|
| `libchecked-simx.so` | 44 reused model/access objects |
| `libvortex.so` | 14 runtime/stub objects |
| `libvortex-simx.so` | Three backend objects plus `public_hooks.o` (four objects); five Processor wrappers applied at this backend link |
| `checked_public_test` | `main.o` and its declared library links |

The earlier checked-log contradiction failure, stale public schema mutation
finding, skipped success-dependent replay methods and W08 review-harness count
error are retained alongside their later corrections. A passing integrity audit
of a failed archive means the failure was faithfully verified; it does not change
the native outcome to pass.

## Remaining qualification boundary

This packet establishes its named diagnostic and retained-data consistency scope.
It does not establish an absolute bound for unobserved aggregate totals without
the conditional monotonicity/no-later-update argument, qualify seed-free benchmark
binaries, execute the complete unchanged warm matrix or accept P06-A02/A03.
Reported identities for absent object/library/tool payloads are not independent
rehashing of those payloads, and cached dependency compilation origin remains a
separate provenance limit. Accepted cold evidence and historical warm-v1 rejection
remain separately scoped. No gate, tolerance, threshold or baseline is waived.
