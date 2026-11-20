# P04-T01 — fixed tiny-model source qualification

All five declared qualification commands passed against the clean source
commit below. The full repository source suite ran **1,733 tests in
752.879 seconds** with exit code 0; the source remained unchanged. The
retained process receipts and raw logs establish those host results. Independent
source and final-results reviews support [P04-A01 acceptance](acceptance.json).

This packet addresses **P04-A01 at `source_present` scope only**. It freezes the
model, inputs, exact reference and declared placement before native executor
development. P04 remains `in_progress`; P04-A02 and P04-A03 are unearned. The
acceptance record binds this completed work package to its actual tests and
independent reviewers; it does not complete the inference phase.

## Frozen source and model

| Identity | Value |
|---|---|
| Tested source commit | [`10ace66193686e3862c3c218760b66c044f1d4ae`](https://github.com/baabi-boo/AI-GPU/commit/10ace66193686e3862c3c218760b66c044f1d4ae) |
| Tested Git tree | `775aa7d5f96cfc5f7346e591ca151f36c485d2cf` |
| Parent revision | `4a5df5afef1826b70a2addee5029aae9dada2da1` |
| Fixture SHA-256 | `d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03` |
| Tested host tools | Python 3.12.14; GCC 14.2.0, with C++17 and UBSan for the host helper |
| Execution scope | Python source/tooling checks and compiled host C++ tests; no GPU backend |

The [fixed contract](../../../designs/tiny_mlp_fixture_v1.md) describes a
synthetic, bias-free `16 → 8 → 4` ReLU MLP with a batch of 16. Its **160 original
deterministic weights** and five input families produce **ten FP16/BF16 cases**.
There is no tokenizer, downloaded model asset or trained-model quality claim.
The fixture contains 44 encoded tensor hashes over 4,000 uint32 words; the
producer and [model manifest](../../../../ci/project/p04_model_manifest.json)
fix seeds, logical/storage layouts, zero tolerances and 17 source dependencies.

The planned graph has three native matmuls per case: hidden `(16,8,16)` and two
output row blocks `(8,4,8)`. ReLU, exact FP32-to-FP16/BF16 conversion and output
row copies are explicit host work. Actual hidden outputs must be compared
before ReLU and must supply the bridge; the bridge must supply subsequent
native inputs. The thirty launches across this fixture are **planned**, not
executed. CPU matmul fallback is unavailable.

[source-inventory.json](source-inventory.json) binds all 25 changed source files
to their exact Git blobs, SHA-256 digests and sizes. The immutable commit and
whole-tree identity bind unchanged dependencies too. The source under test
predates this evidence packet; later evidence and current-status edits do not
replace its identity. No local/API commit mapping is substituted for the actual
fetched source commit.

## Qualification results

| Check | Result | Retained evidence |
|---|---|---|
| Independent fixture reproduction | Pass, read-only | [Raw log](fixture.log) |
| Frozen model contract and source hashes | Pass, read-only | [Raw log](contract.log) |
| Project structure and evidence metadata | Pass; no GPU certification | [Raw log](governance.log) |
| Historical baseline-packet consistency | Pass; no historical GPU rerun | [Raw log](baseline-packets.log) |
| Full source suite | Pass: 1,733 tests, 752.879 s | [Raw log](full-suite.log) |
| Base-revision change classifier | R2; no detected R3 contract or evidence finding | [Text](change-impact.log), [JSON](change-impact.json) |

[verification.json](verification.json) retains the exact argument vectors,
per-command exits, durations, sampled process-group RSS, cleanup outcomes and
matching raw-log hashes. [run_formal_tests.py](run_formal_tests.py) is the exact
harness that produced those receipts. It requires a clean source tree, checks
that it remains clean, and uses a 1,800-second limit per command, a 15 GiB disk
reserve, a sampled 3 GiB process-group RSS budget and a 5 MiB per-log budget.
These are polled budgets, with the limitations recorded in each receipt.

The [64-test development log](focused-development.log) is retained separately.
It predates the formal source freeze and is not substituted for the complete
source-bound suite. Its reviewed test bytes match the frozen source. The final
P04 test inventory contains 19 reference, 32 contract, 5 independent P02
numerics, 6 host-helper and 2 CI tests.

The numerical cross-check covers 1,920 scalar outputs through 6,400 ordered
P02 reference quartets, plus 48 extra extreme/cancellation quartets. The host
helper's legal-domain sweep is **258 calls covering 33,024 element/position/
format/value combinations**. These counts describe host/reference coverage,
not native device work. Mutation tests refresh relevant digests before
requiring semantic rejection, and failed checks preserve bytes and mtimes.

## Independent reviews and retained provenance

| Review | Scope and retained record |
|---|---|
| `/root/w06_a06_changed_hunk_review` | Every implementation/test/specification/workflow hunk and exact source hashes; [review](reviews/w06_a06.md), [record](reviews/w06_a06_review.json) |
| `/root/w07_a01_base_classifier` | Base classifier, four workflow path additions, protected surfaces and R2 obligations; [review](reviews/w07_a01.md), [commands and hashes](reviews/w07_a01_policy_review.json) |
| `/root/w07_a02_qualification_review` | Harness and first four completed receipts; [review](reviews/w07_a02.md), [observation](reviews/w07_a02_review.json) |
| `/root/w07_a03_fixture_provenance` | Independent seeds/weights/inputs/layout/hash reconstruction; [review](reviews/w07_a03.md), [result](reviews/w07_a03_provenance_results.json), [probe](reviews/w07_a03_provenance_probe.py) |
| `/root/w07_a04_current_docs_review` | Nine frozen preacceptance navigation/planning files; [record](reviews/w07_a04_review.json) |
| `/root/w07_a05_execution_boundary_review` | Actual-output lineage, P03 completion/ownership API and planned tensor-byte accounting; [record](reviews/w07_a05_execution_boundary_results.json) |
| `/root/w07_a06_final_test_matrix` | Independent final 64-test coverage/AST/source inventory; [record](reviews/w07_a06_test_inventory.json) |
| `/root/w08_a02_formal_results_review` | All five completed commands, exact clean source, log hashes, tools, no skips and final scope; [review](reviews/w08_a02.md), [record](reviews/w08_a02_review.json) |
| `/root/w08_a06_packet_review` | The assembled 31-artifact acceptance snapshot, normalization and A01-only attachment; [review](reviews/w08_a06.md), [record](reviews/w08_a06_review.json) |
| `/root/w09_a01_final_docs_review` | Final current-status wording, historical boundaries and all nine current document diffs; [review](reviews/w09_a01.md), [record](reviews/w09_a01_review.json) |
| `/root/w09_a03_acceptance_metadata_tests` | Later evidence/status snapshot: 55 metadata tests and both validators pass; [review](reviews/w09_a03.md), [record](reviews/w09_a03_results.json), [command receipts](metadata-checks/verification.json) |

These reviews preserve the state and pending obligations at their observation
time. They are scoped engineering reviews, not invented human approvals or
GPU measurements. The source publication is independently recorded in
[source-publication.json](source-publication.json): the qualified commit and tree
were read back from `master` after a non-forced update with an expected prior
head. The completed [60-agent, ten-wave ledger](agent-ledger.md) and
[full portable receipts](agent-ledger.json) retain the actual distinct
assignments and completed work. Failed spawn attempts are excluded.

[artifact-provenance.json](artifact-provenance.json) maps copied records to
their original session identifiers and hashes. Raw logs, JSON records, scripts
and the source inventory are byte identical. Trailing ASCII spaces were removed
from two Markdown reviews to satisfy diff checks; exact line/count mappings
and original/retained hashes preserve that formatting-only transformation.
Original scratch-directory
names inside a retained receipt are historical identifiers, not missing public
download promises. The base classifier and policy can be reconstructed from
their recorded Git revision, and the nonempty raw classifier outputs are here.

The [independent compiled-ledger review](reviews/w10_a04_postledger.md) and
[structured verification](reviews/w10_a04_postledger.json) match all sixty
portable receipt bodies, all 120 raw/retained receipt hashes, ten waves and the
sixty Markdown rows. The follow-up uses the same reviewer and leaves its
original receipt unchanged; it does not increase the agent count.

## Hosted checks and final delivery review

The [hosted CI observation](reviews/w09_a04.md) and its
[structured record](reviews/w09_a04.json) identify the exact qualified source.
[Project Governance](https://github.com/baabi-boo/AI-GPU/actions/runs/44705486903)
passed, including 1,733 tests in 316.405 seconds on the hosted runner. This is a
separate observation from the local qualification duration. General CI was
still in setup at that observation; its planned full coverage is not a result,
and the existing DSP gate failure remains unresolved.

The [source-boundary review](reviews/w09_a05.md) compared all 3,631 frozen Git
blobs and five Gitlinks: only the nine intended current documents differed.
The [publication preflight](reviews/w09_a06.md) verifies the actual published
source, intended non-forced evidence-child update and remaining delivery checks.
The [agent-accounting review](reviews/w09_a02.md) records intermediate actual
counts and a corrected guard in the coordinator's temporary ledger finalizer.
Those intermediate counts are not substituted for the completed final ledger.

The [final evidence-integrity review](reviews/w10_a02.md) approves its corrected
52-artifact snapshot. A redundant raw bookkeeping observation was omitted to
avoid retaining a controlled machine path; its original session data remains
preserved, and the portable accounting review and guard probes are retained.
The [later source CI observation](reviews/w10_a03.md) preserves the independent
09:05:27 UTC observation on 2026-11-20: governance passed and general CI was
still in setup. Neither snapshot claims results for a future evidence commit.

The [final executor handoff review](reviews/w10_a01.md) defines the immediate
milestone: one actual `fp16-seeded_dense` three-call SimX case with exact
intermediates, actual-output lineage, dispatch records and checked cleanup,
then the full ten-case/error/trace qualification. The frozen P03 manifest still
contains a historical T01 advisory in `next_implementation`; the current
canonical roadmap, status and P04 phase guide correctly select T02. Refresh
that advisory during the reviewed T02 manifest update, preserving this qualified
source snapshot and its pins.

## Reproduce the source checks

Use a checkout containing the tested commit and the later evidence packet.
Choose a fresh worktree path and a new output directory; the runner refuses a
dirty source or an existing output directory.

```sh
P04_REPO=/path/to/AI-GPU
P04_SOURCE=/path/to/clean-p04-source
P04_OUTPUT=/path/to/new-p04-results
git -C "$P04_REPO" worktree add --detach "$P04_SOURCE" 10ace66193686e3862c3c218760b66c044f1d4ae
python3 "$P04_REPO/docs/project/evidence/p04-fixture/run_formal_tests.py" \
  --source "$P04_SOURCE" --output "$P04_OUTPUT"
```

The invoked commands are preserved verbatim in `verification.json`. They need
Python 3.12 and a C++17 host compiler with UBSan; they do not download a GPU
toolchain or run a GPU simulator. The independent provenance probe may be run
separately with `--repo` pointing to a repository containing the frozen commit.

## Limits and next development step

- No composed model executor, native model launch, layer-level device output,
  dispatch timing, accelerator performance, FPGA or silicon result is supplied.
  P04-A02/A03 and later physical gates remain unearned.
- Generated-build/runtime/kernel agreement is a future execution obligation;
  source hashes and an exact accepted profile mapping do not establish it.
- The planned per-case tensor-buffer totals are 1,920 H2D and 768 D2H bytes,
  including output poison writes. Argument/control/module/setup traffic is
  separate; these are API-level counts, not measured DMA transactions.
- The retained qualification harness has a disclosed F1 diagnostic limitation:
  an early bounded-runner block before log creation causes a nonzero missing-log
  exception before that blocked receipt is saved. It fails closed and cannot
  grant a false pass. Every retained real command produced a complete matching
  log; the [isolated probe](reviews/w07_a02_preflight_probe.json) did not affect
  qualification. The exact executed harness is preserved unchanged.
- The existing tensor DSP area failure, 267 to 283 against the unchanged 5%
  threshold, remains unresolved. This work changes no RTL, native profile,
  golden baseline or gate tolerance. See the [development audit](../../p04-audit.md).
- P01-A03 vendor XRT `hw_emu` remains blocked and is required before P07 can
  close. Existing P02/P03 execution evidence keeps its historical scope.

The [finding dispositions](findings.md) and [structured record](findings.json)
preserve repaired defects and unresolved obligations.

The next bounded implementation is **P04-T02**, the
[managed model executor](../../p04-executor-plan.md): compose the frozen graph
from actual outputs, retain ownership through incomplete operations, and
record native dispatch, host work, transfers and timings before model acceptance.
