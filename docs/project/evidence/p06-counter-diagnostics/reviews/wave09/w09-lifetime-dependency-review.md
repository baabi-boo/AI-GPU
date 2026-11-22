# Wave 9 independent lifetime and dependency review

## Verdict and scope

**PASS for the conditional source argument and its retained source bindings. No F2/F3 issue or source-theorem release blocker was found.** This is advisory review of the source proof, not warm qualification or measurement acceptance. The unresolved caller, executable, and dependency conditions remain mandatory before applying the theorem to a warm measurement.

Reviewer: /root/w09_lifetime_dependency_review, agent 51, wave 9 slot 3. The reviewer read AGENTS.md, the repository review and acceptance policies, current project status, roadmap and backlog, the prior independent wave 6 lifetime review, and the relevant wave 7 original-native audit. This review made no repository edits or commits, ran no build or test suite, and used no network. It inspected retained source and original artifact data only.

The working published HEAD was 4268d2d5d811063bb886cde7bd0e27e61a79c9b4. The separately observed native producer is e5f152464dda5e488d6d1a030c1fcdc49b5a9701. The lifetime manifest binds source 407ab9fea5e4f793a2a5088f566a87f3e631aa84 and audited base 7455e008c1e001d3329e74fd55ffcd942592ec5f. The dependency gitlink is e62c84a6f0e06566ba6e182d308434b4532068a5.

## Independently reproduced identities

All following checks passed. The full per-file results are retained in the accompanying JSON and in w09-lifetime-dependency-checks.json.

| Check | Result |
|---|---:|
| Pinned repository file SHA-256, byte size and Git blob SHA-1 | 55/55 |
| Current working bodies equal the pinned 407 bodies | 55/55 |
| Production bodies equal at audited base, 407, native e5, current HEAD and current working tree | 45/45 |
| Retained Ramulator UTF-8 body SHA-256, byte size and Git blob SHA-1 | 21/21 |
| Dependency gitlink equal at all four repository revisions | 4/4 |
| Available exact selector tuples | 33 unique |
| Backing component references | 40 unique |
| Unavailable tuples | 12 unique; exactly six L2 and six L3 |
| Available plus unavailable tuples equal frozen p06_contract.py inventory | 45/45 |
| Available selector scope, unit and macro metadata equal frozen contract | 33/33 |
| Aggregate component histogram | 26 single-component, seven two-component |
| Dependency-manifest, body-packet and adapter chained bindings | All match |
| Local links in final lifetime proof | 46/46 resolve |

Original UTF-8 bodies were re-encoded without normalizing their embedded CRLF before hashing. The retained source identities are not a claim about compilation origin of an installed library.

| Reviewed file | SHA-256 | Bytes |
|---|---|---:|
| docs/designs/simx_counter_lifetime_v1.md | 6b555d2920af3405c4af588de7e43d46e77619dc43dad263bf92141a60a4672d | 24,927 |
| docs/designs/simx_counter_public_diagnostics_v1.md | 025c9e58c4fb2d0d8eeb78ed1ab6d5fc65255f2e3bfeb9c454ac658a454a5ca5 | 20,458 |
| docs/project/evidence/p06-counter-diagnostics/lifetime-source-manifest.json | 601ba960e5c57687d6cd2ee3c6cc6b3e60c53cdf5cc64158ebdee6c8a3d0fb3c | 63,560 |
| docs/project/evidence/p06-counter-diagnostics/dependency-source-manifest.json | 3fb3332ecf76c5ee136bf68e2840f8e4e612a15f660a983d0913662cf8c469b6 | 16,601 |
| docs/project/evidence/p06-counter-diagnostics/dependency-source-bodies.json | e5fd3d919e3c8f446381cc33e527c230c463010fc4178168e0ef52d21b187bbd | 99,341 |

The public diagnostic main and both hook files also match e5 byte-for-byte. The final lifetime document was compared with scratch w08-lifetime-before.md. Its exact-route, terminal-theorem, inventory/update/reset, and finalizer sections are byte-identical. Changes are confined to the acceptance-ID correction, CP explanation, and separately scoped native evidence status. No added text extends a scalar diagnostic to the full managed warm sequence.

## Conditional theorem and selected storage

The mathematical implication at lifetime proof lines 62–113 is sound. Zero-based nonnegative, monotone selected components give every earlier component value no larger than its terminal value. A successful checked terminal sum from zero gives the complete terminal aggregate at most UINT64_MAX. Summing the earlier inequalities bounds every earlier aggregate, including one never previously queried. The no-update suffix extends that bound until the relevant storage is destroyed.

Neither endpoint subtraction nor individually checked components supplies the final aggregate bound. Two representable data-cache bank values can have an unrepresentable sum. A previously rejected checked update or aggregate invalidates that lifetime even if later queries succeed. PerfCounter supports assignment and subtraction, so monotonicity comes from the audited selected production paths, not the type name. Its ordinary-build alias is uint64_t; the checked diagnostic cannot automatically qualify a later ordinary measurement binary.

The independent source inspection agrees with the manifest's selected updates and reset preservation:

| Selected storage | Source evidence and implication |
|---|---|
| Core/base, 13 components | core.h:40–72 initializes checked fields; core.cpp:494, 526–527, 565–569, 790, 793, 982, 1207, 1212 and lsu_unit.cpp:815–817 add nonnegative quantities. core.cpp:444–478 preserves them on reset. |
| I-cache and D-cache, 15 components | cache.h:61–80 supplies zero initialization and checked accumulation. cache.cpp selected updates are increments at 1194–1230, 1293–1297, 1341–1342, 1434, 1755, 2128–2129, 2173 and 2232; on_reset at 873 onward preserves perf_stats_. |
| Local memory and coalescer, four components | local_mem.h:44–47 and mem_coalescer.h:34–35 initialize selected fields. Local-memory increments are at 215, 232, 237 and 345; reset 452–473 preserves them. Coalescer miss addition is at 286 and reset 44–49 preserves it. |
| External-memory reads, writes and latency, three components | processor_impl.h:119–122 initializes storage; processor.cpp:203–212 increments request totals and tracks the separate pending balance; latency adds that balance at 344/449. Reset 429–435 clears the pending balance, not the three selected totals. |
| External-memory bank stalls, one component | types.h:1696, 1725–1736, 1784 initializes, preserves and adds to checked crossbar collisions. memory.cpp:77 returns the derived statistic. The resettable cache-port collision statistic is a different, unselected field. |
| TCU stalls/hits and tensor-buffer reads, four components | tcu_unit.h:68–72, tcu_unit.cpp:359–390 and 873/876/906 support zero initialization, preservation and increments. tcu_tbuf.cpp:34–40, 68–73, 92–111 and 194 preserve and increment the two Buffer::reads_ components, then sum them with checked additions. |

Checked aggregation proceeds through cache.cpp:3472–3480, cache_cluster.cpp:83–88 and socket readout; csr_unit.cpp:215–218 also uses a checked coalescer accumulator. TCU readout assigns the already-checked tensor-buffer total at tcu_unit.cpp:1298–1301; it is a derived copy, not another cumulative component.

The document accurately excludes transient pending reads and derived/unselected state. Core::perf_stats() recomputes opds_stalls at core.cpp:1281–1286. The proof therefore does not assert that all statistics storage is immutable during readout. Similarly, SimPlatform reset/cleanup changes its clock and reset generation; those are control state, not the selected core cycle counter. No reset, decrement, replacement or reseed of the selected production storage was found on the admitted paths.

## Caller, exclusivity and CP boundary

The source supports the document's premises; it does not make those premises automatic for a new caller.

ProcessorImpl::run at processor.cpp:310–347 exits when cores are no longer running and platform delivery is idle, with VM excluded. Cache flush loops at 277–307 can tick and must precede the terminal vector. SimPlatform::reset at simobject.h:1225–1273 deletes pending events and explicitly requires a quiescent caller; deleting work cannot establish successful completion. The pending-read balance must separately be zero before reset and at terminal observation.

OperationState releases events and its queue before operation buffers (runtime.cpp:181–206). The actual Queue destructor joins its worker before unregistering and releasing its device reference (queue.cpp:63–76). ManagedMatmul::close rejects shared ownership (runtime.cpp:579–593), and RuntimeContext releases buffers, kernel and module before device release (121–144). RefCounted::release deletes only on the final reference (vortex2_internal.h:82–100); public vx_device_release ignores its Boolean result (device.cpp:1477–1485). Consequently wrapper call counts or a success return are insufficient evidence of actual queue/backend destruction.

Public MPM readout reconstructs both halves at perf.cpp:277–286. The unchecked all-core summation at 289–303 is explicitly excluded. device.cpp:1007–1024 reads Q_LAST_DCR_RSP after cp_submit_cl_ has released its submission lock, so caller exclusivity is necessary. The processor hook invokes AsyncRun::invoke (vortex.cpp:211–217; async_run.h:62–72), which collects prior work and makes processor failures sticky. Core readout restores its saved class only on success (core.cpp:1252–1273); failure must invalidate that context.

The CP explanation is source-correct. enabled() requires both enable bits, and busy() then covers head < tail, loaded cacheline, command engine and launch engine (cmd_processor.cpp:65–73). The head-writeback address is programmed/read but never used to publish internal head. Low tail reads expose staging; high reads expose committed high bits (102–106, 160–162). Runtime submission writes one 64-byte line, increments expected retirement, stages low, commits high, and waits for its target (device.cpp:651–661, 719–764). The diagnostic additionally requires expected sequence to fit the 32-bit observed window (public_main.cpp:293–298).

The original normal terminal record was inspected as data: control and queue_control are 1, status/error are 0, sequence advances 26 to 92, and runtime/raw-pair tail advances 1,664 to 5,888, exactly 64 bytes per command over 66 half reads. Raw head remains 0 with status not-published. These facts support drain inference under the diagnostic's exclusive serial conditions; they do not measure the internal head or provide a general atomic public snapshot.

Device::cp_quiesce_ disables before polling and can return silently on errors or exhausted polling (device.cpp:533–552). It cannot certify drain. Direct-RAM backend DMA uses memcpy/RAM::read/write without entering the timing processor (vortex.cpp:171–194); failure suppression must include actual RAM side effects, not only processor entry counts.

The existing warm caller resets completed operation objects before its intermediate snapshots and uses a before-release observer (main.cpp:433–463; observer.cpp:211–225). Its enabled set is capability-derived (observer.cpp:121–131), and valid_snapshot only validates that chosen subset (main.cpp:153–171). Those sources do not establish the exact 33/12 inventory, all queue joins/final references, and CP premises for the full warm caller. The proof explicitly retains that gap.

## Finalizer dispatch and callback confinement

The wave 6 F1 dispatch correction remains correct. In the retained Ramulator sources, Factory gathers children (factory.cpp:139–162), and TopLevel stores/traverses Implementation pointers (base.h:280–305). Frontend and memory-system finalizers invoke component->finalize() through those pointers (frontend.h:34–44; memory_system.h:32–42). HBM2 inherits IDRAM and Implementation without overriding finalize. Thus this child-dispatch path calls the empty inherited Implementation::finalize at base.h:104, not the separate IDRAM virtual slot. The current proof states this accurately at lines 300 and 307–309.

The selected graph matches dram_sim.cpp:175–209: GEM5, GenericDRAM, HBM2, Generic, FRFCFS, AllBank, OpenRowPolicy, RoBaRaCoCh and no plugin when DRAM_TRACE is absent. GEM5 creates no children. GenericDRAM creates its DRAM, mapper and controller children; Generic creates scheduler, refresh and row-policy children. Its finalize at generic_dram_controller.cpp:401–410 computes five floating-point averages. The other selected implementation finalizers are empty. Registered statistics are arithmetic scalar/vector values; base.h:165–192, stats.h:72–89 and stats.cpp:5–9 emit them without ticking or request submission.

The Generic controller delivers read callbacks only in serve_completed_reads at 297–317, reached from tick at 171–181. The adapter callback at dram_sim.cpp:259–262 merely appends a read response. Delivering the GPU callback requires adapter drain at 235–249, reached from tick at 314–328. The destructor at 292–301 invokes interface finalizers but no tick, drain or request submission, and does not delete its raw frontend/memory-system pointers. That supports the conditional no-update suffix; it is not a memory-leak proof.

The outer destruction path is also consistent: VM-off Device frees perform allocator/host bookkeeping (device.cpp:165–190, 1232–1257); CallbacksAdapter closes the backend (vortex2_internal.h:202–204; callbacks.inc:52 onward); backend destruction joins (vortex.cpp:56–62); ProcessorImpl destruction calls SimPlatform::finalize (processor.cpp:231–233). Cleanup stops workers, clears ownership, deletes events without firing, and resets the platform clock (simobject.h:1344–1382). The diagnostic destructor wrapper observes real destructor completion (public_hooks.cpp:245–268). Its zero post-cleanup clock is not a measurement that proves no intervening ticks; the source suffix argument and prior idle/exclusivity premises do that work.

## Native evidence boundary and historical annotation

The corrected original archive was rehashed: 4,228,429 bytes, SHA-256 05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276. Its inert reports identify native e5, seven model passes, one separate passing public boundary control and five passing public modes: 13 native process cases. This review did not rerun their execution or the existing comprehensive wave 7 audit.

The raw mode records contain seven terminal snapshots: normal has two unseeded successful contexts; coherent-terminal has one seeded snapshot and a separate fresh unseeded control; each overflow mode has a seeded failed context and its own fresh unseeded successful terminal snapshot. The fresh control does not rehabilitate the failed or reseeded lifetime. The native record and proof do not claim full managed warm-workspace coverage, seed-free measurement qualification, hardware execution or acceptance.

**F0-LIFETIME-01 — preserved source-audit history needs an explicit current-index note.** Confidence high; evidence type static-proof; not a source/theorem release blocker. The frozen lifetime manifest's observed_native_evidence at lines 1746–1774 is the 407/run45026112992 seeded model record. public_diagnostic_checkpoint at 1776–1779 names 81ed and does not claim a native result. remaining_obligations[0] at 1782 still requests the subsequently completed public diagnostic. phase_state at 1800 contains the original P06-T01-A02/A03 identifier typo. The canonical acceptance IDs are P06-A02/P06-A03. The final proof prose correctly distinguishes the later e5 pass and uses the correct IDs.

Preserve the manifest bytes and add this clarification to a current index:

> The lifetime source manifest is retained unchanged as the 407-bound source-audit snapshot. Its pending-public-diagnostic status predates the separately retained corrected native pass at e5f1524 (run 45031746149); read the current native index and independent wave 7 audit for that outcome. Its P06-T01-A02/A03 string is an original identifier typo: the acceptance IDs are P06-A02 and P06-A03. Complete warm-caller qualification, loaded dependency provenance and measurement acceptance remain open; qualification and readiness flags remain false.

## Remaining qualification blockers

1. Bind and independently validate the complete unseeded managed warm caller, every launch/reset generation, the exact 33/12 inventory, actual queue joins, owner/final references, collected execution, pending-read reconciliation, terminal CP-before-disable state and destruction suffix. Directed scalar controls do not discharge that obligation.
2. Bind the actual loaded dependency to the selected source behavior. The retained 21-body audit, repository gitlink and cached binary hash establish different facts. The dependency manifest expressly records dependency_binary_source_attestation=false. No source-to-binary attestation was established here.
3. Qualify the precise later measurement executable, runtime, generated configuration, loader closure, workload and environment. The checked/seed-capable diagnostic binaries and later replay publication do not automatically qualify an ordinary seed-free measurement process.

These are existing limits of a correct conditional argument, not newly discovered flaws in that argument. P06/P06-T01 remain in progress; P06-A02/P06-A03 remain open; P06-WARM-RV64-MPM-HIGH-HALF remains unconditional; qualified=false, ready_for_warm=false and absolute_no_wrap_bound=not_established. This review claims no acceptance or warm execution.
