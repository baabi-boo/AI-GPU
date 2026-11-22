# P06 simulator completion evidence

## Current result and scope

The repaired code checkpoint is
[`4781ca96db15a1d130626edc7a73411a4f6c2e7c`](https://github.com/baabi-boo/AI-GPU/commit/4781ca96db15a1d130626edc7a73411a4f6c2e7c),
tree `6dd0d759390cda78ec63ad0caacc00a08f03e2bc`. Its clean host discovery
passed **83 tests in 87.502 seconds**, and its pinned-parent replay reproduced
all eight intended historical exception failures. The final CP exception
boundary has an independent review with no unresolved F2/F3 finding in that
review's declared source and host-test scope.

The earlier checkpoint
[`db5ebb3a16770004423f2456ec6d0caaa0aced6d`](https://github.com/baabi-boo/AI-GPU/commit/db5ebb3a16770004423f2456ec6d0caaa0aced6d)
passed the dedicated native completion controls and 2,988 governance tests.
It predates the subsequently discovered CP allocation-error regression and its
repair, so its native result remains historical evidence. **Fresh native
verification of `4781ca9` passed** in
[run 45009314161](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314161).
The [new original packet and independent review](checkpoints/native-4781ca9.tar.gz)
bind the repaired code to same-tree merge
`e929c52d05bad80b28dd4085a97838d7fe2de354`; they verify both the actual native
processor fault/success unit and six successful public-runtime launches.
Both corresponding original governance jobs now pass: the
[PR job](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314170) records
**2,993 tests in 1,864.865 seconds**, and the
[push job](https://github.com/baabi-boo/AI-GPU/actions/runs/45009309941) records
**2,993 tests in 1,891.161 seconds**. Each includes the 83
focused completion tests. Their [original completed logs and independent
review](checkpoints/closure-4781ca9.tar.gz) are retained separately.
This is evidence at the repaired code checkpoint; it does not imply that
the broader CI matrix or later documentation/evidence commit was executed
by that earlier job.

The [completion contract](../../../designs/simulator_completion_v1.md)
defines the implemented behavior. The
[development audit](../../p06-simulator-completion-audit.md) explains why
reliable completion and exceptional teardown precede counter qualification.
The [checkpoint index](checkpoints/README.md) gives exact archive/member paths;
its [machine-readable form](checkpoints/index.json) records identities, scopes
and outcomes. The [root manifest](manifest.json) binds every delivered file
other than itself.

No phase acceptance is added. P06-A02/A03 remain open; warm v1 retains
`qualified=false` and an unestablished absolute no-wrap bound. This evidence
does not establish native public-runtime injected-fault behavior, native RTL or
functional SimX execution, arbitrary failed-context reuse, concurrent contexts,
forced cancellation, a performance improvement, vendor integration or physical
FPGA/silicon behavior.

## Verification by source state

| Evidence | Exact source state and recorded result | What it establishes |
|---|---|---|
| [Clean repaired host suite](checkpoints/host-4781ca9.tar.gz) | Clean `4781ca9`; 83 unittest methods pass, no failures/errors/skips; tracked source and tools stable before/after | Controlled-model backend/public-runtime, actual-framework, owner, provenance and runner-policy tests. It executes no native GPU model. |
| [Repaired-checkpoint parent replay](checkpoints/parent-4781ca9.tar.gz) | Candidate `4781ca9`; pinned parent `42809ff0c1b81384d7c9b079e4ef786be8407600`; all eight built old-backend cells fail the intended assertions | Sensitivity to swallowed execution failures. Compile failures and timeouts are not accepted as the expected failure. |
| [CP allocation finding, repair and review](checkpoints/cp-allocation-repair.tar.gz) | Recorded file hashes match the repaired code in `4781ca9`; 44 existing host cells and 38 new positive cells pass; four built `db5ebb3` controls fail the intended OOM assertion | Processor faults remain terminal, while the original recoverable CP allocation path retains OOM and same-device continuation. |
| [Fresh repaired native packet](checkpoints/native-4781ca9.tar.gz) | `4781ca9`, executed merge `e929c52d05bad80b28dd4085a97838d7fe2de354`, identical tree; both native cells pass with independent source/command/compiler review | Real timing SimX RV64 `p02-tfr`, `PERF=1`, one worker, direct-RAM CP; actual model fault/success unit and six public successes. |
| [First native completion packet](checkpoints/native-db5ebb3.tar.gz) | `db5ebb3`, executed merge `782552fdbb5a216fe7907dde84d8f3f0dc6eb6dd`, identical tree; native controls pass | Real timing SimX RV64 `p02-tfr`, `PERF=1`, one worker, direct-RAM CP. This is pre-repair evidence. |
| [Repaired full governance receipts](checkpoints/closure-4781ca9.tar.gz) | Original PR and push jobs each pass 2,993 tests, in 1,864.865 and 1,891.161 seconds respectively, at the repaired code checkpoint | Independent original-log verification, including all 83 focused methods; distinct from the local focused run and later documentation-only assembly. |
| [First full governance receipt](checkpoints/native-db5ebb3.tar.gz) | Original job log records 2,988 tests passing in 1,191.429 seconds, including the then-current 78 focused tests | Governance/tooling evidence at `db5ebb3`; no inference that the later checkpoint's full suite ran. |
| [Existing warm-workspace packet](checkpoints/warm-db5ebb3.tar.gz) | `db5ebb3`; retained-data replay validates 24 processes, 792 launches and 25,344 checked words | Healthy existing native execution control. Qualification remains blocked and conditional statistics are `not_satisfied`; no speedup is accepted. |

The [earlier clean 78-test receipt](checkpoints/host-db5ebb3.tar.gz) and
[earlier exact parent replay](checkpoints/parent-db5ebb3.tar.gz) remain intact.
They are not relabeled as executions of the repaired checkpoint. Historical
documents retain their original pending/not-run language, which applies to
their recorded state rather than the latest status above.

## The compatibility regression discovered during review

The first completion implementation caught every CP callback exception and
made the device terminal. Independent consumer review identified a concrete
conflict with the inherited lifecycle contract: the CP chooses `Retire` before
allocating its copy scratch buffer, and a scratch `std::bad_alloc` must reach
the queue's existing `VX_ERR_OUT_OF_HOST_MEMORY` handling. The next transaction
must retire that abandoned descriptor without replaying its released staging.

The repair latches failures at asynchronous execution and synchronous
processor hooks. Unrelated CP/host exceptions keep their inherited route. The
new regression compiles the complete
[`tests/runtime/test_ai_lifecycle.cpp`](../../../../tests/runtime/test_ai_lifecycle.cpp)
without modifying it, through the actual dispatcher, common runtime, callbacks,
backends and command processor, with controlled Processor/RAM implementations.

| Directed coverage | Execution cells | Result |
|---|---:|---|
| Entire unchanged lifecycle: SimX/processor-RTL backends × RAM/LLC | 4 | All three allocation stages report OOM, release captures and preserve seeded destination data; a fresh transfer succeeds on the same device and queue. |
| Asynchronous processor `bad_alloc` and unknown exceptions | 8 | Terminal failure survives repeated waits and queue-error consumption. |
| Synchronous processor DCR read/write faults | 16 | Terminal failure prevents subsequent processor work. |
| Synchronous processor LLC read/write faults | 8 | Terminal failure remains distinct from CP scratch allocation failure. |
| Processor-RTL drain faults | 2 | Terminal failure is retained after the drain hook throws. |
| Compiled pre-repair lifecycle controls | 4 | Each exits 1 at the original OOM assertion after stages 0 and 1 pass. |

The five new unittest methods contain the 38 positive cells. The independently
retained development driver executed those actual methods and the negative
controls; the clean 83-test discovery subsequently ran the same five methods
normally. Both sources of evidence are retained. This is host exception-path
coverage, not native processor fault injection or permission to reuse a failed
processor context.

## Native execution archives

The fresh repaired-code packet retains the original ZIP from
[run 45009314161](https://github.com/baabi-boo/AI-GPU/actions/runs/45009314161),
artifact `14749901531`: **2,792,870 bytes**, SHA-256
`461ddd226474aff20205b5ae852489fd4e88f21f7065a74efba25e706eb087b9`.
Its independent review verifies all 812 original ZIP members, 786 retained
input records, 761 checkpoint source bodies, five gitlinks, 18 command/log
records, five compiler/header roles and 87 model-object compile commands.
It explicitly matches the three repaired runtime/helper files and the
completion contract. The actual native unit records nine checked successes,
three legacy successes, one checked `OutOfRange` exception, one legacy error
and fresh-context success; the public cell records six successful serial
launches across two contexts. Original pending-governance API observations
remain historical data inside this frozen packet.

The original ZIP remains unchanged inside `native-4781ca9.tar.gz`. Extract it
beneath `w10-a03-native-ci/packet/` to reconstruct the original review manifest
paths. Its native scope and exclusions are the same narrow categories as the
earlier packet below; it adds no native public injected-fault or RTL result.

The native packet retains the original ZIP from
[run 45006726571](https://github.com/baabi-boo/AI-GPU/actions/runs/45006726571),
artifact `14748468420`: **2,791,612 bytes**, SHA-256
`d5f71cec99321c5f8e6c11fab37875aa93e551270a1a15c29b3fe9af6c766588`.
The independent review verifies all 812 original members, 786 retained input
records, 761 checkpoint source bodies, five gitlinks, 18 command/log records,
five compiler/header roles and 87 model-object compile commands.

The linked unit records normal `gp=7` and `gp=-1` execution, unchanged legacy
success/error behavior, a real bounded-RAM `OutOfRange` exception consumed from
the checked asynchronous run, complete destruction and a fresh successful
context. Its ordered summary reports nine checked successes, three legacy
successes, one checked exception and one legacy error. The public regression
checks six successful serial launches across two contexts, exact outputs,
nonzero low `gp`, waits and cleanup. Neither native cell injects a fault through
the public runtime.

The original ZIP is nested in its checkpoint archive unchanged. Its extracted
tree is not duplicated. Extracting it beneath `w09-a01-native-ci/packet/`
reconstructs the paths in the original review manifest. The same policy retains
the original warm ZIP, whose digest is
`9abac0ec3611c111528968460121db19e3449ad7184e7b8c433e0ad20b54e744`.

## Preserved development history

All 13 original `host/initial-*` records remain unchanged. They cover the first
backend/CP checks, public-runtime checks, the earlier seven-case owner suite,
eight intended old-backend failures and an initial fixture build failure.
The [development archive index](development/README.md) retains the subsequent
runner defects/repairs, assertion-preservation checks, ready-check mutation,
actual framework accounting leak, timing/functional repairs and independent
cleanup probe. Those proofs preserve their original source state and outcome.

The ready-check mutation passes the older seven owner cases and fails the
added eighth case. The actual-framework regression passes eight repaired
timing/functional cells; six built old-header fault/abandonment controls fail
the intended assertions and two normal controls pass. These checks show that
full teardown disposes of abandoned accounting. They do not authorize live
failed-context reuse, operations on finalized objects or internal multiworker
exception transport.

The original [development root index](checkpoints/development-index-db5ebb3.tar.gz)
preserves the previous README and manifest verbatim. Existing review files and
development archives are unchanged, including original gzip review copies and
their already documented whitespace-only display copies. Additional
[checkpoint reviews](checkpoints/checkpoint-reviews.tar.gz) retain the parent
Git-replacement finding and repair, public evidence-scope review, base-policy
classification, workflow trust review and independent archive/receipt audits.
Later corrections do not rewrite prior findings.

## Retention, limits and next action

Each new archive has an external member manifest and an identical internal
`MANIFEST.json`. Original member bytes are preserved; only tar/gzip metadata is
normalized. Every member was reopened and compared with its original hash and
bytes. Compiled binaries and caches are excluded unless already part of an
original hosted ZIP; original receipts retain their declared identities.
Temporary absolute paths remain in original reports. No retained program was
executed while assembling this packet. Hash preservation alone is not proof
of producer honesty or a hermetic execution environment.

The clean host receipts bind every tracked blob and tool identities, but do
not retain all system headers or compiler-support bytes. Before/after checks
detect observed drift, not transient replacement restored between samples.
Nested bounded host commands have separate monitored process groups; the outer
receipt's RSS sample is not their aggregate. Native binaries are identified
but not archived by the dedicated runner. Resource limits and explicit scope
limits remain those of each original receipt.

Native completion and repaired-checkpoint governance are now verified. After
final delivery review, the next bounded development action is the
[counter qualification plan](../../p06-mpm-qualification-plan.md): independently
review the exact 33 available selectors, coherent snapshot reads and enforceable
whole-context lifetime/no-wrap assumptions before implementing qualification
and collecting a fresh unchanged warm matrix. The
[five source audits](checkpoints/next-development-audits.tar.gz) retain the
specific coverage gaps, prospective guard design, immutable warm-v1 boundary,
phase dependencies and inherited DSP finding. They implement no counter guard
and grant no acceptance.

The [late-review archive](checkpoints/late-reviews-4781ca9.tar.gz) retains
the independent final production review, the initial 72-file evidence review,
the protected-input/phase audit and seven original early audit/harness reports.
Their source-time observations remain unchanged. It also retains the two
accepted requests to cancel this task's superseded `db5ebb3` broad CI runs.
Those original management snapshots still report queued overall runs with no
conclusion; they are explicitly incomplete records, not passing CI evidence.
Neither unrelated runs nor verification thresholds were modified by those
recorded actions.

The [closure archive](checkpoints/closure-4781ca9.tar.gz) retains the original completed
governance logs/review, the completed [assignment ledger](delivery-ledger.md)
and its history, final documentation records and #60's independent source/ref
preflight. The ledger verifies **60 distinct actual agents, all 60 initial
assignments completed, ten logical waves and six assignments per wave**.
Follow-ups are not counted again. Agent counts provide coordination evidence;
they do not substitute for tests, source review or phase acceptance.

The later normalized CI API receipt confirms that both superseded own `db5ebb3`
broad CI runs completed/cancelled. Their earlier requested/queued observations
remain unchanged in the preceding archive. Canceled runs are not passes, and
the corresponding current broad CI matrices were still incomplete at that
receipt's capture time.

The final independent evidence delta review, immutable final-commit source
projection and actual publication readback are subsequent scoped observations.
They are not self-certified by this archive. Final documentation/evidence must
pass its own structure/link/manifest checks, and publication must preserve the
tested code inputs and use the already-authorized non-force expected-head
procedure. The root manifest must be refreshed after later additions.

## Final advisory evidence review

The [independent final delivery review](reviews/final-delivery-review.md)
([machine-readable result](reviews/final-delivery-review.json)) passes the sealed
82-file input package and its scoped claims, with no unresolved release-evidence
finding. It independently verifies the 122 closure originals, preserved earlier
archives, both original 2,993-test governance logs, completed 60-agent ledger,
documentation deltas and unchanged execution inputs.

That review follows the assembly-stage observations above. Its two outputs and
this link were appended after the audited input snapshot; the refreshed root
manifest inventories their actual bytes and excludes itself. The review records
the earlier input-manifest identity explicitly and makes no circular self-hash
claim. Final immutable-commit projection and actual remote publication readback
remain separate pending checks. No phase, performance or whole-CI acceptance is
added by this advisory.
