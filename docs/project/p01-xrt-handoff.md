# P01 vendor XRT integration handoff

## Scope, identity and disposition

This continuation implements the prepared-artifact runner for **P01-T05 /
P01-A03** and preserves the concurrent read-only vendor-preparation route.
The latest exact integration passed **1,075 tooling tests with zero failures,
errors or skips**. The original 875-test runner result and first combined
1,071-test result remain separately identified historical checkpoints.
No qualified vendor `hw_emu` build or smoke ran. **P01-A01/A02 remain accepted,
P01-A03 and P01 remain blocked, and P02 remains not started.** The
[roadmap](roadmap.json) and existing acceptance reports remain authoritative.

| Source identity | Recorded value |
|---|---|
| Repository and authorized target | `baabi-boo/AI-GPU`, `master` |
| Shared starting revision | `91b82fe300f94ab0a70dd0e0e4a69a0e23b16101` |
| Original tested XRT implementation | `42e36724a2f2a02766b26de8deb9b04b7557fa27` |
| Original implementation tree | `c0f28a660c0a5c8b16d3f82adee06d104668d4e5` |
| Preserved concurrent preparation implementation | `81e35e97d2fa410bbfbb970b53ccc179b0aa8d27` |
| First tested integration | `236770d6083ae88749e1830dd08eb72ee4327f97` |
| First integration tree | `449e538d1066df343b501ab365fa521cb2cdc2fa` |
| Preserved concurrent Git-observation correction | `e9e36c1cdccf975e330d9a9d2d67f3df9e50ba98` |
| Latest tested integration | `ae27591d1e4b7c9f2ec802c75fd6556b95a0483b` |
| Latest integration tree | `9d2be910dd14ce4e6fabf2e30e4d84db98d835c7` |
| Preserved concurrent delivery records | `fb53ef0fe979406cb3906200e1bbe49abcb1dafc` |
| Documentation-only integration | `91d52abdf41b6994e4184b7a4566fa055649e6e7`, tree `25486f2c1d769ad924a3b9ecbc68e38adf54bd16` |
| Observation date | 2026-11-16 UTC |
| Implementation and integration owner | `/root`, with separately scoped agent implementation, testing and review assignments |
| Handoff authorship | A42's retained premerge handoff, updated by A56 from recorded observations; A56 ran no tests |

The first integration has ordered parents `42e36724a` and `81e35e97`; the
latest has ordered parents `236770d6` and `e9e36c1`. The later concurrent change
isolates preparation Git observations from default machine configuration and
adds four regressions. These identities name code and integration checkpoints;
this subsequent handoff, review and evidence packaging are separate documents
and are not represented as bytes present in an earlier tested tree.

The third integration has ordered parents `ae27591d` and `fb53ef0`. It preserves
the concurrent preparation handoff and completed ledger, changing only those
two documentation files. Production and test bytes remain those of the latest
1,075-test checkpoint. The concurrent ledger's assignments are not counted in
this continuation's sixty requested assignments.

The user explicitly authorized implementation, testing, commits and direct push
to the stated `master` branch. That authority does not supply vendor
qualification or waive an acceptance gate. Publication of the combined XRT
continuation remains unobserved at this record's assembly; the separate
[preparation handoff](p01-hwemu-handoff.md) retains its own historical delivery
and hosted observations.

The original [verification packet](evidence/p01-xrt-tooling/verification.json)
remains historical evidence for `42e36724a`, including its 875-test run and live
blocked CLI observations. The separate
[merge verification packet](evidence/p01-xrt-merge/merge-verification.json)
binds the combined source identities and their distinct completed-suite records. The
[review record](p01-xrt-review.md) preserves scoped findings and corrections.
The [XRT execution ledger](p01-xrt-agent-execution.json) records **60 completed
distinct assignments across ten logical waves of six**. It includes actual
results, evidence bases and 57 retained note hashes; assignments 1–3 explicitly
use their contemporaneous coordinator records. Older and concurrent ledgers
remain separate historical records. Agent completion does not grant vendor or
hardware acceptance.

## Implemented path and configuration

The [integration guide](p01-xrt-integration.md) is the operator runbook. The
runner consumes an already prepared and independently reviewed vendor artifact
packet; it neither provisions a vendor installation nor builds the FPGA image.

| Changed component | Purpose and affected behavior |
|---|---|
| [Runner](../../ci/project/xrt_baseline.py) | Read-only `probe` and `plan`, then a separate `run` path with fresh build/output roots, sequential bounded commands, retained inputs and failure checkpoints |
| [Contract](../../ci/project/xrt_contract.py) and [example](../../ci/project/p01_xrt_environment.example.json) | Strict manifest, file-identity and build-receipt validation; the example deliberately contains invalid unknown identities |
| [Inventory](../../ci/project/xrt_inventory.py) | Bind source, native tools, vendor lookups, platform, prepared image/configuration, receipt/logs and effective generated build configuration |
| [Source guard](../../ci/project/xrt_source.py) | Reject hidden `assume-unchanged`, `skip-worktree` and unmerged entries in the source checkout and indexed recursive submodules |
| [Runtime inspection](../../ci/project/xrt_runtime.py) | Check selected ELF structure/compatibility and generated Vortex/runtime/coreutil lookup bindings before and after the smoke |
| [Signal handling](../../ci/project/xrt_signals.py) | Route execution/probe cancellation through cleanup and failure retention, restoring enclosing handlers |
| [XRT INI template](../../sw/runtime/xrt/xrt.ini.in) and [Tcl hook](../../sw/runtime/xrt/xsim.tcl) | Preserve the corrected tracked hook, concurrent lean debug/profiling defaults and exact waveform opt-in guard |
| XRT tests and shared fixture support | Original implementation added 284 distinct tests; the shared configuration file is subsequently reconciled into four behavioral tests, with the combined counts recorded below |

The merged tree preserves two independent workflows:

| Route | Inputs and build boundary | Execution boundary |
|---|---|---|
| [Read-only preparation](p01-hwemu-runbook.md), `hwemu.py inventory/plan` | Inventory reports prerequisites; plan checks its own manifest/receipt and an existing generated build | Emits an unqualified candidate with `launch_ready=false`, `execution_performed=false` and blocked A03; declared budgets are not enforced by an execution supervisor |
| [Prepared-artifact runner](p01-xrt-integration.md), `xrt_baseline.py probe/plan/run` | Requires its own independently reviewed strict manifest/receipt and a fresh build directory | Constructs fixed commands and applies its own CLI budget; it does not consume preparation candidate commands, budgets or a saved plan |

Both schema families use `schema_version: 1`, but their exact key sets differ.
There is no automatic adapter or promotion from a preparation plan to execution.
The preparation planner's **F1 compiler-glob follow-up remains open and
unwaived** in the [backlog](backlog.md). Adding this separate runner does not
correct that parser limitation or grant the planner's candidate launch readiness.

The prepared image, generated application and runtime must share the fixed RV64
configuration: one cluster, one core, four warps, four threads, issue width one
and native STD scalar arithmetic. The integer `demo -n1` must report 16 points
and 64-byte buffers. This workload does not qualify tensor arithmetic.

Once prerequisites pass, run mode is designed to execute six commands:
`configure`, the kernel-library build, the runtime-stub build, the application
build, the vendor-runtime build and the direct `demo -n1` smoke. GPU build
commands use the fresh generated build tree. The smoke uses `VORTEX_DRIVER=xrt`,
`XCL_EMULATION_MODE=hw_emu`, manifest-pinned image/configuration paths and its
own retained tracing-disabled INI. The inherited `blackbox.sh` and `run-xrt`
recipes do not select this direct smoke path. The generated template now has
lean defaults and retains its guarded Tcl hook; waveform capture requires
explicit debug configuration plus `VORTEX_XRT_WAVEFORM=1`. The direct smoke's
retained INI has no Tcl hook. The generated `run-xrt` recipe still assigns its
own `XRT_INI_PATH`.

The guide fixes a default budget of two compile workers, 1,800 seconds per
command, a 15 GiB free-disk reserve, 16 MiB per command log and 6 GiB sampled
process-group RSS. These are configured limits for a future run, not measured
vendor resource requirements. Sampled monitoring is not a hard kernel quota;
effective cgroup memory remains unknown. Pre-write checks protect the reserve,
and a bounded emergency failure-status checkpoint may be attempted when a
full report cannot fit. Unsafe paths or unavailable storage can prevent even
that checkpoint.

A48's **premerge** disk/memory observation at
`2026-11-16T00:46:58.659575+00:00`, while the implementation was `42e36724a`,
recorded **54,359,621,632 available bytes (50.63 GiB)** on the workspace
filesystem and **5,218,430,976 bytes (4.86 GiB)** on `/tmp`. The latter was below
the default 15 GiB reserve, so future execution needs an adequately provisioned
existing parent `TMPDIR` selected before CLI startup. Child `TMPDIR` alone does
not redirect parent temporary work. Observed host `MemAvailable` was
8,099,147,776 bytes (7.54 GiB); effective cgroup headroom was not established.
These timestamped measurements do not certify current capacity, a later merge's
resource state or the resources a vendor build would require.

A59's final resource audit at `2026-11-16T01:16:13+00:00` observed
**54,317,580,288 free bytes (50.587 GiB)** on the workspace filesystem and
4.861 GiB on `/tmp`. At `01:16:33+00:00`, the repository occupied 358,993,920
allocated bytes and the complete workspace 361,619,456 bytes. Its pending-file
snapshot contained 42 documentation/evidence text files totaling 792,499 bytes;
later ledger and handoff completion adds only small text changes. No vendor
package, binary payload or large build was added. These remain dated resource
observations, not a vendor-build capacity guarantee.

## Verification by exact source checkpoint

Root used this source-root command for the recorded full-suite checkpoints:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

### Historical original implementation: 875 tests

At `42e36724a2f2a02766b26de8deb9b04b7557fa27`, the
[retained log](evidence/p01-xrt-tooling/p01-xrt-full-tests.log) ends with
`Ran 875 tests in 98.655s` and `OK`, with no failures, errors or skipped tests.
The [command record](evidence/p01-xrt-tooling/p01-xrt-full-tests.json) records
exit 0, start `2026-11-16T00:29:34.078112+00:00`, finish
`2026-11-16T00:31:12.941418+00:00` and 98.862 seconds wall time. The total
comprises the 591 existing tests and 284 new XRT tests. This handoff does not
substitute a later documentation revision for those tested bytes.

A37 independently audited the original discovery and test quality without
executing the suite. Its 284 distinct test IDs span 15 semantic modules and 33 concrete test
classes, with no duplicated imported test methods, loader errors or
`expectedFailure` suppression. The actual full-suite execution above supplied
the zero-skip result, including conditional local compiler/ELF prerequisites.

| Original XRT test category | Count | What actually supplies the proof |
|---|---:|---|
| Generated-build integration | 2 | Real repository `configure` runs in separate temporary RV64 trees; generated INI/source path checks and unmocked inventory/tamper detection |
| Source provenance | 15 | Real disposable Git repositories, index flags and recursive file-backed submodules |
| CPU ELF compilation/inspection | 37 | Tiny local host ELF fixtures and real `readelf`, including selected loader experiments and the incompatible-class fallback regression |
| Cancellation | 6 | Three real local process-cleanup tests plus three signal/thread unit tests |
| Runner orchestration | 109 | Deliberately inert build/process observations; real file copies, hashes, checkpoints and boundary checks |
| Direct contract, environment, path, inventory, reference and parser checks | 115 | Temporary files and malformed inputs; some native inventory/observations are explicitly mocked |
| **Total** | **284** | **Local tooling/configuration evidence only** |

### First combined integration: 1,071 tests

At `236770d6083ae88749e1830dd08eb72ee4327f97`, tree
`449e538d1066df343b501ab365fa521cb2cdc2fa`, root's retained run passed **1,071
tests, zero skips, exit 0**. It began at
`2026-11-16T00:57:41.503468+00:00` and finished at
`2026-11-16T00:59:43.774332+00:00`: 121.926 seconds of unittest execution and
122.255 seconds wall time. A53 and A54 independently reconciled the retained
log, identity and selected source hashes. A54 found every expected test ID once,
all with `ok`, and no loader errors, duplicate inherited methods, failures,
errors, skips, expected failures or unexpected successes. Those audits ran no
suite and remain bound to this first integration.

The combined count is `875 + 193 + (4 - 1) = 1,071`: concurrent preparation adds
193 separate tests, while the shared configuration tests consolidate **1 + 4
into 4**. A50 preserved the exact generated hook/file assertion, stronger
no-unsubstituted-`@` check, lean INI defaults, rejection of non-opt-in waveform
values and exact-string-`1` recursive waveform opt-in. Its focused real
configure/Tcl run passed all four tests with zero skips; all four also passed
in root's combined suite. Consolidation removes duplicate behavior, without
removing an independent configuration obligation.

### Latest integration: 1,075 tests

At `ae27591d1e4b7c9f2ec802c75fd6556b95a0483b`, tree
`9d2be910dd14ce4e6fabf2e30e4d84db98d835c7`, root's retained run passed **1,075
tests, zero failures/errors/skips, exit 0**. It began at
`2026-11-16T01:05:12.345327+00:00` and finished at
`2026-11-16T01:07:19.931192+00:00`; the log ends with
`Ran 1075 tests in 127.156s` and `OK`, while metadata records 127.569 seconds
wall time. The metadata records clean checkout state before and after the run
and unchanged hashes for 92 selected source files. These selected bindings do
not claim an atomic or complete filesystem snapshot.

The actual count is `1,071 + 4 = 1,075`. The added four regressions accompany
`e9e36c1`'s fixed system/global Git configuration isolation while preserving
repository/worktree configuration and explicit includes for safety inspection.
They cover machine defaults and continued rejection of repository/worktree/
included filters and partial-clone settings. The original 875-test and
first-merge 1,071-test results remain bound to their own source checkpoints;
this later run supplies the combined execution evidence for the correction.
The [merge packet](evidence/p01-xrt-merge/merge-verification.json) retains the
actual logs, exits, exact revision/tree and selected source bindings separately
from the original packet.

The real configure tests generate files without building a GPU. Disposable Git
tests prove selected source-inspection behavior. CPU ELF fixtures exercise the
host loader and parser; their binaries are not vendor or accelerator artifacts.
Synthetic orchestration success means the intended state transitions and
rejections worked under supplied observations. It does not demonstrate a
successful vendor build, actual vendor resource usage or a GPU numerical result.
No production golden, numerical tolerance or phase gate was weakened.

## Historical live blocked observations

A38 invoked the actual `42e36724a` implementation CLI in read-only `probe`
and `plan` modes. These are retained original-revision observations, not fresh
probes of the later merged checkout. The [verification record](evidence/p01-xrt-tooling/verification.json)
and linked metadata retain exact argument arrays, interpreter/tooling identities,
stdout/stderr hashes, times and before/after observations.

| Actual observation | Outcome | Exit | Boundary |
|---|---|---:|---|
| `python3 ci/project/xrt_baseline.py probe` | `blocked` | 1 | Five vendor executables absent from `PATH`; all three vendor roots unset; pinned platform/artifact manifest and independently reviewed receipt still required |
| `plan` with the unchanged authoritative example manifest, empty dedicated tool root and nonexistent build/output paths | `blocked` | 1 | Rejected during manifest loading: `source.revision must be a lowercase hexadecimal digest` |

The five absent executables are `v++`, `vivado`, `emconfigutil`, `platforminfo`
and `xsim`. The unavailable roots are `XILINX_VITIS`, `XILINX_VIVADO` and
`XILINX_XRT`. The invalid example was rejected before build/output directory
creation or execution. The observed source/root metadata fingerprints and Git
index hashes remained unchanged; the selected build/output paths remained
absent. These observations are narrower than full-tree byte verification.
No process-execution trace was collected: the absence of vendor/child execution
is supported by the reviewed probe and early-rejection paths.

The blocked exits are expected recorded outcomes, not a passing plan or a
vendor execution failure. No vendor install, license-server probe, image build,
vendor `hw_emu` smoke, FPGA synthesis, physical-board measurement or silicon
qualification occurred in this continuation. It added no GPU numerical or
performance execution evidence.

## Review and preserved acceptance

A39 used immutable, hash-verified copies of the starting revision's classifier
and policy to inspect the original exact base-to-implementation delta. The determinate
result is **R2**, policy version 3: 32 paths comprise seven R0, 24 R1 and one
R2. The only final-class reason is `path:sw-stack` for `xrt.ini.in`; no R3
contract detector fired. Classification/explanation exited 0. This is advisory
classification, not software acceptance.

A53 separately applied those immutable base-policy inputs to the combined
revisions. The first integration remains R2 over 58 paths (11 R0, 45 R1, two
R2); the latest integration remains **R2 over 59 paths** (11 R0, 46 R1, two R2).
For the latest revision, `xrt.ini.in` and `xsim.tcl` supply `path:sw-stack`, no
R3 contract detector fires, and classification/explanation both exit 0. These
results apply to the named immutable integration deltas, not subsequently
assembled evidence and delivery documents.

The configure-copied obligation is addressed by the two actual configure tests
in the passing original and combined-integration suites. No RTL or SimX timing code changed, so
the conditional Beacon and `model_parity` obligations are not triggered;
neither workload is represented as run or passed. The existing user authority
covers the direct publication route, without an invented PR approval or waiver.

The [review record](p01-xrt-review.md) preserves the concrete correction chains:
the generated Tcl path, numeric/configuration rejection, late identity drift,
retention/resource handling, SIGTERM cleanup, compiler/library selection,
hidden Git index flags, path retargeting and incompatible ELF fallback. No
unresolved concrete F2/F3 remains in that recorded correction chain. Review
scope stays explicit: independent regressions of a later correction do not
turn a pre-fix review into a review of every later hunk.

A43 subsequently reviewed the exact final ELF-header/four-object compatibility
and path-revalidation production hunks at `42e36724a`, including failure and
checkpoint boundaries, with no additional concrete finding. A49 reviewed
coexistence, A50 reconciled and tested shared configuration behavior, A51
reconciled the operator documentation and A52 independently audited first-merge
source identities, behavior and protected assets. A53's latest object comparison
confirms that the XRT helper bytes remain identical to `42e36724a`, preparation
modules match `e9e36c1`, and shared INI/Tcl remain those from `81e35e97`.
These scoped checks do not close the separate preparation planner F1 or assert
that A52 reviewed a later correction it did not inspect.

Remaining limits are part of the contract. Filesystem checks do not provide an
atomic snapshot or prevent every concurrent replacement. The source-index guard
does not compare every working file with its committed blob. Selected ELF
checks do not establish complete loadability, symbol ABI, dependency closure or
actual process-map provenance. Receipt/log hashes and nonempty qualification
text bind assertions; independent review must assess their truth and the
installed release/platform compatibility.

| Gate or evidence | Disposition after this continuation |
|---|---|
| [P01-A01 clean build](evidence/p01-build.json) | Existing acceptance preserved |
| [P01-A02 native numerical matrix](evidence/p01-native.json) | Existing acceptance preserved |
| [P01-A03 vendor integration](evidence/p01-xrt-blocked.json) | Existing blocked record preserved; this continuation adds no accepted vendor execution |
| Supplemental full-AFU `xrtsim` | Existing separate evidence; cannot satisfy vendor `hw_emu` |
| P01 / P02 | `blocked` / `not_started` |

The tooling records retain `phase_complete=false` and
`acceptance=not_evaluated`. Protected assets, licenses/attribution, accepted
evidence, inherited goldens and toolchain pins remain preserved, as documented
by the independent governance review. No requirement is waived.

## Completed collaboration and final review

All sixty numbered workers completed their assignments under the three-worker
concurrency limit. The coordinator, follow-up turns, failed spawns and the
separate preparation continuation are excluded from the total. Final accounting
checks verified contiguous unique identities, six completed assignments per
wave and all 57 available note hashes.

A60 independently checked the third merge's exact parents and two-document
delta, preservation of the concurrent records, all 92 selected tested-source
identities and 21 merge-packet artifact hashes. It checked the 59 prior
completions and their available note hashes, then supplied its own completion
report. All 207 reviewed local Markdown targets resolved and the whitespace
check passed. No concrete release blocker was found in that scope. The final
ledger update records this last report; it does not invent an additional agent
or rerun the suite.

## Source control and publication boundary

The terminal HTTPS push could not obtain credentials. The authorized GitHub
connection imported the reviewed objects with new commit metadata instead.
The [publication identity map](p01-xrt-publication-map.json) retains exact raw
local commit bytes and verifies the following GitHub tree and ordered-parent
identities through API readback:

| Local execution or assembly checkpoint | Corresponding GitHub commit | Identical tree |
|---|---|---|
| `42e36724a2f2a02766b26de8deb9b04b7557fa27` | `9ed4c00749d8c637262cc24ef92c0ce97da395f2` | `c0f28a660c0a5c8b16d3f82adee06d104668d4e5` |
| `236770d6083ae88749e1830dd08eb72ee4327f97` | `7c8d67861b714fd047c26d7b106b0ab27b1207aa` | `449e538d1066df343b501ab365fa521cb2cdc2fa` |
| `ae27591d1e4b7c9f2ec802c75fd6556b95a0483b` | `827dc664dc464c7a370dd9211deabfac4e8524ee` | `9d2be910dd14ce4e6fabf2e30e4d84db98d835c7` |
| `91d52abdf41b6994e4184b7a4566fa055649e6e7` | `7a1993c6d4eae77b14f9a6302b91026a0595073a` | `25486f2c1d769ad924a3b9ecbc68e38adf54bd16` |
| `4f8e862c50976047feebc6bc55ec2dda2ccf9cbe` | `deca8022327199039946585c7c1397de5b60f512` | `ac4d458491d15f4a96ff7c192b646291f6da1844` |

The actual test executions remain bound to their original local checkpoint IDs,
trees and timestamps. The mapped GitHub commits preserve file-tree content and
merge ancestry; they are not represented as commits on which those earlier
commands ran. The final mapping and explanation are subsequent documentation.
An XRT manifest/receipt still requires its exact reviewed source revision; this
map does not make revisions interchangeable or automatically qualify an input.

The original runner, preserved concurrent work and both integration checkpoints
are locally available at the exact identities above. This handoff records the
combined XRT continuation **before observed publication**. No push, remote
readback or hosted-CI result for this combined continuation is asserted here.
The preparation continuation's prior publication and hosted-failure history
remain in its own handoff; preserving them does not establish hosted recovery
for this integrated source.

Direct publication to the authorized repository's `master` is already
authorized. The integration owner must check the actual remote head, preserve
any further concurrent work and verify the delivered remote revision. Publication observations belong to
that delivery step. The separately assembled documentation/evidence revision
remains identifiable from the tested source checkpoints. This frozen assembly
record establishes completed implementation, checks and collaboration; the
delivered commit's remote identity and hosted checks are separate publication
observations.

## Next bounded action

**The FPGA platform operator must prepare and independently qualify one
compatible vendor release/platform and matching `hw_emu` artifact packet.**
Follow [P01-T05](backlog.md) and the [integration guide](p01-xrt-integration.md):

1. Identify supported host/release, exact platform/shell and authorized
   tool/license access. Resolve disk, memory and preparation-build resources
   before downloading or building vendor artifacts.
2. Provide the matching `.xpfm`, `vortex_afu.xclbin`, `emconfig.json`, original
   successful preparation commands/logs, pinned source/configuration identities,
   completed build receipt and substantive independent qualification review.
   Preserve preparation failures and populate the manifest from observations.
3. Run the read-only plan with fresh, separate build/output paths and the
   reviewed native toolchain. Stop on every missing or mismatched prerequisite.
   Preserve the selected reserve, worker, timeout, log and RSS limits.
4. Only after the plan and qualification are ready, run the bounded direct
   smoke and retain its actual command exits, configuration/runtime bindings,
   transfer/launch/completion milestones and all 16 reference points. Obtain
   independent review before any A03 decision.

Until that real execution and review exist, keep P01-A03 blocked. Even a future
reviewed `hw_emu` pass would establish its named integration scope; physical
FPGA, performance and silicon obligations remain separate.
