# Independent publication review — selected direct repair

**R3: the scoped repair is ready for publication after the final tree/ref and
documentation checks below. No new F2/F3 finding remains in this review.**
The broader CI matrix is still running; this verdict claims neither overall
CI success nor a phase acceptance, waiver or human approval.

Reviewer /root/w10_a06 authored none of the production repair, harnesses,
runners, workflow or execution packets. I applied AGENTS.md, code/RTL/SimX
review guidance, coding rules, bug-fix discipline and review policy to baseline
4df7186… and selected candidate 18c888058ac851b802350c99770ed9ac2d27b582.
The alternative 27a18d4… is excluded from the selected source.

## Production and preserved contracts

I reviewed every production hunk in Core::dcr_read and VX_csr_mpm. On RV64,
Word is unsigned uint64_t; reading the original low CSR and shifting by zero
or 32 before uint32_t conversion preserves the requested half without an
invalid-width shift. RV32 keeps its old low/high route. The selected class is
restored on every supported normal return. No new cross-module ownership
access, synchronization, instruction, counter update or simulator event appears.

The host RTL uses its existing RV32 half decoding at both widths, with
intermediates matching the 32-bit DCR bus. Its unsigned part-select and sized
cast zero-extend the twelve implemented high bits of each 44-bit counter.
Default zero behavior and class/extension mappings remain. Request capture
and the registered response schedule are unchanged.

Baseline byte comparisons confirm unchanged architectural csr_unit.cpp,
VX_csr_data.sv, VX_dcr_data.sv, DCR interfaces, public software/runtime/kernel/
common surfaces, VX_gpu_pkg, configuration/type constants, toolchain pin and
all synthesis/performance goldens. The pinned SimX Makefile retains SHA-256
c719966647f32fef5421dd798a89d3eeddccd692e7c61046e5744b7a8e722403.
Its additive test fragment uses the normal production objects/link rules.
The protected SVG and exact README embed also match baseline.

All pre-existing ci/project files and roadmap acceptance metadata remain
unchanged. Original cold execution pins still reject changed current source;
historical replay retains its separate scope. Warm v1 still unconditionally
returns P06-WARM-RV64-MPM-HIGH-HALF with qualified=false and an unestablished
absolute no-wrap bound. A repair cannot recover historical missing high bits.

## Whole-change review map

| Changed area | Publication assessment |
|---|---|
| Production decoder/model | Direct width, ownership and hunk review above |
| Native tests and build integration | Direct Makefile/catalog/wrapper review; [native review](native-review.md) supplies source-bound execution and object/link verification |
| Runners, workflow and boundary tests | [Enforcement review](enforcement-review.md) covers every enforcement hunk, failure closure, identities, resource limits and trust |
| Synthesis catalogs/variants | Both catalogs select the same live registered wrapper; four additions are opt-in and preserve existing cases/defaults |
| Archives and cost experiment | Direct hash/CRC/report checks plus [circuit review](circuit-review.md) and [alternative disposition](alternative-review.md) |
| Status, roadmap, handoffs and plan | Documentation preserves acceptance scopes and separates repair from performance qualification |
| Agent receipts/ledger | Final regeneration must count actual completed work, with no invented approvals |

## Evidence and cost disposition

I independently rehashed the selected and alternative native/circuit ZIPs,
checked CRCs and inspected their raw reports. Each candidate has eight native
passes, two numeric parent failures and complete paired circuit measurements.
The selected matrix totals 1,056 RTL reads, 19,912 assertions and 18,064 SimX
checks; repeat attempts are not added together. Both old-production binaries
build successfully, then exit one on missing high bits. Full SimX records
714 failed checks out of 5,251.

The concrete alternative experiment closes the original missing-comparison
F2. Its shared decoder saves 2/68 estimated Beacon LUTs but adds 9/21 generic
Yosys cells; PERF-off path length grows 7→8 and PERF-on watch endpoints grow
12→32. Retaining the direct repair avoids those measured trade-offs. This
selects the depth-preserving implementation among the tested alternatives,
without claiming global optimality. Original RV64 +21/+417 LUT increases,
NO-BASELINE verdicts, comparison exits and gate_outcome=fail remain visible.
No production stage, golden, threshold or compensating subsystem change was added.

The immutable governance gzip and raw log independently match their hashes
and exact 2,910-test successful footer. Actual exit zero is attributed to the
parent-owned session record; missing pre-launch/interpreter provenance remains
explicit. The base-owned classifier independently returned R2 over 75 committed
files; observable host behavior and enforcement justify manual R3 treatment.
I performed no heavy build, synthesis or redundant full test run.

The enforcement review's F1 standalone executing-interpreter identity gap
remains a follow-up; the hosted equality check protects the inspected runs.
Leaf RTL, stable injected-state and generic synthesis evidence establishes no
full AFU coverage, enabled-extension qualification, atomic/live reads, physical
timing, absolute no-wrap proof or warm performance acceptance.

## Integration and publication controls

At **2026-11-22 04:42:51 UTC**, main CI run 44983573278 had 92 jobs:
12 successful, 20 running, 60 queued and no completed failures. Those unfinished
cells remain pending. The policy requires named run/not-run evidence and the
change's concrete contract obligations; it does not require every automatic
broad-matrix job to complete before every landing. No remaining F2 missing-test
obligation is uniquely supplied by those queued cells for these two stateless
data-selection hunks: paired model/RTL behavior, eight native executions,
parent sensitivity, response timing, circuit comparison, host governance and
independent reviews cover the declared repair. Continue CI and investigate any
later failure; do not infer an all-CI or performance pass.

Read-only GitHub checks find master at 4df7186… and validation head at
18c8880…. Master reports protected=false, protection disabled and status-check
enforcement off with empty contexts/checks; repository/inherited rulesets are
empty. These are observed settings, not permission to bypass a later rule.

A bounded scan inspected 144 new/modified plain files, eight ZIPs containing
1,013 members, and two decompressed logs: 22,483,719 bytes. No private-key,
long GitHub-token, signed-download-URL or URL-credential pattern appeared.
This is not a complete secret audit; later edits need the final check.

The proposed consolidated landing preserves history: create one commit whose
parent is the exact current master and whose tree is the complete reviewed
staged tree. Keep validation/experiment branches for provenance. Recheck the
master lease immediately before a non-forced update and preserve concurrent
work. Require staged, API-created and fetched tree equality, and production/
test bytes identical to 18c8880; only then align the local branch.

The user authorized implementation and pushing master. This review invents
no human approval or gate exception. Refresh documentation and the actual
60-receipt ledger, record measured cost/disposition in the landing message,
and verify the resulting remote SHA/tree. The validation implementation first
appeared at 58c71d3…; this review does not invent the future landing SHA.

**Verdict: publish after those final identity/documentation checks, with broad
CI explicitly still running.** Existing phase gates, the inherited DSP finding
and future versioned warm qualification remain separate. No remote mutation
was performed by this reviewer.
