# P06 counter diagnostics development handoff

## Resume here

**Implement a separately versioned qualification binding for the actual
seed-free measurement binaries and complete managed warm caller.** Reviewed
all-selector and public-runtime diagnostics are complete for their declared
scope; they are prerequisites for that work. The
[audit](p06-counter-diagnostics-audit.md) explains the implementation, closed
findings, original failures and remaining evidence limits. The
[qualification plan](p06-mpm-qualification-plan.md#qualification-work-to-implement-and-review)
is the authoritative full development and execution sequence.

P06/P06-T01 remain `in_progress`; A02/A03 remain open. Keep diagnostic and
replay `qualified`, `ready_for_warm`, `warm_execution`, full warm coverage and
all acceptance claims false. Preserve the unconditional warm-v1
`P06-WARM-RV64-MPM-HIGH-HALF` rejection and unestablished absolute no-wrap
bound. Accepted cold evidence, P01 vendor `hw_emu`, P05 obligations and inherited
area findings retain their existing scopes.

## Source and evidence identities

| Checkpoint | Exact identity and scope |
|---|---|
| Audited baseline | `7455e008c1e001d3329e74fd55ffcd942592ec5f` |
| First all-selector original | `407ab9fea5e4f793a2a5088f566a87f3e631aa84`; run `45026112992`, attempt 1; seven model cells pass |
| Failed first public original | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`; run `45029135146`, attempt 1; seven model cells and public boundary control pass, normal fails, four public modes blocked |
| Corrected native original | `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`; tree `74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`; run `45031746149`, job `137236632765`, artifact `14758252829`; seven model cells plus six public-stage cases pass |
| Latest reader and native checkpoint | `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`; tree `061ecbddc9b321edbd70c054c8efce4d188de04f`; run `45034575685`, job `137245341329`, artifact `14760051170`; all 13 diagnostic process cases pass, with independent source/Git and inert replay review |
| Published test-only repair and clean local governance | `142b2d6aaea2fa4226118b857514113032d2e26c`; tree `754ef8577f9a72785c0809048762c70b16cb4857`; exactly two replay test modules change; independent review closes F2-01/F2-02; the clean local full suite passes all 3,318 tests; hosted/native retries remain separately queued |
| Pinned lifetime dependency source | Ramulator `e62c84a6f0e06566ba6e182d308434b4532068a5`; actual loaded source-to-binary provenance remains an obligation |

The [native index](evidence/p06-counter-diagnostics/native/index.json) identifies
these four untouched original archives. The unchanged
[public pass locator](evidence/p06-counter-diagnostics/native/public-runtime-pass.json)
remains pinned to the corrected `e5f1524` original:

| Original archive | SHA-256 |
|---|---|
| [run-45026112992-attempt1.zip](evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip) | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` |
| [run-45029135146-attempt1.zip](evidence/p06-counter-diagnostics/native/run-45029135146-attempt1.zip) | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` |
| [run-45031746149-attempt1.zip](evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip) | `05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276` |
| [run-45034575685-attempt1.zip](evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip) | `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb` |

The corrected `e5f1524` packet and the separately executed `4268d2d5` packet
each cover all 33 available selectors/40 components, with
6,389 assertions and 1,788 half reads per model boundary cell. Each packet's six
public stage cases are one boundary control plus five actual public modes. Those modes
observe ten actual Processor lifetimes, seven complete terminal snapshots,
462 successful half reads and one failed cache half read. The
[public contract](../designs/simx_counter_public_diagnostics_v1.md) distinguishes
unseeded scalar contexts from seeded terminal/failure controls and records the
inverse-payload DMA unchanged-RAM assertion and static payload lifetime.

The latest [independent audit](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit.md)
reconciles the 4,290,949-byte, 1,046-member original, all 17 model/14 public
command records, and 270 model/683 public source bodies against immutable Git.
The 683-name public inventory adds exactly seven retained Python files; the
original 676 source bodies match the earlier corrected packet.

## Replay existing originals safely

Run these examples from the physical repository root using the current trusted
readers. `pwd -P` supplies the canonical absolute archive prefix; the archive
paths must have no symlink components. The commands do not build or run SimX.
`--output` creates a new file exclusively. A fresh `mktemp` directory below
ensures both output names are unused; do not reuse a previous receipt path or
overwrite an original. Omitting `--output` prints the receipt instead.

```sh
P06_SOURCE_ROOT=$(pwd -P)
P06_REPLAY_DIR=$(mktemp -d /tmp/p06-counter-replay.XXXXXXXX)

python3 ci/project/p06_counter_diagnostics_replay.py \
  --archive "$P06_SOURCE_ROOT/docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip" \
  --sha256 c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f \
  --source-revision 407ab9fea5e4f793a2a5088f566a87f3e631aa84 \
  --output "$P06_REPLAY_DIR/model-original.json"

python3 ci/project/p06_counter_public_replay.py \
  --archive "$P06_SOURCE_ROOT/docs/project/evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip" \
  --sha256 05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276 \
  --source-revision e5f152464dda5e488d6d1a030c1fcdc49b5a9701 \
  --output "$P06_REPLAY_DIR/public-original.json"
```

The default archive prefixes are `checked-counters` and `public-counters`.
The model command verifies seven cells and the public command six. The model
reader can separately check the corrected archive's seven model cells using
that archive's digest and full `e5f1524` revision together. Do not combine
different originals into a new native execution claim.

For an extended producer inventory, supply both `--source-inventory` and
`--source-inventory-sha256` from independent reviewed expectations. The helper
pins all original 270 model / 676 public names; additions must satisfy its
reviewed roots, complete descriptors and exact retained body hashes. Invalid
explicit input fails without fallback. The
[source-inventory usage](../designs/simx_counter_public_diagnostics_v1.md#offline-usage-and-source-inventory-trust)
defines the manifest fields and optional invocation. Preserve the receipt's
actual `trusted_replay_sources` closure with its external archive/revision/
manifest expectations.

The latest `4268d2d5` [model replay](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit-checked-replay.json)
and [public replay](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit-public-replay.json)
both pass. The public replay explicitly supplies
[public-source-inventory-4268d2d5.json](evidence/p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json)
and its independent exact-byte SHA-256
`bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`.
The [fixed-inventory rejection receipt](evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit-public-legacy-cli.json)
records exit 1 for the original 676-name route on this 683-name packet. Invalid
explicit digests also reject without fallback; no original locator or inventory
has been rewritten to admit the later archive.

A successful replay establishes only `retained-data-consistency-only`, with
`native_execution="not_run"` and `retained_code_executed=false`. It does not
authenticate an untrusted producer or independently rehash absent executable,
object, library or tool payloads. Never execute retained helpers or resolve
their recorded absolute producer paths on the replay host.

## Boundaries the next implementation must preserve

The [model](../designs/simx_counter_diagnostics_v2.md),
[public](../designs/simx_counter_public_diagnostics_v1.md) and
[lifetime](../designs/simx_counter_lifetime_v1.md) contracts apply to the exact
RV64 `p02-tfr` timing SimX, `PERF=1`, one-worker, VM-off, CP-on-direct-RAM
route. The complete managed caller must establish zero origins, checked
monotone updates, preserved resets, all 33 terminal checked sums, 12 unavailable
rows receiving no query, actual queue joins/final references, enabled-CP
retirement and no updates through destruction. Bind the actual seed-free host,
runtime, kernel and loaded dependencies to the reviewed source/build chain.

Keep the CP interpretation precise: raw head writeback is unsupported, and the
raw tail pair contains staged low/committed high bits. The schema-2 drain
statement is a source-backed inference under exclusive submission and exact
retirement, not a raw head equality or a generic concurrent atomic snapshot.
Discard a failed processor context; later success in a new context cannot
rehabilitate it. A library digest alone does not prove that the loaded Ramulator
was built from the audited source graph.

Implement and independently review the new strict validator and its rejection
tests before fresh performance inspection. Then run the separate four-process
FP16/BF16 × policy preflight: **132 launches and 4,224 exact output words**.
Only after those obligations pass, execute the unchanged **24-process,
792-launch, 25,344-word** attempt. Keep all primes/warm-ups, the frozen timing
and policy order, five measured batch means per format/policy and the original
three statistical predicates. Full details and the unchanged two-job, one-worker,
4 GiB RSS, 15 GiB disk, log and time limits are in the
[qualification plan](p06-mpm-qualification-plan.md#fresh-matched-attempt).
Do not infer all-33 RTL parity from this SimX result; the selected
`memory_bank_st` route has a separate RTL coverage gap.

## Receipts and remaining publication work

The [host index](evidence/p06-counter-diagnostics/host/index.json) retains the
concurrent local 3,070-test/149-failure attempt, the clean `81ed687`
3,146-test/18-failure/6-error attempt, and the clean `e5f1524` pass of 3,158
tests in 1,305.183 seconds on Python 3.12.3. Independent original-log review
recounted all 3,158 distinct successful methods with zero skips/failures/errors.
This historical full-suite pass excludes the later reader/inventory additions.
Their reviewed focused scopes are checked replay 43 methods/167 subtests,
public replay 40/247, inventory helper 48/278 and independent integration 37/110.
See the [audit verification table](p06-counter-diagnostics-audit.md#host-and-retained-data-verification)
for the original review links; these counts must not be summed as one suite.

The latest [completed hosted receipt](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/receipt.json)
records run `45034575638`, job `137245340992`, at `4268d2d5`: **3,312 executed
tests in 1,811.712 seconds, 3,310 `ok`, two `FAIL`, no errors or skips, exit 1**
on Python 3.12.3. The [independent original-log review](evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/failed-review.md)
matches every executed ID to the earlier discovery, including all 154 additions.
The two isolation guards stop on current trusted `baseline_inventory.py` when
the current and recorded producer source roots share a pathname. This original
remains failed; neither incomplete guard is represented as passing.

The [test-only repair review](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-review.md)
is complete for published `142b2d6`, closing both the root-path collision and
filename-only execution-witness findings. The
[final author record](evidence/p06-counter-diagnostics/reviews/wave10/w10-replay-guard-fix-exec-identity.md)
retains 89 passing affected-module methods in 139.141 seconds. Independent
review separately records eight methods / 670 subtests in 4.956 seconds and
three methods / 15 subtests in 4.437 seconds. All three scopes have zero
failures, errors or skips; they are separate from the full hosted gate.

The subsequent [clean local governance receipt](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/receipt.json)
and [independent review](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/review.md)
record **all 3,318 distinct tests passing in 1,918.414 seconds on CPython 3.12.14**,
with no failures, errors or skips. All four governance commands exit 0. The
isolated detached `142b2d6` worktree is clean before/after, and all 365 recorded
source bodies match immutable Git and remain unchanged. Both formerly failed
guards and all six added methods explicitly pass. The original raw local
[unittest log](evidence/p06-counter-diagnostics/host/local-clean-142b2d6/unittest.log)
has 578,913 bytes and SHA-256
`dd05f5f1b09e8e97ae5fc13b2da5c739d39ef6d22a34d035f1cc9142f564e4c7`.

The separate [hosted API observation](evidence/p06-counter-diagnostics/host/checkpoint-142b2d6/pending-receipt-20261122T165509Z.json)
records run `45040805357`, job `137264592244`, queued at 2026-11-22 16:55:09 UTC,
with no runner, steps or conclusion. Native retry `45040805341`, job
`137264592580`, also remains queued with no executed result. The clean local
suite completes the documented governance verification; the latest audited
native execution remains the thirteen-case `4268d2d5` original.

Current checkpoint receipts and remaining publication work:

1. Clean local full-suite verification is complete at `142b2d6`, with its
   independently reviewed original receipt above. Preserve the queued hosted
   and native observations and every prior failure; any later remote result
   remains a distinct execution with its own receipt and review.
2. Native intake and independent source/Git/replay review are complete for
   `4268d2d5` native
   [run 45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685).
   All thirteen diagnostic process cases pass. The fourth original archive,
   explicit 683-source manifest, passing inert replay receipts and fixed-676
   rejection receipt are retained above; earlier failed originals remain intact.
3. Append the completed governance review and remaining real task outputs to
   the packet. Preserve the [47-task historical snapshot](evidence/p06-counter-diagnostics/reviews/session-agents-wave08.json).
   The [current actual-task ledger](evidence/p06-counter-diagnostics/agent-ledger.json)
   records all 60 assignments complete, with six actual tasks in each of ten
   waves; none remains in progress. The reviewed repair, clean local full-suite
   verification, final actual-result prose and independent certification are
   complete; final actual-60/ten-wave completion is true. The certified 60/59
   candidate remains unchanged, with direct original evidence, related reviews
   and historical missing author notes still explicit.
4. Finish final local-link/project metadata checks and independent review of
   the completed receipt prose. Root's authorized next action is to publish
   the assembled documentation/evidence with the tested `142b2d6` implementation
   and test source unchanged, verify the remote revision, and report that actual
   publication in the final response. The clean local suite remains attributed
   to its tested code checkpoint; metadata checks cover the assembled documents.

These are evidence/publication follow-ups, not permission to bypass the new
qualification work or launch the warm experiment. A later diagnostic pass still
leaves qualification, warm readiness/execution and P06-A02/A03 acceptance unearned.
