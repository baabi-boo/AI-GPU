# W09 independent documentation and claim review

Reviewer: `/root/w09_documentation_review`, agent 53, wave 9 slot 5.
Review checkpoint: `2026-11-22T15:08:54.341740+00:00`.
Repository HEAD: `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`; documentation includes the uncommitted bodies identified below.
Audited development base: `7455e008c1e001d3329e74fd55ffcd942592ec5f`.

## Disposition

**Pass for the captured diagnostic documentation checkpoint.** No unresolved F2 or F3 finding was found. One F1 wording issue was corrected by the evidence owner and reread. This is advisory review of the stated documentation and evidence claims. It is not counter qualification, warm readiness, phase acceptance, maintainer approval or a new execution result.

Final publication still needs the acknowledged latest-CI intake/status update and later actual-task ledger refresh. Root reported a newer `4268d2d5` native result during this review and assigned its independent intake to agent55. This report intentionally remains bound to the three already indexed originals; it neither promotes a pending run to pass nor borrows that newer result. Root alone commits or pushes.

## Scope and method

Read `AGENTS.md`, the review policy, current project/gate/acceptance context, every changed hunk in README, roadmap, status, backlog and P06 phase guide, and the full qualification plan, diagnostic audit/handoff and three counter design contracts. The evidence README and late ledger-reference paragraphs were checked after agent52 froze its first pass. This reviewer made **no repository edits**.

Verification was read-only source inspection, direct standard-library ZIP/JSON/log analysis, byte/hash comparison and local Markdown target checks. No archived helper was imported or executed. No native builds, native cases, full host suite or repeated focused suite ran. Supporting source hashes and the exact checks are retained in the companion JSON.

## Finding and correction

### DOC-53-01 — unsupported empty-FIFO observation wording — F1, resolved

**Confidence:** high. **Evidence type:** static-proof.

The earlier packet README paragraph at `docs/project/evidence/p06-counter-diagnostics/README.md:29–34` described the drain statement as using “empty CP FIFO.” The original schema records CP enables, status/error, expected/retired sequence, unsupported raw head storage and the mixed raw tail pair. It contains no independently observed FIFO-empty field. `sim/common/cmd_processor.cpp:65–73` makes enabled `busy()` cover unconsumed ring work, a loaded cacheline, command-engine work and launch work; `public_main.cpp:265–303` supplies the source-backed inference under exclusive serial submission. The concrete documentation risk was misreading an inferred drain condition as an additional retained observation.

Agent52 replaced the phrase with **enabled idle status and exact retirement**. The corrected paragraph still explicitly identifies the staged low/committed high pair and rejects unsupported host head-writeback interpretation. Its fixed SHA-256 is `a9cfb40c3b45f6db8f20e8e83c4b01cd69efd01cc2cfa6c1a683bf075f9d2b5e`. The detailed public/lifetime designs and audit/handoff were already precise.

## Evidence reconciled

All three original native archives match their indexed byte counts, SHA-256s, member counts and embedded report digests:

| Original | Source | Directly corroborated outcome |
|---|---|---|
| `45026112992`, attempt 1 | `407ab9fea5e4f793a2a5088f566a87f3e631aa84` | Seven model cells pass; model-only scope |
| `45029135146`, attempt 1 | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c` | Seven model cells and public boundary control pass; public normal fails; four later modes blocked |
| `45031746149`, attempt 1 | `e5f152464dda5e488d6d1a030c1fcdc49b5a9701` | Seven model cells plus public boundary control and five public modes pass: 13 native process cases |

The corrected public logs contain mode assertions **1,668 / 1,176 / 1,176 / 1,173 / 1,814** for normal, immediate overflow, delayed overflow, cache overflow and coherent terminal. Their totals are ten actual constructions/disposals, seven terminal vectors, 231 selector queries, **462 successful half reads plus one failed cache half read**. Each vector retains 33 available selectors, 40 backing components and twelve unavailable rows unqueried. Each of the three recorded ordinary/checked/public-boundary controls has 6,389 assertions and 1,788 half reads. These observations agree with the design, audit, handoff, status and plan.

All seven corrected terminal vectors retain enables equal to one, sequence **26 → 92**, runtime/raw-pair tail **1,664 → 5,888**, and raw head storage zero with `not-published` status. The source correctly distinguishes staged-low/committed-high raw reads from an independent complete committed tail. Direct source inspection corroborates exclusive ownership, extra-retain rejection, queue destruction/join ordering, unchanged-RAM inverse-payload controls and static lifetime of the DMA source arrays. No generic concurrent atomic-snapshot guarantee is inferred.

The corrected archive's **270 model and 676 public retained source bodies** independently match every size/hash descriptor and the corresponding immutable `e5f1524` Git body. This corroborates source text identity; it does not authenticate an absent binary payload or prove loaded dependency compilation origin. Joined raw build commands independently count **45 model compilations/one link** and **19 public compilations/four links**. The public makefile confirms 44 reused model objects, 14 runtime objects, three backend objects plus one hook, and one main. The backend DSO has four objects, and `14 + 3 + 1 + 1 = 19` new translation units.

The three host logs also match their exact indexed sizes and hashes. Their distinct outcomes remain:

| Host execution | Result |
|---|---|
| Concurrent local development attempt | 3,070 tests; 149 failures; source changed during execution |
| Clean hosted `81ed687`, run `45029135196` | 3,146 tests; 18 failures and six errors; controlled interpreter-fixture exposure |
| Clean hosted `e5f1524`, run `45031746158` | **3,158 distinct successful methods in 1,305.183 seconds**, zero failures/errors/skips |

The successful log has 3,158 distinct method headers and 3,158 successful result lines. One method, `test_accepts_staged_entry_with_blocked_upstream_phase`, prints its docstring/result on the following line; accounting for that prevents the misleading 3,157 count produced by a single-line-only parser. The earlier clean hosted failure and native CP-head-assumption failure are preserved separately from the concurrent local failures.

The four focused review scopes match their retained reports and are never summed into a full run: checked replay **43 methods/167 subtests**; complete public replay **40/247**; source-inventory helper **48/278**; independent reader integration **37/110**. The historical e5 full-suite pass excludes the later `4268d2d5` reader/inventory additions.

## Qualification and gate consistency

The documents consistently distinguish all-selector **transport/backing-source coverage** from universal native updater coverage, seeded terminal/failure controls from unseeded scalar controls, and both from the complete managed FP16/BF16 warm caller. No production runtime, CP semantics, ABI, timing or RTL behavior change is attributed to this diagnostic continuation. The continuation's changed source paths are tests, diagnostic makefiles, readers/producers and workflow enforcement; production implementation bodies remain outside that change set.

The lifetime contract is correctly conditional: all 40 components need zero origins, admitted monotone checked updates and preserving resets; all 33 terminal checked sums must succeed; every selected source must remain stable through readout and destruction. The full warm caller and actual loaded Ramulator source-to-binary provenance remain open. A cached-library digest, source manifest or successful scalar context does not establish those premises. Agent51's complementary independent lifetime/dependency review found no current theorem/dependency mismatch; its retained-history note is now explicitly addressed in the packet index.

The next path remains separately versioned: bind seed-free binaries and full caller plus loaded dependencies, implement pure admission/final validation, independently review rejection controls, then run the four-process preflight. Its arithmetic is consistent: **132 launches / 4,224 words**, sixteen snapshots, 528 enabled queries, 1,056 successful halves and 192 unavailable unqueried rows. The following complete experiment remains **24 processes / 792 launches / 25,344 exact words**. Primes and warm-ups remain disjoint, five measured means per format/policy and all three original predicates remain unchanged.

`ci/project/p06_warm_contract.json` is byte-identical to the audited base, SHA-256 `893d85401b1d5f7757d82cb7c743a89b36264fe19c7d08c239b7f216b7a8cbbd`. The warm analyzer/replay, machine roadmap and protected framework SVG are also byte-identical. The warm-v1 blocker remains unconditional; qualification/readiness/warm/acceptance remain false. P06/P06-T01 stay in progress, P06-A02/A03 stay open, P01 vendor hw_emu and P05 remain separate, and the inherited **267 → 283 DSP / 5%** finding is unchanged. The SimX `memory_bank_st` versus RTL MEM-decoder gap is still explicit.

## Late retention and publication notes

The fixed first-pass packet README and audit/handoff ledger paragraphs accurately name the retained **54-task / 51-completed** checkpoint, three in progress, six requested tasks not yet recorded, and a false actual-60/ten-wave completion flag. This review does not claim later completion. The immutable lifetime manifest remains 407-bound: the README now explains its historical pending-public text and original `P06-T01-A02/A03` typo, identifying the actual open gates as P06-A02/P06-A03. The historical lifetime comparison was renamed to `.md.txt` without making it current prose; the former relocation-related Markdown links are no longer interpreted as current links.

At this fixed checkpoint, `status.md:204–207`, audit `:107–112` and handoff `:146–152` still describe the earlier 4268 host-in-progress/native-queued state. Root subsequently reported native run `45034575685`/job `137245341329`, artifact `14760051170`, 4,290,949 bytes, SHA-256 `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb`, and assigned independent intake to agent55. **That later artifact is outside this review.** Latest-status prose must receive the planned reviewed update or retain an explicit historical as-of label before final publication. The host result remains unasserted here.

The final pass checked **807 local file targets** across the twelve documents and **9 Markdown heading targets**, with zero missing targets. Agent52 separately reported its current/historical retention verification; this review did not represent that as new GPU or full-suite execution.

## Fixed documentation identities

The following hashes pin this review. Subsequent latest-CI or ledger edits require their own delta review; they are not silently covered by these identities.

| File | SHA-256 |
|---|---|
| `README.md` | `22b026f4a4afde960e7e19e15151e54293f9a238964a7c6d69adedc9a5349477` |
| `ROADMAP.md` | `f67421afed6b1677a0c96dedd2fb05c8079458b86e5038bb00d61a61379162cf` |
| `docs/project/status.md` | `e2613f1730b00f999fad966820890afc23f00458ea6fc692754a296d839f696a` |
| `docs/project/backlog.md` | `365c34e19bbb558ed3b11bbdc64394ea85d414b91bb28f9160dfea5cf28548e6` |
| `docs/project/phases/p06-performance.md` | `385b1a292d5911307cf24d720994ac3264cecaf5f416e8efbf90a51037f48a36` |
| `docs/project/p06-mpm-qualification-plan.md` | `37349a766731325b7222136cf99a2651961fe70c67f5f52461e4cd0c83b1da77` |
| `docs/project/p06-counter-diagnostics-audit.md` | `7aa7f9160ce396e7ab6c2bbcd4806d0c30518292e8bdee6f89879532528c8871` |
| `docs/project/p06-counter-diagnostics-handoff.md` | `da89aefd3185c1e40b8e122542c700544a77ae0f8541b8e7eaaeddc23c3314b8` |
| `docs/designs/simx_counter_diagnostics_v2.md` | `1d46c118522ef2c67b7046a8f9538f3fc3d305963efeff350b75898dd3b2e199` |
| `docs/designs/simx_counter_public_diagnostics_v1.md` | `025c9e58c4fb2d0d8eeb78ed1ab6d5fc65255f2e3bfeb9c454ac658a454a5ca5` |
| `docs/designs/simx_counter_lifetime_v1.md` | `6b555d2920af3405c4af588de7e43d46e77619dc43dad263bf92141a60a4672d` |
| `docs/project/evidence/p06-counter-diagnostics/README.md` | `a9cfb40c3b45f6db8f20e8e83c4b01cd69efd01cc2cfa6c1a683bf075f9d2b5e` |

The companion JSON additionally pins supporting code, indexes, manifests, ledger and protected gate files; records exact original archive and host-log checks; and preserves the findings and explicit non-execution limits.
