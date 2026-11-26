# Checkpoint publication evidence

This packet records source and host-tooling work following
`858090410a992756808256ace90d36b9b3b88dd3`. It does not contain a new native
qualified-warm execution or performance acceptance. See the
[audit](../../p06-checkpoint-publication-audit.md) and
[implemented contract](../../../designs/checkpoint_publication_v1.md).

## Implementation and independent review

The shared JSON checkpoint writer now releases only its own failed temporary
entry, preserves the committed report until publication, checks temporary
ownership before replacement, and preserves the first failure through cleanup.
Its directory handle retains write/search-only directory compatibility.
There is no automatic checkpoint retry or child-work replay.

- [Initial implementation review](reviews/implementation.md) covers the shared
  writer at `ba88572`; its subsequent permission correction is separate.
- [Directory-access review](reviews/directory-access.md) covers the corrected
  implementation at `93bb3f0`, including actual mode-0300 publication and denied
  search/write probes. Permission-denial sensitivity was observed under UID
  1000; a privileged account can bypass ordinary mode checks.
- [Test-correction review](reviews/test-corrections.md) covers the final
  descriptor-cleanup negative controls and required false-claim fields.

The source history retains the initial correction, permission follow-up and
test-fixture correction separately. The tests distinguish supported failure
recovery from best-effort cleanup limits and preserve failed negative controls.
The [original supervisor reproduction](negative-controls/a003-orchestration-audit.md)
and the [direct](negative-controls/a005-tests.md),
[supervisor](negative-controls/a006-integration.md),
[ownership](negative-controls/a007-ownership.md),
[acquisition](negative-controls/a008-input-recovery.md) and
[preparation/builder](negative-controls/a009-prepare-build.md) reports retain
their old-revision comparisons. Their individual runs overlap the combined
selection below and are not added to its test count.

## Focused integration

The [complete focused result](validation/focused.json),
[raw log](validation/focused.log) and
[retained invocation script](validation/focused-runner.py) record **225 unique
test methods and 670 successful subtests**, executed in one uninterrupted
selection with zero failures, errors, skips or retries. Unittest duration was
**30.761 seconds**.

The selection covers all **24 new methods in six modules** and relevant existing
P02, P04 and P06 consumers. The recorded HEAD was
`93bb3f0342eff0b469a0da06cb067916af7c539e`, with two modified test files and an
untracked audit document. The test corrections were subsequently committed at
`a693d6f8828e4e10b5374db7fef8c727aa69d34e`. All **117 loaded local Python files**
had matching before/after SHA-256 hashes and no missing baseline. The retained
working-tree state did not change during execution. Process observations found
no cwd, environment, signal, thread, Linux-task or descriptor-state changes.

These are focused development results for the recorded source bytes. They do
not qualify a later complete revision. The selected published revision requires
its own strict unfiltered governance invocation and independent original replay.

## Canonical discovery

The [discovery record](validation/discovery.json) contains **5,539 unique test
IDs** at `a693d6f8828e4e10b5374db7fef8c727aa69d34e`, with no loader errors,
failed-import placeholders or duplicate IDs. Comparison with the base
governance original found **24 additions, zero removals**, preserving the
relative order of all **5,515 existing IDs**. The additions exactly match the
methods in the six new checkpoint modules. The complete discovery digest is
`ff3430b00d2879442b396902872dc6490784156e2dc0ae660af1a777dfdfbe7b`.
Discovery did not execute the test bodies.

## Python launcher ownership and final integration

The [launcher finding](launcher/original-finding.md) reproduced a child
continuing after PID-directed `SIGTERM` terminated its parent launcher. The
[implementation](launcher/implementation.md) records pending termination in a
temporary signal handler, forwards it in ordinary control flow, and reaps the
direct child before returning. This preserves the existing environment checks,
arguments and ordinary/signal exit-status mapping. It also restores the previous
handler. Calling the launcher entry point requires the main thread. There is no
execution deadline, process-group change, escalation or descendant/native
cleanup guarantee; a child that handles or ignores termination remains owned
until its actual exit.

The [design](launcher/design-review.md),
[production review](launcher/implementation-review.md),
[test review](launcher/test-review.md) and
[packaging review](launcher/packaging-review.md) are independent of the
implementation. All [25 existing launcher tests](launcher/existing-tests.json)
and [eight new lifecycle tests](launcher/new-tests.json) pass. The
[explicit base negative control](launcher/baseline.json) retains the observed
orphan-child behavior and its safe reclamation; the new regression fails against
that old implementation. These individual runs overlap the final selection.

The [final focused result](validation/final-focused.json),
[log](validation/final-focused.log) and
[runner](validation/final-focused-runner.py) record one uninterrupted invocation
of **258 unique methods and 752 successful subtests across 18 modules**, including
all **32 new methods**, with zero failures, errors, skips or retries. Unittest
duration was **28.921 seconds**. The recorded code commit was
`d31e8879e7c248b1a72615128882533ccdd0b3b4`, with the precisely recorded pending
documentation/evidence changes. All **122 observed or required local source
files**, and all **932 inventoried repository Python files**, had stable hashes.
HEAD, worktree status and observed process state were unchanged during execution.

[Final canonical discovery](validation/final-discovery.json) records **5,547
unique IDs**, with **32 additions and no removals** from the base; the additions
are 24 checkpoint and eight launcher methods. All prior relative order remains
unchanged, with no loader errors, placeholders or duplicates. The full ID digest
is `0e8dbaad34266093f76db937eba670ce8f628ceb500998cb9094cdd2f12071fa`.
This supersedes the earlier discovery count, but does not execute test bodies
or substitute for complete revision qualification.

The [P05 historical reference](launcher/a01-retained-binding.json) points the
old launcher and test artifacts to their exact retained bytes with unchanged
digests. The [retention mapping](launcher/source-retention.json) and
[independent review](launcher/history-review.md) preserve the original accepted
execution and record unchanged. The analogous
[P02 mapping review](reviews/historical-binding-review.md) preserves the old
shared helper. Only those two roadmap evidence references change; acceptance
criteria and phase states remain intact.

## Reconciled base governance original

The previous published revision's Project Governance run
[45762183368, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45762183368)
succeeded for `858090410a992756808256ace90d36b9b3b88dd3`. Its
[unchanged retained original](base-governance/run-45762183368-attempt1.zip)
is **1,395,652 bytes**, SHA-256
`21c1c6bda5e8513d99642dd12d5db8c52d4b2bcae8726119b12236e7708fc74e`,
matching the authenticated [provider metadata](base-governance/provider-original.json)
for artifact **15092372891**.

An [independent replay](base-governance/review.md), using a clean exact-base
checkout and the recorded reader at `a693d6f8828e4e10b5374db7fef8c727aa69d34e`,
passed with **5,515 canonical tests, 38,655 successful subtests and 55,200
events**. The original invocation took **3,134.501976 seconds** and recorded no
failures, errors, skips, missing IDs or duplicate IDs. The
[replay receipt](base-governance/replay/replay.json),
[invocation and reader identities](base-governance/replay/invocation-completed.json),
reader snapshots and raw log are retained together. Offline replay reconciles
the original records; it does not rerun test bodies or authenticate the provider.
This result applies to the base revision, not the changed checkpoint revision.
The later [provider status observation](base-governance/all-workflows.json)
records all **15 base workflows completed successfully**, including the main CI.

## Preserved inputs

The [invariant result](validation/protected-invariants.json) and
[retained verifier](validation/protected-invariants.py) record an observation
at HEAD `a693d6f8828e4e10b5374db7fef8c727aa69d34e`; the verifier also records
the selected implementation revision `93bb3f0342eff0b469a0da06cb067916af7c539e`.
They establish:

- All **69 measurement files**, totaling **1,303,138 bytes**, match the frozen
  qualified-warm source projection by byte length and SHA-256.
- All **21 dependency descriptors**, their proof bytes, source pin and gitlink
  remain unchanged. Their dependency source files were not materialized locally;
  this is not a fresh hash check of those dependency source bytes.
- All **25 baseline golden files**, **39 numerical fixtures**, frozen proofs,
  selected resource/performance rules, roadmap and acceptance states are
  unchanged from the audited base. Subsequent status/backlog edits describe
  this continuation without changing phase or acceptance decisions.
- The inherited SVG is unchanged at **48,225 bytes**, SHA-256
  `db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`.

The historical evidence tree was unchanged at that invariant observation.
This new packet adds evidence without rewriting the historical originals.
The [final protected-input result](validation/final-protected-inputs.json) and
[review](validation/final-protected-review.md) repeat the check after the launcher
repair and source-reference corrections. All **14 checks pass**. Reversing
exactly the two declared roadmap evidence pointers makes the entire roadmap
document identical to the base. Both original acceptance records remain
byte-exact; the only changed pre-existing evidence document is the P02 README
explaining the new reference. No dependency source files were materialized or
freshly rehashed.

## Remaining execution boundary

The **24-process, 792-launch, 25,344-word** native qualified-warm population
remains unstarted. Require exact private control delivery, the public age
recipient, strict governance and original replay for the selected revision,
and actual admission at **15 GiB free disk and 4 GiB available memory**. Retain
complete or explicitly partial originals through encrypted delivery and
independently replay a complete native original before the frozen performance
decision. P06-A02/A03 and P01 vendor integration remain open.
