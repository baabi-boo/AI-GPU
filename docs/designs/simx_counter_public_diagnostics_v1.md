# SimX public native counter diagnostics, version 1

## Scope and version boundaries

This contract describes the real Processor/RAM public diagnostic implemented
by [public_main.cpp](../../tests/unittest/checked_counters/public_main.cpp),
[public_hooks.cpp](../../tests/unittest/checked_counters/public_hooks.cpp) and
the [native producer](../../ci/project/p06_counter_public_execute.py). It
extends the [all-selector model diagnostics](simx_counter_diagnostics_v2.md)
through the common runtime, SimX backend and functional command processor
(CP). The native observation details below were established by the corrected
execution at `e5f152464dda5e488d6d1a030c1fcdc49b5a9701` and independently
confirmed by the later `4268d2d5d811063bb886cde7bd0e27e61a79c9b4` original.
The execution section keeps their source and receipt identities separate;
implementation links identify the corresponding source and current readers.

The three public version numbers identify different records:

| Record | Contract or marker | Schema | Meaning |
|---|---|---:|---|
| Native packet report | `simx-counter-public-native-v1` | 1 | Producer source/build/command bindings, separate boundary control and five public cells |
| Raw native observation | `COUNTER_PUBLIC_RESULT` | 2 | One mode's assertions, native entry counts, errors, terminal vectors and destruction records |
| Offline replay receipt | `simx-counter-public-replay-v1` | 1 | Current trusted reader's consistency checks over retained bytes |

The [raw parser](../../ci/project/p06_counter_public_records.py) requires the
schema-2 fields and exact per-mode inventory. A producer report's schema 1
does not admit an older raw observation schema. The independent model packet
uses `simx-checked-counters-native-v2`; its offline reader emits
`simx-counter-diagnostics-replay-v1`.

These are diagnostic contracts. `qualified`, `ready_for_warm`,
`warm_execution`, `full_warm_coverage`, `acceptance_claimed`,
`phase_acceptance` and `performance_acceptance` remain false. The
[warm-v1 contract](warm_workspace_benchmark_v1.md) retains its unconditional
`P06-WARM-RV64-MPM-HIGH-HALF` rejection and unestablished absolute no-wrap
bound. P06/P06-T01 remain in progress and P06-A02/A03 remain open.

## Admitted route and diagnostic build

The admitted route is RV64 timing SimX, `p02-tfr`, TFR tensor/STD scalar
arithmetic, `PERF=1`, `SIMX_CHECKED_COUNTERS=1`, one cluster/socket/core,
four warps of four threads, issue width one and one simulation worker.
Instruction/data caches and local memory are enabled: one instruction-cache
bank, two data-cache banks, one LSU block, one TCU block and two external
memory channels. VM, L2, L3, WGMMA and CP-on-LLC are excluded. Each selected
public query uses `core_id=0`; the unchecked host sum for `core_id=0xffffffff`
is outside this contract. Generated configuration and compiler records must
establish the route, not just its profile name.

With `CP_ON_L2=CP_ON_L3=0`, CP transfers use registered host memory or actual
functional `RAM::read/write`. They do not enter the timing processor's
`cp_mem_transfer`. The workload still executes on the actual timing
Processor and default HBM2 Ramulator adapter; alternate DRAM models and
plugins are outside this binding.
([Backend](../../sw/runtime/simx/vortex.cpp),
[Processor](../../sim/simx/processor.cpp),
[configuration validation](../../ci/project/p06_counter_public_build.py).)

The [diagnostic makefile](../../tests/unittest/checked_counters/public.mk)
places five GNU linker `--wrap` targets on the diagnostic backend link:
Processor construction, destruction, `run_checked`, `dcr_read` and
`dcr_write`. Each hook calls the corresponding `__real__` operation. It
records actual entry/completion, typed `PerfCounterError` observations and
model state, and rethrows errors. It does not replace Processor/RAM or
manufacture an overflow exception. Test accessors seed actual component-owned
storage only while the model is quiescent. These hooks and accessors belong
to diagnostic binaries; production targets retain their normal source lists.

The initial checked model build contains 45 translation units and one link,
including the byte-exact production TCU body followed by its diagnostic
footer. The public build compiles 19 new units and reuses 44 model objects.
Its four links have distinct roles:

| Output | Inputs and role |
|---|---|
| `libchecked-simx.so` | 44 checked model/accessor objects, excluding the model test main |
| `libvortex.so` | 14 common/stub runtime objects |
| `libvortex-simx.so` | Three backend objects plus the observation-hook object; all five Processor wraps resolve here |
| `checked_public_test` | Public diagnostic main, linked to the runtime and backend |

The [build-record validator](../../ci/project/p06_counter_public_build.py)
binds ordered macro inventories, exact compiler flags, source/object mappings,
dependency targets, generated inputs and link arguments. Retained object and
binary identities supply recorded binding/stability evidence; their payloads
are absent from the archive.

## Public scenarios and required observations

Each mode runs in its own native test process and constructs two successive
actual Processor contexts. Every context uploads and downloads the exact
three-word program `[0x00700193, 0x0000700b, 0x0000000b]` through public queued
transfers. Successful scalar execution must produce the `gp=7` exit witness,
positive instruction/cycle counts, idle platform state and zero pending reads.
The raw `program_words_verified=6` counts both three-word readbacks.

The corrected original reports:

| Public mode | Assertions | First context | Later independent control | Successful terminal snapshots | Native half-read entries |
|---|---:|---|---|---:|---:|
| `normal` | 1,668 | Unseeded scalar success | Fresh unseeded scalar success | 2 | 132 |
| `immediate-overflow` | 1,176 | Cycles seeded to `UINT64_MAX`; real updater overflows | Fresh unseeded scalar success | 1 | 66 |
| `delayed-overflow` | 1,176 | Cycles seeded to `UINT64_MAX-2`; two increments precede overflow | Fresh unseeded scalar success | 1 | 66 |
| `cache-overflow` | 1,173 | Scalar success, then actual D-cache read components seeded to `UINT64_MAX` and 1; real aggregation fails | Fresh unseeded scalar success | 1 | 67, including one failed read |
| `coherent-terminal` | 1,814 | Scalar success, then all backing components seeded for full-width terminal readout | Fresh unseeded scalar success | 2 | 132 |

The coherent seed for selector index `i`, component index `k`, is
`0x1234567800000000 + 2*i + k`. Its terminal values are seeded transport
evidence; the preceding scalar witness and the later fresh unseeded context
are recorded separately. The two normal contexts are unseeded throughout.
The asynchronous overflow contexts retire no scalar instructions; the delayed
case reaches exactly `UINT64_MAX` before the rejected update. The cache case
retains the failed native low-half read and unchanged poisoned components.

All three negative modes require `VX_ERR_INVALID_VALUE` (3), repeated event
wait and higher-timeline failure, multi-event failure, a completed event
timeline, and queue-finish error consumption. Consuming that queue-local
error does not clear the backend's sticky processor failure. Two later public
counter queries must preserve the 64-bit sentinel
`0xdecafbad12345678`; later DCR write, DMA and second-queue launch attempts
must fail without additional run/read/write/overflow entries.

DMA suppression has its own side-effect check because the direct-RAM path
can bypass Processor entry hooks. Each negative mode attempts the bitwise
inverse of the original three program words. In the original packet the
address is 196,608, status is 3, and direct observations of actual RAM before
and after both equal `[7340435, 28683, 11]`. The attempted payload differs.
The namespace-scope `constexpr` original and inverse arrays have static
storage duration, keeping the asynchronous DMA source alive through waits
and cleanup. A failure must discard the context; the later fresh-context
success is an independent control, not recovery of the failed lifetime.
([Caller](../../tests/unittest/checked_counters/public_main.cpp),
[RAM observation and real-operation hooks](../../tests/unittest/checked_counters/public_hooks.cpp),
[sticky execution owner](../../sw/runtime/common/async_run.h).)

## Terminal ownership, CP interpretation and destruction

Each successful terminal vector covers exactly **33 available selectors and
40 actual backing components**; the 12 unavailable L2/L3 selectors remain
unqueried. The caller finishes work, releases all events, queues and the
program buffer, then verifies the actual device reference count is one and
the queue/buffer registries are empty. A deliberate extra device retain must
fail this ownership predicate. The real queue destructor joins its worker
before unregistering and releasing its device reference.
([Terminal caller](../../tests/unittest/checked_counters/public_main.cpp),
[queue lifetime](../../sw/runtime/common/queue.cpp),
[reference ownership](../../sw/runtime/common/vortex2_internal.h).)

Both CP enable controls must still be one. Before and after readout, CP
status/error are zero and retired sequence equals the runtime's expected
sequence. In all seven original terminal snapshots, sequence advances
**26 → 92**, and runtime tail plus the recorded raw tail pair advance
**1,664 → 5,888**: 66 half-read commands at 64 bytes per retired command.

`head_writeback_raw=0` is retained with
`head_writeback_status="not-published"`. The functional CP stores the head
writeback address but does not publish its internal head there. The raw tail
pair combines the **staged low register and committed high register**; it
is not an independent complete committed-tail observation. Drain is a
source-backed inference under exclusive serial submission: writing high
commits the staged low word, runtime submission waits for retirement, and
the enabled CP's `busy()` covers unconsumed ring work, a loaded cacheline,
command-engine work and launch work. These conditions, exact retirement and
tail accounting establish the inference without treating initialized head
bytes as an observed internal head.
([CP implementation](../../sim/common/cmd_processor.cpp),
[runtime submission](../../sw/runtime/common/device.cpp).)

Each selector's low/high replies must match its actual checked aggregate
using exact integer reconstruction. Raw selector tags, successful statuses,
saved-class restoration, ticks and reset generations must agree. Model state
and all 40 components remain unchanged across the entire vector. This
requires exclusive submission: `cp_submit_dcr_read()` does not hold the
submission mutex across its final response-register read. The public API is
not a concurrent atomic snapshot API.
([Public MPM API](../../sw/runtime/common/perf.cpp),
[raw validation](../../ci/project/p06_counter_public_records.py).)

The terminal observation precedes CP disable and final device release.
`cp_quiesce_()` disables CP before polling and can return without proving
drain, so it is not a terminal certificate. Destruction hooks compare the
actual pre-destructor model state with the last recorded state and observe
completed Processor destruction, zero platform ticks and idle state. The
clock reset is cleanup state, not a monotonic counter observation. Across
five modes the corrected packet records **10 constructions/disposals, seven
terminal snapshots, 231 selector queries, 462 successful native half reads
and one additional failed cache half read**.

The [terminal lifetime argument](simx_counter_lifetime_v1.md) supplies the
conditional monotonicity and no-later-update reasoning. Its dependency
finalizer argument remains conditional on the actual loaded dependency
implementing the pinned source graph. Diagnostic scalar observations do not
establish the complete managed warm caller's ownership/reset/lifetime
premises or the provenance of a later measurement binary.

## Original execution and retained failure

The [native index](../project/evidence/p06-counter-diagnostics/native/index.json)
retains the original archives and their outcomes. The corrected source is
`e5f152464dda5e488d6d1a030c1fcdc49b5a9701`, tree
`74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`.
[Run 45031746149](https://github.com/baabi-boo/AI-GPU/actions/runs/45031746149),
attempt 1, job `137236632765` succeeded. Original artifact `14758252829` is
retained byte-for-byte as
[run-45031746149-attempt1.zip](../project/evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip):
4,228,429 bytes, SHA-256
`05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276`.
The [three-field pass locator](../project/evidence/p06-counter-diagnostics/native/public-runtime-pass.json)
binds that archive name, digest and producer revision; it is not a
qualification decision.

Independent original-data review reconciled the hosted run/artifact identity,
source bodies against immutable Git blobs, command logs and raw results.
The combined corrected packet passes **13 native test process cases**:
seven model cells (ordinary/checked boundaries, core overflow, cache aggregate
overflow, pending primitive underflow, cache backing overflow and TCU backing
overflow), a separate checked boundary control for the public build, and the
five public modes above. Each model boundary result has 6,389 assertions and
1,788 half reads over 33 selectors/40 components. The model report retains
17 commands; the public report retains 14. Native intake/review is complete
for this bounded diagnostic scope.

The latest [run 45034575685](https://github.com/baabi-boo/AI-GPU/actions/runs/45034575685),
attempt 1, job `137245341329`, separately succeeds at
`4268d2d5d811063bb886cde7bd0e27e61a79c9b4`, tree
`061ecbddc9b321edbd70c054c8efce4d188de04f`. Original artifact `14760051170` is
retained byte-for-byte as
[run-45034575685-attempt1.zip](../project/evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip):
4,290,949 bytes, 1,046 members, SHA-256
`6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb`.
The [independent original-packet audit](../project/evidence/p06-counter-diagnostics/native/w10-native-checkpoint-audit.md)
matches all 270 model and 683 public source bodies to immutable Git and confirms
all thirteen passing process cases, 17 model/14 public commands and the same
public observation counts described above. The unchanged three-field pass
locator continues to identify the earlier `e5f1524` original.

Both latest inert replay routes pass. The public route explicitly uses the
independently Git-pinned
[683-source manifest](../project/evidence/p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json),
SHA-256 `bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`.
Its seven added public source files do not alter the original fixed 676-name
route: that route rejects the expanded packet, and a wrong explicit digest
rejects without fallback. These replay receipts retain the data-only scope
and false qualification/readiness/warm/acceptance claims.

The earlier `81ed6871634fefbf5c78fb27cf10dce913bd4d9c` attempt,
[run 45029135146](https://github.com/baabi-boo/AI-GPU/actions/runs/45029135146),
remains a native failure: seven model cells and the public build's boundary
control passed, public normal failed with `terminal CP ring is not drained`,
and four public modes were blocked. Its harness had equated unsupported head
writeback storage with the submitted tail. The correction changes the
diagnostic observation/validation contract, not production CP behavior. A
successful integrity audit of that failed original never changes its native
outcome. The separate earlier all-selector original at `407ab9f` remains
model-only evidence.

## Producer resource and retention contract

The [workflow](../../.github/workflows/p06-checked-counters.yml) and
[producer](../../ci/project/p06_counter_public_execute.py) retain the
**15 GiB disk reserve, 4 GiB available-memory prerequisite and monitored RSS
bound, two build jobs and one simulation worker**. Timeouts remain 120 seconds
for configuration, 1,800 seconds for a build and 180 seconds for a case, with
16 MiB bounded command logs. The native public interpreter is pinned to
**CPython 3.12.14 on Linux**; executing-Python and PATH `python3` identities
must agree. These are execution prerequisites, not replay-side tool installs.

Reports bind clean checkout revision/tree, submodule pins, full retained source
bodies, generated configuration, original compiler/link records, interpreter
and tool identities, dependency identities, raw command logs, process outcome,
cleanup and resource observations. Public execution has nine input-binding
groups and the exact before/after stability sequence for all 14 commands.
Unexpected exit, timeout, build failure or missing data fails the relevant
case; an expected fault passes only when its native diagnostic completes
successfully after checking that fault. Failed and blocked cases remain
visible.

## Offline usage and source inventory trust

Use the current trusted repository readers from the physical source-root
directory. The following commands match their `--help` interfaces and the
retained originals. Archive paths must be absolute, canonical and free of
symlink components. `--output` creates a new file exclusively: choose unused
paths, or omit it to print the complete receipt.

```sh
P06_SOURCE_ROOT=$(pwd -P)

python3 ci/project/p06_counter_diagnostics_replay.py \
  --archive "$P06_SOURCE_ROOT/docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip" \
  --sha256 c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f \
  --source-revision 407ab9fea5e4f793a2a5088f566a87f3e631aa84 \
  --output /tmp/p06-all33-original-replay.json

python3 ci/project/p06_counter_public_replay.py \
  --archive "$P06_SOURCE_ROOT/docs/project/evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip" \
  --sha256 05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276 \
  --source-revision e5f152464dda5e488d6d1a030c1fcdc49b5a9701 \
  --output /tmp/p06-public-original-replay.json
```

The default prefixes are `checked-counters` and `public-counters`,
respectively. The first command checks seven model cells; the second checks
six cells (one model boundary control and five public modes). The model
reader can also check the corrected archive's seven model cells by using
that archive, its digest and `e5f1524`'s full revision together. Do not sum
receipts from different originals into a new execution claim.

Without external expectations, the readers pin the **complete original
270-name model and 676-name public inventories**, including uncompiled
headers and producer helpers. They do not accept only the compiled units or
rediscover the original inventory from a later checkout. Retained bodies are
rehash-checked against their descriptors and source snapshots.

An extended producer source inventory requires an independently reviewed
complete manifest under
[simx-counter-source-inventory-v1](../../ci/project/p06_counter_source_inventory.py)
and its separately supplied SHA-256. Its exact fields are `schema_version: 1`,
`contract_id`, `producer_contract_id`, `source_revision` and `sources`.
Each source row contains `path`, `sha256` and `size_bytes`, in unique
lexicographic path order. Every original mandatory name remains required;
additions are limited to the helper's reviewed producer roots. The archive's
complete descriptors must equal the manifest, and retained body bytes must
match. No descriptor path is opened on the replay host.

After assigning the following variables from those independent expectations,
the optional public invocation is:

```sh
python3 ci/project/p06_counter_public_replay.py \
  --archive "$P06_ARCHIVE" \
  --sha256 "$P06_ARCHIVE_SHA256" \
  --source-revision "$P06_PRODUCER_REVISION" \
  --source-inventory "$P06_SOURCE_MANIFEST" \
  --source-inventory-sha256 "$P06_SOURCE_MANIFEST_SHA256" \
  --output "$P06_REPLAY_OUTPUT"
```

The same explicit manifest option is also available for an unchanged inventory.
The model reader accepts the option pair with its own producer contract.
Supplying only the manifest path or only its digest is rejected. A malformed,
incomplete, mismatched or unsafe explicit manifest fails without falling back
to the original inventory. The digest covers exact manifest bytes and must
come from the caller's trusted expectation, not from an archive assertion.
A matching revision label and manifest do not independently prove Git
provenance, compilation or execution.

Both [model replay](../../ci/project/p06_counter_diagnostics_replay.py) and
[public replay](../../ci/project/p06_counter_public_replay.py) treat archive
members, commands and producer paths as inert data. They never extract,
import or execute retained code, rerun retained commands, open recorded
producer paths or build native binaries. Receipts record the trusted archive
reader and the **current local helper closure** under
`trusted_replay_sources`, with path, SHA-256 and size. Preserve that receipt
with its external archive/revision/optional-manifest expectations; a future
reader's identity must come from its actual bytes, not a guessed commit.

Successful replay means `scope="retained-data-consistency-only"`,
`native_execution="not_run"` and `retained_code_executed=false`. Consistent
synthetic or forged records remain synthetic or forged. External digests
identify bytes but do not authenticate GitHub origin. Absent object,
executable, library, tool and dependency payloads cannot be independently
rehash-checked, and cached dependency identities do not prove compilation
origin. Host-header/system-library coverage and before/after filesystem
checks have their recorded limits. Neither replay nor these seed-enabled
diagnostics qualify a seed-free measurement binary, GEMM, workspace reuse,
the complete cumulative warm lifetime, warm performance, RTL, full-AFU/vendor
emulation or physical hardware.
