# P06 dependency provenance: next bounded handoff

## Current result and next action

**Build the selected SimX dependencies from immutable source inputs, then bind
their actual compilation, archive/link steps and produced bytes to the libraries
linked and loaded by the managed lifetime processes.** This is the next bounded
P06-T01 task. It needs a separately versioned receipt and independent review;
this document plans that work and does not implement or qualify it.

The preceding observation increment is implemented at
`b4127b19a004b5aebb8d52eab9ceda0da3ff4561`, tree
`bd37fb53ab1c34dfebc2ac8805abff5877735fc4`.
[Run 45130300651, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45130300651)
executed the unchanged FP16/BF16 × allocation-policy matrix: **four processes,
132 launches and 4,224 exact FP32 result words, with zero mismatches**. The
[aggregate original review](evidence/p06-native-lifetime/reviews/w08_a01.md)
reconciles every process, 1,188 DCR reads and 2,680 recorded zero-pending
observations, including the terminal state and actual destructor entry.

The [separate accessor probe](evidence/p06-native-lifetime/reviews/w07_a05.md)
uses the selected FP16 model. Its gp `7` and `-1` contexts each observed 23
positive pending samples, maximum balance 1 and final balance 0. The compiled
always-zero control exited 1 for the exact missing-observation assertion.
Those probe operations are outside the four-process matrix and its 132 launches.

Start from the [native lifetime packet](evidence/p06-native-lifetime/README.md),
[implemented witness contract](../designs/managed_counter_lifetime_v1.md),
[build/product original review](evidence/p06-native-lifetime/reviews/w07_a06.md)
and [dependency audit](evidence/p06-native-lifetime/reviews/w05_a03.md).
The [previous managed-preflight handoff](p06-managed-preflight-handoff.md)
preserves the original planning context. Native execution, inert original review
and full governance have separate scopes; use the packet's named governance
receipt for a completed full-suite outcome. This handoff supplies no new
governance execution or acceptance result.

## The remaining provenance edge

The current producer freezes dependency product hashes, builds fresh guarded
models, records compiler and linker commands, and observes exact loaded-library
paths. Its original report explicitly leaves
`dependency_compilation_provenance_verified=false`: those observations do not
establish which dependency source, headers, tools and options produced the three
reused inputs. The [current dependency inventory](../../ci/project/p02_matrix.py)
and [preparation route](../../ci/project/p04_ci_prepare.py) define that boundary.

The next receipt must connect each selected immutable input to successful
observed build execution, each output to the command that produced it, the
actual static-link inputs to the resulting model, and the resulting dynamic
products to the native loader observations. A compile database describes planned
commands; cached bytes and favorable numerical output do not establish this
complete chain.

### Reuse the existing application validator

The trusted
[`validate_application_build()` reader](../../ci/project/p06_managed_preflight_application_build.py)
already checks the complete **30-command application graph**, including the
exact **14-source runtime-stub compile/link command**. Both format builds in the
native original passed that inert validator in the
[independent build review](evidence/p06-native-lifetime/reviews/w07_a06.md).
The present live producer's
[`validate_host_build()`](../../ci/project/p06_managed_preflight_execute.py)
checks and binds the final host invocation; it does not yet invoke and bind the
full application graph.

Integrate the existing full-graph validator into the new live admission route.
Import it and its local helpers before the trusted-helper/source freeze, supply
the live validated source, compiler records and tool identities, and bind its
complete result into the new build and process identities. Keep its exact recipe
grammar and prerequisite ordering. Any changed recipe needs an explicit reviewed
grammar update. This closes a live admission join without inventing a second
stub validator or changing the interpretation of the existing originals.

## Selected source and product graph

The following identities are the superproject gitlinks at the completed
observation checkpoint. Recheck them when selecting the next execution source.
The [dependency audit](evidence/p06-native-lifetime/reviews/w05_a03.md) links the
upstream build definitions it inspected at these revisions.

| Selected product | Required source and relationship |
| --- | --- |
| `third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a` | Berkeley SoftFloat gitlink `b51ef8f3201669b2288104c28546fc72532a1ea4`; RISC-V specialization and exact selected objects; statically consumed by `libsimx.so` |
| `third_party/ramulator/libramulator.so` | Ramulator2 gitlink `e62c84a6f0e06566ba6e182d308434b4532068a5`; complete selected library source graph and its compiled static inputs |
| `third_party/ramulator_ext/libramulator-vortex.so` | Superproject [extension recipe](../../third_party/Makefile), Ramulator's committed `src/dram/impl/GDDR6.cpp`, included headers and `gddr6.o`; linked against the freshly built Ramulator product |

Ramulator's pinned build definition selects yaml-cpp `yaml-cpp-0.7.0`, spdlog
`v1.11.0` and argparse `v2.9` by tag. **Resolve and review immutable commit/tree
identities for the next source lock before execution.** Those declared tags do
not authenticate the source used by a historical cache. The selected default
Ramulator library incorporates yaml-cpp and spdlog, including bundled fmt;
argparse is a header-only input for the separate executable, although the parent
configure step fetches/configures it. Record that distinction in the selected
build graph.

Build the Ramulator library target and the existing extension. The complete
library includes registered implementations beyond the selected HBM2 workload,
and the model explicitly retains the GDDR6 extension at link time. Include that
source graph. The broad `third_party all` target also selects unrelated products;
use dedicated targets for this three-product dependency task.

## Implementation sequence

### 1. Freeze the receipt, inputs and execution contract

Define a distinct versioned dependency receipt and caller-pinned expectations
before evaluating a new original. Specify exact schemas, source inventories,
tools, allowed command grammar, configuration, archive membership, installation
paths, payload limits, failure outcomes and source/product joins. Preserve the
existing preflight and lifetime formats and their historical results.

Complete source acquisition and immutable transitive resolution before freezing
the selected trees. Inventory build scripts and included inputs, including
ignored files that participate in compilation. Require a fresh source/build
workspace without old objects, archives, libraries, CMake cache or compiler cache.
After the freeze, unexpected fetches, updates or input changes fail the attempt.

### 2. Build and retain SoftFloat's exact archive

Preserve the selected RISC-V specialization, `SOFTFLOAT_FAST_INT64`, PIC,
round-odd, inline level 5, both fast-division options and
`THREAD_LOCAL=_Thread_local`, as established by the reviewed source and
[superproject recipe](../../third_party/Makefile). The upstream recipe hardcodes
`gcc` and `ar`; a `CC=` assignment alone does not select a different compiler.
Use a reviewed recipe override or controlled PATH with verified actual tool
identities, and retain that tool/command connection.

Record every required source-to-object invocation, successful result, included
input set and output hash. Retain exact archive member names, order and bytes;
reject thin archives, duplicate members, unlisted objects and stale inputs.
Bind the actual archive consumed by each model link and the members it selects.

### 3. Build Ramulator and its compiled transitive inputs

Use fresh owned source copies and separate binary directories. Explicitly select
Release, PIC, C++20, yaml-cpp/spdlog static/shared settings, bundled or external
fmt, optional tools/tests/examples and the immutable fetched-source locations.
These choices are part of the reviewed contract, not defaults inferred from a
target name.

Retain CMake configuration and generated build inputs, the compile database,
actual verbose execution receipts, dependency/header closure, object/archive
bytes, and final link evidence. Reconcile intended commands with successful
observed commands and the outputs they actually produced. Build the selected
dependency products once, then use those exact bytes for both format models.

### 4. Build the Vortex Ramulator extension

Preserve the reviewed C++20, `-O3 -DNDEBUG -fPIC` recipe and exact Ramulator,
spdlog and yaml-cpp include roots. Bind `GDDR6.cpp`, its included headers,
`gddr6.o`, the actual link command and the just-built Ramulator library to the
extension output. Add a reviewed dependency-file or equivalent included-input
receipt; the present extension recipe alone does not supply that closure.

### 5. Stage verified inputs and freeze the managed build

Install only byte-verified products and required headers at the canonical model
input paths in an owned fresh measurement checkout. Account explicitly for
upstream conventions: Ramulator writes its shared library into its source
directory, and SoftFloat uses a local `platform.h`. Keep those writes inside the
owned dependency copies and bind their source origins. A future dependency-root
option would require a reviewed path/link contract change.

Freeze the staged inputs before configuring the managed models. Preserve fresh
FP16/BF16 build directories, generated-header reproduction, checked 64-bit
counters, the exact runtime/model/kernel/host compiler roles and the existing
43-unit model/backend admission. Join the new dependency receipt digest to
each format's build binding and every process binding. Retain object bytes
where the new receipt requires independent object-level reconstruction; the
current original records all 43 object identities but does not retain their
individual payloads.

### 6. Admit the complete application graph and actual links

Reuse the existing 30-command application validator as described above, including
kernel-library compilation/archive/conversion stages and the 14-source stub.
Preserve its source and transitive helpers in the execution packet before any
command relies on it. Bind both the complete application result and the existing
exact final host-command result to the new build identity.

Retain link-map or linker-trace evidence sufficient to identify the SoftFloat
archive members consumed by the model and the yaml-cpp/spdlog objects consumed
by Ramulator. A nearby archive hash alone does not identify what a linker used.
Join the model, backend, stub, application and kernel products to their actual
commands and final bytes. Keep the original path, duplicate and substitution
checks for the five selected loaded libraries.

### 7. Execute the unchanged bounded native population

Run the same FP16/BF16 × `per_operation`/`reusable_single_tile` population through
the new selected provenance route. Preserve all 33 launches per process,
numerical checks, complete lifetime sidecars, actual destruction observations
and failure retention. Keep the accessor probe and its always-zero control
separate from the four managed processes and their 132-launch count.

Require exact source/tool/input/product stability at the specified boundaries.
Preserve the first real failure when later stability or cleanup checks also
fail. A new process, retry, favorable prefix or omitted variant cannot repair
an incomplete original. Attribute any changed numerical or counter behavior
to the newly selected source/build inputs without altering goldens or thresholds.

### 8. Retain and independently review the complete original

Retain original job identity, raw logs, source/build inputs, products, receipts,
bindings and failure evidence. The reusable reader must consume caller-pinned
expectations, validate bounded exact schemas and inventories, and keep all
retained paths, commands, source files and binaries inert. Its result establishes
consistency of a named original; actual execution is supplied by that original's
identified hosted run. Independent review must reconcile both layers.

## Controls that demonstrate the new provenance edge

| Control | Required behavior |
| --- | --- |
| Favorable cached library with no fresh build receipts | Reject missing source-to-build evidence even when the numerical smoke passes |
| Changed top-level or fetched source under the same cache name | Reject source/lock mismatch before admission |
| Populated CMake cache, old object, unexpected fetch or input mutation after freeze | Fail the freshness or stability premise with the original reason retained |
| Wrong specialization, TLS/options, external fmt selection, compiler, archiver or linker | Reject the exact configuration/tool mismatch |
| Missing, duplicate, reordered or fabricated command record | Reject inventory/order or command-to-product inconsistency; an echo log cannot supply execution evidence |
| Substituted archive member, old static input or changed library between build, link and launch | Reject the broken object/archive/link/product join |
| Alternate library selected by the actual loader | Reject the path/product mismatch despite a favorable result |
| Diagnostic mutation or reduced counter limit in the managed build | Preserve the existing production-build rejection; fault controls remain separate |
| Earlier native/build failure followed by successful cleanup or another process | Preserve the failed attempt and prohibit successful admission |

Include an end-to-end control using a freshly built, known different dependency
product whose numerical smoke still succeeds. The provenance checker must reject
its source/recipe/product mismatch for the expected reason. This distinguishes
provenance sensitivity from numerical correctness without mutating the admitted
measurement build.

## Resource and completion boundary

Keep the existing **two build jobs, one simulation worker, 15 GiB disk reserve,
4 GiB minimum available memory, 4 GiB RSS limit, 120-second configure limit,
1,800-second build limit, 180-second native-process limit, 16 MiB command-log
bound and 90-minute hosted-job ceiling**. The
[existing dependency recipe](../../third_party/Makefile) contains an explicit
nested `make -j4`; outer `MAKEFLAGS=-j2` does not cap it. The new dedicated route
must enforce two jobs inside every nested build. Use the existing bounded
process-group supervision and preserve its polling/containment limitations.
If the reviewed fresh-build or retention design cannot fit the fixed budget,
record that resource block and review a bounded alternative before execution.
Use the identified pinned prebuilt toolchain; rebuilding the compiler is outside
this selected dependency task.

The task is complete only when a separately versioned dependency receipt passes
all required source, build, archive/link, product and loader joins, meaningful
negative controls, a fresh complete native original and independent review.
Report exactly that bounded provenance result. Do not rewrite old false fields
or silently upgrade an old reader's acceptance meaning.

The broader qualification boundary stays explicit. The existing reports and
contracts retain these three obligations in order:

1. `all_40_component_lifetime_and_pending_balance`
2. `dependency_source_to_loaded_binary_provenance`
3. `independent_complete_counter_qualification`

The existing seven fields remain false: `qualified`, `ready_for_warm`,
`warm_execution`, `full_warm_coverage`, `acceptance_claimed`, `phase_acceptance`
and `performance_acceptance`. A new narrowly scoped provenance outcome requires
its own reviewed meaning; it does not remove the full 40-component lifetime
argument or independent complete qualification. The
[component source map](evidence/p06-native-lifetime/reviews/w05_a01.md) and
[terminal ownership trace](evidence/p06-native-lifetime/reviews/w05_a02.md)
remain supporting premises with their stated limits.

P06 and P06-T01 remain `in_progress`; P06-A02/A03 remain open under the
[canonical roadmap](roadmap.json) and [acceptance policy](acceptance.md).
Preserve the warm gate, historical failed originals, the RV64 area finding,
P01-A03 vendor `hw_emu` blocker and the scopes of earlier acceptances. Neither
this plan nor a future dependency receipt establishes an absolute no-wrap bound,
a complete trusted toolchain/system-input closure, warm speedup, native RTL,
physical FPGA or silicon performance.
