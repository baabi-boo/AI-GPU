# Independent hosted governance and final native-summary review

Reviewer: `/root/w10_a04_final_hosted_evidence`. The root coordinator retained
this summary of independent read-only checks. No edits, tests, builds or
publication were performed by the reviewer.

**Verdict: LAND the retained results within their stated scopes. No F1/F2/F3
finding was identified. The actual published source passed 3,062 governance
tests.**

## Original hosted governance result

Observation began at 2026-11-22 11:57:29 UTC. Run `45017731138`, attempt 1,
job `137193572417` completed successfully at
`9fd7eac203c77fa54c7af80fa0220ae09553cd55`. Checkout and preflight name that
source and report no tracked changes. The command was
`python3 -m unittest discover -s ci/project -p 'test_*.py' -v`.

The independently fetched original log ends with **3,062 tests in 1,295.925
seconds, OK**. It contains 3,062 unique named test entries: 3,061 conventional
single-line successes and one multiline success. There are zero failed,
errored or skipped test results. All job steps, including post-checkout cleanup
and job completion, succeeded.

The reviewer compared the [retained log](../hosted/governance-45017731138-job137193572417.log)
against the separately fetched original in sixteen complete chunks. The
638,690 UTF-8 bytes match exactly, including BOM and final newline. There
are 3,291 lines and the SHA-256 is
`539713f1a68140cec166562eb0087d6b8cf4c3a62af564e9d0fa57f558ef7042`.
The [index](../hosted/governance-index.json) binds that log and returned job
metadata. System CPython 3.12.3 (compiled with GCC 13.3.0) executed this job;
the native workflow's pinned CPython 3.12.14 is separate provenance.

This is an actual later full-suite execution, not an inferred sum of 3,043
earlier local tests and nineteen additions. The earlier local receipt keeps
its actual 53f execution identity. This hosted receipt binds source through
checkout/preflight and the original log; it does not claim a separate
after-suite source/tool inventory or turn host tests into native execution.

## Native summary verification

The reviewer checked [native-review.md](native-review.md) against the original
ZIP, report and logs: ZIP/report sizes and SHA-256, CRC and 317 members,
264 retained source identities, fifteen command logs, thirty configuration/
stamp/probe artifacts, both 44-compilation/one-link streams, per-mode guard
selection, before/after records and all five raw output observations.
The principal evidence and stated limits match. The reviewed summary SHA-256
is `df184b111ac99e7a49df9c1517160b7cc4ceaf85cd32f43a1be4f52c10b56e97`.

This review did not repeat every implementation hunk or the previous complete
Git-source comparison. It preserves nineteen seeded, fourteen unseeded and
twelve unavailable selectors; the direct Core/AsyncRun fault; the first-field
cache aggregate case; and the primitive pending-underflow case. No native
public-runtime, all-selector, continuous lifetime, cycle-parity or warm
performance claim is added. All five original qualification/coverage flags
remain false.

## Broader hosted status

At the observation above, nine of eleven workflows at 9fd had completed
successfully, including native checked counters and Project Governance.
Generic CI (`45017730939`) and P04 Native Model (`45017731029`) remained
queued. No failed conclusion was observed. Other green workflows are status
observations here, not independent artifact acceptance or new phase closure.
Remote `master` independently still resolved to 9fd. Final publication requires
a fresh expected-head check and remains the root coordinator's responsibility.
