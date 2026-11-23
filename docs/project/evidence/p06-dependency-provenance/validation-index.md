# Validation evidence index

This index reconciles evidence available at **2026-11-23 10:16:22 UTC**. It is
a checkpoint, not a claim that later working-tree changes have passed a final
integration run. Counts below describe individual runs; overlapping suites are
**not added together as unique tests**. The index itself did not execute tests,
build dependencies, launch native models, or request hosted execution.

## Revisions and evidence levels

The development base is `832ae98178d7ce9022a13f1a69d9082f909c9e0d`. The published
foundation is `5527cb062e10dfff3266022d138dd7cdf63f5e5c`, whose tree
`06beb70d004cf444488eee6e02512894c11bafef` matches locally reviewed commit
`7a2d1636c2f73e1bb71aeace455b7acaeb37c308`. The
[publication receipt](validation/foundation-publication.json) records that
equal-tree check and remote readback. The native/control readers and subsequent
corrections were still uncommitted changes at the index checkpoint. Their named
source hashes, rather than HEAD alone, identify the reviewed implementations.

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| Immutable-source inventory and selected plan | The five pinned trees, retained blob population and 406 selected translation units | Actual compilation or loading of those products |
| Real-source CMake configure | Compatibility of the fixed local-source options and expected 97-row generated compilation database | Execution of the selected dependency build targets |
| Tiny host compiler/recorder fixtures | Actual selected host operations and their retained joins, within the fixture scope | The complete 406-unit dependency build or native GPU application |
| Synthetic report/ZIP controls | The targeted reader, inventory, state and transport rules exercised by each fixture | Execution authenticity or an unstubbed successful complete original |
| A completed governance suite | Host project-tooling checks at its exact tested revision | Fresh dependency/native execution or qualification |
| A prepared host diagnostic | Sealed sources, helpers, tools and bounded recipes available for a later attempt | Any completed compile/archive/link operation |

The earlier native-lifetime result at `b4127b19a004b5aebb8d52eab9ceda0da3ff4561`
belongs to its [separate original packet](../p06-native-lifetime/README.md).
It cannot establish that this new fresh-dependency path executed.

## Completed foundation and compatibility observations

| Run | Observed result | Evidence and scope |
| --- | --- | --- |
| Post-recovery foundation | 177 tests, 49.452 s, no failures/errors/skips | [Receipt](validation/foundation-recovery.json) and [raw log](validation/foundation-recovery-tests.log); local host fixtures and source/receipt controls, not a complete dependency build |
| Recovered substitution and dependency ZIP readers | 35 tests, 3.176 s, no skips | [W04-A03](agents/w04_a03.md); includes actual tiny shared-library builds/loads and synthetic lifetime/ZIP controls. The initial 33-test run had two failures, which the report preserves |
| Workflow controls | 9 tests; separately, one failing-pipeline test | Counts recorded by the [publication receipt](validation/foundation-publication.json). These are attributed root results, not additional runs by this index |
| Selected historical compatibility | 107 tests, 55.677 s unittest duration, no failures/errors/skips | [Receipt](validation/w04_a06-compatibility.json) and [raw log](validation/w04_a06-compatibility.log); frozen historical helpers, controlled runner fixtures and inert original-archive reads. The bounded supervisor's elapsed duration is separately 56.097575 s |

The foundation 177-test result, 35-test reader/control result and later suites
overlap. The compatibility run also includes one dependency-admission test.
None of these counts is a deduplicated total across the project.

## Subsequent focused validation

| Boundary | Latest scoped result available at checkpoint | Attribution and later-change limit |
| --- | --- | --- |
| Native retained reader | 16 tests, 35.488 s, no skips | [Raw log](validation/w05-native-replay-final.log) and [W05-A01](agents/w05_a01.md). Predates W07 dependency-workspace root additions; synthetic dependency admission remains explicit |
| Separate retained control reader | 14 tests, 65.537 s, no skips | [Raw log](validation/w06-control-replay-tests.log) and [W06-A02](agents/w06_a02.md). Predates W07 workspace-root and trusted-builder inventory additions |
| Receipt and option controls | 50 tests, 5.292 s, no skips | [Completion record](validation/w06-receipt-completion.json), [final log](validation/w06-receipt-validation-final.log), and [independent read](agents/w06_a06.md). Receipt SHA-256 `437a9148f6a5db3d7a6ad477e2390f38df80c9222b6c971db82a2745b02ea3c6` still matched at the index checkpoint |
| Recorder start and cleanup | 26 tests, 4.807 s, no skips | [W07-A01](agents/w07_a01.md); 22 existing recorder tests, three new start-monitoring tests, and one earlier interruption test. Includes actual tiny child creation/readiness/cleanup, injected monitor failures, and an actual OS execution refusal. Recorder SHA-256 `a1b1fa9dd8322ce38cf688caaaa6c03de69bbc6822bb5a7aff7f6b3c8544f7e4` still matched |
| Pending-probe supervision failures | 47 tests, 57.939 s, no skips | [W07-A04](agents/w07_a04.md); synthetic supervisor receipts with actual retained files/log hashes, plus both existing probe suites. Tested probe `f5cb5e2c...`; later W08 checkpoint-write correction is outside this result |
| Dependency-workspace input boundaries | 5 tests, 11.665 s, no skips | [W07-A03](agents/w07_a03.md); ten negative cases and an admitted-support-archive positive. Real targeted validators with explicitly synthetic upstream admission; no native execution |
| Current control-reader helper trust | 2 tests, 0.010 s, no skips | [W07-A06](agents/w07_a06.md); actual builder hash/origin checking and simulated source drift reject before archive creation. The 61-module top-level local import closure was also checked statically |
| Replay CLI behavior | 3 tests, 12 subcases, 0.019 s, no skips | [W06-A05](agents/w06_a05.md); real CLI argument/intake and exclusive-output behavior; success serialization uses an explicitly synthetic replay result |
| Source staging failures | 2 tests, 0.004 s, no skips | [W07-A02](agents/w07_a02.md); actual staging implementation with controlled partial-copy and source-drift failures |
| Model map path spelling | 3 tests, 0.106 s, no skips | [W05-A05](agents/w05_a05.md); targeted semantic alias/duplicate/extra-input checks, not a full native original |
| Prepared host diagnostic controls | 7 tests, 3.490 s, no skips | [W06-A03](agents/w06_a03.md) and [raw log](host-diagnostic/review-controls.log); actual diagnostic CLI intake subprocesses and map validation, with no compiler or managed native execution |

The 50-test receipt run includes the earlier 21 option-control methods and the
expanded receipt suite; the previous 21- and 42-test observations must not be
added to it. Its [initial 50-test log](validation/w06-receipt-validation-initial.log)
records one positive-fixture assertion failure: an equivalent path spelling
changed raw map bytes. The corrected test checks the new raw digest/size and
all remaining semantic fields. W06-A04's author turn was interrupted; the root
performed the completion run and W06-A06 independently reviewed it. Attribution
is preserved in the completion record.

W08-A01 subsequently reproduced a separate first-failure reporting defect:
five test methods with seven injected cases failed when an error-checkpoint
write hid the original supervisor reason. Its [report](agents/w08_a01.md)
owns that observation. At this index checkpoint, the root had edited the probe
and substitution implementation; the earlier 47-test result did not validate
those new bytes. A later settled-candidate result must identify and cover them.

## Actual pinned inputs and configure evidence

The [source observation](source-inputs/recovery-observation.json) and
[W04-A02 independent review](agents/w04_a02.md) identify **1,294 files totaling
10,938,128 bytes** across five pinned Git trees. The selected source population
is 309 SoftFloat, 60 Ramulator, 29 yaml-cpp, seven spdlog and one extension unit.
The canonical manifest digest is
`c677abd7a1cbb78cab13c23b40a92a83be427e06c3dffa40419de92b8697cd2e`;
the canonical selected-plan digest is
`f479cc6ed3ee4d4dd7fd305bc45943af33a3a2ba9069da48eebe627c5f817570`.
These canonical digests differ from hashes of newline-terminated JSON files.

W04-A02 ran the real-source configure with CMake 3.22.6 in 0.397883 s. Its
97 database rows comprise 61 Ramulator rows, including the unbuilt executable's
main, 29 yaml-cpp rows and seven spdlog rows. **Zero selected execution receipts**
were present afterward. CMake's ordinary compiler-detection probes may execute;
the selected dependency targets did not. The report retains the configure-log
identity, but its temporary original log bytes were cleaned up.

The [host diagnostic preparation](host-diagnostic/preparation.json) seals
attempt `03`, using 18 exact helpers from published `5527cb...`, the actual
pinned inputs, and the fixed resource budgets. It records zero outer commands,
zero tool records and `outcome="not_run"`. It tests neither the later recorder
correction nor the new readers. A later diagnostic result needs its own exact
lineage and cannot be promoted to a formal hosted/native receipt.

## Results still required

At the index checkpoint, the root's full governance run was still executing in
the immutable `5527cb...` worktree. Its local log was present, but no final
`receipt.json` existed. No completion or total is inferred from partial `ok`
lines. Even a later successful result there applies to the published foundation,
not automatically to the subsequent candidate.

The last attributed hosted observation is [W07-A04](agents/w07_a04.md) at
2026-11-23 10:07:16 UTC: fresh-dependency run `45146777986`, job `137597902301`,
was queued, with no steps, log or conclusion. This index made no provider
request and infers no queue cause.

The following remain distinct obligations:

1. Freeze and validate the settled native/control candidate. W07-A06's proposed
   76-method integration population is a recommendation, not a completed run.
2. Obtain the unchanged complete fresh original: 406 actual compilations,
   three archives, two indexes and two shared links, with the full product and
   source joins, rather than only planned 413 selected operations.
3. Complete the live application/model bindings and four managed processes:
   132 launches and 4,224 exact FP32 words. Run the separate positive/always-zero
   probe and separate alternate-library control, preserving their populations.
4. Replay the complete hosted original with no semantic boundary substituted,
   externally supplied identities and independent original review. Exercise
   the complete-original global inventory/order/timing/join mutations described
   by the historical [coverage review](control-coverage.md). The later readers
   now exist; a complete original has still not been established here.

For this new evidence, `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance` and
`performance_acceptance` remain false. Complete-counter qualification,
40-component lifetime/pending-balance closure, no-wrap proof, warm performance,
P06-A02/A03, vendor XRT `hw_emu` and physical hardware retain their separate gates.

## Later settled-candidate checks

After the initial index snapshot, the [checkpoint-failure review](agents/w08_a01.md)
verified the correction with **67 tests in 70.012 seconds**, no skips. Its retained
[passing log](validation/w08_a01-checkpoint-final.log) covers the five new checkpoint
methods, 47 existing probe methods and 15 substitution methods. The original
supervisor reason remains primary when its error-checkpoint write also fails.

The subsequent [combined integration receipt](validation/candidate-integration-01.json)
and [raw log](validation/candidate-integration-01.log) record **76 tests in
130.246 seconds**, no skips, against the settled working candidate. All current
`ci/project` Python file identities match before and after that run. The seven
modules cover live admission, native replay, combined control replay, substitution,
project workspace boundaries, CLI behavior and current-helper trust. This is a
source-hash-bound working candidate result on parent `5527cb06`, not a full
governance result or an observed complete fresh original. These overlapping
methods must not be added to other focused runs as a unique-test total.

A [later provider read](validation/provider-observation-5527.json), at
2026-11-23 10:20:34 UTC, again found the foundation's fresh job queued, with no
steps or runner assignment. Its queued metadata supplies no executed result or
known queue cause.

## Published replay checkpoint and completed foundation suite

The [replay publication receipt](validation/replay-publication.json) joins local
reviewed commit `ba4deccd25b8f2cd08581af6785348e5ee0781bd` to published master
`8b71ee07392c1ed86f654b2d683d9a8d2d1f50ea`. Both have exact Git tree
`80146459e865581508315a18ffd1e11dd1a0773c`; publication used an expected-head
lease without force, followed by provider readback and local fetch. The full
governance run of that candidate was still running at this receipt checkpoint.

The earlier published foundation `5527cb062e10dfff3266022d138dd7cdf63f5e5c`
completed **4,025 tests in 2,852.987 seconds**, with no failures or skips. Its
[bounded receipt](validation/foundation-full-governance.json) and complete
[original log](validation/foundation-full-governance.log) retain exact revision,
tree, command, output identity and observed resource use. This result belongs
to the foundation tree and does not substitute for the later candidate suite
or fresh dependency/native execution.

## Actual dependency-build failure and bounded parser correction

The [first host diagnostic execution](host-diagnostic/execution-summary.json)
used the frozen foundation helpers and passed three actual selected compiles.
The fourth unit's successful GCC dependency prepass repeated `primitiveTypes.h`;
the recorder rejected that valid input list before the final compiler started.
The [execution review](agents/w09_a04.md) retains four original records, the
actual depfile and first-failure log. No archive, link, managed build or native
process ran in that failed attempt.

The correction retains raw dependency bytes and their raw token limit, then
records each normalized input name once in first-seen order. Its root-owned
[recorder/receipt run](validation/depfile-fix-record-receipt.json) passed **52
tests in 3.328 seconds**. The earlier environment-only failure is retained: the
root had omitted the already reviewed CMake directory from PATH; restoring that
explicit selection required no source workaround.

The [independent correction review](agents/w09_a06.md) reports **101 tests in
3.249 seconds**, including an actual tiny repeated-header GCC compile and inert
validation after producer files are deleted. Changed or reordered input closure,
duplicate receipt rows, oversized raw lists and existing graph/archive controls
remain rejecting. Those tests overlap other runs and supply no complete fresh
build or native result. The separately running full replay-checkpoint suite
remains pinned to the earlier `ba4deccd`/`8b71ee07` tree and does not cover this
later parser correction.

## Actual second diagnostic and map category correction

The [attempt 04 execution](host-diagnostic/execution-04-summary.json) used
published `146253db8407e21aaef70e05f3f0dd3c7f5f6d33`, whose
[publication receipt](validation/depfile-fix-publication.json) joins its tree to
the local reviewed parser correction. Actual execution passed **405 compiles,
three archives and two indexes**. Its first shared-link child exited zero, but
the record failed when an 18,084,083-byte linker map met the recorder's incorrect
16 MiB JSON-receipt cap. The parser separately used the 16 MiB command-log cap.
The existing 64 MiB per-artifact limit applies to these file payloads; no numeric
budget is increased by assigning maps to that existing category.

The [independent original review](agents/w10_a03.md) validated all 410 passing
records, source trees, partial unit population and archive/index joins while
preserving the one failed link record. The unchanged incomplete evidence still
fails complete-graph validation, with no extension compilation/link, generated
CMake capture, complete original, formal preparation or native execution. The
corrected parser's [supplemental result](host-diagnostic/execution-04-map-supplement.json)
is a separate observation, not a successful replacement for the original.

The [independent map-category review](agents/w10_a04.md) passed **91 tests in
5.220 seconds**, with no skips and 379 Python files unchanged during the run.
Its [receipt](validation/w10_a04-map-limit-tests-01.json) binds the actual
source hashes. Seven new methods exercise the size categories, independent
line/packet/symlink restrictions, separate JSON bound and a real recorded link.
The two decisive checks fail against unchanged published `146253...` helpers
for the expected old-limit reasons. This scope does not resolve the separately
observed zero-member spdlog admission boundary or establish a complete original.
