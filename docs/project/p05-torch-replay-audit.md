# P05 retained PyTorch evidence audit

## Starting point and selected development step

The initial audited `master` was
`f01c9d03147343d274ee0a45b71b34f004709c0e`. Personal development context was
recovered, then checked against the current repository and GitHub. The live
repository was ahead of the recovered conversation. Its
[CI run](https://github.com/baabi-boo/AI-GPU/actions/runs/45270759140) and
[governance run](https://github.com/baabi-boo/AI-GPU/actions/runs/45270759106)
were successful, with no open issues or pull requests at initial inspection.
Those selected runs did not resolve every historical acceptance obligation.

The source, roadmap, acceptance policy, backlog and recent evidence establish
the following boundaries:

| Area | Established state at this audit | Remaining work |
| --- | --- | --- |
| Numerical contract and native operators | P02 and P03 complete at their recorded scopes | Broader formats, shapes and operations require their own contracts and evidence. |
| Fixed native model | P04 accepts the bounded `16 → 8 → 4` model | Arbitrary model loading and general framework backends remain separate work. |
| Python/framework bridge | P05-A01 accepts the copying binding; scoped custom operators and successful installed runs exist | P05-A02/A03 original-artifact review and acceptance remain open. |
| Performance | P06-A01 baseline and subsequent complete counter qualification are recorded | The explicit 24-process warm experiment has not established performance or A02/A03 acceptance. |
| Hardware integration | Supplemental simulation and processor RTL evidence exist | P01-A03 vendor XRT `hw_emu` remains blocked; no physical FPGA or silicon claim follows. |

Three initial source audits found no new confirmed runtime or qualified-warm
semantic defect. They checked managed-context reservation, partial submission,
workspace leases, explicit-close ownership, Python error retention, framework
packing and the warm experiment's frozen process/binding/decision structure.
The audits do not extend native execution or performance acceptance.

The canonical primary next experiment remains P06's fresh qualified warm run.
This workspace could not meet its unchanged 15 GiB disk reserve; other checkouts
also contained unfinished delivery-workflow changes. Those edits were preserved
in place. An isolated `master` checkout was used for the independently actionable
P05 task already identified in the backlog.

**The selected implementation is an inert semantic reader for original P05
installed PyTorch artifacts.** The existing bounded ZIP reader could establish
container integrity, but the observation validators required the original live
runner's directories. That prevented the same numerical, lifecycle and tensor
checks from being used directly in an independent relocated review.

## Implemented boundary

The [replay contract](../designs/torch_archive_replay_v1.md) keeps live installation
validation separate from retained-data reconciliation. The shared archive reader
remains unchanged. A replay accepts an independently selected original digest,
execution revision and format, checks retained data, and returns only after the
original archive and trusted reader inputs pass final stability checks.

The implementation has four responsibilities:

1. Preserve the original live validators while exposing explicitly named
   retained-data entry points. Numerical, dispatch, lifecycle, raw-log and
   tensor predicates remain shared. The retained entry points receive immutable
   request and installed-file identity facts from the complete archive reader.
2. Reconstruct native comparisons from frozen fixtures and raw P03/P04 logs.
   Reconcile compiler/build bindings, source retention, complete commands,
   model intermediates, actual operands/results, cleanup and derived counts.
3. Join retained first-party wheel/source/install bytes, bundle artifacts,
   interpreter receipts and framework inventories without opening recorded
   producer paths. Distinguish actual retained bytes from receipt-only evidence.
4. Check the complete original's report, command, source, copy and member
   relationships. Copies contribute no additional launches. Supplementary
   host-fault files remain explicitly scoped and do not become new native work.

Archived Python, scripts, libraries, executables and wheels are never imported,
executed or extracted. Replay reports `native_execution="not_run"`,
`retained_code_executed=false`, `acceptance_claimed=false` and
`phase_acceptance=false`. It cannot authenticate an arbitrary producer or grant
acceptance by itself.

## Independent originals and scope

The [intake record](evidence/p05-torch-replay/intake.json) independently pins the
FP16 and BF16 originals from
[run 45244780331, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45244780331)
at execution revision `c0b44ce64665fe11895f869eea8c38c9b820d6f7`. Both downloaded
ZIPs matched GitHub's recorded SHA-256 digests and sizes. The originals remain
unchanged throughout review.

Each original contains 16 framework calls and 36 framework-route launches,
36 native comparison launches, and 36 plain Python launches: **108 distinct
recorded launches per format**. Native/Python packet copies are byte-equal and
add zero executions. Across both originals the recorded population is 32
framework calls, 72 framework-route launches and 216 distinct launches.
Those numbers describe the historical executions, not work performed by replay.

The first published live-validator refactor also produced fresh hosted native
evidence at `c6fb039e706e812b6b3f4d2a5db1828076fe50df`:
[Installed PyTorch run 45349805332](https://github.com/baabi-boo/AI-GPU/actions/runs/45349805332),
[Installed Python run 45349805128](https://github.com/baabi-boo/AI-GPU/actions/runs/45349805128),
and [Native Model run 45349805244](https://github.com/baabi-boo/AI-GPU/actions/runs/45349805244)
all completed successfully. Both fresh PyTorch originals matched their provider
digests and passed the complete public replay, with 663 members and 108 recorded
launches each. The hosted jobs supply new execution evidence for the refactor;
the separate replay checks retained consistency and executes no native work.
The `c0b44ce6` and `c6fb039e` populations remain separate execution revisions.

First-party installed bytes, the bound Vortex wheel and bundle artifacts are
retained. Full third-party wheel/payload bytes, interpreter/seed bytes and some
generated metadata are absent. Their locked descriptors and before/after
inventories support retained consistency, not a fresh byte-level reconstruction
of everything installed on the original host. The reader states these limits.

## Validation and independent findings

The first live/retained seam passed 80 focused tests. After preserving the final
request-validation order, its 40 affected tests passed again. An independent
review compared 15 baseline/current live behaviors, checked that the shared
semantic bodies remained AST-identical, and rejected 14 additional attacks.
Those overlapping selections are not added into a unique-test total.

The assembled implementation then passed **520 integrated P05 tests in
127.900 seconds**, with no failures, errors or skips and identical before/after
source hashes. Both original archives also passed the complete command-line
reader, covering all 663 members in each original. These results identify the
pre-hardening implementation by source manifests; later fixes require their own
affected validation and original replays.

Independent review subsequently found concrete consistency gaps in that first
implementation:

| Finding | Concrete consequence | Required correction |
| --- | --- | --- |
| Native retained-source membership could shrink | A required application source could be removed while declarations and copied packets were adjusted consistently. | Require the frozen complete source sets independently of candidate declarations. |
| Native/Python chronology was incomplete | Positive sequential command durations could fit inside a falsely zero-length enclosing interval. | Reconcile command durations with report time using the declared timestamp rounding allowance. |
| One interpreter could have contradictory identities | Package-tool receipts could assign different bytes to the same provisioning executable. | Join canonical and resolved interpreter identities wherever the same executable is claimed. |
| Distribution ownership was only aggregate | Retained Vortex files could be reassigned to another distribution while aggregate file coverage stayed unchanged. | Join the known Vortex distribution's members to the retained first-party installation and wheel. |
| A truncated GNU sparse tar header escaped the validation boundary | The standard library could raise `IndexError` before the reader rejected the sparse member. | Normalize that exception only at tar parser entry/advancement; preserve unexpected validation-body defects. |
| Application effective-header types could contradict compiler records | A changed `ITYPE` remained invisible in the shared `VX_CFG_*` summary, despite an independent kernel record naming another format. | Require exactly one `ITYPE`, `OTYPE` and `KUNROLL`, each equal to the independently parsed kernel configuration. |

The executed negative probes and complete-caller source reasoning are kept
distinct. A helper-level mutation is not described as a fully rewritten public
archive run. Separate workers implement corrections, and separate reviewers
check them before the repaired tool is published. These findings were defects
in the new replay implementation; they do not establish numerical or ownership
defects in the GPU runtime. A separate operator-documentation finding corrected
the distinction between replay JSON, textual `--help`, and argparse usage errors.

The final reader was tested from a clean isolated checkout at local commit
`2e41134931b7293156cc2b6b114401b795a48e21`, tree
`9d47de23188837fbf766946e697a2afd9a933a7d`. That exact tree was published as
`e71e63229870fcb61b7edf9793cb0d6dccdbaf63`; the
[publication receipt](evidence/p05-torch-replay/validation/repair-publication.json)
preserves the identity mapping rather than relabelling the earlier test command.

| Validation | Observed outcome | Meaning and limit |
| --- | --- | --- |
| Initial integrated P05 selection | 520 passed; 127.900 seconds; no failures/errors/skips | Pre-hardening reader, identified by its original manifest. |
| Reviewed complete-core selection | 534 unique tests passed; 121.040 seconds; no failures/errors/skips | All 41 monitored source/test files match the published d8 reader tree. |
| Final isolated P05 selection | **547 unique tests passed; 250.244533 seconds; no failures/errors/skips** | Clean exact reader tree, unchanged monitored inputs; temporary storage genuinely satisfied the existing 1 GiB host reserve. |
| Final public original replay | **Four passes**, all 663 members per original, unchanged ZIP digests and identical reader manifests | Both c6 primary formats and both c0 historical formats remain separate populations; no native work executed. |
| Local broad governance invocation | **Failed**: 4,633 selected IDs; 4,595 method rows; 55 failed subtests in eight parent methods and two class-setup errors; 23 skip events | All 57 failure/error blocks name the 1 GiB host-fixture `disk_reserve` admission failure. All 542 P05 methods selected in this earlier invocation passed. |
| Hosted d8 governance, run 45352860975 | **Passed with 23 skip events**: 4,610 methods, 2,311.819 seconds | 4,589 passing methods, 21 method skips and two class skips; not a full zero-skip invocation. |

The broad local run selected 282 modules and preserved its exact ID list and
monitored source hashes. Markdown edits and new disjoint tests occurred while
it ran; it was not an entirely frozen checkout. Thirty-eight selected bodies
did not start: 15 behind CMake class skips and 23 behind disk-reserve setup
errors. The workspace had about 658 MiB free when inspected after the run;
individual failure-time free-byte samples were not retained. The 55 failed
subtest receipts explicitly show no process start; the two setup errors name
the same reserve reason without complete child-process receipts. This is the host
**1 GiB** reserve, distinct from the native/P06 **15 GiB** reserve. No guard was
weakened and no unrelated workspace was deleted.

Independent review a57 joined all 31 local failed-parent/setup-blocked method
IDs to actual passing rows in the separate hosted d8 run, with source identity
and eight local-only test additions kept distinct. This resolves the narrow
resource-related ambiguity; combining the runs cannot create a single clean
zero-skip invocation. The 36 CMake-associated method bodies and the existing
P06 full-governance handoff remain separately accounted for. The
[validation summary](evidence/p05-torch-replay/validation-summary.json) retains
the failed log, hosted skips and independent reconciliations. Overlapping
selections and review probes are never summed into a unique-test claim.

An actual complete c0 FP16 replay also passed under independent filesystem,
process, network, import, extraction and dynamic-library guards. All 23 negative
controls were denied, retained bytes remained inert, and the original and
trusted-source hashes stayed stable. This guarded review used its recorded
earlier reader snapshot; the final-source four-original replay is separate.

## Source-scoped P05 acceptance decision

The primary accepted execution is **c6**, not the reader publication revision.
The independent frozen-criteria assessment a53 found the A02 simulation proof
sufficient and identified stale A03 matrix wording as the remaining documentary
gap. Agent a44 reconciled that matrix, a45 independently checked it, and the
final packet review checked the actual decision attachments. The root integrator
records [P05-A02](evidence/p05-torch-replay/acceptance-torch.json) at `simulated`
and [P05-A03](evidence/p05-torch-replay/acceptance-compatibility.json) at
`source_present`, preserving the existing A01 record. P05 is complete only for
this declared scope under the [acceptance policy](acceptance.md). The originating
user authorized implementation, commit and direct master publication; no human
approval or policy waiver is invented.

The qualification covers PyTorch **2.15.0+cpu**, little-endian **CPython 3.12.14**
with the GIL and main interpreter, **Linux x86_64**, and **RV64 SimX**. The six
matmul signatures are FP16/BF16 crossed with `(8,4,8)`, `(8,4,16)` and
`(16,8,16)`, with FP32 output. The bias-free batch-16 `16 → 8 → 4` ReLU model
retains five families per format and two destination poisons. Input storage,
packing, exact conversion, ReLU and output assembly are declared host work;
native matmul outputs and actual model intermediates agree with the frozen
reference and independent native/Python routes.

Independent host evidence review a33 reconciled 45 unique scripted test
definitions and nine compiled host scenarios per original, without multiplying
those definitions across formats or revisions. Independent source review a49
matched 82 retained first-party source paths and 731 additional receipt-only
paths to the exact execution Git revision: 813 unique paths, with zero mismatches.
The latter 731 are not archived historical filesystem bytes; 193 submodule paths
remain outside that byte comparison. Some third-party, interpreter, tool, seed,
generated-metadata and internal host-assertion bytes are absent. These limits
prevent complete offline binary requalification, reproducible-build proof and
complete host semantic reconstruction. All public replay false flags remain
unchanged, including `host_fault_semantics_revalidated=false`.

The accepted eager contract does not qualify arbitrary models, autograd,
training, real fork execution, processor RTL/XRT, a full device backend or CUDA
binary compatibility. Higher-level `linearize`, input-free FX constant evaluation
and scripted invocation remain unqualified and can submit native work; universal
zero-submission rejection of every unsupported context is not claimed.

## Publication and remaining obligations

The independently reviewed validator seam was published to `master` as
[`c6fb039e706e812b6b3f4d2a5db1828076fe50df`](https://github.com/baabi-boo/AI-GPU/commit/c6fb039e706e812b6b3f4d2a5db1828076fe50df).
The authenticated GitHub connection published the exact locally reviewed tree
with an expected-parent check and no force update. Local and remote trees were
then compared and aligned without overwriting working changes.

The complete-core reader was published as
[`d8abc24d2fd5dab5ceddbae3627e3d3eb9750358`](https://github.com/baabi-boo/AI-GPU/commit/d8abc24d2fd5dab5ceddbae3627e3d3eb9750358),
followed by independently reviewed parser repairs at
[`e71e63229870fcb61b7edf9793cb0d6dccdbaf63`](https://github.com/baabi-boo/AI-GPU/commit/e71e63229870fcb61b7edf9793cb0d6dccdbaf63).
Both publications used exact reviewed-tree comparison and a checked-parent,
non-force master update. The [review ledger](evidence/p05-torch-replay/reviews/ledger.json)
records actual launches and completions; final evidence/docs publication requires
all 60 distinct agents to finish. Agents run in bounded batches, each with a fresh
scoped context; their actual identities, assignments, reports and outcomes
distinguish implementation, testing and review.
Durable notes and a coordinator kept the integration context bounded.

All four unchanged original ZIPs were preserved as durable owner-accessible
artifacts outside Git, following the repository resource policy. Their
[retention receipt](evidence/p05-torch-replay/original-retention.json) distinguishes
that access from public provider availability; a digest alone does not preserve
or deliver an archive. The public packet excludes private access identifiers.

**The next development step remains the qualified P06 warm experiment.** Obtain
one uninterrupted full governance invocation with its required dependencies and
zero skips, then provision the unchanged 15 GiB reserve and execute the frozen
24-process / 792-launch / 25,344-word matrix. Retain and independently replay
the original, evaluate the unchanged predicates, and obtain the remaining
correctness/RTL/parity and target-budget/resource evidence for A02/A03. Other
checkouts' unfinished delivery work was preserved. Vendor `hw_emu`, physical
FPGA qualification and the historical 267 → 283 DSP area finding remain open.
This work changes no arithmetic fixture, hardware threshold, resource admission
gate or native ABI. Its phase change is confined to the documented P05 decision.
