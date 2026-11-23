# Native managed counter lifetime observations

The pending-read and per-run/reset observation increment is implemented at
[`b4127b19a004b5aebb8d52eab9ceda0da3ff4561`](https://github.com/baabi-boo/AI-GPU/commit/b4127b19a004b5aebb8d52eab9ceda0da3ff4561).
[Native run 45130300651, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45130300651)
passed the four-process matrix and the separate accessor/control probe.
Independent reviews reproduce every process observation from the original raw
logs and reconcile the build, product, ownership and destruction records.

The [development audit](development-audit.md) records why this prerequisite was
selected. The [versioned contract](../../../designs/managed_counter_lifetime_v1.md)
defines the implemented observations. The next bounded action is the
[dependency provenance handoff](../../p06-dependency-provenance-handoff.md).

## What changed

`Processor::pending_mem_reads() const` observes the actual owned pending balance.
The explicitly selected lifetime wrapper records all 33 real run boundary pairs,
every raw counter and output-flush read, four snapshots, construction and actual
destructor entry. It rejects outstanding reads before the real run can reset
that balance and requires exactly one reset per run. After destruction, it
inspects only the still-live platform.

The new `P06_MANAGED_COUNTER_LIFETIME` record follows the entire original v1
transcript. Its reader first validates the byte-preserved v1 prefix, then the
additional pending/reset observations and chronological joins. Default v1
emission and historical replay retain their original contracts. A successful
void `run_checked()` call may leave a nonzero architectural `gp`; exceptions and
public completion failures are handled separately.

## Original native result

The [aggregate original review](reviews/w08_a01.md) independently recomputes:

| Population | Verified original total |
| --- | ---: |
| FP16/BF16 × allocation-policy processes | 4 |
| Native launches | 132 |
| Exact FP32 result words | 4,224 |
| Numerical mismatches | 0 |
| Run/reset boundary pairs | 132 |
| Exact zero-pending observations | 2,680 |
| Snapshots | 16 |
| Available counter queries | 528 |
| MPM half replies | 1,056 |
| Output-flush reads | 132 |
| Total DCR reads | 1,188 |
| Unavailable rows, without queries | 192 |

Each process records reset generations 1 through 34, with snapshot generations
`[1, 2, 34, 34]`. The terminal live model has 194,112 core cycles, 16,797 retired
instructions, 5,900 platform ticks and zero pending reads. Its after-batch,
before-release and actual destructor-entry states agree. Completed disposal
leaves the platform idle, ticks zero and reset generation 34. Terminal ownership
is one device reference with no queues or buffers; the enabled, error-free
command processor retires exactly 66 final counter queries.

The process-specific reviews are
[FP16 per operation](reviews/w07_a01.md),
[FP16 reusable](reviews/w07_a02.md),
[BF16 per operation](reviews/w07_a03.md), and
[BF16 reusable](reviews/w07_a04.md).
Each verifies 33 launches and 1,056 exact words, reconstructs canonical numerical
expectations, recomputes its identities and reproduces both retained observations.
The reusable policies also retain stable tensor addresses and balanced releases.

## Separate accessor and control probe

The [probe original review](reviews/w07_a05.md) verifies two successful native
contexts with architectural `gp` values 7 and −1. Each records 135 steps,
23 samples with outstanding reads, maximum pending balance 1, 137 read-only
observation groups and final pending balance zero. Each stepped and checked run
increments reset generation once.

Both separate probe executables compiled successfully. The native probe exits
0. The always-zero control exits 1 for the exact required behavioral assertion:

```text
FAILED pending_reads native_probe: pending getter did not observe an outstanding read
```

Static ELF inspection confirms that the native executable imports the actual
getter, the model exports it, and the always-zero executable has no getter
reference. The mutation is confined to the separate probe translation unit.
These probe operations are outside the four managed processes and 132 launches.

## Build, identity and retention

The [envelope review](reviews/w06_a03.md) verifies the original archive against
GitHub metadata, all 1,264 members, clean source identity, workflow, preparation
and interpreter observations. The [build review](reviews/w07_a06.md) validates
both exact 46-command backend graphs, including 43 guarded model translation
units per format, and both complete 30-command application graphs. Generated
headers, four independent compiler roles, build bindings, final product bytes
and actual loaded-library paths join.

The complete application-graph validator already exists in the trusted inert
reader and includes the exact 14-source runtime-stub compile/link command.
The live producer currently validates and binds the final host command; the
next provenance task will reuse and integrate that existing full-graph validator.
Three dependency products remain reused inputs with unresolved fresh compilation
origins. Individual model object and compiler-executable bytes are not retained;
their recorded identities are distinguished from rehashed retained final products.

All 35 managed command receipts pass, with no omitted, retried or replacement
native process. All 76 required stability checkpoints agree. The maximum sampled
command RSS was 887,721,984 bytes. The original preserves two build jobs, one
simulation worker, 15 GiB disk reserve, 4 GiB RSS and bounded command limits,
together with the monitor's polling limitations.

Durable original files:

- [Original GitHub artifact ZIP](native/b4127b19-run45130300651-attempt1/original.zip)
- [Artifact metadata](native/b4127b19-run45130300651-attempt1/artifact-metadata.json)
- [Original workflow job log](native/b4127b19-run45130300651-attempt1/job-original.log)
- [Complete member inventory](native/b4127b19-run45130300651-attempt1/member-inventory.json)

Artifact 14798140556 is exactly 9,086,055 bytes, with SHA-256:

```text
3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3
```

The ZIP expands to 37,138,100 bytes. Original files remain unchanged inside it.
Review scripts and receipts under `original-review/` are derived evidence; their
recorded absolute paths identify the environment where review ran. Review used
trusted committed validators and treated archived code, commands and binaries
as data. No retained program was executed during review.

From the repository root, the [portable integrity check](original-review/w08_a03-portable-verify.py)
verifies the ZIP and every member without extracting files or executing archive
contents:

```sh
python3 -I docs/project/evidence/p06-native-lifetime/original-review/w08_a03-portable-verify.py
```

This repeats byte-integrity verification. The process and build reviews above
provide the separately scoped semantic validation.

## Host checks, compatibility and governance

| Evidence | Exact scope and result |
| --- | --- |
| [Integrated host run](host-controls/focused-integration.json) | 90 methods passed in 72.205 seconds; six lifetime/default runner modules, with source stability retained |
| [Probe host tests](host-controls/w03_a06-tests.log) | 30 methods passed in 15.991 seconds, including the repaired JSON suffix-injection rejection; external native execution is mocked |
| [Final-format hook rerun](host-controls/w04_a03.json) | 11 methods / 38 fresh controlled processes passed with strict C++17 warnings and UBSan; repeated coverage within the 120 distinct methods |
| [Compiled parent sensitivity](host-controls/w04_a03-parent-control/report.json) | Both variants compile; parent enters the reset-bearing call and fails the exact pre-reset assertion, candidate rejects before entering and passes |
| [Coverage audit](reviews/w08_a02.md) | All 80 newly added methods are discoverable without skips or expected failures; existing test modules are unchanged |
| [Current default/replay compatibility](reviews/w06_a04.md) | Default v1 native run 45130300249 passes 4/132/4,224; replay run 45130300109 passes 203 tests in 273.807 seconds and preserves the original failed archive's `report.outcome` rejection |
| [Full hosted governance original](ci/b4127b19-full-governance-original.log) and [independent final review](reviews/w10_a03.md) | Run [45130300117](https://github.com/baabi-boo/AI-GPU/actions/runs/45130300117) at `b4127b19` passes 3,813 unique methods in 2,498.078 seconds; all 80 new methods pass once, with no skips or expected failures |

The [implementation push checkpoint](ci/b4127b19-push-ci-checkpoint.json)
records 13 of 14 workflows completed successfully. Generic CI has 41 of 42 jobs
passing; its RV32 regression job is still running at that recorded checkpoint.
That pending outcome is kept separate from completed governance and native
execution. The [final integration receipt](final-integration.json) records the
completed report-ledger verification, documentation scope, navigation, published-baseline
consistency and authored-content checks.

Supplemental syntax, extracted-emitter, arithmetic-boundary and malformed-input
checks retain their individual commands and scopes. Inert review assertions,
collection-only checks and repeated methods are not added to native or unit-test
method totals. The [sensitivity review](reviews/w06_a01.md) reconciles the 120
distinct focused methods as 80 new and 40 existing methods. All 120 are a
subset of the completed 3,813-method governance suite and are counted once.

## Collaboration and final review

The [completed execution ledger](agent-execution.json) records **60 distinct
agents across ten logical waves, six completed assignments per wave**. Each
entry names the actual delegated task and binds its retained report by SHA-256
and byte count. The 60 report files total 532,326 bytes. Root work, follow-up
messages, repeated checks and test scenarios are excluded from this count.
The [final ledger audit](reviews/w10_a06.md) reconciles that accounting.

| Wave | Six completed assignment areas |
| --- | --- |
| 1 | Processor, witness, reader, build/test, CI/provenance and priority audit |
| 2 | Contract, accessor, runner/workflow, hooks, reader and native probe |
| 3 | Compiled controls, rejection tests, runner tests, reader review, replay and probe review |
| 4 | SimX, trust boundary, fixture repair, probe builds, emitter/CLI and workflow review |
| 5 | Component lifetime, ownership, dependency plan, build projection, freeze and reset ordering |
| 6 | Sensitivity, adversarial boundaries, native envelope, CI, protected gates and claims |
| 7 | Four original native processes, separate probe and build bindings |
| 8 | Aggregate original, governance coverage, durable retention, next handoff, code and current docs |
| 9 | Qualification boundary, source projection, navigation, compatibility, ledger and manifest |
| 10 | Final code range, packet, completed governance, next step, Git publication and ledger |

The [final source/preservation review](reviews/w10_a01.md) confirms the unchanged
813 captured project inputs, protected trees, golden/acceptance data and all
40 prior evidence entries. The [publication review](reviews/w10_a05.md) binds
its prepared tree and requires an exact final local/API tree match before the
master ref moves. Its complete whitespace check records trailing spaces in six
byte-identical original logs; its check of the other changed files passes.
Original bytes remain intact. Final integration records captured diagnostics
separately from authored-content checks.

## Qualification boundary and continuation

All seven fields remain false: `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance`, and
`performance_acceptance`. The three existing obligations remain unchanged:

1. `all_40_component_lifetime_and_pending_balance`
2. `dependency_source_to_loaded_binary_provenance`
3. `independent_complete_counter_qualification`

The [40-component source map](reviews/w05_a01.md) and
[terminal ownership trace](reviews/w05_a02.md) supply reviewed premises.
Pending reads are separate transient state; each run pair directly observes two
core cumulative fields. Complete source/binary-bound lifetime qualification still
needs the dependency provenance chain and independent reconciliation.

P06 and P06-T01 remain `in_progress`; P06-A02/A03 remain open. The unchanged warm
gate, absolute no-wrap question, historical failed originals, RV64 area finding
and P01 vendor hardware-emulation blocker retain their prior scopes. This
continuation establishes the bounded native SimX observations. The
[current handoff](../../p06-dependency-provenance-handoff.md) specifies the next
fresh dependency source, compile, archive, link and loaded-product task.
