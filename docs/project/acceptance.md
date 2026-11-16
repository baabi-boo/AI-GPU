# Acceptance and evidence policy

A phase closes because its defined results have been demonstrated, not because
its documents, source files or assigned agent tasks exist. The canonical phase
dependencies, acceptance IDs, required levels, status and evidence references
live in [roadmap.json](roadmap.json). The [requirements](requirements.md) provide
traceability; the [verification plan](verification.md) defines test coverage.

## Evidence levels and scope

| Level | What it establishes | What it does not establish |
|---|---|---|
| `source_present` | Inspectable source, design/governance records or a reviewed plan | Successful GPU execution, numerical correctness or physical performance |
| `simulated` | A named workload ran in a specified software simulation environment | Native hardware datapath correctness, FPGA speed or power |
| `rtl_verified` | The specified RTL was exercised or assessed through the named verification/implementation flow | Physical FPGA operation or manufactured silicon |
| `fpga_measured` | Results were obtained on an identified physical FPGA configuration | ASIC frequency, power, yield or product readiness |
| `silicon_measured` | Results were measured on identified fabricated silicon and board revisions | Untested devices, configurations, conditions or general market parity |

Every record must name its scope, execution driver and arithmetic implementation.
For RTL, distinguish processor-only `rtlsim`, full-shell emulation, synthesis,
and timing/resource analysis. A synthesis report may support a resource gate;
it is not a numerical execution test. A DPI arithmetic implementation delegates
calculations to software and cannot satisfy a **native tensor datapath** gate.
XRT `hw_emu` is not physical hardware; physical runs must identify `hw` and the
actual device. Functional-only simulator timing is not physical throughput.

A higher level is not a universal substitute for a lower-level obligation.
Evidence must address the same criterion, workload and scope. For example, a
silicon photograph does not prove a clean build, and a physical GEMM pass does
not prove a framework's error handling. State unsupported or untested claims
explicitly. Source presence cannot be promoted by relabelling a record.

## Phase status and execution outcomes

| Phase status | Meaning |
|---|---|
| `not_started` | The phase's implementation/qualification work has not begun |
| `in_progress` | Work or partial evidence exists; not all exit obligations are met |
| `blocked` | A named dependency, tool, resource, decision or unresolved failure prevents progress or closure |
| `complete` | All dependencies and every acceptance criterion have compatible passing evidence and the required review/decision |

Partial completion remains `in_progress` or `blocked`; it is not a percentage
claim about the whole GPU. A completed phase can be reopened when its contract
changes or new evidence invalidates a result. Preserve the previous record and
explain the new blocker rather than rewriting history.

### Staged development entry versus phase acceptance

The optional `entry_acceptances` array in `roadmap.json` names specific,
reviewed acceptance results from another phase that must already have valid
passing evidence before this phase can be marked `in_progress` or `complete`.
The validator checks their real evidence references; missing, malformed, failed,
`not_run` and `blocked` reports cannot authorize entry. These prerequisite
acceptances do **not** change the source phase's status or waive its other
acceptance criteria. Full `depends_on` phase dependencies still govern **phase
completion**, while preparatory planning can proceed before those dependencies
close. The graph checks both dependency types for cycles.

In the current program, P02 uses P00 completion plus accepted P01-A01/A02 to
start native numerical development even while P01-A03 vendor hardware
emulation remains blocked. P07 additionally depends on P01 completion, so
P07 cannot be accepted until P01-A03 eventually passes. This is an explicit
sequencing decision, not new GPU or physical hardware evidence.

Evidence reports and individual commands use `pass`, `fail`, `not_run` or
`blocked`. `not_run` means no execution occurred. `blocked` identifies the
missing prerequisite; neither counts as a pass. A nonzero unexpected exit or an
unexplained correctness failure cannot be represented as a passing command.

## Acceptance procedure

1. **Freeze the contract.** Name the requirement and acceptance IDs, exact
   configurations, workloads, supported inputs, reference oracle, numerical
   tolerances, performance/resource bounds and exception policy **before**
   evaluation. Review changes to these contracts; do not loosen a bound after a
   failure to make it pass. Inherited goldens and tolerances remain protected.
2. **Confirm prerequisites.** Resolve dependencies and ownership, inspect the
   source revision and dirty state, pin tools/submodules/configuration, and
   approve the resource budget. Missing hardware, licenses or access are visible
   blockers. A preflight result does not certify that hardware works.
3. **Execute the declared tests.** Retain exact commands and exit results. Use
   matching application/backend configuration and current generated build files.
   Record native versus DPI arithmetic, CPU reference work, transfers and any
   explicitly permitted host operations; silent CPU fallback never qualifies.
4. **Preserve evidence.** Record the exact tested commit, configuration, scope,
   raw results, limitations and hash-checked artifacts using the
   [evidence format](evidence/README.md). Do not substitute a guessed commit or a
   different revision for an uncommitted test tree; make the tested source
   reproducible before claiming acceptance.
5. **Review independently where required.** Apply the inherited
   [review policy](../review/code-review-policy.md). The reviewer checks the
   source/configuration against the logs, test coverage, failure disposition,
   artifact integrity and claim scope. Record actual review and any required
   maintainer decision. An agent report is not an invented human approval, and
   agents cannot grant themselves waivers.
6. **Attach and close.** Add a report reference for each satisfied acceptance ID
   in the phase's `evidence` array. Mark the phase `complete` only when every
   dependency and criterion is satisfied. Update [status](status.md), remaining
   [backlog](backlog.md) items and the next bounded action in the same change.
7. **Verify delivery.** Review the final diff, run applicable checks, confirm the
   intended repository/branch and preserve concurrent changes. Record the actual
   published revision and remote verification without exposing credentials.

One report may cover several criteria if it contains distinct proof for each;
each criterion still needs its own roadmap evidence entry. Keep failed and
blocked records available for diagnosis. A later pass does not erase a failure.

## Mechanical validation is necessary, not sufficient

From the source root, the project checks are:

```sh
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

They check project structure, dependencies, evidence metadata, local references
and protected assets. A passing report must name an actual tested revision, a
non-pending reviewer, passing command evidence and hash-checked artifacts.
Complete phases require passing compatible reports for every acceptance ID.
Malformed referenced records are errors even if the phase is incomplete.

The checker does **not** observe a lab instrument, verify an operator's honesty,
establish scientific correctness or replace reviewer/maintainer judgment. It
does not automatically set phase status, grant approval, waive a failed gate,
or alter inherited GPU tests. A governance pass may support P00; it cannot
satisfy simulation, RTL, physical FPGA or silicon acceptance by itself.

## Hard stop conditions

- Missing mandatory execution, untraceable source/configuration, stale generated
  headers, unexplained numerical errors or missing native-datapath coverage.
- Silent fallback, substituted arithmetic, hidden transfers or incomparable
  workloads used to support an acceleration/performance claim.
- Changed goldens, weakened tolerances, silenced tests or unresolved required
  review findings without the policy's legitimate decision process.
- Missing physical-board evidence required by P07/P08/P09, missing qualified
  feasibility and human go/no-go decisions for P10, or missing manufacturing
  sign-off, funding/procurement authority and silicon lab evidence for P11.
- Credentials, private keys, signed access URLs, sensitive machine paths or
  unlicensed model/PDK/IP material in an evidence packet.

Describe the blocker and the precise next action; do not relabel it as success.
P00 is repository foundation only. P01–P11 earn their own evidence, and P09 is
not a prerequisite for the bounded inference-ASIC path through P10.
