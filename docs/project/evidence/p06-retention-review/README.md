# Qualified warm retention and replay: tooling evidence

This continuation makes the documented independent replay command executable,
requires explicit command observations for started dependency/native writers,
and implements checked inspection and private restoration of the existing
decrypted retention format. The [audit](../../p06-retention-review-audit.md),
[retention contract](../../../designs/qualified_warm_retention_review_v1.md) and
[operator guide](../../p06-hosted-warm-guide.md) explain the changes and the
remaining native experiment.

**This packet establishes tooling development and review only.** It contains no
new 24-process qualified-warm original, GPU performance result, hardware
qualification, producer authentication or P06 phase acceptance. Synthetic
archives and process records remain synthetic. Successful retention inspection
can preserve a failed or partial attempt without making it a complete native
original.

## Audited base and changed-source qualification

The audited base is `25543e1cf96530264746c0e2d130018dd0dba465`, tree
`ac44d4f633abaadbd7077f940cbab0f0ddde6b27`.
[Project Governance run 45475313555](https://github.com/baabi-boo/AI-GPU/actions/runs/45475313555),
[job 138733849431](https://github.com/baabi-boo/AI-GPU/actions/runs/45475313555/job/138733849431),
records **5,036 tests in 2,136.484 seconds**, `OK`, and
`Strict governance PASSED`. All 15 observed workflows at that revision succeeded.
These are exact-base observations, not qualification of changed source.

[A40](reviews/A40.md) independently retrieved the original governance artifact
`14959569964` through the supported provider download. Its **1,298,894-byte**
size and SHA-256
`c464d6b761da1ac0d729c6d738b172384b59f7d780e412e8324199bd34b98bb8`
match the provider and upload log. The
[original-receipt audit](validation/base-governance-audit.json) records 40
passing consistency checks: **5,036 ordered test lifecycles, 37,234 successful
subtests and 52,342 consecutive events**, with no failures, skips, errors or
missing/duplicate/unexpected IDs. It also checks the base Git tree inventory,
untruncated log, ready environment receipt and all 11 before/after tool
identities. This additional inspection remains base-only evidence.

The local implementation checkpoint is
`583985564ddbfd564f15344efe96c74a7c94c55b`, tree
`72dc5c78acb8f117780abd269d6d5d8158f7dbf1`. It precedes the final cleanup
correction, one reader metadata-isolation regression and the final documentation.
It is a local review checkpoint; its SHA is not asserted to be a published
provider commit.

The published changed revision requires its own complete, uninterrupted strict
governance invocation under the [checked environment](../../governance-runbook.md).
Read that exact provider SHA's Actions result and retained original receipts
before the separate manual private qualified-warm dispatch. Focused runs,
canonical enumeration and results from the base do not substitute for that
qualification. No later publication or workflow result is implied by this
packet's creation.

[A54's workflow review](reviews/A54.md) expects **15 existing automatic
workflows** on a normal push of this candidate to `master`, including native and
replay checks. Inspect their actual outcomes at the published SHA; a filter
review is not a workflow result. The private full qualified-warm route remains
manual, and those automatic checks do not supply its new 24-process original.

## Implemented boundaries

| Component | Change and boundary |
| --- | --- |
| `p06_qualified_warm_replay.py` | Use explicit trusted module/path pairs so direct script execution does not invent a `__main__.py` source. Preserve trusted-location and source-identity checks. |
| `p06_qualified_warm_hosted.py` | Permit the preparation schema's omitted command list, but require explicit observations for started dependency/native stages. Missing records cannot authorize closeout. |
| `p06_qualified_warm_retention.py` | Verify an externally selected plaintext SHA-256 and revision, complete canonical manifest and tar inventory, exact headers/padding, byte counts and streamed member hashes. No decryption, code execution or origin authentication. |
| `p06_qualified_warm_restore.py` | Validate before creating output, restore exclusively through owned descriptors, preserve exact bytes and private modes, recheck stability, and retain incomplete output on failure. No recursive extraction or deletion. |
| Cleanup ownership | Attempt every independently owned resource once, preserve an existing operation failure, avoid unsafe descriptor retries, and reject success after a terminal close failure. |
| Governance contract coverage | Add only the retention contract's literal path to both existing workflow event filters and the exact expected-path oracle. The native manual workflow, jobs, budgets and admission remain unchanged. |

The public encryption summary is only consistency metadata for the retention
reader. The reader does not read or verify the ciphertext named by that summary.
The operator separately checks the ciphertext, decrypts with trusted age, selects
the plaintext identity, and later replays native originals from a separate
trusted checkout. These identities and operations are not interchangeable.

The [source identity inventory](validation/source-identities.json) binds 27
selected source/document/frozen inputs and all 69 measurement-source rows at
its actual observation time. It distinguishes raw working-file identities from
the local checkpoint and audited base and checks the final production hashes
against the recorded execution evidence. It is not an execution receipt or a
claim of a final published commit. Later documented observations, if present,
must be read at their own scope; an older whole-file review hash is not silently
assigned to revised documentation.
The [separate follow-up observation](validation/source-identity-followup.json)
records the later status/backlog wording corrections identified by A49. The
other 25 inventoried paths, including all production/test/workflow files,
remain unchanged. The original A46 inventory is preserved without rewriting
its observation time or earlier documentation identities.

## Verification accounting

The [validation artifact index](validation/artifact-index.json) records the raw
SHA-256, Git-blob identity and byte length of its **31 selected public artifacts**.
It preserves the original source locations as provenance, while its `path`
fields identify the available files relative to that index. Its byte checks
do not upgrade any artifact's execution or acceptance scope.

The [execution ledger](agent-ledger.json) binds each completed assignment to its
unaltered supplied report with SHA-256, Git-blob identity and byte length. Every
assignment began with a separate context (`fork_turns=none`); at most three
workers ran concurrently alongside the root integrator. Follow-up turns and
agents from the preceding automation continuation are not additional
assignments in this ledger. The root's integration work is recorded separately
and is not counted as an agent assignment. Read completed work from the actual
completed rows; requested and started counts do not establish completion. A
completed assignment means its report is finished, not that an acceptance gate
passed.

Individual reports retain their own commands, outcomes and source identities.
Earlier tests are not reassigned to later bytes, and overlapping focused runs
are not added into a unique total. Actual age encryption/decryption checks use
throwaway identities and synthetic files only. Keys and private native originals
are excluded from this public packet.

| Development check or review | Actual result and scope |
| --- | --- |
| Direct replay regression, [A07](reviews/A07.md), reviewed by [A13](reviews/A13.md) | Eight new CLI tests include real subprocess invocation and trusted source binding. The review also preserves the old proof's rejection of the changed current caller. |
| Started writer observations, [A10](reviews/A10.md), reviewed by [A23](reviews/A23.md) | Thirteen new regressions include the two reproduced missing-inventory cases. Preparation's valid schema remains supported; missing started-child observations cannot authorize packaging/encryption. |
| Canonical retention and filesystem restoration, [A14](reviews/A14.md), [A15](reviews/A15.md), [A16](reviews/A16.md), [A17](reviews/A17.md) | Independently scoped grammar, path/ownership, metadata and bounded-I/O checks; each report records its exact reviewed version and limitations. |
| Cleanup correction, [A27](reviews/A27.md), reviewed by [A32](reviews/A32.md) | 57 focused tests pass, including 15 new cleanup methods. The separate independent review adds four test methods covering seven previously untested cleanup scenarios. These are overlapping and separately scoped development checks. |
| Final real-age round trip, [A33](reviews/A33.md) | 55 checks pass using real age/age-keygen v1.3.2 and the final cleanup code. Nine files, nine source directories and 131,613 source bytes survive exact encrypt/decrypt/inspect/restore checks. Wrong-key decryption produces no plaintext; wrong-digest inspection/restoration fail. |
| Cleanup-test validity, [A35](reviews/A35.md) | All 15 methods pass against corrected source; 14 reject checkpoint `58398556`. The marker-close test already passed at that checkpoint. Failure injection invokes actual close operations and checks monkeypatch/resource cleanup. |
| Coherent production-focused invocation, [A36](reviews/A36.md) | One invocation passes 137 distinct test bodies and 304 subtests, with 715 ordered events and zero failures, errors or skips. It executes all 78 new tests and 59 directly affected existing tests in 69.030309 seconds. No retry or full-suite claim. |

The exact [final real-age result](validation/final-age-roundtrip.json),
[probe source](validation/final-age-roundtrip-probe.py) and
[cleanup focused result](validation/cleanup-focused-tests.json) are retained
without transformation. The real-age probe records its original task-local
paths and is supporting development evidence, not a portable native-run
entrypoint. Its disposable private identities were deleted; their contents were
never retained in this packet. The earlier [A12](reviews/A12.md) round trip
remains bound to its earlier source identities and is not relabelled as a test
of the later cleanup correction.

The [focused validation summary](validation/focused-validation.json) and
[unaltered execution artifacts](validation/focused-run/artifact-manifest.json)
retain the command, interpreter, selected IDs, events, results and before/after
identities for 531 code/test/fixture/contract files. Documentation was excluded
from that stability assertion because it was still being assembled. The
[canonical inventory comparison](validation/focused-run/inventory-comparison.json)
separately enumerates **5,114 current IDs versus 5,036 base IDs**, with exactly
78 additions and zero removals. Neither enumeration executes any test body.
The old IDs retain their relative order. This is discovery evidence, not a
complete 5,114-test qualification.

After that focused invocation, [A39](reviews/A39.md) added only the retention
contract path to the governance workflow's two filters and existing test oracle.
Its separate existing workflow module passed **12 tests**. A36's aggregate
531-file inventory therefore describes the source before that later oracle
edit; the production files and all 137 executed test bodies remain unchanged.
The focused invocations are not added into a full-suite result.
[A47](reviews/A47.md) independently checked the exact three additions and the
base-policy **R2 CI-enforcement** classification. The earlier narrower R1
observation does not cover this workflow change. Final publication also requires
the immutable base classifier against the actual committed candidate; no human
review, approval or waiver is invented by an agent report.

The new regression modules cover direct CLI execution, writer observations,
reader format/integrity bounds, private restoration, actual producer/packager
compatibility and cleanup fault handling. Their discovery in the full suite is
separate from execution of that suite. The final strict run must have zero
failures, errors and skips and stable checked source/tools.

## Review map and remaining qualification

Read each report at its stated observation time and file identities. Later
packet assembly does not extend an earlier review to new bytes.

| Review area | Retained review and scope |
| --- | --- |
| Production integration | [A57](reviews/A57.md) independently reads the four production changes at their final observed hashes; [A50](reviews/A50.md) maps the complete candidate's changed hunks to independent review and focused evidence. Neither is a new execution or maintainer approval. |
| Public content and attribution | [A48](reviews/A48.md) and [A55](reviews/A55.md) inspect successive exact snapshots for public content, file types, links and source attribution. Later reports and presentation bytes require a final scan of their own. |
| Current operator instructions | [A49](reviews/A49.md) checks the operator guide, handoff, status and backlog against source; its two document corrections are recorded in the separate source follow-up above. |
| Historical preservation | [A51](reviews/A51.md) compares the complete base inventory with actual bytes and modes, including frozen inputs, historical evidence, phase records, native sources, goldens and attribution. New packet assembly lies outside that historical population. |
| Retained evidence data | [A52](reviews/A52.md) audits the artifact index, retained lifecycles and source identities. The 29 externally sourced artifacts match available originals; the two source-identity records are primary records whose self-references do not independently prove copying provenance. |
| Assignment and report accounting | [A53](reviews/A53.md) verifies its 51-report snapshot and report provenance. Its result stays at that cutoff; later completed ledger rows require their own identity checks. Context-isolation claims remain grounded in the root's actual dispatch record. |
| Publication and CI | [A54](reviews/A54.md) records the exact-source CI verification plan; [A56](reviews/A56.md) checks publication source binding, parent history and checkpoint payload equivalence. These are static preflights, not a published SHA, final candidate classification or strict pass. |

For the completed candidate, the integrator must reconcile the actual ledger
and report set, rescan the final public bytes and links, and apply the immutable
base classifier to the actual committed candidate. Publication must preserve
concurrent remote work and verify the resulting provider tree and parent chain.
Then inspect the published SHA's full strict original receipts and all expected
automatic workflow outcomes. Each result retains its own execution scope; none
closes the separate experiment or phase obligations below.

## Preserved experiment and remaining action

[A38](reviews/A38.md), [A42](reviews/A42.md), [A44](reviews/A44.md) and
[A45](reviews/A45.md) independently examine development priority, actual
performance-reducer semantics, runtime/framework scope and hardware/resource
obligations. Their static reviews support completing the existing measurement
question before introducing another feature. They are bounded source/evidence
reviews, not new runtime or hardware execution.

P06 and P06-T01 remain `in_progress`; P06-A02/A03 remain open. The frozen proof,
69 measurement sources, golden baselines, historical evidence and phase records
retain their existing identities and acceptance scopes. The required full warm
population remains **24 processes, 792 launches and 25,344 exact FP32 words**,
including primes and warm-ups. Native admission still requires **15 GiB free
disk and 4 GiB available memory**, plus the unchanged process, build and time
bounds.

The next experimental action is one complete admitted attempt, with the exact
private control original and explicit public age recipient configured, followed
by preservation, checked restoration, independent replay and the frozen
performance decision. A complete valid run may reject the hypothesis. The
development environment did not meet native disk admission, and no new
24-process qualified-warm attempt was made here. Vendor XRT `hw_emu`, physical
hardware, synthesis/resource and DSP obligations remain separate and open at
their existing scope.
