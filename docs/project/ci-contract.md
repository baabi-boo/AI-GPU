# Project checks and GPU CI

AI-GPU has two distinct validation surfaces: inexpensive **project governance**
and the inherited **GPU build/test infrastructure**. Neither substitutes for the
other. This document describes their contracts, not a successful hosted run;
actual results and unresolved work belong in [status](status.md) and reviewed
[evidence records](evidence/README.md). Start from the [README](../../README.md)
or [documentation index](../index.md) for the wider development path.

## Lightweight project workflow

The additive [Project Governance workflow](../../.github/workflows/project-governance.yml)
runs the following commands from the **source root**:

```sh
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

| Check | What it establishes | Important limit |
|---|---|---|
| Preflight | Read-only source/pin, tool, submodule, resource and image inventory | Missing GPU tools/submodules are optional for governance; presence alone does not prove a usable execution environment |
| Project validator | Roadmap structure, dependency/gate references, evidence metadata and hashes, protected image, and scoped local documentation links | It does not execute recorded commands, authenticate a measurement or grant approval |
| Unit suite | Positive/negative governance fixtures, cross-document contracts and source-only configuration plumbing | These are not GPU workloads, native RTL tests or physical measurements |

The commands use Python's standard library and Git. They need no initialized GPU
submodules, RISC-V compiler, Verilator, vendor tools or board. The workflow uses
GitHub-hosted `ubuntu-24.04`, explicitly checks system **Python 3.12**, and has a
**five-minute job timeout**. It does not install GPU dependencies. Checkout still
requires ordinary GitHub access; the local validation commands themselves are
offline. Follow the [developer guide](developer-guide.md) for other tiers.

Documentation checks deliberately support a bounded Markdown subset. They are
not a complete GitHub/CommonMark renderer, HTML sanitizer, or proof of browser
and CSS visibility. Keep project markup straightforward and review its rendered
presentation; passing metadata checks does not replace that review.

The workflow's own boundaries are explicit:

- `contents: read`; no referenced secrets or write-permission job.
- `actions/checkout@v4` with credential persistence, submodules and LFS disabled.
- Ordinary `push` and `pull_request` events with matching path filters, plus
  manual dispatch; no `pull_request_target` or self-hosted runner.
- Filters cover project documents/tooling, relevant configuration/profile inputs,
  the protected image, contribution forms, pins and the workflow itself.
- Per-event/ref concurrency cancels superseded runs; cancelled is not passed.

These restrictions describe this workflow only, not every inherited workflow.
They do not certify hostile-kernel isolation, a safe physical device or permission
to spend money. Preflight resources are snapshots, not an approved build budget;
PATH tool presence and host RAM readings have the limitations printed by the tool.

## Inherited GPU CI remains separate

The existing [CI workflow](../../.github/workflows/ci.yml), test catalogs, golden
baselines and dedicated implementation gates remain in place. See the
[technical CI design](../designs/continuous_integration.md),
[test catalog](../../ci/testcases/) and [verification plan](verification.md).
GPU execution uses generated scripts in a freshly configured build tree with
matching application/backend settings; source-root governance is an exception,
not a replacement for that rule.

The inherited workflow listens to pushes and pull requests without the new
project workflow's path filter. Its event defaults select SimX smoke coverage
for pushes and SimX/RTL smoke/full coverage for pull requests. **A toolchain cache
miss overrides those push/PR defaults to broad driver/tier coverage**, and an
indeterminate change base can also broaden driver selection. A documentation
change therefore does not guarantee a small inherited run. The five-minute
governance timeout does not bound other workflows, downloads or test matrices.

The `full` setup profile builds the pinned SST **core** from source, because its
installation embeds absolute prefix paths. The hostless integration uses only
the locally built `vortex.VortexGPGPU` plugin; it does not depend on upstream
SST Elements libraries. The setup reserves the existing plugin directory, and
the regression runner supplies it to `sst --add-lib-path` explicitly. Building
the whole upstream SST Elements collection exhausts the hosted runner's disk
before tests execute. If future tests begin using external SST elements, add a
reviewed, narrowly scoped dependency and disk budget for those components.

The `model_parity` and `perf_gate` cells include exceptionally large WGMMA RTL
models. On hosted runners, their `Run cell` step exports `THREADS=2`, limiting
the parallel Verilator C++ compilation workers (which otherwise default to the
visible CPU count). All other categories keep their inherited default. This is
a **host resource safeguard**, not a reduction in test coverage: the catalog,
RTL configuration, workload inputs, cycle goldens, tolerances and 180-minute
cell timeout remain unchanged. A job that ends with a runner shutdown signal
and exit 143 has not demonstrated a passing performance or parity assertion;
review the logs and retry the exact cell before claiming the GPU CI gate passed.

Review Actions availability, account limits and the selected resource budget
before publishing or manually dispatching expensive work. Inspect the actual
planned matrix and cache state; do not infer them from a README edit. Manual
synthesis, whole-GPU analysis and physical-board flows need their own resources,
access and authority. Do not silently disable inherited jobs, cut cases, alter
goldens or widen tolerances to make a status green.

## Review and repository adoption

Treat this new enforcement conservatively as **R3** under the inherited
[review policy](../review/code-review-policy.md): independent review by an agent
that did not author the change, applicable contract evidence, and actual
maintainer approval recorded in the pull request. An agent cannot grant itself
that approval or a waiver. Because `.github/**` changes are involved, reviewers
use the base revision's classifier locally rather than trusting the changed
workflow's own classification summary.

A path-filtered workflow does not run for every possible pull request. Before
making its job an unconditional required check, review skipped-workflow behavior
and adopt an explicit strategy for unaffected changes. Adding this YAML does not
enable branch protection, configure repository permissions or confirm a private
security-reporting channel. Use the [maintainer checklist](maintainer-checklist.md)
for those separately verified decisions; do not invent settings or approvals.

## Report the result that actually happened

Record the exact tested revision/configuration, commands and exit outcomes,
reviewed artifact hashes, limitations, and hosted run identity when available.
A local pass is not a hosted pass; a workflow definition, queued/skipped/cancelled
run, or unexecuted template is not execution evidence. Preserve failures and
state which later steps did not run when an earlier check stopped the job.

Governance evidence can support P00 only within its scope. It cannot establish
native arithmetic correctness, full AFU integration, physical FPGA operation,
silicon measurements or fabrication authority. Apply [acceptance](acceptance.md)
before attaching reports or completing a phase; update status and the next
bounded action together. No CI badge alone closes the development roadmap.
