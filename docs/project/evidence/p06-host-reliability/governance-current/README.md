# Current-source governance original and independent replay

Project Governance completed successfully for the published code revision
`81d7a35c641f3a969c23c8e604f7468a4d88644a`, tree
`9da606f541ecb85248ef00995e8288c1266eea88`. The independently selected original
matched its authenticated size and digest, and one bounded local replay passed.
This packet preserves original bytes, separate provider observations and the
replay's explicit claim limits. It does not qualify the later audit commit.

## Original identity

| Field | Bound value |
| --- | --- |
| Repository | `baabi-boo/AI-GPU`, repository and head-repository ID `1457409699` |
| Workflow | `418772913`, `.github/workflows/project-governance.yml` |
| Run / attempt | `45796540254` / `1` |
| Governance job | `139828665982`; completed/success, all 13 steps successful |
| Artifact ID | `15109565376` |
| Artifact name | `project-governance-81d7a35c641f3a969c23c8e604f7468a4d88644a-run45796540254-attempt1` |
| Original bytes | `1414721` |
| Original SHA-256 | `5596e541ebf8eb272d813ee353b8e5eb998a641aef7b675f5b014cfd8e2ef045` |
| Provider expiry | `2026-12-26T10:51:00Z`; unexpired at both observations |

[Selection](selection-before.json) retained expected identity before acquisition.
[Acquisition](acquisition.json) matched the unchanged [original ZIP](original.zip).
The ZIP was never extracted or repacked. Its read-only acquisition/replay mode
was `0400`; Git preserves its content as a regular blob, not that local permission
mode or inode. All before/after filesystem identities refer to the original
acquisition location, not the publication copy.

The independent [terminal provider review](../reports/a087-terminal.md) and
[exact terminal responses](../a087-terminal-provider/) confirm the selected
tuple. The [post-replay review](../reports/a087-after-replay.md) and
[responses](provider-after/) confirm the same tuple after replay, complete jobs
and artifact pagination, a stable final run, and unchanged `master`.
Provider observations are dated and non-atomic. Their authored metadata omits
account connector locators; exact response bodies retain their original bytes.

## Replay result

The [independent report](../reports/a088-current-replay.md),
[exact invocation](a088-replay.sh), [metadata](a088-replay-metadata.json),
[checksums](a088-replay-sha256.json) and [receipt](replay.json) retain one
invocation during **2026-11-26 10:59:00–10:59:10 UTC**, exit **0**, with empty
stderr. Its stdout is byte-identical to the receipt.

| Reconciled original execution measure | Value |
| --- | ---: |
| Canonical tests | 5,575 |
| Successful subtests | 39,419 |
| Ordered events | 56,144 |
| Recorded original execution duration, seconds | 2,744.522179 |

The replay reconciles retained execution records. It imports the explicitly
trusted source for discovery and executes no test bodies. Source, reader/runtime
and original identities were byte-identical before and after. Both resource
observations preserved the 1 GiB storage reserve plus 32 MiB metadata allowance.

The receipt correctly leaves `provider_authenticated`, `retained_code_executed`,
`tests_executed_by_replay`, `native_acceptance`, `phase_acceptance` and
`performance_acceptance` **false**. Only `independent_packet_replay` and
`trusted_source_imported` are true. Separate authenticated provider responses
support origin observation; they do not turn this local reader into the full
hosted admission procedure. In particular, workflow-active/artifact-detail
reobservation and the production transport/staging guarantees are not established
by this connector route.

## Remaining work

The post-replay observation found **14 of 15 current-source workflows successful**.
Main CI run `45796538630`, attempt 1, remained queued with only `change-impact`
and `plan` jobs, both queued and without steps. Its matrix and aggregate `Gate`
result remain pending. No full main-CI or Apptainer success is inferred here.

The qualified native warm experiment remains unstarted. Its exact private
control delivery, intended public age recipient and admitted 15 GiB disk /
4 GiB memory runner are still required, together with the prescribed admission
and frozen source/proof contracts. The inherited native trace-ownership F2
remains open; see the [continuation](../CONTINUATION.md) and
[resumption handoff](../RESUME.md).
