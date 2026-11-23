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

Sixty actual agent assignments are planned across ten waves of six. The session
allows three workers concurrently; each wave runs in two bounded batches.
Only completed assignments count. Each report is retained in
`evidence/p06-qualified-warm/agents/`; the final execution ledger will identify
each completed assignment and its output. Production ownership is disjoint.

| Wave | Scope |
| --- | --- |
| 1 | Current implementation, source proof, replay, experiment and execution audit |
| 2 | Native route, contract/projection, producer, records, reader and analysis |
| 3 | Independent source and implementation review |
| 4 | Adversarial identity, population, lifetime, provenance and compatibility checks |
| 5 | Integration and complete-route verification |
| 6 | Frozen publication checkpoint and fresh native preparation |
| 7 | Native original and independent numerical/lifetime/build review |
| 8 | Complete inert replay and experimental-predicate review |
| 9 | Governance and source-scoped delivery documentation |
| 10 | Independent final audit and publication verification |

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
original log is preserved; it is not reported as a pass. The frozen full
governance run remains a separate obligation.

Next, publish the reviewed implementation checkpoint, create an exact clean
source checkout with pinned submodules, and perform one fresh three-stage
attempt under unchanged resource limits. Preserve the complete original and
evaluate the fixed predicates only after independent complete replay. Native
execution and final governance validation are pending at this checkpoint. No
warm, performance, hardware or phase result is claimed.
