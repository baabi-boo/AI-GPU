# Maintainer adoption checklist

This is a procedure, **not evidence that repository settings are configured or
approvals have been granted**. Record actual decisions and observations in the
relevant pull request and [status](status.md). An unchecked item is not a pass;
an inapplicable item needs a reason rather than a fabricated completion mark.

## 1. Confirm ownership and authority

- [ ] Confirm the intended repository is `baabi-boo/AI-GPU`, its current default
  branch is `master`, and the publishing account has the needed permissions.
  Inspect the current remote head and branch rules; preserve concurrent work.
- [ ] Identify the actual maintainer, review participants and operational
  responsibilities. Role names in the roadmap do not appoint people or prove
  that a team, confidential contact, hardware budget or support commitment exists.
- [ ] Agree on the contribution and release workflow under
  [CONTRIBUTING.md](../../CONTRIBUTING.md) and the normative
  [review policy](../review/code-review-policy.md). Do not infer authorization
  for paid services, hardware, IP, external partners or manufacturing from setup work.

## 2. Review and accept the foundation

- [ ] Review the exact base-to-head diff. For `.github/**` changes, use the base
  revision's classifier as the policy requires; a modified workflow's own summary
  is not trusted review evidence. Treat new enforcement conservatively as R3.
- [ ] Obtain an independent reviewer who did not author the change, resolve
  required findings, and record exact checks, not-runs and remaining limitations.
  Preserve inherited tests, thresholds, goldens, source boundaries and tool pins.
- [ ] Obtain and record **actual maintainer approval in the pull request**.
  Deliver the initial setup through review; do not auto-merge it by treating an
  agent's report, requested agent count or successful local checks as approval.
  Only the maintainer can grant a policy-compliant waiver.
- [ ] After authorized merge/publication, read back the intended branch and
  commit. Attach compatible evidence to every satisfied P00 criterion and update
  status together. Keep P00 open while a required approval or delivery gate is pending.

## 3. Adopt CI deliberately

- [ ] Inspect repository Actions policy, allowed actions, token permissions,
  runner trust, concurrency and spending limits before enabling or dispatching
  expensive work. The inherited [CI workflow](../../.github/workflows/ci.yml)
  can expand to full coverage on a cold toolchain cache; it is not a cheap docs check.
- [ ] Review the separate [Project Governance workflow](../../.github/workflows/project-governance.yml):
  hosted runner, read-only contents, no persisted checkout credentials or GPU
  toolchain/submodule installation, bounded timeout and source-root checks.
  Its permissions do not describe every inherited workflow.
- [ ] Observe a hosted governance run on the relevant revision and retain its
  outcome. Local success does not establish hosted success; neither proves GPU
  arithmetic, physical memory operation or hardware readiness. Report inherited
  GPU CI separately, including failures, skipped work and unavailable environments.
- [ ] Before making a check mandatory in branch rules, verify its exact reported
  context and test both changed-path and skipped-path pull requests. Do not make
  a path-filtered workflow unconditionally required without a reviewed strategy
  that reports the appropriate result for every required case. Never hide a
  failed test or weaken coverage to satisfy branch protection.
- [ ] Change branch protection, Actions access, release permissions, environments
  or secret configuration only after the owner approves the specific settings.
  Apply least privilege, test the resulting workflow, and record what actually
  changed. Do not commit credentials, signed URLs or private environment dumps.
- [ ] Keep untrusted pull requests away from secrets and self-hosted hardware.
  Approve physical-runner access and resource budgets separately; retain failures
  and artifact provenance under the [developer policy](developer-guide.md).

## 4. Confirm security and release operations

- [ ] Verify a working confidential reporting route and an actual responder
  before advertising either. Follow [SECURITY.md](../../SECURITY.md); private
  reporting availability and response commitments must not be assumed.
- [ ] Before a release, identify its intended class and assemble the source,
  license/dependency inventory, artifact hashes, tested compatibility and evidence
  required by the [release policy](releases.md). An unversioned changelog entry
  does not create a release or approve its support claims.
- [ ] Obtain distinct human decisions for hardware access, procurement, licensed
  IP, foundry work and manufacturing. Review the [hardware plan](hardware.md),
  [open decisions](decisions.md) and [risk register](risks.md) before commitments.

## 5. Leave a concrete next action

After P00 is accepted, assign the P01 verification owner and begin **P01-T01**
(environment/provenance manifest), then **P01-T02** (bounded native test matrix).
Use the [backlog](backlog.md), [configuration candidate](configurations.md) and
[handoff template](handoff.example.md). Record the resource budget, unresolved
prerequisites, exact evidence and next owner; do not jump from setup to large
models, FPGA purchase or fabrication without the intervening gates.
