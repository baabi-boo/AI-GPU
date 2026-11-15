# P01 implementation and evidence review

## Reviewed implementation

The implementation checkpoint is
`e9c9ac01f93b0d84915340999100260f2599ec44`, tree
`fbafa8e643aa935a1103e0d49ce2268b32f12c1e`. GPU execution uses the separate,
clean source revision `03181532b81fe95b1cfeac2ffb25d8597af689b2`.
Exact helper snapshots identify execution instrumentation independently of GPU
source. Subsequent documentation and evidence attachment do not change that
tested GPU revision.

The base revision's change-impact classifier returned **R1** for the published
implementation, with no detected external-contract or evidence findings.
Independent scoped reviews were nevertheless used for manifest trust, generated
inputs, process limits, configuration selection, provenance and evidence claims.
The user explicitly authorized implementation and publication to `master`.
Agent reviews are engineering evidence, not invented human approvals or waivers.

## Concrete findings and corrections

| Finding | Correction and verification | Independent participants |
|---|---|---|
| Generated make overrides/includes could contradict inventoried defaults; FIFO inputs could block inventory reads | Check regular-file containment before reading and compare instantiated `config.mk` bytes with the source template; regression fixtures cover overrides, includes, FIFOs and escaping links | `w02e_inventory_tests`; root integration |
| Native suffix flags could coexist with contradictory resolved DPI aliases | Validate resolved FPU and TCU aliases as well as native suffixes; both contradiction regressions pass | `w03d_orchestrator_tests`; root integration; `w04b_runner_review` |
| Newer modified generated headers or copied build recipes could pass timestamp checks | Independently regenerate four headers and compare thirteen copied build inputs with the source | `w04b_runner_review`, `w04e_build_identity_fix`, `w06c_generated_fix_review` |
| Ignored dependency changes and separate helper/host changes could leave stale provenance | Rehash dependencies around cases; retain six exact executing helpers and before/after host identities; drift regressions reject altered inputs | `w04b_runner_review`, `w04f_runner_identity_fix`, `w06c_generated_fix_review` |
| A changed manifest could retain the immutable toolchain's labels | Bind bootstrap and inventory to the reviewed canonical manifest digest; changed sizes and either archive digest fail under the production anchor | `w05a_archive_review`, `w05d_manifest_anchor`, `w06a_manifest_fix_review` |
| Inventory discarded duplicate JSON properties before checking the trusted manifest | Reject duplicate fields at every object depth, including identical duplicates; unchanged production-lock regressions and independent reproductions pass | `w06a_manifest_fix_review`, `w06d_strict_manifest_fix`, `w07a_strict_manifest_closure` |
| Cancellation at successful command completion could be swallowed | Check pending SIGINT/SIGTERM through drain, wait and finalization; all six boundary regressions fail the old implementation and pass the corrected helper | `w05c_process_review`, `w05e_cancellation_fix`, `w06b_cancel_fix_review` |
| Reproduction instructions conflated old GPU source with the newer runner and could select system CMake compilers | Use separate pinned checkouts and explicit GNU 11 C/CXX paths in a fresh CMake cache; shell syntax, links and a non-mutating actual plan pass | `w07d_provisioning_review`, `w07f_runbook_reproduction_fix`, `w08c_runbook_closure` |
| Attention coverage prose said RS although typed descriptors select SS | Preserve all executed fields and historical snapshots; correct the two current descriptions and publish the [operand erratum](p01/attention-operand-erratum.md) | `w08e_attention_contract_review`; root integration |

The full isolated source-root project/tooling suite passed **346 tests** after
the production helper fixes. Project governance validation also passed. These
tests exercise tooling and metadata; they do not establish GPU numerical
correctness. The published checkpoint's hosted Project Governance workflow
passed independently.

## Historical evidence and preservation

The [historical manifest](p01/history-manifest.json) preserves the GCC 14
compilation failure, first missing-`ccache` RTL failure, partial numerical results,
standalone retry, old instrumentation and stage-specific provisioning evidence.
`w06e_existing_run_audit` checked the raw observations;
`w08b_history_integrity_review` independently reconciled all 33 exported raw
artifacts, seven nested command logs, three configuration snapshots and seven
archived source files. Four unexecuted cases remain `not_run` in the historical
failed invocation. The outer RTL command exited 2; 127 was the nested missing
executable error. Later checks are not attributed to that older runner.

Exactly four exported evidence lines retain original trailing spaces: three compiler
source-display lines (14, 16 and 20) in the historical GCC 14 failure log, and line
70 of `p01/xrtsim/artifacts/generated-config.mk.txt` (`PROFILE ?= `), faithfully
expanded from the unchanged empty-profile template. These are documented
byte-preservation exceptions, not source-code whitespace changes. Publication hashes identify the sanitized
files; nested historical hashes retain their original raw-byte meaning.

`w07c_preservation_review` verified unchanged Git objects for native hardware,
simulators, runtime, kernels, inherited tests, default configuration, toolchain
pins, submodules, catalog, tolerances, goldens, workflows, licensing, P00 evidence
and the original agent ledger. The protected SVG retains SHA-256
`db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`
and its README embedding.

## Numerical and integration acceptance

The completed [native packet](p01/native/report.json) passed all six frozen
cases. `/root/w09e_native_acceptance_review` independently verified fifteen
command logs, eighteen effective configurations, six exact helper snapshots,
stable source/build/tool/host/dependencies, twenty-four binary observations and
all forty-one exported artifacts. Both attention executions reported worst
absolute error `5.29e-05` with unchanged `atol=rtol=0.001`. The SS correction
changes only two descriptive fields; the original executed matrix is preserved.
This supports **P01-A02 pass for these exact ordinary numerical cases**.

The separate [clean-build packet](p01/clean-build/report.json) passed a selected
FP16 SimX case in a new generated build directory. Before execution,
`/root/w09f_clean_build_acceptance_review` independently observed the build and
output paths absent. Its final audit passed 235 assertions, including five
successful commands, thirteen copied and seven primary generated inputs,
independent header regeneration, three effective configurations, four surviving
binaries and all sixteen exported artifacts. This supports **P01-A01 pass for
the clean generated application/simulator build**, with the explicitly recorded
reused dependency libraries. It is not a hermetic tool/dependency rebuild.

The [supplemental AFU packet](p01/xrtsim/report.json) passed the vendor-free
`xrt --target=xrtsim` integer demo: configure, kernel/runtime builds and the
sixteen-point reference completed successfully. Its ordered upload, launch,
read, completion and verification markers were retained. The scratch harness
was independently reviewed by `w09b_supplemental_harness_review`; its exact
worker-count check was tightened and independently verified before execution.
The actual completed packet passed `/root/w10b_xrtsim_evidence_review`: 1,173 integrity/provenance assertions, four logs, three effective configurations, nine identity checkpoints, four live binaries and all forty-three exported artifacts were verified.

The [vendor prerequisite record](p01-xrt-blocked.json) records **P01-A03 blocked**:
no qualified vendor `hw_emu` DMA/launch/completion execution is established.
Its required RTL metadata vocabulary does not relabel an unavailable run as a
pass. **P01 remains blocked and P02 remains not started.**

## Scope limits

SimX is software arithmetic; native processor RTL uses TFR tensor and STD scalar
arithmetic and bypasses the AFU. Supplemental vendor-free `xrtsim`, if run, does
not replace vendor `hw_emu`. No synthesis, physical FPGA or silicon qualification
is claimed. Ordinary seeded GEMM and small unscaled attention do not establish
P02 exceptional-value, rounding, layout or numerical cancellation semantics.

Actual initial tool provisioning preceded the production bootstrap. Its own
script and hashes are retained; no later installer receipt is fabricated.
Original dependencies were built with GCC 14.2; the native application/simulator
stages use GCC 11.3, device libraries RISC-V GNU 12.2 and device applications
Vortex LLVM 20.1.8. Installed-tool observations cover the declared primary files,
not every transitive shared library. Resource limits are sampled budgets, not
hard quotas or cgroup certification; simulation timings are not physical speed.

## Final release validation

The separate [P01 execution ledger](../p01-agent-execution.json) records **60
completed distinct assignments across ten logical waves of six**, with at most
three subagents active concurrently. The old P00 ledger remains unchanged.
Assignment counts do not qualify a numerical or hardware gate.

The [final tooling validation](p01/tooling-validation.json) records all **346
tests passing in 15.568 seconds** and the input/output hashes. The independent
[real-archive audit](p01/toolchain-archive-compatibility.json) verified all eighteen
locked parts and 6,273 members across five archives, including links and ordering,
without extraction or production installation. Its scope remains distinct from
the earlier actual provisioning script and fixture-tested installer.

`w10c_acceptance_record_review` independently reconciled the three acceptance
records and their 151 then-current artifact references, twenty-four raw command
logs and fifteen passing invocations. `w10d_ledger_review` checked the first
fifty-four completed assignments before the final wave was appended.
`w10e_release_integrity` verified protected files, links, shell examples and the
scoped privacy scan. `w10f_delivery_readiness` passed 460 staged-candidate
assertions and the governance checker. Root then appended the six actually
completed final-wave assignments and refreshed the affected artifact hashes.
No unresolved concrete F2/F3 finding remains in these reviewed scopes.

The implementation checkpoint is published on `master`. The evidence packet is
delivered by the commit containing this review; its exact remote commit/tree and
observed hosted workflow states are checked at delivery. A local tooling pass is
not a claim that every hosted CI workflow has completed.
