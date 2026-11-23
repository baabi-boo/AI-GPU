# Qualified warm-workspace evidence

The explicit route for the frozen 24-process FP16/BF16 warm-workspace experiment
is implemented, independently reviewed and published at
`c0b44ce64665fe11895f869eea8c38c9b820d6f7` (tree
`13450812d279d55f36a172fcf38653ff567f6c86`). All 89 focused tooling tests pass.
**All 4,527 canonical test IDs have passing outcomes across completed hosted
and supplemental executions.** The [independent reconciliation](validation/coverage/final-reconciliation.json)
proves 4,491 hosted passes plus 59 supplemental passes, with 23 overlaps and all
36 hosted gaps covered. This is combined passing coverage across two environments;
no complete 4,527-test local run or single invocation without skips is established.
The fresh native experiment is **unstarted and resource-blocked**.
This packet establishes no new native warm performance or phase result.

## Contract and source boundaries

- [Development audit](../../p06-qualified-warm-audit.md)
- [Current resumable handoff](../../p06-qualified-warm-handoff.md)
- [Execution, retention and replay runbook](runbook.md)
- [Implemented route](../../../designs/qualified_warm_workspace_v1.md)
- [Frozen warm sampling and predicates](../../../designs/warm_workspace_benchmark_v1.md)
- [Preceding four-process original](../p06-counter-qualification/README.md)

The new proof's SHA-256 is
`172721c671ddaa79541dde9c37c154b5ab5a99b8abb0caabf2e07036dd429efb`.
Its projection changes only the explicit native caller among 69 measurement
sources. The original qualification proof remains
`d12718e9b182a3c93eab346901b380031516d556dd823017a63831d4a0304b4e`.
Historical original/prerequisite packets and the seven historical false fields
are preserved. No packet field selects the new trusted route implicitly.

Fresh historical four-process qualification requires its reviewed original
source projection/revision. The historical proof intentionally rejects the
current warm caller. Use the explicitly selected qualified-warm route at this
checkpoint; historical archive replay remains supported.

## Current review and validation

The independent reports in `agents/` state actual work and limits. Wave three
covers the native extension (`w03_a01`), proof/admission (`w03_a02`), producer
(`w03_a03`), complete reader (`w03_a04`), unchanged statistics (`w03_a05`) and
actual historical archive compatibility (`w03_a06`). Wave four adds separately
recorded adversarial probes. All **60 actual worker assignments completed**,
six in each of ten waves. The [execution ledger](execution-ledger.json) binds
each task, scope and report hash. The coordinator, same-worker follow-ups and
supplemental probe executions do not increase the worker count.

The [focused execution receipt](validation/qualified-warm-focused.json) and
[complete log](validation/qualified-warm-focused.log) record 89 passing tests in
195.293 seconds on the documented dirty implementation tree. Current-source
identities are in the receipt. The [historical compatibility review](agents/w03_a06.md)
records a real public replay of the unchanged earlier ZIP and 29 passing
historical analyzer tests. Supplementary synthetic probes are not added to the
unique unittest count. The initial concurrent-edit historical test failure is
retained as `validation/historical-qualification-initial.log`.

Hosted [governance run 45244780344](https://github.com/baabi-boo/AI-GPU/actions/runs/45244780344)
completed green, but its [retained analysis](validation/hosted-c0b44ce6/w09_a03-log-analysis.json)
records 4,491 passing methods and 23 skip events: 21 individual skips plus two
class setups suppressing 15 other bodies. The 4,512-test summary therefore leaves
36 canonical bodies unexecuted. Ambient preflight found CMake; the fixtures'
restricted PATH could not find/admit it. Its actual hosted location is unknown.

The [completed supplement](validation/coverage/supplement-result/retention-manifest.json)
runs three entire modules with 9, 21 and 29 cases on the same implementation.
All **59 pass without failures, errors or skips in 13.542 seconds**, with exact
IDs, stable source/tools and observed command cleanup. Its 36 supplement-only
IDs match every hosted gap; 23 others overlap hosted passes. The exact union is
all 4,527 canonical IDs. Hosted Python 3.12.3 and local Python 3.12.14 remain
separate environments. Hosted skip events remain recorded; `full_suite_result`
stays false for a single complete invocation.

Earlier local records are preserved and excluded from that union. The initial
canonical invocation stopped after 1,312 successes (observed tool exit 130),
while its raw supervisor remains `running`. The first two-partition attempt
finished failed after SIGKILL and supervised termination, with 2,472 successes;
its [retained terminal failure](validation/governance/final-c0b44ce6/retention-manifest.json)
is not a pass. A small independent probe established retained test-case references
in the temporary harness, and a separately reviewed correction released them.

The corrected long attempt then lost execution-service contact after 3,771
successful test-ID outcomes (3,770 verbose `... ok` lines plus one standalone
`ok` after expected compiler diagnostics). Its [unfinalized snapshot](validation/governance/released-cases-unfinalized/snapshot-manifest.json)
preserves raw `running` state, missing final results and the later stop request.
Exit status, final source/tool checks and cleanup remain unobserved. No causal
OOM or complete-suite claim is inferred. The 1,312/2,472/3,771 partial observations
do not contribute to combined passing coverage. A complete invocation without
skips remains an explicitly unproven validation obligation, with no gate waiver.

## Native readiness and remaining evidence

[Prelaunch status](native/prelaunch-status.json) records that no fresh native
workspace or experiment exists. Independent reviews verified the exact clean
published checkout, all eight recursive submodules, source projection and
selected tools/inputs. They separately found available RAM below the required
4 GiB and insufficient projected disk headroom to retain the 15 GiB reserve
through the fresh build. [Resource review](agents/w06_a02.md) and
[recovery review](agents/w06_a06.md) retain dated measurements and limits.
Prior originals and unrelated data were preserved; the guards were not lowered.

One fresh attempt must retain all 24 processes, 792 launches and 25,344 exact
FP32 output words. Both formats must independently satisfy the unchanged 95%
median host-time rule and every measured pair's host-time and modeled-cycle
constraints. A valid complete experiment may reject that performance hypothesis.
No sample may be omitted or replaced to obtain a favorable result. P06-A02/A03,
the vendor integration gate and physical-device evidence remain separate.

The primary host metric is the instrumented warm serial-operation interval;
it is not an uninstrumented runtime or physical-device timing claim. Both the
qualification result and a possible satisfied/not-satisfied hypothesis remain
separate from P06 acceptance. The [measurement review](agents/w07_a03.md) and
[sampling review](agents/w07_a06.md) explain those interpretation limits.
