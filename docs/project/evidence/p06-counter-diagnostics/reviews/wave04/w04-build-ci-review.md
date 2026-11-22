# Independent public diagnostic build and CI review

## Scope and verdict

Reviewed the complete new `tests/unittest/checked_counters/public.mk` and every pending hunk in `.github/workflows/p06-checked-counters.yml` and `ci/project/test_p06_checked_ci.py`, against the production Makefiles, dispatcher loading path, configured build behavior and repository rules. The repository HEAD at review is `407ab9fea5e4f793a2a5088f566a87f3e631aa84`; these three reviewed files are the pending continuation, identified by hashes below.

**No F1, F2 or F3 findings.** Treat the combined change as **R3** because it expands what the diagnostic workflow enforces. This is an independent review; I did not author or edit any repository file. **Verdict: land from this static build/CI scope.** Actual native public model/runtime linking and execution remain unobserved and must not be reported as passing on the strength of this review.

The ordinary production model, runtime, installed API, configuration generator, toolchain pins, golden data and warm acceptance gates are unchanged by this scope. The dedicated diagnostic target does not claim a timing/model change or RTL parity.

## Exact reviewed identities

| Path | SHA-256 |
|---|---|
| `tests/unittest/checked_counters/public.mk` | `ce65fef47f9c977ef5cb7f40f2e6ece0c4975f1999c607f63d6f0fc72ce3882a` |
| `.github/workflows/p06-checked-counters.yml` | `3d96c976076c91dfda3cb0262506d48be6501ecd187eae1f217d42234a4de8f0` |
| `ci/project/test_p06_checked_ci.py` | `18dcf86b5177cb344e7ae56eaeb1b2c4c71a0b6510cb5d8fcc667ea4538dfb55` |

All three identities were unchanged at the end of the independent probe and again immediately before writing this report.

## Build findings

The dedicated fragment is located under tests and is invoked explicitly from the freshly configured SimX build directory. `configure` copies the fragment byte-for-byte. Its default is the diagnostic target, while ordinary production targets and their original object inventory remain intact.

The first checked boundary build contains exactly 45 compile records and one link. The public model library uses the exact 44-object subset, excluding the boundary main. It excludes the four replaced original implementations and does not contain the hooks. A fresh public build contains 63 compiles and four links; a Make dry run that explicitly marks the 44 preexisting model prerequisites as already built contains exactly 19 new compiles and four links. These are source/object/role inventories: runtime and backend legitimately compile `utils.cpp` separately.

The runtime contains its 14 unchanged production sources. The backend contains its three unchanged production sources and the single hooks object. All five verified GNU `--wrap` arguments occur only on the backend DSO link, where its Processor references are unresolved. The hooks use the same compiler flags as the actual model Core object. Runtime and backend flags independently match their respective production Make rules after canonicalizing equivalent include paths and removing only dependency-file side-effect options for comparison.

The executable, runtime and backend use sibling `$ORIGIN` search paths. The backend's distinct `libchecked-simx.so` dependency is linked from the same isolated directory. The existing runtime dispatcher requests `libvortex-simx.so`; the diagnostic executable already links that same sibling library. The public runner's separately reviewed environment must preserve the declared no-preload/no-library-path boundary. No actual dynamic-loader observation is claimed here.

All new object rules depend on both the configured and source diagnostic makefiles. Runtime/backend/main object rules explicitly depend on the generated configuration/type headers, and compiler-generated `.d` files are included. An independent actual `g++ -MM` preprocessing probe on the public main resolved its public hooks, runtime internal header, frozen counter inventory and generated `VX_types.h`. The backend recipe selects its unique `.cpp` prerequisite explicitly, avoiding the stamp-first prerequisite-order bug documented in the author's retained failed probe. Ordinary requests lacking the checked guard are rejected at Make parse time.

## Workflow findings

Push and pull-request path filters remain symmetric. The broader runtime, kernel-header and frozen-counter-header patterns preserve existing coverage and add all newly relevant sources. The public diagnostic executes after the ordinary/checked producer, with the exact checkout SHA, separate fresh work/output paths, no scope or resource override, and shell `pipefail` retaining both streams.

The workflow retains hosted Ubuntu, read-only contents permission, checkout credentials disabled, recursive pinned submodules, CPython 3.12.14 with identity verification, restore-only toolchain/dependency caches, and preparation provenance checks. It introduces no secrets, self-hosted runner, fork privilege, cache write, failure suppression or conditional test skip. The 90-minute job bound, 15 GiB reserve, 4 GiB memory/RSS controls, two build jobs and one simulation worker remain intact. The artifact upload still runs with `always()` and includes the entire evidence directory, including both producers' outputs and logs. A first-producer failure can prevent the second from starting, but remains a failed workflow with retained earlier evidence; absence of a public result is not a public pass.

## Verification actually run

1. `python3 -m unittest discover -s ci/project -p 'test_p06_checked_ci.py' -v`: **15 passed in 0.067 seconds**. These include actual shell pipeline failure/stream retention for the new public producer, resource rejection, interpreter identity, trigger coverage, ordering and upload behavior. They are host tests, not native execution.
2. Independent fresh out-of-tree RV64 `p02-tfr` configure and Make dry-run probe: **passed** the exact 45/44/19 inventories, four links, 14 runtime/four backend objects, backend-only five wraps, normal flag comparisons, sibling rpaths, source/configured Make dependencies and no-guard rejection.
3. Actual public-main dependency preprocessing with the emitted runtime compiler flags: **passed**. No object or executable was produced.
4. Whitespace checks for all three reviewed files: **passed**. The new-file `git diff --no-index --check` exits 1 because the file differs from `/dev/null`, with no whitespace findings.

Receipts outside the repository:

- `w04-build-ci-tests.log`
- `w04-build-ci-probe.log`
- `w04-build-ci-probe.json`

The prior-object dry run uses GNU Make's explicit old-prerequisite option. It is not evidence that those objects were compiled. No placeholder binary, native model build/link/run, kernel execution, warm experiment or acceptance was produced. I did not run `checkout`, `reset`, `stash`, `clean`, commit or push. The final committed-range classification using the base policy remains the publisher's release check; this pending content was manually treated as R3.

## Remaining boundaries

The actual public harness, hook behavior, pure/live build validator, raw-result validator and orchestration runner have separate reviewers. This review does not approve their behavior by implication. Hosted execution must establish the native link/runtime behavior, and packet source/binary/dependency identities must be checked before any stronger evidence claim. All diagnostic qualification/readiness flags remain false.
