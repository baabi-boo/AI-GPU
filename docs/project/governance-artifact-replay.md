# Governance artifact replay operator guide

Governance replay checks one original strict-governance ZIP against an
independently selected digest and exact trusted source checkout. It reconciles
recorded execution; it does not run the test bodies or repeat native work.
The [implemented contract](../designs/governance_artifact_replay_v1.md) defines
the accepted ZIP grammar, limits, source collection and provider boundary.
Observed verification and publication results live in the
[audit](p06-governance-replay-audit.md), with retained inputs in the
[evidence index](evidence/p06-governance-replay/README.md).

## Select the reader, source and original independently

Use a reviewed reader checkout, a trusted local Python interpreter and
`/usr/bin/git` on Linux. The reader code comes from that checkout, never from
the archive. The source checkout is the exact clean revision whose canonical
test population is being checked. Discovery **imports this trusted source** in
a bounded child, including import-time/discovery hooks, without running test
bodies. Isolation does not make an unknown checkout safe to import.

Select the full revision and original SHA-256 from independently reviewed
provenance before invoking replay. A digest calculated only from the suspect
download establishes no independent identity. For hosted admission, the
authenticated provider observation supplies the expected original digest and
the exact run/attempt binding.

The retained historical base is source
`f3123513bb5bc5fa1c409bf0e7366d2f47c2d85b`, run `45625012254`, attempt `1`,
artifact `15032214051`. Its independent recorded SHA-256 is
`a7df58f9462692e9994a8a9f2a15a8c2cd4f59301272c0d446b01353620059a0`;
see [base-original.json](evidence/p06-governance-replay/base-original.json) and
the [provider run](https://github.com/baabi-boo/AI-GPU/actions/runs/45625012254).
The following command keeps the current reader separate from the exact base
checkout and leaves the receipt outside that checkout. Start at the reviewed
reader repository root; the selected base commit must already be available
locally.

```bash
set -euo pipefail
umask 077
P06_GOV_READER="$(pwd -P)"
P06_GOV_REVISION=f3123513bb5bc5fa1c409bf0e7366d2f47c2d85b
P06_GOV_SHA256=a7df58f9462692e9994a8a9f2a15a8c2cd4f59301272c0d446b01353620059a0
P06_GOV_REVIEW="$(mktemp -d /tmp/p06-governance-review.XXXXXX)"

git -C "$P06_GOV_READER" worktree add --detach \
  "$P06_GOV_REVIEW/source" "$P06_GOV_REVISION"
git -C "$P06_GOV_READER" rev-parse HEAD > "$P06_GOV_REVIEW/reader-revision.txt"

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  "$P06_GOV_READER/ci/project/governance_replay.py" \
  --archive "$P06_GOV_READER/docs/project/evidence/p06-governance-replay/originals/run-45625012254-attempt1.zip" \
  --expected-revision "$P06_GOV_REVISION" \
  --source-dir "$P06_GOV_REVIEW/source" \
  --expected-sha256 "$P06_GOV_SHA256" \
  --output "$P06_GOV_REVIEW/replay.json"
```

All four named input arguments are required. Paths must be canonical absolute
paths without symlink components. `--output` is optional; success prints the
receipt to stdout and, when requested, exclusively creates a mode-0600 output
file. Its parent must already exist, and the destination must be absent and
outside the trusted source checkout. A rerun needs a fresh output path. Retain
the receipt with the reader revision and original provenance; a dirty reader
tree also needs an exact source record before claiming a reproducible review.

Optional file output requires Linux `O_TMPFILE` support on its destination
filesystem. Failed unpublished writes leave no named receipt. If a check fails
after exclusive publication, the uncertain pathname is preserved for inspection;
the writer never deletes it based on an earlier ownership observation.

Do not extract the original or run its recorded paths. The source observer
requires exact tracked materialization and rejects untracked files and unbound
Python caches. A separate clean worktree avoids incidental test outputs in the
selected source. Top-level gitlink pins are checked without requiring native
dependency initialization; this does not relax the hosted native checkout gate.

## Interpret the result

A successful receipt has scope `project-governance-artifact-replay-only`.
`independent_packet_replay: true` means the original, complete ordered event
population, receipts and logs agree with the independently checked source and
canonical discovery. `trusted_source_imported: true` makes the collection
boundary explicit. The original tool/interpreter identities remain recorded
observations; replay does not freshly hash missing original binaries or execute
their probes again.

The local receipt keeps `provider_authenticated`, `retained_code_executed`,
`tests_executed_by_replay`, `native_acceptance`, `phase_acceptance` and
`performance_acceptance` false. Preserve separate provider evidence for origin
and run/attempt claims. A local historical replay can remain useful after a
provider artifact expires, but it cannot satisfy a current hosted download and
admission check by itself.

| Failure or change | Required response |
| --- | --- |
| Exit 1 and `governance replay failed` | Preserve the original and failed invocation's scope. Check the selected inputs and supported contract; the public error deliberately omits raw retained data. |
| Existing or aliased output path | Choose a new absent canonical path outside the source checkout. Do not overwrite earlier evidence. |
| Wrong digest, missing members, truncated records or inconsistent events/logs | Obtain and inspect the correct unchanged original. Do not repair, trim or repack it, or substitute a newly calculated expected digest. |
| Wrong/dirty source, unbound imports or changed canonical IDs | Use a dedicated checkout of the independently selected exact revision and resolve source integrity or discovery failures. There is no selection or source-bypass flag. |
| Provider expiry, missing/duplicate artifact, changed run attempt or changed metadata | Hosted admission fails. Obtain a complete strict result and original for the selected published revision/current attempt, then begin fresh admission. Do not reuse a previous attempt's artifact. |

## Hosted operation and next qualification

The [hosted preflight](../../ci/project/p06_qualified_warm_hosted.py) now requires
metadata success **and** a provider-bound original download, independent replay,
unchanged source and unchanged provider observations before admitting the later
stages. There is no metadata-only fallback. A run keeps the original and
separate provider/replay records under `hosted/governance/` in its private
attempt envelope; standalone preflight removes its temporary download. Provider
authentication goes only to GitHub's API; the following storage download never
receives that token. Tokens and signed storage URLs must not enter evidence.

Metadata requests have a supervised 20-second execution deadline and a bounded
five-second cleanup wait. The original ZIP transfer has its separate 120-second
deadline. A socket timeout alone is insufficient to bound DNS resolution;
failed worker supervision stops admission.

Artifact acquisition requires a Linux filesystem that supports anonymous
`O_TMPFILE` staging. Unsupported staging fails admission. The helper discards
unpublished partial bytes by closing their descriptor; if verification fails
after publication, it retains the uncertain final pathname rather than risking
deletion of a concurrent replacement. Inspect that failed attempt before
starting a new one.

The retained base result qualifies that base source only. All changed replay,
transport and hosted code needs the final published revision's own complete,
unfiltered, uninterrupted strict invocation under the
[checked environment](governance-runbook.md), with zero skips and retained
originals. Focused tests, canonical collection and historical-original replay
are distinct development/review evidence, not substitutes for that invocation.

The P06 qualified warm experiment remains unstarted: **24 processes, 792 launches
and 25,344 checked FP32 words**. Preserve the **15 GiB free-disk and 4 GiB
available-memory gates**, exact private input delivery and public age-recipient
requirements. Follow the [hosted operator guide](p06-hosted-warm-guide.md) after
the new published source qualifies and unchanged native admission passes.
P06-A02/A03 remain open; governance replay closes no acceptance gate and does
not remove the separate P01 vendor-integration blocker.
