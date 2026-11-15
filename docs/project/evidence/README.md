# Evidence records

This directory contains the evidence format and, as work is accepted, compact
reviewable records. [report.example.json](report.example.json) is an **unexecuted
template**: it is not proof and must never be referenced as phase evidence.
Use the [acceptance policy](../acceptance.md) before producing a real report.

## Foundation setup records

- [Source validation](setup-validation.json) supports P00-A01/A02 at the exact
  published source candidate; [command log](setup-validation.log) retains actual
  exits, including the separately blocked simulation prerequisite screen.
- [Accepted delivery](setup-accepted.json) supports P00-A03 after explicit
  maintainer authorization and verified merge into `master`; the
  [merge observation](setup-merged.json) preserves the exact GitHub readback.
  The earlier [blocked delivery record](setup-delivery.json) is retained as
  historical evidence, not rewritten to look like an earlier success.
- [Independent reviews](setup-review.md) retain failures, corrections, scopes,
  exact snapshots and advisory dispositions.
- [Publication observation](setup-publication.json) records the review branch,
  PR, protected SVG readback and hosted statuses at the stated observation time.

These source-level setup records do not qualify any GPU or hardware phase.

## Roadmap reference

Each entry in a phase's `evidence` array has exactly this shape:

```json
{
  "acceptance_id": "P00-A01",
  "record": "docs/project/evidence/setup-validation.json"
}
```

The example path above shows the reference format; its presence in this guide
does not claim that a corresponding report exists or passes. Paths are relative
to the repository root, never to this directory or a worker's machine. They must
remain inside the repository after normalization and symlink resolution.

## Report contract

| Field | Required meaning |
|---|---|
| `schema_version` | Integer `1` |
| `record_id` | Unique, nonempty identifier for the recorded observation |
| `kind` | `governance`, `design_review`, `simulation`, `rtl`, `fpga`, `silicon` or `release` |
| `outcome` | `pass`, `fail`, `not_run` or `blocked` |
| `evidence_level` | One canonical level from the table below |
| `scope` | What was demonstrated, backend/arithmetic implementation and important boundaries |
| `source_revision` | Full 40-hex commit identifier of the source actually tested |
| `configuration` | Exact configuration description or a precise artifact reference |
| `acceptance_ids` | List of canonical criterion IDs addressed by this report |
| `commands` | Objects containing `command`, `result` and `exit_code` |
| `artifacts` | Objects containing repository-relative `path` and 64-hex `sha256` |
| `limitations` | Explicit list of untested configurations, omissions and claim limits |
| `reviewer` | Actual review identity, or `pending` before review |

| Report kind | Compatible evidence level |
|---|---|
| `governance`, `design_review` | `source_present` |
| `simulation` | `simulated` |
| `rtl` | `rtl_verified` |
| `fpga` | `fpga_measured` |
| `silicon` | `silicon_measured` |
| `release` | The level actually supported by its explicit scope and underlying evidence; packaging alone is `source_present` |

A passing report requires at least one genuinely passing command and one
hash-checked artifact, a valid tested revision, and a non-pending reviewer. It
must include the acceptance ID of every roadmap entry that refers to it. A
stronger level is acceptable only for the same obligation and execution scope;
it does not automatically replace a different kind of proof.

Record exact invocations and working-directory/configuration context in the
command text or associated artifact. A named read-only API observation may be a
command for a delivery/governance check; identify the observation and retain its
sanitized result. Use `null` for the exit code of an unexecuted template command;
never invent exit code zero for a test that did not run. Real command records
retain their observed exit result and explicit outcome.

## Producing a record

1. Copy the template to a uniquely named report; leave it unreferenced while
   placeholders, missing artifacts or pending review remain.
2. Replace placeholders with observed data. Pin the tested source and all
   relevant toolchain/configuration/workload identities. Hardware packets also
   identify the board/part, bitstream, platform, achieved clock and conditions.
3. Retain compact raw logs and manifests, then compute SHA-256 for every listed
   artifact. Do not edit an artifact after recording its digest without creating
   a corrected, reviewable record.
4. Have the appropriate reviewer inspect the packet and limitations. Record
   real review identity and disposition; this does not fabricate a maintainer,
   procurement or manufacturing approval.
5. Attach the report to the relevant acceptance IDs and run the project checker.
   It validates metadata and integrity, not the physical truth of a measurement.

Do not commit large waveforms, model weights, toolchains or proprietary IP merely
to make a report self-contained. Keep a compact manifest with hashes and stable
authorized artifact identifiers; retain large raw evidence through an approved
artifact store. The reviewer must verify access and provenance. The offline
checker does not fetch or authenticate external archives.

Never include credentials, private keys, environment dumps, signed download URLs
or sensitive machine-specific paths. Preserve redistribution permissions for
models, fixtures, PDK collateral and third-party IP. A digest is not a license.

## Retention and changes

Keep historical results tied to their tested revision and contract. Record
failed, blocked and not-run work honestly; do not overwrite it to make a later
pass look uninterrupted. When source, workload, precision or platform changes,
review whether fresh evidence is required. Completing P00 says nothing about
GPU correctness or physical performance until those later gates are exercised.
