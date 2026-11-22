# Wave 8 evidence retention handoff

## Scope and disposition

Agent `/root/w08_evidence_retention` preserved the available original per-task notes, logs, receipts, configuration records, audit scripts and historical patches. The work edits only `docs/project/evidence/p06-counter-diagnostics/reviews/` and the packet `README.md`, plus `w08-evidence-retention*` scratch records. It does not modify native originals/indexes, host logs/indexes, source/dependency manifests, lifetime proof, production/test code or active project documents. Root alone commits and publishes.

The byte-for-byte ledger capture is **2026-11-22T14:47:26+00:00**, at repository HEAD `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`. It records **47 distinct task names**, not 60 completed agents: waves 1–7 have 42 tasks and a `completed` wave state; wave 8 has five recorded tasks and an `in_progress` wave state. Wave states are statements in the root-maintained ledger, not a new independent completion attestation. The repository HEAD at retention is not substituted for any earlier tested revision.

The frozen intake contains **176 pre-existing scratch originals**. **172 files / 9,046,841 bytes** were copied unchanged. Four existing identical artifacts are referenced by their verified SHA-256 and byte count: the dependency source bodies, the concurrent local governance failure, the original public-native failure log and the hosted 81ed governance failure. The copied ledger, this subsequent author handoff and a post-intake correction to the public-design author note are additional records. The original captured public-design note remains unchanged; its later correction fixes gate-name prose and updates document hashes, without changing the original replay receipts. `reviews/retained-files.json` reports final counts and hashes; its inventory excludes generated catalog metadata from the original-file count. Original ZIPs, extracted native archives, build trees, downloaded tools and large generated objects were not duplicated.

## Mapping and known gaps

`reviews/task-artifact-map.json` maps every actual name in the retained ledger to observed artifacts, direct task-named notes, related independent reviews and explicit limitations. `reviews/README.md` provides a browsable task table. `reviews/ARTIFACTS.md` and `reviews/retained-files.json` enumerate normalized repository paths, original scratch filenames, SHA-256 digests and byte lengths. Associations based on filenames or explicit report references do not independently attest authorship.

The following standalone-note gaps are preserved rather than filled with reconstructed prose:

- `w02_harness`: no standalone author handoff was established; its independent harness review and integrated source are related evidence.
- `w02_runner`: no standalone author handoff was established; its independent runner review and integrated source are related evidence.
- `w05_lifetime_proof`: the original validation JSON is retained, but no standalone author handoff was established; the independent lifetime review is separate.
- `w05_public_replay`: no standalone author handoff was established; the independent test handoff and later independent replay review are separate.
- `w08_qualification_plan`: recorded as active in this partial ledger; no artifact was present at the frozen intake.

The observed `build_lifetime_manifests.py` generator is retained with **unverified authorship**. The source task brief, baseline 64-test log without a source binding and `w08-lifetime-before.md` snapshot are shared historical context; none is attributed to a task merely to fill a ledger row. No conversation transcript was fabricated, and conversational-only handoffs were not reconstructed.

## Evidence distinctions and historical corrections

The packet README distinguishes actual hosted compiled SimX execution from inert replay and synthetic/host tests. It links the genuine 407ab9f seven-cell pass, the 81ed687 public-normal failure with blocked later modes, and the e5f1524 seven-model-cell plus six-public-runner-cell pass. The six public-runner cases include one model boundary control and five public modes. The e5 hosted governance receipt records 3,158 passing tests; it predates the separately committed replay/source-inventory additions.

The full public replay receipt records 40 methods and 247 subtests against the genuine e5 ZIP, with no new native execution. The earlier skipped-success note, stale schema/no-op mutation finding, corrected test delta, contradictory-log failures, original native failure and first W08 review-harness failure remain unchanged. The W08 review-harness error was its own incorrect 36-object assertion; the genuine packet requires 44. The original note explains its repair and separate successful rerun.

The original `w04-build-records-review.md` has a historical prose typo that reverses the two Vortex library roles. It is retained unchanged and explicitly corrected in both current indexes: `libchecked-simx.so` contains 44 reused model/access objects; `libvortex.so` contains 14 runtime/stub objects; `libvortex-simx.so` contains three backend/hook objects with the wrappers; `checked_public_test` contains `main.o`. This correction does not rewrite the source note or an original receipt.

All diagnostic qualification, warm-readiness, full-warm-coverage, warm-execution and acceptance flags remain false. `P06-WARM-RV64-MPM-HIGH-HALF` remains unconditional. Original native execution does not establish seed-free measurement qualification, a full warm attempt, native RTL, physical FPGA performance or phase acceptance.

## Verification and follow-up

Retention verification checks copied bytes against the frozen source hashes; validates every manifest target, digest and byte count; verifies the ledger's exact task-set equality with the task map; checks links in the generated indexes; and scans the retained text for common token/private-key/signed-URL patterns. No secret-pattern candidate was found during intake. The completed verification passed for all 178 retained original/reference records, the ledger snapshot, exact 47-task mapping and 279 generated local links, with no integrity errors or sensitive-pattern candidates. The one observed later public-design author edit is retained as a separate version. These are evidence-integrity checks, not execution qualification. No native build, full test discovery or expensive source archive was run or generated.

A later retention owner must retain the remaining actual task artifacts and a new byte-for-byte final ledger snapshot, while preserving this 47-task snapshot and original failed/partial records. Do not turn missing notes into invented transcripts. Read the current native/host indexes for later root-managed receipts; this task did not author those execution outcomes. No source/test/governance gate or threshold was waived.
