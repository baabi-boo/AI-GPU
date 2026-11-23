# Local execution attempt 02 — preserved ordering failure

## Result

**Attempt 02 failed at final inert verification of its dependency receipt.
No managed native workload or separate native control ran.** Compilation,
linking, product verification and staging completed, but the producer emitted
its retained-file inventory in an order that the existing reader rejects.
The original remains failed and unchanged.

The [machine-readable summary](attempt-02-summary.json) records the exact
observations, artifact identities, correction and separately scoped diagnostic.
This attempt uses the [local execution contract](../../../../designs/local_dependency_execution_v1.md)
and source `ac2f2ae761c3644103278f7a41cc6ae7db734a86`, tree
`5e7caa2b008fe8b1924811aeda5a079845a37343`.

The original envelope records **610.126890 seconds**. Fresh preparation passed
in 87.924567 seconds. The dependency child then finished with exit code 1 after
521.702241 seconds. Its original reason is
`retained inventory ordering differs`, at stage `inert-verification`; the outer
envelope records `dependency-build child failed: nonzero_exit`.

## Completed observations and host repair

| Actual operation | Passing records |
| --- | ---: |
| Compilation | 406 |
| Archive creation | 3 |
| Archive indexing | 2 |
| Shared-library linking | 2 |
| **Total** | **413** |

These records contain **819 successful child observations**: 406 dependency
prepasses and 413 tool executions. All five outer build commands returned zero.
The selected translation units remain 309 SoftFloat, 60 Ramulator, 29 yaml-cpp,
seven spdlog and one extension source.

Before final receipt rejection, the producer retained both verified linker
maps, all three products, 144 generated build inputs and 929 generated-source
observations. It staged **628 files**: 625 pinned fetched-source files and three
products. The documentation review independently rehashed all 628 staged files
against their original descriptors. The source-checkout observations before
and after staging are identical and clean. The report also retains 13 stability
observations and 3,679 file descriptors, excluding the report itself. These are
completed observations within a failed attempt, not a complete successful
dependency receipt.

The missing C++ runtime from [attempt 01](attempt-01.md) was supplied in a new
host root, `/workspace/p06-local-host-02`. Its sealed host receipt has SHA-256
`1a205a1d080753490669664c61236a2102176aff1457529415809740ad70f4ce`.
The independent repair review joined all seven package files through the
signed Debian package index and verified actual shared-library selection.
The link-time runtime is the matching packaged `libstdc++.so.6.0.30`; normal
execution still selects system runtime libraries, outside a complete host/OS
provenance claim. The previous host root remains unchanged.

The actual Ramulator map in attempt 02 selects **25 yaml-cpp members** and no
external archive members. The extension map selects no archive members.
The previous static C++ fallback is absent, and the original report's
`external_archives` list is empty. The archive-selection requirement is unchanged.

## Ordering defect and reviewed correction

The [dependency producer](../../../../../ci/project/p06_dependency_build.py)
iterated `sorted(self.output.rglob("*"))`. Python `Path` ordering compares path
components, whereas the receipt contract orders complete relative POSIX path
strings. A directory whose name is a prefix of a sibling filename or another
directory can therefore appear in the wrong lexical position.

The original inventory contains exactly three descending adjacent pairs:

| Previous entry | Following entry that should sort earlier |
| --- | --- |
| `sources/ramulator/src/dram/lambdas/rowopen.h` | `sources/ramulator/src/dram/lambdas.h` |
| `sources/softfloat/source/8086/specialize.h` | `sources/softfloat/source/8086-SSE/extF80M_isSignalingNaN.c` |
| `sources/softfloat/source/ARM-VFPv2/specialize.h` | `sources/softfloat/source/ARM-VFPv2-defaultNaN/extF80M_isSignalingNaN.c` |

Independent review established this as an F2 producer defect. The reviewed
correction returns the already checked descriptors as
`sorted(rows, key=lambda row: row["path"])`. Hashing, file-type checks, symlink
rejection, report exclusion and the byte bound are unchanged. The
[reader's ordering requirement](../../../../../ci/project/p06_dependency_receipt.py)
remains enforced.

Three permanent regression tests reproduce the relevant filename/directory
prefixes and preserve the symlink and byte-budget checks. Before the correction,
the ordering test failed and the other two passed; after the correction, all
three passed. Only a fresh corrected producer run can supply a successful
original. This historical record asserts no later retry outcome.

## In-memory prospective diagnostic

An independent diagnostic used the frozen source-02 reader and a **deep copy
held only in memory**. It did not rewrite the original report, change retained
files or execute a retained compiler, command or binary.

| Input to the full receipt semantics | Observed result |
| --- | --- |
| Unchanged failed original | Rejected as an incomplete successful build |
| Hypothetical successful status with original inventory order | Rejected for inventory ordering |
| Hypothetical successful status with lexical inventory order | Full `verify_document` semantics accepted the hypothetical data in 13.113840 seconds |

The last case changed only the in-memory status fields needed to reach the
remaining semantics and the descriptor ordering. It checked the actual 413
records, three archives, both links, three products and exact source manifest.
All seven qualification and acceptance fields remained false. The diagnostic
rehashed **3,680 original packet files, totaling 140,173,896 bytes**, before and
after; all original bytes, including the failed report, remained identical.

**That diagnostic is not an original pass, repaired execution record or native
run.** It isolates the proposed correction and checks for another retained-data
mismatch before an expensive fresh attempt. The failed report remains the
authoritative outcome of attempt 02.

## Original identities

| Original | Bytes | SHA-256 |
| --- | ---: | --- |
| Local envelope | 12,201 | `567f5e34826ddc9d510cf242361f3afb112a7e8fbcdccfc556cbe2df236285ed` |
| Preparation | 1,885,720 | `d35a65fa1c216ee68b0a64f9e01e7bdc7203045b95b57e0042735458c29bfbbd` |
| Dependency report | 1,784,914 | `344c43fe145a76f11938c45abcdb940ddda5a47da52c9ced6249713b9d62123b` |
| Ramulator linker map | 18,041,699 | `63380e4a848e10a7caf97a2123028654f8972437ed1c933c13db3a08e0255382` |
| Extension linker map | 607,597 | `edc1a23d403c32b62279e27f05862f06e97942d5546368260bc46726fa5bb678` |

The independent prospective review is identified by
`w06_a05-retention-review.json`, SHA-256
`426e351da82a370f5fee7ac7901296228648de42c2b897ff32a31a9aec68c7c8`.
Its source identities, exact diagnostic mutations and regression results are
retained in the machine-readable summary.

## Preserved raw archive and claim boundary

`AI-GPU_P06_local_attempt_02_failed_2026-11-23.zip` contains the producer's
evidence directory: **28,674,439 bytes**, **3,685 members** and
142,094,266 uncompressed bytes. Its SHA-256 is
`8d407e6b5355aec7e9736957de613ce8ac0b69b45284617bcc5dcc10305a5b32`.
Packaging checked every member against the original, rehashed originals after
packaging and passed ZIP CRC validation. The documentation review independently
rehashed this archive and checked its member count and total uncompressed size.
It is an original-evidence archive, not a complete host-disk snapshot.

The original keeps `fresh_dependency_build_passed=false`,
`dependency_source_to_loaded_binary_verified=false`,
`separate_controls_passed=false` and `native_execution="not_run"`.
All seven `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance` and
`performance_acceptance` fields remain false. The completed operations,
recorded staging and prospective diagnostic do not change those original claims.
