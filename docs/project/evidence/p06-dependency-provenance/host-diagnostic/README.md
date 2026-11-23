# Separate host dependency diagnostic

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
