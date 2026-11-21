# P06 qualification handoff

## Resume here

The selected step qualified the original cold SimX baseline, repaired timing
validation and added a reusable full-matrix analyzer. **Only P06-A01 is accepted;
P06 and P06-T01 remain `in_progress`, with A02/A03 open.** Read the
[qualification audit](p06-qualification-audit.md),
[original packet](evidence/p06-baseline/README.md) and
[acceptance decision](evidence/p06-baseline/acceptance.json) for the reviewed scope.

| Identity | Exact scope |
|---|---|
| `84b6ca0ca75fba248ba330642bbf8764db3d459c` | Accepted original execution; run `44901052221`, attempt 1 |
| `9036b379e3dbdf2b68d1590ca37a47cbf099b7b4` | Published analyzer and timing-validation implementation checkpoint |
| `9b02c09a2cd249582632d02192cca3357f41e655` | Local reviewed checkpoint used for detached host validation |
| `43b8b18f4bb4d6dab557b18a4b73ef17a2699664` | Identical tree of the published and local implementation checkpoints |

The [implementation validation packet](evidence/p06-analysis-validation/README.md)
is the live source for publication receipts, exact tested revisions, local/hosted
outcomes and any fresh-artifact replay. Consult it before making a final
validation claim; implementation validation does not reassign original acceptance.
Use `git rev-parse HEAD` to identify the integration checkout containing this
handoff; validation remains bound to the exact source identities above.

All **60 agent assignments across ten waves are complete**, with six completed
assignments per wave. The [execution ledger](p06-qualification-agent-execution.json)
retains each actual receipt, raw and canonical hashes, and explicit source/scope.
The agent count does not expand any execution or acceptance claim.

## What is established

The accepted RV64 `p02-tfr` SimX suite covers three matmul shapes and the fixed
batch-16 model in FP16/BF16: eight workloads, 48 processes and 72 launches,
including 40 measured processes and 60 measured launches. Each invocation has a
fresh context; a retained warm-up does not establish warm-cache measurements.
All 45 counter rows retain their meanings: 33 available and 12 unavailable.
Counts cover whole contexts, including all three model launches.

The [analyzer](../../ci/project/p06_analyze.py) replays both digest-pinned archives,
checks complete compatible inventories and derives six per-sample diagnostics
with measured-only statistics. The
[analysis contract](../designs/native_baseline_analysis_v1.md) defines input
identities, compatibility, exact ratio operands, null handling and output scope.
It executes no archived code and grants no automatic acceptance.

The [record validator](../../ci/project/p06_records.py) now requires successful
model traces to satisfy both serial containment bounds:

1. Creation + accumulated advance + accumulated close must fit the process
   receipt duration plus exactly **1,000 ns**.
2. Native stage submit + accumulated wait + comparison + close, plus bridge,
   bridge comparison, assembly and output comparison, must fit accumulated
   advance, with **no additional allowance**.

Exact retained decimal seconds determine the process bound. Accumulated waits
are not multiplied by call counts. Nested observer intervals and event profiles
that overlap host waits are excluded from these sums. Original measurements and
summaries remain unchanged. The separately reproduced approximately 100 ms
supervisor exit-observation delay cannot be subtracted from original durations:
their exact exit timestamps were not retained. No fine-grained host speedup,
causal bottleneck, optimization or physical performance is established.

## Reproduction prerequisites and commands

Run governance and retained-data checks from the source root. Use Linux,
Python 3.12 standard library, Git, Bash, make and a native C++17 compiler with
UBSan support/runtime for the full host suite; keep at least 1 GiB free temporary
storage. See the [developer guide](developer-guide.md) and
[governance workflow](../../.github/workflows/project-governance.yml).
Governance preflight alone does not establish compiler/UBSan readiness.
These checks need no GPU build tree, RISC-V tools, simulator, vendor toolchain or
initialized submodules. Historical dependency repositories are not prerequisites
for the ordinary full host suite or P06 archive analysis.

```sh
git status --short
git rev-parse HEAD HEAD^{tree}
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 ci/project/check_baseline_packets.py
timeout 1200s python3 -m unittest discover -s ci/project -p 'test_*.py'
```

Use the [packet reproduction command](evidence/p06-baseline/README.md#reproduce-the-full-matrix-analysis)
for original-archive analysis: canonical absolute ZIP paths, both externally
pinned SHA-256 digests, original source `84b6ca0ca75fba248ba330642bbf8764db3d459c`
and a new output path are required. Preserve command exits and tested source
identity; the commands above are instructions, not additional passing results.

The optional [historical source auditor](evidence/p06-baseline/reviews/audit_sources.py)
has stronger prerequisites: complete, preseeded, non-partial Git repositories
containing the original main-repository revision and the pinned `ramulator`,
`softfloat`, `spdlog` and `yaml-cpp` objects beneath `--vendor-root`. Use the
[source proof](evidence/p06-baseline/reviews/source-provenance.json) for identities
and the packet README for its exact invocation. It issues no explicit fetch and
executes no archived code, but does **not enforce network isolation** around Git;
a partial clone can attempt a lazy fetch for missing objects. Do not treat a
shallow checkout without the historical objects as sufficient for this audit.

## Immediate bounded next action

Review the completed implementation validation at its exact source, then freeze the
[serial workspace amortization proposal](p06-next-experiment-proposal.md): its
manifest, [draft ownership and failure matrix](p06-ownership-review-matrix.md),
and separate warm-context measurement schema. The proposal is a draft, with no selected final reference/candidate
commits or optimization result. Resolve native multiple-live-operation ownership
before implementing reuse; completed wait alone must not imply lease release.
Preserve the original cold baseline and require matched numerical inputs,
repetitions, source/artifact identities and rejection criteria before evaluation.

| Open obligation | Required next evidence |
|---|---|
| P06-A02 | Matched before/after correctness, native RTL and applicable parity/performance gates; synchronized SimX/RTL changes |
| P06-A03 | Reviewed target budget and synthesis/resource/timing reports with predictions separated from measurements |
| P01-A03 | Qualified vendor XRT `hw_emu` tools/platform and integration evidence; still required before P07 acceptance |
| Inherited DSP failure | Attribution and resolution of the unchanged 267 -> 283 DSP area-gate finding |
| Physical FPGA/silicon | Identified hardware execution and measurements; no physical speed, power or energy result exists here |

Keep the native execution budget at two jobs, 4 GiB polled RSS and 15 GiB disk
reserve with bounded logs/deadlines. No golden data, tolerance, acceptance gate,
toolchain pin or resource limit is relaxed by this handoff.
