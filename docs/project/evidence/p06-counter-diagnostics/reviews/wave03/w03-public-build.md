# Wave 3 public diagnostic build

Implemented only `tests/unittest/checked_counters/public.mk`.
Final SHA-256: `ce65fef47f9c977ef5cb7f40f2e6ece0c4975f1999c607f63d6f0fc72ce3882a`.

## Build contract

Invoke from the freshly configured checked build's `sim/simx` directory:

```sh
make -f ../../tests/unittest/checked_counters/public.mk PERF=1 PROFILE=p02-tfr CONFIGS=-DSIMX_CHECKED_COUNTERS=1 checked-public
```

The fragment includes the configured `checked_counters.mk` and does not edit any production makefile, source, object list or flags. It rejects non-RV64, wrong profile, PERF other than 1, absent/repeated checked-counter guard, DEBUG, SST and GEM5. All outputs are confined to `sim/simx/checked-public/`, except the hooks object beside the pre-existing diagnostic access objects. `configure` copies the fragment byte-for-byte.

Outputs are `libchecked-simx.so`, `libvortex-simx.so`, `libvortex.so`, and `checked_public_test`. The model library links the exact 44 checked model/access objects without either main or hooks. The hooks object uses unchanged model CXXFLAGS and joins the three real backend objects at the backend DSO link. Exactly five GNU --wrap arguments intercept the verified external Processor constructor, destructor, run_checked, dcr_read and dcr_write symbols there. Common runtime/stub contributes 14 separately compiled real objects; the executable contributes one main object and directly links both runtime and backend. Every runtime-loaded artifact has a sibling $ORIGIN rpath. The executable also has a link-time rpath-link for that same directory. VORTEX_DRIVER=simx selects the intended existing runtime route; no LD_LIBRARY_PATH is needed by this arrangement.

Per-kind stamps are `sim/simx/simx_config.stamp` (model and hooks) and `sim/simx/checked-public/{runtime_config.stamp,backend_config.stamp,main_config.stamp}`. Runtime and backend flags match the existing production rules after canonicalizing the original backend relative include path; per-object dependency flags were added so generated/source/header edits invalidate the right objects. The app uses the same runtime flag vector. All new objects and links depend on both configured and source public.mk; generated headers and compiler .d files cover input dependencies. Ordinary production targets remain unchanged.

## Bounded validation actually run

A new temporary RV64 p02-tfr build was configured; no real simulator objects were created or linked.

- Fresh public Make dry-run: 63 compile records, four link records, correct source-to-object mappings.
- Model shared-library link: exactly 44 distinct checked model/access objects; four replaced production objects, old test main and hooks absent.
- Hooks: identical compiler flags to the actual Core compile record, excluding target-dependent dependency paths.
- Runtime/backend flag vectors: exact equality to their existing production Make rules after canonicalizing include paths and removing only dependency-file side effects.
- First-stage checked_counters_test Make dry-run: 45 compiles and one link.
- Second-stage public Make dry-run: 19 compiles and four links when GNU Make `-o <object>` marks the 44 prerequisite objects as already built. This is explicitly a dry-run reuse simulation; it creates no placeholder objects and is not native evidence.
- Five --wrap entries appear only at the backend DSO link. Runtime link has 14 objects; backend link has its three actual objects plus hooks.
- Actual syntax checks passed for unchanged backend vortex.cpp, backend utils.cpp, backend cmd_processor.cpp, common-runtime utils.cpp and stub vortex.cpp using their exact emitted flags with only dependency side-effect options removed.
- An ordinary/no-guard request is rejected at Make parse time.
- `git diff --no-index --check /dev/null tests/unittest/checked_counters/public.mk` emitted no whitespace findings (exit 1 denotes the new-file difference).
- Final public_main.cpp passed a separate syntax check under its exact emitted main flags in another fresh configured tree; receipt `w03-public-main-build-syntax.log`.

The first dry-run caught a Make prerequisite-order issue: the combined backend rule initially selected its stamp with `$<`. It now selects its unique `.cpp` prerequisite explicitly. The failed probe remains before the final passing probe in the validation log.

Retained scratch evidence: `w03-public-build-check.py`, `w03-public-build-validation.log`, `w03-public-build-compiler-records.log`, `w03-public-first-build-dry-run.log`, `w03-public-second-build-dry-run.log`, the three `w03-public-*_config.stamp` files and `w03-public-build-results.json`.

## Not run

No native model/backend/runtime link, public executable run, kernel execution, warm qualification or acceptance occurred in this agent's work. Available disk was approximately 1.5 GiB, below the unchanged 15 GiB native reserve. The runner must validate actual compiler/link records, all 44 reused object identities, both stages' stamps, linked symbol bindings and before/after artifacts in the hosted build. No commit or push was performed.
