# Governance artifact replay v1

## Purpose and trust boundaries

The independent reader reconciles one original ZIP produced by the strict
[Project Governance workflow](../../.github/workflows/project-governance.yml).
The hosted qualified warm gate requires this reconciliation before proceeding
to its existing native admission. Replay does not rerun the recorded suite or
authorize a performance or phase acceptance.

| Evidence layer | Required check | Limit of the result |
| --- | --- | --- |
| Retained internal consistency | ZIP identity, exact member set, completed receipts, ordered events, environment and log joins | Consistent records do not authenticate their producer or reproduce execution. |
| Trusted source and canonical population | Independently selected clean Git revision, materialized source inventory and ordered discovery from that checkout | Discovery imports trusted source code; it does not run test bodies or requalify the recorded tools. |
| Provider binding | Authenticated provider observations join the original bytes to one exact repository, revision, run and current attempt | The local replay receipt alone does not establish this binding. |
| Native qualification | Existing source, input, capacity, native execution and independent native replay requirements | Governance replay establishes no native, hardware, performance or phase acceptance. |

Run the reviewed reader outside the archive. Archive members and recorded
absolute paths are data: no extraction, imports, retained tools, recorded
commands or producer-path reads occur. The explicit `source_dir` is a separate
trusted input. Canonical discovery imports its tracked Python code in a bounded
child, including import-time and discovery hooks. The isolation is not a
security sandbox for an untrusted checkout. The reader's local interpreter and
`/usr/bin/git` are trusted executables, distinct from the original interpreter
and tool identities recorded in the packet.

## Accepted original ZIP

[`governance_replay_archive.py`](../../ci/project/governance_replay_archive.py)
accepts one canonical absolute local path to a stable, singly linked regular
file through directories without symlink components. It hashes the complete
archive before and after inspection and checks file and directory identities.
All members are inspected, even when a caller retains only selected bytes.

The accepted container is a single-disk, non-ZIP64 ZIP with stored or raw
deflate regular-file members. It has no preamble, trailing bytes, archive or
member comments, extra fields, encryption or unsupported record extensions.
Local headers, central entries and optional 12- or 16-byte data descriptors
must agree on names, methods, flags, sizes and CRCs. Records must be contiguous
and nonoverlapping; every deflate stream must finish at its declared extent.
Directory, symlink, device and other nonregular entries are rejected.

Member names use ASCII components matching
`[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*`: at most 512 bytes, 16 components and
255 bytes per component. Empty, `.` and `..` components, absolute paths,
backslashes, duplicate names, case aliases and file/parent collisions fail.

| Container bound | Maximum |
| --- | --- |
| Original ZIP and aggregate compressed member bytes | 256 MiB each |
| One expanded member | 256 MiB |
| Aggregate expanded members | 512 MiB |
| Members | 64 |
| Central directory | 64 KiB |

The orchestrator then requires exactly these **12 nonempty members**, with no
additional entries. These narrower limits are applied after the bounded archive
read; the byte bounds are not a peak process-memory guarantee.

| Required member | Expanded byte limit |
| --- | --- |
| `logs/cmake-install.log` | 1 MiB |
| `logs/cmake-requirements.txt` | 256 bytes |
| `logs/cmake-version.log` | 64 KiB |
| `logs/environment.log` | 16 KiB |
| `logs/governance.log` | 256 MiB |
| `logs/source-revision.txt` | 65 bytes |
| `environment/environment.json` | 1 MiB |
| `run/discovered.json` | 32 MiB |
| `run/events.jsonl` | 32 MiB |
| `run/started.json` | 32 MiB |
| `run/summary.json` | 32 MiB |
| `run/unittest.log` | 128 MiB |

This is the current workflow's versioned packet grammar, not a general ZIP
restorer. An unsupported original fails; removing members or repacking it would
create different evidence.

## Independent reconciliation

[`governance_replay.py`](../../ci/project/governance_replay.py) requires the
caller-selected full lowercase Git object ID and original SHA-256. JSON inputs
must have valid UTF-8, object roots, unique keys, finite numbers and the expected
field types; a boolean cannot substitute for an integer count.

The [record validator](../../ci/project/governance_replay_records.py) joins the
started receipt to a completed, strictly successful summary and the raw checked
environment receipt. It requires stable before/after source, interpreter and
environment identities, clean source inventories, the exact canonical command
and discovery configuration, consistent preparation/run timestamps, checked
tools and successful preparation probes. Source revision text must match the
selected revision exactly. Retained tool hashes, versions, command results and
probe observations are checked for agreement; their original binaries and
producer filesystem are not freshly inspected or executed.

Recorded run output must also be consistent with a fresh directory: it cannot
contain or collide with the environment receipt or live requested/resolved
tool paths. Fresh descendants remain supported. Disposable preparation probes
are not treated as required live inputs after preparation finishes.

The [event reader](../../ci/project/governance_replay_events.py) derives the
entire execution population from the ordered manifest and JSONL stream. Every
canonical ID needs one serial start, successful outcome and stop in discovery
order; subtests and fixtures are accounted separately. Missing, duplicate,
unexpected, reordered or unfinished events fail, as do skips, failures, errors,
expected failures and unexpected successes. All derived statistics and
discrepancies must equal the summary. Limits are 100,000 canonical IDs, 4,096
bytes per ID, 1,000,000 events and 64 KiB per newline-terminated event record,
within the member byte limits above.

Raw event and inner-log sizes must match the summary. Both logs need the same
complete successful unittest trailer and reconciled count; the outer log also
needs the exact strict-runner success line. The inner stream must occur in the
outer stream in byte order, allowing inserted child-process diagnostics. Log
equality is not required because the producer's Python text capture omits some
descriptor/child output. CMake requirement, install and version logs and the
environment log must join the checked preparation receipt. An `OK` line or
success-shaped summary alone cannot qualify a packet.

## Trusted Git source and collection

[`source_binding`](../../ci/project/governance_replay_source.py) verifies the
explicit checkout root, exact HEAD/tree and index, then hashes materialized
tracked bytes and modes against their Git object identities. It rejects dirty
or incomplete source, hidden/sparse index entries, untracked files, replacement
refs, grafts, executable filters, deferred object retrieval and unbound local
Python source or bytecode. Source inventory is bounded to 32,768 entries,
128 MiB per file, 1 GiB of tracked bytes and 32 gitlinks, with a 30-second source
observation deadline. Git subprocess output and duration are bounded.

The independent projection compares HEAD, tree, object format, tracked digest,
count, byte total and sorted gitlink path/pin identities to the retained source.
It does not require the producer's absolute checkout path, Git executable hash
or submodule initialization state to match the reviewer's machine. Top-level
gitlink pins do not establish native dependency closure; hosted native source
admission still requires its complete initialized recursive population.

[`collect`](../../ci/project/governance_replay_collect.py) discovers
`ci/project/test_*.py` from the selected source root using `unittest.TestLoader`.
It runs in an isolated, no-site, no-bytecode child with a sealed environment,
checks tracked Python imports against Git object identities and rejects
unbound source, external third-party imports and invalid discovery leaves.
It collects the ordered IDs without calling a test runner or test body. There
are no test selection, retry, partition or receipt-only bypass options.

The child has a 60-second deadline, 1 GiB address-space limit, 32 MiB result
limit and 1 MiB diagnostic limit. Empty, duplicate, failed-import or excessive
discovery fails. The collector and orchestrator reobserve source around
collection and again before returning the replay result. The entire ordered
discovery list must equal the retained manifest; matching only a total is
insufficient.

## Provider binding and mandatory hosted admission

[`download_artifact`](../../ci/project/p06_governance_artifact.py) takes the
exact revision, run ID and attempt selected by the hosted governance metadata
check. It requires exactly one current, nonexpired artifact named
`project-governance-{revision}-run{run_id}-attempt{run_attempt}`, a provider
`sha256:` digest and bounded positive size. Repository names and numeric
repository identities, head SHA, workflow/run identities and any supplied
artifact attempt field must agree. Current provider artifact metadata may omit
`workflow_run.run_attempt`; the exact artifact name and current successful run
attempt provide that join. All bounded artifact pages are inspected, and the
selected artifact and provider state are reread after download.

Each metadata request uses the isolated
[`p06_governance_api`](../../ci/project/p06_governance_api.py) worker, with a
20-second execution deadline and at most five further seconds to reap it.
The worker accepts at most 4 KiB of private request input and a 2 KiB API path;
its response and output are bounded to 4 MiB. It uses verified TLS, refuses
redirects, and ignores inherited proxy and TLS-key-log settings. Pagination
bounds the number of requests. These per-request limits are separate from
the archive transfer deadline.

Byte retrieval has a 120-second wall deadline and a 256 MiB compressed bound.
The token is sent only to the exact GitHub API ZIP endpoint. Its authenticated
302 response may select one supported numeric `productionresultssa` Azure HTTPS
storage URL; the storage request carries **no provider token** and cannot
redirect again. The worker ignores ambient proxies and TLS key logging, does
not expose the token or signed URL in arguments or public output, and checks
exact transfer size and SHA-256 before exclusive publication. The storage host
grammar bounds transport; the authenticated API redirect and matching provider
digest establish the byte binding.

Acquisition requires Linux anonymous `O_TMPFILE` staging on the selected
filesystem. The staging inode has no pathname and is published exclusively
from its verified descriptor. Unsupported anonymous staging fails admission.
Closing an unpublished descriptor discards the partial download; a failure
after publication retains the uncertain final pathname for inspection. The
provider helper never deletes a pathname based on a prior ownership check.

[`p06_qualified_warm_hosted.preflight`](../../ci/project/p06_qualified_warm_hosted.py)
must download and replay that original against the selected trusted checkout.
It then rechecks source, the same workflow/run/attempt/jobs and the retained ZIP
identity. Only successful completion sets the hosted
`independent_packet_replay`, `provider_observed_stable` and
`source_observed_stable` fields to true. Metadata-only
`verify_governance` still reports `independent_packet_replay: false` and is not
sufficient admission. Reruns, expiry, missing or duplicate artifacts, changed
observations, digest mismatches and replay failures stop admission; no older
artifact or green status is substituted.

The hosted run retains `hosted/governance/governance.zip`, `provider.json` and
`replay.json` in its existing private attempt envelope. Standalone preflight
uses and removes an owned temporary directory. This check precedes private
control intake, input acquisition and native launch. The existing capacity,
tool, dependency and native gates remain required.

## Interfaces and result scope

The local API is
`verify_archive(path, *, revision, source_dir, expected_sha256)`. The CLI requires
`--archive`, `--expected-revision`, `--source-dir` and `--expected-sha256`;
`--output` optionally creates a fresh canonical absolute receipt file outside
the trusted source checkout. It never replaces an existing path and rejects
symlink ancestors and aliases. Optional file output requires Linux `O_TMPFILE`
support on its destination filesystem, uses exclusive descriptor publication,
and preserves an uncertain published pathname if a later check fails. Failed
unpublished writes leave no named receipt. The receipt is also printed to stdout. CLI
failure exits 1 with only `governance replay failed`; hosted admission exposes
the static `governance_admission` failure. Raw exceptions, retained paths,
tokens and signed URLs are not public diagnostics.

The version-1 receipt has scope `project-governance-artifact-replay-only` and
records selected source/tree/inventory identity, canonical count and digest,
successful subtests, events, duration, original ZIP identity, environment digest
and event/log byte counts. `independent_packet_replay` and
`trusted_source_imported` are true. `provider_authenticated`,
`retained_code_executed`, `tests_executed_by_replay`, `native_acceptance`,
`phase_acceptance` and `performance_acceptance` are false. Hosted provider
evidence is a separate enclosing record; it does not rewrite these local
receipt claims.

Use the [operator guide](../project/governance-artifact-replay.md) for a
reproducible historical-original command and failure handling. Observed results
belong in the [audit](../project/p06-governance-replay-audit.md) and
[evidence index](../project/evidence/p06-governance-replay/README.md). The changed
implementation requires its own final published revision's complete strict
governance invocation; replaying a historical original cannot qualify new code.
