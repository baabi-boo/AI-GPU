# Project checks and GPU CI

AI-GPU has two distinct validation surfaces: inexpensive **project governance**
and the inherited **GPU build/test infrastructure**. Neither substitutes for the
other. This document describes their contracts, not a successful hosted run;
actual results and unresolved work belong in [status](status.md) and reviewed
[evidence records](evidence/README.md). Start from the [README](../../README.md)
or [documentation index](../index.md) for the wider development path.

## Project governance workflow

The additive [Project Governance workflow](../../.github/workflows/project-governance.yml)
starts with the following checks from the **source root**:

```sh
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 ci/project/check_baseline_packets.py
```

It then installs pinned native CMake **3.22.6**, prepares the checked environment
with [governance_env.py](../../ci/project/governance_env.py), and invokes the
[strict runner](../../ci/project/governance_run.py) through the private
`venv/bin/python3` with its required `--environment-receipt`. Follow the
[governance runbook](governance-runbook.md) for the complete commands, exact clean
environment, fresh external output paths and pipeline failure handling.

| Check | What it establishes | Important limit |
|---|---|---|
| Preflight | Read-only source/pin, tool, submodule, resource and image inventory | Missing GPU tools/submodules are optional for governance; presence alone does not prove a usable execution environment |
| Project validator | Roadmap structure, dependency/gate references, evidence metadata and hashes, protected image, and scoped local documentation links | It does not execute recorded commands, authenticate a measurement or grant approval |
| Published baseline consistency | Retained baseline metadata, integrity and required native-record relationships | It does not rerun workloads or grant project-gate acceptance |
| Checked environment | Interpreter/tool identities and native prerequisite probes | A ready receipt does not establish suite execution |
| Strict unit suite | Complete canonical governance fixtures, cross-document contracts, source-only configuration plumbing and bounded host tensor-oracle tests | These do not execute GPU workloads or native RTL, or provide physical measurements |

Ordinary `python3 -m unittest discover -s ci/project -p 'test_*.py'` is a
development check and cannot qualify an exact revision. Qualification requires
one uninterrupted, unfiltered invocation of the full discovered manifest:
every ID starts once in order, succeeds and stops once; subtests also succeed,
with zero skips, expected failures, unexpected successes, errors or failures.
Require exit zero and `governance_passed: true`, backed by complete events and
receipts, clean/stable source and checked/stable interpreter and tools.

Retain the complete packet, including the manifest, events, preparation and
completion receipts, internal and outer logs, and source/tool identities. For
qualified warm hosted admission, retain the original artifact and provider
identity for the exact revision, run and current attempt; verify it against an
independently selected digest and perform
[independent replay](governance-artifact-replay.md) against a clean exact checkout.
CI attempts upload even after failure and retains artifacts for
30 days; timeout or runner loss can prevent upload. Preserve failed/incomplete
attempts. Historical or partial results cannot qualify changed source.

The checked environment requires GIL-enabled Linux CPython **3.12.x** on a
little-endian x86-64 glibc host and the runbook's native tools and probes,
including C++17 and UndefinedBehaviorSanitizer (UBSan) support.
Tensor host tests compile and run in temporary directories under explicit time
and resource budgets. No initialized GPU submodules, RISC-V compiler, Verilator,
vendor tools or board are needed. The workflow uses GitHub-hosted `ubuntu-24.04`
and a **90-minute total job budget**, including preparation, validators, the
suite and artifact upload. It does not install GPU dependencies. Checkout
requires GitHub access and the pinned CMake installation requires PyPI access;
environment preparation is offline. Follow the [developer guide](developer-guide.md)
for resource requirements and other tiers.

The historical increase from 40 to 60 minutes followed the retained
[baseline cancellation](evidence/p06-managed-preflight-replay/hosted/baseline-57248-governance.json)
at source `57248e73`, run `45085300201`. That run stopped while its suite was
still executing, with no complete-suite result. Its 2,445-second observed
interval is consistent with the former 40-minute deadline; attributing the
cancellation to that deadline is an inference. The
[independent CI review](evidence/p06-managed-preflight-replay/agents/w04_a05.md)
records that change. The [runbook](governance-runbook.md) explains the later
60-to-90-minute increase: a retained 3,555.657-second suite left only 44.343
seconds for other steps under the former budget. These budget changes do not
reduce coverage or acceptance thresholds, guarantee completion, or turn a
cancelled run into a pass.

Governance preflight inventories host compilers as optional and does not test
C++17 or UBSan support. Its success alone does not establish readiness to run
the full unit suite.

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

## Complete managed-preflight replay workflow

The additive [P06 Managed Preflight Replay workflow](../../.github/workflows/p06-managed-preflight-replay.yml)
is a separate host-only job on `ubuntu-24.04`, using system CPython 3.12 and a
**20-minute timeout**. It checks the original successful and failed preflight
archives against independently pinned source inventories and Git derivations,
runs the nonempty focused test groups, and retains the current run identity and
results. The [implemented contract](../designs/managed_counter_preflight_replay_v1.md)
defines its seven external inputs and complete verification boundaries.

The successful original is run `45085300171` at source `57248e73`; the failed
original is run `45084009157` at `8756f400`. The negative control requires the
reader's exit status 1 and exact `report.outcome: value differs` result; a
missing file, usage error or unrelated failure does not satisfy it. The reader
executes no retained code or binary, performs no native build, and leaves all
qualification, readiness, warm-execution and acceptance claims false. Its
source revision denotes the historical producer, while the workflow retains
the current reader's CI identity separately.

This workflow uses ordinary pull requests, filtered pushes to `master`, and
manual dispatch. It grants only `contents: read`, disables checkout credential
persistence, submodules and LFS, and uses no self-hosted runner. Unlike governance,
it does not cancel a preceding replay run automatically. The final artifact
upload is attempted even after a failed check, with run/attempt/revision identity;
that does not guarantee evidence from an unavailable runner or absent output
directory. The [evidence packet](evidence/p06-managed-preflight-replay/README.md)
distinguishes local workflow checks, original producer execution, and actual
hosted replay results. A workflow definition alone establishes none of those
execution outcomes.

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
change therefore does not guarantee a small inherited run. The 90-minute
governance budget does not bound other workflows, downloads or test matrices.

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
native RTL arithmetic correctness, full AFU integration, physical FPGA operation,
silicon measurements or fabrication authority. Apply [acceptance](acceptance.md)
before attaching reports or completing a phase; update status and the next
bounded action together. No CI badge alone closes the development roadmap.
