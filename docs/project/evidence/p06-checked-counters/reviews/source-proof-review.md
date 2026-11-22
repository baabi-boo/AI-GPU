# Independent source and arithmetic reviews

This record summarizes three independent, read-only reviews of candidate
`53f4ad08c469a1cc73fa604249b302f9416055e0` against integrated upstream
`89aa43236038fcfff5d36a7cdb95646b038fe2fb`. The root coordinator retained their
findings here. None of the reviewers authored these changes, edited files,
built the model, ran tests or published the candidate.

| Reviewer | Reviewed scope | Result |
|---|---|---|
| `/root/w05_a01_guard_core_review` | Exception primitive and all thirteen selected Core paths, including LSU and retirement gathering | No F2/F3 found; scoped landing recommendation subject to remaining evidence |
| `/root/w05_a02_memory_proof_review` | Nine cache, three local-memory, one coalescer and four global-memory selectors | No F2/F3 found in scoped storage and formed aggregates |
| `/root/w05_a03_tensor_crossbar_review` | Three tensor-buffer selectors and overlapping crossbar source review | No F2/F3 found; explicit aggregate-lifetime and exact-profile limits |

The advisory classifier reports R2 with SimX/RTL-lockstep and configure-copy
notices. Review depth was R3 because this change introduces an enforcement
contract. The ordinary alias preserves the exact original field types,
initializers, operands and operations. No reviewed hunk changes scheduling,
queue depth, numerical arithmetic or modeled event order; checked mode adds
host work and changes invalid-counter behavior. This is static reasoning,
not an executed model-parity result.

## Arithmetic and Core inventory

For `U = UINT64_MAX`, addition checks `delta <= U - value` before mutation;
subtraction checks `delta <= value`. Signed operands are checked before
conversion. Self-operations capture their old operand value. The exception
contains an enum and static diagnostic strings, with no dynamic diagnostic
construction. It does not claim allocation-free exception runtime machinery.

| Selected values | Actual updates | Exact operand |
|---|---|---|
| Cycles | Core tick while work exists | One |
| Instructions and TCU instructions | Every relevant retirement gather call at end of packet | One; no assumed one-retirement-per-cycle rate |
| Scheduler idle | Schedule without a fetch candidate | One |
| Active/stalled warps | Scheduler mask population counts | Bounded nonnegative count |
| Issued warps/threads | Each scheduled trace | One or thread-mask population |
| Scoreboard/LSU/TCU stalls | Actual blocked issue/dispatch branches | One |
| Loads/stores | LSU dispatch request-mask count | Exact four-lane-profile conversion |

All thirteen Core fields start at zero and survive launch reset. Query-time
operand-stall recomputation is separate and outside the selected inventory.
Assignments and scalar conversions remain possible, so the type alone is not
a universal no-wrap type system; source review remains necessary.

## Memory inventory and meaning

The nine selected cache fields use checked unit increments at admission,
MSHR rejection, pipe-exit miss and eviction/dirty-sector flush sites. Each
increment remains individually guarded even inside nested loops. Per-bank
and per-cache reductions use `Cache::PerfStats::operator+=`, then preserve
values through Socket and CSR readout.

Local-memory reads, writes and stalls use checked unit increments. Coalescer
misses add a Boolean predicate; the CSR reduction now uses a checked local
accumulator. Processor reads/writes and pending reads add Boolean event counts;
responses decrement the checked pending balance. Global memory latency adds
that checked pending balance without an unguarded scalar sum. Crossbar
collisions add a Boolean predicate; Memory publishes the exact source value.

Cumulative storage survives the inspected reset paths; temporary query totals
start at zero. Pending balance retains its explicit reset, whose validity
still depends on quiescent ownership and matched requests/responses.

`memory_lt` preserves its existing meaning: pending occupancy is accumulated
in Processor run/cycle paths. Other flush and CP-transfer loops may advance
the platform without adding to this counter. It is not an integral over every
platform tick.

## Tensor sources and exact route

Tensor stalls and cache hits use checked unit increments in the WGMMA path.
Private buffer read counts use checked increments at the issued bank-row-read
site; the total across buffers uses a checked local accumulator before
assignment to the published snapshot. Reset/invalidation preserves the
cumulative backing counts. Crossbar reset preserves collisions too.

The exact dense `p02-tfr` profile disables WGMMA. The inspected tensor-buffer
counter increment/fill producers are within that disabled path, so ordinary
execution of this route leaves the three tensor-buffer values at zero.
They remain available selectors and require queries; zero does not prove
high-word source selection. The harness correctly seeds the actual stalls
and cache-hit fields but leaves the private buffer read source unseeded.

## Aggregate lifetime boundary

A successful guarded update bounds its stored component. A successful guarded
read bounds the aggregate it actually forms. Those facts do not continuously
bound a mathematical sum of independently growing components between reads.
For example, two valid component values may sum above `U` before an aggregate
query rejects that total. A future complete qualification needs continuous
aggregate enforcement or a terminal quiescent observation, proven component
monotonicity and proof that no later updates occur. The revised contract makes
this distinction explicit instead of asserting a complete lifetime bound.

The reviewed aggregate operations are not transactions: earlier fields or
model side effects may precede a later counter exception. Only the rejected
primitive is guaranteed unchanged. The context must remain terminal.

## Exception path and exclusions

Inspected update/aggregate/serial dispatch paths allow exceptions to propagate.
No inspected destructor performs guarded arithmetic. `run_checked()` and the
synchronous `AsyncRun::invoke()` boundary retain processor failures; cleanup
joins before disposal. The legacy catch-and-return processor entry is excluded.

Cache-internal non-warm collision sources and operand-stall sources are not
qualified by these reviews. Extra checked fields do not expand the inventory.
The manifest partition was independently confirmed: 19 seeded available,
14 unseeded available and 12 unavailable rows, with no overlap or omission.
Uniform compilation, native execution, actual public counter-failure handling,
all-33 transport, coherent snapshots and the full lifetime argument remain
separate obligations. No warm readiness or phase acceptance is granted.

## Source identities

The following SHA-256 values were recomputed by the coordinator from the
reviewed immutable commit; they identify source, not execution evidence.

| File | SHA-256 |
|---|---|
| `sim/common/perf_counter.h` | `8635c832c9fc4ad60cf3bf21665a5bc22a6d3500b1f5c012dd056fb4c6907417` |
| `sim/simx/core.h` | `642af0adfae25333fc822289293a0d10273f58c8b1442a4acad63fad5a2f8609` |
| `sim/simx/core.cpp` | `f95003971a6052962b761b1ee8e815ead42f6a60fccf8157fa94c3ded3e44f31` |
| `sim/simx/lsu_unit.cpp` | `d1105256786bc7f2227d4c963a0b4368d84d480aba93fdf3188019ae466b30fb` |
| `sim/simx/types.h` | `c09d02ca868b9b7fd28142c4c5aa922b9500975feddaf92695d220a5be6bd546` |
| `sim/simx/csr_unit.cpp` | `c35bd6a80120f76c9cf65076c736aaf577329285a74aac8c11c03f0ce829fc3d` |
| `sim/simx/processor_impl.h` | `f72e86ce9204a80a8246ab9c6ec1fab9bfccaf334a5ee487e4dc9dc01a7f921b` |
| `sim/simx/processor.cpp` | `569cf629d1e25ec9a295b20bfadfabbe21cd0989127f2b825fceee99a8062b78` |
| `sim/simx/mem/cache.h` | `839637e7738c774b02f1f556da86a4c716215696a70dd384d9e413ad6943653b` |
| `sim/simx/mem/cache.cpp` | `c8eacd73616bb9f82533bbe45ba8a317524717948de08d73ecdb78dfb0c4a53d` |
| `sim/simx/mem/cache_cluster.cpp` | `ad5e592d87234764df3186c8fdd9dbfc18b2a7dbdfdb207ba2cc6071d4e3fa44` |
| `sim/simx/socket.cpp` | `e30e63d3523411bad58eb49c8526aabe032bed584c8d044b677c18906cf844d4` |
| `sim/simx/mem/local_mem.h` | `708446110e56f8cce88f50bcbca8fb8e1ff741a4019e16b4c9fda48d86f67635` |
| `sim/simx/mem/local_mem.cpp` | `07aa27331d6ef604a432b99e70df12b7853787d4151cc1517092d76406cd4d33` |
| `sim/simx/mem/mem_coalescer.h` | `3368578b678a354eb5a876d1121351cd22987c729514fcfb7bfe4d86795961c7` |
| `sim/simx/mem/mem_coalescer.cpp` | `9fcf09145f6fee29c5f5494fff155f2c0fa90e5f984893cb756c31d75b155a88` |
| `sim/simx/mem/memory.h` | `8cdd7e1945842b3f58f64bcb3fad1fd3e61555cbc82d9063996e53453a71301a` |
| `sim/simx/mem/memory.cpp` | `4d73809cd63a0c768115c5de0205989f6f941446895de1831587002fc94ed474` |
| `sim/simx/tcu/tcu_unit.h` | `8546c4db53cc938c9a91ddcab002fa020195d39b93f9e35de3c21d9ecee28cb8` |
| `sim/simx/tcu/tcu_unit.cpp` | `b48d0e7fe5145292ad354168d3fe73b0bcdbbb508335656ce6fe07608af8fb5b` |
| `sim/simx/tcu/tcu_tbuf.h` | `8b05c6d23de3d5fb5423d7ce93d1d1a1395a4d474856371281ed943abe8c2be3` |
| `sim/simx/tcu/tcu_tbuf.cpp` | `eb20f6c16dd0915bebf39a0f85f7c11ee28a0ed681418385205b898f4b557463` |
| `sw/runtime/common/async_run.h` | `a9f63b2a896c5e512f7c592c758618ea88b774c9dac4bca29e847e2e3719a24e` |
| `profiles/p02-tfr.json` | `79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102` |
