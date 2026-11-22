# Independent native transport review

**Native regression obligation satisfied; no F2/F3 finding remains in this
packet's execution or parent-sensitivity scope.** Reviewer `/root/w09_a02`
authored none of the production repair, harnesses or runners. This review applies
AGENTS.md, the repository review guidance and host-transport contract §5 to
retained execution evidence. Separate circuit-cost, governance and final
publication reviews remain necessary; this is not a waiver or phase acceptance.

## Exact source and retained evidence

[Run 44983573225, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/44983573225)
completed native job `137089144698` successfully. The PR head was
`18c888058ac851b802350c99770ed9ac2d27b582`; the actual checkout was merge commit
`6e6426a0bf761baab11e932a4c86b49a5de81217`. Both resolve to tree
`d6dd742a905e0f3e76c7374cc678ba87e5c2a19e`. GitHub's commit endpoint independently
confirmed that tree and merge parents, rather than inferring the old checkout
from a mutable PR head.

The [archive](../hosted/attempt3-native.zip) and
[verification index](../hosted/attempt3-native.json) preserve artifact
`14738787973`: **286,540 bytes**, SHA-256
`abc1423ab4f6089ab38a71a5a4bddee8b3afc59214aaae88120f8714035b2cd1`.
All **125 unique regular members**, their CRCs and extracted copies were checked;
the uncompressed total is **1,736,643 bytes**. I rehashed **34 structured command
logs** and **79 configuration/compiler records** against their declared hashes.
The additional parent compiler stamp was independently hashed and compared with
the candidate after normalizing only source/build roots: **80 retained build
artifacts** in total.

The review compared 41 recorded candidate source paths against the original
`18c8880` Git objects, plus the workflow, and checked all 31 parent critical
inputs. The parent is exactly `4df7186edbca82b21b2b8cba9b3b192248b99209` with
five identical test/harness overlays. Its two production decoders and unchanged
architectural CSR sources match that original parent. Before/after source,
reference, generated configuration and tool records agree. Candidate and parent
tool/dependency identities are identical, and effective RV64 PERF-on compiler
records agree after root normalization.

## Executed candidate matrix

| XLEN | PERF | RTL reads / assertions | Linked SimX checks |
|---|---|---:|---:|
| 32 | Off | 188 / 3,610 | 3,781 |
| 32 | On | 340 / 6,346 | 5,251 |
| 64 | Off | 188 / 3,610 | 3,781 |
| 64 | On | 340 / 6,346 | 5,251 |

All eight native builds and executions exited zero. Raw output independently
reconciles **1,056 RTL reads, 19,912 RTL assertions, 28 ignored requests and
18,064 SimX checks**. Each RTL result reports a two-rising-edge response,
44-bit counters and TCU disabled. Every SimX build compiles and links the same
42 distinct object paths: 41 production model objects and the harness,
including `processor`, `cluster`, `socket`, `core` and `csr_unit`.

The actual native targets exercise raw host DCR halves and reconstruction,
boundary seeds, repeat/reordered reads, representative classes and restoration
of the selected class. SimX also checks its unchanged architectural CSR
behavior. This closes the missing native-matrix evidence identified in
[Wave 3's independent review](../agents/w03_a04.md).

## Same-harness parent sensitivity

Both parent targets configure and compile successfully, then intentionally
exit **1** on RV64 with PERF on. These are numeric regression failures:

- **RTL:** `FAIL RV64 tick=32 tag=00220001: expected=00000001 actual=00000000`.
- **SimX:** the cycle high-half check at core 0, class 0, index 0, seed
  `0x0000000100000000` returns zero instead of one. Its complete result is
  **714 failures among 5,251 checks**.

I parsed all 714 SimX failures independently: 357 missing high replies, 238
low-first truncated reconstructions and 119 high-first truncated
reconstructions. Every expected value derives from the stated seed; every
observed value is exactly the missing-high-half result. No unrelated failure
class is present. All 42 parent SimX objects were compiled and linked; this
evidence is not a mocked model, compiler failure or resource timeout.

## Limits and disposition

The strict runner retains `formal_qualification_eligible=true`,
`qualified=false`, `acceptance_claimed=false` and
`absolute_no_wrap_bound="not_established"`. This review accepts its declared
native regression evidence only. The hardware test is a DCR/MPM leaf, not a
full AFU run. SimX uses stable injected state without advancing simulation
ticks. Wider topologies, enabled extension paths, moving counters, concurrent
readers, atomic snapshots and an absolute no-wrap bound remain unqualified.

Binaries and full tool/library bytes are not archived. Their ten stable
before/after binary hashes are recorded observations, not independent binary
rehashes. Reported RSS is sampled, with a maximum of 862,720,000 bytes; the
4 GiB/15 GiB/16 MiB budgets are not hard cgroup quotas. No native rerun occurred
during this offline review.

**R3 disposition:** the contract's eight-cell and old-production numeric-failure
requirements are fulfilled. Landing still requires the separate cost and
integration dispositions. Historical warm results, the unconditional warm v1
block and all existing phase gates remain unchanged.
