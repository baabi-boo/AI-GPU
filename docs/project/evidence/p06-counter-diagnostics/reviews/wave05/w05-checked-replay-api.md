# Counter diagnostic replay shared API (wave 5)

Implemented: `ci/project/p06_counter_diagnostics_replay.py`. No archive code is executed.

Public helpers:

- `open_archive(path, sha256, *, prefix)` context manager yields `(packet, archive)`, using the digest-pinned `p06_replay._archive_api()` and its bounded `ArchiveReader`. `packet` is a `DiagnosticPacket` with `.report`, `.view`, `.api`, `.members` (consumed member names), `.paths`, `.sources`, `.tools`, `.environment`, `.commands`, `.command_index`. `archive.receipt()` is available before context exit; the original digest is checked again at close.
- `DiagnosticPacket.source(expected_revision, *, required)` validates clean equal before/after source snapshots, strict checkout identities, initialized pinned submodules and retained source bodies; `required` is the required source-relative path iterable. `.source_body(name)` returns verified bytes; `.sources` maps source-relative path to descriptor.
- `.setup()` validates canonical producer paths, fixed resource budgets, exact clean environment. Must precede source/tools/commands.
- `.toolchain()` validates equal before/after tools/dependencies, tool identities, PATH/executing interpreter equality. Sets `.tools` (tool-name -> identity). `.version_commands()` validates four initial commands and Python 3.12.14 version logs.
- `.command(id, argv, cwd, timeout, *, environment=None)` consumes the next exact command, verifies fixed outcome/resources/cleanup/log identity, returns `(record, utf8_log_text)`.
- `.inventory(rows, label, *, expected=None, sorted_paths=False)` validates strict relative descriptors. `.retained(rows, *, expected=None)` verifies and consumes all rows, returns a path -> bytes mapping. `.identity(row, *, expected_path=None, resolved_equal=False)` validates a recorded absolute file identity without opening the path.
- `.configuration(rows, *, build, copied=checked.COPIED, original=None)` verifies retained generated configuration inventory under `artifacts/<build.name>/`, optional original relative descriptors, copied-source equality, config root/xlen/profile/tool mapping; returns build-relative path -> bytes.
- `.model_build(*, build, binary, stamp_rows, generated_rows, compiler_records, build_text)` validates retained stamp and generated TCU bytes, calls only `checked.parse_build_records`, validates recorded object identities and compares recomputed compiler summary. Returns `(words, recomputed_summary)`; summary retains object identities but never rehashes absent object payloads. Assumes checked variant; pass `is_checked=False` for ordinary.
- `.finish()` rejects trailing commands and all unconsumed members under the selected diagnostic prefix.
- Exported constants/helpers: `BUDGET`, `TIMEOUTS`, `HEADER_PROBE`, `HEADER_PROBE_CONTENT`, `require`, `_same`, `_fields`, `_integer`, `nonacceptance_result()`.

Checked standalone API: `replay_archive(path, sha256, *, expected_revision, prefix="checked-counters") -> dict`. Always false qualification/readiness/warm/acceptance, `native_execution="not_run"`.

All command argv/root arguments accept `PurePosixPath` or strings, never resolve recorded producer paths. Error types derive from ValueError.

Validation: original native-v2 ZIP replay passes (270 source files, 17 commands, 7 cells, 45 TUs / one link per variant). Eleven focused mutations rejected; replay passed with producer-path I/O, process creation, live validate_build and live file_identity patched to raise. Exact result is `/workspace/scratch/98908dfa3444/w05-checked-replay-final.json`.
