# Counter diagnostics development task

Base master: 7455e008c1e001d3329e74fd55ffcd942592ec5f.

Selected bounded implementation: complete all 33 available native SimX backing-source transport diagnostics, real-model public runtime fault/coherence/terminal diagnostics, and strict retained diagnostic evidence. This advances P06-T01; it does not complete P06 or permit historical warm-v1 qualification.

Read AGENTS.md and the six w01 audit notes outside the checkout. No agent commits or pushes; root integrates and publishes to master. Disjoint file ownership, no goldens/threshold/default configuration edits. Local native build forbidden by observed disk budget; use host tests locally and existing bounded hosted workflow. Never reduce reserve/limits.

Implementation shape:
- Test-only typed member-access wrappers include unchanged socket.cpp, mem/cache.cpp, mem/memory.cpp. TCU uses a generated TU containing exact original tcu_tbuf.cpp bytes followed by its test-only accessor footer to preserve strict subobject-linkage diagnostics. Use ordinary compiler access checks and C++17 explicit-instantiation member access; no -fno-access-control. Production targets/objects/flags stay unchanged. Bind wrapper-to-original and generated-body/footer identities explicitly.
- Shared typed diagnostic counter interface under tests/unittest/checked_counters. Exact 33 names/classes/CSRs and components, all-zero origins, ten known values, both half orders, each component and split carry. Twelve L2/L3 unavailable rows receive no query.
- Real native public diagnostics must use unchanged common runtime, backend CP and Processor/RAM, with test-only linker interception when linking the diagnostic backend. Observe actual typed exceptions and destructor; no synthetic throw masquerades as native failure. Use a small actual scalar program uploaded via public buffers and DCR writes so no new kernel toolchain is needed for this control.
- Terminal positive diagnostic: after successful launch/read/queue destruction and buffer release, require one final Device reference, model idle, zero pending reads, completed pre-disable CP, all33 stable public reads, no relevant updates before actual destruction, followed by fresh-context success. Late real aggregate overflow must fail. Scope is serial direct-RAM, VM/L2/L3/WGMMA off p02-tfr.
- Source-bound mathematical lifetime proof uses monotone components plus checked terminal sum. No guessed tick rate/cap/timeouts. Ramulator finalizer source audit is separate from native execution evidence.
- Version diagnostic schema and report contract; all diagnostics/replay always keep qualified=false, ready_for_warm=false, full_warm_coverage=false, warm_execution=false. All33 transport can have its own narrow true result.
- Preserve old warm v1 and accepted cold evidence byte-for-byte. No speedup/phase acceptance claim.

Potential later bounded action: separately versioned qualification binding for seed-free measurement binaries, then unchanged fresh warm matrix.
