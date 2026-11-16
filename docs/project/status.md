# Current project status

**P02-T01 is complete and P02-A01 has reviewed source-level evidence.**
The [contract acceptance record](evidence/p02-numerics/acceptance.json) and
[numerical handoff](p02-numerics-handoff.md) cover the implemented contract,
98 independent arithmetic fixtures, 20 source layout fixtures and bounded
verification. P02 remains `in_progress`: A02's whole-processor arithmetic/layout
coverage and A03's WGMMA concurrency obligations remain pending.

P02 entered development through the user-directed staged-entry decision.
P01-A01 and P01-A02 are accepted, while P01 itself remains blocked on vendor
`hw_emu` (P01-A03). This blocks completion of P01 and acceptance of P07,
**not** the P02–P06 software/RTL development chain.
At the accepted historical revision, all six frozen numerical executions pass
from a clean GPU source checkout. The fresh generated FP16 SimX build and
supplemental full-AFU integer `xrtsim` smoke also pass. Independent reviews accept
the clean-build and native numerical packets. Qualified vendor tools/platform
are still missing for P01-A03. P00 remains complete, P02 is in progress,
and P03–P11 remain `not_started`.
[roadmap.json](roadmap.json) remains authoritative for phase state and evidence;
the linked reports define the exact accepted scope.

## Where the project stands

| Area | Current state | Meaning |
|---|---|---|
| P00 — project foundation | `complete` | Its three source-level acceptance gates and verified default-branch delivery remain preserved |
| P01 — reproducible baseline | `blocked` | A01 clean-build and A02 six-case numerical reports accepted; A03 vendor integration is still required before P07 |
| P02 — tensor numerical contract | `in_progress` | T01 complete; A01 source contract accepted; A02 full-processor arithmetic/layout and A03 WGMMA concurrency remain pending |
| P03–P11 | `not_started` | Later software, hardware and silicon gates have not been earned |
| Full vendor XRT `hw_emu` | `blocked` | Required vendor tools, identified platform and matching integration artifacts are unavailable |
| Physical FPGA / custom silicon | Not qualified | No physical board or fabricated silicon measurements are established |

Execution and integration owner for this continuation: the primary coding agent
(`/root`). Independent agent reviews supply scoped engineering evidence; they
are not invented human approvals or waivers.

## Latest continuation — P02 contract and executable fixtures

Formal validation used clean source
`a25321496d802f43830c1658487f1adf79c838c3`, tree
`7e459269e22f90691cf410e42068982f5a8c7a2d`. The
[evidence packet](evidence/p02-numerics/README.md) retains exact commands,
configuration, selected compiler-header identities, logs, source hashes,
independent reviews and failed attempts.

| Result | Demonstrated scope |
|---|---|
| 1,343 offline tests passed; zero failures, errors or skips | Project tooling, contract checks and host model-function tests |
| 98 native dense and the same 98 stalled fixtures passed, with 306 hold checks | Direct native TFR FEDP leaf, exact FP32 bits, without DPI arithmetic |
| 98 production-model fixtures passed | Host `TfrFedp` calls; no full SimX processor run |
| 47 actual RISC-V compiler cases passed: 17 positive, 30 intended rejections | Disabled-format and output-contract checks in both WMMA/WGMMA contexts, 94 context checks |
| Four existing FP16/BF16 WMMA/WGMMA kernel objects compiled | Compile-only integration; WGMMA uses explicit overrides outside the ordinary profile |

The runnable `p02-tfr` profile and 20 matrix-memory fixtures freeze the first
ordinary WMMA application geometry and layouts. The matrix fixture adapter and
their full-processor execution remain outstanding. Leaf enable stalls do not
establish WGMMA synchronization, metadata handling, multiple warps or backpressure.

The first clean candidate `135cfec14d1fed0b4e950bc243e69a91879e4275`
failed native harness compilation because raw profile enum flags did not supply
the resolved C++ selectors. The corrected Makefile uses the established resolved
flag path, and a real-profile regression preserves raw rejection guards. An
earlier dirty-source stall run exposed a shared Verilator-context lifecycle bug;
each DUT now owns its context. Both failures remain retained with their exact
provenance limits. Production arithmetic, inherited goldens and P01 evidence
were preserved. The [agent ledger](evidence/p02-numerics/agent-execution.json)
records collaboration separately from qualification.

## Preserved sequencing decision — staged numerical development entry

On 2026-11-16 the user directed an execution-sequencing change to avoid making
vendor-only tools a prerequisite for native AI software development. The
[machine-readable roadmap](roadmap.json) now permits P02 entry based on both
accepted P01-A01/A02 evidence records, with P00 complete. The governance
validator requires passing, compatible evidence for **every** named entry
acceptance before a phase may be `in_progress` or `complete`. A missing,
blocked or failed record will reject the transition. P02's existing three
acceptance obligations were unchanged and none was claimed accepted by that
entry decision. The later P02-A01 source result is recorded above.

**P01-A03 stays blocked and required.** P07 now also depends on full P01
completion, so an FPGA prototype cannot be declared complete without the
vendor integration result and later actual physical measurements. The
[staging handoff](p02-entry-handoff.md) records the next work, and
[ADR-004](decisions.md#adr-004--staged-native-development-entry-with-vendor-integration-retained)
records the decision. Historical evidence, failed attempts, vendor runbooks
and source-level numerical tolerances were not changed by this decision.

## Latest continuation — supplemental tensor-oracle hardening

The [tensor-oracle guide](p01-tensor-oracles.md) and
[evidence index](evidence/p01-tensor-oracles/README.md) describe this supplemental
P01 correction and retain each execution's exact source and configuration.

- Class-aware NaN/infinity handling and overflow-safe finite ULP distances prevent
  nonfinite mismatches and signed overflow from producing false comparisons.
- FEDP preserves the FP32 accumulator C bits; independent packed FP16/BF16
  fixtures check operand layout, accumulation and numerical edge cases.
- Integer references use modular 32-bit arithmetic. Strict CLI checks reject
  malformed, empty and disabled-format selections; seeded single-case replay
  consumes the same input stream as the corresponding full run.

Matrix/full-suite source: **`ca8686d668ed9f2ff733ce7e3c12dd458b9776d8`**. Native matrix: **pass — nine builds, 62 commands and 95 CLI checks**.
Full tooling suite: **1,272 tests passed, zero failures/errors/skips in 336.269 seconds**. The earlier `20ea50d` native-matrix
attempt failed during compilation on a GCC diagnostic; retain that failure
separately from later retries and the accepted historical baseline.

At that tensor-oracle execution checkpoint, P00 was `complete`, the historical
P01-A01/A02 reports were unchanged, P01-A03 was blocked, and P02–P11 were
`not_started`. Those checks do not complete P01 or qualify physical hardware;
the newer staged-entry decision is described above.

<a id="latest-continuation--supplemental-local-afurtl-qualification"></a>

The later host-only diagnostic correction at `a25ee6663e37d5fe28e7a6fd40b3857083ddeecc`
preserves nonzero-exit context when child output contains invalid UTF-8. All 12
tensor host groups and the actual malformed-output negative control pass there.
Native consumer/configuration hashes remain identical to the matrix source; the
nine-build matrix and full-suite results above retain their original revision.

## Earlier continuation — supplemental local AFU/RTL qualification

The [local qualification guide](p01-local-qualification.md) documents the
[bounded runner](../../ci/project/local_qualification.py) for real execution
through the XRT runtime, local `libxrtsim` shim and full AFU RTL, alongside
focused CP/LLC-port and AXI-arbiter RTL unit harnesses. Its fixed application
cases cover integer transfers/launch, cold and warm reopen, and reordered AXI
memory traffic; FP16/BF16 GEMM are explicit selections with the frozen P01
configurations and reference tolerances. Separate generated build trees and
retained source, tool, dependency and configuration identities bound each run.

The frozen source `7e4ac5851f1f71d292ed1802c3f92456d96faf8d` completed
**all eight selected cases and 32 monitored commands**, including both native
TFR FP16/BF16-to-FP32 GEMMs. The same source passed **1,260 tooling tests in
293.241 seconds**. It fixes the stencil application's advertised block-size
option, rejects zero geometry before device work, places child compiler
temporary files on the monitored build filesystem, and retains accurate
helper-drift and process-launch diagnostics. The
[qualification handoff](p01-local-qualification-handoff.md) and
[evidence index](evidence/p01-local-qualification/README.md) retain the exact
commands, finished packets, configuration reviews and failed attempts.

The subsequent source `143c69fe284bc2a1628721cf8a4237ac82d2547d` strengthens
the CP/LLC test oracle while preserving its six functions and all 37 original
assertions. Both affected unit selections pass in a **fresh five-command
packet**. Paired isolated mutation proofs detect three faults that the original
harness missed. That follow-up also raises the governance job timeout from five
to ten minutes with matching policy text; its focused CI guardrail test passes.
The full tooling suite and eight-case matrix were **not rerun at this later
revision**. The handoff retains source-to-GitHub mappings and points to
commit-scoped delivery and hosted CI checks.

The initial published-head governance run at `1b1bf572` then found one stale
test expectation: five minutes instead of the reviewed ten-minute job budget.
The exact one-line correction at local source `420937e` (GitHub `f269505c`)
passed the full 1,260-test tooling suite again in **257.346 seconds**, with
clean, unchanged source and completed cleanup. The
[separate CI follow-up](evidence/p01-local-qualification/ci-followup/README.md)
preserves the failed hosted run, correction review, fresh full-suite evidence
and source mapping. Native results retain their earlier revisions; the original
sealed archive and 60-agent ledger remain unchanged.

The local shim uses modeled host/device memory and retains DPI-assisted integer
multiply/divide. STD floating-point and TFR tensor claims are limited to each
retained configuration; local AFU/unit evidence does not qualify vendor
loading/platform semantics, physical cache coherence or physical hardware.
P00 remains `complete`, P01-A01/A02 retain their accepted historical reports,
P01-A03 remains blocked on vendor `hw_emu`, and P02–P11 remain `not_started`.

<a id="latest-tooling-continuation--compiler-records"></a>

## Earlier tooling continuation — compiler records

The shared [compiler-record validator](p01-compiler-records.md) resolves the
preparation planner's F1 glob ambiguity and the XRT execution inspector's
operand and record-aggregation gaps. It checks the runtime, kernel and host
compiler records independently, consumes option operands before crediting macro
definitions, requires the kernel's direct RV64 ISA/ABI selections, and preserves
the exact generated-runtime linker binding. Shell expansion syntax, unsupported
compiler transports and non-LF record separators cannot qualify a candidate.
The execution runner rejects invalid records before smoke launch and rejects
later configuration drift before recording success.

The clean implementation commit
**`f11190c87778ef049237650bbba4234ca62026b2`**, tree
`36335b94da7392e4c5fd24618d4ce85addbf2d20`, passed **1,120 tooling tests,
with zero failures, errors or skips**. The baseline at `9740532` passed 1,075
tests; the continuation adds 45 tests, including real compiler-preprocessor
oracles, actual Make-generated stamp compatibility, file-backed rejection cases,
runner failure handling and retained-helper provenance. The working tree was
clean before and after the full run, and all captured project Python source
hashes remained unchanged. The
[verification packet](evidence/p01-compiler-records/verification.json) retains
the exact commands, source identities and results; subsequent documentation and
publication records do not relabel that execution as a test of another revision.

The identical implementation tree is published on `master` as
[`623544c`](https://github.com/baabi-boo/AI-GPU/commit/623544cdd51f9c70a4e2fcef29ed3b56d8cce3fe);
the [publication map](evidence/p01-compiler-records/publication-map.json) retains
the original local commit bytes and exact remote tree/parent verification.

Use the [compiler-record handoff](p01-compiler-records-handoff.md) for review dispositions,
delivery state and the continuation's actual assignment record. This work
preserves the accepted numerical packets and establishes no new GPU, vendor
`hw_emu` or physical-device result. P01-A03 remains blocked and P02 remains
`not_started`; the next bounded action remains vendor/platform qualification.

The [completed execution ledger](p01-compiler-records-agent-execution.json)
records 60 distinct assignments in ten logical waves. Hosted
[Project Governance](https://github.com/baabi-boo/AI-GPU/actions/runs/43790120429)
also passed all 1,120 tests on the published implementation. Its
[observation](evidence/p01-compiler-records/code-ci-final.json) keeps the general
CI workflow's still-queued state separate from that successful result.

## Implemented P01 work

The [P01 runbook](p01-baseline-runbook.md) supplies the reproduction sequence.
The implementation contains:

- An immutable [toolchain lock](../../ci/project/p01_toolchain.lock.json) and
  [bootstrap](../../ci/project/baseline_bootstrap.py) for the minimal RV64 tool
  set, with verified archive identities, bounded extraction and install receipts.
- A [six-case matrix](../../ci/project/p01_baseline.json) and strict
  [loader](../../ci/project/baseline_matrix.py), preserving catalog provenance,
  dimensions, random seeds and inherited numerical tolerances.
- [Source/tool/build inventory](../../ci/project/baseline_inventory.py) and
  [bounded process execution](../../ci/project/baseline_process.py), retaining
  exact identities, logs, failures and resource-stop reasons.
- A [sequential runner](../../ci/project/baseline.py) with read-only planning,
  fresh output directories, atomic progress records, effective configuration
  checks and CPU-reference success-marker checks.
- Independent tooling tests for provenance, matrix integrity, shell-token
  rejection, resource limits, descendant cleanup, archive safety and failure
  retention. Passing these tests does not demonstrate GPU numerical correctness.

| Frozen workload | Dimensions | Observed SimX / processor RTL results |
|---|---|---|
| FP16 → FP32 GEMM | `M=N=K=64` | `pass` / `pass` |
| BF16 → FP32 GEMM | `M=N=K=64` | `pass` / `pass` |
| TF32 → FP32 attention | `N=32, D=16, c=8, t=8` | `pass` / `pass` |

Each pair explicitly selects **TFR tensor and STD scalar arithmetic**. SimX
remains a software model. Processor `rtlsim` and supplemental full-AFU `xrtsim`
remain distinct from vendor `hw_emu`, physical FPGA execution and silicon.
Attention uses SS operands for both GEMMs. The unused `WGMMA_RS` command macro
does not establish RS coverage; the [erratum](evidence/p01/attention-operand-erratum.md)
preserves and corrects the original matrix's descriptive error.

## Historical reviewed execution packet

The GPU source checkout is pinned to
**`03181532b81fe95b1cfeac2ffb25d8597af689b2`**, separately from the evolving
baseline tooling published at **`e9c9ac01f93b0d84915340999100260f2599ec44`**.
All six executing helper snapshots match that implementation commit. Source/tree,
recursive submodule and generated-build identities are retained. The toolchain
tag `v3.0.2` resolves to immutable commit
`e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`; the lock covers 18 archive parts,
**720,873,529 compressed bytes**.

| Observation | Outcome and boundary |
|---|---|
| Pinned source, recursive submodules and minimal RV64 tool provisioning | Prepared; inventory checks passed against the clean execution checkout |
| Memory-model dependencies, kernel library and host runtime | Built successfully; this does not prove a GPU workload result |
| Initial FP16 SimX attempt with GCC 14.2 | Failed during compilation of pinned spdlog/fmt with `-Werror=dangling-reference`, before the numerical workload ran; the failed command and log are retained |
| Dedicated GCC 11.3 compiler and completed numerical cases | Compiler smoke and all three paired workloads passed their CPU-reference checks |
| First FP16 processor-RTL build | Stopped because the supplied Verilator Makefile expected an absent `ccache` executable; the runner now explicitly sets `OBJCACHE=''`, and the bounded direct-compile retry passed. Both attempts are retained |
| Frozen six-case numerical matrix | [P01-A02 accepted](evidence/p01-native.json): all six cases pass; review reconciled 15 command logs, 18 configuration snapshots and 41 exported artifacts |
| Separate fresh generated-build smoke | [P01-A01 accepted](evidence/p01-build.json): fresh FP16 SimX generated build, five successful commands and zero reference errors; reused dependency libraries remain explicitly pinned |
| Supplemental full-AFU `xrtsim` smoke | [Pass](evidence/p01/xrtsim/report.json): four successful commands and all 16 integer reference points; vendor `hw_emu` remains a separate obligation |
| Historical source-root project/tooling checks | The reviewed baseline revision passed 346 tests and governance validation; this is not the current continuation's test count and does not certify numerical execution |
| Full vendor XRT `hw_emu` | Blocked by missing vendor tools/platform; no P01-A03 pass is claimed |
| Synthesis, physical FPGA and silicon qualification | Not performed by this baseline continuation |

The execution budget uses two compile workers, a 15 GiB free-disk reserve,
6 GiB sampled process-group RSS and bounded logs/time. Host available-memory
observations do not certify a cgroup limit; the execution environment does not
expose that limit. Keep this limitation in the packet.
The baseline's final [resource observation](evidence/p01/resource-observation.json)
records no budget stops, a highest sampled process-group RSS of **3,494,166,528 bytes
(about 3.25 GiB)**, and **53.48 GiB free disk** after all three packets completed.
Simulation durations and these host-resource measurements do not establish
physical accelerator performance.

The [historical packet](evidence/p01/history/README.md) retains failures and old
instrumentation with [raw-to-published hash mappings](evidence/p01/history-manifest.json).
The [implementation review](evidence/p01-review.md) records concrete findings,
independent corrections and acceptance reviews. The [P01 handoff](p01-handoff.md)
records the delivered scope and remaining vendor-integration obligation.

## Offline packet verification continuation

The published [offline packet verifier](p01-packet-verification.md) implements
P01-T06 evidence checks: original-byte verification, a separate unsigned
inventory, and an explicit published-export mode. It also adds a bounded
[CI consistency check](../../ci/project/check_baseline_packets.py) for the
retained native and clean-build exports. Run from the source root:

```sh
python3 ci/project/check_baseline_packets.py
python3 ci/project/baseline_packet.py verify-export docs/project/evidence/p01/native \
  --require-native-records
```

The [packet continuation handoff](p01-packet-handoff.md) records the initial
`e9c9ac0` checkpoint, incorporation of baseline delivery `25ca2e6`, and published
implementation [22c545c](https://github.com/baabi-boo/AI-GPU/commit/22c545c632628f9da9f18ccf8fb512a8bfac7f81).
That historical immutable release checkout passed all 591 governance/tooling
tests, the project checker, preflight and both published-packet checks. The handoff records
exact identities, independent review and hosted CI observations. This
continuation performed no new GPU execution and grants no new acceptance.
The six-case and clean-build evidence above remain the reviewed execution record;
P01-A01/A02 remain accepted and P01-A03 remains blocked. Published verification
checks public bytes and retained records, without proving original log bytes or
the asserted redaction relationship.

The separate [packet continuation ledger](p01-packet-agent-execution.json)
records that historical delivery's actual assignments and dispositions. The
original P00 and P01 execution ledgers remain separate historical records.

## Vendor hardware-emulation preparation

The [hw_emu runbook](p01-hwemu-runbook.md),
[manifest contract](p01-hwemu-manifest.md) and
[preparation handoff](p01-hwemu-handoff.md) describe the read-only P01-T05
preparation route. Its implemented source includes:

- Read-only [inventory and planning commands](../../ci/project/hwemu.py).
  Inventory reports local prerequisites without invoking vendor tools. Planning
  validates a strict inert manifest, file hashes and a matching retained receipt,
  clean source/submodule identities, existing generated-build copies and compiler
  records, lean XRT settings and bounded input/resource observations.
- The corrected XRT INI hook path, `sw/runtime/xrt/xsim.tcl`, with debug mode off
  and the inherited profiling/trace options disabled. Waveforms require explicit
  debug configuration plus
  `VORTEX_XRT_WAVEFORM=1`; the environment flag alone does not enable debug mode.

A successful plan establishes input consistency only. It retains
`launch_ready: false`, `vendor_qualification_verified: false`,
`execution_performed: false`, `phase_complete: false` and P01-A03
`acceptance_outcome: blocked`. The planner launches no workload and does not
enforce the candidate's execution budget. Actual vendor compatibility, artifact
production provenance and separately supervised execution still require review.
This continuation establishes no new GPU execution, vendor-emulation result or
physical measurement. P01-A01/A02 retain their accepted historical evidence;
P01-A03 remains blocked and P02 remains `not_started`.

## Vendor integration tooling continuation

The [vendor XRT runner](../../ci/project/xrt_baseline.py) now implements the
prepared-artifact P01-T05 route. Its [guide](p01-xrt-integration.md) defines the
fixed RV64 integer smoke, pinned platform/runtime/artifact manifest, reviewed
build receipt, fresh host/kernel build and tracing-disabled direct launch.
Independent tooling tests exercise blocked prerequisites, provenance drift,
configuration mismatches, process failures and reference-result handling.
The [continuation handoff](p01-xrt-handoff.md) records verification and delivery.
The [review record](p01-xrt-review.md) documents the corrected findings; the
separate [execution ledger](p01-xrt-agent-execution.json) records **60 completed
assignments in ten waves of six**, without counting or changing the historical
P00/P01 and concurrent preparation assignments.

The combined implementation at `ae27591d1e4b7c9f2ec802c75fd6556b95a0483b`
passed **1,075 tooling tests, with zero failures, errors or skips**. The
[merge verification packet](evidence/p01-xrt-merge/merge-verification.json)
retains the exact source identity, test log and immutable-base R2 classification.
The working tree was clean before and after that run, and all 92 recorded
selected source hashes stayed unchanged. Later documentation and delivery
records are separate from this tested source checkpoint. The original
[875-test packet](evidence/p01-xrt-tooling/verification.json) and intermediate
1,071-test result remain historical observations at their own revisions.
The [publication map](p01-xrt-publication-map.json) distinguishes these local
execution identities from API-created GitHub commits with identical trees;
the actual test runs are not relabelled as later executions.

The two tools have separate manifest, receipt and report schemas; their shared
`schema_version: 1` does not make inputs interchangeable. The XRT runner requires
its own independently reviewed manifest/receipt and a fresh build directory,
constructs fixed commands and does not consume a `hwemu.py` candidate. There is
no automatic adapter or promotion from a preparation plan to execution. The
later [compiler-record continuation](p01-compiler-records.md) resolves the
read-only planner's F1 compiler-glob follow-up and strengthens both inspectors.
That correction does not grant a preparation candidate launch readiness or
replace the execution runner's independent input review.

The current environment still lacks the vendor executables, vendor roots and
qualified platform/artifact packet. No vendor `hw_emu` job ran in this
continuation. Passing tooling tests or a read-only plan does not accept P01-A03;
all existing accepted native evidence and phase states remain unchanged.

## Next bounded action

**P02-T02: connect the frozen matrix fixtures to the existing WMMA regression
and execute them on matching full SimX and native processor RTL configurations.**
Implement explicit fixture selection and exact-bit output checking for both
formats; exercise compact layouts, tile boundaries and multi-instruction K
accumulation together with normal, edge and cancellation cases. Preserve the
reviewed v1 arithmetic rules and all inherited tolerances. Then qualify WGMMA
descriptor/metadata handling, synchronization, multiple warps and backpressure
with applicable model-parity evidence. Neither the leaf run nor kernel
compilation satisfies those remaining gates.
Follow the [P02 numerical handoff](p02-numerics-handoff.md),
[P02 phase guide](phases/p02-tensor.md), [backlog](backlog.md), and
[acceptance policy](acceptance.md).

**Parallel blocked hardware task:** P01-T05 still needs a qualified vendor
release/platform, matching prepared `hw_emu` artifact packet and actual reviewed
DMA/launch/completion smoke through the [vendor integration guide](p01-xrt-integration.md).
Do not spend money, install oversized vendor tooling, claim an A03 pass or close
P01 without the missing evidence. This work must be completed before P07.

## Preserved P00 history

P00 was authorized and merged through
[pull request 1](https://github.com/baabi-boo/AI-GPU/pull/1). The original source
baseline is `da55a516a48b49013724f697d3c12a48932b449f`; the reviewed source candidate
was `5a97e59ed95163c585106250194f816353d6ca4e`, tree
`9f65ae6e2bce7adeaec2432c11756510028c8bc0`. The reviewed PR head was
`bebef861742165db1d0d78352ac008b079a35fdd`, and the verified merge commit was
`106b01945d102eec169e68400b2cb8df985236cb`.

The [accepted delivery record](evidence/setup-accepted.json),
[merge observation](evidence/setup-merged.json),
[source validation](evidence/setup-validation.json),
[command log](evidence/setup-validation.log),
[independent review](evidence/setup-review.md),
[publication observation](evidence/setup-publication.json) and earlier
[blocked delivery record](evidence/setup-delivery.json) remain unchanged.
Their historical checks and workflow observations do not qualify P01.
The original [P00 agent ledger](agent-execution.json) records its 60 completed
assignments across 10 waves; it is not the ledger for this P01 continuation.
The separate historical [P01 ledger](p01-agent-execution.json) records the baseline
delivery's completed assignments. Neither historical ledger counts the current
hardware-emulation preparation; requested totals do not establish completion or
hardware evidence.
The protected README illustration, upstream attribution and inherited golden
results remain preserved; see the [baseline inventory](baseline.md).

## Required handoff for every continuation

Read [AGENTS.md](../../AGENTS.md), this page and the canonical roadmap against
the current checkout. Use the [handoff template](handoff.example.md) to record
exact changes, tested source/tooling identities, commands, results, not-runs,
review findings, publication state and one next bounded action. Update status
and phase evidence together. Preserve failures and never convert missing native
or integration evidence into a passing gate.

## Preserved baseline collaboration history

The historical [P01 execution ledger](p01-agent-execution.json) records **60 completed
distinct agent assignments across 10 logical waves**, scheduled with at most three
subagents active concurrently for the accepted baseline delivery. It does not
count assignments in later hardware-emulation or local-qualification continuations. The original
P00 ledger remains unchanged. The completed historical assignments support that
implementation and review; vendor A03 remains blocked independently of agent count.
