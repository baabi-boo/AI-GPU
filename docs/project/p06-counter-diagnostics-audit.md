# P06 native counter diagnostics audit

## Decision

Continue P06-T01 with **complete native backing-source diagnostics and actual
public-runtime failure/terminal observations**. The audit started from clean
`master` at `7455e008c1e001d3329e74fd55ffcd942592ec5f`; the implementation and
verification history are recorded in the associated evidence packet.

The existing checked arithmetic is a useful prerequisite. Its native tests do
not yet exercise every available source or connect native processor failures to
the public runtime. Closing these specific gaps is the next bounded development
step before a new measurement qualification reader and fresh warm experiment.

## Findings that selected the work

| Finding at the audited parent | Consequence | Required development |
|---|---|---|
| Directed native transport seeds 19 of 33 available selectors | Nine I/D-cache selectors, four global-memory selectors and TCU local reads lack real backing-source boundary evidence | Exercise all 33 selectors and every contributing bank/buffer through the real DCR path |
| Native cache failure adds two standalone statistics structures | It proves the aggregate operator but not the actual cache/CSR ownership path | Overflow the real two-bank cache and two-buffer TCU sums |
| Public counter-fault tests substitute Processor and RAM | Their real runtime/CP checks cannot establish native model-to-public error propagation | Link an instrumented diagnostic backend around the actual Processor and RAM; preserve the production error boundary |
| Public warm snapshots accept a dynamically enabled subset | A successful subset does not establish the exact required 33/12 inventory | Require the complete available inventory and no queries for unavailable L2/L3 rows |
| Device release reports a reference release; CP shutdown may stop polling early | Successful release is not proof of final destruction or prior quiescence | Observe ownership, completed work, pending balance and actual destruction separately |
| The checked-runner build validator hashes original object paths | Calling it during offline replay would consult the replay host | Separate pure retained-record parsing from live execution identity checks |

The all-33 inventory has **40 backing components** in the exact topology:
six D-cache values each sum two banks, and TCU local-memory reads sum two
private buffers. Other selected values each have one source. Seeding a returned
aggregate copy would not test these components. Ordinary WGMMA-disabled
execution leaving TCU values at zero does not establish transport correctness.

The selected diagnostic design uses typed test-only accessors compiled from
unchanged production implementation bodies. An initial access-control compiler
option was rejected after a compile probe showed that it invalidated the
simulator's protected-lifecycle-hook detection. The replacement uses C++17
explicit-instantiation accessors with normal compiler access checking. Production
class definitions, target objects, flags, public ABI, counter semantics and
generated configuration remain unchanged. The
[v2 contract](../designs/simx_counter_diagnostics_v2.md) defines the evidence boundary.

## Terminal lifetime argument

For nonnegative monotone components, a successful checked aggregate at a
terminal observation bounds every earlier aggregate by that final value.
This requires proof that all components started at zero, their updates and
permitted resets preserve the invariant, and no later operation can update
them. Sampled monotonicity, small observed values and timeouts do not supply
those premises.

The exact single-owner, VM-disabled, direct-RAM CP route already provides a
promising ordering: completed operations release and join their queues; owner
cleanup releases buffers, kernel and module; the observer then queries counters
before the final Device release. The audit requires explicit native observations
at these boundaries instead of treating release success as a drain certificate.
Concurrent submitters, external retained Devices, VM and CP-on-LLC remain outside
this argument.

The pinned Ramulator source audit at
`e62c84a6f0e06566ba6e182d308434b4532068a5` resolves a specific finalization
uncertainty. The selected GEM5/HBM2/GenericDRAM finalizers traverse components and
emit or calculate statistics; they do not tick or deliver request callbacks.
The AI-GPU adapter independently confines GPU callback delivery to its
`tick()`/`drain()` path, which its destructor does not call. This is a source
proof of that boundary, not evidence of a native run or complete lifetime
qualification. The actual loaded dependency and executed route must still be
bound to the native packet.

## Baseline and resource observations

At the audited parent, governance preflight and project metadata validation
passed. The 64 focused checked-counter host methods passed in 57.771 seconds.
Those tests include controlled model substitutions and do not establish new
native processor execution. The source was clean when this baseline began.

The checkout had approximately 1 GiB free disk, below the unchanged 15 GiB native
reserve. Native validation therefore belongs in the existing bounded hosted
workflow. Keep two build jobs, one simulation worker, the memory/log/time limits
and failure retention. Do not lower a reserve or substitute mocked process
results for the native run.

The GitHub audit found no open pull requests. The preceding native diagnostic
and focused runtime workflows were successful at `9fd7eac20`; broader CI and
the latest documentation-checkpoint workflows included queued jobs. Those
historical observations are separate from validation of this continuation.

## Acceptance limits and remaining sequence

This work advances diagnostics. It does not accept P06-A02/A03 or make the
historical warm v1 path usable. Keep `qualified=false`, `ready_for_warm=false`
and `warm_execution=false` in diagnostic results and retained-data replay.

After independently reviewing the complete native packet and lifetime source
argument, bind a separately versioned qualification reader to the actual
seed-free measurement binaries. Only that route may precede the unchanged fresh
24-process, 792-launch, 25,344-word warm attempt. Preserve original failures,
the cold baseline, all statistical predicates, the vendor P01-A03 blocker,
the separate P05 acceptance obligations and the inherited tensor area finding.
