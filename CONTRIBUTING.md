# Contributing to AI-GPU

AI-GPU develops a programmable AI accelerator on the inherited Vortex stack.
Contributions should advance a bounded, testable capability while preserving
upstream engineering, licensing and attribution. This guide applies to human
contributors and coding agents; [AGENTS.md](AGENTS.md) contains the engineering
invariants.

## 1. Choose a bounded work item

Read [current status](docs/project/status.md), the [roadmap](ROADMAP.md),
[backlog](docs/project/backlog.md) and [acceptance policy](docs/project/acceptance.md)
against the current checkout. Do not infer completion from an old conversation.

Use this fork's [issue forms](https://github.com/baabi-boo/AI-GPU/issues/new/choose)
for defects, phase work and evidence submissions. Identify the relevant work item,
phase/acceptance IDs and [requirements](docs/project/requirements.md). State the
goal, non-goals, affected contracts, dependencies, proposed owner and exit evidence.
Discuss changes to architecture, numerical bounds or platform scope before
implementation; freeze acceptance bounds before measuring a candidate.

For a defect, provide the exact revision/configuration, a small reproducer,
expected and actual behavior, commands, observed outcomes and sanitized logs.
Follow [SECURITY.md](SECURITY.md) for suspected vulnerabilities. Do not post
credentials, signed URLs, private memory, restricted IP or unlicensed fixtures.

## 2. Work in the correct repository and environment

The target is **`baabi-boo/AI-GPU`**, whose existing default branch is **`master`**.
Do not accidentally submit AI-GPU changes to upstream Vortex. External
contributions use an authorized fork or permitted topic branch and a pull request
targeting this repository's `master`; private-repository access and fork policy
must be respected.

Inspect the current branch, source revision, remote identity and local changes
before updating or creating a task branch. Preserve unrelated work. Keep commits
focused and explain why a change is needed, including the affected contract and
its evidence. Do not rename the default branch, force-push over others' work or
treat this guide as permission for direct publication.

Use the [developer guide](docs/project/developer-guide.md) to choose tools and a
resource budget. Before expensive work, account for downloads, unpacked tools,
builds, traces, available disk/RAM, nested build jobs and retention. Use dedicated
versioned tool directories and separate build trees. Missing tools, licenses,
hardware access or budget are explicit blockers. Repository work does not
authorize purchases, paid services, commercial IP or manufacturing commitments.

## 3. Run the checks appropriate to the change

Project governance runs from the **source root**, without GPU dependencies:

```sh
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
git diff --check
```

These validate structure, metadata and governance tooling. They do not demonstrate
GPU correctness, performance, physical memory access or hardware readiness.
The lightweight project workflow is additive; inherited GPU CI remains separate.

GPU/kernel/RTL tests run from a **freshly configured out-of-tree build**, using
its generated scripts and matching application/backend `CONFIGS`. Reconfigure
after source or build/configuration changes; never patch generated headers to
hide mismatches. See [verification](docs/project/verification.md),
[CI guidance](docs/continuous_integration.md) and the
[test catalog](ci/testcases/). The current generated regression selector is
`./ci/regression.sh --test '<marker expression>'`; select and record a bounded
matrix rather than copying obsolete per-suite flags or launching every test.

| Change | Coverage to add or preserve |
|---|---|
| Governance tooling | Standard-library positive/negative tests in `ci/project/`, including failure behavior |
| Native kernels/operators | Focused host/kernel tests under `tests/regression/`, supported inputs and explicit rejection cases |
| Runtime/driver behavior | Applicable host/runtime unit and integration tests, including error paths and resource lifetime |
| RTL behavior | Unit tests under `hw/unittest/`, applicable processor/full-AFU integration and timing-model evidence |
| Catalog/build integration | Register cases in the applicable `ci/testcases/` catalog and build rules; reconfigure before execution |

A functional change needs a test that exposes its failure or new behavior.
Native tensor arithmetic and software-delegating DPI are different evidence;
processor `rtlsim` does not cover the full AFU, and XRT `hw_emu` is not a physical
FPGA. Record exact driver, arithmetic backend, inputs, reference and tolerances.
Never use hidden CPU fallback, altered goldens or weaker tests to claim success.

## 4. Review the diff and its evidence

Apply the normative [review policy](docs/review/code-review-policy.md) and the
repository's [code-review skill](.agents/skills/code-review/SKILL.md). Classify
the actual base-to-head diff with `ci/change_impact.py`; the classifier is
advisory, not approval. For changes to `.github/**` or `.gitattributes`, rerun
the **base revision's** classifier locally as the policy requires; do not trust
the modified workflow's own summary.

R2 requires review of every changed hunk and maintainer approval. R3 additionally
requires an independent review agent that did not author the change, the relevant
contract evidence, and maintainer approval recorded in the pull request.
An agent review cannot invent human approval or grant its own waiver.
Use the [pull-request template](.github/pull_request_template.md) to record
impact, affected consumers, tests, limitations and unresolved findings.

Preserve these inherited obligations:

- No silenced tests, wider tolerances, smaller workloads or removed coverage to
  conceal a failure; document the root cause and follow the review policy.
- Golden baselines are regenerated only through the prescribed human-run,
  reviewed commands, named in the commit message; agents and CI do not regenerate them.
- Cycle-moving RTL and SimX changes land together with applicable parity and
  performance/logic-depth evidence. Do not replace a regression with an unrelated gain.
- Toolchain pins move only after matching prebuilt artifacts exist. Installed
  APIs, ISA/configuration and cross-layer contracts require their consumers' evidence.
- Retain the original README illustration and embed, upstream copyright/license
  notices, existing functionality and the software/hardware isolation boundaries.

## 5. Leave a reproducible handoff

Use the [evidence format](docs/project/evidence/README.md) and
[handoff template](docs/project/handoff.example.md). Record the exact tested
revision/configuration, tool/submodule identities, commands, exit results,
artifact hashes, actual reviewer and explicit not-runs. A missing or blocked run
is not a pass; report local and hosted CI results separately.

Update relevant phase evidence, [status](docs/project/status.md) and
[backlog](docs/project/backlog.md) with remaining blockers and one bounded next
action. Complete a phase only when its dependencies and every acceptance gate
have compatible passing evidence and required decisions. Templates and agent
counts cannot substitute for evidence.

Before publication, verify the target, current remote head, user authorization,
maintainer approval and branch rules. Preserve concurrent changes and use the
authorized review/merge workflow. After publication, read back the actual branch
revision and report it accurately; a local commit or intended push is not delivery.

## Licensing and attribution

The inherited project is [Vortex](https://github.com/vortexgpgpu/vortex), released
under [Apache License 2.0](LICENSE). Contributions must preserve existing notices
and be offered under compatible project terms. Keep third-party code, fixtures,
models and tool/IP material traceable to their own licenses; the repository's
license does not automatically grant redistribution rights to those materials.
