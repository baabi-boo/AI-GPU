# Wave 5 independent review of the original all-selector native packet

Reviewer: `/root/w05_native_all33_audit`, Wave 5 agent 2/6. This reviewer did not author the implementation or produce the hosted native execution. Review date: 2026-11-22 UTC.

## Verdict and scope

**The supplied original ZIP is internally consistent with the published seven-cell native prerequisite execution at `407ab9fea5e4f793a2a5088f566a87f3e631aa84`. No F1, F2, or F3 finding was found in this assigned packet review.** All original boundary and negative-cell logs validate against the source-bound contract. The evidence supports the narrow all-33-selector native transport prerequisite and its directed checked failures.

This is a read-only evidence supplement to the R3 diagnostic contract review. It does not replace a final integrated change review or independently authorize phase acceptance. In particular, it covers the original seven-cell checkpoint only; the later public-runtime matrix and terminal-lifetime proof are outside this artifact. This reviewer performed a data audit, not another native execution. `qualified`, `ready_for_warm`, `acceptance_claimed`, `full_warm_coverage`, and `warm_execution` remain false.

Repository guidance considered: `AGENTS.md`, the repository `code-review` and `simx-review` guidance, `docs/review/code-review-policy.md`, the scratch task contract `COUNTER_DIAGNOSTIC_TASK.md`, and relevant Wave 2 runner and Wave 4 build-record review notes. The preceding runner review's native execution obligation is addressed here only for the observed original seven cells and exact published source checkpoint.

## Original archive and source identities

| Item | Identity |
| --- | --- |
| Original ZIP | `/workspace/scratch/98908dfa3444/native/run-45026112992-attempt1.zip` |
| Original ZIP bytes | 1,137,709 |
| Original ZIP SHA-256 | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` |
| Published source commit | `407ab9fea5e4f793a2a5088f566a87f3e631aa84` |
| Published source tree | `b5e1f32c73bee17bb963aebca5681cb2526d40af` |
| Workflow run / attempt | `45026112992` / `1` |
| Job / artifact IDs supplied by intake | `137219393978` / `14756780371` |
| Artifact name supplied by intake | `p06-checked-counters-407ab9fea5e4f793a2a5088f566a87f3e631aa84-run45026112992-attempt1` |
| Native report interval | 2026-11-22 13:26:39 to 13:28:21 UTC |
| Report contract | `simx-checked-counters-native-v2`, schema 2 |
| Trusted archive-reader SHA-256 | `4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3` |
| Trusted checked-runner SHA-256 | `bcab9b048606a0d1d4ab8be3f91df9ebe5bce2a41375cd98b9dc2a279b5e2f99` |
| Published retained workflow SHA-256 | `0f7a12fe7e491b4464bd62e07ace3da310c812381291d88d5565b230e7858091` |

The parent supplied successful GitHub run/job metadata and the external original ZIP digest. I independently rehashed the supplied ZIP through the trusted reader, checked its byte count, and verified the retained job/workflow/source bindings. I did not independently fetch GitHub metadata in this reviewer task. A ZIP digest identifies these bytes; it does not by itself authenticate GitHub origin or make arbitrary producer claims trustworthy.

The archive was opened through the trusted repository `docs/project/evidence/p05-torch/reviews/archive_reader.py`, after validating that local reader's digest. The original archive was rehashed at close as well as intake. The reader enforced bounded central-directory and member handling, canonical relative names, uniqueness, ordinary file/directory kinds, compression restrictions, aggregate expansion and read bounds, and archive stability. JSON was parsed with the reader's duplicate-key, number, depth, and node bounds.

There are exactly **327 data members** and **3,981,364 expanded bytes**. All 327 members were read and hashed. The complete inventory is exactly the main report, 17 command logs, 270 retained source bodies, 16 retained build/configuration/probe bodies per variant, and the seven root preparation/job/workflow/log files. There is no executable or object payload hidden among that inventory. No member was extracted, no retained code was imported or executed, and no recorded producer absolute path was opened. Recorded absolute paths were validated as `PurePosixPath` labels only.

## Source and hosted preparation binding

All **270 retained source bodies** were compared byte for byte with `git show 407ab9fea:<path>` from the local published Git object database. Every comparison passed. Their descriptor inventory also equals the exact published tracked-file selection used by the runner plus its critical paths, not merely a matching count. Their hashes and byte counts match the report's source and retained-source descriptors.

The source before/after snapshots are equal. The checkout records the exact commit and tree above, `dirty=false`, no changed or untracked paths, no blockers, no missing tracked critical files, and no submodule errors. The five direct submodule pins agree with the published commit's Git links. All eight recorded recursive entries are marked initialized. The extra nested submodule payloads are not independently rehashed by this review.

All **11 local trusted runner/helper files** used for data validation equal the published Git blobs and retained source bodies. Their local bytes were checked again after the audit. This prevents silently validating the old artifact with the later public-runtime implementation or a changed helper contract. I called only the pure record/output functions on archive bytes, not the live runner or `validate_build`, which would access producer filesystem paths.

The root `workflow.yml` equals the published `.github/workflows/p06-checked-counters.yml` bytes and its recorded job digest. `job.json` consistently identifies a push on `refs/heads/master`, repository `baabi-boo/AI-GPU`, job `native-counters`, the source commit, run ID, attempt 1, RV64, profile `p02-tfr`, performance counters on, and the ordinary/checked variants. Its `native_execution=not_run` is explicitly an initialization-stage statement; it is not the final execution result.

`preparation.json` records pass, no reason, and the same clean checkout; preparation does not claim native execution. Its three dependency identities match the native report's dependency identities. Shared tool identities agree between preparation and execution. The four recorded preparation-source hashes agree with their published Git blobs. The recorded cocogfx cache quarantine preserves its source revision and each moved file identity and ends with an empty status. These are consistency checks on retained preparation records, not a rerun of preparation.

`python-provision.json`, both version logs, and both selected Python identities agree on CPython 3.12.14 on Linux. Other version logs identify GNU Make 4.3 and Ubuntu g++ 11.4.0. Root `execution.log` is the exact narrow pass summary referring to this packet's report; root `preparation.log` is the consistent preparation-only pass summary.

## All 17 raw command records

Every command's raw log bytes were verified against its recorded SHA-256 and size. I checked its exact ID/order, argv, working directory, clean environment, timeout, process-started state, completed cleanup, integer exit code 0, pass outcome, absent failure reason, duration, sampled RSS, and log budget. The command arguments were reconstructed from the published runner contract and recorded roots; they were not executed.

| Command | Duration, seconds | Log bytes | Result |
| --- | ---: | ---: | --- |
| `version-make` | 0.013330 | 297 | Pass |
| `version-gpp` | 0.013280 | 246 | Pass |
| `version-python3` | 0.013306 | 15 | Pass |
| `version-executing_python` | 0.013064 | 15 | Pass |
| `ordinary-configure` | 2.649724 | 0 | Pass |
| `ordinary-build` | 39.218948 | 105,447 | Pass |
| `ordinary-header` | 0.020028 | 58,658 | Pass |
| `ordinary-boundaries` | 0.023785 | 993 | Pass |
| `checked-configure` | 2.648361 | 0 | Pass |
| `checked-build` | 40.116879 | 106,413 | Pass |
| `checked-header` | 0.022283 | 61,813 | Pass |
| `checked-boundaries` | 0.023916 | 992 | Pass |
| `checked-core-overflow` | 0.026027 | 397 | Pass |
| `checked-cache-aggregate-overflow` | 0.020987 | 298 | Pass |
| `checked-pending-underflow` | 0.021221 | 267 | Pass |
| `checked-cache-backing-overflow` | 0.025553 | 456 | Pass |
| `checked-tcu-backing-overflow` | 0.026087 | 454 | Pass |

The two configure logs are legitimately empty and bind to the SHA-256 of the empty byte string. The successful native commands include the fixed isolated Python wrapper that disables core dumps and executes the identified diagnostic binary. The wrapper text is compared as data; this audit never invokes it.

The fixed resource budget is unchanged: two build jobs, one simulator worker, 15 GiB minimum free disk, 4 GiB maximum polled process-group RSS, 16 MiB per-command log, configure/header timeout 120 seconds, build timeout 1,800 seconds, run timeout 180 seconds, and version timeout 30 seconds. Recorded available memory is **15,618,981,888 bytes**. Each recorded source/work/tools/output filesystem has **86,514,208,768 free bytes** at preflight. The largest sampled command RSS is **903,798,784 bytes**, the ordinary build. All recorded command durations, sampled RSS values, and raw log sizes are below their limits. These sampled observations do not establish hard quotas or capture peaks between polls; the report retains that limitation.

## Ordinary and checked build recomputation

For each variant I verified the 13 generated/copied configuration descriptors, the compiler stamp, generated TCU translation unit, and exact two-line header probe against the retained bytes. Their before/after records are equal. The four copied build inputs equal the corresponding published source bytes. Key `config.mk` values bind RV64, `p02-tfr`, source/tools paths, and that variant's install path.

The retained compiler stamps pass the current trusted `checked.compile_flags`. The raw build logs then pass `checked.parse_build_records` with all source bodies and the generated TCU body provided in memory. The recomputed pure records equal the original report's compiler records, excluding the producer's live object identities, which are verified separately as records.

Both variants contain exactly **45 unique source-to-object compile records and one link**. Every translation unit has the validated normal release/configuration flags, with only its exact dependency target varied. The checked build carries exactly `SIMX_CHECKED_COUNTERS=1`; the ordinary build does not. The permitted topology, include order, C++17 mode, optimization/release settings, and performance-counter selection are retained. No `-fno-access-control` or other unapproved flag is admitted.

The exact object/link checks prevent original socket/cache/memory/TCU objects from being linked in addition to the diagnostic replacements. The three inclusion wrappers contain their expected unchanged production include and admitted directives. The TCU translation unit is exactly the retained original `sim/simx/tcu/tcu_tbuf.cpp` bytes, one LF byte, and the retained access footer. Its SHA-256 is the same in both variants: `2e7fd46ccea9209154402229d4c58eb45e58cff943e1593b80a068f75ef4bb47`.

Raw header-preprocessor logs pass `checked.verify_header` and reproduce the report's effective configurations. Together with source compile-time assertions, the retained build establishes the directed RV64, `p02-tfr`, performance-enabled, tensor-enabled, one-cluster/one-core, four-warp/four-thread, serial timing topology, with one instruction-cache bank, two data-cache banks, two tensor-buffer components, and no VM/L2/L3/WGMMA support in this diagnostic.

Each list of 45 recorded object identities maps one-to-one to the recomputed compile outputs and equals its `objects_after` list. Recorded binary before/after identities are equal and bind the exact invoked paths:

| Variant | Recorded binary bytes | Recorded binary SHA-256 |
| --- | ---: | --- |
| Ordinary | 2,075,136 | `dac6e761a03f888790be7bae6976f8a90882d85039f3a2fcb5d772074c3752bc` |
| Checked | 2,162,232 | `44b04eb85715253c46beab30f150ace02d17c44cfd54357d666751bc01400bc5` |

These are **producer-recorded identities**, not binary payload hashes recomputed by this reviewer. The binaries, object payloads, host tools, and three dependency libraries are absent from the archive. The review establishes their record consistency and source/build/log binding, not a new binary rehash or an independent compilation-authenticity proof.

## Seven original cells and independent count derivation

All seven raw logs pass the trusted `verify_output` or `verify_negative` contract. Their unique result records equal the corresponding report observations with the required exact types and negative-mode scope. No failure marker, duplicate result, wrong scenario, or missing process completion is admitted.

Both ordinary and checked boundary cells cover the same exact ordered **33 available selectors**, **40 distinct backing components**, **400 component vectors**, **14 split vectors**, and **33 reset observations**. All available selectors receive actual storage seeds; no available selector remains unseeded. The **12 unavailable L2/L3 selectors are unqueried**. The two observations are identical except for the checked flag.

The published and byte-matched `main.cpp` independently explains the runtime totals:

- 40 components × 10 fixed values = 400 isolated component transport calls.
- Seven two-component selectors × two split/carry values = 14 aggregate transport calls.
- 33 post-reset selectors = 33 further transport calls.
- Total: 447 transport calls. Each reads low/high halves in both orders, producing `447 × 4 = 1,788` actual DCR reads.
- Each read checks return status, value, and restoration of the MPM class; each ordering additionally checks the reconstructed 64-bit result. This is 14 assertions per transport call.
- There are 40 initial-zero assertions, 40 reset-storage assertions, and three assertions on each of 17 standalone aggregate fields. The complete total is `447 × 14 + 40 + 40 + 17 × 3 = 6,389`.

Both raw boundary logs report exactly **1,788 reads, 6,389 checks, and zero failures**. The native source verifies non-null/non-aliased component pointers and the expected one- versus two-component topology before producing a pass. The value vectors include the 32-bit split, upper-bit boundaries, and `UINT64_MAX`; split aggregation explicitly checks carry into bit 32 and exact full-width maximum.

| Checked negative cell | Source-bound scenario verified |
| --- | --- |
| `core-overflow` | Seeds the actual core cycle accumulator to `UINT64_MAX`, runs the production updater through `Processor::run_checked`, observes `PerfCounterError::Overflow`, preserves the protected value and zero retired instructions, and contains failure in the production `AsyncRun` owner. |
| `cache-aggregate-overflow` | Exercises production `Cache::PerfStats::operator+=` with overflowing reads and verifies all destination/source fields stay unchanged. This original mode is a standalone aggregate test, not real bank storage. |
| `pending-underflow` | Decrements zero through the `PerfCounter` primitive and verifies the underflow exception and unchanged value. This original mode is not a private model pending-read injection. |
| `cache-backing-overflow` | Seeds the actual two `dcache_reads` bank components to maximum and one; invokes the actual DCR query through `AsyncRun`; verifies aggregate overflow, both source values unchanged, and the DCR output sentinel unchanged. |
| `tcu-backing-overflow` | Repeats that actual DCR aggregate failure with the two real `tcu_lmem_reads` buffer components, preserving both inputs and the output sentinel. |

The core and both real-backing failure cells additionally require eight sticky failure checks, suppression of two later tasks, successful join, and an actual fresh context that executes the scalar exit-code witness and updates production counters. The fresh model is constructed after the failed model and completion owner leave scope. The report honestly marks all five failure observations `public_runtime=false` and `warm_execution=false`; the two real-backing modes use schema 2 and the original three retain schema 1.

## F0 observations and remaining obligations

1. **F0, high confidence, static-proof:** Original byte/source/command consistency and seven-cell contract checks pass. The script behind this review is an independent one-off audit, not a new versioned acceptance service.
2. **F0, high confidence, static-proof:** Native public-runtime wait/query integration and terminal capture are absent from this original archive. The later public matrix requires its own clean published-source execution and original-artifact review.
3. **F0, high confidence, static-proof:** Tool, dependency, object, and binary identities are records only where payloads are absent. Full host-header/compiler-support/system-library inventories, malicious concurrent writers, and executable origin authentication are not established.
4. **F0, high confidence, static-proof:** All-selector source transport does not prove a complete cumulative counter lifetime or instrumentation of every possible updater. The pending-underflow cell retains its primitive-only limitation. No warm GEMM, workspace reuse, numerical acceptance, performance result, RTL, full-AFU, physical hardware, or phase acceptance follows.

The review is acceptable as evidence for this narrow checkpoint. Preserve the original ZIP digest and hosted metadata when publishing an intake record, and keep the later public-runtime execution obligation separate. No repository source, gate, golden, or acceptance flag was changed by this reviewer; no commit, push, checkout, reset, native build, or retained-code execution was performed.

## Reproduction and companion receipts

The data-only review completed successfully with:

```text
python /workspace/scratch/98908dfa3444/w05-native-all33-audit.py
exit code 0
```

Companion files outside the repository:

- `/workspace/scratch/98908dfa3444/w05-native-all33-receipt.json`: compact scope, identity, outcome, and limitation receipt.
- `/workspace/scratch/98908dfa3444/w05-native-all33-details.json`: recomputed cell observations, command log identities/resource values, and variant records for inspection.
- `/workspace/scratch/98908dfa3444/w05-native-all33-audit.py`: the reviewer-authored data-only verification script. It imports the trusted local reader/helpers and never an archived code body.
