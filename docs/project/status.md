# Current project status

**Checkpoint: P00 repository foundation is accepted on the default branch
`master`.** [Pull request 1](https://github.com/baabi-boo/AI-GPU/pull/1) was
explicitly authorized by the maintainer, merged and verified. P01 is the next
phase; it has **not** started.
The live phase state and gate references are canonical in
[roadmap.json](roadmap.json). This page explains the current handoff; it is not
independent proof that a phase or GPU workload passed.

## Where the project stands

| Area | Current state | Meaning |
|---|---|---|
| P00 — project foundation | `complete` | All three source-level gates have compatible evidence; independent reviews, explicit user authorization and verified default-branch delivery are recorded |
| P01–P11 | `not_started` | Their qualification work and acceptance evidence have not been completed by this setup |
| Inherited Vortex implementation | `source_present` | GPU RTL, native tensor kernels, runtime, simulators and FPGA flows are inherited source, not new measured AI-GPU results |
| Physical hardware / custom silicon | Not qualified | No board has been selected or measured, and no fabrication commitment has been made |

The source baseline is `da55a516a48b49013724f697d3c12a48932b449f` in
`baabi-boo/AI-GPU`, whose default branch is **`master`**. See the
[baseline inventory](baseline.md) for provenance, source boundaries and the
protected illustration checksum. The reviewed and locally tested source
candidate is **`5a97e59ed95163c585106250194f816353d6ca4e`**, tree
`9f65ae6e2bce7adeaec2432c11756510028c8bc0`. The reviewed PR head was
`bebef861742165db1d0d78352ac008b079a35fdd`. The verified merge commit is
**`106b01945d102eec169e68400b2cb8df985236cb`**, whose tree preserves the
complete reviewed changes. See the [accepted delivery record](evidence/setup-accepted.json),
[merge observation](evidence/setup-merged.json) and
[review record](evidence/setup-review.md) for exact provenance. The later
documentation-only closure commit records this acceptance; it is not a new GPU
qualification result.

## What has been prepared

- A [charter](charter.md), [architecture](architecture.md), traceable
  [requirements](requirements.md), detailed phase guides and dependency-aware
  acceptance criteria.
- [Hardware](hardware.md) and [software](software.md) development paths,
  [verification](verification.md), [benchmarks](benchmarks.md),
  [risks](risks.md), [decisions](decisions.md) and [release rules](releases.md).
- Standard-library offline project validation, positive/negative tests and a
  read-only prerequisite/resource preflight under `ci/project/`.
- An additive lightweight governance workflow and structured issue forms.
  The inherited GPU tests, golden data, tool pins and workflows remain intact.
- An opt-in, unqualified [native AI configuration candidate](configurations.md)
  with source-only parser tests; no GPU execution is established by this profile.
- Preservation of the original README illustration and upstream attribution.

The [agent execution ledger](agent-execution.json) records **60 actual completed
assignments across 10 waves of six**. Final source review reported no remaining
actionable findings within its scopes. Agent counts are not GPU acceptance
evidence or maintainer approval and do not determine phase status.

## Checks observed during integration

The [source validation report](evidence/setup-validation.json) and
[command log](evidence/setup-validation.log) identify the exact published source
candidate tested with a clean worktree. The [review record](evidence/setup-review.md)
retains earlier failures, repairs and independent clean-checkout checks. The
[publication observation](evidence/setup-publication.json) and later
[merge observation](evidence/setup-merged.json) are timestamped snapshots, not
promises that workflow outcomes remain unchanged.

| Check | Observed result | Scope / remaining work |
|---|---|---|
| `python3 -I -S -B -m unittest discover -s ci/project -p 'test_*.py'` | Foundation snapshot: 180 tests passed. Local CI-repair candidate: 187 tests passed, including five SST source/launcher and two RTL resource-budget contract checks | Source-only testing; does not execute GPU kernels or the external SST build |
| `python3 ci/project/preflight.py --tier governance --min-free-gib 1` | Passed | GPU dependencies are optional for this tier; this is not an approved execution budget |
| `python3 ci/project/check_project.py` | Passed at the exact published source revision | Source-only metadata, links and integrity; not GPU truth or approval |
| `python3 ci/change_impact.py lint-policy` | Passed | Inherited policy structure only |
| `python3 ci/testcase.py lint` | Passed: 945 cases across 28 categories | Catalog validation, not 945 executed GPU tests |
| Protected illustration SHA-256 | Matched the baseline | Image bytes remain unchanged |
| GitHub Project Governance workflow | Review-branch push/PR and merged `master` run passed | [Default-branch run](https://github.com/baabi-boo/AI-GPU/actions/runs/43662715598); source-only prerequisite, validator and unit tests succeeded |
| Inherited GitHub GPU CI | [Follow-up `master` run](https://github.com/baabi-boo/AI-GPU/actions/runs/43671896012): setup and both XLEN builds passed; GPU matrix still running at the November 15 checkpoint | The SST disk exhaustion is resolved. Two sparse-WGMMA `perf_gate` / `model_parity` shards were interrupted by hosted runner shutdowns (exit 143), not by recorded test assertions. A scoped Verilator build-concurrency safeguard has been added for subsequent validation; a full GPU pass is **not** claimed |
| Locally launched GPU build/workloads, XRT emulation, synthesis, physical FPGA and silicon tests | Not run | These belong to separately gated execution phases; no local toolchain download or hardware purchase occurred |

## CI runner-queue mitigation checkpoint (2026-11-15)

At the November 15 06:13 UTC observation, [master CI run
43680345927](https://github.com/baabi-boo/AI-GPU/actions/runs/43680345927)
failed before its `plan` and `change-impact` jobs received runners (runner ID
zero, no executed steps); `setup`, `build` and `tests` were skipped. The earlier
[full-coverage run
43671896012](https://github.com/baabi-boo/AI-GPU/actions/runs/43671896012)
had planned 125 jobs, and many were likewise left without runners, making
runner-queue contention plausible but not proven. Neither run supplies a clean
GPU gate result.

The CI definition now bounds test-matrix dispatch to eight concurrent cells and
cancels superseded push/PR runs of the same event and ref. It does not remove
any test cases or change goldens. **Hosted validation remains outstanding:**
check whether GitHub assigns runners to the next push run, inspect actual
`Run cell` failures separately, and review Actions account/resource limits if
jobs still terminate without executing steps. Keep P01 blocked until its
independent native and RTL evidence exists.

## What remains before GPU execution

1. **P01 prerequisites:** the inspected execution checkout had five uninitialized
   submodules and lacks the required RISC-V/LLVM/Verilator environment. XRT
   emulation additionally requires an identified platform and vendor tools.
   Missing access remains a blocker, not a substitute pass.
2. **Engineering decisions:** the supported numerical/configuration subset,
   tiny-model fixture, physical board, performance/resource targets and any
   funded silicon program remain governed by the [decision log](decisions.md).
   Role names do not assert that staff, budgets or approvals already exist.
3. **Evidence continuity:** later GPU work must retain exact source/configuration
   identities, raw results, hashes and independent reviews; do not promote the
   inherited failing CI or source-only P00 evidence to a P01 pass. The earlier
   [blocked delivery record](evidence/setup-delivery.json) remains historical
   evidence of the pre-merge state, superseded by the accepted delivery record.

## Next bounded action

**Begin P01's reproducible baseline packet (P01-T01, followed by P01-T02).** Assign an
actual verification owner and freeze one small native configuration and catalog
matrix before downloading tools or launching builds. Record the source/tree,
submodule commits, tool bundle identities, formats, dimensions, arithmetic
backend and out-of-tree build locations. Set the disk/RAM/job/time budget and
retain the preflight result. Follow [P01](phases/p01-baseline.md), the
[backlog](backlog.md) and [developer guide](developer-guide.md).

The first execution target is bounded native GEMM/attention correctness, not
more cores, a large model, CUDA compatibility or a manufacturing order. Missing
native or full-AFU evidence prevents phase closure. Do not weaken inherited
tolerances or goldens to resolve a failure.

## Required handoff for every continuation

Read [AGENTS.md](../../AGENTS.md), this page and the canonical roadmap against
the current checkout before choosing work. Use the
[handoff template](handoff.example.md) to record what actually changed, exact
tests and not-runs, unresolved findings, publication state and the next bounded
action. Update this page and the relevant phase evidence together; never carry
an old conversation's completion claim forward without checking the repository.
