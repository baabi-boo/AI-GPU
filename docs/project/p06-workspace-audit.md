# P06 serial workspace development audit

## Starting point and selected work

This continuation audits `master` at
`3235cd59d724663dda1bece20645d5ccf30462e1`. The canonical
[status](status.md), [roadmap](roadmap.json), [backlog](backlog.md),
[acceptance policy](acceptance.md), current source, existing host tests and
hosted workflow results supply the starting evidence.

P02, P03 and the bounded P04 model have accepted evidence. P05's copying
binding is accepted, while independent framework acceptance remains open.
P06-A01 accepts the cold SimX baseline; P06-A02/A03 require their separate
optimization and resource evidence. P01-A03 vendor emulation and the inherited
267 to 283 DSP finding remain unresolved. None of those gates is closed here.

The next useful implementation is the ownership prerequisite identified in
the [workspace proposal](p06-next-experiment-proposal.md), followed by an
explicitly selected fixed-shape resident workspace. The accepted baseline's
small-workload counts motivate this experiment but do not establish that
allocation is the bottleneck or predict a speedup.

## Concrete source findings

| Finding | Consequence and selected action |
|---|---|
| Native managed submit permits more than one live operation | Add an exclusive lease retained through successful wait until completed operation close. Separate queue locks do not qualify overlapping launch setup. |
| Managed contexts can coexist despite SimX's shared process state | Reserve one managed context before opening its device. Keep the reservation while retained operations outlive their owner. Document the boundary around unmanaged/raw runtime clients and separate linked copies. |
| Repeated owner close can lose a prior cleanup error | Preserve cleanup status and reject new managed work after an observed cleanup failure, including failures encountered during destruction. |
| Completion-query errors can be overwritten by a later successful observation | Retain non-timeout primary errors while continuing to drain; never expose output from a failed operation. |
| Every operation allocates and releases A/B/D | Add opt-in resident A/B/D for `(8,4,8)`, with unchanged default behavior, kernel, fixture arithmetic, transfers and per-operation queue/events. |
| Existing P04 lifecycle mocks replace the managed runtime | Add combined tests of the real model and real managed wrapper, distinguishing host fault injection from native accelerator execution. |
| Common release APIs do not expose every underlying deallocation failure | Describe observed release failures accurately; handle-release counts alone do not prove physical memory reclamation. |
| Historical replay and metadata tests call the strict original execution-source validator | The three changed runtime files correctly fail its original hashes. Separate historical interpretation from native execution qualification while preserving every original source pin and accepted measurement. |

## Implementation and verification boundaries

The candidate remains an internal C++ API. Existing model, Python, PyTorch and
cold-benchmark callers keep per-operation buffers. The resident option is
restricted to the small accepted shape in FP16/BF16; it retains 128 A bytes,
64 B bytes and 128 D bytes. Host staging, queue/events and input/output copies
remain per operation. Unsupported requests must fail before new work is queued.

Verification covers setup rollback, competing contexts and operations,
completed wait without close, timeout and eventual drain, partial submission,
sticky failure state, owner destruction, repeated close, changed inputs and
poisons, resource bounds and consumer compatibility. Native numerical checks
must use independent existing fixtures and current generated build trees.

Local native execution is unavailable: this environment lacks the pinned GPU
toolchain and the required 15 GiB disk reserve. Host checks run on temporary
storage with the existing 1 GiB reserve. Hosted native workflows retain their
two-job, memory, disk and deadline limits. No limit is relaxed to fit this host.

This implementation is not a performance acceptance. The original cold
manifest, source pins and accepted measurements remain unchanged. Warm-context
before/after measurements require the
separate frozen sampling, timing, source-pair and rejection protocol before a
speedup or P06-A02 decision; P06-A03 still needs its resource/timing reports.

## Frozen-baseline integration finding

The [consumer audit](evidence/p06-serial-workspace/agents/w05_a03.md) reproduced
an F3 integration blocker at `5da357f0f4a3cd3581919b35941db7a07d0d9fbe`:
the old contract loader rejected the three intentionally changed runtime files.
The [complete integration attempt](evidence/p06-serial-workspace/host/checkpoint-5da357f-failed/retention.json)
ran 2,484 tests with two failures and twelve errors from that same coupling.
Failed imports and setup reduced the method count. The original native validator
was correct to reject those bytes; updating its pins would misidentify a new
experiment as the accepted cold baseline.

The implemented correction leaves the strict native loader and runner unchanged
in scope. A distinct historical-analysis API validates the exact manifest,
21 interpretation inputs and seven invoking helper identities. Replay still
checks every retained source descriptor and all 46 frozen execution pins inside
each digest-verified original archive, with no execution of archived code.
The current baseline workflow performs that historical replay, while workspace,
P04 and P05 workflows retain their separate current-native execution scopes.
The [fresh analysis](evidence/p06-serial-workspace/host/historical-replay/analysis.json)
and its [retained failed/corrected CLI attempts](evidence/p06-serial-workspace/host/historical-replay/retention.json)
are recorded separately from the unchanged accepted measurements.

The [P06-A01 successor](evidence/p06-serial-workspace/p06-a01-retained-baseline.json)
only relocates the two original reader artifacts to exact retained source bytes.
Original commands, hashes, source revision and acceptance state remain intact.
Independent enforcement review and the complete corrected-checkpoint rerun remain
required before the integration finding can close; these documentation changes
make no closure claim. The [handoff](p06-workspace-handoff.md#historical-cold-baseline-and-current-execution)
explains historical native reproduction and current candidate qualification.

## Work accounting

The requested work is organized into ten waves of six actual agent assignments,
batched within the session's concurrency limit. Individual receipts live in
`evidence/p06-serial-workspace/agents/`. Only completed receipts count toward the
final execution ledger; agent count does not expand test or acceptance scope.

Validation results, exact tested commits, independent review findings and the
published branch identity are recorded in the final evidence packet and handoff.
