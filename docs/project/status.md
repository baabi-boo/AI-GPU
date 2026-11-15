# Current project status

**Checkpoint: repository foundation is a review candidate, not yet accepted.**
The live phase state and gate references are canonical in
[roadmap.json](roadmap.json). This page explains the current handoff; it is not
independent proof that a phase or GPU workload passed.

## Where the project stands

| Area | Current state | Meaning |
|---|---|---|
| P00 — project foundation | `in_progress` | Independent source review and repairs are complete; final evidence/publication checks and actual maintainer approval remain |
| P01–P11 | `not_started` | Their qualification work and acceptance evidence have not been completed by this setup |
| Inherited Vortex implementation | `source_present` | GPU RTL, native tensor kernels, runtime, simulators and FPGA flows are inherited source, not new measured AI-GPU results |
| Physical hardware / custom silicon | Not qualified | No board has been selected or measured, and no fabrication commitment has been made |

The source baseline is `da55a516a48b49013724f697d3c12a48932b449f` in
`baabi-boo/AI-GPU`, whose default branch is **`master`**. See the
[baseline inventory](baseline.md) for provenance, source boundaries and the
protected illustration checksum. That baseline SHA does not identify the new
setup files. Exact reviewed and delivered revisions belong in the final evidence
packet. Publication and required maintainer approval have **not yet been verified**.

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

These observations include exact clean-checkout checks at the repaired snapshot
`d577267a8d7eb0b786faf47fe2aeb6acf0d66e56`; see the
[review record](evidence/setup-review.md) for original failures, corrections and
scope. Later integration edits still require final verification before P00 closes.

| Check | Observed result | Scope / remaining work |
|---|---|---|
| `python3 -I -S -B -m unittest discover -s ci/project -p 'test_*.py'` | 180 tests passed: 51 validator, 42 preflight, 11 profile, 24 adversarial, 18 repository-contract and 34 Markdown-edge tests | Repeated in an exact clean checkout with standard-library-only Python; no GPU execution |
| `python3 ci/project/preflight.py --tier governance --min-free-gib 1` | Passed | GPU dependencies are optional for this tier; this is not an approved execution budget |
| `python3 ci/project/check_project.py` | Passed after navigation integration | Earlier missing documents and the inherited dead contribution link were resolved; final exact-revision review remains pending |
| `python3 ci/change_impact.py lint-policy` | Passed | Inherited policy structure only |
| `python3 ci/testcase.py lint` | Passed: 945 cases across 28 categories | Catalog validation, not 945 executed GPU tests |
| Protected illustration SHA-256 | Matched the baseline | Image bytes remain unchanged |
| GitHub-hosted workflow execution | Not run for this setup checkpoint | Local checks do not establish a green hosted run |
| GPU build, SimX/native RTL workloads, XRT emulation, synthesis, physical FPGA and silicon tests | Not run | These belong to their separately gated execution phases |

## What prevents acceptance now

1. **P00 evidence:** final independent source review is complete. Check the
   later metadata and retain the final exact-revision results under the
   [evidence policy](evidence/README.md).
2. **Approval and delivery:** publish a reviewed pull request, obtain actual
   maintainer approval for the R3 CI change, and verify authorized publication on
   the intended branch. Agent review and local tests cannot supply that approval.
   An intended push or a local commit is not delivery evidence.
3. **P01 prerequisites:** the inspected checkout has five uninitialized
   submodules and lacks the required RISC-V/LLVM/Verilator environment. XRT
   emulation additionally requires an identified platform and vendor tools.
   Missing access remains a blocker, not a substitute pass.
4. **Engineering decisions:** the supported numerical/configuration subset,
   tiny-model fixture, physical board, performance/resource targets and any
   funded silicon program remain governed by the [decision log](decisions.md).
   Role names do not assert that staff, budgets or approvals already exist.

## Next bounded action

**First finish P00; then begin P01's reproducible baseline packet.** Assign an
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
