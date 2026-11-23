# Original dependency evidence: intake and inert replay

Use the reviewed [v1 contract](../../../designs/dependency_provenance_v1.md)
and [handoff](../../p06-dependency-provenance-handoff.md) to select an original,
then use one of the three readers below. These commands review retained bytes;
they do not build dependencies or run the retained application.

**Recorded availability, 2026-11-23:** the last supplied observation of
[hosted run 45146777986](https://github.com/baabi-boo/AI-GPU/actions/runs/45146777986)
was `queued`. This guide has no completed original ZIP or actual artifact ID to
publish. Recheck the provider before intake; a queued workflow is not execution
evidence. The [separate host diagnostic](host-diagnostic/README.md) was prepared
and unexecuted at authoring. Its full 406-source plan, and any eventual host
compilation result, retain that lower scope. They cannot replace a hosted
original, native population, loader joins or independent original review.

## 1. Establish the external intake record

1. Independently select the repository, run, **attempt**, executed `head_sha`,
   job and artifact. Retain the actual provider responses, retrieval time and
   raw job log. For the pending original, the stable API resources are
   [run metadata](https://api.github.com/repos/baabi-boo/AI-GPU/actions/runs/45146777986),
   [jobs](https://api.github.com/repos/baabi-boo/AI-GPU/actions/runs/45146777986/jobs)
   and [artifacts](https://api.github.com/repos/baabi-boo/AI-GPU/actions/runs/45146777986/artifacts).
   Record the real numeric artifact ID, exact name, size and provider digest
   when supplied. A workflow's artifact-name template is not an observed
   artifact identity. Match job conclusion and step records to the selected
   attempt; a successful upload alone does not establish a successful build.
2. Retain the downloaded **original ZIP unchanged**. Record its byte length and
   SHA-256 outside the packet, tied to those API identities. Do not extract,
   repack, rename members, merge attempts or discard unfavorable evidence.
   Review an existing ZIP through the bounded reader, never by importing or
   executing files it contains.
3. Establish the report/snapshot expectations below during independent intake
   of that selected original, and preserve them separately from the candidate
   packet. Use exact raw member bytes, not normalized or reserialized JSON.
   A candidate's own digest fields do not establish external expectations.
   Stop on a mismatch; do not repin a replacement merely to make replay pass.
4. Record the trusted reader checkout revision and any local modifications
   used for review. This revision may differ from the original's execution
   revision. The latter comes from the selected run and is joined to retained
   source, build, native and hosted records. These checks establish consistency;
   caller-supplied pins do not cryptographically authenticate GitHub or a
   producer. Retain the provider intake record for that separate attribution.

Populate these shell variables from the external intake record. All SHA-256
values are 64 lowercase hexadecimal characters; the execution commit is 40.
Member paths are relative to the selected hosted root inside the ZIP.

| Shell variable | Exact external expectation | Required scope |
|---|---|---|
| `P06_SOURCE_REVISION` | Selected run's executed Git commit (`head_sha`) | All |
| `P06_ZIP_SHA256` | Entire untouched ZIP | All |
| `P06_DEPENDENCY_RECEIPT_SHA256` | `dependency-build/report.json` | All |
| `P06_NATIVE_REPORT_SHA256` | `native-lifetime/report.json` | Native, combined |
| `P06_NATIVE_SOURCE_BEFORE_SHA256` | `native-lifetime/snapshots/source-before.json` | Native, combined |
| `P06_PROBE_REPORT_SHA256` | `pending-probe/report.json` | Combined |
| `P06_SUBSTITUTION_REPORT_SHA256` | `dependency-substitution/report.json` | Combined |

**`--source-manifest-sha256` means the exact native `source-before.json` bytes.**
The [dependency Git manifest](source-inputs/README.md), its canonical digest,
the 406-unit source plan and a Git tree hash are different identities. None can
substitute for this native snapshot pin or for the execution commit.

## 2. Choose literal prefixes and fresh outputs

Run from the trusted repository root. Set `P06_ARCHIVE` to the absolute original
ZIP path, and `P06_REVIEW_DIRECTORY` to a new absolute directory whose parent
already exists. The commands below leave unavailable expectations unset and
fail before replay if a required value is missing.

| ZIP layout | `P06_HOSTED_PREFIX` | Dependency reader prefix |
|---|---|---|
| `job.json`, `dependency-build/`, `native-lifetime/`, ... | Empty string | `dependency-build` |
| `evidence/job.json`, `evidence/dependency-build/`, ... | `evidence` | `evidence/dependency-build` |

Select the literal reviewed prefix; do not search for a favorable report.
Prefixes use forward slashes, without leading/trailing slashes or traversal.

```bash
git rev-parse HEAD
git status --short
: "${P06_ARCHIVE:?Set the absolute original ZIP path}"
: "${P06_REVIEW_DIRECTORY:?Set a new absolute review directory}"
: "${P06_SOURCE_REVISION:?Set from external intake}"
: "${P06_ZIP_SHA256:?Set from external intake}"
: "${P06_DEPENDENCY_RECEIPT_SHA256:?Set from external intake}"
P06_HOSTED_PREFIX="${P06_HOSTED_PREFIX-}"
P06_DEPENDENCY_PREFIX="${P06_HOSTED_PREFIX:+${P06_HOSTED_PREFIX}/}dependency-build"
mkdir -- "$P06_REVIEW_DIRECTORY"
```

Keep the shell output and command exit status with the review record. Each
`--output` creates a **new** JSON file exclusively; its parent must exist. An
existing file is rejected and preserved. Omit `--output` to receive the complete
result on stdout; with it, stdout contains a summary. Keep failed attempts and
use a new destination for a retry.

## 3. Run the appropriate reader

Choose the needed scope. The combined reader includes dependency/native
validation, so a complete original does not require three redundant replays.

### Dependency only

The [dependency reader](../../../../ci/project/p06_dependency_replay.py)
checks the selected dependency packet, including source/build/product
consistency. It does not review the native population or behavioral controls.

```bash
python3 -B ci/project/p06_dependency_replay.py \
  --archive "$P06_ARCHIVE" \
  --sha256 "$P06_ZIP_SHA256" \
  --source-revision "$P06_SOURCE_REVISION" \
  --dependency-receipt-sha256 "$P06_DEPENDENCY_RECEIPT_SHA256" \
  --prefix "$P06_DEPENDENCY_PREFIX" \
  --output "$P06_REVIEW_DIRECTORY/dependency.json"
```

### Complete native original

The [native reader](../../../../ci/project/p06_dependency_native_replay.py)
also joins hosted identity, workflow/provision records, dependency preparation,
managed build and loaded products, source snapshots and raw lifetime evidence.
The separate pending and alternate-library controls remain outside this scope.

```bash
python3 -B ci/project/p06_dependency_native_replay.py \
  --archive "$P06_ARCHIVE" \
  --sha256 "$P06_ZIP_SHA256" \
  --source-revision "$P06_SOURCE_REVISION" \
  --dependency-receipt-sha256 "$P06_DEPENDENCY_RECEIPT_SHA256" \
  --native-report-sha256 "${P06_NATIVE_REPORT_SHA256:?Set from external intake}" \
  --source-manifest-sha256 "${P06_NATIVE_SOURCE_BEFORE_SHA256:?Set from external intake}" \
  --prefix "$P06_HOSTED_PREFIX" \
  --output "$P06_REVIEW_DIRECTORY/native.json"
```

### Native original plus both separate controls

The [combined reader](../../../../ci/project/p06_dependency_control_replay.py)
adds raw pending-probe/always-zero evidence and the alternate dependency's
source/build/product joins, separate transcript, chronology and rejection of
the original library. **Its archive is positional and its revision flag is
`--expected-revision`.** The other two readers use `--archive` and
`--source-revision`.

```bash
python3 -B ci/project/p06_dependency_control_replay.py "$P06_ARCHIVE" \
  --sha256 "$P06_ZIP_SHA256" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --dependency-receipt-sha256 "$P06_DEPENDENCY_RECEIPT_SHA256" \
  --native-report-sha256 "${P06_NATIVE_REPORT_SHA256:?Set from external intake}" \
  --source-manifest-sha256 "${P06_NATIVE_SOURCE_BEFORE_SHA256:?Set from external intake}" \
  --probe-report-sha256 "${P06_PROBE_REPORT_SHA256:?Set from external intake}" \
  --substitution-report-sha256 "${P06_SUBSTITUTION_REPORT_SHA256:?Set from external intake}" \
  --prefix "$P06_HOSTED_PREFIX" \
  --output "$P06_REVIEW_DIRECTORY/combined-controls.json"
```

## 4. Interpret and preserve the result

Require the actual successful exit and passing full JSON, not a substring in a
log. Retain failures and their diagnostics without turning them into execution
results. These readers leave `native_execution="not_run"` and
`retained_code_executed=false`: any execution evidence belongs to the original
producer. Synthetic packets remain synthetic even when consistent.

The native population is four FP16/BF16 × allocation-policy processes,
**132 launches and 4,224 exact FP32 words**. The pending-probe/always-zero pair
is separate, as is the alternate dependency's **one process, 33 launches and
1,056 words**. Never add controls to managed totals. Other outer members may
be listed without semantic verification; successful scope is explicit in the
result, not everything that happened to share the ZIP.

The [archive reader](../p05-torch/reviews/archive_reader.py) limits the original
ZIP to 256 MiB, expanded members to 1 GiB and membership to 20,000 entries, with
additional cumulative read limits and strict name/JSON checks. The
[dependency contract](../../../../ci/project/p06_dependency_contract.py)
adds tighter packet/file limits. Review reads members without extracting them,
rehashes the ZIP at completion and checks trusted reader-source stability.
Producer paths, retained commands, binaries and Python remain inert.

A pass establishes the selected retained consistency only. It does not establish
fresh execution by the reader, complete compiler/system provenance, complete
40-component lifetime qualification, no-wrap bounds, warm performance,
P06-A02/A03 or hardware acceptance. All seven fields remain false:
`qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
`acceptance_claimed`, `phase_acceptance` and `performance_acceptance`.
