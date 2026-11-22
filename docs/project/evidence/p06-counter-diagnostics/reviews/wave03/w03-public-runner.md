# Public diagnostic execution runner handoff

Owned files only: `ci/project/p06_counter_public_execute.py` and `ci/project/test_p06_counter_public_execute.py`.

Implemented a separate fresh-tree checked native runner. It builds and validates the45-TU existing boundary fixture, runs its all33 control, then links the public diagnostic using19 new TUs and the validated44 reused model objects. Five public modes are separate processes. The existing15GiB disk/4GiB RSS+available-memory reserves, two build jobs, one simulation worker, process/log/time limits and core-dump suppression remain mandatory. Pinned actual CPython3.12.14 must resolve to the same interpreter as PATH python3.

Source capture retains tracked ci/project, sim, sw/common, sw/include, entire sw/runtime, sw/kernel/include, diagnostic sources, frozen ai_bench_common headers and Ramulator adapter sources. Every non-test top-level ci/project Python helper is hashed at import to cover transitive trusted validators. No retained source code is executed. Source cleanliness, exact revision when supplied, tool/dependency equality, helper bytes and retained source bytes are checked.

Execution bindings include generated configuration/copied Makefiles, checked stamp, exact generated TCU bytes,45 model objects, control executable, header probe, three public stamps,19 new objects and four shared-library/executable artifacts. Every established group is rehashed before and after each command and once at completion. Validated object identities must match the binding capture. Source/tool/dependency checks accompany these. Public execution uses VORTEX_DRIVER=simx and sibling-library rpaths; inherited LD_LIBRARY_PATH/LD_PRELOAD/build flags are removed.

The report retains raw logs and process failures. A successful negative scenario must still have an actually started process, integer exit0, completed cleanup and no process failure reason; the separate public records validator must accept its actual observations. Any drift/failure blocks later scenarios and prevents both public-diagnostic success and all-selector summary success. Qualification, warm readiness/execution/coverage, phase acceptance and performance acceptance always remain false.

## Validation status

Both final files passed Python source compilation (syntax only). No orchestration test execution yet: the public-records module is still being authored by its owner. No fallback module was created and no imports were bypassed in production. The parent requested immediate handoff to free a review slot rather than wait idle. Once modules complete, run:

`python3 -m unittest discover -s ci/project -p 'test_p06_counter_public_execute.py' -v`

The11 test methods use explicit controlled host process/validator boundaries to isolate orchestration; they establish no native execution. They cover the full command/binding sequence, fixed budgets/environment, resource/source/helper/interpreter blockers, failed build/cleanup/exit identity, output rejection, nine input-binding drift classes, source/dependency/log/retained-copy drift, preserved preexisting output, overlapping paths, and empty/symlink artifacts. Strict compiler/JSON parser tests are owned by their separate authors.

Native build/link/execution is not run due the unchanged local disk reserve. No commits or pushes performed.

The agreed module interfaces and exact artifact/stamp paths are in `/workspace/scratch/98908dfa3444/w03-public-interfaces.md`.

## Final source identities

- `ci/project/p06_counter_public_execute.py`: SHA-256 `b1d879ff188482c951e962e58ae7610b2fc37d2a9e73a4a5b7c87c58116b8d1c`, 21507 bytes.
- `ci/project/test_p06_counter_public_execute.py`: SHA-256 `71cd970d283bbbbc69e7ea1ca5ae6fc2d308d01166482830e44bf9fa4131892c`, 18347 bytes.
