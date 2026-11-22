# Independent review: CP terminal observation and public record strictness

## Verdict and scope

**R3 review; land the reviewed diagnostic-source checkpoint for a fresh native retry. No open F1, F2, or F3 finding was found in the final three-file diff.** This verdict does not claim native diagnostic success, warm qualification, RTL parity, or phase acceptance. The original failed native execution remains failed and the four later public modes remain blocked in that original report.

Reviewer: agent 33 of 60, wave 6 third (`w06_cp_drain_review`). I did not author or edit any repository file, commit, push, perform a native build, or run a native diagnostic. The review compares the three paths below with published base `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`. Root subsequently applied the raw-tail wording/name clarification described below; I inspected that delta and reran the focused tests on its final bytes.

| Reviewed path | Final SHA-256 |
|---|---|
| `tests/unittest/checked_counters/public_main.cpp` | `4a408a3b4485050366ed330e652769e884fdd56433dceb5c6c3f80186f4950be` |
| `ci/project/p06_counter_public_records.py` | `d947be071b670edcbc0b7d613860c288ee1b013f16e256679747afe0353a7e78` |
| `ci/project/test_p06_counter_public_records.py` | `6db25cdc71e58c2458c61007e1e616fe19adf91f771cfe5cfbe398ce99bd2a84` |

The enforcement and schema changes are conservatively R3 under `docs/review/code-review-policy.md`, regardless of a path classifier result. Every changed hunk was inspected. I applied `AGENTS.md`, the repository code-review and simx-review checklists, C++/Verilog coding rules, bug-fix discipline, and the relevant simulator architecture/framework rules. No production timing or functional implementation changes are in this reviewed diff, so a new model-parity or RTL run is not asserted or needed to establish this narrow source correction. Fresh native execution is still necessary to verify the complete diagnostic.

## CP drain argument

**High confidence, static proof.** The old assertion treated zero-initialized host head-writeback storage as the internal CP head. `Device::cp_init()` clears that allocation and programs its address. `CommandProcessor::mmio_write()` stores the address, but no CP production path writes the internal head there; `publish_completion()` writes the sequence to the distinct completion address. The retained native log's failure therefore matches the diagnosed harness observation error.

The repaired observation retains `head_writeback_raw == 0` and labels it `head_writeback_status: "not-published"`. It never synthesizes a successful internal head value. A nonzero raw value fails rather than being accepted as a head observation.

`CommandProcessor::busy()` is `enabled() && (head < tail || cl_loaded || command-engine-not-idle || launch-engine-not-idle)`. The harness separately requires both control registers to equal 1 and runtime CP enable to remain true, so zero status cannot be explained by disabling the CP. It also requires zero queue error and the full retired sequence to equal the runtime expected sequence within the 32-bit observable bound. With the runtime's one-command-per-64-byte-cacheline construction, initialized CP state, completed submissions and exclusive ownership, the exact sequence and byte accounting support a source inference of drain. `expected <= UINT32_MAX` also prevents overflow of the `expected * 64` expression.

**Raw tail clarification resolved (F0, high confidence, static proof).** `Q_TAIL_LO` returns `q0_.tail_lo_staging`; `Q_TAIL_HI` returns the committed tail's high word. A concatenation is not an independent read of the committed 64-bit tail. I raised this representational distinction to root. The final producer, validator and tests use `tail_register_pair_raw`, and the comments explicitly state staged-low/committed-high semantics and the role of completed serialized submission plus retirement in establishing correspondence. This accurately scopes the evidence and leaves no open finding. The status/sequence inference does not depend on falsely treating staged low bits as a direct committed-tail observation.

Source checked: `sim/common/cmd_processor.cpp` (enable/busy, MMIO, fetch/head advance, retirement and completion), `sw/runtime/common/device.cpp` (initialization, cacheline append, serialized LO/HI commit and sequence polling), and `sw/runtime/simx/vortex.cpp` (CP transactions, bounded CP ticking and direct-RAM host transport).

## Ownership and terminal vector

**High confidence, static proof.** The successful path waits for the launch and queue finish before taking the witness. `close_resources()` releases all remembered events, queues and the program buffer. `terminal_cp()` checks one remaining device reference and empty queue/buffer registries. The deliberate extra-retain control rejects a nonexclusive owner and verifies restoration. The harness has no competing host submitter or active batch; released queue workers are joined by the runtime destructor. These checks support reading the private runtime accounting without racing a producer in the admitted harness.

Both terminal CP observations remain before actual device destruction and CP disable. The first precedes the terminal vector; the second follows the 66 public half reads. The producer and validator retain exact `cp_after.expected == cp_before.expected + 66`, enabled/idle/error/retirement checks at both ends, 33 available selectors, 40 backing components, exact low/high tags and reply reconstruction, unchanged full model observations across readout, and post-destruction evidence. Public MPM reads use the synchronous processor hook and do not advance GPU ticks on the admitted idle direct-RAM route. The repair does not remove those premises.

Nearby assumptions inspected: CP register transaction bursts can advance the functional CP without inventing head writeback; each normal context has two COUT initialization transfers, program write/readback, 19 descriptor writes, one launch and two post-launch COUT metadata reads, giving the illustrative pre-vector sequence 26 and post-vector sequence 92. IO-aperture COUT reads do not introduce a lazy GPU cache flush. VM-off avoids MMU DCR activity. These are source derivations, not new native observations.

## Schema, assertion totals and strict logs

Schema version 2 is changed in both producer and validator; old `head`/`tail` fields and unknown/missing fields fail exact field-set validation. All fixed boolean qualification/acceptance guards remain false. Integer bounds reject booleans and out-of-range tails/sequences. Raw unpublished-head status and the named inference basis have exact type/value checks.

Each CP observation adds exactly four assertions: two CP read-success checks, one raw-head zero check, and one exact byte-accounting check. Normal/coherent modes have four observations; negative modes have two. The +16/+8 deltas therefore agree with final totals: normal 1668; coherent-terminal 1814; immediate-overflow 1176; delayed-overflow 1176; cache-overflow 1173. These totals are control-flow expectations, and only a fresh native run can confirm actual produced totals.

The reserved-marker repair is strict: there must be exactly one occurrence across `CHECKED_COUNTERS_RESULT`, `CHECKED_COUNTERS_FAILURE_RESULT`, and `COUNTER_PUBLIC_RESULT`, in addition to the exact public prefix and unique final-line requirement. This rejects malformed, tab-delimited, suffixed or embedded competing markers without broadening accepted results. I independently reproduced three examples that the base validator accepted and the final validator rejected: a bare checked-result marker, a tab-delimited checked-failure marker, and a malformed public marker preceding a valid result. Existing byte/depth/type/duplicate-key and explicit failure-marker protections remain intact.

## Validation performed and inspected

- **Run, pass:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/project -p test_p06_counter_public_records.py -v`, from the source root, on final hashes above: 33 tests, 1.934 seconds. These tests use synthetic records; they do not authenticate execution.
- **Run, pass:** `git diff --check -- tests/unittest/checked_counters/public_main.cpp ci/project/p06_counter_public_records.py ci/project/test_p06_counter_public_records.py`.
- **Run, pass:** independent in-memory base/final parser regression examples for the three malformed marker forms above.
- **Inspected and verified:** root's final syntax-only receipt `/workspace/scratch/98908dfa3444/w06-cp-drain-syntax/receipt-final.json`, SHA-256 `9fb0aba955ba572ab21e9cd6bbac1fdfa632c407a0c72506e239a3adf78c8f5f`. It records exit 0, empty compiler output and final main SHA `4a408a3b4485050366ed330e652769e884fdd56433dceb5c6c3f80186f4950be`. I checked the complete argv against the predecessor receipt and independently reconciled its relocated include paths and removed dependency-output flags with the archived native stamp. All other flags match. The four generated-header hashes match both scratch copies and original archive members. This is syntax-only evidence, not link or execution evidence. I did not independently rerun the compiler.
- **Inspected and hash-verified:** failed native archive `docs/project/evidence/p06-counter-diagnostics/native/run-45029135146-attempt1.zip`, SHA-256 `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5`. The checked model report passes. The public build and model control pass; public normal exits 1 with `terminal CP ring is not drained`; immediate/delayed/cache/coherent public modes remain blocked. Both report qualification flags remain false. No original failed artifact was transformed into pass evidence.
- **Not run:** new native build/link/execution, broad repository tests, model parity, RTL, vendor emulation or hardware checks.

## Remaining obligation

Publish and execute the final source checkpoint through fresh native CI; bind the retained observations to these exact source bytes and preserve failed attempt 1. If any native mode fails, retain it as failed and diagnose it before changing claims. P06 and warm acceptance remain pending. This review permits the bounded source retry, not promotion of the diagnostic result or the lifetime theorem to executed acceptance.
