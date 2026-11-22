# Source inventory independent tests

Owner: `agent39of60`, `wave7third`, `/root/w07_source_inventory_tests`.

## Scope and result

Created only `ci/project/test_p06_counter_source_inventory.py` in the repository.
No producer, reader or helper changes; no native build, compiler invocation,
toolchain execution, commit or push. The filesystem tests use temporary inert
files. A stock Python child process bounds the FIFO/race test with a five-second
timeout; no retained archive code is imported or executed.

Focused execution passed **48 test methods and 278 subtests**, with **0 failures,
0 errors and 0 skips**, in **1.742 seconds**. Subtests are counted separately and
are not presented as additional test methods. No implementation failure was
observed; the helper author and primary owner received the result.

The checkout HEAD was `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`. Both the new helper
and test file were uncommitted additions; this is a test of the exact source hashes
below, not a claim that those files were present in that commit.

## Exact inputs and output

| File | Bytes | SHA-256 |
|---|---:|---|
| `ci/project/p06_counter_source_inventory.py` | 33,730 | `8961331993ceb112f80a83314ee7a6a3020163a89ca1b8781139c103e98f6862` |
| `ci/project/test_p06_counter_source_inventory.py` | 36,430 | `d9745d9d3a7c36af8a4bd85a3f83d9a8787f4672beabb77e0898267ca40d467f` |
| `/workspace/scratch/98908dfa3444/w07-source-inventory-tests.log` | 9,511 | `b351398bf7dcdc64eda578191f95b8e3210649c68ca93d3701750b49ded91395` |

The log records source hashes before the run; a separate read confirmed the same
hashes after it. The test suite uses only the approved public helper APIs and
`CONTRACT_ID`; filesystem boundary hooks use standard-library `os`, `io`, built-in
file access and `Path.resolve`. No private helper constants or validators are
patched, so the test expectations do not mirror the implementation's internals.

## Original source anchors

The suite first hashes each original ZIP against an independently embedded digest,
then reads its report and original retained source bodies as inert data. It
checks all **946 source descriptors** against the retained bytes, checks matching
before/after source lists, and checks the report's original revision. Absence or
substitution of either original fails setup rather than skipping tests.

| Producer source | Original ZIP SHA-256 | Mandatory names | Name-list SHA-256 |
|---|---|---:|---|
| `407ab9fea5e4f793a2a5088f566a87f3e631aa84` / `run-45026112992-attempt1.zip` | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` | 270 | `d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108` |
| `81ed6871634fefbf5c78fb27cf10dce913bd4d9c` / `run-45029135146-attempt1.zip` | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` | 676 | `f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da` |

The public source descriptors come from its retained failed original. Their
validity as source descriptors does not change that execution outcome.

## Coverage

- Complete original source-name equality, independent fixed name-list digests,
  source-body descriptors, original schema validation, digest-bound decoding and
  exact archive descriptor comparison for both producers.
- Clearly labeled synthetic later revision/helper addition and synthetic changes
  to an original helper body. Caller-pinned changed expectations are accepted,
  while original archive descriptors fail equality until they also match.
- Mandatory uncompiled `sim/avedsim/vrt_c.h` and original
  `ci/project/baseline_packet_io.py` omissions, including additions that preserve
  the row count. The independent original list and fixed digest also detect drift
  of the helper's mandatory-name data without patching its internals.
- Permitted extensions in each reviewed producer root; root-prefix lookalikes,
  unknown roots and inappropriate cross-producer extensions fail.
- Exact manifest and descriptor fields; plain container/string/integer types;
  schema-version booleans; size booleans, negative values, floats and values above
  256 MiB; accepted 0-byte and 256 MiB descriptor endpoints; accepted 20,000-row
  and rejected 20,001-row lists.
- Duplicate and unsorted names; unsafe separators/components, absolute and drive
  paths, embedded controls, non-ASCII names, excess path depth and length.
- Explicit external SHA-256 and revision/contract binding; wrong hash rejection
  before malformed encoding/JSON parsing; no inferred digest or legacy fallback;
  duplicate JSON keys including escaped aliases; invalid UTF-8/BOM/UTF-16,
  malformed/top-level nonobject JSON and nonfinite/float numeric tokens.
- Exact byte-hash binding includes whitespace; 8 MiB decode and file endpoints
  pass; one byte over fails. An oversized file fails before reading its contents.
- Pure APIs reject filesystem access; the file loader reads the explicit
  manifest without source-path discovery or resolution.
- Missing/nonregular files, leaf and ancestor symlinks, preexisting FIFO and a
  regular-file-to-FIFO opening race; same-size content drift with restored mtime,
  identical-content inode replacement, growth/truncation and parent directory
  replacement during reading all fail.

## Focused invocation

The run used source-root unittest discovery restricted to the single new file:

```python
suite = unittest.defaultTestLoader.discover(
    "ci/project", pattern="test_p06_counter_source_inventory.py"
)
result = unittest.TextTestRunner(
    stream=sys.stdout, verbosity=2, resultclass=CountedResult
).run(suite)
```

`CountedResult` subclasses `unittest.TextTestResult`, counts `addSubTest` calls,
then delegates each call unchanged to the standard result. Output was redirected
to the log above. Equivalent ordinary invocation:

```sh
python3 -m unittest discover -s ci/project -p 'test_p06_counter_source_inventory.py' -v
```

This evidence covers host-only source-manifest validation and bounded filesystem
handling. It does not independently prove GitHub/Git provenance, missing binary
payload identities, native execution, warm readiness, a no-wrap lifetime theorem
or any qualification/acceptance gate.
