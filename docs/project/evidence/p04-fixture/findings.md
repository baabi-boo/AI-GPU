# P04 fixture audit and finding dispositions

Seven development issues were corrected before the implementation freeze at
[`10ace66193686e3862c3c218760b66c044f1d4ae`](https://github.com/baabi-boo/AI-GPU/commit/10ace66193686e3862c3c218760b66c044f1d4ae).
The existing DSP gate failure, vendor-emulation blocker and qualification-harness
diagnostic limitation remain open. The [structured record](findings.json)
preserves the original reporters, fix and review agents, compact observed results,
and original receipt/probe identities. Original scratch filenames identify
provenance; they do not imply separately delivered raw probe files.

This history grants no acceptance and reports no new GPU execution. The
[packet index](README.md) carries the separate qualification and acceptance
records. Severities below are retained only where the originating report assigned
them; “unassigned” does not mean F0 or a retrospective waiver.

| ID | Finding | Reported severity | Disposition |
|---|---|---|---|
| P04-F01 | Provisional split input repeated row blocks | Unassigned | Corrected before initial fixture generation |
| P04-F02 | Alternate-root verification used different source than it pinned | F2 | Fixed and independently reviewed |
| P04-F03 | Normative specification identity and source-evidence wording | F1 | Fixed and independently reviewed |
| P04-F04 | Host output-copy token disagreed across contracts | Unassigned | Fixed; numerical tensor bytes unchanged |
| P04-F05 | Pinned specification edits could skip governance CI | Unassigned | Four positive trigger lines added and reviewed |
| P04-F06 | Incomplete native-profile compatibility checks | F2 | Exact typed profile mapping and rejection tests added |
| P04-F07 | CI regression guard accepted quoted or padded control keys | F2 | Guard repaired and bypasses independently rejected |
| P04-F08 | Existing tensor DSP area regression | Unassigned | Unresolved; separate measured correction required |
| P04-F09 | P01-A03 vendor `hw_emu` prerequisites | Unassigned | Blocked; still required before P07 closure |
| P04-F10 | Missing record on an early qualification preflight block | F1 | Disclosed diagnostic limitation; fails nonzero |

## Corrections retained in the frozen implementation

### P04-F01 — distinct output row blocks

`/root/w02_a01_reference_impl` found that the provisional input formula repeated
each eight-row block because `8*3+1` is divisible by five. The producer and
specification adopted `((3*r + 2*k + 3*(r//8)) % 5) - 2` before the first fixture
was generated. No accepted fixture or tolerance was changed. Independent
serialized-input tests distinguish repeated and swapped output halves; the
frozen provenance review reconstructed all input families from their definitions.

### P04-F02 — copied-root source identity

`/root/w03_a04_source_review` reproduced the F2 defect by changing a copied
producer's W1 seed while retaining the old fixture. The invoking checker's
manifest write and subsequent check both exited zero; the copied producer's own
check and copied checker both exited one. Hashing target sources did not establish
that the invoking producer had used those sources.

The correction compares the copied checker, producer and encoding helper against
the actual invoking modules before generating expectations. Intentional changes
use the reviewed target's own checker. The independent repair review executed
nine probes: source mismatches fail even after their copied manifest hashes are
refreshed, while identical copies and the reviewed target-own path remain usable.
All six mismatch rejection paths preserved temporary-file bytes and modification
times. This is source consistency, not authentication or protection against
concurrent source mutation.

### P04-F03 — specifications and evidence scope

The same source review assigned F1 to omitted identity pins for the normative
tiny-MLP and tensor-numerics specifications, and to a sentence overstating what
fixture data establish. Both specifications are now pinned. The wording defines
correctness targets for later execution. Related clarification labels transfer
totals as tensor-buffer estimates and requires actual-output lineage,
`ok() && complete`, and retained ownership for partial or timed-out operations.
The frozen changed-hunk and execution-boundary reviews confirmed these limits.

### P04-F04 — host-work token consistency

`/root/w03_a06_runtime_mapping` found `output_row_assembly` in the fixture but
`copy_row_blocks` in the manifest graph and allowlist. The producer now uses
`copy_row_blocks`; explicit regeneration and a cross-document assertion keep the
contracts aligned. All **44 raw tensor hashes over 4,000 uint32 words** remained
identical. The whole-file fixture hash changed only with this metadata correction:

- Before: `de845064bf2ca9de3ead396d479374c941761f1df565c238ced9a09a55f219c6`.
- After: `d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03`.

The structured record preserves the repair and independent-review provenance.
No current executor existed when this mismatch was found, and no new host
operation was introduced by harmonizing its name.

### P04-F05 — governance trigger coverage

`/root/w04_a06_integration_review` found that spec-only edits to two pinned inputs
would not trigger Project Governance. The focused regression initially reported
four failing subtests: two omitted paths in each event filter. The workflow adds
both paths under `push` and `pull_request`, exactly four lines. Independent review
proved that deleting those additions reproduces every baseline workflow byte;
permissions, runners, commands, trust settings and failure propagation are intact.
The final guard covers all 17 pins, itself and the workflow. Baseline-policy
classification of the frozen change is R2, with no new R3 contract exposure.

### P04-F06 — complete accepted-profile mapping

`/root/w05_a02_contract_adversarial` demonstrated four incompatible profiles that
the old subset checker accepted after manifest regeneration: disabled FP16,
disabled local memory, PE ratio 2, and an added memory-size override of 8192.
Actual configuration generation succeeded in every case, but the actual native
profile guard rejected all four with compiler exit one. These were host guard
compilations, not GPU executions.

The checker now validates all **26 core and two chip settings** with exact keys
and types. Extra overrides, `platform`, `extends` and unknown top-level fields
are rejected; known descriptive metadata remains separately permitted. The native
guard, defaults, type definitions and parser are pinned without being changed.
Seven new tests cover 15 independent mutations after digest refresh, requiring
30 nondestructive CLI rejections. The full contract module passed 32 tests in an
isolated copied bundle. Independent review confirmed the parser's real override
and inheritance behavior and the fixed source boundary. Generated configuration,
compiler records and backend/kernel agreement remain executor obligations.

### P04-F07 — conservative CI job-key guard

`/root/w05_a06_workflow_review` found that the new guard accepted legal YAML
spellings `if : false`, `'if': false`, and `continue-on-error : true`. The current
workflow was unconditional; the defect concerned the test's ability to detect
future job suppression. Requiring plain mapping keys at the existing indentation,
rejecting duplicates and forbidding both controls closes the demonstrated paths.
Twelve mutation probes were rejected while the baseline and a harmless plain
`name` field were accepted. A different reviewer separately rejected the three
original bypasses. The workflow was unchanged by this test repair. The guard
deliberately supports the existing subset rather than arbitrary YAML.

## Remaining issues and bounded follow-ups

### P04-F08 — existing DSP area gate

The [development-entry audit](../../p04-audit.md) retains three existing failures:
[43831931973 / 133185321661](https://github.com/baabi-boo/AI-GPU/actions/runs/43831931973/job/133185321661),
[44006819632 / 133788898496](https://github.com/baabi-boo/AI-GPU/actions/runs/44006819632/job/133788898496),
and [44271136872 / 134700081401](https://github.com/baabi-boo/AI-GPU/actions/runs/44271136872/job/134700081401).
Each reports **267 → 283 DSP**, displayed as +6.0%, beyond the unchanged 5% limit.
The green predecessor run had 42 jobs and no `logic_gate` cell. A later reduced
green run cannot establish that this failure was resolved.

Widened MX scale-index multiplication at `1a898f7` is a static candidate, not a
measured causal bisect. A separate correction must measure parent/candidate Beacon
results and per-unit attribution, preserve the widened index, prove any addressing
rewrite equivalent, and run the MX WGMMA NRC=16 RTL case with applicable parity.
This fixture change alters no RTL, golden baseline or gate threshold.

### P04-F09 — vendor integration

The [existing P01-A03 blocked record](../p01-xrt-blocked.json) remains authoritative.
Qualified vendor tools/platform and matching integration artifacts must be
established before the bounded XRT `hw_emu` smoke can run. P01-A01/A02 stay
accepted, but source-only P04 work, processor RTL and vendor-free `xrtsim` do not
replace this obligation. Full P01 completion is still required before P07 closes.
This retention assignment performed no new vendor prerequisite scan or execution.

### P04-F10 — early blocked-result recording

`/root/w07_a02_qualification_review` found an F1 diagnostic edge in the exact
qualification harness. A resource preflight can return `blocked` before creating
a log; the outer harness then attempts to hash that missing file before saving
the returned receipt. An isolated impossible-disk-reserve probe observed
`process_started=false`, followed by `FileNotFoundError` at the outer hash step.
The harness fails nonzero and cannot manufacture a pass. None of the completed
qualification commands inspected by that reviewer took this path.

The exact executed harness is preserved. Before adapting it for the next
qualification, the P04 executor/qualification owner should save the returned
blocked receipt even when no log exists, represent the absent log explicitly,
and check early disk/resource/log-open failures with isolated no-process probes.
The historical runner and its actual command receipts must remain unchanged.
