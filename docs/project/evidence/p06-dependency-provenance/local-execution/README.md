# Local fresh dependency and native lifetime evidence

## Completed local result

This continuation implements an explicit local route for the next bounded
P06-T01 step: join fresh selected dependency compilation, archive/link results,
staged products, native model/application builds and actually loaded libraries
in one original, then replay and independently review that original and its two
separate controls. The [local contract](../../../../designs/local_dependency_execution_v1.md)
and [runbook](runbook.md) define preparation, execution and inert replay.

**Attempt 04 passed all five execution stages, and its untouched complete
original passed public inert replay and independent native/control review.**
Execution used clean source `0f9aaa36d46364c297254164f5dab0d4f0e88349`, tree
`fb8e90f38498ca138acf978d4a11d6a087e5a778`, from 2026-11-23 13:23:09 to
13:38:04 UTC. The enclosing execution measured **894.591061 seconds**.

The completed [original summary](attempt-04-summary.json) and
[execution observation](validation/local-attempt-04-execution-summary.json)
record the five passing stages. The [public replay summary](validation/local-attempt-04-replay-summary.json)
and [complete replay result](validation/local-attempt-04-replay.json.gz) identify
the corrected reader separately: `ba2d649d4150e046c2ba610de02725d9d062b1be`,
tree `a9db358818a66f2a241ed2d8a7453edf938ccb2c`. That reader correction did not
rewrite or rerun the original. It accounts for two actual destructor diagnostics
that caused the original reader's preserved inventory failure.

| Actual stage | Observed result | Stage duration, seconds |
| --- | --- | ---: |
| Local preparation | Exact source, dependency inputs, selected tools and fresh workspace admitted | 85.370126 |
| Fresh dependency build | 413 successful tool records / 819 successful child observations; products staged and receipt passed | 507.728831 |
| Managed native lifetime | Four FP16/BF16 × policy processes; 132 launches / 4,224 exact result words | 253.039344 |
| Pending probe and always-zero control | Positive observations in two scalar contexts; separate always-zero process rejected at its exact assertion | 7.532778 |
| Alternate dependency control | One separate process; 33 launches / 1,056 exact words; original provenance rejected | 39.836296 |

The earlier failures remain preserved alongside the completed retry:

| Attempt | Execution source | Preserved result |
| --- | --- | --- |
| [01](attempt-01.md) | `ac2f2ae7` | Dependency verification rejected selected static C++ runtime members caused by an incomplete host installation. No managed native process ran. |
| [02](attempt-02.md) | `ac2f2ae7` | All selected dependency operations and staging completed, but the producer's retained inventory order failed the strict reader. No managed native process ran. |
| [03](attempt-03.md) | `7251f078` | Dependency and complete native lifetime originals passed; the enclosing wrapper failed on the larger native report's JSON structure limit. Both controls remained unrun. |
| [04](attempt-04-summary.json) | `0f9aaa36` | Complete five-stage execution passed. The unchanged original passed the corrected public reader at `ba2d649d` and independent native/control review. |

All seven qualification, warm and acceptance fields remain false. Native SimX
execution, inert replay, governance tests, synthetic fixtures and physical
hardware observations retain their separate meanings.

## Why this step came next

The preceding [native lifetime original](../../p06-native-lifetime/README.md)
established the fixed four-process witness, while the
[host dependency diagnostic](../host-diagnostic/README.md) established the
413-operation selected dependency graph in a lower diagnostic scope. Neither
provided the complete fresh dependency-to-loaded-library original and separate
controls needed for the next qualification decision. The initial audit therefore
selected that missing join before another feature or a warm performance run.

The implementation preserves the existing numerical cases, goldens, compiler
options, managed population and acceptance gates. It adds local preparation,
bounded orchestration and one complete local reader, with an explicit local
origin. It records no invented GitHub run, job, restored-cache or authenticated
producer identity.

| Implementation | Declared responsibility |
| --- | --- |
| [Pinned toolchain provisioner](../../../../../ci/project/p06_local_toolchain.py) | Check the immutable archive lock, safe extraction/link semantics and selected native tool/library identities. |
| [Local preparation](../../../../../ci/project/p06_dependency_local_prepare.py) | Verify the clean exact source and five pinned dependency trees, select host tools and retain the local preparation original. |
| [Local executor](../../../../../ci/project/p06_dependency_local_execute.py) | Run preparation, fresh dependency building, native lifetime, pending probe and substitution control in five separate interpreters. |
| [Complete local reader](../../../../../ci/project/p06_dependency_local_replay.py) | Reconstruct dependency, native and both control semantics inside one externally pinned archive and verify the enclosing local identity without executing retained content. |

The runbook documents eight recursive gitlinks, 15 locked toolchain archive
parts, Linux CPython 3.12.14, the reviewed CMake installation and a complete
matching GCC 12 host installation. SoftFloat and Ramulator come from checkout
gitlinks; yaml-cpp, spdlog and argparse come from the supplied repository root.
Preparation verifies all five pinned trees, comprising 1,294 selected files and
10,938,128 bytes.

## Corrections established by real inputs and independent review

The failed originals exposed specific integration boundaries. Their failures
remain evidence; corrections apply to later source or a new host installation.

| Finding | Correction and retained check |
| --- | --- |
| Incomplete GCC 12 host runtime | A new host root includes the matching shared `libstdc++6` package, verified through signed Debian package metadata. The original host root and failed attempt 01 are unchanged. |
| Component-wise `Path` ordering differs from required POSIX-string ordering | The producer sorts checked retained descriptors by their complete relative path strings. The reader's ordering, byte, type and symlink checks remain enforced. |
| Pending reader omitted the producer's selected host-tool prefix | The reader reconstructs the exact optional `host_bin` path and ordered deduplication. |
| Synthetic substitution fixture omitted the recorder's real empty lock | The reader and fixture require the actual empty `payloads/.retention.lock`, with missing and nonempty controls. |
| Completed native report exceeds generic JSON structure limit | The dependency-managed report has an explicit 500,000-token ceiling at the wrapper and pinned control entry points. The generic default remains 250,000; existing byte, depth, duplicate-key, UTF-8 and number checks remain enforced. |
| Hosted cache is checked as untracked source before relocation | The hosted preparer relocates the already validated cache before its unchanged strict source snapshot. Dirty source, wrong revision and invalid cache inputs still block acquisition. |
| Synthetic replay guard rejects trusted reader files under `/home/runner/` | Tests admit only exact current trusted inputs and the caller-selected ZIP for reading. Producer siblings, tools, build products, unknown runner paths, execution, extraction and writes remain blocked. |
| Complete control inventory omitted actual Ramulator destructor files | The reader accounts for exactly `pending-probe/ramulator.stats.log` and `dependency-substitution/work/ramulator.stats.log` as required, bounded, hash-identified opaque diagnostics. Unknown files and incorrect frozen/final inventory joins still fail. |

The hosted cache and pathname corrections respond to retained historical hosted
failures and have separate regression evidence. A successful hosted retry is
not inferred from those local regressions. The diagnostic correction is reader
only; its 22 distinct regression tests and independent actual-control review
preserve complete member coverage. The [validation summary](validation-summary.md)
states exact tested source scopes, before/after profiles and omissions.

## Original intake identity and complete replay

The successful complete ZIP is
`AI-GPU_P06_local_attempt_04_passed_2026-11-23.zip`: **47,632,218 bytes**, **5,597
members** and **227,787,986 uncompressed bytes**. Its SHA-256 is
`d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`.
The [packaging identity](originals/AI-GPU_P06_local_attempt_04_passed_2026-11-23.identity.json)
records member-by-member comparison, the closing original rehash and ZIP CRC
verification. Complete original ZIPs are delivered separately to the repository
owner; this committed identity is the reference for subsequent intake.

The exact external report pins are:

| Input | SHA-256 |
| --- | --- |
| Local execution envelope | `77f55f174f4decd6baeb0f152bf3250a5096d2f5bd846ae802260ce7e4a5eea7` |
| Fresh dependency receipt | `f22f564ddd8d8a3d20636410f6d2f04b328018676803fdc5ea483c28ded10e8a` |
| Native lifetime report | `83040361c8b934dcab290bb8ba00d74e0b2b05f4db25f3455518c34945b997a6` |
| Native source-before snapshot | `04207022c43cc2e5a715e1eca626adb165711c975f2d1757e5ec3baddfbd5bf1` |
| Pending probe report | `802e174fb76420957286203b264ddca84dce949cbd32434c847821a36d2d7711` |
| Dependency substitution report | `042dfc54c7e87ab33e1148a3360e2d4e51c620bdcfff92563f1386fe65699313` |

The root public CLI replay passed in **18.657440 seconds**. The
[independent guarded public replay](agents/w10_a05.md) then passed in
**20.738125 seconds** and rejected each of eight wrong external identity
arguments. The negative cases created no result file. Its exact positive output
is byte-identical to the root result: **1,595,517 bytes**, SHA-256
`2a28ebd63c136ccfde0b0b98c109e45765911fe1c53765ee0ca2b6cbdd669c3d`.
Both successful calls returned through the archive's closing identity check.

The complete reader accounted for all 5,597 members with 5,763 bounded reads and
271,449,823 charged bytes, joined all five stage originals and eleven toolchain
identities, and reconstructed every dependency/native/control semantic reader.
The independent instrumentation denied producer-path opens/resolves/traversal,
process execution, network activity, dynamic loading and filesystem mutation,
except writing the explicitly selected exclusive result file. It recorded zero
prohibited events. This is instrumented inert review, not an OS sandbox or
authenticated producer-origin claim. Replay reports `native_execution="not_run"`
and `retained_code_executed=false`; actual execution remains the separately
pinned original at `0f9aaa36`.

The [native-original review](agents/w10_a01.md) independently reconstructs both
formats and all four raw transcripts, including exact integer-only expected
results. The [separate-control review](agents/w10_a03.md) verifies positive and
always-zero behavior, alternate-source derivation, build/loader joins, all
1,056 alternate-process words and the original-provenance rejection. Every
original byte remained unchanged during these reviews.

## Fixed execution and review boundaries

The verified dependency population is **406 compilations, three archive
creations, two indexes and two shared links**: 413 tool records and 819 child
observations including dependency prepasses. It includes three products,
628 staged files, 144 generated CMake inputs and 13 stability boundaries.
The verified managed matrix is
FP16/BF16 × per-operation/reusable allocation: **four processes, 132 launches
and 4,224 exact FP32 result words**, with 16 snapshots, 528 available queries,
1,056 half replies, 132 cache-flush reads, 1,188 DCR reads and 192 unavailable
rows. Each process completed 33 ordered run/reset pairs, reached reset
generation 34 and finished with zero pending reads and zero live buffers.

The pending-accessor positive process and always-zero process are separate from
that matrix. The positive process checked two scalar contexts, `gp=7` and `-1`;
each observed 23 positive samples, maximum pending balance one and final balance
zero. The always-zero control failed the exact missing-pending-observation
assertion. The alternate dependency process is also separate: one FP16 reusable
process, 33 launches and
1,056 checked words, whose numerical success coexisted with rejection of the
original dependency provenance. These populations are not combined.

The two destructor diagnostic files are 2,103 and 2,248 bytes. They are checked
under the existing 16 MiB log limit, matched to the bound native destructor and
accounted at their actual runtime phase. Their metadata explicitly sets
`interpreted`, `numerical_evidence`, `performance_evidence` and
`qualification_evidence` to false. The diagnostic `.nan` text is never promoted
to numerical or performance evidence.

Budgets remain two build jobs, one simulation worker, 15 GiB free-disk reserve,
4 GiB required available memory/child RSS ceiling, 120-second configuration,
1,800-second builds, 180-second native processes and 16 MiB logs. The outer
local execution has a 90-minute polled ceiling. These process observations are
not hard cgroup quotas or accepted performance measurements.

Each complete original ZIP contains the producer's unchanged evidence directory.
Its sidecar identity records every member rehashed against the original, a
closing original rehash and ZIP CRC verification. The ZIP is a retained evidence
packet; complete compiler support files, system headers and the whole host/OS
are outside its provenance claim. Review reports and new replay outputs stay
outside that original directory.

## Evidence navigation and next bounded action

Use the [source-scoped validation summary](validation-summary.md),
[complete evidence index](evidence-index.json), [individual reviews](agents/),
[original identities](originals/) and [execution/replay runbook](runbook.md).
The local [assignment ledger](agent-execution.json) and
[readable work ledger](agent-execution.md) record the 60 distinct assignments
spawned across ten waves of six, with actual report identities. Follow-ups to
the same assignment do not add agents to that count.
The enclosing [dependency evidence index](../README.md) preserves the earlier
hosted/diagnostic continuation and its separate work ledger.

With the complete local original, inert replay and independent control review
now established, the [next-step audit](agents/w07_a03.md) and
[final scope review](agents/w10_a04.md) select separately versioned complete counter
qualification/admission for the existing managed caller. It must bind all ten
lifetime premises, 33 available selectors and 40 backing components to the exact
guarded binaries and loaded dependencies. Pending reads are a transient balance,
not a 41st cumulative component. Freeze and independently review that contract
and meaningful rejection controls, then run a fresh qualification preflight.
The planned 24-process warm experiment follows qualified admission.

`qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
`acceptance_claimed`, `phase_acceptance` and `performance_acceptance` remain
false. P06-A02/A03, complete no-wrap qualification, warm performance and vendor
XRT `hw_emu` remain open. No RTL, FPGA or silicon measurement is supplied by
this local SimX evidence.
