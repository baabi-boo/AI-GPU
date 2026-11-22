# Wave 3 public diagnostic build-record validator

Implemented only:

- `ci/project/p06_counter_public_build.py`
- `ci/project/test_p06_counter_public_build.py`

Final SHA-256 identities are retained in `w03-public-build-record-identities.json`.
The implementation hash is `22982ed2264626fb1be2b86785fddb89655c9e0f82a2257ce0e9ab7c89eab758`;
the test hash is `37e6e354faa0e73f58474f9d8fa7e9ab105bb38854779f468c85f888486e0029`.

## Contract

The agreed `validate_build(text, model_stamp_words, stamps, *, source, build,
compiler, source_files, model_records)` API and `STAMPS`/`ARTIFACTS` tuples are
implemented. `parse_build_records` takes the same arguments and is pure: producer
paths are `PurePosixPath` labels. It does not read source, generated, object or
binary files, resolve paths, import retained code or execute recorded commands.

The prior checked-model report must identify the exact 45 sources/objects and
their three production inclusions plus generated TCU body/footer binding. The
public model library must use exactly 44 of those objects, excluding the boundary
test main. The second transcript must compile exactly 19 source/object/role
tuples and link exactly four outputs. `utils.cpp` legitimately appears in two
roles with different flags/objects; `cmd_processor.cpp` also remains separately
bound in model and backend roles.

Each role's complete ordered macro tokens are pinned, including legal duplicate
definitions from the generated p02-tfr configuration: model 36, runtime/main 304,
backend 306. The pins hash newline-joined original macro tokens plus a final LF.
The validator additionally applies semantic configuration checks, fixed include
order, fixed ordinary compiler options, exact per-object flag/stamp equality and
exact dependency targets. Unknown hardware defines, altered derivations, new
guards, access overrides and reordered macro tokens fail closed.

All library/object inventories and library search paths are fixed. The five
verified Processor wraps occur exactly at the backend DSO link. The model keeps
the exact external softfloat/Ramulator dependencies; runtime, backend and app
retain their fixed sibling-library links. The literal single-quoted `$ORIGIN`
token is admitted; shell expansion and other operator/escape forms are rejected.
Actual multiline compiler recipes are parsed after literal backslash-newline
continuation handling.

The pure return includes 19 `object_paths`, 44
`reused_model_object_identities`, source/object/role records, four full link
argument inventories, compiler-stamp digests and wrapped symbols. The live
wrapper rehashes all 44 reused objects against their original identities, rejects
aliases for new objects, and replaces `object_paths` with 19 live
`object_identities`. Its transitive repository helpers are already covered by
`p06_checked_execute.HELPERS`.

## Validation actually completed

Command:

```sh
python3 -m unittest discover -s ci/project -p 'test_p06_counter_public_build.py' -v
```

Final result: **35 tests passed in 7.252 seconds**. The tests create a fresh
configured p02-tfr tree, obtain actual first/second Make dry-run compiler/link
records and real generated compiler stamps, then remove the producer tree before
parsing. They cover the exact inventories, role duplication, continuations,
filesystem-free parsing, all five wraps, source/header omissions, foreign or
missing objects/libraries, guard/options/macro drift, malformed records,
identity types, path aliases, record-size bounds and live object drift.

The live hashing unit test uses explicitly synthetic small host files; it is not
a native object or execution result. Make `-o` in the second dry run marks the
44 model prerequisites as already built without creating placeholder objects.

The initial fixture configure attempt failed because this host is outside the
supported OS detector. The test now explicitly selects the existing host-probe
recipe's `--osversion=ubuntu/focal`, using no toolchain binaries. The failure and
all subsequent successful runs remain in `w03-public-build-record-tests.log`.
The independent existing scratch transcripts also passed the pure parser after
their original producer build directories had been removed.

Both new files passed `git diff --no-index --check /dev/null <file>` with no
whitespace output; exit 1 denotes new-file content, not a whitespace finding.
No full native build/link/run, phase qualification, commit or push was performed.
The existing 15 GiB native reserve remains unchanged.
