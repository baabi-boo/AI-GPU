# AI-GPU project documentation

This is the development plan and evidence hub for AI-GPU. The inherited Vortex
implementation is documented in the [technical reference](../index.md).
Plans describe work to earn; source files and documentation alone do not prove
that a GPU workload or physical device has passed its checks.

## Choose a starting point

| Your question | Read first | Continue with |
|---|---|---|
| What are we building? | [Plain-language overview](../../README.md), [charter](charter.md) | [Roadmap](../../ROADMAP.md), [current status](status.md) |
| What should I work on next? | [Developer guide](developer-guide.md), [backlog](backlog.md) | [Architecture](architecture.md), [contribution process](../../CONTRIBUTING.md), [agent rules](../../AGENTS.md) |
| What would prove this works? | [Acceptance policy](acceptance.md), [verification strategy](verification.md) | [Evidence format](evidence/README.md), [benchmark protocol](benchmarks.md), [review policy](../review/code-review-policy.md) |
| How does this become real hardware? | [Hardware plan](hardware.md), [physical FPGA phase](phases/p07-fpga.md) | [Risks](risks.md), [decisions](decisions.md), [ASIC feasibility](phases/p10-asic.md) |

Before continuing existing work, check the current source revision and local
changes, then read [status](status.md). Do not treat an old conversation or an
unexecuted template as a completion record.

## Plan, provenance and current work

- [Charter](charter.md): mission, first useful milestone, scope and non-goals.
- [Baseline](baseline.md): exact inherited source, capability boundaries,
  dependency pins and preserved illustration.
- [Requirements](requirements.md): stable requirements mapped to acceptance IDs.
- [Human-readable roadmap](../../ROADMAP.md): development sequence and phase links.
- [Canonical roadmap](roadmap.json): authoritative phase IDs, dependencies,
  criteria, evidence levels, live status and evidence references.
- [Current status](status.md): observed results, blockers and the next bounded action.
- [Backlog](backlog.md): ordered work items with deliverables and gate mappings.
- [Decisions](decisions.md): accepted setup directions and unresolved choices.
- [Risk register](risks.md): triggers, mitigations, responsibilities and stop gates.

The roadmap JSON owns the phase contract. Status explains the handoff; the
backlog selects work. Keep them consistent when a result or decision changes.
An accountable role in a plan does not assert that a person or budget is assigned.

## Engineering and qualification

- [Architecture](architecture.md): existing boundaries and the native execution path.
- [Software plan](software.md): operators, model execution, Python and framework scope.
- [Hardware plan](hardware.md): real memory, FPGA integration, ASIC and board obligations.
- [Developer guide](developer-guide.md): lightweight checks, pinned environments,
  out-of-tree builds and resource limits.
- [AI configuration candidate](configurations.md): opt-in native profile, source
  provenance and qualification still required before any execution claim.
- [Project CI contract](ci-contract.md): lightweight checks versus inherited GPU
  CI, resource limits, trust boundaries and hosted-result reporting.
- [Verification strategy](verification.md): references, coverage and backend distinctions.
- [Benchmark protocol](benchmarks.md): frozen workloads and honest performance accounting.
- [Acceptance policy](acceptance.md): evidence, review, phase closure and stop conditions.
- [Release policy](releases.md): versioned artifacts, reproducibility and qualified claims.
- [Security policy](../../SECURITY.md): experimental trust boundaries and reporting.
- [Maintainer checklist](maintainer-checklist.md): actual approval, repository
  settings, CI adoption, confidential reporting and release decisions.
- [Changelog](../../CHANGELOG.md): unreleased changes and preserved foundations.

Simulation, native RTL, physical FPGA and fabricated silicon are different
evidence scopes. A governance check does not certify any of those execution
results. Follow the relevant phase gates before making a capability claim.

## Detailed phase guides

These guides contain entry conditions, ordered work, deliverables, acceptance
and handoff instructions. Consult the [roadmap](../../ROADMAP.md) for dependencies
and [roadmap.json](roadmap.json) for live status; the grouping below is navigation,
not a substitute dependency graph.

**Foundation and first native model**

- [P00 — Project foundation](phases/p00-foundation.md)
- [P01 — Reproducible baseline](phases/p01-baseline.md)
- [P02 — Tensor numerical contract](phases/p02-tensor.md)
- [P03 — AI operator library](phases/p03-operators.md)
- [P04 — Tiny-model inference](phases/p04-inference.md)

**Usable software and a measured prototype**

- [P05 — Python and framework integration](phases/p05-framework.md)
- [P06 — Memory and performance scaling](phases/p06-performance.md)
- [P07 — Physical FPGA prototype](phases/p07-fpga.md)
- [P08 — Reliability and release hardening](phases/p08-reliability.md)

**Separately gated research and silicon**

- [P09 — Training and multi-device research](phases/p09-research.md)
- [P10 — ASIC feasibility and sign-off planning](phases/p10-asic.md)
- [P11 — Funded silicon realization and bring-up](phases/p11-silicon.md)

P09 is not required for the bounded inference-ASIC path. P10/P11 still require
qualified specialists, physical implementation evidence and explicit human
funding/manufacturing decisions; a roadmap does not authorize purchases.

## Evidence and continuation records

- [Vendor XRT integration](p01-xrt-integration.md): prepared-artifact manifest,
  bounded host/kernel build and explicit `hw_emu` smoke execution.
- [Vendor integration handoff](p01-xrt-handoff.md): implementation, actual checks,
  remaining prerequisites and publication state for the P01-T05 continuation.
- [Evidence guide](evidence/README.md): record fields, artifact integrity and retention.
- [Acceptance report template](evidence/report.example.json): **unexecuted**, not proof.
- [Benchmark specification template](evidence/benchmark.example.json): **unmeasured**
  experiment planning, not an acceptance report.
- [Handoff template](handoff.example.md): exact source, actual outcomes, limitations,
  publication state and the next action.
- [Agent execution ledger](agent-execution.json): completed setup assignments;
  worker counts are not GPU qualification evidence.

Return to the [repository overview](../../README.md) or the
[inherited technical documentation](../index.md) for subsystem implementation details.
