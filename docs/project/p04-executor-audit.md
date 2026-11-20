# P04 managed-executor development audit

Starting revision: `041f0981b2648dd5ec1494f4c1ca0300da8b9ca6` on `master`.
The primary coding agent owns integration. This is a development record, not an
acceptance decision. The canonical phase state remains in [roadmap.json](roadmap.json).

## Selected next step

P04-T01 and P04-A01 have already qualified the frozen fixture at source scope.
P03 supplies accepted managed native matmul for the exact shapes required by
the model. P04-T02 is therefore the next bounded development step: compose the
batch-16, bias-free 16 → 8 → 4 network through the existing managed runtime.
The [executor plan](p04-executor-plan.md) fixes the intended graph and proof.

The audit found four concrete gaps:

1. No model executor currently connects the three native matmuls. Actual hidden
   words must pass exact comparison before the host bridge; its actual bytes
   must supply both output-row calls.
2. A timed-out managed operation must remain owned. Destroying a local operation
   drains indefinitely and does not provide bounded cancellation.
3. Native traces contain event outcomes and byte counts but no separate event
   timing. The existing runtime profiling API can provide host-monotonic queue
   service intervals without changing the installed API.
4. Model-level launch, lineage, row-order, failure and resource records need a
   strict consumer and a native regression path. Existing P03 build provenance
   checks are reusable; its single-matmul output schema and fixture inventory are
   not model qualification.

## Existing CI and resource constraints

The starting revision's [general CI](https://github.com/baabi-boo/AI-GPU/actions/runs/44711512894)
and [governance](https://github.com/baabi-boo/AI-GPU/actions/runs/44711512799)
completed successfully. The preceding implementation revision's
[full CI](https://github.com/baabi-boo/AI-GPU/actions/runs/44705486919)
failed its tensor logic-area gate: DSP usage 267 → 283 exceeds the unchanged
5% bound. The smaller subsequent green run does not resolve this existing
failure. No new cause is attributed to P04, and this work does not change
hardware, golden data or tolerances.

Initial local simulation preflight is blocked: Vortex LLVM/RISC-V tools,
Verilator and CMake are absent, and required submodules are uninitialized.
Approximately 39 GiB disk and 1.6 GiB available memory were observed. Local
work is bounded to source and C++17/UBSan host checks, with one compiler job,
a 15 GiB disk reserve and no unrestricted toolchain installation. A dedicated
hosted execution path will reuse the repository's pinned toolchain setup and
retain generated-build, compiler, module, source and output identities. Each hosted
variant uses at most two build jobs, a 4 GiB process-group RSS cap, a 15 GiB
free-disk reserve, 16 MiB per-command logs and bounded build/run deadlines.
The existing P03 runner and its 6 GiB budget remain unchanged.

## Ten-wave work plan

The requested 60 distinct agents are scheduled as six agents in each of ten
waves. The workspace supports three concurrent workers, so each wave has two
groups of three. Receipts record completed work only; this schedule is not
evidence that a task or test has finished.

| Wave | Focus |
|---|---|
| 1 | Independent runtime, runner, environment, numerical, lifetime and scope audits |
| 2 | Executor ownership and graph, opt-in event profiling, deterministic case inputs |
| 3 | Native application, strict execution records and focused host failure coverage |
| 4 | Trusted runner, CI/catalog integration and source-contract integration |
| 5 | Integration fixes, independent source review and native execution checkpoint |
| 6 | Adversarial numerical, record, timing and resource reviews |
| 7 | Hosted execution diagnosis and remaining correctness fixes |
| 8 | Independent execution and source verification |
| 9 | Evidence reconciliation, status and reproducible handoff |
| 10 | Final independent delivery review and publication verification |

Keep the frozen fixture, producer, numerical contract, P01 vendor blocker and
historical acceptance records unchanged. Only actual compatible execution and
independent review can earn P04-A02/A03; a source or mock test cannot do so.
