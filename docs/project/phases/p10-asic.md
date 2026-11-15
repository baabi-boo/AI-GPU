# P10 — ASIC feasibility and sign-off planning

**Goal:** make an evidence-backed go/no-go decision for a bounded inference ASIC.
The live status, dependencies and authoritative gate text are in
[roadmap.json](../roadmap.json); the accountable role is Silicon program lead.
This phase plans a possible silicon program; it does not authorize purchases.

## Entry and boundaries

- P08 must be complete with a hardened, reproducible physical FPGA prototype.
  Preliminary research can begin earlier, but cannot satisfy this phase's exit.
- P09 training/multi-device research is **not** a prerequisite for this bounded
  inference ASIC. Do not expand the first chip to cover unproven research goals.
- Carry forward the accepted numerical, software, memory and model contracts;
  select a manufacturable implementation rather than silently changing them.
- The [inherited synthesis flows](../../synthesis_analysis.md) are useful inputs,
  not proof of production readiness. Predictive libraries, black-box SRAM,
  pre-layout PPA estimates and generated GDS do not establish foundry sign-off.
- Process node, memory technology/capacity, package, suppliers, budget and dates
  remain decisions until supported by qualified evidence and human approval.

## Ordered work packages

1. Freeze a bounded target configuration and inference workload. Specify host
   interface, usable memory, power/thermal envelope and measurable success goals
   through reviewed decisions; distinguish requirements from current estimates.
2. Assign actual qualified owners for architecture, verification, physical
   design, DFT, package/board, test and procurement. Document access to the
   foundry process design kit (PDK), licensed tools and required partner support.
3. Build an IP/dependency register for standard cells, real SRAM macros, clock/
   reset infrastructure, PCIe, and the selected memory controller and PHY.
   Check license, integration interfaces, availability, delivery and cost evidence.
   HBM additionally requires a viable package/interposer, assembly and supply plan.
4. Produce a reviewed implementation/sign-off plan: functional and formal
   verification, clock/reset-domain crossings, equivalence, scan/DFT/MBIST,
   floorplan, clock trees, timing corners, power integrity, DRC/LVS and package
   interfaces. Replace black-box assumptions with qualified components before
   treating a report as sign-off; label exploratory PPA reports as estimates.
5. Plan board power sequencing, signal integrity, cooling, debug and manufacturing
   test access together with the package. Define bring-up fixtures and safe lab
   procedures before fabrication; identify remaining risks and contingency work.
6. Assemble written supplier/partner availability and cost information, staffing,
   schedule assumptions, risk disposition and procurement authority. Obtain a
   recorded human go/no-go decision before any tapeout commitment or paid order.

## Deliverables and acceptance

| Gate | Required deliverable and proof | Evidence level |
|---|---|---|
| `P10-A01` | Reviewed dependency register with qualified PDK/SRAM/interface IP/package/tool owners and written availability/cost evidence | `source_present` |
| `P10-A02` | Bounded design and complete physical-design, verification, DFT, timing and power-integrity sign-off plans; estimates explicitly labelled | `source_present` |
| `P10-A03` | Recorded human approval of scope, funding, schedule, procurement, accountable owners and external partners | `source_present` |

These are documentary feasibility gates, not hardware measurements. Preserve
reviewed report versions, configuration/source hashes, assumptions, open risks
and the decision record. Protect commercial PDK/IP, confidential quotes and other
restricted materials; store only authorized summaries and durable evidence
references in the repository. Follow [hardware](../hardware.md),
[risks](../risks.md) and [acceptance](../acceptance.md).

## Stop conditions and handoff

Block exit for missing qualified IP/macros, unresolved licensing, unsupported
physical assumptions, absent sign-off ownership, unbounded cost/schedule risk or
missing human authorization. Repository development permission is not purchasing,
partner-negotiation or manufacturing authority; agents cannot approve spending.

Hand [P11](p11-silicon.md) the approved scope, funded ownership, dependency/IP
register, signed decision and executable sign-off/bring-up plan. The next bounded
action is to complete qualified implementation and verification, not to fabricate
an unreviewed layout. Record blockers in [status](../status.md) and
[backlog](../backlog.md).
