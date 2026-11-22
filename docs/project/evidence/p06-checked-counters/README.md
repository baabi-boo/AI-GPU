# P06 checked-counter evidence

## Result and qualification status

The opt-in SimX checked-counter prerequisite is implemented. The retained
original hosted report records **PASS for all five directed native cells** at
`9fd7eac203c77fa54c7af80fa0220ae09553cd55`, run `45017731063`, attempt `1`.
It records `native_prerequisites_passed=true`, while `qualified`,
`ready_for_warm`, `acceptance_claimed`, `full_warm_coverage` and
`warm_execution` remain **false**. The [independent original-packet review](reviews/native-review.md)
confirms the actual behavior and exact source/build bindings, with no F1/F2/F3
finding in either assigned review scope.

The [development audit](../../p06-checked-counters-audit.md) explains the
selected next step. The [implemented counter contract](../../../designs/simx_checked_counters_v1.md)
defines checked storage, intermediate sums and typed terminal failure. The
[qualification plan](../../p06-mpm-qualification-plan.md) retains the remaining
source, lifetime, transport, public native failure and experiment obligations.
This packet grants no P06 acceptance or performance claim.

## Evidence map

| Retained record | Actual result and scope | Boundary |
|---|---|---|
| [Native original report](native/report-45017731063.json) and [original artifact ZIP](native/run-45017731063-attempt1.zip) | Five native cells pass; ordinary and checked variants each compile 44 translation units and link the production model with the directed harness | Partial selector coverage; no warm workload or public-runtime native fault qualification; independent behavior and source/build reviews complete |
| [Actual hosted governance index](hosted/governance-index.json), [original job log](hosted/governance-45017731138-job137193572417.log) and [independent review](reviews/hosted-governance-review.md) | **3,062 tests pass in 1,295.925 seconds** at actual published `9fd7eac…`, run `45017731138`, attempt 1; no failures/errors/skips | Separate later host execution with its original log; no native, warm or acceptance claim |
| [Immutable host governance report](local/governance-53f4ad08c/report.json), [raw log](local/governance-53f4ad08c/governance.log) and [file index](local/governance-53f4ad08c/index.json) | 3,043 tests pass at local `53f4ad08c469a1cc73fa604249b302f9416055e0`; raw unittest duration 1,647.227 seconds | Host governance, not a native model execution; includes the original 45 checked primitive/integration/runner methods |
| [Governance preflight log](local/governance-53f4ad08c/preflight.log) and [structure log](local/governance-53f4ad08c/structure.log) | Both commands pass at the same immutable local revision | The source inventory's uninitialized-submodule block remains a native prerequisite limitation, not a failed governance result |
| [Local native preflight](local/native-preflight-53f4ad08c.json) | Blocked below the unchanged 15 GiB disk reserve; zero subprocess commands, zero variants and all five cells blocked | Preserved local outcome; the later hosted pass does not rewrite it |
| [Build grammar packet](local/dry-run/README.md), [original report](local/dry-run/report.json) and [file index](local/dry-run/index.json) | Actual configure/stamp generation and `make -n`; 44 prospective compilations and one prospective link per mode | Object identity was explicitly mocked; zero C++ compilations, native links or model executions |
| [Public counter-fault review](reviews/public-fault-review.md) and [assignment ledger](agents.json) | Later author-reported five passing public methods / ten RAM/LLC cells, separately from fourteen passing workflow methods | Controlled Processor/RAM host tests; these nineteen methods were added after the 3,043-test immutable run |
| [Final source projection](source-projection.json) and [independent preservation review](reviews/final-source-review.md) | All 3,159 non-documentation source entries match native-tested `9fd7eac…`; historical protected inputs remain unchanged | Source equivalence supports reuse of the identified results without claiming execution at a later documentation commit |
| [Publication mapping](publication.json) | Exact local-to-published tree equality and non-force publication ancestry | Equal file trees do not change execution revisions or create a new test run |
| [Hosted workflow observation](hosted-status-9fd.json) | Timestamped statuses at the actual published source | Workflow status only; pending jobs and green workflow summaries do not establish new qualification |

The later nineteen methods bring the focused checked-counter suite to 64
methods: 12 primitive, six production-stat integration, 27 runner, fourteen
workflow and five controlled public-runtime methods. Five additional
executing-interpreter tests extend the existing transport suite. Do not add
the nineteen later methods to the 3,043-test receipt and present the sum as a
single execution. The actual later **3,062-test run** is established by its own
original hosted log and independent review. The retained public source review
preserves its earlier author-reported execution scope.

The original hosted governance log is retained byte-for-byte, including two
timestamp-prefixed blank lines with trailing spaces. The staged full-diff check
identifies only those two original log lines; the authored source/documentation
check excludes that raw log and passes. Normalizing the original receipt would
change its independently verified hash.

## Original hosted native execution

| Identity | Value |
|---|---|
| Workflow / event | `P06 Checked Counters` / `push` |
| Source revision | `9fd7eac203c77fa54c7af80fa0220ae09553cd55` |
| Source tree | `973fa9a286686990c96d10f95ab2e77ed6328f1a` |
| Run / attempt | [45017731063](https://github.com/baabi-boo/AI-GPU/actions/runs/45017731063) / `1` |
| Job | `137193572054` |
| Artifact | [14753040127](https://github.com/baabi-boo/AI-GPU/actions/runs/45017731063/artifacts/14753040127) |
| Artifact name | `p06-checked-counters-9fd7eac203c77fa54c7af80fa0220ae09553cd55-run45017731063-attempt1` |
| Original ZIP size | 1,119,268 bytes; 317 entries |
| Original ZIP SHA-256 | `66dd0db69db3fb0d22f975c8d67cea8f445aa40a3f1ac0fbb0d5b20529aa9b40` |

The directly readable report is a byte-preserved copy of
`checked-counters/report.json` inside the ZIP. The ZIP retains the original
report, logs, selected source bodies, generated configuration and compiler
evidence. **Retained code is inert evidence: inspection and replay must not
execute source, scripts or Makefiles extracted from the packet.** Object and
executable identities are recorded; this is not an archive of the binaries or
a complete build environment.

The route is fresh RV64 `p02-tfr`, serial timing SimX, `PERF=1`, TFR tensor
arithmetic and STD scalar arithmetic. It uses one cluster, core and socket,
four warps and threads, and issue width one. L2/L3 reporting remains disabled.
The two fresh build variants differ in checked-counter instrumentation; the
ordinary variant leaves `SIMX_CHECKED_COUNTERS` undefined and the checked
variant selects `SIMX_CHECKED_COUNTERS=1`.

### Five native cells

| Cell | Observed result | What it establishes and leaves open |
|---|---|---|
| `ordinary-boundaries` | PASS; 19 seeded selectors, ten vectors each, 760 half-word transport reads and 2,749 checks | Real Processor → Cluster → Socket → Core → CSR transport for the listed seeded values in ordinary mode |
| `checked-boundaries` | PASS; the same 19 selectors, ten vectors, 760 reads and 2,749 checks | Checked-mode boundary arithmetic and transport; observations equal the ordinary cell after removal of the mode flag |
| `checked-core-overflow` | PASS; typed overflow, protected value unchanged, eight sticky failure checks, two later tasks suppressed, terminal join and fresh-context success | Actual `Core::tick` updater through `Processor::run_checked()` and production `AsyncRun`; this native unit does not exercise public runtime wait/query integration |
| `checked-cache-aggregate-overflow` | PASS; typed overflow and unchanged source/destination | Actual `Cache::PerfStats::operator+=` with its first member overflowing; no claim of transactional rollback after a later member fails |
| `checked-pending-underflow` | PASS; typed underflow and unchanged zero | Actual `PerfCounter` primitive used by pending accounting; no injection into the Processor's private pending bookkeeping |

The Core cell seeds the actual cycles source to `UINT64_MAX`; the attempted
tick throws before changing it and before any instruction retires. The entire
failed Processor/RAM context is disposed before a separate real program runs
successfully with `x3=7` and positive counters. This is fresh-context recovery,
not reuse or repair of the failed context.

Boundary transport covers the thirteen Core selectors, three local-memory
selectors, `coalescer_miss`, `tcu_tbuf_stalls` and `tcu_tbuf_cache_hits`. The
**fourteen available but unseeded selectors** are the nine I/D-cache selectors,
`memory_reads`, `memory_writes`, `memory_lt`, `memory_bank_st` and
`tcu_lmem_reads`. The **twelve unavailable L2/L3 selectors** remain explicit and
are not queried as fabricated zeros. Seeded ordinary/checked equality is
transport and arithmetic evidence; it is not normal-workload cycle parity or
complete backing-source transport for all 33 available selectors.

### Execution bindings and limits

The original report records a clean source revision and matching before/after
source and tool snapshots. Both variants contain real records for all 44
compiled translation units, one link, effective macros/configuration,
compiler stamps, object identities and executable identities. Selected source,
dependency, generated-file, stamp, binary and log identities bind the recorded
execution. The actual executing Python interpreter is identified separately
from a Python resolved through `PATH`. These observations establish the
declared packet scope; they are not a complete system-dependency inventory or
protection against a malicious concurrent writer.

The native contract retains a 15 GiB free-disk reserve, a 4 GiB memory/RSS
budget, two build jobs, 16 MiB per log, 120 seconds per configure, 1,800 seconds
per build, 180 seconds per invocation and a 90-minute hosted job limit. Resource
monitoring uses polled budgets, not hard filesystem/memory quotas. Reported
sampled RSS can miss peaks between polls. Successful completion does not waive
these limits for future work.

## Host and dry-run provenance

The immutable governance command was:

```text
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

It ran from `/tmp/ai-gpu-checked-verify-53f4ad08c` at the local source revision
`53f4ad08c469a1cc73fa604249b302f9416055e0`, tree
`80553bb237af44b187dd6d18178e851cd6671ec8`. The outer process receipt records
exit zero, 1,648.962310 seconds, complete cleanup and sampled peak RSS
326,823,936 bytes. Source and actual interpreter identities are stable.
The [file index](local/governance-53f4ad08c/index.json) binds the unmodified
report and all three original command logs. It does not reclassify this host
suite as native execution.

The local native preflight found 4,310,839,296 free bytes and stopped before
launching a command. The dry-run packet is a separate, smaller host check:
actual configuration and compiler-stamp generation followed by prospective
build command parsing. Its generated configuration/header hashes describe
capture-time files because the original dry-run report did not record those
hashes. The [dry-run index](local/dry-run/index.json) distinguishes these from
original report-bound source, stamp and log identities. The explicit
`ubuntu/focal` generation label on the local Debian host is not Ubuntu native
execution evidence. Neither packet relaxes the formal native reserve.

The controlled public tests compile the actual SimX backend, command
processor, common runtime, device, queue, event and public MPM code with
controlled Processor/RAM substitutes. They check real typed counter
overflow/underflow/negative-operand faults, persistent rejection, event waits,
queue-error consumption, suppressed work, cleanup and a fresh context in RAM
and LLC configurations. A synchronous public query fault preserves the
caller's output and prevents later processor reentry. The query aggregate is
a controlled local addition at the DCR hook, not an actual cache/TCU native
backing-source reduction. O2/NDEBUG, warnings as errors and UBSan are retained
in this host test route. These checks complement the real Core native cell;
they do not supply the missing native public-runtime integration.

## Independent reviews

These are retained source-review records, with their own exact scope and
identities. A reviewer recommendation is distinct from an execution receipt.

| Record | Scope and disposition |
|---|---|
| [Source and arithmetic review](reviews/source-proof-review.md) | Three independent reviews of the typed guard, all 33 selected storage/update paths and formed aggregates; bounded landing recommendation, with aggregate-lifetime obligations explicit |
| [Execution-path review](reviews/execution-path-review.md) | Independent runner/workflow/interpreter-binding, native-harness and host-test reviews; their reviewers did not execute native cells |
| [Integrated R3 review](reviews/integrated-review.md) | LAND the bounded implementation and CI-enabling checkpoint; reviewed before hosted execution and did not assert its success |
| [Public fault review](reviews/public-fault-review.md) | Independent review of additive controlled public-error-transport tests; native model and public fault injection remain separate |
| [Original native review](reviews/native-review.md) | Two independent reviews verify actual five-cell behavior, source/build binding and original log integrity; no F1/F2/F3 within assigned scopes |
| [Immutable governance review](reviews/governance-review.md) | Completed 3,043-test original local receipt and exact execution identity |
| [Local integrity review](reviews/local-integrity-review.md) | Independent byte comparisons of governance/dry-run/preflight originals and exact publication tree mappings |
| [Publication provenance review](reviews/publication-provenance-review.md) | Identical local/published trees and preserved upstream ancestry, without relabeling execution |
| [Final integrated review](reviews/final-integrated-review.md) | Fresh independent R3-depth review of every changed production/test/CI file; LAND the bounded checkpoint with no unresolved F1/F2/F3 |
| [Final documentation review](reviews/final-documentation-review.md) | Corrected native status, semantic links, canonical next action and explicit qualification boundaries |
| [Final hosted review](reviews/hosted-governance-review.md) | Original actual 3,062-test hosted governance log, final native-summary consistency and scoped broader-CI status |
| [Agent ledger review](reviews/agent-ledger-review.md) | Sixty unique assignments in ten waves, actual final-agent presence and explicit live-registry/history limits |
| [Final release review](reviews/release-review.md) | Final source/evidence/documentation check and fresh leased non-force publication requirements; no open F1/F2/F3 |
| [Historical primitive review](reviews/primitive-review.md) | Initial fatal-abort candidate only; superseded and not evidence for the replacement's completion behavior |
| [Completion-alignment review](reviews/completion-alignment-review.md) | Rejected the abort route after upstream completion changes; required the typed terminal-failure correction and fresh review |

The [original native review](reviews/native-review.md) independently verifies
all five output records, fifteen command logs, 264 retained source files and
both actual 44-translation-unit builds. The reviewers inspected original bytes
and source control flow; they did not infer coverage from report booleans or
the workflow conclusion. The [governance receipt review](reviews/governance-review.md)
and [publication provenance review](reviews/publication-provenance-review.md)
separately establish their exact local execution and tree-mapping scopes.

The [completed agent ledger](agents.json) records **60 distinct agents across
ten waves, six assignments per wave**. Every assignment has an actual final
report and completed status. The root reconciled completion after receiving
the sixtieth report; this is actual work recorded in the task/final-message
history, not the requested count or a claim of sixty simultaneous live agents.
The [ledger review](reviews/agent-ledger-review.md) preserves its earlier
in-progress snapshot and the live registry's historical-enumeration limit.

## Publication identities

The [publication receipt](publication.json) records non-force publication after
integrating upstream `89aa43236038fcfff5d36a7cdb95646b038fe2fb` and preserves
the original local history as `audit/local-checked-counters-713e05d99`.

| Local checkpoint | Published commit with identical tree | Tree |
|---|---|---|
| `53f4ad08c469a1cc73fa604249b302f9416055e0` | `a9227933c340fd44e73deaffafdd353fecf65492` | `80553bb237af44b187dd6d18178e851cd6671ec8` |
| `713e05d99f8b37d4370f7607d1f8129d40cde73b` | `9fd7eac203c77fa54c7af80fa0220ae09553cd55` | `973fa9a286686990c96d10f95ab2e77ed6328f1a` |

Identical trees establish identical repository file bytes, not identical commit
metadata or another execution. The local governance and dry-run receipts keep
their actual local revision. Hosted native execution names its actual published
revision. The publication receipt records the completed initial native run and
its completed independent packet review; the original native report supplies
the execution result without changing earlier local blocked receipts.

## Remaining development gates

Checked primitives reject invalid operations before their own mutation.
Checked readout sums reject an unrepresentable sum when it is formed. A sum of
independently changing components can nevertheless exceed `UINT64_MAX` between
observations while every component still fits. Qualification must prove a
continuous aggregate bound, or prove monotonic components through a successful
terminal quiescent all-selector observation and that no update follows it.
The proof must cover initialization, primes, measured work, close and relevant
teardown, with exact source/ownership/topology/dependency bindings. Assignment,
reset, narrowing or pre-wrapped arguments require source review beyond the
primitive's arithmetic guarantee.

The next bounded work is to close that lifetime/source proof, extend real
backing-source native transport to all 33 available selectors, and exercise
actual public native wait/query counter faults and serial coherent observation.
Then a separately versioned qualification reader and a complete fresh matched
warm experiment can be reviewed. Both policies must use the same instrumented
binary within each format; instrumentation cost is not an uninstrumented
speedup claim.

The [frozen warm-v1 contract](../../../designs/warm_workspace_benchmark_v1.md)
retains unconditional `P06-WARM-RV64-MPM-HIGH-HALF`, `qualified=false` and
`absolute_no_wrap_bound="not_established"`. Historical runs cannot acquire
missing bits or new source guarantees retroactively. P06/T01 remain
`in_progress`; P06-A02/A03 remain open. No RTL, physical FPGA/silicon, vendor
XRT `hw_emu`, tensor DSP-budget or unrelated phase obligation is closed by
this checked-counter prerequisite.
