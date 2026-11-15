# P00 — Project foundation

Live status, dependencies and authoritative acceptance criteria are in
[roadmap.json](../roadmap.json). Accountable role: **Project maintainer**.

## Goal and boundary

Give AI-GPU a truthful, enforceable development contract and a usable handoff.
This phase prepares the project; it does not implement new tensor hardware,
run an AI model, validate an FPGA or authorize chip manufacturing.

## Entry conditions

- No predecessor phase is required.
- Resolve the target repository/default branch and inspect its current commit.
- Preserve existing edits, upstream provenance, licensing, assets and tests.
- Read [AGENTS.md](../../../AGENTS.md) and the inherited
  [review policy](../../review/code-review-policy.md).

## Ordered work packages

1. **Inventory:** record the source baseline, inherited capabilities, known
   limitations and the original README illustration checksum.
2. **Define the target:** establish the charter, requirements, scope boundaries,
   owner roles, unresolved decisions and risk register.
3. **Plan delivery:** give each phase dependencies, concrete work packages,
   acceptance identifiers, required evidence and blocking conditions.
4. **Make progress inspectable:** establish current status, a prioritized
   backlog, evidence records and the next bounded implementation task.
5. **Enforce consistency:** add offline metadata validation and negative tests;
   keep governance checks separate from inherited GPU correctness gates.
6. **Review and publish:** resolve independent review findings, inspect the final
   diff, publish only to the authorized repository and verify the branch head.

## Deliverables

- Project-facing README with the existing GPU/framework illustration preserved.
- [Charter](../charter.md), [baseline](../baseline.md),
  [requirements](../requirements.md) and [decisions](../decisions.md).
- [Roadmap](../../../ROADMAP.md), phase documents and canonical phase manifest.
- [Developer guide](../developer-guide.md), [status](../status.md),
  [backlog](../backlog.md), acceptance policy and evidence-record conventions.
- Lightweight validator, its tests, contribution guidance and review records.

## Exit acceptance

| Gate | Observable proof | Evidence level |
|---|---|---|
| `P00-A01` | Navigation, scope, evidence labels and roles are documented; links resolve and the original image hash matches. | `source_present` |
| `P00-A02` | Offline validation and positive/negative unit tests pass without a GPU toolchain. | `source_present` |
| `P00-A03` | Independent findings are resolved and a remote readback verifies the delivered commit on the intended branch. | `source_present` |

From the source root, record these checks with their actual exit results:

```sh
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
git diff --check
```

## Evidence, stop rules and handoff

Retain the tested revision/tree, exact commands, results, image checksum,
independent review dispositions and publication readback under the
[acceptance policy](../acceptance.md). A requested agent count is not evidence
of a completed review or a functioning GPU.

Stop closure for broken links/dependencies, changed protected assets, unsupported
capability claims, unresolved required findings or an unverified remote update.
Do not weaken inherited gates or install a GPU toolchain to make metadata pass.

Handoff to [P01](p01-baseline.md): select a verification owner and a bounded,
resource-reviewed native baseline configuration. P00 completion must not change
any later phase to complete or turn inherited test definitions into results.
