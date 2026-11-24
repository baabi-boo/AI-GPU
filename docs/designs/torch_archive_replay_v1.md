# Installed PyTorch archive replay v1

## Purpose and boundary

The P05 installed qualification produces separate native, copying Python and
PyTorch observations. An independent reviewer needs to check those observations
after the original runner and its temporary installation have disappeared.
Replay reads a caller-selected original ZIP as data and reports whether its
retained observations are internally consistent with the frozen P05 contract.

The caller supplies the original archive SHA-256, exact source revision and
format independently. A matching digest identifies bytes; it does not prove
their origin or that an arbitrary producer executed an accelerator. Provider
metadata and independent review remain separate evidence. Replay never grants
P05-A02/A03 or any other acceptance, and does not rerun an experiment.

## Trusted reader and untrusted records

Use the existing reviewed `archive_reader.py` without changing its format,
resource bounds or source pin. It checks the original identity before parsing
and again before closing. Retained Python, shared libraries, executables,
scripts and wheels are data. Do not import, execute or extract archive members.
Recorded absolute paths are interpreted syntactically; do not open them or
reconstruct the producer's directory tree.

The live installed validators continue to require the actual installation and
its bytes. A separately named retained-data entry point shares their numerical,
dispatch, lifecycle and raw-log checks. Its installation identity comes from
verified retained descriptors, package bytes and inventory joins. Selecting
replay must not disable or monkeypatch a live validation function.

## Required reconciliation

For each original, the reader checks the declared format and source, finished
successful reports, clean before/after source identities, bounded completed
command receipts and their exact raw logs. Nested copies of an existing packet
must agree byte for byte and contribute no additional executions.

The native comparisons are reconstructed from their retained raw logs with the
trusted P03/P04 record parsers and frozen fixtures. Actual hidden, bridge and
final model results remain distinct from their reference arrays. Reconcile the
plain Python and framework observations against those native results, including
both output poisons, all three matmul signatures and all five model families for
the selected format.

For the framework calls, check the actual operand layouts and bytes, result
bytes, schema and version, native dispatch, five-event profiling records,
successful explicit close, resource restoration and raw-log agreement. Derive
counts from validated observations, then compare recorded summaries with those
counts. A successful label or cached summary is insufficient.

Package checks join the retained bound wheel, first-party installed files,
adapter and extension identities, bundle artifacts and before/after installed
inventories. The third-party framework binaries and full wheelhouse are not
retained in these originals. Their locked identities, payload inventories and
stability observations can be checked for consistency; replay cannot freshly
hash missing third-party bytes. State that limit explicitly. The same distinction
applies to compiler, interpreter and dependency receipts whose binary or source
bytes were not archived. Supplementary fault-test files can be retained and
hash-checked without revalidating every host fault-test assertion; report that
separate scope explicitly.

## Results and limitations

A single-format original contains 16 framework calls and 36 framework-route
native launches. It also contains 36 native comparison launches and 36 plain
Python launches, for 108 distinct launches. Copies of these records are not new
runs. A combined FP16/BF16 review must validate each original independently and
require the same selected source revision before reporting 32 framework calls
and 216 distinct launches.

Every replay result reports `native_execution="not_run"`,
`retained_code_executed=false`, `acceptance_claimed=false` and
`phase_acceptance=false`. Successful retained consistency is not current-source
native execution, third-party binary requalification, physical hardware
evidence, a performance result or phase completion.

Tests cover malformed or missing records, changed operands/results, failed
cleanup, altered versions and identities, incomplete command inventories,
duplicate or inconsistent packet copies, and attempts to access producer paths
or execute retained code. Synthetic fixtures remain labelled as host-only
validation. Original-artifact reviews retain the independently supplied digest
and exact reader revision separately from the original execution revision.
