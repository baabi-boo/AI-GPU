# Root audit and development decision

## Verified starting state

- Connected GitHub `master`: `142b2d6aaea2fa4226118b857514113032d2e26c`.
- Recovered prior local handoff: `fed2f84f6704219ddfc70867aa39fe7fd61e3fc1`;
  378 documentation/evidence files, no production implementation changes.
- Published recovered tree unchanged as `4d8f5c00a995611fc85310bbda6122b62091ebd5`,
  tree `9bb5e21ffc98f239f276ec065d47877fe126037f`; branch API readback confirms both.
- Initial API observations show all eleven latest workflows at `142b2d6` succeeded.
  These API observations do not independently replay artifacts or waive an
  inherited gate that was outside a particular workflow's selected changes.
- Project metadata validation passes on the recovered tree. The original warm
  manifest digest and protected framework illustration digest are unchanged.
- P00/P02/P03/P04 complete; P01 blocked; P05/P06 in progress; P07-P11 not started.

## Concrete development findings

1. All-selector and scalar public-runtime diagnostics are implemented, but their
   binaries contain seeded/private-access diagnostic objects. They cannot serve
   as seed-free managed measurement binaries.
2. The historical warm compiler and replay contracts reject checked-counter
   flags and require the complete old 24-process record. Relaxing those old
   contracts would erase their declared evidence scope.
3. The managed caller already executes the exact 33-operation numerical and
   ownership sequence; its retained-data validator checks the full 45-row
   inventory. Missing evidence includes actual raw half-read coherence,
   enabled-CP terminal retirement, runtime ownership and Processor destruction.
4. Existing preparation hashes cached dependencies, but does not establish their
   source-to-compiled-to-loaded provenance. Public getters also do not expose
   pending balance or all 40 backing components. These remain explicit limits.
5. Existing warm environment helpers tie THREADS to build jobs. The new route
   must independently keep one simulator worker while permitting two compilers.
6. Local disk reserve is insufficient for native execution. A separate checkout
   in available temporary storage preserves other work; native builds run in a
   dedicated hosted workflow with unchanged resource limits.

## Selected bounded step

Implement a separately versioned seed-free managed counter preflight using the
production simulator, original warm main/observer/kernel, read-only wrappers,
strict original compiler/linker and loader validation, a four-process producer,
pure record/replay validation, rejection tests and a dedicated hosted workflow.
Collect actual binary payloads as well as hashes. Preserve historical warm-v1,
numeric fixtures, poison, statistical predicates and all golden data.

The completion target is four actual processes, 132 native launches, 4,224 exact
FP32 output words, 16 snapshots, 528 available queries and 1,056 half replies.
It is a managed execution/observation prerequisite. Full qualification, warm
readiness, performance acceptance and phase acceptance remain false while the
remaining dependency and whole-lifetime obligations are open. Do not analyze
the preflight's timing values as a new optimization result.

Ten logical waves each contain six actual distinct assignments. Reports and
tool-returned completion messages, not requested counts, establish completion.
Implementation, integration, independent enforcement review, real native
execution, failure disposition and final publication must all be retained.
