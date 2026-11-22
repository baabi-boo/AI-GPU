# Wave 1 lifetime audit

Source inspected: `7455e008c1e001d3329e74fd55ffcd942592ec5f`. Audit only; no production edits, builds or executions.

## Conclusion

The existing `before_release` observation is a sound candidate terminal point **only for the exact serial, VM-off, direct-RAM CP route**. No new installed runtime API or counter cap is necessary to pursue its proof. The smallest useful next implementation is a dedicated native terminal diagnostic, fixed all-33 inventory validation and a source-bound lifetime record; keep warm readiness false until dependency, native behavior and independent review obligations all pass.

The lifetime theorem is: every selected component starts at zero, only increases through checked updates, survives permitted launch resets, and is never updated after a complete successful terminal checked aggregate observation. Thus each earlier sum is bounded by its terminal value, which is at most UINT64_MAX. Checked components alone do not prove the aggregate premise.

## Existing ordering and concrete gaps

1. `tests/regression/ai_warm_workspace/main.cpp:433-453` destroys each operation before snapshots, then closes the owner before collecting the observer's saved terminal result. `sw/runtime/ai/runtime.cpp:181-211` releases events and the queue, then buffers; `sw/runtime/common/queue.cpp:63-75` drains and joins the worker before releasing its Device reference. `ManagedMatmul::close()` rejects surviving operation ownership (`runtime.cpp:579-592`).
2. `RuntimeContext::release()` releases resident buffers, kernel and module before calling `vx_device_release` (`runtime.cpp:121-139`). The observer verifies owner-close phase and zero live observed buffers and queries before the real release (`observer.cpp:211-225`).
3. Inventory is currently dynamic: `observer.cpp:121-126` derives enabled rows from capability bits; `main.cpp:153-171` accepts any successfully queried enabled subset. The new terminal diagnostic/reader must independently require precisely the 33 expected available rows and 12 unavailable/unqueried rows. Do not assume the existing predicate proves all-33 coverage.
4. `vx_device_release()` reports successful reference release, not final destruction (`device.cpp:1477-1485`). `RefCounted::refs()` exists internally (`vortex2_internal.h:94`); a test-only native terminal probe can require one final Device reference and no remaining queues/operations. Avoid exporting a new ABI for this diagnostic. The production benchmark's exact call graph must separately exclude external retains, legacy clients and concurrent DCR submitters.
5. `Device::cp_quiesce_()` is void and may return on MMIO failure, all-ones status or exhausted polling (`device.cpp:533-552`). It disables queues before checking busy. It is not a drain certificate. Instead establish all synchronous commands and queue workers completed *before* the terminal observation, and diagnose pre-disable CP state while the live queue is still enabled.
6. `cp_submit_dcr_read()` reads `Q_LAST_DCR_RSP` after its submission lock has been released (`device.cpp:1007-1024`). Coherence needs the dedicated single-submitter process, not merely two successful reads. SimX hooks invoke `AsyncRun::wait()` before model DCR operations (`simx/vortex.cpp:211-217`, `common/async_run.h:62-72`); model MPM reads themselves do not tick.

## Source map for monotonicity and last updates

| Selected group | Source/update/reset evidence | Lifetime issue |
|---|---|---|
| 13 Core/base | `sim/simx/core.cpp:473-494,526-569,788-793,982,1202-1212`; LSU loads/stores `lsu_unit.cpp:815-817` | Stats survive reset; nonnegative counts accumulate only during model execution. |
| 9 I/D cache | `mem/cache.h:61-80`; `cache.cpp:874,1194-1230,1293-1297,1341-1342,1434,1755,2128-2129,2173,2232`; aggregation `3472-3476`, `cache_cluster.cpp:83-87`, `socket.cpp:452-455` | Six D-cache selected values aggregate two independent banks; terminal checked read is essential. Nonselected cache bank collision storage has different reset behavior and must not be generalized into the claim. |
| 3 local memory | `mem/local_mem.cpp:215-237,345,452-453` | Shared checked statistics survive reset. |
| Coalescer misses | `mem/mem_coalescer.cpp:286`; checked CSR accumulation `csr_unit.cpp:215-217` | Single block in exact route; aggregation remains checked. |
| 3 global memory | `processor_impl.h:119-122`; `processor.cpp:203-211,344,429-434,449` | Pending reads is transient and explicitly reset; require zero/reconciled balance before reset. `memory_lt` is run/cycle-loop occupancy, not every platform tick. |
| Global bank stalls | `types.h:1696,1720-1736,1784`; `mem/memory.cpp:76-78` | Checked crossbar accumulator survives reset. |
| 3 TCU | `tcu/tcu_unit.cpp:349,360,873-906,1300`; `tcu_tbuf.cpp:40,68-72,106-111,194` | Buffer reads aggregate two private sources; retained counters are monotone. Ordinary WGMMA-disabled execution leaves TCU buffer activity zero but does not excuse distinct transport coverage. |

`ProcessorImpl::run()` waits for no running core plus `SimPlatform::idle()` (`processor.cpp:339-345`). Flush loops tick until hierarchy/platform drain (`243-307`). Direct-RAM CP copies call RAM directly (`sw/runtime/simx/vortex.cpp:173-194`); LLC CP copies call `cp_mem_transfer()` which ticks (`processor.cpp:358-378`). Therefore the proof must require CP_ON_L2=CP_ON_L3=0 and VM off. All flush/copy work relevant to the final output must precede terminal readout.

After a proven drained terminal read, allocator frees with VM off are host bookkeeping (`device.cpp:1232-1257`), CP host frees are host memory operations (`simx/vortex.cpp:133-142`), backend destruction joins already-complete execution (`56-61`), and `ProcessorImpl` finalizes the platform (`processor.cpp:231-233`). Timing-platform cleanup stops workers, deletes events without firing them and clears state (`sim/common/simobject.h:1344-1381`). These paths do not themselves tick the model.

## DRAM dependency finding

Ramulator is **not** passed GPU callbacks directly. Its read callback only appends an adapter response (`sim/common/dram_sim.cpp:258-262`). GPU callbacks run solely from adapter `drain()` (`235-248`), called by adapter `tick()` (`314-320`). Destructor calls frontend/memory-system `finalize()` but neither `drain()` nor `tick()` (`292-301`). This is a strong adapter-level no-counter-update boundary even if dependency finalization delivers a pending read callback. Still inspect and bind pinned Ramulator `e62c84a6f0e06566ba6e182d308434b4532068a5` before claiming the plan's full dependency obligation; that submodule is uninitialized in this checkout. No dependency finalizer execution was performed here.

## Proposed bounded acceptance diagnostics

- Native actual-runtime serial success: complete a real kernel and download, destroy operation/queue, release module/buffers, then collect exactly 33 two-half reads and verify 12 rows receive no query; retained tick counts and all selected values must stay unchanged across repeated terminal reads and teardown observation points.
- Native final-reference/ownership probe: require one Device reference, zero surviving queues/operations, healthy collected execution, pre-disable CP completion, model idle and zero pending memory-read balance. An extra retained Device or queue must invalidate the diagnostic rather than be mistaken for disposal.
- Real multi-bank late aggregate overflow: independently seeded D-cache bank totals individually fit but sum exceeds UINT64_MAX; terminal public query must fail and poison the context, including if it occurs after last measured operation.
- Last-update sensitivity: diagnostic-only deliberately tick or invoke a relevant updater after the proposed terminal mark, then assert rejection; ordinary diagnostic cannot claim terminality merely because two samples match.
- Full disposal/fresh-context success and persistent failed-context rejection. Retain separate direct-RAM positive and LLC/VM unsupported or negative cells; do not broaden qualification.
- Qualification-reader rejection for a missing terminal row, falsely disabled required row, queried unavailable row, failed cleanup, extra retain/unjoined queue, mismatched source/configuration/dependency/binary and missing independent review.

These diagnostics should not introduce seeds into the measurement binary or change workload, sampling, timing, golden values or acceptance gates. All native execution requires hosted resources under the existing budget; local disk is insufficient for the 15 GiB native reserve.
