# Wave 3 public native observation verifier

Owned and created only `ci/project/p06_counter_public_records.py` and `ci/project/test_p06_counter_public_records.py`.

## Implemented contract

The pure standard-library verifier exposes `MODES`, `verify_output(text, mode)` and `verify_record(value, mode)`. It performs no filesystem reads, path resolution, subprocess execution, native linking or runtime execution. Runner source/build/tool/process binding remains separate.

It requires one bounded final `COUNTER_PUBLIC_RESULT` line, exact schema 1 field inventories at every level, exact primitive types (booleans cannot stand for integers), bounded integers/output/depth, no duplicate JSON keys, no floats/NaN/Infinity, and no accompanying failure or unrelated result line. The five exact modes always retain false warm/qualification/acceptance flags.

The fixed 33 selector/class/CSR/component tuples are declared independently of the reported rows and checked against the existing frozen 45-row public contract in tests. All 40 actual source values must fit uint64; every successful aggregate must fit uint64; every row must exactly reconstruct from its low/high observed words. Tags, core zero, sequence order, generation, restored class, stable ticks/reset identity, fresh context, CP enable/drain/retirement/head/tail, exclusive final ownership, and actual destruction boundaries are checked independently of producer summary booleans.

Seeded coherent snapshots require the exact 40 seeded values but remain transport evidence. The unseeded scalar witness and lifecycle are retained separately. No lifetime qualification is derived from diagnostic seeds or matching snapshots.

The async failure records require fresh quiescent real storage, exact MAX or MAX-2 cycles seed, saturation before mutation, no retired instructions, typed-error counts, and delayed progress. The cache failure requires actual component slots16/17=MAX/1 and one failing low half. Raw public status3 and exact unchanged sentinel values are required both for the triggering cache query and the repeated rejected queries. Suppression entry counts must remain unchanged, and actual destruction must match the final failed model observation before the successful fresh context.

An intentional cache aggregate exception leaves Core's performance class at4 because the exception occurs before the original restoration statement. This is a poisoned context. The verifier requires that exact fault-specific transition; every successful terminal half requires restoration to class0. Production behavior was not modified.

## Source-derived count reconciliation

These expected counts were derived from source, not observed in native execution:

| Item | Harness assertions |
|---|---:|
| Context construction, upload/readback, 19 descriptor writes |90|
| Frozen inventory check |146|
| One CP terminal observation |13|
| Complete terminal snapshot |714|
| Unseeded successful context |823|
| Seeded successful context |969|
| Failed async context |336|
| Failed cache context |333|
| Main entry plus final result checks |6|
| normal |1652|
| coherent-terminal |1798|
| immediate-overflow / delayed-overflow |1165|
| cache-overflow |1162|

Manual descriptor setup contributes19 DCR writes per context,38 total. Kernel=null, args=null, ndim0 adds no descriptor writes. The direct-RAM/VM-off route does not introduce a cache-flush or MMU DCR read here; COUT reads are I/O DMA and finalization performs no performance dump. Expected read totals are132 for two positive terminal snapshots,66 for async fault plus fresh snapshot, and67 for cache fault plus fresh snapshot. Suppression is observed after the first context's run1/write19/read0(async) or1(cache)/overflow1. Platform construction and each one launch reset give generations1/2 on the first context and3/4 on the fresh context; finalization leaves reset generation intact but resets clock to zero.

## Validation actually run

`python3 -m unittest discover -s ci/project -p 'test_p06_counter_public_records.py' -v`

29 tests passed in1.517 seconds. They use explicitly synthetic complete records for all five modes and exercise wrong/missing/extra fields, strict types, selector substitutions, hidden aggregate overflow, seed removal, wrong high halves/tags/order/classes, ticking/reset drift, CP incompletion, extra ownership, wrong destruction, missing native progress, changed public destinations, revived model entries, wrong global counts, duplicate/malformed/unbounded JSON, failure/trailing output, and attempted filesystem/subprocess access. Complete synthetic records remain nonqualifying; tests establish parser behavior only.

`git diff --check` passed for both owned paths. No native library, executable, GPU workload, commit or push was produced by this agent. Native execution and independent review remain required.

Raw host test receipt: `/workspace/scratch/98908dfa3444/w03-public-records-tests.log`.
