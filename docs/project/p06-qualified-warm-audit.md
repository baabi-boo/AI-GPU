# Qualified warm-workspace development audit

## Starting evidence and priority

This continuation starts at published `master`
`f80b58b06e7bcf734f3190f6db478fd11f0bab01`. The live GitHub head and
the project-specific personal-context handoff agree. The source checkout was
clean; governance preflight and `check_project.py` passed. Existing phase
acceptances remain the authority for their own scopes.

The next bounded task is an explicitly selected, independently reviewed route
for the frozen 24-process warm-workspace experiment. The preceding four-process
counter qualification cannot qualify future processes. P05 framework review is
a separate open branch; vendor XRT integration remains blocked and cannot be
replaced by this SimX experiment.

The frozen experiment retains FP16 then BF16, one warm-up pair and five measured
pairs per format, alternating allocation-policy order, and 33 operations in
each fresh process. Complete population: 24 processes, 792 launches and 25,344
checked output words. The measured population is 20 processes and 640 operations.
The median candidate host time must be at most 95% of reference; no measured
candidate pair may regress in host time or modeled cycles, and both formats
must improve. These are experimental predicates, not phase acceptance.

## Audit findings before implementation

1. The native managed-preflight caller rejects every phase/pair except pair zero
   warm-up, and its two witness process identities are hardcoded to preflight.
   Changing only the Python runner would fail on the first measured pair.
2. That native caller belongs to the immutable qualification proof's 69-source
   projection. A new caller requires an explicitly pinned and independently
   reviewed projection extension. The historical proof and original diagnostic
   and control archives must remain unchanged.
3. The complete dependency/lifetime reader already supplies most provenance,
   build, loader, raw-record and lifecycle checks. Its remaining fixed population,
   command count, invocation arguments and identity rules need explicit extension
   points with historical defaults preserved.
4. The historical warm analyzer deliberately rejects full qualification. The
   new route must derive its own qualification from complete evidence and may
   reuse frozen arithmetic only after validation. Packet metadata must never
   choose the trusted reader route.

## Work organization

All **60 actual worker assignments completed across ten waves of six**. The
session permits three workers concurrently, so assignments were batched and
pipelined. The [execution ledger](evidence/p06-qualified-warm/execution-ledger.json)
identifies each distinct worker, completed task, scope and hashed report.
Same-worker follow-ups and supplemental probes are not additional workers, and
the coordinator is excluded. Production ownership was disjoint.

| Wave | Scope |
| --- | --- |
| 1 | Current implementation, source proof, replay, experiment and execution audit |
| 2 | Native route, contract/projection, producer, records, reader and analysis |
| 3 | Independent source and implementation review |
| 4 | Adversarial identity, population, lifetime, provenance and compatibility checks |
| 5 | Integration and complete-route verification |
| 6 | Exact clean checkout, bounded supervisors and resource readiness |
| 7 | Measurement meaning, operator procedure, stability and claim boundaries |
| 8 | Historical compatibility, packaging and corrected exhaustive test setup |
| 9 | Delivery documents, CI observations, test accounting and agent-ledger checks |
| 10 | Independent final delivery, source, outcome and resumption reviews |

Waves six onward were adapted after independent resource review blocked native
launch. No worker report is substituted for a missing native observation.

## Implementation checkpoint

The explicit route is implemented. The native caller now accepts the selected
qualified-warm mode and actual pair/phase identities; the separately pinned
projection changes only that caller among the original 69 measurement sources.
The historical proof, historical native caller fixture, original prerequisite
packets and blocked historical analyzer retain their own identities and scopes.

Independent wave-three reviews cover native behavior, proof/admission, producer,
reader and statistical gates. No blocking finding remains. The actual historical
four-process original passes the current public reader, with all 27 compared
summary fields unchanged. All 29 historical warm-analyzer tests also pass and
retain unconditional rejection. The new route's full focused selection passes
**89 tests in 195.293 seconds**. These are source-root tooling tests, including
explicit synthetic dependency/prerequisite seams; they do not claim a native
warm result. Supplemental adversarial probes are separately counted.

An initial historical test selection ran while shared reader source was being
edited and detected those input changes (eight failures and two errors). Its
original log is preserved; it is not reported as a pass. At that implementation
checkpoint, complete governance remained a separate obligation; the later
execution and its actual outcome are recorded below.

## Published implementation

The implementation was published to `master` as
`c0b44ce64665fe11895f869eea8c38c9b820d6f7`, with tree
`13450812d279d55f36a172fcf38653ff567f6c86` and sole parent
`f80b58b06e7bcf734f3190f6db478fd11f0bab01`. The
[publication receipt](evidence/p06-qualified-warm/validation/implementation-publication.json)
records all 66 selected blob identities, exact local/remote tree equality and
the non-forced, expected-head update. The separate local review commit
`89f51bc53a6de89657418a0a07ceb4a73c9dd91b` has that same tree; it is not the
published execution revision. Independent remote readback is retained in
[W09 A03](evidence/p06-qualified-warm/agents/w09_a03.md).

The base revision's classifier reports R2 for the CI-enforcement path. The new
external contract additionally received independent review at R3 depth. The
workflow change adds exactly one design-document path to each push and pull
request filter. No runner, permission, command, timeout or trust setting changes.
No RTL, simulator timing, runtime/kernel implementation, golden baseline,
accepted phase JSON, historical proof, old evidence packet or protected SVG
changes. The [review mapping](evidence/p06-qualified-warm/agents/w05_a02.md)
and [protected-file inventory](evidence/p06-qualified-warm/agents/w04_a06.md)
record those checks.

| Implementation | Purpose |
| --- | --- |
| Explicit native `--qualified-warm` mode | Admit actual pair/phase identities and separate witness contracts while preserving historical no-flag grammar. |
| Pinned caller projection extension | Review exactly one changed file among 69 measurement sources without editing or laundering the original proof. |
| Producer and admission | Bind the frozen sampling plan, current proof and reconstructed prerequisites before builds and all 24 process launches. |
| Complete reader | Reconstruct both format builds, 57 commands, raw counter/lifetime observations, all source/load joins, exact inventories and final stability. |
| Report-only bounded decoder | Permit the larger complete report with a 64 MiB, 750,000-node, depth-64 bound; historical and non-report parsing remain unchanged. |
| Analysis | Apply the unchanged exact median and every-pair predicates only after complete reconstruction. Validity and hypothesis satisfaction remain separate results. |

Historical archive replay remains supported. Fresh historical four-process
qualification requires a source revision matching its original frozen
projection; the old proof intentionally rejects the new current caller.
The new route does not grant a historical proof a new source identity.

## Native launch was blocked before an attempt started

A fresh clone of the published implementation and all eight recursive
submodules were independently checked: nine clean repositories, 8,038 tracked
blobs totaling 494,473,754 bytes, all 69 measurement descriptors, four selected
proof/original inputs and seven host executables. All 17 required destination
and fetched-input absence checks held. The
[checkout review](evidence/p06-qualified-warm/agents/w06_a01.md) certifies that
snapshot, separately from resource readiness.

The [supervisor/resource review](evidence/p06-qualified-warm/agents/w06_a02.md)
found an execution-readiness blocker. At its 19:11:04 UTC observation, available
RAM was 3,390,668,800 bytes, below the unchanged 4 GiB prerequisite. Free disk
was 18,233,057,280 bytes. The preceding workspace's measured allocated footprint
was 2,238,537,728 bytes; reproducing that alone would leave 111,607,808 bytes less
than the 15 GiB reserve, before the larger warm report, approximately 4.68 MB of
additional process logs and transient build growth. These are dated observations,
not a promise about later capacity.

The [recovery review](evidence/p06-qualified-warm/agents/w06_a06.md) found no
material safe cleanup among this task's temporary files. Prior original packets,
tool extractions and unrelated user data were preserved. No resource threshold,
timeout, job limit or acceptance requirement was lowered. The native workspace
was never created and no native experiment was started. The
[prelaunch status](evidence/p06-qualified-warm/native/prelaunch-status.json)
records zero observed experiment processes and launches; the 24/792/25,344
population remains a planned obligation. There is no new native original ZIP,
qualification result, positive or negative performance result, or phase acceptance.

## Validation outcomes and complete passing coverage

Independent discovery freezes **4,527 unique IDs: 4,437 prior tests plus 89 new
warm-route tests and one historical-proof rejection test**. No old ID was removed,
and all 107 generated IDs remain. Supplemental probes and repeated selections
do not increase this unique population.

The completed hosted [Project Governance run 45244780344](https://github.com/baabi-boo/AI-GPU/actions/runs/45244780344)
at exact implementation `c0b44ce64665fe11895f869eea8c38c9b820d6f7` finished green
at 20:35:47 UTC. Its [original-log analysis](evidence/p06-qualified-warm/validation/hosted-c0b44ce6/w09_a03-log-analysis.json)
records **4,512 reported tests in 3,555.657 seconds, with 23 skip events**:
4,491 passing methods, 21 method skips, and two class-setup skips suppressing
another 15 canonical bodies. Every canonical ID is accounted for, but 36 bodies
did not execute in that job. No unittest failures or errors were recorded.

Hosted preflight reported ambient CMake availability, but the dependency fixtures
could not find/admit CMake through their restricted interpreter-directory,
`/usr/bin` and `/bin` search path. The executable's actual hosted location was
not logged. The evidence establishes a visibility/admission mismatch, not
runner-wide absence. The local proper venv exposes the existing, hash-verified
CMake binary without widening production environment rules or downloading tools.
The earlier focused environment validation passes all 25 selected existing cases.

After independent selection and runner review, a separate completed supplement
executed all three affected modules: `test_p06_dependency_build` (9 cases),
`test_p06_dependency_option_controls` (21) and `test_p06_dependency_receipt` (29).
**All 59 pass with zero failures, errors or skips in 13.542 seconds including
supervision.** The coordinator observed exit zero; every command's cleanup,
exact ordered ID list, plain unittest `OK`, source/tool stability and native
absence checks pass. The [retained original](evidence/p06-qualified-warm/validation/coverage/supplement-result/retention-manifest.json)
preserves every output byte and separately attributed supervisor stdout.

The [independent final reconciliation](evidence/p06-qualified-warm/validation/coverage/final-reconciliation.json)
and [coordinator check](evidence/p06-qualified-warm/validation/coverage/coordinator-coverage.json)
compare actual sets: **4,491 hosted passing IDs + 59 supplemental passing IDs
− 23 overlapping IDs = all 4,527 canonical IDs**. The supplement-only set is
exactly all 36 hosted gaps; no unexpected or missing ID remains. Hosted Python
is 3.12.3 and the local venv is 3.12.14. This establishes complete passing
test-ID coverage across two environments. **No complete 4,527-test local run
or single invocation without skips is established.** The stronger invocation
obligation remains unproven, and hosted skip events remain part of the record.
No phase, proof or native resource requirement is waived by the coverage union.

### Earlier failed and unfinalized attempts

The first clean canonical local invocation was interrupted after the dependency
fixtures' restricted PATH was found to omit CMake. Its 1,312 successful outcome
lines supply no completed-suite result. The tool returned exit 130; the unchanged
raw supervisor still says `running`. A [separate coordinator interruption record](evidence/p06-qualified-warm/validation/governance/initial-canonical/coordinator-interruption.json)
records that distinction without inferring final cleanup or source stability.

The first two-partition attempt finished failed at 20:07:48 UTC. Worker zero
received SIGKILL after 1,289 successes, and supervised termination ended worker
one after 1,183 successes. The resulting 2,472 distinct passing observations
leave 2,055 IDs without success in that attempt. Final source/tool stability and
process-group cleanup were recorded, but no full-suite pass follows. The
[independent failure receipt](evidence/p06-qualified-warm/validation/w10_a03-final-receipt.json)
and [byte-preserving retention](evidence/p06-qualified-warm/validation/governance/final-c0b44ce6/retention-manifest.json)
preserve the failure. `final-c0b44ce6` denotes the terminal failed attempt,
not a passing gate. Its missing worker result remains missing.

A small independent weak-reference probe confirmed a harness defect: extra
`all_cases` and `cases` lists retained completed test instances after unittest
released them. The separately reviewed correction deletes those lists after
constructing the same suite. This establishes the retention mechanism, not
the operating system's cause for SIGKILL; kernel/cgroup evidence was unavailable.

The corrected long attempt passed both earlier interruption points and reached
3,771 successful test-ID outcomes (1,998 and 1,773); these include 3,770 verbose
`... ok` lines and one standalone `ok` after expected compiler diagnostics. Logs stopped advancing around
20:48 UTC; at 20:53:36 the execution service no longer recognized session 53940.
The raw supervisor remains `running`, with no final worker results or source-after
record. A stop request at 20:57:15 proves only that termination was requested.
Exit status, final source/tool checks and cleanup are **unobserved**. The
[unfinalized snapshot](evidence/p06-qualified-warm/validation/governance/released-cases-unfinalized/snapshot-manifest.json)
retains all present bytes unchanged, without inventing a finished result.
**None of the 1,312, 2,472 or 3,771 partial observations contributes to the
completed hosted/supplemental coverage union.**

### Operator and future CI follow-up

Two narrow runbook findings were corrected: both standard-library verification
heredocs use `-I` so environment optimization cannot disable assertions, and
post-replay output-file failure is distinguished from failed reconstruction.
The [review](evidence/p06-qualified-warm/agents/w07_a02.md) and
[small packaging probes](evidence/p06-qualified-warm/agents/w08_a03.md) preserve
their scope. The benchmark and source contracts are unchanged.

A hosted-governance environment correction should expose the selected CMake
binary through the controlled interpreter/tool environment and obtain one
complete invocation without skips, preserving restricted PATH rules. A future
long native attempt also needs stable supervision; the lost local session
cannot be treated as proof of reliable long-duration execution or cleanup.

## Current outcome and next bounded action

The explicit qualified warm route is implemented, independently reviewed and
published. Completed hosted and supplemental executions establish passing
coverage for all 4,527 canonical test IDs; a single full zero-skip invocation
remains unproven. Fresh native execution remains unstarted and resource-blocked. P06-A01 retains only its
original simulated cold-baseline acceptance. P06-A02/A03, the separate vendor
XRT gate and the inherited 267-to-283 DSP finding remain open.

Obtain one uninterrupted governance invocation without skips and provision
adequate capacity. Recheck the exact inputs and resource requirements, then run
one fresh complete three-stage attempt. Preserve its entire unchanged
two-root original and independently replay it before evaluating the frozen
predicates. A valid experiment may return `not_satisfied`; it must not be repaired
by dropping samples, rerunning favorable pairs or moving thresholds. Use the
[qualified warm handoff](p06-qualified-warm-handoff.md) and
[runbook](evidence/p06-qualified-warm/runbook.md) to resume.
