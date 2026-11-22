# Independent integration review — 18c checkpoint

**The repair's scoped landing evidence is sufficient; broader CI remains
pending.** The [CI index](../hosted/final-ci-validation.json) records the refreshed,
non-atomic **2026-11-22 04:48:11 UTC** snapshot. Publication may proceed after
final source/tree and remote-head checks, while retaining the pending matrix
and investigating subsequent failures. This is not an overall CI-pass claim.

I did not author the implementation, runners or workflows. I applied AGENTS.md,
the code-review skill, coding rules, bug-fix discipline and review policy. Scope
is integration status, retained governance evidence and attribution of existing
review obligations; the production and enforcement hunk reviews remain
separately linked below.

## Source and completed evidence

Read-only GitHub commit/run/job endpoints identify candidate
`18c888058ac851b802350c99770ed9ac2d27b582`. The PR checkout is
`6e6426a0bf761baab11e932a4c86b49a5de81217`, with tree
`d6dd742a905e0f3e76c7374cc678ba87e5c2a19e` and parents baseline `4df7186…`
and candidate `18c8880…`. The observed tracked changes after that candidate
were documentation/navigation only. Final publication still needs its own
identity check.

The [immutable governance receipt](../host/governance-18c8880.json) binds
**2,910 passing tests in 1,516.847 seconds**. I independently rehashed the
72,826-byte gzip and its complete 502,190-byte decompressed log, reproduced the
deterministic gzip, counted all 2,910 test entries, matched the exact `OK` footer
and found no failure/error/skip markers. Actual exit zero is recorded from
`/root`'s execution-session completion; I did not inherit that session or infer
its exit from the footer. Clean-source observations exist during and after the
run. The missing pre-launch snapshot and interpreter/dependency binary records
remain explicit limitations. This host suite is not native GPU execution.

All **seven dedicated workflows and sixteen jobs** succeeded at this candidate:
frozen baseline replay, installed Python, installed PyTorch, native model,
serial workspace, warm workspace and host MPM transport. These are workflow
and job conclusions; the [native review](native-review.md) separately verifies
the raw eight-cell matrix and both numeric parent failures. A green warm
workflow leaves its unconditional qualification block intact. A successful
MPM measurement job leaves its raw area failures and `NO-BASELINE` outcomes
intact. The [enforcement review](enforcement-review.md) retains its standalone
interpreter-provenance F1 and the hosted equality check that protects these runs.
Both hosted governance runs, **44983573226** and **44983569071**, have now
succeeded through every step, including project structure, baseline-packet
consistency and the governance suite. Their API conclusions supplement the
independently verified local log; I do not invent a hosted test count.

## Pending and cancelled work

Main PR CI run **44983573278** has **92 jobs: sixteen successful, twenty
running and fifty-six queued** in this snapshot. This includes five
setup/build jobs and 87 test jobs. No completed failure was observed.
Model-parity and performance cells are running or queued; the logic gate is
running and the ordinary RTL unit cell is queued. None of those unfinished
results count as passes.

The ordinary PR's `simx,rtlsim` filter excludes the new driverless catalog
case: `ci/testcase.py::_filter` rejects its absent `marker_driver`. The dedicated
MPM workflow supplies the required native coverage. Do not claim this broad
matrix executed the new host catalog entry merely because its RTL unit cell
eventually passes.

Four superseded generic runs and the duplicate selected-candidate push run are
recorded as cancelled. The isolated alternative's duplicate push and generic
PR runs are also cancelled; its dedicated comparison remains separate. Root
reported the cancellation purposes, while I verified their API conclusions.
No cancellation is classified as a passing regression run. The untouched
baseline run **44977488194** passed **43/43 jobs**, which validates its original
scope, not this candidate.

The [earlier executor audit](../../../p04-executor-audit.md) retains the
**267 → 283 DSP** finding from run `44705486919`. I inspected that documented
history, not its old raw synthesis artifacts. Neither the narrower baseline
success nor the presently unfinished logic gate resolves it. Golden files and
roadmap acceptance metadata remain unchanged.

## Disposition

**R3; no repair-specific F2/F3 integration obligation remains.** The
[alternative review](alternative-review.md) closes the named comparison F2
and retains the direct repair. It preserves the original red area outcomes
and the [original review](circuit-review.md); neither is relabelled as a pass.

Policy §2 requires named executed/unexecuted evidence, applicable Beacon work
and independent R3 review; §3 adds obligations when contracts change. It does
not require every generic matrix cell to finish before every R3 landing.
The frozen transport contract's eight native cells, both numeric parent
failures, paired leaf measurements and reviewed cost explanation are complete.

I rechecked the two production hunks: they change host reply selection, with
no pipeline, queue, arbiter, channel, retirement, interface or response-register
change. The RTL native test verifies its unchanged two-edge response schedule;
that is a leaf protocol result, not full-workload parity. The matching SimX
change selects a returned word without advancing simulated time. No installed
API layout, ISA, configuration default, toolchain pin, golden, tolerance or
existing test case changes create another contract-specific obligation.
Consequently I found no concrete missing test that only the unfinished generic
cells can provide for this repair. Those cells remain valuable broader coverage
and may still find defects; their status is retained without a waiver.

**Verdict: ready for the authorized publication, conditional on final input/tree
identity and remote-head checks.** A consolidated commit must retain the
reviewed `18c8880` production/test/workflow/configuration bytes and accurately
name the original execution SHAs. Leave broad CI running, report it as pending,
and investigate any failure. No all-CI-green, historical warm qualification,
phase acceptance or physical-performance claim follows. No build, test rerun,
source edit or remote mutation was performed here.
