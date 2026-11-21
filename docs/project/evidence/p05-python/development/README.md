# P05 development history

These receipts retain the actual worker reports from this continuation. Each
report describes its own source snapshot, executed checks, failures and limits.
Later corrections supersede earlier implementation choices without relabelling
earlier tests as executions of new code. Host fake-runtime tests do not establish
accelerator arithmetic, and inert bundle fixtures do not qualify native artifacts.

## Completion accounting

<!-- BEGIN COMPLETION STATUS -->

The [completion ledger](agent-ledger.json) records **60 distinct completed
worker assignments across ten logical waves of six**. Follow-up turns are not
additional agents, and the coordinating root is not counted as a worker. Each
entry identifies its actual task path and retained receipt size and SHA-256.
The ledger was emitted only after the final coordinator observation listed all
sixty tasks with receipts present, all original receipts matched their retained
copies, and the first thirty historical receipt identities remained unchanged.

<!-- END COMPLETION STATUS -->

The [initial checkpoint](initial-receipts.json) records thirty completed
assignments from waves one through five. Its manifest and all thirty receipt
bodies remain byte-identical to the first implementation commit. Later receipts
retain the actual corrections, bounded checks and independent review; they do
not replace the earlier checkpoint or expand its tested source scope.

The [ledger builder](build_agent_ledger.py) refuses an incomplete or duplicated
assignment inventory, a missing or extra receipt, an original/copy mismatch,
or changed initial checkpoint bytes. It records exact task paths, hashes,
sizes, line counts and six assignments per wave. Coordinator observations and
worker receipts are the completion evidence; the utility does not authenticate
the agent service or turn assignment counts into technical acceptance.

## Work and preserved findings

Independent fifth-wave reviews found stale-header build inputs, dynamic-loader
path grammar, public state-error mapping, mismatched tool roots and malformed
native-report handling. Their receipts bind the reproductions and reviewed fixes.
The primary agent also corrected the stale P05 state in the root README and
ROADMAP; P05 remains in progress and its framework gate remains unearned.

Waves six and seven verified the corrected native boundary and packaging,
reviewed publication, and developed three independent retained-data auditors.
Adversarial review found and repaired numerical-marker, command-membership,
allocation/state/timing and provenance/resource checks. Original failures,
initial auditor bodies and unchanged bounded rechecks remain in
[review history](../reviews/README.md).

Wave eight independently reviewed numerical, dispatch and provenance evidence
for each format. Wave nine reconciled the complete matrix, reviewed bounded
P05-A01 acceptance, updated the handoff and compatibility guides, replayed the
original archives from a fresh location, and verified source boundaries. The
final wave reviews acceptance, the public interface, auditor enforcement,
governance, completion accounting and delivery readiness.

The [host validation history](host-validation.md) preserves the failed local
source-changing full suite and its incomplete causal evidence, the inherited
workload-start assertion and isolated passing recheck, baseline configure
timeout, metadata leakage reproduction and reviewer-harness corrections. The
clean hosted 2,174-test pass at
`e1420fd550f716df33a2556057b7086a03032cbe` has its own source identity. The
107 compiled fake-runtime scenarios and eleven probes remain host-only
lifecycle/error evidence and are not added to an inflated aggregate test total.

The [installed SimX packet](../README.md) records the separate actual native and
Python routes: 144 launches and 660 event/profile pairs across both formats.
Only the bounded copying binding and clean installation earned P05-A01;
P05 remains `in_progress`, A02/A03 remain unearned, and scoped PyTorch custom
operators require their own versioned contract, implementation and evidence.
Vendor XRT `hw_emu` and the inherited DSP area finding remain unresolved.

Absolute scratch paths in original receipts identify where a development check
ran. Only evidence explicitly retained in this packet is promised here; native
qualification and clean hosted source-suite results have their own linked
records. Subdirectories under `host/` and `qualification/` retain the selected
raw commands, scripts, outcomes and inventories named by those records; expanded
temporary or counterexample packet trees are not duplicated here.

## Rechecking the ledger

Once finalization has written the ledger, verify its retained receipt identities
from the repository root without the original scratch directories:

```sh
python3 -B docs/project/evidence/p05-python/development/build_agent_ledger.py verify
```

The root finalizer uses `build` with the completed coordinator spawn JSON and
the original receipt directory. It creates a fresh ledger only after all checks
pass and then replaces the completion paragraph above. An existing completed
ledger is preserved; subsequent checks use `verify`. Publication, technical
acceptance and future source changes remain separate from this completion record.
