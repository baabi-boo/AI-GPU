# Local fresh-dependency execution v1

## Purpose and evidence scope

The local route executes the existing P06 fresh dependency build, managed native
lifetime population and two separate controls without requiring a GitHub runner
or claiming that a hosted cache was restored. It uses the same source locks,
compile and link grammar, numerical fixtures, lifetime witness and application
admission as the hosted route. Hosted evidence retains its existing envelope.

The local envelope identifies actual local child execution. Its inert reader
checks retained consistency; it does not authenticate a producer or rerun the
retained compiler, source, command or binary. Independent review must distinguish
that replay result from the named original execution.

All seven `qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
`acceptance_claimed`, `phase_acceptance` and `performance_acceptance` fields remain
false. This prerequisite does not close the complete counter qualification or
P06-A02/A03 performance gates.

## Inputs and preparation

[`p06_dependency_local_prepare.py`](../../ci/project/p06_dependency_local_prepare.py)
emits `p06-local-dependency-preparation-v1` with an explicit `local` execution
origin. It requires a clean, exact source revision and initialized recursive
gitlinks. It verifies the five immutable dependency trees through their actual
Git objects, rejects existing staged products or fetched-source directories,
and records the same host-tool aliases that the build and native runner use.
SoftFloat and Ramulator are read from the selected checkout's initialized
gitlinks; yaml-cpp, spdlog and argparse are read from the correspondingly named
repositories beneath `--dependency-repositories`. The currently reviewed
checkout has five top-level gitlinks and eight recursive entries. Preparation
does not fetch missing inputs or restore a dependency cache.

[`p06_local_toolchain.py`](../../ci/project/p06_local_toolchain.py) selects the
four SimX components from the reviewed
[`p01_toolchain.lock.json`](../../ci/project/p01_toolchain.lock.json): RISC-V GNU,
Vortex LLVM, libc64 and libcrt64. The immutable bundle revision is
`e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`; its 15 selected parts total
606,992,434 compressed bytes. This selection does not assert where the rolling
`v3.0.2` tag points at a later date. Verilator is outside this SimX-only selection.

Provisioning verifies each part's SHA-256, size and Git blob identity before and
during streamed extraction into a fresh directory. It rejects unsafe member
types, duplicate destinations, links outside their component and unsupported
paths. Link resolution expands symbolic prefixes before applying parent
segments; actual installed links must agree with the retained resolution. The
11 selected native compiler/library identities are joined to archive members.

The preparation records local archive acquisition, never an invented cache key
or GitHub run identifier. The existing hosted preparation discriminator rejects
local-only fields. Both the dependency producer and inert dependency reader
validate the selected preparation, host tools, source manifest and checkout.
The live native admission rechecks the preparation and selected native tools at
its stability boundaries, including invoked and resolved paths.

The toolchain metadata reader validates recorded consistency without opening
producer paths or rehashing the large archives. Independent original review
must supply any claim about actual archive and installed bytes. System headers,
host compiler support files and runtime libraries retain the existing limits of
the dependency and native contracts.

## Execution sequence

[`p06_dependency_local_execute.py`](../../ci/project/p06_dependency_local_execute.py)
runs these stages serially, each in a fresh Python interpreter:

1. Local source and prebuilt preparation.
2. The existing fresh dependency build: 406 compilations, three archives, two
   archive indexes and two shared links.
3. The existing FP16/BF16 by allocation-policy managed lifetime population:
   four processes, 132 launches and 4,224 checked FP32 output words.
4. The separate pending-read probe and compiled always-zero control.
5. The separate alternate-dependency control, whose correct numerical result
   must still be rejected by the original dependency-provenance check.

Only the third stage contributes to the managed population. Control execution
does not increase those counts. Every stage must retain its original report,
successful bounded-process result and agreeing terminal output. A failed stage
stops the sequence and remains a failed attempt. Each attempt uses a fresh
workspace; the runner does not overwrite a previous attempt.

The caller selects the same explicit `--host-bin` for preparation, dependencies
and the managed runner. Changing only the native compiler after dependency
compilation is rejected. The route requires Linux CPython 3.12.14 and does not
introduce warning suppressions to admit a host compiler. A compatible host
installation includes compiler support and link-time runtime files as well as
the executable aliases. In the reviewed local environment, GCC 12.2.0 and
CMake 3.22.6 were selected; the matching shared `libstdc++6` package is necessary
to avoid the incomplete host installation's static-library fallback. These
host observations do not extend the receipt to complete host/OS provenance.

### Managed-report JSON intake

The complete dependency-managed report has an explicit maximum of 500,000
structural tokens. The outer executor selects that bound only for the
`native-lifetime` child report. The pending and substitution producers select
it only for managed input on the dependency route, after requiring an exact
dependency-receipt SHA-256 argument. They then enforce the existing matching
contract, revision, provenance pin, completed population and false claims.

The shared baseline parser's default remains 250,000 tokens. Its optional token
budget must be an exact integer no greater than 500,000; the 64-level depth
limit, 1,024-character number limit, unique fields, strict UTF-8 and finite
number checks remain unchanged. Managed report intake remains bounded at
16 MiB. Historical managed intake, source/tool snapshots and terminal log
records retain the generic limit. This parsing allowance changes no execution,
numerical, resource or qualification criterion.

## Budgets

The existing limits remain two build jobs, one simulation worker, 15 GiB free
disk, 4 GiB minimum available memory and 4 GiB child-process RSS. Configure,
build and native-process limits remain 120, 1,800 and 180 seconds respectively;
command logs remain bounded at 16 MiB. The whole local route has a polled
90-minute deadline. Each inner producer retains its own process supervision.

The outer process-group monitor does not establish an aggregate descendant RSS
limit or hard containment of child-created process groups. Its limitations are
retained in the envelope. Archive provisioning separately limits expansion to
4 GiB, individual members to 1 GiB, archive members to 50,000 and elapsed time to
1,800 seconds while preserving the disk reserve.

## Packet and inert replay

`evidence/local-execution.json` uses
`p06-local-dependency-execution-v1`. It binds the source, interpreter, stage
ordering, exact argv/environment, command results, report digests and retained
orchestrator source. The evidence directory also contains the original local
preparation, five stage logs and the four dependency/native/control subpackets.
Keep unrelated shell logs outside this directory.

[`p06_dependency_local_replay.py`](../../ci/project/p06_dependency_local_replay.py)
requires externally supplied pins for the archive, revision, local envelope,
dependency report, native report, native source snapshot and both control
reports. It reuses the complete dependency, native and control readers within
one bounded archive-reader context, including closing integrity verification.
The local origin, exact packet inventory, tools, stage records and terminal
outputs must all agree. A prefix changes only the packet's location inside the
archive; it does not expand the allowed inventory or grant filesystem access.

The native Ramulator destructor also writes a diagnostic file in each control's
working directory. Replay requires exactly `pending-probe/ramulator.stats.log`
and `dependency-substitution/work/ramulator.stats.log`, bound to the retained
destructor source and accounted as nonempty, at most 16 MiB opaque bytes. Their
hashes and sizes are returned with `interpreted`, `numerical_evidence`,
`performance_evidence` and `qualification_evidence` explicitly false.
Values such as `.nan` for an idle channel remain uninterpreted diagnostics.
The substitution file is produced after its frozen compilation products; it
belongs only to the final retained inventory. Missing diagnostics, unrelated
extra files, changed final identities and diagnostics inserted into the frozen
product snapshots remain rejected. These files contribute no managed processes,
launches, checked words or qualification observations.

A replay pass reports `native_execution="not_run"` and
`retained_code_executed=false`. The independently identified original supplies
execution evidence. A consistently fabricated record remains fabricated after
consistency checks; local evidence is never relabelled as a hosted run.

The [local execution and replay runbook](../project/evidence/p06-dependency-provenance/local-execution/runbook.md)
describes fresh input layout, compatible host prerequisites, packet preservation
and the exact command-line pin mapping. Instructions in that guide are not
execution evidence; completed results belong to their separately identified
originals and independent reviews.
