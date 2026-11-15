## Summary and scope

<!-- What changes and why; include non-goals and affected consumers. -->

**Work item / phase / acceptance / requirement IDs:**

**Exact tested revision and configuration:**

**Dependencies and remaining blockers:**

## Impact and review

See [review policy](https://github.com/baabi-boo/AI-GPU/blob/master/docs/review/code-review-policy.md) and
[acceptance policy](https://github.com/baabi-boo/AI-GPU/blob/master/docs/project/acceptance.md).

**Impact class:** R? <!-- Classify the verified base-to-head diff; explain disagreements. -->

**Review base / head:**

**Contracts touched:** pending <!-- Interfaces, ISA/configuration, installed/shared ABI, workflow or enforcement; name every affected consumer, or justify none. -->

**Independent reviewer and disposition:** pending <!-- Required for R3; not the author. -->

**Maintainer approval / required decisions:** pending <!-- Record actual approvals; an agent report is not human approval. -->

For `.github/**` or `.gitattributes` changes, attach the base revision's locally
run classifier result. The modified workflow's summary is not trusted evidence.

## Execution evidence

| Evidence | Status | Exact scope, command, result and artifact reference |
|---|---|---|
| Governance preflight / project validator / unit tests | run / not run / failed / n/a | Source-root checks; explain exclusions |
| Functional tests (simx / rtlsim / xrt) | run / not run / failed / n/a | Driver, arithmetic backend, configuration and reference |
| `model_parity` | run / not run / failed / n/a | Case names; cycle gap |
| `perf_gate` | run / not run / failed / n/a | Any human-run baseline update and measured reason |
| Beacon `logic_gate` | run / not run / failed / n/a | DUTs; deeper units and why |
| Synthesis (`fpga_gate` / `asic_gate`) | run / not run / failed / n/a | Flow, assumptions and achieved results |
| XLEN 64 build | run / not run / failed / n/a | Exact build configuration |
| Physical FPGA / silicon, when claimed | run / not run / failed / n/a | Device, target, bitstream/revision and measurement scope |
| GitHub-hosted CI | run / not run / failed / pending | Link actual run; distinguish local results |

A `not run`, blocked or pending item is not a pass. Explain every missing
applicable run and every `n/a`. Record command exit codes and raw evidence;
a successful process exit alone does not prove numerical correctness.
Distinguish native tensor arithmetic from DPI, processor RTL from full AFU,
and emulation from physical hardware. Report any permitted host work explicitly.

**Phase evidence reports and hash-checked artifacts:**

**Untested cases, limitations and unresolved findings:**

**Resource budget / access / spending approvals, if needed:**

## Preservation and handoff

- [ ] No test silenced (`known_issue:`, wider tolerance, smaller arguments or removed case) without the policy-required measured reason, root-cause plan and approval.
- [ ] Golden data changed only through its prescribed human-run update command, named in the commit message; no agent/CI regeneration.
- [ ] Cycle-moving RTL changes carry the matching SimX change, or named parity evidence showing no cycle change.
- [ ] A toolchain pin moves only after matching prebuilt artifacts exist.
- [ ] Original README illustration/embed, licensing, provenance and inherited functionality are preserved.
- [ ] Relevant phase evidence, status and backlog are updated; completion claims meet every dependency and acceptance gate.
- [ ] Required review findings and maintainer decisions are resolved, or a legitimate maintainer-granted waiver is explicitly recorded under policy.

**Next bounded action and handoff owner:**

**Publication target and authorization:** <!-- Verify repository, branch and current head before merge; do not presume direct-push authority. -->

**Verified published revision:** pending <!-- Fill only after actual remote readback. -->
