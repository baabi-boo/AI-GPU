# P04 managed-model executor evidence

This packet records development of P04-T02 from starting revision
`041f0981b2648dd5ec1494f4c1ca0300da8b9ca6`. The implementation composes the
accepted managed matmul operations for the frozen synthetic batch-16,
bias-free 16 → 8 → 4 model. P04 remains `in_progress`; P04-A02 and P04-A03
are not accepted by the existence of this code or these host tests.

## Implementation and qualification boundary

The managed executor owns each asynchronous operation until it can be drained.
It checks the actual 128 hidden FP32 words before applying the declared host
ReLU/exact conversion, supplies the resulting bytes to the two native output
calls, and assembles the actual returned blocks in row order. No host matmul
fallback is present. Creation, partial submission, timeout, comparison,
profiling and cleanup failures remain distinguishable.

The [record contract](../../../designs/mlp_execution_records_v1.md) and strict
consumer bind observations to the fixture, clean source, generated configuration,
compiler commands, identified dependencies, native module, backend and host
application. Records include the actual inputs, outputs, encoded launch arguments,
five event results/profiles per matmul and before/after memory accounting.

The planned native matrix is:

| Dimension | Required coverage |
|---|---|
| Backends | SimX and native processor RTL |
| Input formats | FP16 and BF16, each accumulating/outputting FP32 |
| Cases per format | `seeded_dense`, `negated_dense`, `zero`, `signed_basis`, `split_boundary` |
| Repetitions per case/backend | Two, using distinct destination poison values |
| Complete matrix | 20 case/backend pairs, 40 model runs, 120 native matmul launches |
| Exact comparisons | 5,120 hidden words; 2,560 bridge words; 2,560 output-block words; 2,560 assembled-output words |
| Explicit tensor transfers | 76,800 H2D bytes including destination poison, 30,720 D2H bytes |

These are qualification requirements until actual compatible records are retained
and independently reviewed. A successful selected-variant report does not claim
the full matrix. Argument/control staging, module loading and setup traffic are
outside the explicit tensor-byte totals.

The first published implementation is
[`7167ce1`](https://github.com/baabi-boo/AI-GPU/commit/7167ce17d335ec1f50e26da9b4832c1c27013ada).
The [source map](source-map.json) records its exact tree equality with the locally
reviewed checkpoint. Initial hosted preparation stopped before native execution
because the restored `cocogfx` checkout was dirty. Investigation reproduced the
condition with its unignored build products. The
[failed preparation record](failed-attempts/7167ce1-simx-fp16/preparation.json)
preserves that blocker; it is not a numerical failure or passing model result.

After the cache correction, the first SimX/FP16 variant at `f4c6a323` completed
five cases, ten model repetitions and thirty launches. Independent numerical and
dispatch checks passed within that selected scope. Independent provenance review
found that the artifact upload omitted the required `.config.stamp` body. The
[original incomplete packet and finding](failed-attempts/f4c6a3-simx-fp16/retention-failure.json)
are retained. This successful execution does not supply a complete qualification
packet; fresh execution and upload are required after correcting retention.

## Reproduction

The dedicated `P04 Native Model` workflow runs four isolated variants, with two
jobs at a time. It restores identified existing caches, verifies the exact clean
checkout and recursive submodule metadata, moves tools outside source, and retains
preparation diagnostics and execution packets even on failure. The general native
catalog also contains `p04_mlp` SimX and RTL cells; each selects both formats.

With matching prerequisites prepared outside a clean checkout, the full runner is:

```bash
python3 ci/project/p04_execute.py run \
  --source-dir "$PWD" --tools-dir /absolute/path/to/tools \
  --work-dir /absolute/path/to/fresh-work \
  --output /absolute/path/to/fresh-packet \
  --iterations 2 --jobs 2 \
  --timeout-seconds 1800 --run-timeout-seconds 180
```

The two destination paths must not exist or overlap the checkout/tools. The runner
requires at least 4 GiB available memory and a 15 GiB free-disk reserve; commands
have a polled 4 GiB process-group RSS budget and a 16 MiB log cap. These are command
budgets, not cgroup or whole-job quotas. The hosted invocation fixes the case
deadline at 180 seconds; the reusable CLI permits bounded customization through
1,800 seconds, which is outside this frozen qualification invocation. It does not install or rebuild
dependencies. `--backend` and `--format` select a smaller declared variant without
enabling development mode. Dirty-source development output cannot earn acceptance.

The packet retains raw command logs, source and tool inventories, executing helper
bodies, selected runtime/source bodies, generated configuration and compiler records.
Native binaries are hashed, not copied. This is not a complete transitive source or
binary-replay archive; the exact commit and recursive source identities remain
necessary reproduction inputs.

## Development evidence and limits

See the [initial audit](../../p04-executor-audit.md),
[starting CI observations](initial-ci.json), and
[host regression record](development/host-regression.md). Individual `development/wNNx.md`
receipts identify each worker's actual work, reviewed hashes, commands, findings
and scope. Host fault injection, synthetic serialized observations and source checks
do not constitute native execution.

Event timestamps use the host steady clock. Queue wait, preparation and service
intervals are observable separately; service includes runtime synchronization and
does not measure physical GPU latency. Host wait intervals overlap event intervals
and must not be summed with them. Native processor RTL is separate from full-AFU,
vendor `hw_emu` and physical FPGA evidence.

P01-A03 remains blocked. The earlier tensor DSP area-gate failure remains recorded
in the starting CI evidence; this change does not modify RTL, baselines or tolerances.
