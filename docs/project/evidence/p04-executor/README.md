# P04 managed-model executor evidence

**P04-T02 is accepted, completing P04 for the frozen model and configuration.**
[P04-A02 numerical execution](acceptance-numerics.json) and
[P04-A03 dispatch/transfer evidence](acceptance-dispatch.json) bind acceptance to
clean source `c9d139cc9f84839b6a56b6228dd304460cbfe45c`, tree
`6ef022a7f940b2e084da6117f307d4b6d0a443f1`. The
[independent qualification review](qualification-review.json) accepts the fresh
SimX/native processor RTL × FP16/BF16 matrix at `rtl_verified` scope. Native
processor RTL bypasses the AFU; this is not vendor emulation or physical hardware
qualification.

Development began at `041f0981b2648dd5ec1494f4c1ca0300da8b9ca6`. The managed
executor composes accepted matmul operations for the frozen synthetic batch-16,
bias-free 16 → 8 → 4 model. The original
[P04-A01 fixture acceptance](../p04-fixture/acceptance.json) and its historical
manifest remain unchanged. The next bounded action is
[P05-T01's Python binding](../../p05-entry-handoff.md); P05 remains `not_started`.

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

## Accepted fresh matrix

All four jobs in the
[fresh native workflow](https://github.com/baabi-boo/AI-GPU/actions/runs/44762622060)
succeeded. Their 62 bounded commands produced the following observed results:

| Dimension | Observed coverage |
|---|---|
| Backends | SimX and native processor RTL |
| Input formats | FP16 and BF16, each accumulating/outputting FP32 |
| Cases per format | `seeded_dense`, `negated_dense`, `zero`, `signed_basis`, `split_boundary` |
| Repetitions per case/backend | Two, using distinct destination poison values |
| Complete matrix | 20 case/backend pairs, 40 model runs, 120 native matmul launches, 600 event/profile pairs |
| Exact comparisons | 5,120 hidden words; 2,560 bridge words; 2,560 output-block words; 2,560 assembled-output words |
| Explicit tensor transfers | 76,800 H2D bytes including destination poison, 30,720 D2H bytes |
| Host row assembly | 10,240 copied bytes |

These totals count only the four fresh `c9d139c` packets. Each contains five cases,
ten model repetitions and thirty launches. Earlier successful executions with
incomplete retained provenance are not included. Argument/control staging, module
loading and setup traffic are outside the explicit tensor-byte totals; physical
DMA transactions and bandwidth are not measured.

The [numerical audit](reviews/c9d139c-numerics.json) independently recomputes exact
integer results and checks actual hidden, bridge, row-block and assembled words.
The [dispatch audit](reviews/c9d139c-dispatch.json) checks actual input lineage,
56-byte arguments, address bounds, dependency/profile ordering, timing consistency,
completion and cleanup. The [provenance audit](reviews/c9d139c-provenance.json)
checks source Git bodies, retained artifacts, generated stamps, compiler roles,
tool identities and native TFR/STD selection. All three pass the complete matrix;
their own reports intentionally leave the acceptance decision to the independent
qualification review and formal records.

The [archive index](archive-index.json) binds eight original ZIPs and 736 member
identities: four accepted fresh packets and four preserved incomplete predecessors.
Fresh packets include the actual `.config.stamp` bodies and matching final hosted
job results. [Replay instructions](execution/README.md) were executed successfully
from a new extraction directory; the [replay receipt](execution/replay/verification.json)
records all three passing full-matrix audits. This reads retained observations
and does not add native executions to the totals. Each original `job.json` is an
initial identity receipt; its `native_execution: not_run` field is not a final
result. Final status comes from the finished model report, raw logs and retained
`final-job.json`.

The same source revision passed the complete host governance suite:
**1,816 tests in 366.568 seconds**, with no errors, failures or skips. The
[exact job metadata](host-tests/c9d139c-governance.json), compressed raw log and
[independent host review](development/w08f.md) retain that result. Host fault
injection and serialized synthetic observations remain separate from the native
matrix. The [summary](summary.json) presents exact counts and separate timing
categories without treating overlapping intervals as disjoint costs.

## Failed attempts and corrections

The first published implementation is
[`7167ce1`](https://github.com/baabi-boo/AI-GPU/commit/7167ce17d335ec1f50e26da9b4832c1c27013ada).
The [source map](source-map.json) records its exact tree equality with the locally
reviewed checkpoint. Initial hosted preparation stopped before native execution
because the restored `cocogfx` checkout was dirty. Investigation reproduced the
condition with its unignored build products. The
[failed preparation record](failed-attempts/7167ce1-simx-fp16/preparation.json)
preserves that blocker; it is not a numerical failure or passing model result.
The general catalog's [original preparation failure](failed-attempts/7167ce1-catalog-simx64/diagnosis.json)
has the same dirty-submodule boundary. A reviewed preparation correction moves
only identified unused cache products outside the checkout and retains their
before/after identities. Unknown or modified source still fails the clean-source
gate.

After the cache correction, all four `f4c6a323` native variants completed their
declared cases. Numerical and dispatch checks passed, but independent provenance
review found the artifact upload omitted required `.config.stamp` bodies.
All four original incomplete ZIPs and their findings are retained in
`failed-attempts/` and indexed above; the
[SimX/FP16 finding](failed-attempts/f4c6a3-simx-fp16/retention-failure.json)
records the first observation. No missing stamp was reconstructed or waived.
Enabling hidden files only in the two narrow model evidence uploads fixed
retention, and fresh `c9d139c` execution supplied the accepted packets.

Adversarial review also found an include-root gap in the new provenance auditor
and timing-consistency gaps in the dispatch auditor. The original scripts and
counterexamples remain under `reviews/history/`. Exact-role include roots,
sequential enqueue order and nested host-duration checks were corrected and
independently re-reviewed in [W08B](development/w08b.md) and
[W08C](development/w08c.md) before final qualification. These are evidence-checker
corrections; no native runtime or frozen numerical contract changed to obtain
the passing result.

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
and must not be summed with them; `advance_ns` contains nested host work, and
absolute steady clocks from separate jobs are not aligned. A wait timeout retains
ownership; destructors may drain indefinitely, so this is not bounded device
cancellation. Resource snapshots check the declared allocator/owner boundaries,
not every process-heap allocation or broad physical recovery. Native processor RTL
is separate from full-AFU, vendor `hw_emu` and physical FPGA evidence.

P01-A03 remains blocked and is required before P07 can close. The earlier tensor
DSP area-gate failure, 267 → 283 beyond the unchanged 5% bound, remains recorded
in the starting CI evidence. This change does not modify RTL, SimX behavior,
baselines or tolerances, and does not claim overall general-CI success.
