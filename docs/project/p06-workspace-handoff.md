# P06 serial workspace handoff

## Current implementation and evidence

The [development audit](p06-workspace-audit.md) selected a correctness
prerequisite for the proposed small-workload experiment: explicit managed
ownership, retained failure state and an opt-in fixed workspace. The
[frozen runtime/correctness contract](../designs/serial_matmul_workspace_v1.md)
was established against `3235cd59d724663dda1bece20645d5ccf30462e1` before the
runtime implementation. Its [evidence packet](evidence/p06-serial-workspace/README.md)
records exact source hashes, completed reviews and test scope.

Targeted host checks are passing. The [first clean implementation integration run](evidence/p06-serial-workspace/host/checkpoint-5da357f-failed/retention.json)
at `5da357f0f4a3cd3581919b35941db7a07d0d9fbe` ran 2,484 tests and failed with
two failures and twelve errors, all caused by the original cold-baseline source
pins rejecting the changed runtime. The separation described below is implemented;
a complete rerun on its corrected frozen checkpoint, independent enforcement
review and fresh SimX/processor-RTL execution remain pending here. The earlier
2,449-test baseline predates the runtime changes and did not select the added
workspace tests. Historical native passes do not qualify the changed runtime.

P06-A01 retains its original cold SimX acceptance at
`84b6ca0ca75fba248ba330642bbf8764db3d459c`. P06 and P06-T01 remain `in_progress`;
P06-A02/A03 are open. The [warm performance proposal](p06-next-experiment-proposal.md)
still needs a separate reviewed sampling and measurement freeze. Fewer tensor
allocations are not a measured speedup.

## Runtime contract to preserve

| Boundary | Implemented behavior |
|---|---|
| Context ownership | One atomic reservation per linked managed-runtime instance, acquired before native open and retained while operations outlive their owner. |
| Operation ownership | One live operation per context, including after a successful wait. Completed explicit close with healthy cleanup returns its lease. |
| Busy requests | Otherwise valid competing create/submit returns `VX_ERR_TIMEOUT`, `complete=true`, with no new work. Owner close with a live operation is incomplete and retains ownership. |
| Completion failure | The first non-timeout wait/query error remains primary through eventual drain. Timeout alone is retryable, not cancellation. |
| Cleanup failure | Retain the first observed cleanup error, attempt all remaining cleanup, consume handles once and poison new managed work. Repeated owner close preserves the error. |
| Output | An operation's own failure, including final retained-context teardown, suppresses its output. A previously healthy closed operation owns a detached host result that a later owner-teardown failure does not revoke. |
| Default policy | `per_operation` retains `(8,4,8)`, `(8,4,16)` and `(16,8,16)` in each of FP16/BF16. Model, Python, PyTorch and cold-benchmark callers retain this policy. |
| Resident policy | `reusable_single_tile` accepts only `(8,4,8)`, eagerly owns A128/B64/D128 requested bytes, and validates actual addresses before owner publication. MLP rejects every non-default policy before native open. |

A terminal successful model can still retain its managed context. Explicitly
close the model before creating another managed owner; execution completion is
not context release.

Each operation still owns fresh host staging, queue and events, rewrites all
input and poison bytes, launches the same kernel and reads all output bytes.
Partial dispatch retains its accepted prefix and all required resources until
completion is established. Destruction may drain indefinitely. No reset or
recovery API is added.

Raw runtime clients and independently linked runtime copies are outside the
reservation guard. Individual objects remain single-caller; the atomic-create
test does not qualify concurrent operations or general native thread safety.

## Host integration gate

From the source checkout, inspect its actual revision and edits, then use the
existing project checks:

```sh
git status --short
git rev-parse HEAD HEAD^{tree}
python3 ci/project/check_project.py
bash ci/check_sw_sim_boundary.sh
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

These are reproduction instructions, not additional recorded passing runs.
Retain exit status, full console output and tested revision/tree. A focused
`test_p06_workspace*.py` run is useful during development but does not replace
the complete integration gate. New host fixtures use the existing bounded
host-command helper, C++17/UBSan and source-identity checks. Their deferred fake
C API and synthetic output establish control, transport and fault behavior;
they are separate from native numerical execution.

## Historical cold baseline and current execution

The [original P06 manifest](../../ci/project/p06_benchmark_contract.json), all
46 execution-source pins, accepted archives and measurements remain unchanged.
`load_contract` and `validate_contract` still check every frozen execution input
against the checkout being qualified. The [native cold-baseline runner](../../ci/project/p06_execute.py)
continues using that strict path and rejects this changed runtime before launch.

Historical readers use the explicit `load_analysis_contract` entry point. It
checks the exact original manifest, 21 interpretation inputs and the actual paths
and frozen hashes of seven executing fixture helpers. The current
[replayer](../../ci/project/p06_replay.py) separately verifies every retained
source descriptor and all 46 original execution pins inside each digest-verified
archive. Archived Python and binaries remain data. The
[fresh retained analysis](evidence/p06-serial-workspace/host/historical-replay/analysis.json)
reproduces the original eight workloads, 48 processes and 72 launches; it records
`native_execution=not_run` and makes no new acceptance claim.

The current [baseline workflow](../../.github/workflows/p06-baseline.yml) now
runs that historical analysis using current trusted readers and absolute archive
paths. Its candidate checkout identity is distinct from the recorded original
native source. It supplies no current-runtime cold performance result. Current
native correctness belongs to the workspace matrix below and the existing
[P04 model](../../.github/workflows/p04-model.yml),
[P05 Python](../../.github/workflows/p05-python.yml) and
[P05 PyTorch](../../.github/workflows/p05-torch.yml) routes, each with its own
execution scope and artifact review.

To reproduce original cold native execution, use a separate clean checkout of
`84b6ca0ca75fba248ba330642bbf8764db3d459c`, that checkout's original native runner,
identified tools/dependencies and the unchanged native budgets. Follow its frozen
execution instructions. Do not replace the current runtime with retained files,
refresh original source hashes, or treat an analysis pass as permission to run
changed sources under the original experiment identity.

The [P06-A01 retention-only successor](evidence/p06-serial-workspace/p06-a01-retained-baseline.json)
changes only two artifact paths to exact historical reader bytes; its
[retention metadata](evidence/p06-serial-workspace/p06-a01-source-retention.json)
records the mapping. The original acceptance, commands, digests, measurements,
source revision and phase state are preserved.

## Native correctness execution

Use the dedicated [runner](../../ci/project/p06_workspace_execute.py),
[manifest](../../ci/project/p06_workspace_contract.json) and
[hosted workflow](../../.github/workflows/p06-workspace.yml). The runner creates
fresh configured build trees and runs the two policies in separate application
processes. It installs no tools or dependencies. The local development host
lacks the pinned GPU toolchain and required disk reserve; host-only checks are
not a substitute for this run.

Before execution, provide a clean committed checkout, existing identified
toolchain and dependency libraries, at least **15 GiB free disk** at every
checked root and **4 GiB available RAM**. The limits remain **two build jobs,
4 GiB polled process-group RSS, 16 MiB per-command logs, 1,800 seconds per build
command and 180 seconds per application invocation**. The hosted workflow has
a 90-minute job deadline, four backend/format jobs and at most two such jobs in
parallel. Its host interpreter is CPython 3.12.14.

For a full matrix, replace these absolute example paths. Source and tools must
already exist. The attempt path must be new under an existing parent, outside
both input roots, with no symlink traversal. The runner creates its `work` and
`evidence` children; do not precreate or reuse them.

```sh
P06_WORKSPACE_SOURCE=/absolute/path/to/AI-GPU
P06_WORKSPACE_TOOLS=/absolute/path/to/pinned-tools
P06_WORKSPACE_ATTEMPT=/absolute/existing-parent/new-workspace-attempt
mkdir "$P06_WORKSPACE_ATTEMPT"
python3 "$P06_WORKSPACE_SOURCE/ci/project/p06_workspace_execute.py" run \
  --source-dir "$P06_WORKSPACE_SOURCE" \
  --tools-dir "$P06_WORKSPACE_TOOLS" \
  --work-dir "$P06_WORKSPACE_ATTEMPT/work" \
  --output "$P06_WORKSPACE_ATTEMPT/evidence" \
  --jobs 2 --timeout-seconds 1800 --run-timeout-seconds 180
```

No backend/format selectors means all four variants. For one variant, append
`--backend simx --format fp16` to that command and use a fresh attempt directory.
That selection still runs both policies; there is no policy, case, iteration,
dirty-source or enlarged-budget escape. Existing host-tool or Verilator
locations may be supplied through the documented `--host-bin`/`--verilator`
options without changing the frozen matrix.

| Successful scope | Policy processes | Native launches | Exact FP32 output-word comparisons |
|---|---:|---:|---:|
| One backend/format variant | 2 | 8 | 256 |
| SimX and processor RTL × FP16 and BF16 | 8 | 32 | 1,024 |

These are required totals, not results already observed. Each process runs
`single-dense_boundaries`, `numerical-zero`, `single-k03`, then
`single-dense_boundaries` again, with the format prefix and alternating frozen
poisons. All four calls explicitly close before the next. A selected workflow
job reports `full_matrix_completed=false`; four passing job reports require
independent reconciliation to establish a combined matrix at one source/configuration.

Retain the complete attempt even on failure: job/workflow/interpreter identities,
preparation logs, report, raw command logs, source and compiler-record snapshots,
generated headers, tool/dependency identities, bindings and binary hashes. Verify
the original output words and resource observations against the frozen manifest.
Source, tools, dependencies, binaries, retained evidence and raw-log hashes must
remain stable. Do not combine unrelated revisions, replace failed samples or
treat a successful workflow status alone as artifact qualification.

## Allocation and observation boundary

The four-call default process must observe 12 tensor allocations/releases; the
resident process must observe three of each, all resident allocation during
context setup and release during final owner teardown. Both have a 320-byte peak
requested tensor payload. Resident idle payload stays at 320 until teardown;
default idle payload returns to zero after operation close.

The observer wraps device-open/release and tensor-buffer create/release calls.
It checks every tensor lifetime using successful memory-info observations before
and after allocation and release, while the device remains live. Release deltas
must reverse the corresponding allocation charge, including allocator rounding.
Requested payload is not device-wide allocator use or host RSS, and simulator
accounting does not prove physical reclamation or recovery.

The native observer does not independently count queue/event creation or enqueue
calls inside rejected probes. Native busy probes establish unchanged observed
device/buffer counts and no returned operation. Reviewed guard placement and
separately scoped host tests additionally support the absence of hidden queued
work. The unchanged fixtures supply independent expected bits; synthetic host
output is never native arithmetic evidence.

## Remaining development and acceptance

Finish and independently review the clean correctness checkpoint first. Then
freeze the warm performance schema, matched reference/candidate source pair,
identical inputs, repetitions, timing boundaries and rejection criteria before
collecting performance samples. Keep the accepted cold baseline and its archived
measurements separate from that future experiment.

| Open obligation | Required evidence |
|---|---|
| P06-A02 | Matched before/after correctness, native RTL and applicable parity/performance gates with synchronized timing changes. |
| P06-A03 | Reviewed target budget and synthesis/resource/timing reports separating predictions from measurements. |
| P05-A02/A03 | Independent review of the existing framework route's installed execution and compatibility artifacts; this workspace work makes no new framework acceptance. |
| P01-A03 and P07 | Qualified vendor XRT `hw_emu` integration remains required before P07 acceptance. Processor `rtlsim` bypasses the AFU and does not supply it. |
| Inherited area finding | Attribution and resolution of the unchanged 267 → 283 DSP area-gate failure. |

No FPGA/silicon measurement, physical speed/power claim, golden-data change,
tolerance relaxation or resource waiver follows from this implementation.
