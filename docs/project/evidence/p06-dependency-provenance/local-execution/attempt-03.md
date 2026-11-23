# Local execution attempt 03 — native pass, wrapper failure

## Preserved outcome

The fresh dependency original and the complete managed native lifetime original
both passed at `7251f078972c1d524de06d069e91b014b55896f5` (tree
`c44b5a93ab3aabaf2438e9e7d102339c9dc80542`). The enclosing local execution
**failed after the native child completed** because the wrapper's generic JSON
structure limit rejected the larger native report. Neither the pending-read
probe nor the dependency-substitution control ran in this attempt.

The original envelope remains unchanged: `outcome="fail"`,
`native_execution="unknown"`, and its three aggregate success fields are false.
The native child independently records `native_execution="run"` and its own
successful original. Those two scopes must be reported separately; the child
does not retroactively make the enclosing attempt pass. All seven qualification,
warm and acceptance fields remain false in both originals.

The [machine-readable summary](attempt-03-summary.json) records exact identities,
counts and the separate semantic diagnostic. The attempt started at
2026-11-23 12:56:46 UTC and finished at 13:10:55 UTC; the envelope measured
848.761432 seconds. Its three actual child stages were:

| Stage | Outcome / exit | Duration, seconds |
| --- | --- | ---: |
| Fresh local preparation | Pass / 0 | 89.413209 |
| Fresh dependency build and receipt | Pass / 0 | 501.262001 |
| Managed native lifetime | Pass / 0 | 257.203585 |

## Completed original observations

The dependency original contains **413 successful tool records**: 406
compilations, three archive creations, two indexes and two shared links. Its
819 successful child observations include 406 dependency prepasses. The
independent review verifies 411 prerequisite chronology edges, 1,294 pinned
source files, 144 generated CMake inputs, three products, 628 staged files and
13 stability boundaries. It rehashed all 3,680 packet files before and after.

The corrected host installation selected the matching shared C++ runtime.
Ramulator selected exactly 25 yaml-cpp archive members, zero spdlog members and
zero external/static-runtime members. The maps still contain support-library
LOAD entries; a LOAD entry alone does not mean an archive member was selected.

The native original completed **four processes, 132 launches and 4,224 checked
FP32 words** across FP16/BF16 and both allocation policies. Each process
completed 33 launches and 1,056 checked words. The same original records
16 snapshots, 528 available queries, 1,056 half replies, 132 cache-flush reads,
1,188 DCR reads and 192 unavailable rows. These are actual SimX observations,
not RTL, FPGA or performance measurements.

## Parser failure and correction scope

The 3,679,258-byte native report contains 265,793 structural tokens under the
generic baseline parser's counting rule. Its maximum nesting depth is ten.
The baseline helper's default limit is 250,000 tokens, so the wrapper rejected
the report before consuming its completion fields. The exact original reason
is `local child report: JSON structure exceeds the limit`.

Review also found that both future control producers use the same generic
parser for the managed input, so fixing only the wrapper would leave the next
two stages blocked. The bounded correction provides an explicit token budget
for the dependency-managed report at these three entry points. The historical
default, depth, number, duplicate-key, UTF-8 and finite-value checks remain
enforced. No compiler flag, numerical threshold, execution population,
resource budget or qualification gate is changed. Only a fresh complete
attempt can establish the corrected enclosing result.

## Separate unmocked semantic diagnostic

The frozen `7251f078` native reader's `verify_view` entry point accepted the
actual native and dependency subpackets from the externally pinned failed ZIP
in 16.911919 seconds. It reconstructed the full dependency and native semantics
inside one bounded archive and completed its closing archive check. An audit
hook prohibited subprocess and network execution; it observed no prohibited
event. No retained source, binary or command was executed or rewritten.

This diagnostic deliberately does **not** claim a successful local envelope,
either separate control, a hosted execution identity or complete local replay.
Its scope is the successful native and dependency subpackets within the failed
attempt. The source-snapshot pin is
`3235c313957898a6d8cea2ebecdb540d897e5754ab6ade9c8ba3867060411201`.

## Original identities

| Original | Bytes | SHA-256 |
| --- | ---: | --- |
| Local envelope | 15,094 | `cfed86b4a364f621308c8ec715dbd7256e45e8418afd3cb816100b338ad0097d` |
| Preparation | 1,885,720 | `10ed731c8d22c81a9343bc91069169e210f5669886cfb92f6f41d3c460f94bf0` |
| Dependency report | 1,784,774 | `202ee0fb2d79d4c47380e41dfb9356a2f353c36f977348442111461d2ffb4924` |
| Native lifetime report | 3,679,258 | `bba2af32da50326b43c0225f63478a3003865a6fc34eaef2e79b9228697a56d0` |

`AI-GPU_P06_local_attempt_03_failed_2026-11-23.zip` contains the unchanged evidence
directory: **41,603,298 bytes**, **5,016 members**, and 201,335,935 uncompressed
bytes. Its SHA-256 is
`d4136feb365a809ad975bde4e5c553fecbfc3143a5fff8da25a6de191a6cb5cc`.
Packaging rehashed every member against the original, rehashed the original
after packaging and passed ZIP CRC verification. The archive is a preserved
failed original with successful subpackets, not a complete host-disk snapshot.
