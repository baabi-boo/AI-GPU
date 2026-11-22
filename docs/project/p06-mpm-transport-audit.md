# P06 host counter transport audit

## Outcome and development decision

The RV64 host counter defect is repaired in SimX and RTL. At `18c8880`, all
**eight strict native executions passed**, and both old-production targets
compiled and then failed the same high-half assertions. Independent review
closes the native regression obligation. The immutable host governance suite
also passed **2,910 tests**. Paired circuit measurements and the concrete
alternative comparison are reviewed: retain the direct decoder at `18c8880`.
Broader repository CI remains in progress at this documentation checkpoint;
no overall CI-green or publication claim is made here.

The next performance-development step is a reviewed qualification layer that
binds the repaired counter route, followed by a fresh complete warm experiment.
The repair cannot recover historical high bits or close a phase gate.

This audit began from clean authorized `master` at
`4df7186edbca82b21b2b8cba9b3b192248b99209`. The
[canonical roadmap](roadmap.json) keeps P00/P02/P03/P04 complete, P01 blocked,
P05/P06 in progress, and P07–P11 not started. The
[acceptance policy](acceptance.md) distinguishes implementation, execution,
independent review and phase acceptance.

## Why counter transport was the next step

The warm analyzer already blocks qualification under
`P06-WARM-RV64-MPM-HIGH-HALF`. A counter above `0xffffffff` could return a zero
high word while its query reported success. Apparently monotonic low words
cannot establish the required cycle comparison. Reliable transport therefore
precedes further performance optimization.

| Audited boundary | Finding and implemented response |
|---|---|
| [Public reconstruction](../../sw/runtime/common/perf.cpp) | `vx_device_mpm_query` assembles a `uint64_t` from two unsigned 32-bit DCR replies. API, tags, addresses and bus width remain unchanged. |
| [SimX host adapter](../../sim/simx/core.cpp) | Old RV64 high tags selected an absent architectural CSR alias. The adapter now reads the full low-address value and selects bits 31:0 or 63:32. RV32 retains its original route. |
| [Host-only RTL decoder](../../hw/rtl/core/VX_csr_mpm.sv) | Its XLEN-dependent macro omitted RV64 high reads. Both host halves are now decoded independently of XLEN, with zero-extension above the implemented 44-bit counter. |
| Architectural CSR paths | [SimX](../../sim/simx/csr_unit.cpp) and [device RTL](../../hw/rtl/core/VX_csr_data.sv) remain unchanged. No RV64 architectural high alias or response stage is added. |
| Historical build identity | P02-A02 pins the original [SimX Makefile](../../sim/simx/Makefile). The additive [MPM fragment](../../sim/simx/mpm_transport.mk) supplies the linked-model test without changing that pin. |
| Project navigation | Live status and handoffs now attribute the previously reviewed workspace correctness packet accurately, without inventing historical reviews or accepting new gates. |

The [frozen transport contract](../designs/host_mpm_transport_v1.md) defines
exact vectors, host/device semantics, native coverage, same-harness parent
sensitivity and narrow circuit comparisons.

## Demonstrated behavior

The [native packet](evidence/p06-mpm-transport/hosted/attempt3-native.json) and
[independent review](evidence/p06-mpm-transport/reviews/native-review.md) bind
[run 44983573225](https://github.com/baabi-boo/AI-GPU/actions/runs/44983573225)
to actual checkout `6e6426a0bf761baab11e932a4c86b49a5de81217`, tree
`d6dd742a905e0f3e76c7374cc678ba87e5c2a19e`, identical to candidate head
`18c888058ac851b802350c99770ed9ac2d27b582`.

| Native engine | Passed matrix | Observed checks |
|---|---|---|
| Production DCR/MPM RTL leaf | RV32/RV64 × PERF off/on | 1,056 reads, 19,912 assertions, 28 ignored requests; two-edge responses |
| Linked full SimX model | RV32/RV64 × PERF off/on | 18,064 checks through Processor/Cluster/Socket/Core/CsrUnit; each build compiles and links 41 model objects plus the harness |

The unchanged parent harness compiles successfully on pinned `4df7186` and
exits **1** in each engine. RTL reports tag `00220001`, expected high
`00000001`, actual `00000000`. SimX reports **714 failures among 5,251
checks**; independent parsing attributes every failure to missing high replies
or truncated reconstructions. Compilation failures and timeouts do not count.

These tests use stable seeded counters with TCU disabled. They do not establish
full-AFU or public-runtime end-to-end execution, broader topology, enabled
extensions, atomic snapshots, concurrency or an absolute no-wrap bound. Binary
hashes are retained observations; executable bytes are not archived. The packet
keeps `qualified=false` and `acceptance_claimed=false`.

## Circuit cost and integration

The [paired circuit review](evidence/p06-mpm-transport/reviews/circuit-review.md)
verifies eight Beacon runs followed by eight generic Yosys confirmations.
RV32 is unchanged. RV64 adds **21/417 estimated LUTs** with PERF off/on;
Beacon depth stays **4/8**. Yosys retains exactly **24/72 formerly discarded
high-counter register bits**, with path lengths unchanged at **7/10**. These
are observable wrapper bits, not new production pipeline registers.

Raw `NO-BASELINE` and RV64 area failures remain visible. The
[matched alternative review](evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the original review's specific missing-comparison F2. Shared decoding at
`27a18d4` passes the same native matrix and saves 2/68 estimated LUTs, but adds
9/21 generic cells, increases the PERF-off Yosys path from 7 to 8, and increases
PERF-on Beacon watch endpoints from 12 to 32. Its modeled delay also worsens.
The direct repair is retained as the lowest-cost depth-preserving tested
candidate under those cross-flow constraints. This is no proof of global
optimality and does not turn the raw area verdict green. The experimental PR is
closed without adopting its code. Neither flow establishes placed timing,
Liberty area, STA, physical Fmax or whole-GPU cost.

The [immutable governance run](evidence/p06-mpm-transport/host/governance-18c8880.json)
exits zero after 2,910 tests in 1,516.847 seconds at `18c8880`; the focused host
suite passes 73 tests. The [CI snapshot](evidence/p06-mpm-transport/hosted/final-ci-validation.json)
and [enforcement review](evidence/p06-mpm-transport/reviews/enforcement-review.md)
state their exact scopes and outstanding integration status. A standalone CLI
provenance follow-up remains: record `sys.executable` separately from PATH
`python3`. Hosted execution already requires those interpreters to agree.

The broader CI subsequently [failed its standard tensor DSP area check](evidence/p06-mpm-transport/hosted/broader-logic-gate.json):
267 → 283 exceeds the unchanged 5% limit. An
[independent comparison](evidence/p06-mpm-transport/reviews/broader-logic-gate-review.md)
matches the prior failure; the failing wrapper does not instantiate the changed
counter decoder. Thirteen other standard builds pass. This inherited issue
remains unresolved, and broader CI is not reported as green.

## Retained failures

The [evidence index](evidence/p06-mpm-transport/README.md) preserves both early
native matrices whose jobs failed during shallow-reference staging, the missing
`nanobind_backend` circuit import and subsequent Git-staging failure, initial
unsupported-OS configuration, and local disk-reserve rejection. Explicit backend
pinning and detached reference worktrees fixed the hosted setup defects.

The [development governance attempt](evidence/p06-mpm-transport/host/governance-development-attempt.json)
retains 2,873 tests with 104 failed subtests while imported sources changed.
Its identity guards rejected drift; it is not relabelled as a passing run.

## Next bounded action and preserved gates

For the next development continuation, follow the
[qualification plan](p06-mpm-qualification-plan.md): implement and independently review a
versioned source/configuration/binary binding, then collect a fresh complete
matched warm attempt under unchanged rules: **24 processes, 792 launches and
25,344 exact output words**, including excluded primes and warm-ups.

Preserve the unconditional warm v1 block, original cold execution pins and
[P06-A01 acceptance](evidence/p06-baseline/acceptance.json). P06-A02/A03,
[P05 custom-op review](p05-entry-handoff.md), vendor P01-A03, the inherited
267 → 283 DSP finding, physical FPGA and silicon obligations remain separate.
No fixture, tolerance, golden or acceptance record changes to absorb failure.

The [agent ledger](evidence/p06-mpm-transport/agent-ledger.md) counts completed
receipts toward ten waves of six workers. Execution identities remain tied to
the original validation commits when publication consolidates the changes.
Root owns final input-identity verification and authorized publication to `master`.
