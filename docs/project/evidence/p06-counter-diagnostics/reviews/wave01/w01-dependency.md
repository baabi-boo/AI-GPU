# Wave 1 pinned DRAM finalization audit

Audited AI-GPU master `7455e008c1e001d3329e74fd55ffcd942592ec5f` and the actual `third_party/ramulator` gitlink `e62c84a6f0e06566ba6e182d308434b4532068a5` from `CMU-SAFARI/ramulator2`. This is read-only source inspection, not a compiled or executed finalization test. No repository files, submodule state, production code, commits or remote refs were changed.

## Conclusion

The pinned dependency closes the specific source-level uncertainty about Ramulator finalization advancing the selected GPU counters. On the exact HBM2/GEM5/GenericDRAM route selected by the current configuration and clean native environment, frontend and memory-system finalization perform child finalization and statistics output. The only selected child with a nonempty finalizer is the Generic controller; it computes five floating statistics averages. No selected finalizer ticks the DRAM model, submits a request, invokes a request callback, or calls the GPU adapter.

The existing adapter supplies a second boundary: Ramulator receives a callback that only appends an adapter response. The GPU callback is invoked exclusively by `RamulatorDram::drain`, and that routine is invoked exclusively by `RamulatorDram::tick`. The adapter destructor invokes neither. Thus the exact teardown does not contribute any new selected GPU counter update. This conclusion does **not** prove prior quiescence, completed CP commands, final Device ownership, all-33 successful terminal readout, or whole-context no-wrap on its own.

## Exact route

- AI-GPU `VX_config.toml:92-108` supplies two memory banks and `VX_CFG_PLATFORM_MEMORY_TYPE = "HBM2"`; `profiles/p02-tfr.json` does not override the memory type.
- `sim/common/dram_sim.cpp:165-206` constructs `Frontend=GEM5`, `MemorySystem=GenericDRAM`, DRAM HBM2, controller Generic, scheduler FRFCFS, refresh AllBank, row policy OpenRowPolicy and address mapper RoBaRaCoCh. TraceRecorder is conditional on `DRAM_TRACE`.
- `ci/project/p06_mpm_execute.py:98-105` builds an allowlisted environment with neither `VORTEX_DRAM_MODEL` nor `DRAM_TRACE`, so `make_backend` selects Ramulator and no trace plugin is instantiated. This must be bound again for any new runner; a caller's ambient environment is insufficient proof.
- `third_party/Makefile:20-29` additionally links the GDDR6 registration extension. It does not select GDDR6 for an HBM2 request. The actual library identity and loading environment remain native packet obligations.

## Dependency call graph

1. `Factory::create_frontend/create_memory_system` construct the chosen implementation and collect its child implementations. `TopLevel::gather_components` only traverses the ownership tree.
2. GEM5 has an empty `init`, empty `tick` and no finalizer override or child creation. `IFrontEnd::finalize` iterates its child list and emits registered statistics.
3. GenericDRAMSystem creates HBM2, RoBaRaCoCh, and one Generic controller per configured DRAM channel. `IMemorySystem::finalize` iterates those components and their gathered descendants, then emits statistics. It never invokes `tick` or `send`.
4. Generic controller creates FRFCFS, AllBank and OpenRowPolicy. Its `finalize` at lines 401-409 computes average read latency and four queue averages, then returns. Its actual request callback invocation at lines 309-311 is in `serve_completed_reads`, reached from `tick`, not finalization.
5. HBM2, RoBaRaCoCh, FRFCFS, AllBank and OpenRowPolicy have no override of `Implementation::finalize`, whose body is a no-op. None overrides `print_stats`. `Implementation::print_stats` and `Stats::operator<<` recursively emit scalar/vector values; they do not call simulation functions or request callbacks.
6. The optional TraceRecorder was also inspected: it has no finalize override; it records only from `update`. It is excluded from the declared clean route regardless.

## Adapter boundary

At the audited AI-GPU source:

- `sim/common/dram_sim.cpp:235-248`: `drain` is the only place that calls `request.callback(request.arg)` and retires adapter request accounting.
- `sim/common/dram_sim.cpp:258-262`: the callback passed into Ramulator only performs `channel.read_rsps.push_back(...)`; it cannot invoke a GPU callback or tick the model.
- `sim/common/dram_sim.cpp:292-301`: the destructor calls `channel.frontend->finalize()` and `channel.memory_system->finalize()`, then restores the output stream. It does not call `drain`, `tick` or `send_request`.
- `sim/common/dram_sim.cpp:314-329`: only `tick` invokes `drain`, issues queued transactions and calls `memory_system->tick()`.
- The adapter stores raw dependency pointers and does not `delete` them in this destructor. Therefore no additional dependency destructor is invoked by this path. This observation is part of the call-graph proof, not a claim that dependency allocation cleanup is complete.

The exact selected dependency finalizers do not even queue adapter responses. The queue-only callback boundary nevertheless explains why request callback reachability and GPU-counter reachability are distinct obligations.

## Source bindings

All rows are at dependency revision `e62c84a6f0e06566ba6e182d308434b4532068a5`. The full 21-file inventory, SHA-256 values, byte counts, canonical URLs and original text are retained in sibling scratch files `w01-ramulator-manifest.json` and `w01-ramulator-sources.json`. Each retrieved UTF-8 body was independently checked against its reported Git blob SHA using `sha1("blob " + byte_length + NUL + bytes)`; all 21 matched, including original CRLF content.

| Dependency path | Git blob SHA-1 | Inspected responsibility |
|---|---|---|
| `src/base/base.h` | `1a7643ac1c931b92294f751aa1566df7586abbfa` | Default finalizer, child gathering, statistics traversal |
| `src/base/factory.cpp` | `2e3fe8b62740e957da8063b61963cf509e83f552` | Exact implementation selection and component gathering |
| `src/frontend/frontend.h` | `a1855bbf9fac3e172f46866fc0dc2f1d52a74298` | Frontend finalization |
| `src/frontend/impl/external_wrapper/gem5_frontend.cpp` | `1fdde713e0c2192f6ab75e4269714298f391f04f` | Selected frontend, no children/finalizer override |
| `src/memory_system/memory_system.h` | `beaf83cb71c042800adc375f8125bd39751e1080` | Memory-system finalization |
| `src/memory_system/impl/generic_DRAM_system.cpp` | `a7cce15d64c44b15366a92e107980e03d8c9d193` | Selected memory-system children and tick separation |
| `src/dram_controller/impl/generic_dram_controller.cpp` | `388a564a740745fd755db8abe92361570e33279e` | Statistics-only finalizer, tick-only callback delivery |
| `src/dram/impl/HBM2.cpp` | `39c4a65e45d223cf8e8e03e886a7a82cf90c76c1` | Selected DRAM, no finalizer/print override |
| `src/addr_mapper/impl/linear_mappers.cpp` | `3792f08e45de4fa5fd7e749cec35632cc6b240e3` | RoBaRaCoCh, no finalizer/print override |
| `src/dram_controller/impl/scheduler/generic_scheduler.cpp` | `2d0b389171ce80db608d1e70b4acc705019e7ef3` | FRFCFS, no finalizer/print override |
| `src/dram_controller/impl/refresh/all_bank_refresh.cpp` | `cf27477993951702c8ebc928378950608d2982f9` | AllBank, no finalizer/print override |
| `src/dram_controller/impl/rowpolicy/basic_rowpolicies.cpp` | `36a94d962064d6ab5edeb1ec18b9d6d653df0dab` | OpenRowPolicy, no finalizer/print override |
| `src/base/stats.h` | `3b6afa6bf6d83d20016461e37ba7c9ff4f7ab772` | Scalar/vector statistics emission |
| `src/base/stats.cpp` | `c1d8f864f0fc2b35116d1841a80460ac1d3ff543` | Registered-statistics iteration |

The remaining seven retained files are the selected interface headers and optional TraceRecorder implementation. Canonical source URL format is `https://github.com/CMU-SAFARI/ramulator2/blob/e62c84a6f0e06566ba6e182d308434b4532068a5/<path>`.

## What still must be proved

The dependency revision and current adapter source now support a no-later-update teardown argument. Native evidence must still bind the actual loaded dependency bytes and generated route, establish completed execution/queues/CP work and zero pending read balance **before** terminal readout, require exactly 33 successful available selector reads and twelve unqueried unavailable rows, show actual final destruction after releasing the last Device reference, and independently review the complete monotonicity/lifetime argument. Neither this source audit nor a successful release call makes warm measurements qualified. No warm speedup, P06 gate, native RTL or physical-device claim follows.
