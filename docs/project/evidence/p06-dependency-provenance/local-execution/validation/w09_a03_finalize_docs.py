from pathlib import Path
root=Path('/workspace/ai-gpu-next')
def once(text,old,new):
    assert text.count(old)==1,(old[:95],text.count(old))
    return text.replace(old,new,1)

p=root/'docs/project/status.md';s=p.read_text()
start=s.index('**Current bounded step:');end=s.index('[Local attempt 03]',start)
s=s[:start]+'''**Fresh dependency compilation-to-loader provenance is established for the
complete local attempt 04. The next bounded step is the separately versioned
complete counter-qualification contract and explicit admission path.** The
[execution summary](evidence/p06-dependency-provenance/local-execution/validation/local-attempt-04-execution-summary.json)
records all five stages passing at
`0f9aaa36d46364c297254164f5dab0d4f0e88349` in 894.591061 seconds. The original
joins **413 dependency tool operations and 819 child observations** to the fresh
products, both managed format builds and their loaded libraries. The managed
FP16/BF16 × allocation-policy matrix passed **four processes, 132 launches and
4,224 checked FP32 words**, with zero mismatches.

The separate positive-pending probe observed both scalar contexts, and its
always-zero control failed for the exact required assertion. The separate
alternate-library process passed **33 launches and 1,056 checked words** while
correctly rejecting the original provenance expectation. Those controls are
outside the four-process managed population. The
[complete public local replay](evidence/p06-dependency-provenance/local-execution/validation/local-attempt-04-replay-summary.json)
passed from clean reader `ba2d649d4150e046c2ba610de02725d9d062b1be` in
18.657440 seconds, with the original ZIP unchanged, no prohibited execution/network
events, `native_execution="not_run"` and `retained_code_executed=false`.
Independent [dependency/source projection](evidence/p06-dependency-provenance/local-execution/agents/w09_a06.md),
[native matrix](evidence/p06-dependency-provenance/local-execution/agents/w10_a01.md)
and [both-control](evidence/p06-dependency-provenance/local-execution/agents/w10_a03.md)
reviews establish their distinct original-evidence scopes.

The [local packet](evidence/p06-dependency-provenance/local-execution/README.md),
[versioned local contract](../designs/local_dependency_execution_v1.md) and
[runbook](evidence/p06-dependency-provenance/local-execution/runbook.md) retain the
exact external pins and limitations. The successful original ZIP has **5,597
members**, **47,632,218 bytes** and SHA-256
`d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`.
This is explicitly local SimX provenance, not an authenticated hosted run,
complete counter qualification or warm/phase acceptance. All seven current
qualification, readiness, warm and acceptance fields remain false.

'''+s[end:]
s=once(s,'''The corrected fresh attempt 04 is executing at
`0f9aaa36d46364c297254164f5dab0d4f0e88349`. Complete original/control replay and
review remain required before advancing this bounded action. The later
`8d735eba0016cdc64592d9c40a98e6b52574e64b` checkpoint repairs hosted cache relocation
and synthetic replay guards; those corrections have separate regression evidence
and are not attributed to attempt 04's frozen native source.''','''Keep execution and review sources separate. Attempt 04 executed frozen
`0f9aaa36`; `8d735eba0016cdc64592d9c40a98e6b52574e64b` later repairs hosted cache
relocation and synthetic replay guards. Reader checkpoint `ba2d649d` accounts
for the two actual `ramulator.stats.log` side outputs that the initial complete
replay rejected. The reviewed correction requires the exact bounded files and
bound destructor behavior, treats their bytes as opaque diagnostics, and retains
strict complete-inventory checks. It changes neither the original nor its native
execution. The initial replay failure and failed local attempts remain preserved;
these corrections do not establish a successful hosted retry.''')
s=once(s,'| Synthetic bridge/path guards in the actual GitHub checkout and temporary-path layout | Corrected test bytes committed as `8d735eba` | **7 passed**; the uncorrected three bridges failed there |','''| Synthetic bridge/path guards in the actual GitHub checkout and temporary-path layout | Corrected test bytes committed as `8d735eba` | **7 passed**; the uncorrected three bridges failed there |
| Complete control inventory/opaque diagnostic correction | Corrected reader/test bytes committed as `ba2d649d` | **22 distinct tests passed**: 14 existing and eight new; independent reruns overlap this population |''')
s=once(s,'''and [independent hosted/test review](evidence/p06-dependency-provenance/local-execution/agents/w09_a02.md)
retain the source identities and limits. These overlapping runs are not added
into a unique-test total; the full 4,256-test run does not establish a full-suite
pass at either later correction checkpoint.''','''[independent hosted/test review](evidence/p06-dependency-provenance/local-execution/agents/w09_a02.md)
and [control-reader correction review](evidence/p06-dependency-provenance/local-execution/agents/w10_a03.md)
retain the source identities and limits. These overlapping runs are not added
into a unique-test total; the full 4,256-test run does not establish a full-suite
pass at any later correction checkpoint.''')
s=once(s,'**Development sequence after the complete fresh-original review:** implement a','**Next bounded development:** implement a')
s=once(s,'| P06 — Memory and performance scaling | `in_progress` | A01 is preserved; fresh local provenance has successful dependency/native subpackets but still needs a complete enclosing original/control review; separately versioned 33-selector/40-component qualification, qualified warm execution and A02/A03 remain open |','| P06 — Memory and performance scaling | `in_progress` | A01 is preserved; complete fresh local dependency/native/control original and inert replay pass independent review; separately versioned 33-selector/40-component qualification, qualified warm execution and A02/A03 remain open |')
s=once(s,'''controls. The fresh retry and its full original/control review are tracked above.''','''controls. Attempt 04 subsequently completed all five stages; its complete public
local replay and independent dependency/native/control reviews now pass as
recorded above. The original and its evidence population remain unchanged.''')
s=once(s,'''the unchanged strict source inventory. The path-guard repair is test-only.
Keep every execution, replay and regression result attached to its actual source.''','''the unchanged strict source inventory. The path-guard repair is test-only.
The final reader correction accounts for the exact opaque runtime diagnostics
emitted by the already bound destructor; it interprets no numerical/performance
value and preserves full inventory equality. Keep every execution, replay and
regression result attached to its actual source.''')
s=once(s,'''**P06-T01 — finish the complete fresh local original/control review, then freeze
the separately versioned complete counter-qualification contract.** The current
execution result is stated at the top of this status; a passing dependency/native
subpacket does not repair a failed enclosing original or supply unrun controls.
Follow the [local runbook](evidence/p06-dependency-provenance/local-execution/runbook.md),
[dependency handoff](p06-dependency-provenance-handoff.md) and
[independent next-step audit](evidence/p06-dependency-provenance/local-execution/agents/w07_a03.md).

Once the complete fresh original and its externally pinned inert replay pass
independent review, the next implementation slice is a pure fail-closed validator
and explicit admission route that joins all ten lifetime premises to the exact
33-selector/40-component source, configuration, build and loaded-binary scope.''','''**P06-T01 — freeze and implement the separately versioned complete
counter-qualification contract, inert validator and explicit admission path.**
The complete fresh attempt-04 original, both separate controls, public local
replay and independent original reviews now pass in the
[local evidence packet](evidence/p06-dependency-provenance/local-execution/README.md).
Follow the [dependency handoff](p06-dependency-provenance-handoff.md),
[independent next-step audit](evidence/p06-dependency-provenance/local-execution/agents/w07_a03.md)
and [qualification plan](p06-mpm-qualification-plan.md).

The next implementation slice is a pure fail-closed validator and explicit
admission route that joins all ten lifetime premises to the exact 33-selector /
40-component source, configuration, build and loaded-binary scope.''')
p.write_text(s)

p=root/'docs/project/backlog.md';s=p.read_text()
s=once(s,'''**Current bounded task: finish the complete fresh local dependency/native
original and independent control/replay review.** Then implement the separately
versioned **33-selector / 40-component / ten-premise qualification contract**
for the existing managed caller. The [current status](status.md) gives the actual
execution checkpoint; the [local runbook](evidence/p06-dependency-provenance/local-execution/runbook.md)
and [dependency handoff](p06-dependency-provenance-handoff.md) define reproduction,
external pins and the ordered handoff. Complete qualification precedes the
24-process warm experiment.''','''**Current bounded task: implement the separately versioned 33-selector /
40-component / ten-premise qualification contract, inert validator and explicit
admission path for the existing managed caller.** The complete fresh local
attempt-04 original, both separate controls and full public replay now pass
independent review in the
[local evidence packet](evidence/p06-dependency-provenance/local-execution/README.md).
The [current status](status.md),
[dependency handoff](p06-dependency-provenance-handoff.md) and
[qualification plan](p06-mpm-qualification-plan.md) define the remaining sequence:
freeze and independently review the new qualification rules, execute their fresh
four-process preflight, and only then run the unchanged 24-process warm experiment.''')
s=once(s,'''failed originals. Fresh attempt 04 uses the corrected parser checkpoint
`0f9aaa36d46364c297254164f5dab0d4f0e88349`; its complete result remains pending
at this documentation checkpoint.''','''failed originals. [Fresh attempt 04](evidence/p06-dependency-provenance/local-execution/validation/local-attempt-04-execution-summary.json)
passed all five stages at `0f9aaa36d46364c297254164f5dab0d4f0e88349` in
894.591061 seconds, including 413 dependency operations, four managed processes,
132 launches and 4,224 exact words. The pending/always-zero controls and the
numerically correct but provenance-rejected alternate process remain separate;
the latter executed 33 launches and 1,056 words. The
[full public local replay](evidence/p06-dependency-provenance/local-execution/validation/local-attempt-04-replay-summary.json)
passed from clean reader `ba2d649d4150e046c2ba610de02725d9d062b1be` in
18.657440 seconds without executing retained content or changing the original.''')
s=once(s,'''40-test preparation/workflow and seven-test real-hosted-layout passes. Do not
sum overlapping tests or attribute a full-suite pass to a later source.''','''40-test preparation/workflow and seven-test real-hosted-layout passes. The later
`ba2d649d` reader correction has 22 distinct control/inventory regression passes
and independent actual-control review. It accounts for two exact opaque runtime
diagnostic files omitted by the earlier reader; the first public replay failure
and original bytes remain preserved. Do not sum overlapping tests or attribute
a full-suite pass to a later source.''')
s=once(s,'''products, managed builds and loaded libraries. Complete this task only with a
successful complete original, separate pending/always-zero and alternate-library
controls, externally pinned full inert replay and independent review. Preserve
the four-process, 132-launch, 4,224-word population and all failed originals.
Local execution remains explicitly local; historical host diagnostics and
GitHub cache/job metadata retain their separate meanings.

After that review, the''','''products, managed builds and loaded libraries. The complete attempt-04 original,
separate pending/always-zero and alternate-library controls, full externally
pinned local replay and independent review establish this bounded provenance
result. Preserve its four-process, 132-launch, 4,224-word managed population,
separate control counts and all failed originals. Local execution remains
explicitly local; historical host diagnostics and GitHub cache/job metadata
retain their separate meanings.

With that scoped prerequisite recorded, the''')
s=once(s,'''supplies explicit local preparation/execution/replay; complete its original
review before the separately versioned complete qualification contract and
required fresh preflight.''','''establishes the complete fresh dependency/native/control original and inert
replay within its declared scope. The next step is the separately versioned
complete qualification contract and required fresh preflight.''')
s=once(s,'| **P06-T01 — Measured optimization — in progress** | Complete the fresh local original/control review, then freeze and independently review a separately versioned 33-selector/40-component qualification contract, exact source/binary premise projection and fail-closed admission/final validator.', '| **P06-T01 — Measured optimization — in progress** | Freeze and independently review a separately versioned 33-selector/40-component qualification contract, exact source/binary premise projection and fail-closed admission/final validator, using the scoped completed provenance original as a prerequisite.')
p.write_text(s)

p=root/'docs/project/p06-dependency-provenance-handoff.md';s=p.read_text()
start=s.index('**Finish the complete');end=s.index('[Local attempt 03]',start)
s=s[:start]+'''**The complete fresh local dependency/native/control original and full inert
replay pass independent review. The next bounded development is the separately
versioned complete counter-qualification contract and explicit admission path.**
The [local execution summary](evidence/p06-dependency-provenance/local-execution/validation/local-attempt-04-execution-summary.json)
records all five stages passing at frozen
`0f9aaa36d46364c297254164f5dab0d4f0e88349` in 894.591061 seconds. Fresh dependency
receipts bind **413 tool operations and 819 child observations** to the exact
products, both managed builds and actual loader records. The unchanged
FP16/BF16 × allocation-policy matrix passed **four processes, 132 launches and
4,224 checked FP32 words**, with zero mismatches.

The separate positive-pending process observed both scalar contexts; the
always-zero process failed for the required missing-observation assertion.
The separate alternate-library process passed **33 launches and 1,056 exact
words** while its loader witness rejected the original provenance expectation.
These controls are outside the managed population. The
[public local CLI replay](evidence/p06-dependency-provenance/local-execution/validation/local-attempt-04-replay-summary.json)
passed from clean reader `ba2d649d4150e046c2ba610de02725d9d062b1be` in
18.657440 seconds. It checked the exact caller-pinned envelope and all subpackets
in one bounded archive, completed closing stability checks and observed zero
prohibited events, with `native_execution="not_run"` and
`retained_code_executed=false`.

The [dependency/source projection](evidence/p06-dependency-provenance/local-execution/agents/w09_a06.md),
[complete native matrix review](evidence/p06-dependency-provenance/local-execution/agents/w10_a01.md)
and [both-control review](evidence/p06-dependency-provenance/local-execution/agents/w10_a03.md)
retain independent scoped findings. The complete original has **5,597 members**,
**47,632,218 compressed bytes** and SHA-256
`d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`.
Use the [local packet](evidence/p06-dependency-provenance/local-execution/README.md)
for all external pins and the [runbook](evidence/p06-dependency-provenance/local-execution/runbook.md)
for reproduction. The explicit [local contract](../designs/local_dependency_execution_v1.md)
does not invent GitHub job/cache identity or authenticate the producer. This
bounded provenance result leaves all seven qualification, readiness, warm and
acceptance claims false.

'''+s[end:]
s=once(s,'''Fresh attempt 04 is executing at
`0f9aaa36d46364c297254164f5dab0d4f0e88349`, whose explicit report-token bound was
independently reviewed. Its full control/replay result is not yet established
at this checkpoint. The later `8d735eba0016cdc64592d9c40a98e6b52574e64b` code
checkpoint fixes hosted-only preparation order and synthetic path guards; its
regressions remain separate from that frozen native source.''','''The later `8d735eba0016cdc64592d9c40a98e6b52574e64b` code checkpoint fixes
hosted-only preparation order and synthetic path guards; those regressions are
separate from frozen attempt-04 execution at `0f9aaa36`. Reader checkpoint
`ba2d649d` accounts for the exact `ramulator.stats.log` side outputs omitted by
the initial reader and synthetic fixtures. Its correction binds the destructor,
requires both exact bounded nonempty files at their actual runtime paths, treats
them only as opaque diagnostics and preserves strict complete inventories.
Neither the original nor any numerical, timing or provenance premise was changed.
The initial full-replay failure remains preserved; the corrected public CLI pass
is a new reader result over the same successful execution original.''')
s=once(s,'''[independent review](evidence/p06-dependency-provenance/local-execution/agents/w09_a02.md).
These overlapping runs do not establish a later full-suite pass or native
qualification.''','''[independent review](evidence/p06-dependency-provenance/local-execution/agents/w09_a02.md).
The final control-reader correction has 22 distinct passing tests (14 existing
plus eight new), with independent eight-test reruns overlapping that population
and [actual-control review](evidence/p06-dependency-provenance/local-execution/agents/w10_a03.md).
These overlapping runs do not establish a later full-suite pass or native
qualification.''')
s=once(s,'''After the complete fresh original/control replay and independent review, implement
one separately versioned qualification record, inert reader and explicit
admission/final-validation route.''','''The complete fresh original/control replay and independent review now establish
the bounded provenance prerequisite described above. Implement one separately
versioned qualification record, inert reader and explicit admission/final-validation
route as the next development slice.''')
p.write_text(s)
print('Finalized current actions and source-scoped completion in all three owned documents.')
