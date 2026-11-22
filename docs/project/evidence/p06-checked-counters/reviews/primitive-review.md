# Independent primitive and storage review

**Historical candidate only:** the initial fatal-abort design reviewed here was
subsequently rejected by the independent completion-alignment review after
upstream completion changes were integrated. The replacement requires fresh
review; these original hashes and findings are retained without relabeling.

Reviewer: `/root/w02_a06_primitive_review`, who authored none of the reviewed code.
Baseline: `42809ff0c1b81384d7c9b079e4ef786be8407600`.
Scope: the checked accumulator and current selected-counter storage/aggregation
integration. This is source review, not native execution or phase acceptance.

## Result

No F1–F3 findings in this scope. Checks precede arithmetic mutation; negative
operands fail before conversion; self-addition reads the delta before mutation.
Deleted binary addition/subtraction covers the currently used operand types.
Selected accumulation paths use increments, bounded Boolean/lane/warp deltas
or checked counter aggregation. No already-wrapped right-hand-side expression
was found in the selected paths.

The review includes cache sums, the CSR coalescer temporary, tensor-buffer
backing counts and total, memory crossbar collisions and pending-read accounting.
The response decrement catches underflow. Reset still clears transient pending
reads while cumulative statistics retain their existing lifecycle. Ordinary
builds retain exactly the uint64_t alias; no scheduling or numerical timing
change was found. Process abort prevents an ignored future exception from
turning invalid arithmetic into apparent success.

## Obligations retained

This type is not a universal no-wrap type system: explicit casts, assignments
and unconverted backing fields require source review. Cache-internal bank
collisions and operand-stall accumulation outside the selected warm inventory
are not qualified here. Uniform guarded compilation, native transport, runtime
snapshot coherence and complete warm execution remain separate obligations.

Disposition: proceed to native build-route validation. The review does not
unblock historical warm-v1 or establish warm-v2 readiness. No test or native
build was run by this reviewer.

## Reviewed input bodies

| Path | SHA-256 |
|---|---|
| `sim/common/perf_counter.h` | `4baebbb566bbc628ecdd48ef5c6987b6c154fce68e202c14ba03e60d81386488` |
| `sim/simx/types.h` | `c09d02ca868b9b7fd28142c4c5aa922b9500975feddaf92695d220a5be6bd546` |
| `sim/simx/core.h` | `642af0adfae25333fc822289293a0d10273f58c8b1442a4acad63fad5a2f8609` |
| `sim/simx/processor_impl.h` | `f72e86ce9204a80a8246ab9c6ec1fab9bfccaf334a5ee487e4dc9dc01a7f921b` |
| `sim/simx/csr_unit.cpp` | `c35bd6a80120f76c9cf65076c736aaf577329285a74aac8c11c03f0ce829fc3d` |
| `sim/simx/mem/cache.h` | `839637e7738c774b02f1f556da86a4c716215696a70dd384d9e413ad6943653b` |
| `sim/simx/mem/local_mem.h` | `708446110e56f8cce88f50bcbca8fb8e1ff741a4019e16b4c9fda48d86f67635` |
| `sim/simx/mem/mem_coalescer.h` | `3368578b678a354eb5a876d1121351cd22987c729514fcfb7bfe4d86795961c7` |
| `sim/simx/mem/memory.h` | `8cdd7e1945842b3f58f64bcb3fad1fd3e61555cbc82d9063996e53453a71301a` |
| `sim/simx/tcu/tcu_unit.h` | `8546c4db53cc938c9a91ddcab002fa020195d39b93f9e35de3c21d9ecee28cb8` |
| `sim/simx/tcu/tcu_tbuf.cpp` | `eb20f6c16dd0915bebf39a0f85f7c11ee28a0ed681418385205b898f4b557463` |
