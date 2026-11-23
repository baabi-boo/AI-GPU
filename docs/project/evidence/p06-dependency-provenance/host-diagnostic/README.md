# Separate host dependency diagnostic

## Passed attempt 05 and independent original review

Fresh attempt `05` passed against published helpers
`19333193192ba5a2d3667c0111235ec9e21a5898`, tree
`baeeb7bc7078e9301c68e94b1207032329be343d`. The
[execution summary](execution-05-summary.json) records **413 passing actual
operations: 406 compiles, three archives, two indexes and two shared links**.
Its five outer commands and complete diagnostic graph validation passed.

The [independent review](review-05.json) passed in **12.306428 seconds** and
reconstructed all records from the original retained data. It checked 819 actual
children, 1,294 source files, the 97-row compilation database, 144 generated CMake
inputs, all archive/index and map joins, prerequisite chronology and 12 source
stability boundaries. All 3,682 retained files (135,214,393 bytes, excluding the
report) were rehashed before and after; report, preparation and driver bytes
remained unchanged. The original report SHA-256 is
`3f961336605864771b803887c5c562d2bfdeccd8568168f53b473a69d2f2d47a`.
The [review report](../agents/w10_a03-attempt05.md) states the exact scope.

The actual 18,084,083-byte Ramulator map selects 25 yaml-cpp members and zero
spdlog members, while loading both exact archives once. The extension's
614,675-byte map consumes the actual Ramulator product. No compiler-support
archive resolver command was needed. The repeated-header unit passed with raw
duplicate names preserved and its unique stable input inventory checked.

The [driver](driver-05.py) differs from the historical driver in exactly its
published revision and the two reviewed archive-selection requirements.
[Preparation](preparation-05.json), the [independent lineage check](review-05-driver-lineage.json)
and [launch](execution-05-launch.json) retain those identities and unchanged
resource bounds. The initial derived summary miscounted dependency children by
using an incorrect stage label; its [correction record](execution-05-summary-correction.json)
preserves both derived versions. The successful original report and all actual
records were never changed.

**This is a completed host dependency diagnostic, with independent original
consistency review.** Formal dependency preparation, cache restoration,
measurement staging, managed builds and native lifetime execution remain
unexecuted here. `fresh_dependency_build_passed` and
`dependency_source_to_loaded_binary_verified` remain false, native execution is
`not_run`, and all seven qualification/warm/acceptance claims remain false.

### Complete raw archive

The separately delivered `AI-GPU_P06_dependency_diagnostics_2026-11-23.zip`
retains the original evidence for attempts 03, 04 and 05, their exact drivers
and preparations, scoped review records, and an explicit post-failure addendum
for attempt 04's unretained map/generated CMake files. No failed original is
repaired. The [archive identity](archive-identity.json) records **61,112,122
bytes**, **8,804 members**, successful CRC verification and SHA-256
`13f6bfadaebaefa6f51767ab49c6be1e502e076b9911c33debc34c24e426a56c`.
The archive manifest inventories every other member; all copied source files
were rehashed after packaging. Treat retained code and binaries as inert data.
The complete generated payloads remain outside Git.

## Earlier failed attempts and reviewed corrections

Attempts `03` and `04` are finished failed originals. Attempt `04` used
published helper revision `146253db8407e21aaef70e05f3f0dd3c7f5f6d33` and its
exact [new driver](driver-04.py). It completed **405 compiles, three archives
and two archive indexes**. The first shared-link child exited zero and retained
its library payload, but its recorder then rejected the 18,084,083-byte linker
map under the 16 MiB JSON-receipt limit. No extension or native process ran.
The [execution summary](execution-04-summary.json) and
[independent partial-original review](../agents/w10_a03.md) preserve this failure
and the separate secondary final-stability error. Missing generated CMake and
compile-database evidence remain missing; this is not a complete graph pass.

The correction applies the existing 64 MiB artifact-file limit to map retention
and parsing; numeric limits and separate JSON/log bounds remain unchanged. The
[supplemental parse](execution-04-map-supplement.json) reads the unchanged map
with that correction. It does not repair the failed original, reconstruct its
missing post-link inputs, or establish complete map admission. A fresh execution
needs a new sealed attempt and an exact published helper revision.

Further inspection found a separate member-selection assumption before the
next build. The [pinned-source and actual-map review](../agents/w10_a05-spdlog-selection.md)
establishes that Ramulator's object targets use spdlog header definitions and
that the actual link selected 25 yaml-cpp members and no spdlog member. The
corrected Ramulator admission requires yaml-cpp member evidence and exact
unique `LOAD` rows for both archives. All seven spdlog compilations, its archive
and index, and its observed link-input bytes remain required; any selected
member still needs its admitted byte identity. The generic required-member and
guarded-model SoftFloat requirements retain their existing meaning.

The [generated CMake supplement](review-04-generated-supplement.json) checks
145 actual workspace-generated inputs without changing the failed original.
The original's missing generated-input fields remain missing. These supplements
guide the next reviewed attempt; they do not turn attempt `04` into a pass.

## Diagnostic boundary

This driver exercises the published dependency recipe functions and actual tool
recorder without requiring a RISC-V toolchain or claiming a restored cache. It
is an evidence-development diagnostic, not the formal dependency producer or a
replacement for the hosted native original. It never invokes `Builder`, stages
measurement inputs, builds managed models or runs a native lifetime process.

The [preparation record](preparation.json) identifies sealed attempt `03` before
execution. Its [actual execution summary](execution-summary.json) now records
**failed**: three selected compiler tools passed, then a fourth successful GCC
dependency prepass listed the same header twice and the recorder rejected the
valid repeated name before starting that unit's final compiler. All four raw
records, the original depfile and command log are retained. No archive, link,
managed build or native process ran. The [independent execution review](../agents/w09_a04.md)
identifies the exact frozen helper revision and first failure. A correction
collects repeated normalized input names once after checking the raw token bound;
its fresh execution requires a new sealed attempt and an exact reviewed revision.

The five pinned Git trees contain 1,294 files and
10,938,128 bytes; the source-derived plan selects 406 compilation units. Those
are input observations and a plan. They do not establish the separately
required 413 actual tool operations.

## Historical attempt 03 commands

Use a clean checkout of published helper revision
`5527cb062e10dfff3266022d138dd7cdf63f5e5c`, the five verified bare Git object
repositories named by the source lock, and explicit CMake 3.22.6. Preparation
requires a new owned workspace. It retains exact source/helper bytes, tools,
recorder configuration and the diagnostic driver's identity.

```bash
python3 -I -B docs/project/evidence/p06-dependency-provenance/host-diagnostic/driver.py prepare \
  --helpers /workspace/p06-foundation-governance \
  --workspace /workspace/p06-host-diagnostic-5527-03 \
  --repositories /workspace/p06-pinned-inputs \
  --cmake /workspace/p06-build-tools/cmake/data/bin/cmake
```

After the separate governance workload finished and resources were rechecked,
the single execution phase used:

```bash
python3 -I -B docs/project/evidence/p06-dependency-provenance/host-diagnostic/driver.py run \
  --helpers /workspace/p06-foundation-governance \
  --workspace /workspace/p06-host-diagnostic-5527-03
```

These commands document the original preparation and execution; attempt `03`
is finished and cannot be resumed. The driver rejects a changed prepared record, driver, helper or selected tool,
and rejects a second execution attempt. A retry requires another fresh
preparation and preserves the earlier original.

Independent review created preparation `03` after two diagnostic corrections:
the complete source/workspace linker-input population is checked, and failures
after the exclusive execution marker are retained before finalization. The
unexecuted `01` and `02` workspaces remain unchanged. The exact previous
[driver bytes](prior/driver-02.py) and [preparation summary](prior/preparation-02.json)
remain available; the prior driver is historical evidence, not the current
entry point.

The focused review controls execute the actual map parser and failed-intake
paths on separate synthetic fixtures, with no compiler or native process:

```bash
python3 -I -B docs/project/evidence/p06-dependency-provenance/host-diagnostic/review_controls.py \
  --helpers /workspace/p06-foundation-governance \
  --prepared /workspace/p06-host-diagnostic-5527-03/prepared.json
```

## Scope of a possible result

The unchanged recipe constructors select SoftFloat, Ramulator/yaml-cpp/spdlog,
and the extension. All phases use the existing process-group supervisor and
the unchanged two-job, 15 GiB disk, 4 GiB memory/RSS, 120-second configure,
1,800-second build and 16 MiB log bounds. Complete retained evidence is limited
to 1 GiB and each file to 64 MiB. No warning suppression is added.

After actual successful compilation, the driver calls the published inert
individual-record, complete compile-graph, generated-CMake and outer-command
validators. It also checks ordered archive members, creator/index bytes and
chronology, actual link inputs, compiler support archives and link maps. Source,
tool and helper stability are checked around each command. Partial logs and
records remain available after the first failure.

All map loads inside the full diagnostic workspace or helper checkout must be
exactly the selected direct inputs. Only compiler support archive paths already
verified by the compiler-resolution and archive checks are exempt from that
population comparison. System inputs outside those roots retain their stated
provenance limitations.

Even a successful `host_diagnostic_passed` result leaves
`fresh_dependency_build_passed=false`,
`dependency_source_to_loaded_binary_verified=false` and
`native_execution="not_run"`. Formal preparation, cache restoration and
measurement staging are explicitly false. All seven qualification, warm and
acceptance fields remain false. The four-process native original, loader joins,
separate behavioral controls and independent original review remain required.
