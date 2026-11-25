# Qualified warm automation v1

## Purpose and existing experiment

Automation composes the existing qualified warm route from one selected source
revision. It does not change the measurement contract, qualification proof,
historical prerequisites, native application or performance predicates.
See [qualified warm v1](qualified_warm_workspace_v1.md) for the experiment and
the [execution runbook](../project/evidence/p06-qualified-warm/runbook.md) for its
existing direct composition.

The seven helpers and manual workflow are implemented; their focused validation
and source-scoped reviews are recorded in the
[tooling evidence packet](../project/evidence/p06-hosted-warm-automation/README.md).
Select the published revision's actual full strict Actions result before a
manual attempt. Focused fixtures and an earlier revision's green run do not
establish that result or a fresh native execution.

The complete population remains 24 fresh processes, 792 launches and 25,344
checked FP32 words. The measured subset remains 20 processes and 640 operations.
FP16 and BF16 must each be evaluated against every frozen predicate. A valid
complete original may fail the performance hypothesis.

## Separate operations

| Operation | Result and scope |
| --- | --- |
| Input acquisition | Exact original ZIP identities, locked archive parts and dependency Git objects; no extraction, compilation or native launch |
| Supervised run | Fresh preparation, dependency build and qualified native execution; raw child records and failure-preserving orchestration receipt |
| Packaging | Byte-conserving copies and inventories after recorded writers finish; no native execution or acceptance |
| Inert replay | Existing complete original reader reconstructs the independently selected source/report/archive identities |
| Hosted delivery | Provider context around the same local producer records; source and output privacy boundaries remain explicit |

The new wrapper's `orchestration_passed` describes reconciliation of child
execution and retained records. It is not an independent replay result or
provider authentication. The native report's `qualified_warm_passed` describes
the complete recorded population; hosted top-level `qualified_warm_passed` and
`counter_qualification_passed` remain false. Historical acceptance fields remain
false. A complete, correctly retained experiment can yield a green hosted job
and an independently replayed `not_satisfied` performance hypothesis.

## Inputs and resource invariants

Use one exact published 40-character source revision, a clean dedicated checkout
and the recorded eight recursive gitlinks. New acquisition and execution roots
must be disjoint and absent before use. Do not resume or combine prior attempts.
The source checkout remains unchanged as tracked source while permitted
dependency products and native build outputs are produced in their established
locations.

Acquire only the existing locked toolchain parts and dependency revisions.
Verify all raw part sizes, SHA-256 digests and Git object identities. Preserve
partial inputs after failure. The diagnostic and attempt-04 control ZIPs remain
external immutable inputs and are neither repaired nor reconstructed.

Preserve two build jobs, one simulation worker, the 15 GiB free-disk reserve,
4 GiB available-memory admission, 4 GiB sampled process-group RSS limit,
120/1,800/180-second native configure/build/process limits and 16 MiB per-child
log limit. The orchestration wrapper adds the existing 90-minute polled outer
budget. Sampling, filesystem snapshots and a recorded cleanup result are not
hard resource reservations or complete descendant containment.

Read-only capacity observations must distinguish visible cgroup bounds from
proof of complete hierarchy visibility. Missing or malformed observations do
not establish unlimited allocation. Do not change the existing readiness
screen's acceptance meaning or let an advisory report authorize native work.
Supported absence of non-root memory interfaces at a visible cgroup-v2 root
does not establish complete ancestry or an unlimited effective allocation.

## Failure and retention

Create receipts and outputs exclusively. Record commands, raw logs, reports,
source/interpreter/input identities, actual exit outcomes and cleanup results.
Check child terminal output against the original report. Read the larger warm
report with the existing bounded qualified-report decoder. Reject missing,
partial, reordered or substituted process populations.

Native execution is `not_run`, `unknown` or `run` according to observed child
evidence; launching a supervisor alone cannot prove that GPU work ran. A failed
attempt keeps successful earlier stages at their original scope and records the
failed or unavailable later stages without inventing them.

The complete replay ZIP has exactly the two existing roots `dependency-build/`
and `qualified-warm/`. Keep orchestration, acquisition and hosting observations
in a separate envelope. Partial packaging does not establish completeness or
qualification and must not be represented as a qualified complete original.
The complete reader rejects its default outer layout. A partial ZIP containing only the two native
subtrees can reach the existing semantic verifier with explicit
`--prefix partial-attempt/evidence`; every frozen native, dependency,
prerequisite and source check remains mandatory. Explicit subtree selection
never substitutes for complete independent replay. The
[packaging/replay review](../project/evidence/p06-hosted-warm-automation/reviews/A47.md)
records this structural limit; no genuine fresh original has been replayed.
Retain hidden regular files and opaque outputs; reject symlinks, special files
and noncanonical names. Hash original files before and after copying and
independently reread the ZIP.

Hosted closeout attempts packaging and encryption of the selected
`attempt/retention/` tree, including its `packet/` products, packaging log and
pre-encryption closeout receipt. Fetched
archive/Git inputs, installed tools, final post-encryption records and encryption
failure diagnostics outside that tree remain private local files. Packaging
failure can leave only a subset of copied evidence in the selected tree;
encryption cannot establish completeness that packaging did not establish.
An unknown launch (`process_started=null`) or unresolved cleanup blocks
packaging and encryption. Confirmed prelaunch `false` with completed cleanup
can close out only if its encryption tools, recipient and retention capacity
are available. Missing workflow configuration prevents checkout and creates no
attempt packet. Governance preflight or pinned-Python setup failure permits
best-effort local closeout after checkout, but `host_setup` rejects before age
provisioning; those local bytes cannot use the absent fresh age path for
encrypted delivery. Composition mocks do not prove otherwise.

Failed withdrawal of an owned packaging success receipt can leave that receipt
and its verified final ZIPs after a failed invocation. Reconcile invocation and
hosted-closeout status with the failure receipt; a success-shaped receipt alone
does not establish packaging success. Duplicate surviving receipt hardlinks can
fail encryption's single-link inventory admission. Preserved packaging failures
are not necessarily encryptable.

Encryption recovery can leave a valid public-named ciphertext and summary after
interrupted cleanup following commit. Upload still requires a successful
invocation and full hosted validation, not file existence or a pass-shaped
summary. Only successfully uploaded validated ciphertext and its sanitized
summary establish durable hosted delivery. Recovery is best effort, not an
atomic multi-file crash transaction or complete writer exclusion.

The workflow's `!cancelled()` prevents starting hosted work after observed
cancellation. Active closeout and delivery remain best effort; a previously
validated pair may upload if the `always()` upload step is reached. The actual
provider conclusion remains authoritative for cancellation. The
[operator failure matrix](../project/p06-hosted-warm-guide.md#failure-and-delivery-matrix)
and [failure-retention review](../project/evidence/p06-hosted-warm-automation/reviews/A48.md)
record these boundaries. Do not report runner-local files as durable artifacts.
The selected hosted envelope includes bounded private source snapshots of the
wrapper's helper closure, hosted helpers and workflows, with repeated identity
checks. Upload requires the hosted helper's validated ciphertext/summary result;
successful encrypted retention of a partial attempt does not pass native work.

## Private artifact boundary

The target repository is public. The historical control original and freshly
retained Ramulator dependency sources include vendor verification-model files
with proprietary/confidential notices. Raw full packets are not cleared for
public redistribution. Their historical identities must remain unchanged.

Private prerequisite transport must not place access tokens or signed URLs in
arguments, public workflow inputs, terminal output or retained records. A
configured transport credential selects only the exact raw original; it grants
no permission to run its retained code. Hash and size checks remain mandatory.

A hosted workflow must not publish plaintext prerequisite archives, native
reports, source copies or partial logs to this public repository's artifacts.
Use separately configured private storage or encrypt complete retention for an
explicit recipient before public artifact upload. Missing delivery configuration
must block before acquisition or native work. Public status may report only
the selected revision, stage outcomes, bounded counts and encrypted artifact
identities. Do not silently discard private failure evidence to obtain a green
job.

Encryption is a retention operation with its own conservative ciphertext-byte
capacity bound plus a 64 MiB margin. It does not admit native execution or lower
the 15 GiB acquisition/build reserve. This distinction allows a small failure
packet to be retained after native work stops at that reserve. If even the
bounded encrypted output cannot fit, preserve private local failure evidence
and fail publication explicitly.

## Review and acceptance

Review new orchestration, acquisition and workflow trust boundaries
independently. Development fixtures exercise control flow and failure handling;
they are not native execution. A source change requires its own validation.
The manual hosted workflow accepts no arbitrary revision input: it selects the
trusted repository's `master` provider SHA and requires a successful complete
Project Governance job for that exact revision before prerequisite acquisition
or native work. An earlier revision's success cannot qualify changed automation.
Provider status checks are followed by the
[governance-original reader](governance_artifact_replay_v1.md): exact artifact
identity and bytes, complete canonical event accounting, source/environment/log
joins and independently collected trusted-source IDs must all pass. Provider
run/attempt/job observations and source identity are rechecked afterward. The
composition retains the original and scoped replay receipts under its existing
private hosted envelope; standalone preflight discards its owned temporary copy.
This enforces original consistency and source binding before native work while
preserving independent reviewer judgment.

No automation result alone closes P06-A02/A03, XRT integration, physical FPGA
qualification, synthesis/resource obligations or phase acceptance.
