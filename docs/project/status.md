# Current project status

**Checkpoint: repository foundation is published for review; approval and merge
are pending.** [Pull request 1](https://github.com/baabi-boo/AI-GPU/pull/1) targets
the existing `master` branch from `ai-gpu-project-setup`.
The live phase state and gate references are canonical in
[roadmap.json](roadmap.json). This page explains the current handoff; it is not
independent proof that a phase or GPU workload passed.

## Where the project stands

| Area | Current state | Meaning |
|---|---|---|
| P00 — project foundation | `in_progress` | P00-A01/A02 have scoped passing evidence; P00-A03 remains blocked pending actual maintainer approval and intended default-branch delivery |
| P01–P11 | `not_started` | Their qualification work and acceptance evidence have not been completed by this setup |
| Inherited Vortex implementation | `source_present` | GPU RTL, native tensor kernels, runtime, simulators and FPGA flows are inherited source, not new measured AI-GPU results |
| Physical hardware / custom silicon | Not qualified | No board has been selected or measured, and no fabrication commitment has been made |

The source baseline is `da55a516a48b49013724f697d3c12a48932b449f` in
`baabi-boo/AI-GPU`, whose default branch is **`master`**. See the
[baseline inventory](baseline.md) for provenance, source boundaries and the
protected illustration checksum. The published and locally tested source
candidate is **`5a97e59ed95163c585106250194f816353d6ca4e`**, tree
`9f65ae6e2bce7adeaec2432c11756510028c8bc0`. Its tree exactly matches the reviewed
local candidate; the [review record](evidence/setup-review.md) explains that
mapping and the earlier immutable snapshots. The evidence attachment is a
later metadata-only update; its latest delivered revision is the PR head.
Review-branch readback is verified. **Human approval and a merge into `master`
have not occurred.**

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
[publication observation](evidence/setup-publication.json) is a timestamped
snapshot, not a promise that later workflow outcomes remain unchanged.

| Check | Observed result | Scope / remaining work |
|---|---|---|
| `python3 -I -S -B -m unittest discover -s ci/project -p 'test_*.py'` | 180 tests passed: 51 validator, 42 preflight, 11 profile, 24 adversarial, 18 repository-contract and 34 Markdown-edge tests | Repeated in an exact clean checkout with standard-library-only Python; no GPU execution |
| `python3 ci/project/preflight.py --tier governance --min-free-gib 1` | Passed | GPU dependencies are optional for this tier; this is not an approved execution budget |
| `python3 ci/project/check_project.py` | Passed at the exact published source revision | Source-only metadata, links and integrity; not GPU truth or approval |
| `python3 ci/change_impact.py lint-policy` | Passed | Inherited policy structure only |
| `python3 ci/testcase.py lint` | Passed: 945 cases across 28 categories | Catalog validation, not 945 executed GPU tests |
| Protected illustration SHA-256 | Matched the baseline | Image bytes remain unchanged |
| Initial GitHub Project Governance workflow | Push and PR runs passed | [PR run](https://github.com/baabi-boo/AI-GPU/actions/runs/43661346807); prerequisite, validator and unit-test steps succeeded on the source candidate |
| Inherited GitHub GPU CI | In progress at the publication observation | Automatically triggered existing workflows; not claimed passed or treated as acceptance of the AI candidate |
| Locally launched GPU build/workloads, XRT emulation, synthesis, physical FPGA and silicon tests | Not run | These belong to separately gated execution phases; no local toolchain download or hardware purchase occurred |

## What prevents acceptance now

1. **Approval and delivery:** PR 1 is published, but actual maintainer approval
   for the R3 CI change is pending. Assess applicable checks, record approval,
   then verify an authorized merge/default-branch readback and attach a new
   delivery report. Agent review, a green governance job and review-branch
   publication cannot supply that approval. The current
   [delivery report](evidence/setup-delivery.json) is explicitly blocked.
2. **Evidence continuity:** retain hashes and exact-revision outcomes when
   final metadata or subsequent code changes are delivered. Do not silently
   relabel historical observations or mark a running/cancelled job passed.
3. **P01 prerequisites:** the inspected checkout has five uninitialized
   submodules and lacks the required RISC-V/LLVM/Verilator environment. XRT
   emulation additionally requires an identified platform and vendor tools.
   Missing access remains a blocker, not a substitute pass.
4. **Engineering decisions:** the supported numerical/configuration subset,
   tiny-model fixture, physical board, performance/resource targets and any
   funded silicon program remain governed by the [decision log](decisions.md).
   Role names do not assert that staff, budgets or approvals already exist.

## Next bounded action

**First obtain approval and finish P00; then begin P01's reproducible baseline
packet (P01-T01, followed by P01-T02).** Assign an
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
