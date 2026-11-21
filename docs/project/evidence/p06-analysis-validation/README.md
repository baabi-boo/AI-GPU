# P06 analysis implementation validation

This packet records development verification for the new analyzer, serial timing
validation and accompanying integration work. It is separate from the
[original baseline acceptance](../p06-baseline/acceptance.json), whose native
execution remains attributed to source `84b6ca0ca75fba248ba330642bbf8764db3d459c`.

## Reviewed implementation checkpoint

The [publication receipt](checkpoint-publication.json) binds published commit
`9036b379e3dbdf2b68d1590ca37a47cbf099b7b4` to the identical reviewed tree
`43b8b18f4bb4d6dab557b18a4b73ef17a2699664` at local checkpoint
`9b02c09a2cd249582632d02192cca3357f41e655`. The shell Git push lacked
credentials; the connected GitHub Git-data API published the verified tree using
a non-force update with the expected original parent. No concurrent remote
change was overwritten.

## Verified implementation results

| Check | Exact result and source |
|---|---|
| Local full host suite | 2,449 tests, `OK`, no failures/errors/skips; 1,114.149 seconds, supervisor 1,116.052 seconds within the unchanged 1,200-second bound. Tested local `9b02c09` in a clean detached checkout. |
| Hosted full host suite | 2,449 tests, `OK`, no failures/errors/skips; 663.127 seconds. Published `9036b37`, run `44911907504`, job `136869306715`. |
| Fresh P06 baseline | SimX FP16 and BF16 jobs succeeded at `9036b37`, run `44911907463`, attempt 1; both original packets pass the new analyzer and strict timing checks. |
| Bounded integration workflows | P04 Native Model: four successful jobs; P05 Installed Python: two; P05 Installed PyTorch: two, all at `9036b37`. |
| Later workflow path-filter change | Eleven focused existing tests passed after adding the analysis contract to both governance event filters; independent reviewer repeated the same eleven successfully. No permissions, job steps or budgets changed. |

The [local log](candidate-governance.log) and [supervisor receipt](candidate-governance.json)
retain the complete local result. The [hosted log](hosted-governance.log) and
[workflow observation](hosted-workflows.json) retain source, commands, step identity,
counts and exact observation scope. At that observation, general CI `44911907451`
was still queued/in progress with no conclusion; that snapshot is not a success
claim for the general CI matrix. A [later CI observation](hosted-ci-observation.json)
retains further completed and pending cells without changing that historical snapshot.
The [last prepublication observation](hosted-ci-final-observation.json) records
26 successful and 16 running jobs at its stated observation time, with no overall
CI conclusion. It also distinguishes predicted publication triggers from execution.

The [verification index](verification-index.json) binds 50 selected stable files,
including all four original/fresh archives and all 20 original acceptance pins.
It deliberately excludes mutable navigation and the execution ledger. The
[release-candidate review](release-candidate-review.json) and
[base-copy impact review](change-impact-review.json) preserve their exact candidate
scope; the latter classifies the named integration commit as R2, with no R3 findings.

The full suites cover the implementation checkpoint. The later positive workflow
filter, navigation, review records and planning documents are identified separately;
full-suite results are not reassigned to a later integration revision. The final
integration also receives current governance/link validation and an independent
base-policy impact classification. No native kernel, runtime, RTL, SimX model,
golden data, toolchain pin, tolerance or resource budget changed.

## Fresh original packet and regression comparison

The [archive index](archive-index.json) pins the new unchanged
[FP16 ZIP](archives/simx-fp16.zip) and [BF16 ZIP](archives/simx-bf16.zip).
The [hosted provenance observation](hosted-p06-observation.json) independently
matches workflow, job, artifact, source, attempt, format, digest and byte size.
The archives' `job.json` files record initial workflow identity; their literal
`native_execution: not_run` marker is preserved. Completed execution steps,
reports and numerical logs are separately checked as the later execution evidence.

The [full analysis](checkpoint-analysis.json) and
[independent comparison](checkpoint-analysis-comparison.json) cover all eight
workloads and 48 samples. All 2,160 modeled counter entries and 288 derived metric
records match the accepted original baseline. All 48 process durations differ;
316 of 324 host timing values differ. Every original/fresh value, warm-up,
measurement and descriptive delta remains intact. No supervisor delay is
subtracted, and no host speedup or new optimization is claimed.

The [source review](checkpoint-source-review.json) verifies 979 retained bodies
per format: 786 main-repository files and 193 dependency files. Exactly 978 are
unchanged from the qualified originals; only `ci/project/p06_records.py` differs,
and its body matches Git at `9036b37`. Tools, dependency snapshots and source pins
remain unchanged. The newly added analyzer/tests are outside that frozen retained
inventory and are covered by their independent reviews and host suites above.
The original baseline acceptance and its artifact hashes remain unchanged.

## Replay the fresh checkpoint analysis

Run from a complete checkout with Python 3.12. Use canonical absolute archive paths
without symlinks and a fresh output path. This reads retained data; it executes no
archived code and grants no acceptance:

```sh
P06_REPO=$(pwd -P)
python3 ci/project/p06_analyze.py \
  --fp16-archive "$P06_REPO/docs/project/evidence/p06-analysis-validation/archives/simx-fp16.zip" \
  --fp16-sha256 c552c4cc540df485aa9b3320d9098ff03f66f4973da1e9c788a1c9b0ba7b1e62 \
  --bf16-archive "$P06_REPO/docs/project/evidence/p06-analysis-validation/archives/simx-bf16.zip" \
  --bf16-sha256 ac49841228abdfd3b1b11a1d68c058e53cf406dcf28ea2af8dab0d7118b6b51a \
  --source-revision 9036b379e3dbdf2b68d1590ca37a47cbf099b7b4 \
  --output /tmp/p06-checkpoint-analysis-new.json
```

Recorded report paths describe the original review environment. Relocating the
checkout or archives changes path metadata, not their externally pinned bytes.
The [handoff](../../p06-qualification-handoff.md) distinguishes ordinary host
prerequisites from the optional historical source auditor's Git-object needs.

## Licensing and retained notices

The original ZIP bytes retain source notices and are not rewritten to add files.
They contain no standalone license-file members. See the
[project license](../../../../LICENSE), [upstream attribution](../../../../README.md),
[third-party notices](../p05-python/THIRD_PARTY_NOTICES.md),
[retained license texts](../p05-python/licenses/) and
[dependency-header identity checks](../p05-python/licenses/header-match-checks.json).
