# Independent enforcement review

Reviewed baseline `4df7186edbca82b21b2b8cba9b3b192248b99209` through
`18c888058ac851b802350c99770ed9ac2d27b582`. I authored none of the implementation.
Scope: all three new runners, workflow, integration Make fragment/targets,
additive catalogs and their failure-boundary tests. Applied AGENTS.md and the
repository code-review policy/skill. Production arithmetic and the alternative
RTL cost experiment are separate reviews.

**No F2/F3 finding in the reviewed hosted enforcement path.** One F1 provenance
follow-up is recorded below. Overall landing still depends on the independent
cost comparison, integration results and final publication identity; this is
not a waiver or phase acceptance.

## Execution and identity controls

The native runner creates fresh, nonoverlapping XLEN/PERF trees, configures each
before building, verifies copied/generated files, and uses distinct build and
binary-run commands. PERF off is empty/unset. A successful build or success
banner cannot rescue a failed process. All eight cells remain in the report;
selected-width success is not full-matrix success, and development mode remains
ineligible. Cleanup failures, resource stops, missing binaries, malformed banners
and source/configuration/tool/binary drift invalidate success.

The reports preserve clean Git revision/tree identities, critical hashes,
before/after binary identities, compiler stamps and cached dependency identities.
Fresh directories and recorded make commands bind the full SimX build; the
[native review](native-review.md) independently reconciles all five builds to
41 production objects plus the harness. Binaries are identified but not archived,
so an offline review cannot rehash or rerun them. Support headers, dynamic
libraries and malicious concurrent writers remain explicitly outside the claimed
inventory/observation scope.

The parent runner uses a detached worktree of the fixed old commit, retains its
production bytes, overlays only the five identical harness/build files, and
shares dependency libraries only after matching tracked dependency trees. Its
expected-failure parser requires started, cleaned-up processes, exit 1 and exact
high-half numeric failures. Compile errors, timeouts, unrelated assertions and
unexpected passes cannot provide sensitivity evidence. The real-Git regression
suite covers shallow fetched pins and destination preservation; its implementation
matches the successful retained parent staging.

The synthesis runner completes all eight Beacon measurements before the eight
generic Yosys confirmations, checks configuration/identity stability, and retains
raw gate verdicts and deltas. Exit zero means measurement completion only.
`NO-BASELINE`, area/depth regressions, `gate_outcome=fail` and `qualified=false`
remain visible. No golden or threshold changes. The
[circuit review](circuit-review.md) still records its separate F2 cost-comparison
obligation; this review does not close it.

## Workflow and coverage

Both jobs use GitHub-hosted Ubuntu runners, `contents: read`, credential-free
checkout persistence and restore-only caches. No self-hosted runner, fork secret,
cache-save step or repository-write permission is introduced. Missing/mismatched
cache identities fail preparation with retained evidence. CPython and the three
Python dependencies are pinned; toolchain identity resolves the existing tag to
an immutable commit. Foldsim provisioning is bounded and limited to that component.

The workflow retains artifacts with `always()`, includes attempt/source identity,
and does not use `continue-on-error`. Parent checks can still collect evidence
after candidate failure, without erasing that failed step. Native/synthesis
processes retain the 4 GiB RSS, 15 GiB free-disk, two-job, one-thread and 16 MiB log
budgets plus bounded timeouts. Polled limits are not hard kernel isolation.

Catalog changes add one unit case and four opt-in circuit variants without
changing existing cases/defaults. The added make fragment preserves the pinned
original SimX Makefile and uses its normal model objects. Ordinary PR/push driver
filters do not select the driverless catalog case; the dedicated workflow supplies
the required eight native executions. Unfiltered host catalog runs remain
explicitly developmental, not formal qualification.

## Independent checks

The base-owned classifier exits zero with R2 over 75 committed files. I retain
manual **R3** because host-visible results and enforcement change. I independently
rehashed both final ZIPs, checked their CRCs and workflow bytes against `18c8880`,
and verified 75 runner logs: 24 candidate, 10 parent and 41 synthesis commands.
All retained source/tool/configuration before/after identities match. Native
records show eight passes and both expected parent exits; circuit records retain
eight-plus-eight completion and the raw red area result. No native/synthesis
rerun or redundant full governance suite ran during this review.

Two initial audit-script checks failed because I used the wrong log-size field
and counted the Yosys version probe as a synthesis measurement. Correcting those
review assumptions produced the checks above; neither was a product failure.

## F1: standalone interpreter provenance

**F1, high confidence, static-proof** — `ci/project/p06_mpm_execute.py::tools_snapshot`.
The native runner hashes `python3` found on PATH, but does not separately identify
`sys.executable`. A read-only probe using the installed Python 3.12 interpreter
with `/usr/bin:/bin` PATH recorded Python 3.13 instead. No native process ran in
this probe. An absolute-interpreter CLI invocation can therefore omit the actual
orchestrating interpreter from its tool inventory.

The hosted workflow explicitly requires PATH `python3` and `sys.executable` to
resolve equally before native execution, so the reviewed hosted packet is not
affected. Follow-up: record the executing interpreter in native tool identities,
as the synthesis runner already does, before relying on standalone formal CLI
receipts for a future qualification binding.

**Verdict:** hosted enforcement scope is ready with the scoped F1 follow-up;
land after the separate cost, integration and publication dispositions. No
performance qualification, absolute no-wrap proof, physical result or acceptance
is asserted.
