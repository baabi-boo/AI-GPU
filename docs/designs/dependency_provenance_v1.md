# Fresh selected dependency provenance v1

## Scope

`p06-dependency-provenance-v1` identifies fresh builds of the three selected
SimX dependency products. `p06-managed-dependency-lifetime-v1` joins that receipt
to complete managed application admission and the unchanged lifetime witness.
The immutable input lock and resource bounds are defined in
[`p06_dependency_contract.py`](../../ci/project/p06_dependency_contract.py).
This contract does not change the interpretation of earlier preflight, lifetime,
replay or performance evidence.

The selected sources are Berkeley SoftFloat, Ramulator2, yaml-cpp, spdlog and
argparse at the five complete commit/tree identities in the lock. Argparse is
a configuration input for the selected parent project, with no compiled object
in the selected library target. The build contains 309 SoftFloat, 60 Ramulator,
29 yaml-cpp, seven spdlog and one extension translation units. Those counts must
be reconciled with the selected source/output graph, not merely printed by the
producer.

## Source and build boundary

Acquisition precedes the source freeze. Read fixed Git objects, reconstruct the
root tree and verify every materialized blob. Use fresh owned source copies and
separate CMake binary directories. Reject pre-existing objects, libraries,
archives, caches and unexpected source inputs. Explicit local FetchContent
selection and disconnected configuration prevent implicit population after
the freeze; they are not an operating-system network sandbox.

SoftFloat retains the RISC-V specialization, FAST_INT64, PIC, round-odd, inline
level 5, both fast-division options and thread-local storage. Ramulator uses the
selected Release/PIC/C++20 library target, static yaml-cpp and spdlog, bundled
fmt, and disabled optional transitive tools/tests/examples. The parent Ramulator
executable is configured but is outside the selected build target. The extension
keeps its committed GDDR6 implementation, C++20/O3/NDEBUG/PIC and reviewed include
roots. The pinned prebuilt RISC-V toolchain is an identified external input;
this route does not rebuild or qualify the compiler itself.

Record actual compiler/archiver/linker child execution, its selected tool,
arguments, working directory, exit result, inputs and output bytes. A compile
database or a favorable verbose log alone is insufficient. Capture complete
included-input observations, including headers selected by `-isystem`; record
system-input identity limits explicitly. Retain the raw compiler dependency
files. Apply their token-count bound before collecting repeated normalized
absolute input names once in first-seen order; a compiler may list a header
more than once. Both prepass and compile observations must reproduce that same
ordered input inventory and its before/after byte identities.
Parallel compilations may complete in
either order. Unique source/output identities and prerequisite relationships,
not an arbitrary total ordering, determine graph consistency.

## Objects, archives and links

Link maps are retained file payloads and use the existing 64 MiB per-file
limit. The separate 16 MiB JSON-receipt and command-log limits apply to those
data categories. Map line-count, line-length and semantic checks remain
independent bounds within the artifact limit.

Retain selected object bytes and complete ordinary GNU archives. Resolve GNU
long member names before enforcing exact ordered membership; reject thin
archives, duplicates, malformed bounds, absent and additional members. Each
member must match its successful compiler output. Archive indexing is a
separate observed step where the upstream build uses it.

Retain exact link commands and linker maps identifying consumed static archive
members. A `LOAD` record alone does not establish member selection. Join
yaml-cpp/spdlog objects to Ramulator and SoftFloat members to both guarded format
models. Preserve the exact model/backend recipe, permitting only explicitly
reviewed map-generation additions in the new route.

Stage only byte-verified products and required fetched source inputs at the
canonical measurement paths. Freeze them before configuring the managed builds,
and check stability through finalization. Retain object/source payloads in the
new bounded dependency packet; historical payload limits retain their meaning.

## Live admission and native population

Import every new trusted reader before helper/source freezing. Invoke the
existing complete 30-command application validator after the four independent
compiler roles are validated. It covers the exact 14-source runtime stub,
kernel-library compilation/archive/conversion and final host link.

Bind the full application result and dependency receipt digest into each
format's build identity before creating process identities. Execute the existing
FP16/BF16 × allocation-policy matrix: four processes, 132 launches and 4,224
exact FP32 words. Preserve all run/reset pairs, pending-read observations,
terminal state and actual destruction. The separate positive-pending probe and
always-zero control remain outside that population. Reject changed loaded paths
or product bytes even when numerical output passes.

## Failure and review

The first real failure remains the original reason even if final stability,
retention or cleanup checks fail later. Partial populations, retries and cached
products cannot replace a failed original. Retain failure evidence and original
hosted run/job/artifact identities.

The reusable reader consumes caller-pinned expectations and bounded exact
schemas. Retained paths, source, command strings and binaries remain inert.
Checks of a retained packet establish consistency, not authentication of an
untrusted producer or a new native execution. Independent review must reconcile
the source/build/product/loader joins with the named original.

Meaningful controls include missing fresh execution records, wrong immutable
source, stale objects, wrong tools/options, forged successful command text,
duplicate or omitted units, substituted archive members, changed link inputs,
alternate loaded libraries, retained-code execution sentinels and first-failure
preservation. A freshly built alternate dependency that still passes the
numerical smoke must fail provenance admission for its actual identity mismatch.

## Limits and acceptance

The fixed budget is two build jobs, one simulator worker, 15 GiB free disk,
4 GiB available memory and RSS bound, 120-second configure, 1,800-second build,
180-second native process, 16 MiB command logs and a 90-minute hosted job.
Enforce the nested job limit explicitly. Retained files are bounded to 64 MiB
each, dependency sources to 64 MiB, the complete new packet to 1 GiB and receipt
records to their declared limits. Resource supervision remains polling-based.

All seven qualification/warm/acceptance flags remain false. A passing new
provenance result is limited to its selected source/build/product chain. Complete
40-component lifetime premises, independent counter qualification, warm
performance, P06-A02/A03, vendor integration and physical hardware remain
separate obligations. No absolute no-wrap bound or complete compiler/system
closure is inferred.
