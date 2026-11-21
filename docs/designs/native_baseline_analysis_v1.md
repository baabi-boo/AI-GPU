# Native baseline analysis contract v1

The [P06 analyzer](../../ci/project/p06_analyze.py) checks and analyzes the complete
two-format experiment defined by the [native benchmark contract](native_benchmark_v1.md)
and its [frozen manifest](../../ci/project/p06_benchmark_contract.json). It consumes
original retained archives and external identities. It does not run native code
or make an acceptance decision.

## Inputs and reproduction

The Python API is
`analyze_archives(fp16_archive, fp16_sha256, bf16_archive, bf16_sha256, *, expected_revision)`.
Archive arguments are canonical absolute `Path` objects without symlink
components. Each digest is the externally obtained original ZIP SHA-256; the
revision is the full source commit that produced both packets. A saved analysis
or summary JSON is not an input substitute.

From the repository root, analyze the originals identified by the
[archive index](../project/evidence/p06-baseline/archive-index.json):

```sh
P06_REPO_ROOT=$(pwd -P)
P06_REPORT_DIR=$(mktemp -d)
python3 "$P06_REPO_ROOT/ci/project/p06_analyze.py" \
  --fp16-archive "$P06_REPO_ROOT/docs/project/evidence/p06-baseline/archives/simx-fp16.zip" \
  --fp16-sha256 aaf54ff60b8f4f889264fb3efa4249cbdb02a7fad2b20124b4ad0ba9ae2f41dc \
  --bf16-archive "$P06_REPO_ROOT/docs/project/evidence/p06-baseline/archives/simx-bf16.zip" \
  --bf16-sha256 f19f174879e2c1fb120a3328ec919d42b4d67f59ba056ceb6e0b6f5607f4996b \
  --source-revision 84b6ca0ca75fba248ba330642bbf8764db3d459c \
  --output "$P06_REPORT_DIR/analysis.json"
```

The command creates the report only after successful analysis. Output creation
is exclusive: an existing file is preserved and causes a nonzero result. Without
`--output`, the full JSON report is written to standard output. Invalid archives,
identities, records or incompatible packets fail; a partial format does not
produce a successful full-matrix report. These are host data checks and need no
GPU build tree or simulator toolchain.

## Replay and compatibility boundary

Each archive first passes the trusted local
[retained-data replay](../../ci/project/p06_replay.py), including its original
logs, numerical checks, compiler records, configuration, sample inventory,
cleanup and recomputed summaries. The analyzer then rereads the original data
through the same digest-checking archive reader and verifies its report identity.
No archive member is extracted or executed.

The formats must share the following identities and policies:

- Complete source snapshot: revision, tree, source-file inventory, pins and
  submodule records.
- Dependency inventory, decoded contract and original manifest bytes.
- Tool names, SHA-256 values and sizes. Each packet's recorded tool paths remain
  separately validated provenance; identical binaries may have different roots.
- Contract ID and digest, sampling, observation boundaries, resource budget,
  loaded helper identities and contract limitations.
- Recorded and independently expected hardware macro maps.
- Hosted identity presence. If present, workflow/run identity must match apart
  from `P06_FORMAT`; one hosted and one non-hosted packet cannot be combined.

Format-specific bindings, fixtures and binaries remain separately qualified by
their replay. The analyzer does not require those different identities to be
equal. It combines checked samples in canonical FP16-then-BF16 order and invokes
the record summarizer again for the complete manifest.

The complete result requires eight workloads, each with one warm-up and five
measured fresh-process invocations: 48 processes and 72 launches in total,
including 40 measured processes and 60 measured launches. All warm-ups and
measurements must pass. No outlier is removed and no incomplete workload is
salvaged.

External digests identify bytes; they do not independently authenticate their
producer. GitHub run observations and source-to-Git verification remain separate
review obligations under the [acceptance policy](../project/acceptance.md).
Internally consistent synthetic records do not establish GPU execution.

## Derived metrics

The analyzer derives the following values for every checked sample before
computing statistics. Useful FLOPs and MACs come from the frozen logical workload;
one multiply plus one add counts as two FLOPs. Counter values cover the original
whole device context.

| Metric key | Formula | Meaning |
|---|---|---|
| `active_cycles_per_useful_flop` | active core cycles / useful FLOPs | Modeled active cycles per logical arithmetic operation |
| `retired_macroinstructions_per_mac` | retired macroinstructions / MACs | Macroinstruction count per logical multiply-accumulate |
| `logical_tensor_bytes` | input H2D + destination-poison H2D + tensor D2H bytes | Explicit tensor payload, including poison; excludes module/control traffic |
| `modeled_external_read_request_bytes` | external read requests × checked memory-block bytes | Modeled read-request boundary, distinct from tensor payload and host DMA |
| `modeled_external_write_request_bytes` | external write requests × checked memory-block bytes | The corresponding modeled write-request quantity |
| `useful_flops_per_logical_tensor_byte` | useful FLOPs / logical tensor bytes | Payload ratio, not a memory-controller roofline intensity |

Ratio records retain exact integer numerator and denominator, unit, finite
convenience value and an unavailable reason when needed. An unavailable operand
produces `null` with `unavailable_operand`; a zero denominator produces `null`
with `zero_denominator`. An unavailable quantity retains `null` with
`unavailable_counter`. Booleans are not accepted as integer operands. A measured
zero remains zero rather than being replaced by an unavailable value.

For each workload, only its five measured samples contribute to count, minimum,
maximum, median and population standard deviation. Ratios are computed per
sample; the implementation does not divide aggregate medians. If any measured
metric is unavailable, that metric's aggregate statistics remain `null` and the
affected sample IDs are listed. The reader never reduces a favorable available
subset silently. Original counter descriptors, null availability, host timings,
sample IDs and log identities remain in the report.

## Serial timing containment

The [record validator](../../ci/project/p06_records.py) preserves its existing
timestamp ordering, individual bounds and whole-context checks. For successful
model traces it additionally requires two sums of disjoint host scopes to fit:

1. Creation duration + accumulated advance duration + accumulated close duration
   must not exceed the process receipt duration plus exactly **1,000 ns**.
2. All native stage submit, accumulated wait, comparison and close durations,
   plus bridge, bridge comparison, assembly and output comparison durations,
   must not exceed accumulated advance duration.

The process receipt is recorded in decimal seconds rounded to six fractional digits.
Its conversion to nanoseconds uses the exact retained decimal value, preserving
the existing 1,000 ns rounding allowance at boundaries that binary floating-point
multiplication could otherwise shift. That allowance is applied once to the
process bound; the child-scope sum has no added allowance. Accumulated waits are
not multiplied by their call counts. Native event profiles overlap host waits,
and observer intervals are nested inside other scopes, so neither is added to
these sums.

## Output and interpretation

The report identifies the original archives and their source, per-format
bindings and checked inventories, common compatibility digests, full recomputed
summary, all per-sample diagnostics, metric definitions and trusted reader,
replay and analyzer source identities. Compatibility digests use original bytes
for the manifest and sorted compact canonical JSON for the other entries.

The report always declares `native_execution: "not_run"`,
`acceptance_claimed: false`, `phase_complete: false` and
`optimization_claimed: false`. A successful analysis is evidence for independent
review; it does not itself award P06-A01 or close P06-A02/A03.

Host process durations include supervision, startup, validation, instrumentation
and cleanup. The [qualification audit](../project/p06-qualification-audit.md)
documents a reproduced approximately 100 ms EOF/exit-observation delay in the
supervisor. Original records lack an exact process-exit timestamp, so no guessed
delay is subtracted. Nested host/event durations remain separately reported.

Whole-context cycles cannot be assigned to individual model stages. Request
bytes are not physical bandwidth, and a configured clock does not convert these
counts into measured hardware latency. Five repetitions do not establish tail
latency or confidence intervals. This analysis establishes neither a causal
bottleneck nor an optimization, physical throughput, power, energy, FPGA or
silicon result.
