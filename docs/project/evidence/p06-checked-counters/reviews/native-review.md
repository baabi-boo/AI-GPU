# Independent original native evidence review

Behavior/evidence reviewer: `/root/w09_a01_native_packet_review`.
Build/source-binding reviewer: `/root/w09_a02_native_build_binding`.
The root coordinator retained these summaries of independent read-only
reviews. Neither reviewer authored the implementation, changed files, built
the model, published changes, or executed/imported code from the archive.

**Verdict: LAND the retained five-cell result as a bounded native prerequisite.
Neither review identified an F1, F2 or F3 finding in its assigned scope.**
Qualification, warm readiness, acceptance and complete coverage remain false.

## Original identities

| Item | Independently verified value |
|---|---|
| Actual source | `9fd7eac203c77fa54c7af80fa0220ae09553cd55` |
| Actual source tree | `973fa9a286686990c96d10f95ab2e77ed6328f1a` |
| Run / attempt | `45017731063` / `1` |
| Event / branch | `push` / `refs/heads/master` |
| Original artifact | `14753040127` |
| ZIP bytes | 1,119,268 |
| ZIP SHA-256 | `66dd0db69db3fb0d22f975c8d67cea8f445aa40a3f1ac0fbb0d5b20529aa9b40` |
| Original report bytes | 321,879 |
| Original report SHA-256 | `6bd18eec99dd2083eeb87d8fbb6cbfedfce072e85bf8e50de0e426e7ba11a88a` |
| Retained workflow SHA-256 | `0f7a12fe7e491b4464bd62e07ace3da310c812381291d88d5565b230e7858091` |

The [standalone report](../native/report-45017731063.json) is byte-identical
to `checked-counters/report.json` in the [original ZIP](../native/run-45017731063-attempt1.zip).
The archive has 317 unique entries, a successful CRC check, no traversal or
absolute paths, no symbolic links and 3,910,608 expanded bytes. `job.json`
records initialization; its initial `native_execution: "not_run"` is not
the final result. The final execution log and report record the actual pass.

## Behavior and original command evidence

The behavior reviewer parsed all five original output records and checked
their equality with the report observations. Every cell started, exited zero,
contained exactly one valid result record with no failure diagnostic, and
completed process cleanup.

| Cell | Independently supported result | Limit |
|---|---|---|
| `ordinary-boundaries` | Nineteen production-storage selectors, ten vectors, both half orders through actual `Processor::dcr_read`; zero failed checks | Fourteen available selectors remain unseeded |
| `checked-boundaries` | The same transport, reset-retention and aggregate assertions pass with checked storage | Quiescent reads, not concurrent public snapshot coherence |
| `checked-core-overflow` | Actual Core cycle update throws through `run_checked` and production `AsyncRun`; protected value stays maximal, no instruction retires, failure remains terminal, later work is suppressed, then a fresh context succeeds | Does not execute the public runtime |
| `checked-cache-aggregate-overflow` | Production `Cache::PerfStats::operator+=` rejects overflowing first-field `reads` addition with unchanged tested source/destination | Does not promise rollback after a later aggregate member fails |
| `checked-pending-underflow` | The pending-count primitive rejects decrement from zero without mutation | Does not inject into the private Processor pending-read balance |

The boundary arithmetic independently reconciles to 760 half reads and 2,749
checks per mode: 19 initial-zero checks, 2,280 status/value/restored-class
checks for the half reads, 380 reconstruction checks, 19 reset-retention
checks and 51 checks across seventeen aggregate fields. The ordinary and
checked records agree except for the expected instrumentation flag. Both
retain fourteen unseeded available and twelve unavailable selectors.

The actual updater fault is supported by source control flow: the harness
seeds the Core cycle field to `UINT64_MAX`; production tick increments it;
the guard throws before mutation; `run_checked` propagates the error; and
`AsyncRun::collect` consumes the future and retains terminal failure. Eight
subsequent failure checks and two suppressed task bodies are observed. The
failed owner, Processor and RAM leave scope before the new context is created.
Its program returns architectural witness 7, retires instructions and finishes
with no processor work still running.

All fifteen original command logs match their recorded hashes and sizes
(329,907 bytes total). Every command finished normally inside its stated
timeout, log-size and polled-memory bounds. Original before/after source,
tools, configuration, stamps, 44 objects per variant and binary identities
are equal. Source is recorded clean, dependencies initialized and required
tools present. These are the monitor's recorded boundaries, not protection
against an adversarial writer between observations.

## Independent build and source binding

The build reviewer independently parsed each original build log as 44 unique
C++ compilation commands and one actual link. The effective flags are uniform
within each variant and select the intended ordinary or checked configuration.
All 264 retained source files, totaling 2,817,261 bytes, match both their
recorded identities and Git source `9fd7eac…`. Thirty retained generated
configuration, stamp and probe artifacts match their hashes. All fifteen
command logs also match in this independent review.

The reviewer reconciled exact workflow/run/Python identity, initialized
submodules and dependency cache-key inputs. Before/after identities for all
objects and binaries agree. This establishes source/command and recorded
artifact binding; original executable and dependency bytes are identified
but are not included in this retained packet, so the reviewers did not
independently rehash or rerun those hosted binaries.

Each link consumes exactly its 44 recorded objects once, followed by the
identified SoftFloat, Ramulator and adapter dependencies. The independently
parsed command streams contain no extra compilation/link records, guard
undefinitions or hidden include/preprocessor overrides. The two original
header outputs reconcile to all 280 effective configuration entries. They
select RV64, native TFR/STD arithmetic, one core, four warps of four threads
and performance counters, preserving the declared feature exclusions.

| Original executable identity | Bytes | SHA-256 |
|---|---:|---|
| Ordinary | 2,061,384 | `6f5f55cc3bee5180983d592c67b2f6523ee58f4ab9e3ec669c1c5e236175fd5a` |
| Checked | 2,130,680 | `cf253e97ba8c876604ee768eeeddba6bcb3fce5c8f2f2ddad37692714dc7ad5f` |

The compiler record identifies GCC 11.4.0. Actual Python and PATH Python
resolve to the same CPython 3.12.14 executable, SHA-256
`d13074847cd54749b1189cd5a798fdbf32328ecfa297fd61ee457d767de3e6bd`.
All five top-level submodule revisions match their Git links; eight recursive
entries are recorded initialized. The toolchain identity remains
`v3.0.2-6cff3efdc1b721e4fec9165801ecd405be34dd11` with the matching `lite`
cache key. Recomputing the dependency digest from `third_party/Makefile` then
`.gitmodules` yields the recorded
`cbe0d7fc3a5ec7c6d1b71c86a227694d83e413fccc1d512acfa661fdbe86c7ac`.
Host headers, compiler support files, all loaded system libraries and nested
dependencies' remote repositories were not independently exhaustively audited.

## Resource scope

The original preflight records 86,514,470,912 free bytes on monitored paths
and 15,516,368,896 available memory bytes. Limits remain two build jobs, one
simulator thread, 15 GiB free disk, 4 GiB polled process-group RSS, 16 MiB per
command log and 120/1,800/180 seconds for configuration/build/scenario.

| Build | Elapsed seconds | Peak polled process-group RSS bytes |
|---|---:|---:|
| Ordinary | 45.730853 | 866,914,304 |
| Checked | 46.528315 | 867,987,456 |

The trusted runner passes these limits into its actual bounded monitor,
including descendant cleanup checks. A polled RSS limit is not a kernel
enforced instantaneous memory ceiling.

## Review boundaries and disposition

The unchanged base classifier reports R2 for `89aa432…` to `9fd7eac…`.
The reviewers applied R3 depth within their assigned evidence scopes because
the change deliberately introduces enforcement and diagnostic behavior.
Earlier independent reviews cover the implementation hunks and controlled
public-runtime tests; neither original-packet reviewer reran the host suite.

The packet establishes nineteen-selector native transport and the three
separately scoped failure scenarios. It does not establish all-thirty-three
native transport, native public failure/coherence, a continuous aggregate
lifetime bound, normal-workload cycle parity, a warm workload, speedup or
phase acceptance. `qualified`, `ready_for_warm`, `full_warm_coverage`,
`warm_execution` and `acceptance_claimed` remain false. Those limits are
consistent with the original records and current contract.
