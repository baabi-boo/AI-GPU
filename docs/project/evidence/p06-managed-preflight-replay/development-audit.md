# Managed preflight replay: development audit

## Decision and source scope

The next bounded development step at source
`57248e73dfce4ae2d21d2cbdb82c3953eef2e3db` was a complete, reusable **inert reader
for the managed counter preflight archive**. The producer had already emitted
a successful four-process original, while the repository had no complete
managed-preflight reader joining that archive to independently selected source
expectations. Building this reader makes the existing evidence inspectable and
repeatable before it is used as a prerequisite for future counter qualification.
It does not supply missing native observations or admit a performance attempt.

This audit reviews the working implementation descended from that source. Its
source inspection and protected-file comparisons were performed by
`/root/w05_a02_development_audit`; code and test authorship belong to the
individual [agent reports](agents/). Publication and final verification belong
to the coordinator's release evidence. This document does not assert a final
commit identity, a completed 60-agent count, a hosted CI pass, or approval of
unreviewed enforcement changes.

The [implemented replay contract](../../../designs/managed_counter_preflight_replay_v1.md)
defines the reader's interface. The original
[preflight contract](../../../designs/managed_counter_preflight_v1.md),
[qualification plan](../../p06-mpm-qualification-plan.md), and
[conditional lifetime argument](../../../designs/simx_counter_lifetime_v1.md)
retain their separate responsibilities.

## Why this work comes before qualification

The earlier diagnostic work establishes substantial, separately scoped evidence:
checked counter operations, all-33-selector transport, source access to all 40
backing components, and directed public runtime fault behavior. The managed
preflight then exercises the actual seed-free caller across FP16/BF16 and both
allocation policies. A producer result alone still leaves a review bottleneck:
source snapshots, build records, loaded-library observations and lifecycle data
must be recomputed and connected by a reader whose expectations are supplied
outside the archive. The [wave 1 qualification audit](agents/w01_a03.md) identified
that missing connection.

The successful original is [run 45085300171, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45085300171),
job `137402429866`, artifact `14779276315`, at the source above. Its
[retained ZIP](../p06-managed-preflight/native/run-45085300171-attempt1.zip) has
SHA-256 `cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d`.
The [original audit](agents/w01_a04.md) and
[intake record](../p06-managed-preflight/native/run-45085300171-intake.json)
retain the identity and observed population. Replay of these bytes is a new
verification operation, not a new native run.

| Original population | Retained count and meaning |
| --- | --- |
| Managed processes | Four: FP16/BF16 × per-operation/reusable-single-tile allocation |
| Operations | 33 per process, including each prime; 132 launches in total |
| Exact output checks | 4,224 FP32 words against the unchanged independent fixture |
| Counter observations | 16 snapshots, 528 available-selector queries and 1,056 half replies |
| Output flush observations | 132 replies, for 1,188 total DCR replies with the counter halves |
| Explicitly unavailable selector rows | 192 across all snapshots; no query is permitted |
| Actual processor lifetimes | Four constructions and four completed destructions |
| Retained source descriptors | 999: 806 first-party and 193 dependency headers |

The failed [run 45084009157 original](../p06-managed-preflight/native/run-45084009157-attempt1.zip)
remains a negative control. Its host compiler selection failed before native
managed execution. The new CI harness requires the exact `report.outcome: value
differs` rejection; an unrelated CLI failure, missing input or arbitrary
nonzero exit cannot masquerade as successful negative coverage. See the
[CI review](agents/w04_a05.md).

## What the implementation adds

The [reader](../../../../ci/project/p06_managed_preflight_replay.py), especially
`replay_archive` and `_Replay.run`, accepts explicit archive identity, source
revision, source inventory and derivation receipt identities. It compares every
retained source body to the selected inventory and binds the separate derivation
receipt to those bytes, checkout metadata and Git blob identities. The
[exporter](../../../../ci/project/p06_managed_preflight_source_export.py)
uses bounded, read-only Git-object queries over five explicitly selected
repositories. It does not discover expectations by trusting the archive or by
executing its source. The [independent source review](agents/w04_a04.md)
reproduced both successful- and failed-original manifests and derivation receipts.

The reader connects the report to the exact contract, numerical corpus, 35
command envelopes, source/tool/dependency stability, both format builds, all
four process outputs and the full hosted envelope. Build checks reconstruct
compiler roles and common bindings, compare generated and copied files across
configured/backend/frozen stages, hash retained payload bytes, and connect
those identities to recorded loader observations. Complete inventory checks
reject extra or unaccounted members. Producer paths remain lexical data, and
retained commands, modules and binaries are not executed. These boundaries are
exercised by the [archive isolation review and tests](agents/w03_a06.md).

Three concrete consistency gaps were closed during implementation and review:

| Gap | Implemented check and practical consequence |
| --- | --- |
| A final application host link did not establish the full preceding application build. | The [application validator](../../../../ci/project/p06_managed_preflight_application_build.py) requires the complete 30-command graph per format and binds the contributing recipes. It verifies kernel/startup/archive/vxbin/stub/host steps, tools, flags and prerequisites. [Independent review](agents/w04_a02.md) exercises same-record shell syntax mutations. |
| Coherently changing all retained generated copies could evade cross-copy checks. | The [generated-input validator](../../../../ci/project/p06_managed_preflight_generated.py) reproduces all four headers and the effective compiler flags from exact current trusted generator and configuration bytes. A retained `VX_DCR_DATA_BITS` change from 32 to 64 is rejected even after descriptor and binding repair. [Independent review](agents/w04_a01.md) also checks hostile bytecode and altered generator inputs. |
| The historical backend parser ignored unrelated commands and did not close the entire build order. | The [backend validator](../../../../ci/project/p06_managed_preflight_backend_build.py) requires exactly 46 records: recursive make, 43 model compiles, model link, then backend link. Independent compiles may be permuted; missing/extra records and links preceding prerequisites reject. The [author's review and regression report](agents/w04_a03.md) distinguishes this repair from its required independent peer review. |

These are validation changes. No native model, runtime, kernel, RTL datapath or
numerical golden was changed by this implementation at the audited working tree.

## What a replay pass still does not establish

The reader verifies the consistency of supplied records and retained bytes. It
cannot turn a consistently fabricated packet into authenticated execution. The
archive and source digests must be obtained independently; a record naming
GitHub is not itself GitHub authentication. Current trusted source identities
and before/after stability checks also do not establish freedom from malicious
concurrent host modification. The reader's own `LIMITATIONS` is authoritative
for these boundaries.

Each format has 75 frozen artifact descriptors, including **43 model object
identities whose bodies were not retained**. Their names and identities can be
reconciled with build records, but the reader cannot hash absent object bodies.
The retained payload population is separately checked: 17 files totaling
13,315,886 bytes, comprising seven format-specific payloads per format and three
shared dependency products. The [build review](agents/w04_a03.md) records the
object-body limitation explicitly.

Source membership, compiler command consistency and loaded-library hashes do
not prove that cached dependencies were compiled from the selected sources.
The current source export covers selected inputs and headers, not the complete
transitive dependency compilation closure. Tool identities likewise do not
retain every compiler support file, system header or system library. The hosted
dependency-installation log is retained and hashed; it is not a verified semantic
build attestation. See the [dependency audit](agents/w01_a02.md) and
[hosted reader](../../../../ci/project/p06_managed_preflight_replay_hosted.py).

All seven contract fields remain exactly false:
`qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
`acceptance_claimed`, `phase_acceptance`, and `performance_acceptance`.
The three unresolved obligations remain
`all_40_component_lifetime_and_pending_balance`,
`dependency_source_to_loaded_binary_provenance`, and
`independent_complete_counter_qualification`. These are enforced by the
[preflight contract](../../../../ci/project/p06_managed_preflight_contract.py)
and the complete reader. They are not recommendations that a favorable numerical
or timing result can override.

## Next bounded native step: observe pending balance and every run boundary

The strongest next lead is a **separately versioned native lifetime witness**
for the actual managed caller. The source inspection identifies a specific
missing observable:

- `ProcessorImpl::perf_mem_pending_reads_` is incremented for read requests and
  decremented for replies. `run()` and `cycle()` add its value to cumulative
  memory latency. `ProcessorImpl::reset()` clears it. See
  [processor storage](../../../../sim/simx/processor_impl.h) and
  [updates/reset](../../../../sim/simx/processor.cpp).
- The current preflight `ModelState` has live/idle/running, generation, tick,
  reset-generation, core cycle/instruction and exit status fields, but no pending
  read balance. `model_locked` fills that structure. The wrapped `run_checked`
  counts successful entries/completions and exceptions without retaining a
  before/after record for every run. See
  [hooks.h](../../../../tests/regression/ai_counter_preflight/hooks.h) and
  [hooks.cpp](../../../../tests/regression/ai_counter_preflight/hooks.cpp).
- The current reader checks snapshot and flush chronology, including bounded
  reset generations, but a four-snapshot record cannot supply the missing
  pending balance and exact reset history for all 33 operations. See
  `_snapshots` and `_cache_flushes` in the
  [record validator](../../../../ci/project/p06_managed_preflight_records.py).

Implement a read-only pending-balance observation on the admitted processor
route, with a versioned witness recording all 33 run/reset boundary pairs.
Require zero pending balance before each permitted reset, after successful runs
and required flushes, at the terminal vector and immediately before destruction.
Record exact reset progression, successful execution, actual final ownership and
completed disposal. Retain failure controls for nonzero balance, lost or repeated
boundaries, excess resets, incomplete cleanup and post-terminal activity. Keep
the observed accessor separate from diagnostic seeding and respect the
[SimObject channel rule](../../../designs/simobject.md#the-cardinal-rule);
this is a read-only host observation proposal, not authority for modules to reach
across ownership boundaries to modify one another.

The [conditional theorem](../../../designs/simx_counter_lifetime_v1.md) explains
why this is more precise than adding an unstructured 40-field inspector. There
are 33 available aggregates over 40 backing components: 26 single-component
and seven two-component aggregates. If the source-bound components start at
zero, remain nonnegative and monotone through checked updates and allowed
resets, and every terminal checked aggregate succeeds, each earlier aggregate
is bounded by the terminal value and `2^64 - 1`. The theorem additionally needs
stable storage through final destruction. Pending reads are a separate transient
balance, decremented on replies and cleared on reset; they are not one of the 40
monotone components. Their reconciliation cannot be inferred from small terminal
counter values or a successful public wait.

The actual route must continue to bind RV64 timing SimX, checked counters,
`p02-tfr`, the selected one-core topology, one simulation worker and exclusive
host submission. VM, L2, L3 and WGMMA remain disabled for this argument. The
unchanged source proof also requires CP/queue ownership, final references,
completed flushes, terminal counter reads before CP disable, no later ticks or
selected-counter updates, and the actual loaded dependency finalizers. Adding
the proposed witness alone does not establish every one of these premises.

## Separate dependency and admission work

Fresh source-to-product receipts must follow the loaded dependency chain before
complete qualification. The selected products are the static SoftFloat archive
and the Ramulator core/extension shared libraries. SoftFloat's contribution must
be connected through the static model link; the dynamic Ramulator products must
be connected to the exact loaded bytes. Retain complete selected source graphs,
configure/compile/link commands, relevant tool identities, product bytes and
load observations. The generated runtime/model libraries belong in the same
binding, rather than being represented only by their names.

The [dependency Makefile](../../../../third_party/Makefile) invokes nested
`make -j4` for Ramulator. A future fresh-build task must budget that subprocess
parallelism explicitly; a top-level worker limit does not alone bound it. That
future task also needs the project's native disk/memory preflight and an
independent review of source projection from the diagnostic/lifetime premises
to the actual seed-free measurement build.

Only after those observations, provenance and an independently reviewed pure
qualification validator are available should a new contract admit a fresh full
warm attempt. Preserve the frozen population and analysis rules: 24 processes,
792 launches and 25,344 checked words. The current four-process replay supplies
no full-warm coverage or speedup claim. The historical warm-v1 function
`_full_hypothesis_qualification` in
[p06_warm_analyze.py](../../../../ci/project/p06_warm_analyze.py) remains
unconditionally blocked by `P06-WARM-RV64-MPM-HIGH-HALF`, with
`absolute_no_wrap_bound="not_established"`. A repaired transport implementation
cannot reconstruct the missing high bits of a historical archive.

## Project state and protected boundaries

The authoritative [roadmap](../../roadmap.json) still records P06 and P06-T01
in progress, with P06-A01 accepted at its existing simulated scope and A02/A03
open. P05-A01 remains accepted within its own binding scope; P05-A02/A03 are
unearned. P01 remains blocked on vendor XRT hardware emulation, and P07–P11
remain not started. No physical FPGA or silicon evidence is supplied by this
work. The earlier RV64 area/DSP regression retains its own disposition; a
reader improvement cannot repair or waive it.

At this audit's working tree, `git diff` against the base showed no change in
`sim/`, `sw/`, `hw/`, `ci/baselines/` or the frozen P04 model manifest. Direct
byte comparisons also confirmed these protected identities:

| File | SHA-256, unchanged from the source base |
| --- | --- |
| `ci/project/p06_warm_contract.json` | `893d85401b1d5f7757d82cb7c743a89b36264fe19c7d08c239b7f216b7a8cbbd` |
| `ci/project/p06_warm_analyze.py` | `ac273f587f759900d16ad41c7c63c2d2b10ca0864d5018f8403572f75e5a3e88` |
| `docs/assets/img/vortex_framework_stack.svg` | `db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4` |
| `docs/project/roadmap.json` | `c3409db37618927f585a590031e0fd50205d650d79b7750ea09ffb53475e5b18` |

The separate governance timeout change has its own
[baseline cancellation record](hosted/baseline-57248-governance.json) and
[CI review](agents/w04_a05.md). The baseline's approximately 40-minute elapsed
run is consistent with the former timeout, but that timing is an inference
about cancellation cause, not a completed-suite result. Final hosted and full
suite outcomes must be recorded against their actual tested source.

## Audit provenance

The wave 1 reports were reconstructed from their completed agents' recorded
handoffs after a temporary workspace restart; each says so explicitly. They
are not presented as byte-identical recovered files or fresh test executions.
This audit additionally inspected the current source symbols named above,
canonical phase metadata, the qualification/lifetime contracts, and current
implementation/review records. It ran read-only Git comparisons and Markdown
link checks, not a native build, a unit suite or a new original-artifact replay.
The audit does not replace the independent enforcement review required before
publication.
