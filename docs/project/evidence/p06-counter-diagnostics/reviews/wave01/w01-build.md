# Wave 1 build and evidence audit

Source inspected: `7455e008c1e001d3329e74fd55ffcd942592ec5f`.
Assignment: audit all-33 backing-source diagnostic and native public-runtime build route. No production edits, commits, or native builds were performed.

## Conclusion

The proposed test-only wrapper translation units are workable without changing production APIs or class layouts. The diagnostic must own a separate object/link inventory. Its access exception must be narrow and verified from the actual compile commands; the existing compiler stamp remains the production flag baseline. Public runtime diagnostics need additional retained source, generated/copy identities, independent runtime compile/link validation, and symmetric workflow triggers.

## Existing enforcement worth retaining

- `ci/project/p06_checked_execute.py:79-96` captures a clean Git revision/tree, tracked model/common inputs, generated headers, copied Makefiles/fragments, and their hashes.
- `compile_flags` (`99-141`) strictly verifies checked mode, supported RV64 p02-tfr hardware flags, release options and ordered include paths.
- `validate_build` (`153-202`) accounts for fresh compilation and the sole link, rejects unrecognized object/source commands and changed flags, and binds every linked object to an observed compile plus identified dependency libraries.
- Execution (`298-311`, `332-411`) snapshots before each command, validates source/tool stability, performs fresh ordinary/checked builds, verifies complete JSON observations, and compares ordinary/checked boundary observations with only the checked-mode label removed.
- Finalization (`421-461`) rehashes generated files, stamps, executable, objects, source, tools/dependencies, retained bytes and logs. Errors remain failures. Preserve this behavior for every new binary.
- The workflow keeps read-only permissions, no persisted checkout credentials, cache restore only, complete failure artifacts, fixed pinned Python, two build jobs, one simulation worker, 4 GiB polled RSS, 15 GiB free-disk reserve, 16 MiB log cap, 1,800-second build and 180-second invocation limits, and a 90-minute job.

## Required implementation changes

### 1. Keep diagnostic access out of production

Use a diagnostic-specific object list in `sim/simx/checked_counters.mk`. Filter only the explicitly replaced production objects out of that list, then link wrapper objects located under a separate `obj/tests/...` path. Do not mutate the included Makefile's `OBJS`, `SRCS`, global `CXXFLAGS`, or production object paths. Otherwise a later ordinary library target could reuse seed-enabled objects.

A wrapper should include the unchanged production `.cpp` and append only typed backing-source access helpers. Compile only a frozen allowlist of those wrappers with exactly one additional `-fno-access-control`. This avoids preprocessor rewriting of access specifiers and preserves class definitions. The normal diagnostic harness should not receive that option unless its own explicit access needs require a separately reviewed entry.

The generated build already copies `*.mk` files (`configure:113-125`); no global configure change is needed for a fragment in an existing configured directory. Keep each wrapper's `.d` dependencies included so changing its included production source/header rebuilds that wrapper. A generated-tree `make -n`/dependency test should demonstrate that production `simx` and `libsimx.so` targets never select test wrappers or the access flag.

### 2. Extend compile validation with an exact source mapping

The current `validate_build` rejects the proposed wrappers in two legitimate ways: all TUs must exactly match the production stamp (`177-178`), and original `cache.cpp`/`tcu_tbuf.cpp` must occur as compiler inputs (`189-192`). Add a frozen wrapper-to-included-production map. For each mapped input:

1. Require that both wrapper and production body are tracked and retained.
2. Require its unique diagnostic object path and exactly the production flags plus one access option at the declared position.
3. Count the original implementation as covered by that wrapper only; reject compiling/linking the corresponding original object too.
4. Require the complete intended source inventory and exact link object multiset. Do not solve the mismatch by simply removing required-source checks or allowing `-fno-access-control` globally.
5. Retain the map and actual per-TU source/object records so reviewers can distinguish included production bodies from direct translation-unit inputs.

The existing cardinality floor of 40 objects is not an adequate replacement-map check. An exact required inventory is preferable for the frozen p02-tfr route. Existing negative tests for missing compile, duplicate link, unbound objects, flags and drift should remain and be extended for missing wrapper, wrong included source, duplicated original/wrapper, access-option leakage, duplicate access flags and stale wrapper objects.

### 3. Expand source binding for public-runtime execution

Current `source_snapshot` retains `sim`, `sw/common`, Ramulator extension and `CRITICAL`; it does not automatically retain the runtime sources needed by real public diagnostics. Add all actual consumed inputs, including:

- `sw/runtime/common` source/headers and `callbacks.inc`, `sw/runtime/stub/vortex.cpp`, `sw/runtime/simx/vortex.cpp`, installed runtime headers, and consumed kernel headers.
- Every new public test/adapter, diagnostic fragment and parser/helper.
- Any shared fixtures imported or textually included by the new test.

Add new helpers to `HELPERS`, so import-time-to-run helper stability remains enforced. Add diagnostic files to `CRITICAL`, so an untracked new file cannot silently enter a formal build. Merely using `git ls-files` on a directory does not catch a new required but untracked file.

For public shared libraries retain identities for the frontend runtime, native diagnostic backend, model library where separate, final harness, runtime/backend stamps, generated configuration and actual compiler/linker commands. Recheck the complete executed closure before/after each process, not only the harness executable. The model compiler stamp cannot validate runtime TUs with different include paths and flags; those need independently specified contracts.

### 4. Apply constructor interception at the correct link

If the native public diagnostic captures the real Processor using GNU linker `--wrap`, flags on only the final executable do not intercept references already linked inside a shared backend. Apply wrapping when linking the dedicated diagnostic `libvortex-simx.so`, or use explicitly reviewed static diagnostic linkage. Bind exact constructor/destructor symbols, wrapper sources and link flags, and assert interception was observed. Keep production backend rules unchanged.

Freeze the diagnostic process environment so `VORTEX_DRIVER=simx` and the intended library search directory select the identified diagnostic backend. Retain resolved identities; a reported filename alone does not prove which library executed. Diagnostic-specific `LD_LIBRARY_PATH` must not escape into measurement processes.

### 5. Expand symmetric CI triggers

Current `.github/workflows/p06-checked-counters.yml:16-19` (and its PR mirror) lists only `sw/runtime/common/perf.cpp` and `async_run.h`. That is insufficient once actual public runtime behavior is part of this workflow. Add the consumed runtime directory coverage and new test paths/fragments to both push and pull-request filters. Expand `test_p06_checked_ci.py:required_sources` accordingly; its existing dynamic source check currently covers only model/common inputs plus explicit critical files. Check Project Governance filters cover the new tooling and test files too.

Preserve the same trusted hosted runner/resource model and always-upload artifact behavior. More cells may require separate bounded invocations, but do not relax the fixed resource limits or accept an incomplete matrix.

## Observation schema and claim scope

The current runner is `simx-checked-counters-native-v1`, with a fixed 19-selector/760-half-read/2,749-check result and fourteen explicit omissions. A new all-33 contract should be explicitly versioned or otherwise unambiguously distinguishable; reject the old result as incomplete input to the new route. Retain original v1 artifacts without relabeling.

All 33 selectors with ten vectors and both half orders require 1,320 half reads. The final assertion count must be independently derived from the actual harness, including any new split-aggregate/reset/failure checks. Require exact selector order and identity, zero omissions and twelve unqueried unavailable rows. Reject duplicates, missing selectors and incorrect types.

Keep `qualified=false`, `ready_for_warm=false`, `warm_execution=false` and `full_warm_coverage=false` until their actual distinct obligations are met. Add a narrow field such as `all_available_transport_seeded=true` for the all-33 result. A complete seeded transport matrix is not a complete warm lifetime proof or statistical experiment. Ordinary/checked boundary equality establishes the tested transport observation parity, not whole-workload timing parity.

## Suggested bounded review gates

1. Generated-tree build-planning/dependency tests establish target separation and access-flag isolation.
2. Host parser tests reject substituted, incomplete and stale compile/source/binary evidence.
3. Fresh hosted ordinary/checked all-33 native runs pass, with raw source/build identities retained.
4. Native public success and typed asynchronous/synchronous failure cells pass, demonstrating actual native backend capture, sticky failure, output preservation, cleanup and fresh-context reuse only after disposal.
5. Independent artifact review checks actual original logs, compiled sources, wrapper substitutions and binaries. Warm readiness remains separately gated.
