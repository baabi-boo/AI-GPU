# Development handoff template

**Template only — not a completed task, approval or acceptance report.** Copy
the structure into the relevant work item or a uniquely named handoff record.
Replace every placeholder with an observation, or explicitly write `not_run`,
`blocked`, `unknown` or `not_applicable` with its reason. Keep secrets, private
machine paths and signed access URLs out of the record.

## Identity and bounded scope

- Work item / phase / acceptance IDs: `<IDs>`
- Actual author and reviewer; review independence: `<identities and scope>`
- Repository and intended branch: `<owner/repository; branch>`
- Exact starting and tested source commits / tree: `<full identifiers>`
- Working-tree state and any uncommitted inputs: `<observed state>`
- Goal, deliverables and explicit non-goals: `<bounded scope>`
- Dependencies and actual authority/access required: `<resolved or blocked>`

A baseline commit does not identify later uncommitted files. Make the tested
source reproducible before attaching passing phase evidence. A role title or
agent report does not stand in for a human procurement/manufacturing approval.

## Configuration and resource record

- Toolchain/submodule versions and resolved commits or bundle hashes: `<values>`
- Generated configuration, application/backend flags and artifact hashes: `<values>`
- Driver and arithmetic backend: `<SimX / native RTL / DPI / full AFU / other>`
- For physical work, exact target/device/platform/bitstream and conditions: `<values>`
- Workload/fixture/seed/shape/dtype, reference and frozen tolerances: `<contract>`
- Approved disk, effective RAM, job, elapsed-time and trace-retention budget: `<limits>`
- Resource observations and stop conditions: `<measurements and unresolved limits>`

Tool presence and host memory figures are prerequisite observations, not hardware
qualification or proof of the effective container allocation. Name any missing
licenses, tools, platform, device or approved spending before proceeding.

## Changes and verification

List changed paths, their purpose and affected consumers. Preserve unrelated
work, licenses, protected assets, inherited coverage and golden baselines.

| Command or read-only observation, with working directory | Outcome | Observed exit code | Log/artifact and SHA-256 | Exact scope / limitations |
|---|---|---|---|---|
| `<exact invocation>` | `not_run` | `null` | `<not produced>` | `<why not run>` |

Use `pass`, `fail`, `not_run` or `blocked`; never infer a pass from source
presence. Separate governance checks, simulated execution, native RTL, full-AFU
emulation, physical FPGA and silicon results. Record failed experiments and
unsupported cases as well as successful ones. A template row is not evidence.

## Review and acceptance disposition

- Impact class and independent-review scope: `<classification and rationale>`
- Findings, severity, reproducer and disposition: `<resolved / open / blocked>`
- Accepted report paths and covered gate IDs: `<references, or none>`
- Remaining gates/dependencies and exact missing evidence: `<items>`
- Any actual required maintainer/human decision: `<record, or pending>`
- Phase/status changes justified by the evidence: `<changes, or none>`

Follow [acceptance](acceptance.md) and the [report contract](evidence/README.md).
Do not grant yourself a waiver, convert an unexecuted check into success, or
mark a phase complete while required evidence/dependencies remain unresolved.

## Source control and delivery

- Local commit(s), or explicit uncommitted state: `<observed identifiers>`
- Remote head checked before publication: `<repository/branch/SHA>`
- Publication outcome and actual delivered commit: `<verified / failed / not_run>`
- Readback observation and any concurrent changes preserved: `<result>`
- Hosted CI status at the observed revision: `<run URL/status, or not_run>`

Do not label a commit pushed until the intended remote branch has been read
back. Local test results and hosted CI results are separate observations.

## Next bounded action

State one next action with its owner, prerequisite, exact intended deliverable,
verification command/criterion, resource cap and stop condition. Link the
relevant [backlog](backlog.md) item and phase guide. Update
[status](status.md) and the canonical [roadmap](roadmap.json) consistently;
leave the next contributor able to continue without reconstructing a chat.
