# Seed-free managed counter preflight v1

## Scope and admission boundary

`p06-managed-counter-preflight-v1` defines a separately identified, bounded
execution of the complete managed workspace caller on checked production SimX.
The [contract module](../../ci/project/p06_managed_preflight_contract.py) is the
authoritative definition. It constructs the preflight contract from the
unchanged [warm-v1 manifest](../../ci/project/p06_warm_contract.json), whose
exact-byte SHA-256 remains
`893d85401b1d5f7757d82cb7c743a89b36264fe19c7d08c239b7f216b7a8cbbd`.
Execution packets retain the constructed contract as inert JSON.

A passing preflight establishes its actual numerical, selected counter-read,
observed lifecycle and source/build consistency checks. It does not establish
the complete counter-lifetime theorem, qualify a performance experiment or close
an acceptance gate. All seven fields below must be present and exactly boolean
`false`; truthy integers, strings, missing fields and changed values reject:

| Fixed false field | Meaning of the excluded claim |
|---|---|
| `qualified` | Complete counter qualification has not been established |
| `ready_for_warm` | The full warm experiment has no admission from this result |
| `warm_execution` | No 24-process warm experiment is represented |
| `full_warm_coverage` | Four preflight processes cannot replace the full population |
| `acceptance_claimed` | This record grants no acceptance |
| `phase_acceptance` | P06 or another phase is not closed |
| `performance_acceptance` | No speedup or physical performance is accepted |

The fixed unresolved obligations are `all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance`, and
`independent_complete_counter_qualification`. Neither a producer assertion nor
consistent rehashing can remove these obligations under v1. A later admission
requires its own reviewed contract and supporting evidence.

The prior [warm measurement contract](warm_workspace_benchmark_v1.md), original
rejection, accepted cold evidence, numerical fixtures, poison schedule, kernel,
thresholds, and historical records remain unchanged. P06-A02/A03, P01 vendor
`hw_emu`, framework acceptance and physical-device obligations retain their
separate scopes.

## Fixed process population

Run the following processes serially, in this exact order, using one clean source
revision and one frozen executable/runtime/kernel set per format. Both policies
of a format use identical artifact bytes.

| Order | Format | Allocation policy | Outer process ID |
|---|---|---|---|
| 1 | FP16 | Per operation | `preflight-simx-fp16-per_operation` |
| 2 | FP16 | Reusable single tile | `preflight-simx-fp16-reusable_single_tile` |
| 3 | BF16 | Per operation | `preflight-simx-bf16-per_operation` |
| 4 | BF16 | Reusable single tile | `preflight-simx-bf16-reusable_single_tile` |

The original caller retains inner IDs `warm-simx-{format}-pair0-{policy}`,
`pair_index=0`, and `phase="warmup"`. They identify unchanged caller records;
they do not turn the new preflight into performance samples or qualify an old
archive. `execution_binding_sha256` binds the separately versioned preflight
inputs before launch and equals the binding supplied in the caller's existing
`qualification_id` argument. An identity digest is not a qualification decision.

Each fresh process opens one managed context, completes one prime and 32 further
serial operations, and explicitly closes every operation before another submit.
It uses the warm manifest's exact `single-dense_boundaries` fixture at
`M=8,N=4,K=8`, alternating poisons and independent FP32 expected words. Retain
all 33 operations, including the prime. No shortened population, replacement
process, retry within an attempt, dropped sample or statistical selection is
admitted.

| Evidence population | Per process | Complete preflight |
|---|---:|---:|
| Processes | 1 | 4 |
| Native matmul launches | 33 | 132 |
| Exact checked FP32 words | 1,056 | 4,224 |
| Complete snapshots | 4 | 16 |
| Successful available-counter queries | 132 | 528 |
| Successful raw half replies | 264 | 1,056 |
| Output-DMA cache-flush replies | 33 | 132 |
| Total observed DCR replies | 297 | 1,188 |
| Unavailable rows, each receiving no query | 48 | 192 |

The four ordered snapshot names are `after_open`, `after_prime`, `after_batch`,
and `before_release`. Each contains the exact historical 45 descriptors: all 33
available selectors and all 12 unavailable L2/L3 rows. Capability-derived
subsets and matching counts with different selector tuples are insufficient.

## Seed-free build and runtime binding

Use RV64 `p02-tfr` timing SimX, TFR tensor arithmetic, STD scalar arithmetic,
`PERF=1`, VM off and CP on direct RAM. The checked model and backend require
`SIMX_CHECKED_COUNTERS=1` with the existing 64-bit checked storage. Keep
`SIMX_FUNCTIONAL` and `SIMX_MT` absent. The simulation worker count is one;
build parallelism may be two. `make -j2` must not change `THREADS=1`.

The new regression reuses the unchanged managed warm caller and observer,
production runtime and native matmul kernel. Its separately linked observational
backend hook observes Processor construction, checked runs, DCR replies and
destruction. It adds no counter seeding, clearing, clamping or replacement. The
existing public `Core::perf_stats()` accessor refreshes the derived `opds_stalls`
aggregate from operand-unit totals, including when these hooks read cycles and
instructions. Therefore public getter observation does not establish immutable
counter storage or the complete backing-component lifetime proof. The wrappers
belong on the backend link: wrapping app references
alone does not intercept backend calls.

Require complete original compile/link inputs, independent role-specific
compiler records and generated/effective headers. The contract's
`required_measurement_sources` names the application/observer inputs that must
be represented in addition to the complete production source closure. Its
forbidden source roots, build components and symbol names identify diagnostic
seed/access code that cannot enter this build. These exclusions support the
positive exact-input validation; passing a blacklist alone does not prove a
binary is seed-free.

Bind the actual host, kernel, runtime, model and backend artifacts before each
launch and rehash them after completion. Match both policies' complete artifact
identities within a format. Retain exactly five loaded-library rows, sorted by
name: `libramulator-vortex.so`, `libramulator.so`, `libsimx.so`,
`libvortex-simx.so`, and `libvortex.so`. Each row has exactly `name` and `path`;
observe paths through `dl_iterate_phdr`, require unique canonical absolute paths,
and cross-bind the actual selected files to independently expected paths and
hashes. Other system libraries are outside this fixed inventory. Reject foreign
loader selections or drift. This observation establishes loaded bytes; reused
dependency hashes alone do not establish compilation from the reviewed
dependency source graph.

Bind the executing interpreter separately from PATH `python3`; require their
resolved bytes and identities to agree with pinned CPython 3.12.14 on Linux.
Retain all trusted local helper identities and check their stability. The
launch environment must exclude inherited loader injection, Python path
injection and arbitrary compiler/make overrides.

## Native witness and unchanged warm records

The output bridge consists of the complete unchanged warm output, ending in its
single `PASSED!` line, followed by exactly one JSON record prefixed with
`P06_MANAGED_COUNTER_WITNESS `. There is no second success marker. The witness
is one bounded line; nothing may follow it except its terminating newline.

The reader removes only that precisely placed, valid record and passes every
remaining original byte to the unchanged warm record validator. It must reject
duplicate, malformed, truncated, misplaced or unknown markers, trailing data,
an earlier failure and a second success line. It must not sanitize output by
discarding arbitrary non-warm lines.

The witness identity contains exactly `schema_version`, `contract_id`,
`process_id`, `sample_id`, `execution_binding_sha256`, `format`, and `policy`,
cross-bound to the independently supplied expected process and original warm
records. Schema version is integer `1`. The contract also defines exact field
inventories for the hook's model state, raw read, observation and destruction
structures; extra or missing fields reject.

The remaining top-level witness fields are `backend="simx"`, `xlen=64`,
`checked_counter_bits=64`, `simulation_workers=1`, `seeded=false`,
`observation`, `snapshots`, `reads`, `cache_flush_reads`, `loaded_libraries`, the fixed
`unresolved_obligations`, and all seven fixed false fields. The `seeded` field
does not establish seed exclusion without the exact build checks.

Each snapshot has exactly `name`, `before`, `after`, `read_begin`, `read_end`,
`device_refs`, `queues`, `buffers`, `cache_flush_count`, `cp_before`, and `cp_after`. The read interval
uses zero-based begin/inclusive and end/exclusive offsets into `reads`; each
span contains 66 replies. The CP fields are null on the first three snapshots
and exact CP observations on `before_release`. The final snapshot has one
Device reference and no registered queues or buffers. Earlier ownership values
are actual observations and follow their caller stage; they are not replaced
with terminal counts.

Each model state records `live`, `idle`, `any_running`, `generation`, `ticks`,
`reset_generation`, `core_cycles`, `core_instructions`, and `exitcode`. It
records only these public observations. Pending-read balance and the 40
individual backing components are not exposed by this observer and must not be
invented as zero values or silently treated as observed.

Each raw read records its global DCR sequence, generation, completed-run count,
address, tag, value, return
status, completion/overflow state, and before/after tick, reset, class, idle and
running state. Validate every expected low/high route in order, both successful
statuses, 32-bit widths and exact 64-bit reconstruction against the unchanged
snapshot value. Both halves and the whole snapshot must belong to one live
Processor generation and stable tick/reset state. All unavailable rows receive
no read. Missing, duplicate, reordered, wrong-class, failed or cross-generation
replies invalidate the process.

The unchanged output download flushes the cache once after every launch. These
33 replies are retained separately in `cache_flush_reads`; they must not be
silently ignored or confused with the 264 MPM halves. Each flush uses address
zero, core tag zero, successful zero response, completed-run counts 1 through
33, and global read positions 67 then 134 through 165. Snapshot flush counts
are exactly 0, 1, 33, 33. Counter reads occupy all remaining positions through
297. Flushes may advance the platform clock, while preserving reset generation
and MPM class and returning to idle. Counter snapshots still require unchanged
tick/reset state. Unknown additional DCR routes reject the process.

The final observation retains actual constructor/destructor entry and completion
counts, exactly 33 checked run entries/completions, all read/write and guard-error
counts, the construction state, final liveness and destruction observation.
Successful return from Device release cannot replace actual Processor
destruction. Any observed error or violation invalidates the process.

Before terminal release, retain actual final Device ownership, empty queue and
buffer inventories and enabled CP retirement observations. Preserve the
[public diagnostic contract's](simx_counter_public_diagnostics_v1.md) distinction
between unsupported head writeback, the staged-low/committed-high tail pair,
and the source-backed drain inference. A disabled busy bit or invented
head-equals-tail check is not a drain certificate. Platform disposal resets its
clock; post-destruction idle/reset values must follow that actual contract,
not an impossible cross-disposal monotonic-tick assertion.

Zero opening aggregate values are observed aggregate origins. Four snapshots
with monotone values are sampled observations. Neither proves every unobserved
component update, pending-balance reset or dependency-finalizer premise in the
[conditional lifetime contract](simx_counter_lifetime_v1.md).

## Pure validation interface and rejection

`load_contract(source)` validates the original frozen warm inputs and produces
the separately versioned preflight contract. `validate_contract` rejects any
field/value/type change. `process_plan` returns fresh copies of the exact four
process descriptors; `select_cases` delegates to the original independent
fixture selection; `counter_inventory` derives the fixed 33/12 partition from
the frozen capability values.

`process_identity(format, policy, binding)` constructs the expected witness
identity. The pure reader must compare against that identity, not trust values
selected by the witness itself. `fields`, `fixed`, `uint`, `digest`, and
`false_claims` enforce exact object fields, recursive types/values, integer
bounds, digest syntax and nonacceptance fields. Boolean values do not satisfy
integer checks. `decode_record` accepts only bounded UTF-8 objects with unique
keys, finite integral values, at most 16 levels of nesting and valid Unicode;
it never executes or imports retained data.

`validate_loaded_libraries` checks the exact five-row schema and optionally
cross-checks separately supplied expected paths. It does not inspect producer
filesystem paths or infer symlink resolution from recorded text. The executing
runner separately observes file identities; a pure replay uses retained
identities and independent expectations.

Complete native preflight success is derived only when all four original
processes and their source/build/command/resource bindings validate. A replay
must recompute the result from retained originals, preserve false qualification
and acceptance fields, and state `native_execution="not_run"`,
`retained_code_executed=false`, and retained-data-consistency-only scope.
Caller-selected archive/source digests identify expected evidence; they do not
authenticate an arbitrary producer. Never import retained helper code, execute
recorded commands or open recorded producer paths on the replay host.

Required rejection coverage includes disabled/host-only guards, diagnostic
object insertion, unsupported topology or workers, mismatched interpreters,
stale generated headers, changed artifacts between policies, wrong loaded
libraries, nonzero origins, missing/incorrect counter halves, failed or
incomplete cleanup, changed population, malformed records and consistently
rehashed incompatible evidence. Favorable timings cannot bypass a rejection.
Independent enforcement review precedes native execution or result admission.

## Execution and retained failures

Use fresh, nonoverlapping source/work/output locations and one immutable attempt
identity. Retain command intent before launch, bounded logs, exit and cleanup
status, failed attempts and any complete prior process results. Stop subsequent
work at the first failure. Never overwrite an old attempt or substitute a later
success for its failed prime/process.

Preserve the existing limits: two build jobs, one simulation worker, 4 GiB polled
RSS, 15 GiB free-disk reserve, 16 MiB command logs, 120-second configuration,
1,800-second builds, 180-second invocations and a 90-minute hosted job. An early
resource block has no native execution. Tool/build commands starting do not
mean a managed native process ran. No download, cache write, toolchain install,
budget waiver or full-GPU build follows from this contract.
