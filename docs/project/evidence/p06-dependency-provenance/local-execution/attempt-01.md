# Local execution attempt 01 — preserved failure

## Result

**Attempt 01 failed during final dependency-product verification. No native
workload or separate control ran.** All five outer build commands returned
success, and their 413 operation records passed, but the linker selected an
external archive outside the reviewed dependency graph. The producer correctly
stopped before product staging and a complete successful receipt.

The [machine-readable summary](attempt-01-summary.json) retains the original
identities, observed operation counts, independent review scope and archive
identity. The attempt uses the [local execution contract](../../../../designs/local_dependency_execution_v1.md)
and frozen source revision
`ac2f2ae761c3644103278f7a41cc6ae7db734a86`, tree
`5e7caa2b008fe8b1924811aeda5a079845a37343`.

The original envelope records 595.561508 seconds. Preparation passed in
85.618661 seconds. The dependency
child finished with exit code 1 after 509.516277 seconds; its reason is
`link selected an unreviewed external archive`. The outer envelope records
`dependency-build child failed: nonzero_exit`.

## Completed observations

| Actual operation | Passing records |
| --- | ---: |
| Compilation | 406 |
| Archive creation | 3 |
| Archive indexing | 2 |
| Shared-library linking | 2 |
| **Total** | **413** |

There are **819 successful child observations**: 406 dependency prepasses and
413 tool executions. The source plan remains 309 SoftFloat, 60 Ramulator,
29 yaml-cpp, seven spdlog and one extension translation unit. All five outer
commands passed: SoftFloat, Ramulator configuration, Ramulator build,
extension compilation and extension linking.

The independent failure review rehashed **3,534 retained files containing
142,475,350 bytes**, excluding the report, before and after its checks. It
validated the completed per-record observations and joined all three dependency
archive member lists to their compiler outputs. The report and retained bytes
remained unchanged. The full receipt reader correctly rejects this failed
original.

A separate SoftFloat review passed within its narrower scope: 309 compilations,
one archive, 619 successful children, 309 exact ELF archive members and 297
matching archive-index symbols. Its 317 pinned source/header files contain
1,241,300 bytes; 35 selected system headers were also checked. This result
establishes that completed subgraph. The complete dependency attempt remains
failed, and its products were not staged.

## Failure cause and correction

The extracted GCC 12 development link
`/workspace/p06-local-host/extracted/usr/lib/gcc/x86_64-linux-gnu/12/libstdc++.so`
points to `../../../x86_64-linux-gnu/libstdc++.so.6`. That target was absent
from the extracted host installation. The actual Ramulator link therefore
selected **108 members from static `libstdc++.a`** and **one member from system
`libc_nonshared.a`**, in addition to 25 admitted yaml-cpp members.

The [dependency producer](../../../../../ci/project/p06_dependency_build.py)
rejected these archive selections at its existing verification boundary. The
independent review classifies the missing host runtime as an F2 environment
finding with high confidence. The archive-selection validator behaved as
intended.

The correction is to preserve this original and host root, provision the exact
matching shared C++ runtime in a new complete host root, verify actual shared
selection, and repeat from a fresh source checkout and workspace at the same
frozen source revision. The numerical workload, compiler flags and dependency
archive scope require no relaxation. This historical record does not assert a
later retry's result.

## Original identities

| Original | Bytes | SHA-256 |
| --- | ---: | --- |
| Local envelope | 12,163 | `1e1c336d2d1c078aa041ccbe698d917370190f4f420f9d4481552514095d9f2a` |
| Preparation | 1,885,693 | `463538673387219cfcbeee4bdb47d47b357130fb858cc4d9c6f6fcc45ceda3de` |
| Dependency report | 1,536,377 | `97fe819aacd6d308e0c799701344efe5bd7229ac4d737f0c04ff1e69956151b1` |
| Ramulator linker map | 21,184,256 | `07bb530ff3eb43fa386fcbd56d2cd53e2822ef0dfbdd2d4eecdb5b56ef8a15f2` |
| Extension linker map | 607,269 | `96ba637f1f068a65eb9b106dbd0ba2c1dc04575fa1205d0b76d9e36f94691c1e` |

The maps are retained through their actual link records even though final
map admission was not reached. Generated CMake/database retention, final product
staging, complete source/stability validation and native loaded-library joins
remain unestablished by this attempt. The original contains no staged products,
no admitted maps and no retained final compilation database.

## Preserved raw archive and claim boundary

`AI-GPU_P06_local_attempt_01_failed_2026-11-23.zip` preserves the producer's
evidence directory: **29,286,833 bytes**, **3,540 members**, and
145,932,041 uncompressed bytes. Its SHA-256 is
`8021368d5efe755ae282ff2a89675979d8a1377582f84fbbea57e35b5ddad502`.
Packaging verified every member against its original, rehashed the originals
after packaging and passed ZIP CRC validation. No retained code was executed.
The archive is a record of the failed attempt, not a complete host-disk snapshot.

The original keeps `fresh_dependency_build_passed=false`,
`dependency_source_to_loaded_binary_verified=false`,
`separate_controls_passed=false` and `native_execution="not_run"`.
All seven `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance` and
`performance_acceptance` fields remain false. Neither completed tool operations
nor a passing review of their failure cause changes those original claims.
