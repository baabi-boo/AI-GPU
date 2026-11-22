# Public native diagnostic runner interfaces

Runner owns `ci/project/p06_counter_public_execute.py` and its host orchestration tests. It imports trusted repository modules, never retained code.

## Public output records

`p06_counter_public_records.MODES` is the exact tuple:
`("normal", "immediate-overflow", "delayed-overflow", "cache-overflow", "coherent-terminal")`.

`verify_output(text: str, mode: str) -> dict` validates the unique `COUNTER_PUBLIC_RESULT ` JSON line, strict fields/types/native observations, and returns the parsed observation. Invalid or incomplete input raises ValueError. It does not certify process success; the runner separately requires process_started=true, outcome=pass, integer exit_code=0 and cleanup_complete=true. All warm/qualification claims stay false.

## Public build records

`p06_counter_public_build.STAMPS` is this build-relative tuple:

- `sim/simx/checked-public/runtime_config.stamp`
- `sim/simx/checked-public/backend_config.stamp`
- `sim/simx/checked-public/main_config.stamp`

`ARTIFACTS` is this build-relative tuple:

- `sim/simx/checked-public/libchecked-simx.so`
- `sim/simx/checked-public/libvortex-simx.so`
- `sim/simx/checked-public/libvortex.so`
- `sim/simx/checked-public/checked_public_test`

Live API:

```python
validate_build(text, model_stamp_words, stamps, *, source, build, compiler,
               source_files, model_records) -> dict
```

`stamps` is `{ "runtime": original_text, "backend": original_text, "main": original_text }`. The model stamp is separately validated by `p06_checked_execute.compile_flags(..., checked=True)`.

`model_records` is the preceding live `p06_checked_execute.validate_build` return. Its `object_identities` contains exactly45 original compiled object identities. The public library must reuse exactly44 of them, excluding `tests/checked_counters_test.o`.

The returned dict must contain `object_identities`, exactly19 newly compiled object identities (same fields as `p06_mpm_execute.file_identity`: path, resolved_path, sha256, size_bytes). It should also retain the exact44 `reused_model_object_identities`, exact source/object mappings, four library/executable links, wrappers, independent flag validation, and counts. Pure retained-data parsing should be a separate function, without consulting recorded producer paths. Invalid data raises ValueError.

The runner first configures a fresh checked tree and builds/checks the existing45-TU native boundary fixture. It then invokes `make --no-print-directory -j2 THREADS=1 PROFILE=p02-tfr CONFIGS=-DSIMX_CHECKED_COUNTERS=1 PERF=1 CXX=<identified compiler> -f ../../tests/unittest/checked_counters/public.mk checked-public` from `<build>/sim/simx`. The second transcript must contain19 new compiles/four links; it may not recompile the44 reused objects or introduce replacements. Fullsource/runtime/header bodies are retained.

The application executes from its sibling-library directory with `VORTEX_DRIVER=simx`; no `LD_LIBRARY_PATH`, preload, or inherited build options are admitted. Every model object, new object, generated configuration/source, compiler stamp, native control binary and four public artifacts is rehashed before each actual execution and at completion. The three dependency libraries, source snapshot and tools are also rechecked. Pinned CPython3.12.14 must be the actual executing interpreter and resolve to the same file as PATH python3.
