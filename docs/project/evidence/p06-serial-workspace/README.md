# P06 serial workspace implementation evidence

This packet records the ownership and fixed-workspace continuation audited from
`3235cd59d724663dda1bece20645d5ccf30462e1`. Start with the
[development audit](../../p06-workspace-audit.md),
[frozen runtime/correctness contract](../../../designs/serial_matmul_workspace_v1.md)
and [handoff](../../p06-workspace-handoff.md). The
[manifest](../../../../ci/project/p06_workspace_contract.json) defines correctness
scope; it contains no performance or phase acceptance.

**Current scope: implemented sources and passing targeted host checks.** The
complete integration suite on the new checkpoint, fresh native correctness execution
and final publication identity are pending at this documentation checkpoint.
The original P06-A01 cold SimX acceptance remains at
`84b6ca0ca75fba248ba330642bbf8764db3d459c`; P06-A02/A03 remain open.

## Retained host evidence

| Evidence | Recorded result and boundary |
|---|---|
| [Initial full-suite baseline](host/baseline-full-suite.json) and [console](host/baseline-full-suite.log) | 2,449 tests passed before runtime implementation. Workspace files added after discovery were not selected; this is not the new implementation's integration result. |
| [Consumer expectations and compiled binding](agents/w03_a01.md), [retained binding result](host/p05-boundary/results.json) and [retention metadata](host/p05-boundary/retention.json) | P03/new-runtime targeted suites and all 107 compiled P05 host scenarios passed. Fake native libraries exercise ownership and injected errors; actual SimX execution remains separate. |
| [Strict records and compiler regressions](agents/w03_a02.md) | 55 methods and 2,704 expected rejections passed. Synthetic output transports and retained stamps are parser evidence. |
| [Compiler hardening](agents/w03_a03.md) | Complete role-aware macro contracts reject extra ISA/derived configuration. Fresh configured stamp targets reproduced the positive records without native compilation. |
| [Runner/workflow regression](agents/w03_a04.md) | Runner and workflow tests passed. External execution/resource/tool observations are explicitly synthetic; fixture producers, parsers and hash checks execute directly. |
| [Real model/managed-wrapper composition](agents/w03_a05.md) | 11 methods / 38 fresh child scenarios passed using real ownership/control code over the deferred fake C API. Scripted zero outputs are not GPU arithmetic. |
| [Allocation and race edges](agents/w03_a06.md) and [console](host/edges-development.log) | 12 methods / 48 child processes cover wrapper allocation exceptions, 128 synchronized context-create races and polling/profile boundaries. General native concurrency or global OOM is not qualified. |
| [Independent runtime review](agents/w04_a03.md) and [retained review observations](host/runtime-review/retention.json) | All assigned runtime/consumer hunks reviewed, with focused suites and a detached-output cleanup probe. The output-scope documentation finding was clarified; no open F2/F3 issue was found in that review's scope. |

Each receipt identifies its actual commands, source hashes, outcomes and limits.
Overlapping test runs and fresh-child scenarios are not added together into an
invented unique test total. Synthetic parser/runner records never count as
native processes or checked accelerator words.

## Integration and native execution status

| Obligation | Current record |
|---|---|
| Full host suite on frozen new implementation checkpoint | Pending; record exact revision/tree, command, console and outcome when completed. |
| New SimX FP16 native workspace variant | Pending checkpoint publication and execution. |
| New SimX BF16 native workspace variant | Pending checkpoint publication and execution. |
| New processor-RTL FP16 native workspace variant | Pending checkpoint publication and execution. |
| New processor-RTL BF16 native workspace variant | Pending checkpoint publication and execution. |
| Independent reconciliation of native originals | Pending original execution packets; source/format/policy/numerics/lifetimes/provenance must agree. |
| Final committed and published branch identity | Pending; recorded only after remote readback. |

The [workflow](../../../../.github/workflows/p06-workspace.yml) runs four
backend/format jobs, each with both policies in separate processes. A successful
selected variant requires **2 processes, 8 launches and 256 exact FP32 words**;
the complete four-variant matrix requires **8 processes, 32 launches and
1,024 words**. These are expected totals, not completed native results.

The default four-call process must allocate/release 12 tensor buffers; the
resident process must allocate/release three, with a 320-byte peak requested
A/B/D payload in each. The native device/buffer observer does not independently
count hidden queue/event/enqueue calls inside rejected probes. Successful
live-device allocator deltas remain simulator accounting, not physical memory
reclamation. See the handoff and frozen contract for the full observation limits.

Native execution retains the two-job, 4 GiB polled RSS, 15 GiB free-disk,
16 MiB command-log, 1,800-second build / 180-second invocation limits and
90-minute hosted job deadline. Local missing toolchain/disk prerequisites are
documented blockers, never passing results or reasons to relax those limits.

## Historical Python acceptance retention

The stronger current error assertions changed a test path referenced by the
historical P05-A01 record. The [retention-only successor](a01-retained-binding.json)
redirects that artifact to
[exact historical test bytes](history/p05-a01/ci/project/test_p05_native_binding.py.txt).
[Retention metadata](a01-source-retention.json) binds the original record,
immediate predecessor, five historical mappings and all artifact identities.
[W04-A01](agents/w04_a01.md) records the verification.

The accepted source remains `e1420fd550f716df33a2556057b7086a03032cbe`.
Original commands, artifact digests, scope and acceptance state are preserved;
only the canonical P05-A01 evidence location changes. This relocation establishes
no new Python/framework or workspace execution result.

## Work accounting and open gates

The requested work is organized into ten waves of six agent assignments, batched
within the available concurrency. The [agent receipts](agents/) record actual
completed scopes; this page does not assert that all 60 have finished. The final
execution ledger and publication report must reconcile completed assignments
and hashes when the work ends.

The [warm performance proposal](../../p06-next-experiment-proposal.md) remains
draft. P06 and P06-T01 are `in_progress`, P06-A02/A03 and P05-A02/A03 remain open,
P01-A03 still requires vendor `hw_emu`, and the inherited 267 → 283 DSP area-gate
failure remains unresolved. Processor RTL, host fault tests and source review
do not close those obligations or establish physical FPGA/silicon performance.
