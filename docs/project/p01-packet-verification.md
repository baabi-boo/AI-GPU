# Verify a retained P01 execution packet

The [offline verifier](../../ci/project/baseline_packet.py) checks the retained
output of the [P01 runner](../../ci/project/baseline.py). It does not run a GPU,
rebuild a simulator, download dependencies or execute the retained helper files.
This is P01-T06 review tooling. Passing verification does not accept a roadmap
gate or complete P01; follow the [acceptance policy](acceptance.md).

Use `verify` or `seal` for original retained bytes. Use the explicit
[`verify-export` mode](#verify-a-published-path-redacted-export) for a published
derivative with an export mapping. The modes make different claims and do not
automatically substitute for one another.

## Verify original bytes before reviewing numerical claims

Run from the source root on Linux with Python 3.12 or newer. The reader requires
POSIX directory-relative, no-follow file access and rejects platforms without
those capabilities; Windows is not supported. Point the command at the
runner's original output directory, or a byte-preserving copy, after the run has
stopped:

```sh
python3 ci/project/baseline_packet.py verify /absolute/path/native-run
```

The directory must contain the original `report.json`, `matrix.json`, command
logs, configuration stamps and helper snapshots referenced by that report.
Keep their bytes unchanged. The original GPU checkout, build products and tool
installation are not required for offline verification.

Verification separates the command result from the recorded execution result:

| Output | Meaning |
|---|---|
| `integrity: verified` | The stopped-run records, frozen matrix semantics and referenced retained evidence satisfy the verifier's consistency and hash checks |
| `outcome` / `requirement_satisfied` | Whether this verifier invocation meets its requested checks; without `--require-native-pass`, valid integrity is sufficient |
| `run_outcome` | The original runner's recorded result, preserved even when it is a failure |
| `native_matrix_passed: true` | The records show successful completion of all six frozen native cases, their required reference/configuration checks and final provenance checks |
| `phase_complete: false` | Offline verification never grants phase acceptance; full vendor XRT integration and independent review remain separate |

A valid record of a failed or selected-case run can pass integrity verification.
Without `--require-native-pass`, exit status 0 and `outcome: pass` therefore do
not imply `run_outcome: pass` or a complete native matrix. To require the entire
numerical matrix as well, use:

```sh
python3 ci/project/baseline_packet.py verify /absolute/path/native-run \
  --require-native-pass
```

The stricter invocation returns a nonzero exit if the six-case requirement is
unsatisfied, including when the preserved packet itself has valid integrity.
Running or planned reports are rejected rather than treated as final results.
Prerequisite-blocked reports (`state: blocked`) are also rejected, whether or
not a retained matrix is present. A finished run that stopped at a blocked
command can be verifiable when its retained records satisfy the contract.
Preserve unsupported or incomplete stopped records unchanged; stopping a run
alone does not make its packet verifiable.

## Interpret interrupted runs and provisional passes

A finished report with `outcome: fail` and the exact reason
`execution interrupted` may retain an ordered prefix of the runner's work.
The verifier accepts supported interruption boundaries while preserving that
failed run outcome. It still requires completed command records, contiguous
provenance observations, the frozen command order and no execution after a
terminal failed, blocked or interrupted case. Active-command or active-case
fields, gapped observations and unrelated failure reasons do not excuse
incomplete evidence.

The summary classifies the selected cases as follows:

| Output | Meaning |
|---|---|
| `passed_ids` | Cases with successful configure/workload commands, completed boundary provenance, verified CPU-reference markers and complete configuration/binary capture records |
| `failed_ids` | Cases recorded as `fail` or `blocked` |
| `interrupted_ids` | The terminal case whose preparation started, or whose workload passed, before the interruption prevented completion of its required evidence |
| `not_run_ids` | Selected cases with no started case work |

The runner records a workload's process success before checking its reference
marker and capturing its evidence. A case may therefore still say
`outcome: pass` in the unchanged report while the verifier places it in
`interrupted_ids`, not `passed_ids`. A successful process exit alone is a
provisional result. Even a verified reference marker does not complete a case
when configuration and binary capture is missing.

An interruption before case work can leave every selected ID in `not_run_ids`.
An interruption during final run observations can leave every selected ID in
`passed_ids` and `interrupted_ids` empty. Neither establishes native matrix
success: the run must finish successfully with all six cases and the final
provenance checks. A valid interrupted packet can return `outcome: pass` from
ordinary integrity verification, but `--require-native-pass` returns a nonzero
exit with `requirement_satisfied: false` and `native_matrix_passed: false`.

## What the verifier checks

The verifier derives coverage from the frozen
[matrix](../../ci/project/p01_baseline.json), rather than trusting the report's
success flags. It checks case identities, dimensions, precision, reference
contract, command sequence and arguments, recorded configuration, log digests,
CPU-reference success markers and retained application/runtime/backend stamps.
Passed cases must retain the native TFR tensor and STD scalar settings with
both `VX_CFG_XLEN=64` and an effective `VX_CFG_XLEN_64=1` companion. Other
`VX_CFG_XLEN_*` selectors are rejected, including a conflicting selector defined
as zero. A macro consumed as another option's operand cannot satisfy these
requirements. DPI arithmetic cannot qualify the native tensor result.

It also checks source identity across recorded case boundaries, build metadata,
helper snapshots, dependency identities, and the final tool/host observations
required by a successful run. GPU source and instrumentation revisions are
separate identities and may differ. Recursive submodule entries need not equal
the number of top-level declarations.

Some identities describe artifacts that the runner does not retain, including
compiled binaries and dependency libraries. Offline verification checks their
recorded identities and consistency; it cannot reconstruct those artifacts or
prove their provenance solely from a digest. Clean-build review remains part of
P01-A01. Likewise, a valid log and reference marker do not independently prove
that the runner, reference algorithm or machine was trustworthy.

In the historical runner packet format, the report records the raw input
matrix's digest and size but the retained `matrix.json` is reserialized. These
bytes may differ even when the parsed matrix is identical. The verifier checks
the retained matrix against the frozen semantic contract; the original input
digest and size remain provenance assertions because those input bytes are not
retained. The manifest hashes the actual retained `matrix.json` bytes. It does
not substitute that identity for the reported input identity.

## Freeze a compact inventory for later checks

For an original packet, create an unsigned manifest outside the packet using a
new output filename:

```sh
python3 ci/project/baseline_packet.py seal /absolute/path/native-run \
  --output /absolute/path/native-run-manifest.json --require-native-pass
python3 ci/project/baseline_packet.py verify /absolute/path/native-run \
  --manifest /absolute/path/native-run-manifest.json --require-native-pass
```

The manifest contains a deterministic, sorted list of the evidence files read,
their SHA-256 hashes and sizes. It adds no timestamp, absolute workspace path,
copied log, binary, toolchain or archive. Existing output files are never
overwritten, and the retained packet is never edited. Repeating a seal over
unchanged evidence produces the same manifest bytes.

The output's parent directory must already exist. With `--require-native-pass`,
`seal` writes no manifest when the full native requirement is unmet, even if
integrity is valid. Omit that flag to inventory a valid failed or selected-case
packet. A write failure can leave a partial output file; the error reports this,
and a retry will not overwrite it.

The inventory covers **referenced evidence files**, not every unrelated file in
the directory. It is unsigned. Anyone who can replace both evidence and its
inventory can produce new matching hashes; retain the reviewed manifest through
the repository's normal provenance and review process. Rechecking an inventory
detects changes to the referenced packet, not the truth of a measurement.

## Verify a published, path-redacted export

A publication derivative can retain the original report while replacing
sensitive path text in command logs. Its published log bytes then have different
identities from the original log hashes and sizes inside the report. Preserve
both identities; do not rewrite the report's nested hashes to make a redacted
log pass original-byte verification.

Use the directory containing `export-manifest.json`, `report.json`,
`matrix.json` and their referenced packet-relative files:

```sh
python3 ci/project/baseline_packet.py verify-export /absolute/path/published-packet \
  --require-native-records
```

The [export verifier](../../ci/project/baseline_packet_export.py) checks the
published bytes and reuses the frozen record contract. With
`--require-native-records`, exit status 0 requires complete, consistent records
for all six native cases and final provenance. Omit that flag to check a valid
failed, interrupted or selected-case export without requiring the complete
matrix. In that mode, `outcome: pass` describes the verification request and
does not change `run_outcome`. A valid incomplete export fails the stricter
request with `requirement_satisfied: false` while retaining
`published_integrity: verified`.

| Export output | Meaning |
|---|---|
| `verification_mode: published_export` | The explicit published-export contract was used |
| `published_integrity: verified` | The mapped published bytes and retained records satisfy the export and frozen record checks |
| `native_matrix_records_consistent: true` | The records, published log markers, unchanged configuration snapshots and final provenance consistently describe the complete passing native matrix |
| `raw_log_bytes_verified: false` | Original command-log bytes were not verified or reconstructed |
| `redaction_relationship_verified: false` | The asserted transformation from original bytes to published bytes was not verified |
| `published_files` | Observed hashes and sizes of referenced published members, including `export-manifest.json` |
| `phase_complete: false` | Export verification grants no project-gate or phase acceptance |

`native_matrix_records_consistent` is deliberately separate from the original
mode's `native_matrix_passed`. Export output does not include the original
mode's `integrity`, `native_matrix_passed` or seal `manifest` fields. Even an
export containing only copies retains these published-mode boundaries.
`verify-export` requires its named export manifest; it does not accept
`--manifest` or `--require-native-pass`. Conversely, `verify` and `seal` do not
accept `--require-native-records`, and their original log checks reject changed
log bytes. An export manifest is not a seal manifest.

### Keep original and published identities distinct

The version-1 `export-manifest.json` records `schema_version: 1`, `source_packet`,
`reported_outcome`, `scope`, `limitations`, `sanitization` and an `artifacts`
list. Its `reported_outcome` must match the copied report's `outcome`. Each
artifact row has exactly these fields:

| Fields | Meaning |
|---|---|
| `path`, `sha256`, `size_bytes` | Published member path and the identity checked against its retained published bytes |
| `source_path`, `source_sha256`, `source_size_bytes` | Original member path and asserted original identity; for command logs, the hash and size must match the unchanged report's command record |
| `transformation` | Either `byte_preserving_copy` or `literal_path_redaction` |

The mapping must cover **exactly the referenced packet members**, including the
report, retained matrix, command logs, configuration stamps and helper
snapshots. Missing rows, duplicate source or published paths, extra mapped
files and unreferenced redacted logs are rejected. The export manifest itself
is read and included in `published_files`, but is not an artifact row. Unrelated
files present in the directory are outside the inventory.

Each source path must be under `source_packet`. The public paths may share a
publication prefix, but stripping the respective source and public prefixes
must yield the same packet-relative member. The verifier opens only those
members beneath the supplied packet directory. The prefixes are metadata, so
relocation does not require access to the original workspace or publication
directory.

For `byte_preserving_copy`, source and published hashes and sizes must be equal.
Only referenced command logs under `logs/` with a `.log` suffix may declare
`literal_path_redaction`, and they require declared sanitization rules. Keep
`report.json`, `matrix.json`, configuration stamps and helper snapshots as
byte-preserving copies. Their original checks remain in force: the frozen
matrix, command arguments, numerical reference, provenance, captured
configuration, native flags and retained non-log identities are not relaxed.
Changing a helper or stamp and refreshing its public mapping cannot override
the report's retained identity. Published workload logs must still satisfy the
recorded CPU-reference marker checks. Both the asserted source log size and
the published log bytes must fit the command's byte limit.

Sanitization metadata contains `method`, `nested_hash_policy` and `rules`.
Rule source prefixes use `${RAW_WORKSPACE}` or a canonical relative suffix
beneath it; replacements are symbolic labels such as `$WORKSPACE`. These rules
and source paths are inert metadata. The verifier does not apply the rules,
open source paths or execute retained code. Matching published hashes and
original identity assertions in an unsigned manifest cannot authenticate who
produced the packet or prove that redaction preserved all original content.
Review that relationship independently using retained original evidence.

## Resource and file safety

Reads reject absolute or traversing member paths, symlinks and nonregular files.
The packet root and directory ancestors must also be real directories, without
symlinks. These checks apply to referenced evidence; the verifier does not scan
unrelated directory contents.

The [packet reader](../../ci/project/baseline_packet_io.py) and verifier enforce
these inspection limits:

| Input or budget | Limit |
|---|---|
| Referenced packet files | 128 paths and 512 MiB summed once per path; rereads do not consume the budget again |
| `report.json` | 8 MiB |
| Retained `matrix.json` | 256 KiB |
| Each retained command log | The smaller of 16 MiB and the report's `budget.max_log_bytes` |
| Each retained configuration stamp or helper source | 1 MiB |
| External manifest | 1 MiB, read separately from the packet budget |
| `export-manifest.json` | 1 MiB, counted within the published packet budget; at most 127 mapped artifacts plus the manifest |

JSON must be a UTF-8 object and rejects duplicate fields and nonfinite numbers.
The parser bounds nesting at 64 levels, counted JSON structure at 250,000 tokens,
and numeric tokens at 1,024 characters. These limits bound evidence inspection;
they do not change the GPU runner's execution budgets or impose an operating
system memory or time limit on the verifier.

Files are checked again before success to detect changes while verification is
in progress. Stop the producing run first. No local file protocol can make a
directory controlled by a concurrent writer permanently immutable.

Review raw logs for sensitive paths or other nonpublishable content before
sharing. Redacting the original packet changes its hashes. Keep original
evidence and any publication derivative distinct, with an explicit mapping and
independent review; do not silently rewrite the runner's original digests.
`verify-export` checks an existing derivative; it does not create or redact one.

## Development checks and handoff

The synthetic fixtures used by the verifier tests are test data, never GPU
acceptance evidence. Run the normal source-root checks:

```sh
python3 -m unittest discover -s ci/project -p 'test_baseline_packet*.py'
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

Retain exact commands, revisions and review findings in the continuation
handoff. Attach only independently reviewed evidence for criteria it actually
satisfies. Processor `rtlsim`, even when every native case passes, does not close
P01-A03's full vendor XRT `hw_emu` requirement or establish physical FPGA results.
