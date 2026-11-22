# P06 workspace qualification and warm measurement

This packet follows the [development audit](../../p06-warm-workspace-audit.md)
from `13dc0d1fdb6d5322104e381aa342dc139c7bb80c`. It preserves the original
correctness evidence and the separately defined warm experiment. The
[measurement contract](../../../designs/warm_workspace_benchmark_v1.md) and
[manifest](../../../../ci/project/p06_warm_contract.json) specify the new route;
the accepted cold baseline remains unchanged.

## Reviewed original workspace correctness

The four ZIPs under [originals](originals/) are the exact GitHub artifacts from
[run 44925627664, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44925627664).
[Artifact metadata](originals/artifacts.json) retains their provider identities,
byte counts and independently checked SHA-256 values. The execution source is
`13dc0d1fdb6d5322104e381aa342dc139c7bb80c`, tree
`b10ca275377103ad94941847ee4efb1b3f296efd`.

| Independent review | Observed result |
|---|---|
| [Numerics and dispatch](reviews/workspace-numerics.json) | Eight processes, 32 native launches and 1,024 exact FP32 output words; zero mismatches. |
| [Resources and ownership](reviews/workspace-resources.json) | All 60 tensor-buffer lifetimes reconcile. Each default process creates/releases 12 buffers; each resident process creates/releases three. Both peak at 320 requested bytes and finish at zero. |
| [Source, compiler and budgets](reviews/workspace-provenance.json) | 80 command receipts, 18 compiler-role/header checks, four exact linker records and eight reconstructed bindings pass the assigned checks. |
| [Complete offline replay](reviews/workspace-replay.json) | Four original variants replay through the new trusted reader, including original logs, fixture checks, retained identities and complete matrix reconciliation. |

The new [offline replay tool](../../../../ci/project/p06_workspace_replay.py)
reads archives as data; it executes neither archived Python nor binaries. Its
result is a historical evidence check, not a fresh native execution. Each packet
contains 971 retained source files. Independent Git-object comparison covers
778 root-repository bodies per packet; 193 submodule bodies are checked against
their recorded hashes, with independent submodule object membership explicitly
unverified. Tool, dependency and binary identities are recorded hashes; their
complete executable bodies are not retained.

The wrappers establish observed device/tensor-buffer activity and live-device
allocator accounting. They do not independently count hidden queue/event/enqueue
activity inside rejected probes, establish physical memory reclamation, or
qualify the full FPGA integration surface. Processor RTL bypasses the AFU.

## New warm experiment

The same clean source and executable per format exercise `per_operation` and
`reusable_single_tile`. The complete plan contains 24 fresh processes: one
excluded warm-up pair and five measured pairs per format, each process holding
one context for one excluded prime and 32 measured serial calls. All 792 calls
must compare their 25,344 FP32 output words exactly and close successfully.

Primary intervals include submission, wait, exact output comparison and explicit
operation cleanup. Minimal fixed-storage allocation bookkeeping remains inside
those intervals and is disclosed as instrumentation. Detailed correctness
allocator queries, counter queries, memory queries, input packing, record copying
and serialization are outside the primary intervals. Counters are cumulative
SimX observations after prime and after the final sample; they are not physical
device latency or per-kernel timing.

Implementation, host validation, native execution and hypothesis evaluation are
separate records. No warm speedup or phase acceptance is asserted by this
initial packet. The retained implementation/test/review receipts will state
their actual checkpoints and outcomes as development completes.

## Preserved obligations

P06-A01 retains the original cold SimX acceptance at
`84b6ca0ca75fba248ba330642bbf8764db3d459c`. P06 and P06-T01 remain in progress;
P06-A02/A03 remain open. Vendor XRT `hw_emu`, physical FPGA qualification and
the inherited 267-to-283 DSP area finding remain separate unresolved work.
No golden data, numerical tolerance, accepted measurement or resource limit
is changed by this continuation.

## Agent work

Named receipts under [agents](agents/) record actual completed assignments,
their commands, evidence and limits. The requested ten-wave plan is accounted
for by completed receipts, not inferred from the requested sixty-agent count.
