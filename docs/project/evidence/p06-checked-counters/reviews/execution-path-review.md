# Independent execution-path and test reviews

The root coordinator retained these three independent read-only reviews of
`53f4ad08c469a1cc73fa604249b302f9416055e0` against
`89aa43236038fcfff5d36a7cdb95646b038fe2fb`.

| Reviewer | Scope | Verdict |
|---|---|---|
| `/root/w05_a04_enforcement_review` | Runner, executing-interpreter binding, workflow and build fragment | No F2/F3; scoped landing recommendation after execution and overall review |
| `/root/w05_a05_native_harness_review` | Real model harness, completion ownership, transport coverage and counts | No F2/F3; native execution remained unperformed by reviewer |
| `/root/w05_a06_host_tests_review` | Primitive, production stats, runner/interpreter tests and counter consumers | No F2/F3; static test adequacy, no test execution by reviewer |

All applied repository review prerequisites, with R3 depth for the enforcement
contract despite the advisory classifier's R2 result. None edited, built,
tested, committed or pushed these changes. This document is not an execution
receipt or acceptance record.

## Runner and workflow

Separate fresh ordinary and checked trees bind the exact release profile,
PERF setting, compiler flags, include order, guard value and generated hardware
configuration. Every recorded compilation must match the validated stamp;
the unique native link consumes exactly the inventoried fresh objects and
identified dependency libraries. A preprocessed header probe independently
checks effective configuration. Required real model and TCU sources are linked.

Source retention includes tracked simulator/common inputs, the actual harness,
profile/build inputs, local execution helpers and the test-local included
production AsyncRun header. The root Makefile is copied but not executed by
this direct SimX make route; the complete clean Git identity still names it.
The selected source subset is not advertised as a complete toolchain archive.

The executing Python interpreter is recorded separately from PATH Python.
Tool, source, generated configuration, compiler stamp, object and binary hashes
are checked at their declared boundaries. Retained records and logs are checked
again at completion. Every native scenario checks binary/configuration/stamp
identity before launch. A source label or success banner cannot override a
failed build/run, incomplete cleanup or a resource stop.

Typed-error diagnostics require normal exit zero after their assertions, one
exact scenario record, correct field types and no duplicate keys, nonfinite
JSON, failure banner or competing record. Crashes and the discarded abort
protocol fail. All five cells are required for the directed prerequisite pass;
qualification, warm readiness, phase acceptance and full coverage remain false.

The hosted workflow uses read-only permissions, hosted Ubuntu and checkout
without persisted credentials. Caches are restored without writes. The pinned
preparation path requires matching cache/source receipts and blocks missing
prerequisites. Fixed limits remain 15 GiB disk, 4 GiB polled RSS, two build jobs,
16 MiB logs, 1,800-second builds, 180-second invocations and a 90-minute job.
Failure artifacts are retained too. These checks do not defend against a
malicious concurrent filesystem writer or inventory every system dependency.

After this review, the new workflow-contract tests identified an omitted
`ci/blackbox.sh` event path. The coordinator added that path symmetrically to
push and PR events. That later additive change has its own test/review identity;
the original workflow hash below is not relabeled as the later file.

## Native harness semantics

Core overflow is seeded into real cycle storage and triggered only by
production Core ticking through `Processor::run_checked()`. Launch reset
preserves the seed. The harness requires exact typed failure, unchanged cycles,
zero retired instructions and a terminal AsyncRun owner. Eight subsequent
observations reject the owner, two actual attempted tasks remain suppressed,
and join retains failure. Captured task state outlives the completion owner.

Scope ordering joins before Processor destruction and retains RAM until that
destruction completes. Only after the whole failed context is gone does a
fresh context run the real three-instruction program, produce x3=7, advance
production counters and finish. This directly uses AsyncRun; it is not a native
public queue/event/wait test.

The nineteen pointers address real persistent Core, LocalMem, MemCoalescer and
TCU storage. TCU local-memory reads remain correctly unseeded because their
published field is derived from private buffer sources. Every selected value
uses the ten frozen vectors, nonconstant other-source values and the real
Processor/Cluster/Socket/Core/CSR path. No unavailable L2/L3 row is queried.

| Observation | Independent count |
|---|---:|
| Half-word reads | 19 selectors × 10 vectors × 4 = 760 |
| Transport checks | 19 × 10 × 14 = 2,660 |
| Initial-zero plus reset checks | 19 + 19 = 38 |
| Aggregate carry/source/copy checks | 17 × 3 = 51 |
| Total | 2,749 |

Each half checks status, value and class restoration. Both read orders are
used while the model is quiescent. Ordinary/checked equality concerns these
seeded observations, not an ordinary-workload cycle-parity experiment.

The cache negative overflows its first member and checks all source/destination
members; it does not promise rollback after a later-member failure. Pending
underflow is explicitly a primitive case, not private Processor injection.

## Host-test adequacy and consumers

The primitive tests execute actual checked operations, typed reasons, unchanged
operands and ordinary unsigned controls under release/NDEBUG/UBSan. The real
AsyncRun helper is used for asynchronous and synchronous sticky failures,
suppressed later work, join/destruction and fresh owner success, without sleeps.

Production-header tests enumerate 48 actual field types and compare layouts.
Actual aggregation operators use distinct values, exercise 17 member failures,
and preserve the rejected primitive and source. Native harness compilation is
syntax-only in these host tests. Runner tests use real temporary identities
and explicit mocked process boundaries; invalid source/tool/configuration,
compiler/link inventories, resources, outputs and drift are rejected.

Consumer inspection found no changed counter used directly in printf varargs,
mixed min/max templates or an expression requiring deleted addition/subtraction.
This does not replace compiling every production translation unit.

## Remaining scope

Native execution and original hosted artifact review remain separate from these
static reviews. The fourteen unseeded available sources, public native fault
integration, coherent all-selector observations, complete aggregate lifetime
closure and a new qualification binding remain open. Historical warm-v1 stays
blocked. No RTL, physical hardware, speedup or phase acceptance is established.

## Reviewed identities

Coordinator recomputation from the reviewed immutable commit:

| File | SHA-256 |
|---|---|
| `ci/project/p06_checked_execute.py` | `b59a3d8f870f7625f085bfcca4071adde8f69b4089da8a2badf25e26ad3f47e5` |
| `ci/project/p06_mpm_execute.py` | `c9524652c24121401f7d2cb044cae72c4f6dece7f8d8357d886d7b1ef63fcea0` |
| `.github/workflows/p06-checked-counters.yml` | `9539d2b5ebcc9d72a5155323dd716ff704ae58010faafdc36519a1f396757219` |
| `.github/workflows/project-governance.yml` | `c5883419d3a8291b7b866f8cd32a66b77054aee55299375b0291404e384f9fcc` |
| `sim/simx/checked_counters.mk` | `ef5a50d475fe8461042f76297dea08a6409a61c61e4c3530ddf22b523a708698` |
| `sim/simx/Makefile` | `c719966647f32fef5421dd798a89d3eeddccd692e7c61046e5744b7a8e722403` |
| `tests/unittest/checked_counters/main.cpp` | `7fce02fbee361fe9de554d1c4f74e7459aa268db7a849adead028298799b83c6` |
| `ci/project/fixtures/p06_checked_counter_test.cpp` | `f43c4f97f21928dcaadfec19d83c4d85f5ebc31afa3ad1c83a8174dedfc58317` |
| `ci/project/test_p06_checked_counter.py` | `d3aa19d3d98d15761f44983537b70d8639bca5fac2eb342432c11a8861a7c959` |
| `ci/project/test_p06_checked_integration.py` | `e95576f095258f4c72487fb0c4971f22fc757e0f49453d091e90519151069bb5` |
| `ci/project/test_p06_checked_execute.py` | `207800792204b248996efa2ae81b2661dbf578e7d6fe89fe989019bfe4f7163a` |
| `ci/project/test_p06_mpm_execute.py` | `a159fcccbacde50edc96c34a24354f613908a1eec72080e3493bcb2fc024e7f5` |
| `configure` | `645cdad95c31a959a36c795c37b2b7e4c0202f19c53093aa9067cda3ef23a0be` |
