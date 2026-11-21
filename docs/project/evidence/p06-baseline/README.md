# P06 original native baseline qualification

This packet retains the complete FP16/BF16 baseline executed at
[`84b6ca0ca75fba248ba330642bbf8764db3d459c`](https://github.com/baabi-boo/AI-GPU/commit/84b6ca0ca75fba248ba330642bbf8764db3d459c)
by [P06 Native Baseline run 44901052221, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44901052221).
The [acceptance decision](acceptance.json) and independent
[acceptance review](reviews/acceptance-review.json) define the P06-A01 scope.
P06 remains `in_progress`; A02/A03 are separate obligations.

## Original execution and reviewed results

The configuration is RV64 `p02-tfr`, SimX timing mode with native TFR arithmetic,
one cluster with one core, four warps of four threads, issue width one and the
benchmark performance observer. The unchanged accepted applications execute
three matmul shapes and the fixed batch-16 `16 -> 8 -> 4` model in each format.

| Inventory | Full two-format experiment |
|---|---:|
| Workloads | 8 |
| Retained warm-up processes / launches | 8 / 12 |
| Measured processes / launches | 40 / 60 |
| Total processes / launches | 48 / 72 |
| Exact native output-word comparisons | 4,608 |
| Bridge-word / assembled-output comparisons | 768 / 768 |
| Counter rows per sample | 45: 33 available, 12 unavailable |

Every invocation starts a fresh process and device context. All samples,
including warm-ups, are checked. Counter values are identical across all six
invocations of each workload in the original packets. Only the five declared
measurements contribute to descriptive statistics.

| Workload, in either format | Active core cycles | Retired macroinstructions | Logical tensor bytes, including poison |
|---|---:|---:|---:|
| Matmul `(8,4,8)` | 5,952 | 509 | 448 |
| Matmul `(8,4,16)` | 6,339 | 559 | 640 |
| Matmul `(16,8,16)` | 6,405 | 2,208 | 1,792 |
| Fixed model | 18,189 | 3,226 | 2,688 |

These are whole-context modeled counts. The model includes three launches.
They are not per-stage latency, physical throughput, bandwidth, power or energy.
The [analysis](reviews/analysis.json) retains raw per-sample counters, six defined
diagnostics, exact logical accounting, host intervals and measured-only statistics.

## Evidence map

- [Archive index](archive-index.json): original GitHub artifact IDs, byte sizes,
  externally observed SHA-256 values and exact execution identity.
- [Original FP16 ZIP](archives/simx-fp16.zip) and
  [original BF16 ZIP](archives/simx-bf16.zip): retained without rewriting.
- [Hosted observations](hosted/observation.json) and
  [governance log](hosted/governance.log): both native jobs and all six workflows
  succeeded at the recorded source; its host suite ran 2,401 tests in 847.900 s.
- [Earlier attempt](hosted/prior-attempt.json) and
  [failed governance log](hosted/prior-failed-governance.log): the preceding
  `fd7129a` source failed one stale budget assertion after 2,401 tests. Its native
  run succeeded separately. Neither result is reassigned to `84b6ca0`.
- [Source proof](reviews/source-provenance.json): all 979 source bodies per
  format match Git content, including separately identified FetchContent headers.
- [Raw measurement review](reviews/measurement-review.json): independent
  numerical, dispatch, cleanup, counter, sampling and summary reconciliation.
- [Timing summary conservation](reviews/timing-summary-conservation.json): the
  stricter reader preserves the original valid measurements and summaries.
- [Supervisor observation](reviews/supervisor-observation.json): a separately
  reproduced host-monitor timing limitation, not a GPU performance result.

The [development audit](../../p06-qualification-audit.md) describes findings,
implementation decisions and the next bounded experiment. The
[analysis contract](../../../designs/native_baseline_analysis_v1.md) defines the
implemented CLI, compatibility checks, metric formulas and limitations.

## Reproduce the full-matrix analysis

Run from the repository root. No GPU build tree, simulator, vendor tool or
archived executable is needed:

```sh
P06_REPO_ROOT=$(pwd -P)
P06_REVIEW_OUTPUT=$(mktemp -d)
python3 ci/project/p06_analyze.py \
  --fp16-archive "$P06_REPO_ROOT/docs/project/evidence/p06-baseline/archives/simx-fp16.zip" \
  --fp16-sha256 aaf54ff60b8f4f889264fb3efa4249cbdb02a7fad2b20124b4ad0ba9ae2f41dc \
  --bf16-archive "$P06_REPO_ROOT/docs/project/evidence/p06-baseline/archives/simx-bf16.zip" \
  --bf16-sha256 f19f174879e2c1fb120a3328ec919d42b4d67f59ba056ceb6e0b6f5607f4996b \
  --source-revision 84b6ca0ca75fba248ba330642bbf8764db3d459c \
  --output "$P06_REVIEW_OUTPUT/analysis.json"
```

The analyzer replays both originals before combining them. It requires matching
source, tools, dependencies, configuration, sampling and hosted-run identities;
format-specific bindings remain separate. It recomputes the full sample summary
and derives metrics per sample. Existing output files are never overwritten.
The JSON explicitly declares no new native execution, automatic acceptance,
optimization result or phase completion.

The independent raw-data audit is
`python3 docs/project/evidence/p06-baseline/reviews/audit_measurements.py --repo "$P06_REPO_ROOT" --output "$P06_REVIEW_OUTPUT/measurements.json"`.
The independent source audit is
`python3 docs/project/evidence/p06-baseline/reviews/audit_sources.py --repo "$P06_REPO_ROOT" --vendor-root /absolute/pinned-vendor-repositories --output "$P06_REVIEW_OUTPUT/sources.json"`.
Its vendor root must contain `ramulator`, `softfloat`, `spdlog` and `yaml-cpp`
Git repositories with the immutable commits recorded in the source proof.
That auditor is offline and does not obtain repositories or execute their code.

## Limits and continuation

Independent review found and repaired two timing-containment gaps: disjoint
model lifecycle intervals must collectively fit the process receipt, and serial
stage/bridge/assembly intervals must collectively fit accumulated advance time.
Exact decimal conversion preserves the existing 1,000 ns process allowance.
Overlapping native event profiles are excluded from these sums.

The original process supervisor can delay observing exit by approximately
100 ms after output EOF. Original durations remain untouched and include
supervision, startup, validation, instrumentation and cleanup. No guessed delay
is subtracted and no fine-grained host speedup is inferred from them.

Source review verified all retained bodies and five top-level gitlinks. Three
unrelated nested CVFPU gitlinks were not fetched, and historical immutability of
FetchContent tags is not asserted. Tool and dependency binary identities are
retained; source consistency alone does not prove their build process.

The next experiment must freeze a small-workload amortization hypothesis and
matched before/after criteria. Native multiple-live-operation ownership must be
resolved before any queue-concurrency or reuse claim. P06-A02 needs correctness,
native RTL and applicable parity/performance results. A03 needs a reviewed
resource/timing budget and synthesis reports. The inherited 267 -> 283 DSP
finding, P01-A03 vendor `hw_emu` blocker and physical-hardware obligations remain.
