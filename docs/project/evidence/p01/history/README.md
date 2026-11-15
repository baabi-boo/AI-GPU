# Historical P01 execution and provisioning records

These files preserve the attempts that preceded the finalized baseline packet.
They are historical observations, not P01 acceptance reports. The successful
standalone retry must not be given checks that the older instrumentation did
not perform.

## Observed sequence and boundaries

| Observation | Recorded result | What it establishes |
|---|---|---|
| Initial FP16 SimX attempt with host GCC 14.2 | Outer command exit 2; no `PASSED!` | Compilation failed in pinned spdlog/fmt with `-Werror=dangling-reference`; the numerical workload did not run. |
| Historical all-six invocation, FP16 SimX case | Exit 0 and one exact `PASSED!` | FP16-to-FP32 64×64×64 GEMM passed its inherited CPU reference in the software model. |
| Historical all-six invocation, first processor-RTL case | Outer command exit 2; nested recipe error 127 | The supplied Verilator build expected an unavailable `ccache` executable. |
| Remaining BF16 and attention cases in that invocation | Four `not_run` outcomes | The invocation stopped on the first RTL build failure. |
| Separate FP16 processor-RTL retry | Exit 0, one exact `PASSED!`, zero mismatches | Native TFR tensor / STD scalar processor RTL passed the inherited FP16 reference. This is not AFU integration or vendor hardware emulation. |

The separate retry's total build-and-run duration was 353.821074 seconds and
its highest sampled process-group RSS was 2,828,828,672 bytes. Its log retains
the command-processor no-retirement diagnostic emitted after 10 seconds,
followed by successful completion and reference verification. Neither sampled
RSS nor simulation time is a hard resource bound, cgroup allocation, or physical
hardware performance measurement.

The clean GPU execution source named by the historical runner is
`03181532b81fe95b1cfeac2ffb25d8597af689b2`. The historical invocation reports
`outcome=fail`, `full_native_matrix_passed=false`, and `phase_complete=false`.
Vendor XRT `hw_emu` is blocked. The separate retry JSON does not contain the
later runner's source/host/tool/helper/build snapshots or before/after checks;
its provenance must not be retrospectively upgraded.

## Contents

`native-run/` contains the historical report, matrix, all seven command logs,
and three FP16 SimX configuration snapshots, with their original relative
layout. `runner-start-source.zip` contains the exact seven older helper/matrix/
lock sources identified by `runner-start-source.json`. The archive has no local
workspace or home paths and is retained byte-for-byte. It is an evidence
snapshot, not the current execution implementation.

`provisioning/` retains the immutable tool archive manifest, verified Debian
GCC 11 package identities, compiler/binutils observations, recursive submodule
and fetched dependency records, and initial dependency/kernel/runtime build
records. The initial Ramulator configuration explicitly identifies GNU 14.2.0;
native application and simulator runs subsequently used GNU 11.3.0. Device
libraries use the pinned RISC-V GNU toolchain and device applications the pinned
Vortex LLVM. Stage-specific identities must remain distinct.

The large tool archives were installed by the earlier provisioning script,
retained here as `bootstrap-source.py.txt`, before the production bootstrap
existed. `bootstrap.log` and `tool-bundles.json` document that operation. This
packet does not claim that the later production installer created an installation
receipt for these existing tools. The later installer has its own fixture-based
regression coverage.

## Integrity and publication transformations

[`../history-manifest.json`](../history-manifest.json) lists every exported raw
artifact's original SHA-256 and byte size alongside the published file's SHA-256
and size. Text files receive only deterministic literal path-prefix replacement;
JSON is not reparsed, reformatted, or rewritten to change any recorded result.
The original workspace prefix is represented by `$WORKSPACE`, with more specific
source, build, tool, compiler and instrumentation prefixes replaced first.

Nested hashes inside historical JSON still identify the **original raw bytes**.
Use the manifest's original-to-published mapping when checking sanitized logs
and configuration snapshots; do not compare a nested raw digest directly to a
redacted file or silently replace the recorded digest. Binary artifacts named
by a historical report are observations only; large compiled binaries and tool
archives are not checked in. Raw execution records remain outside the repository.
No credentials or full environment dumps are included.
