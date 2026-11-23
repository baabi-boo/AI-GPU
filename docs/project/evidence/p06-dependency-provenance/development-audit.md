# Development audit and selected next step

## Audited starting point

The requested repository is baabi-boo/AI-GPU, and the authorized publication
target is master. The audit verified published head
`832ae98178d7ce9022a13f1a69d9082f909c9e0d`, tree
`8adf366ca442a1f07ecd99d87aaac403c660573f`. Personal Context recovered the latest
handoff, then current Git source, AGENTS, status, roadmap, machine-readable gates,
backlog, acceptance policy and developer/review guidance were inspected directly.

P00/P02/P03/P04 are complete only within their declared scopes. P01 remains
blocked on vendor XRT hw_emu. P05/P06 are in progress; P07-P11 have not started.
The next task must advance an identified P06 premise without inventing hardware,
performance, framework or qualification acceptance.

The preceding implementation `b4127b19a004b5aebb8d52eab9ceda0da3ff4561` supplied
the completed four-process lifetime original: 132 launches and 4,224 exact FP32 words.
Its separate pending probe and always-zero control are outside that count. The
retained full governance result has 3,813 tests; generic CI's final aggregate was
still queued during the audit, so this document does not call all CI complete.
See the [native lifetime packet](../p06-native-lifetime/README.md).

## Solid development lead

The [current handoff](../../p06-dependency-provenance-handoff.md) identifies the
remaining source-to-loaded-product edge. The managed path previously reused
SoftFloat, Ramulator and the Vortex Ramulator extension from a dependency cache.
Final product hashes, link commands, loader paths and favorable numerical output
cannot establish which immutable sources, headers and actual build executions
produced those libraries. The old v1 source export also intentionally inventories
selected inputs rather than the complete dependency trees.

A second join is already available in trusted code: the complete 30-command
application validator, including the 14-source runtime stub. The live producer
previously checked only the final host invocation. The next route should call
and bind the full validator while preserving its existing exact grammar.

The selected implementation therefore builds the three dependency products from
five immutable commit/tree locks, records 406 compiles plus archive/index/link
operations, verifies retained object/archive/map joins, stages exact bytes, and
binds that receipt to both format builds and all four native processes. A new
contract and opt-in route preserve historical originals and false fields.

## Execution organization

Sixty distinct agents are requested across ten waves of six. This environment
provides three worker slots; each wave uses two batches. The actual ledger
counts completed contributions, not projected assignments. Recovery turns by
existing authors do not increase the count.

Waves 1–3 audit and implement source/build/receipt/CI foundations. Wave 4 integrates
complete inert native review and meaningful negative controls. Waves 5–8 resolve
actual hosted failures and independently verify original artifacts, loader joins,
provenance sensitivity, regressions and historical compatibility. Waves 9–10
reconcile documentation, the bounded next handoff and publication evidence.

Resource bounds, golden files, the protected framework SVG, acceptance gates
and inherited functionality remain unchanged. The initial filesystem lacked
the formal native reserve; an environment reset later removed the uncommitted
checkout. The [recovery record](recovery/environment-reset.md) documents restored
files and fresh verification. Native completion and acceptance are not inferred
from this planning/audit record.
