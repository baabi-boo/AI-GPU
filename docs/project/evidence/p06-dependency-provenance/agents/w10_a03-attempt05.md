# W10-A03 follow-up — independent original review of host diagnostic 05

This is a follow-up by the same assignment **57 of 60**, wave 10. No additional
agent was spawned. The assignment created this report and the separate
`host-diagnostic/review-05.py`, `review-05.json` and `review-05.log` files. It made
no production changes, original-evidence changes, Git mutations or publication.

## Result

**The complete selected host dependency graph passed independent inert review.**
The actual attempt 05 original reports `finished/pass`, and the independent
review passed on its first execution in **12.306428 seconds**. It verified all
413 actual tool records, the 406-unit source/compile graph, generated CMake
inputs, archive/index joins, both link maps and all 12 diagnostic stability
boundaries. Original retained bytes remained unchanged during review.

This result has **host dependency diagnostic scope**. The formal dependency
receipt, preparation, measurement staging, managed-model build and native/loader
joins remain absent. Their flags remain false, and `native_execution` remains
`not_run`. Attempts 03 and 04 retain their failed outcomes; this review concerns
the fresh attempt 05 only.

The primary result is the [independent review receipt](../host-diagnostic/review-05.json),
SHA-256 `fd6bd4879c71253dd4a19c3cc94649080d1dd34af41b3e14561e4d336d79cb23`.
Its [original review log](../host-diagnostic/review-05.log) records exit success
and the separate original/review outcomes.

## Frozen original and reviewer

The terminal original was supplied by the producer after execution finished at
11:15:38.242019 UTC. The reviewer was prepared while the build ran and executed
only after receiving the terminal outcome and exact report hash.

| Input | Exact identity |
| --- | --- |
| Workspace | `/workspace/p06-host-diagnostic-fixed-05` |
| Trusted helper checkout | `/workspace/p06-dependency-corrected` |
| Published helper revision | `19333193192ba5a2d3667c0111235ec9e21a5898` |
| Published helper tree | `baeeb7bc7078e9301c68e94b1207032329be343d` |
| Original report | 1,709,521 bytes; SHA-256 `3f961336605864771b803887c5c562d2bfdeccd8568168f53b473a69d2f2d47a` |
| Sealed preparation SHA-256 | `a3a84f71db0eaea7bc270ef8ee5773841038fa65c396046ba125cfbdac83adbb` |
| Driver SHA-256 | `28c5abdeb959e92c53fa7d57bc09b5093478c78d57a09443c2b3479e2fe32682` |
| Recorder configuration SHA-256 | `f585ac6250746711c245d9e4cd0a03ee8459439e9db6c5c1f100a2a2669c98d6` |
| Source manifest digest | `c677abd7a1cbb78cab13c23b40a92a83be427e06c3dffa40419de92b8697cd2e` |
| Source-plan digest | `f479cc6ed3ee4d4dd7fd305bc45943af33a3a2ba9069da48eebe627c5f817570` |
| Reviewer SHA-256 | `6616b1dcc1377dfa1bf1675ebd78c593a7f6bcd6df815f32150b1097cf6db3a4` |

The reviewer checked the clean helper checkout, revision/tree, imported-module
origins and published Git blobs; all 18 selected helper source identities and
retained copies; the sealed seven-tool selection; and exact driver/configuration
bytes. Its source and map requirements follow the reviewed correction described
in [W10-A05's source-specific finding](w10_a05-spdlog-selection.md) and
[W10-A06's independent review](w10_a06.md). Those earlier focused tests were not
rerun or added to a new unique-test total here.

## Independently verified execution population

| Operation | Actual records | Passing records |
| --- | ---: | ---: |
| Compile | 406 | 406 |
| Archive | 3 | 3 |
| Index | 2 | 2 |
| Link | 2 | 2 |
| **Selected operations** | **413** | **413** |

The child inventory was derived directly from each original record: **406
children with stage `dependencies` plus 413 with stage `tool`, 819 total**. All
children exited zero. Dependency-prepass children are separate from the selected
413 operation records.

The trusted individual-record validator checked every record's recorder and
configuration identity, selected tool, actual arguments, child sequence and
timing, fresh output, retained payload identities, and before/after inputs. For
every compile, both actual dependency files resolved to the same ordered unique
input inventory. No retained source, helper, command or binary was executed by
this review. Subprocess creation was disabled during semantic checking.

The retained inventory contains **3,682 files and 135,214,393 bytes**, excluding
the report. It was checked for exact names, unique ordering, ordinary bounded
files, hashes and sizes before and after validation. The report, sealed
preparation and driver bytes also remained unchanged.

## Source and generated build graph

All **1,294 source files, 10,938,128 bytes**, matched their SHA-256 and Git blob
identities. The manifest reconstructed the pinned dependency trees. Immutable
source build recipes rederived the same exact plan:

| Component | Verified translation units |
| --- | ---: |
| SoftFloat | 309 |
| Ramulator | 60 |
| yaml-cpp | 29 |
| spdlog | 7 |
| Extension | 1 |
| **Total** | **406** |

The graph reader matched every actual source and unique object output to this
plan. Included project headers matched the source lock, with unreviewed project
inputs rejected. The actual SoftFloat specialization/options and the extension
recipe matched the frozen contract. The **97-row CMake compile database**
contained the exact selected CMake source population plus the known unbuilt
Ramulator `main.cpp` row.

The generated-build reader validated the **144 retained generated inputs**,
configured CMake cache, target flags, archive/index recipes and shared-link
recipes against the actual records. The complete outer-command reader separately
checked the five actual commands and their launchers, environment, target and
two-job bounds. No compiler-support archive resolution command ran, and no
external archive was admitted by this original.

The repeated-header SoftFloat case also passed in this fresh run. Record
`589e5e6c8f572bc9cb13b780b5fbcd7a92a861d492762c504a97133ae696f6eb`
retains 24 raw prepass dependency tokens and 23 unique stable inputs. Its prepass
SHA-256 is `e05906309810aa796318207f3a3fb785534bad55b9ee557146e6c917f170cc23`.

## Archives, links and exact products

The archive parser reconstructed ordered members and symbol tables from retained
bytes. Each creator consumed the exact preceding object outputs in the planned
order. Each separate index consumed its creator's exact archive, and all
prerequisite completion times preceded their dependent operations.

| Archive | Validated object members | Indexing |
| --- | ---: | --- |
| SoftFloat | 309 | Included in the `ar crs` creation; no separate index |
| yaml-cpp | 29 | Exact creator-to-index join |
| spdlog | 7 | Exact creator-to-index join |

Both successful link records had stable before/after inputs and retained actual
maps. Ramulator consumed 60 preceding object outputs plus the two indexed
archives, **62 direct inputs**. The extension consumed its preceding object and
the exact Ramulator shared-library output, **two direct inputs**. The map reader
required every direct input exactly once and reconciled the complete
source/workspace `LOAD` population. All selected archive members had to belong to
an admitted, fully validated archive and match its compiled-object identity.

| Actual map | Bytes | SHA-256 | Observed selection |
| --- | ---: | --- | --- |
| Ramulator | 18,084,083 | `9959236240532b5055e3a3157ae056c1f958e3da161f7b84188b645d50cc6dd8` | 25 yaml-cpp members, zero spdlog members; 80 total `LOAD` records |
| Extension | 614,675 | `62847597df38ac51abde5e627eca4c8ecd72dfa51a62d2856ca8e5d72cfb57f8` | No archive-member extraction; 20 total `LOAD` records |

For Ramulator, yaml-cpp member selection and the unique `LOAD` of **both**
yaml-cpp and spdlog were required. The entire seven-member spdlog archive,
creator/index, actual link-input bytes and chronology were verified despite its
zero extracted members. The generic member validator remained strict.

The fresh compile evidence agrees with the source explanation: all 60 Ramulator
records omit `SPDLOG_COMPILED_LIB`, 59 include the pinned spdlog `common.h`, and
all seven separate spdlog compiles define `SPDLOG_COMPILED_LIB`. Zero archive
member extraction does not imply zero spdlog header code in the Ramulator output.

The map reader received only a narrow context adapting the diagnostic's external
archive field names; no original record or document field was modified. No
formal preparation or staging fields were synthesized.

| Selected product | Bytes | Retained SHA-256 |
| --- | ---: | --- |
| `softfloat.a` | 492,514 | `5bd6e703aaacc9f57d50e0bd4adf4b9bbe5a06294b170312f8ff82b48971ad6e` |
| `libramulator.so` | 5,903,224 | `4c774218ea94d799e76f4457fda366f4ac5899054a33f4ff42a639e479a09216` |
| `libramulator-vortex.so` | 678,208 | `8187eab137187204fc0ad93f127f981c70e616c00aba35834dc28b8e7b39fd8f` |

## Stability and resources

The reviewer reconstructed **929 source-root generated files** from the actual
record outputs and dependency files, then reconciled all **12** completed
diagnostic boundaries: source freeze, before/after each of the five commands,
and final. The final source-root inventory is consistent with those generated
outputs and the locked source manifest. No staging boundary was inserted.

| Actual outer command | Exit | Duration (s) | Peak sampled RSS (bytes) |
| --- | ---: | ---: | ---: |
| SoftFloat build | 0 | 20.548574 | 63,750,144 |
| Ramulator configure | 0 | 0.372201 | 11,837,440 |
| Ramulator build | 0 | 404.433164 | 1,381,498,880 |
| Extension compile | 0 | 14.503791 | 654,249,984 |
| Extension link | 0 | 0.301921 | 35,442,688 |

All five recorded cleanup observations passed. Preparation observed
58,898,423,808 free disk bytes and 7,080,980,480 available memory bytes; execution
entry observed 58,868,641,792 and 7,184,564,224 respectively. Both exceeded the
unchanged 15 GiB disk and 4 GiB memory entry bounds. Jobs remained two, simulation
workers one, configuration timeout 120 seconds, build timeout 1,800 seconds, and
command-log limit 16 MiB. The map used the reviewed existing 64 MiB artifact
category; no numeric budget constant was changed by this review.

Resource monitoring remains sampled and is not a hard cgroup/filesystem quota.
Caller-pinned original consistency does not authenticate its producer or
establish complete compiler/system-input closure. Before/after hashing does not
protect against malicious concurrent writers. The selected CMake executable is
identity-bound without a broader toolchain qualification claim.

## Claim boundary and exact review command

The original's `host_diagnostic_passed` is true. The following remain false:

- `fresh_dependency_build_passed` and `dependency_source_to_loaded_binary_verified`;
- `formal_preparation_executed`, `measurement_staging_executed` and `cache_restoration_claimed`;
- `qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
  `acceptance_claimed`, `phase_acceptance` and `performance_acceptance`.

`native_execution` remains `not_run`, and `retained_code_executed` is false in the
review receipt. The result does not add phase, hardware, full-counter or
performance acceptance. The separate 4,118-test governance run predates these
latest corrections and was neither rerun nor relabelled here.

The actual command, from `/workspace/AI-GPU`, was:

```bash
python3 -I -B docs/project/evidence/p06-dependency-provenance/host-diagnostic/review-05.py \
  --helpers /workspace/p06-dependency-corrected \
  --workspace /workspace/p06-host-diagnostic-fixed-05 \
  --expected-report-sha256 3f961336605864771b803887c5c562d2bfdeccd8568168f53b473a69d2f2d47a \
  --output docs/project/evidence/p06-dependency-provenance/host-diagnostic/review-05.json \
  > docs/project/evidence/p06-dependency-provenance/host-diagnostic/review-05.log 2>&1
```

The receipt is created exclusively; a later independent rerun must choose a
fresh output path. The [reviewer](../host-diagnostic/review-05.py),
[receipt](../host-diagnostic/review-05.json) and [log](../host-diagnostic/review-05.log)
remain separate from the producer's original and summaries. No optional test
rerun or further execution was needed after this review passed.
