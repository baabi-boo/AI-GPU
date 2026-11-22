# Wave 6 independent lifetime-source review

## Verdict and scope

**No open F1, F2, or F3 finding. One initial F1 documentation precision finding was corrected by the root author and independently rechecked.** The conditional terminal theorem is valid for the stated 33 selectors and 40 actual backing components, subject to the runtime premises and loaded-dependency condition it explicitly retains. This review does not qualify a measurement binary, public native run, full warm caller, RTL parity, or hardware result.

Reviewer: `/root/w06_lifetime_review` (agent 34), independent of proof author `/root/w05_lifetime_proof`. This was a read-only source/evidence review. No repository file, production source, gate, threshold, golden data, or phase status was edited; no native build, GPU execution, or network access was performed. The review report and compact receipt are scratch handoff artifacts.

Reviewed proof: `docs/designs/simx_counter_lifetime_v1.md`; reviewed companion files: `lifetime-source-manifest.json`, `dependency-source-manifest.json`, and `dependency-source-bodies.json` under `docs/project/evidence/p06-counter-diagnostics/`. Source revision is `407ab9fea5e4f793a2a5088f566a87f3e631aa84`, audited base is `7455e008c1e001d3329e74fd55ffcd942592ec5f`, working HEAD during review is `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`. The corrected public diagnostic is a working-tree change and is not silently included in the pinned proof source revision.

Read and applied `AGENTS.md`, `docs/review/code-review-policy.md`, the SimX channel/quiescence rules in `docs/designs/simobject.md`, project status, roadmap, backlog, and acceptance policy. Findings use the repository's F scale. Exact receipt hashes bind this reviewed proof version.

## Finding F1-LIFETIME-01: HBM2 child finalizer dispatch is misnamed (closed)

**Severity:** F1. **Confidence:** high. **Evidence:** static proof. **Initial location:** `dependency-source-manifest.json:35`; the initial table wording in `simx_counter_lifetime_v1.md:281` required the same precision. The discussion below records the original finding, not the corrected final text.

The manifest says the empty selected finalizers include `IDRAM::finalize` for HBM2. The actual traversal calls the HBM2 object's `Implementation` virtual slot:

- Retained Ramulator `src/base/base.h:283` declares `TopLevel<T>::m_components` as `std::vector<Implementation*>`; `gather_components()` at 286–304 stores these pointers.
- `src/memory_system/memory_system.h:32–35` invokes `component->finalize()` on that vector.
- `src/dram/impl/HBM2.cpp:6` inherits both `IDRAM` and `Implementation`; its complete retained body contains no `finalize` override. The registration macro in `src/base/base.h:262–276` adds none.
- Therefore the traversal reaches empty `Implementation::finalize()` at `src/base/base.h:104`, rather than the separate empty `IDRAM::finalize()` at `src/dram/dram.h:139`.

Concrete discrepancy: a reader following the original manifest's exact HBM2 dispatch attribution would follow the wrong virtual slot. Both methods are empty, so the no-tick/no-callback conclusion is unchanged. The root author corrected the manifest and proof; I independently verified the final table and explanation at `simx_counter_lifetime_v1.md:292–301`. They now identify the empty inherited `Implementation::finalize` slot reached through the gathered `Implementation*` child. **Closed.** The proof was not edited by this reviewer.

The root's accompanying CP inference paragraph (`238–247`), failed-native history (`349–355`), seeded/unseeded mode distinction (`357–362`), and retained dependency-body descriptor were also reviewed and are accurate. The final proof SHA-256 is `85c265c2af0e5ced9641135fb8cc606885601a1cbd3fbf52c4da878cfb0fef3b`; lifetime manifest is `601ba960e5c57687d6cd2ee3c6cc6b3e60c53cdf5cc64158ebdee6c8a3d0fb3c`; dependency manifest is `3fb3332ecf76c5ee136bf68e2840f8e4e612a15f660a983d0913662cf8c469b6`. The retained raw source JSON is unchanged. Its new manifest descriptor correctly binds 99,341 bytes and its existing SHA-256. The lifetime manifest's dependency-manifest hash is rebound correctly.

## Independently reproduced identity and inventory checks

All of the following passed without using the proof author's pass status as authority:

| Check | Result |
|---|---:|
| SHA-256, byte size, and Git blob SHA-1 at pinned repository revision | 55 / 55 |
| Production bodies identical between source revision, audited base, and current tree | 45 / 45 |
| Retained original dependency bodies matched to manifest SHA-256, byte size, and Git blob SHA-1 | 21 / 21 |
| Repository gitlink matches dependency revision | `e62c84a6f0e06566ba6e182d308434b4532068a5` |
| Available exact selector tuples | 33 |
| Backing component references and unique identities | 40 / 40 |
| Unavailable exact selector tuples | 12 |
| Combined tuples agree with frozen `p06_contract.py::_COUNTERS` | 45 / 45 |
| Available selector scope/unit/class/CSR metadata agrees with contract | 33 / 33 |
| Local links in the final proof resolve | 41 / 41 (initial version: 40 / 40) |

`dependency-source-bodies.json` SHA-256 is `e5fd3d919e3c8f446381cc33e527c230c463010fc4178168e0ef52d21b187bbd`. Each embedded body was encoded as original UTF-8, preserving embedded CRLF, before hashing. The 12 excluded tuples are exactly the six L2 and six L3 selectors; no disabled selector is needed by the theorem. Twenty-six selected aggregates have one component and seven have two components.

The original model archive and its report also match the manifest hashes. The seven model cells pass in that retained report; both boundary cells report 6,389 checks, 1,788 transport half reads, 33 selectors and 40 source components. Those are seeded model prerequisites only.

## Theorem and selected storage

The theorem correctly distinguishes a mathematical aggregate from its returned copy. With nonnegative monotone components, all earlier component sums are bounded by the successfully checked terminal sum. This needs both checked component updates and a successful complete final aggregate. Component checks alone do not exclude two individually representable cache-bank values whose sum exceeds `uint64_t`.

The owning source supports zero initialization and preservation across admitted resets:

| Group | Source support |
|---|---|
| Core/base, 13 components | `sim/simx/core.h:40–72` initializes checked fields to zero. `core.cpp:494,526–527,565–569,790,793,982,1207,1212` and `lsu_unit.cpp:815–818` add nonnegative amounts. `core.cpp:444–478` preserves the selected fields. |
| I-cache 3 and D-cache 12 components | `sim/simx/mem/cache.h:61–80` initializes fields and checks accumulation. `cache.cpp:1194–1230,1293–1297,1341–1342,1434,1755,2128–2129,2173,2232` only increments selected fields. Bank reset at 873 onward preserves them. |
| Local memory, 3 components | `local_mem.h:44–47`, `local_mem.cpp:215,232,237,345`, and reset at 452–473. |
| Coalescer, 1 component | `mem_coalescer.h:34–35`, `mem_coalescer.cpp:286`; reset at 44–49 clears request state, not misses. |
| External memory reads/writes/latency, 3 components | `processor_impl.h:119–122`; callbacks at `processor.cpp:203–212`, accumulation at 344/449, reset at 429–435. Pending reads are correctly excluded: they are decremented and reset and must separately reconcile to zero. |
| External memory bank stalls, 1 component | `types.h:1696,1725–1736,1784` initializes/preserves/increments the checked crossbar collision counter; `mem/memory.cpp:77` makes the derived readout copy. The resettable cache-port collision statistic is a different, unselected counter. |
| TCU stalls/hits, 2 components | `tcu_unit.h:68–72`, updates at `tcu_unit.cpp:873,876,906`, preservation at 359–390. |
| TCU tensor-buffer reads, 2 components | `tcu_tbuf.cpp:34–40,68–73,92–111,194`. The `tcu_unit.cpp:1300` assignment is a derived copy, not another cumulative component. |

No selected reset, decrement, diagnostic reseed, or replacement appears on the admitted production paths. `PerfCounter` deliberately permits assignment and subtraction, so its type alone is not a monotonicity proof; the document correctly makes storage/update auditing and exclusion of diagnostic mutations explicit. The ordinary `uint64_t` alias is correctly separated from checked execution.

The final aggregation chain is complete: cache bank accumulation (`cache.cpp:3472–3480`), cache-cluster accumulation (`cache_cluster.cpp:83–88`), socket readout, checked coalescer accumulation (`csr_unit.cpp:215–218`), and checked tensor-buffer sum (`tcu_tbuf.cpp:106–111`). `csr_unit.cpp:125–247` selects the listed fields. Public MPM query (`sw/runtime/common/perf.cpp:277–286`) retrieves both halves and reconstructs 64 bits. Its unchecked all-core sum at 289–303 is expressly excluded. `core.cpp:1252–1273` restores the class only after success, so an exceptional aggregate can leave it changed; the failed lifetime must remain invalid.

## Terminal ownership, reset and teardown

The proof does not infer quiescence from endpoint subtraction or public release success. It requires prior successful launches, required flush/download completion, collected asynchronous execution, zero pending reads, actual queue joins, owner closure, final reference ownership, no active batch, and no concurrent submitter.

This is grounded in `ProcessorImpl::run()` (`processor.cpp:310–347`), full direct-RAM launch reset (`382–385,429–435`), and `SimPlatform::idle/reset` (`simobject.h:256–262,1225–1273`). Reset discards events, which cannot certify successful completion. `OperationState::release` and `RuntimeContext::release` (`sw/runtime/ai/runtime.cpp:181–206,121–144`) release events/queue and resources in the stated order. `ManagedMatmul::close` at 579–593 rejects shared ownership. Queue destruction joins before dropping the device reference (`queue.cpp:63–76`). `RefCounted::release` deletes only at the final reference (`vortex2_internal.h:82–100`); public release ignores that Boolean (`device.cpp:1477–1485`).

The proof correctly requires exclusive public low/high queries: `cp_submit_dcr_read` reads the final response after the submission lock has been released (`device.cpp:1007–1024`). Processor hooks use `AsyncRun::invoke` (`sw/runtime/simx/vortex.cpp:211–217`, `async_run.h:62–72`), which collects prior work and makes processor failures sticky. Direct-RAM `memcpy`/`RAM` DMA at `vortex.cpp:171–194` does not enter the timing processor, so suppression evidence must include direct-memory side effects as the proof requires.

`Device::cp_quiesce_` at `device.cpp:533–552` disables before polling and has silent failure exits; it is not a drain certificate. Backend destruction joins at `vortex.cpp:56–62`; callbacks close the backend through `vortex2_internal.h:202–204`; `ProcessorImpl::~ProcessorImpl` invokes finalize at `processor.cpp:231–233`. `SimPlatform::cleanup` stops workers, deletes events without firing, clears owned state, and zeros the platform clock (`simobject.h:1344–1382`). That clock is not a selected counter. VM-off frees follow allocator/host bookkeeping and do not add a selected updater.

## Dependency finalizers and callback boundary

The adapter configuration at `sim/common/dram_sim.cpp:175–209` selects GEM5 / GenericDRAM / HBM2 / Generic / FRFCFS / AllBank / OpenRowPolicy / RoBaRaCoCh, with no plugins when `DRAM_TRACE` is absent. The pinned factory gathers the selected tree (`src/base/factory.cpp:139–162`, `src/base/base.h:286–305`). Interface finalizers visit gathered implementation children and emit statistics (`src/frontend/frontend.h:34–44`, `src/memory_system/memory_system.h:32–42`). Aside from the F1 naming correction above, the selected children have the documented empty/statistics-only finalization. The Generic controller computes five averages at `src/dram_controller/impl/generic_dram_controller.cpp:401–410`; its callback is at 297–317 and is called from tick at 180–181. Registered scalar/vector emission (`src/base/stats.h:72–89`, `src/base/stats.cpp:5–9`, `src/base/base.h:165–192`) does not tick or send.

There is an independent adapter barrier: the Ramulator read callback only appends a response (`dram_sim.cpp:259–262`); the GPU callback runs in `drain` (`235–249`), called from adapter tick (`314–328`). The destructor at 292–301 calls interface finalizers but no tick, drain, request submission, or deletion of raw frontend/memory pointers. This establishes the conditional no-update suffix, not leak freedom. The proof correctly refuses to treat a cached dependency-library hash as compilation-origin attestation.

## CP and mode clarification (implemented and rechecked)

The updated test's drain inference is source-sound for the stated exclusive serial route. `CommandProcessor::enabled/busy` (`sim/common/cmd_processor.cpp:65–73`) combines both enable bits with `head < tail`, a loaded cacheline, nonidle command engine, or nonidle launch engine. Thus an enabled zero busy status excludes each of those conditions. Successful serialized retirement, expected count within 32 bits, one command per 64-byte ring entry, and tail accounting supply the remaining correspondence. The submitted tail low register is staged and the high register is committed (`102–106,160–162`), so the corrected test now accurately calls their combination `tail_register_pair_raw`. `head_addr` is programmed but never used to publish internal head; the initialized zero bytes are explicitly unsupported writeback evidence.

The final lifetime document now includes this inference and separates raw head/tail observations from the drain conclusion. This is an explanatory addition to an already explicit CP runtime premise, not a newly discovered F2/F3 flaw.

The modes are now distinguished explicitly in the final proof. `public_main.cpp:504–530,859–868` shows:

| Public mode | Main context | Separate final control |
|---|---|---|
| `normal` | Unseeded successful scalar lifetime | Fresh unseeded successful scalar lifetime |
| `coherent-terminal` | Successful scalar execution followed by deliberate component clear/reseed for transport | Fresh unseeded successful scalar lifetime |
| `immediate-overflow`, `delayed-overflow`, `cache-overflow` | Deliberately seeded failed lifetime; invalid numeric evidence | Fresh unseeded successful scalar lifetime |

A fresh success never rehabilitates its preceding seeded/failed lifetime. The final proof states the distinction explicitly, preventing every terminal vector from being described as unseeded.

## Native evidence boundary and next qualification work

The proof correctly claims no public native pass. I additionally inspected the retained original `run-45029135146-attempt1.zip` at checkpoint `81ed687…`: `public-counters/logs/public-normal.log` says `FAIL native public counter diagnostic: terminal CP ring is not drained`; the public report marks `public-normal` failed and the remaining four cells blocked. That is historical failed evidence, not “not run” evidence and not a pass for the corrected working tree. The seven separate model cells in that artifact remain separately scoped.

The next bounded qualification is a fresh, source-bound five-cell public native run of the corrected test, followed by independent original-artifact replay. Retain the failed attempt; require raw CP observations/statuses, exact 33 available and 12 unavailable tuples, 66 successful terminal half reads, no tick/reset/component drift, queue/resource/final-reference controls, actual destruction completion, each intentional typed failure, rejected later processor work and direct-RAM DMA mutation, and fresh-context controls. Keep seeded transport and failed contexts distinct from unseeded scalar lifetimes.

After that, bind the complete unseeded managed warm sequence, including every launch/reset generation, operation release/queue join, owner closure, exact inventory, terminal CP observations, and destruction suffix. Resolve the actual loaded dependency's selected-source provenance; a retained binary hash alone remains insufficient. Qualify the exact later measurement artifacts/configuration/environment/caller rather than inheriting a diagnostic's success.

P06/P06-T01 remain in progress, P06-T01-A02/A03 remain open, and warm-v1 keeps `P06-WARM-RV64-MPM-HIGH-HALF`, `qualified=false`, `ready_for_warm=false`, and `absolute_no_wrap_bound=not_established`. No acceptance is claimed by this review.
