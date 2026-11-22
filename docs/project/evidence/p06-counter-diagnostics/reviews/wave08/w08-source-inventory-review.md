# W08 independent R3 source-inventory review

Reviewer: `/root/w08_source_inventory_review`, agent 43 of 60, wave 8 first.
Scope: the new `ci/project/p06_counter_source_inventory.py` and its independent
`ci/project/test_p06_counter_source_inventory.py`, including the inherited JSON
and filesystem boundaries in `baseline_packet_io.py`. The reviewer did not
author either new file and made no repository changes.

## Verdict

**PASS for the reviewed inert source-inventory validation scope. No F1, F2 or F3
finding. Confidence: high.** The implementation preserves the complete original
source catalogs and adds an explicit externally pinned descriptor contract
without introducing source-path I/O, fallback, execution or qualification.

This is independent advisory review under `AGENTS.md` and
`docs/review/code-review-policy.md`. The externally visible validation interface
is reviewed as R3. This report supplies reviewer evidence; it is not an invented
maintainer approval or a waiver. Full replay-reader integration is separately
assigned and is not approved solely by this helper verdict.

## Exact reviewed identities

Repository: `/workspace/scratch/98908dfa3444/AI-GPU`.
HEAD before and after review: `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`.
The helper and its test are uncommitted additions, so the identities below, not
HEAD alone, identify the reviewed implementation. Both hashes were checked at
the beginning and end of review and were unchanged.

| File | Bytes | Lines | SHA-256 |
|---|---:|---:|---|
| `ci/project/p06_counter_source_inventory.py` | 33,730 | 905 | `8961331993ceb112f80a83314ee7a6a3020163a89ca1b8781139c103e98f6862` |
| `ci/project/test_p06_counter_source_inventory.py` | 36,430 | 724 | `d9745d9d3a7c36af8a4bd85a3f83d9a8787f4672beabb77e0898267ca40d467f` |
| `ci/project/baseline_packet_io.py` | inherited dependency | — | `53ac39e541628a68b3d405201734195e8ed606b26eab5ee72746e96b3148515d` |

Both new files have final newlines and no trailing-whitespace lines. Other
agents' concurrent uncommitted work was preserved.

## Security and contract review

Evidence type for these conclusions is static proof corroborated by focused
tests. The complete executable helper, test module and inherited I/O/parser
implementation were inspected. The literal catalogs were verified as complete
data through independent immutable-tree reconstruction; an AST inventory also
confirmed the helper contains only the expected imports, constant data, error
class and validation/loading functions.

### Frozen mandatory catalogs and permitted additions

`required_source_names()` checks exact count, uniqueness, sort order and SHA-256
over every sorted name followed by LF. The catalogs are literal original names,
not dynamically discovered from the current checkout and not taken from an
untrusted report at runtime. The public catalog combines the checked names and
406 public additions, then verifies the complete 676-name digest.

The review independently read the immutable producer implementations using
`git show`, reconstructed their source selections against
`git ls-tree -r --name-only -z`, and compared the entire result to the public
`required_source_names()` API. No original producer Python was imported or
executed. The inherited checked selection expressions were also compared as AST
data between the two original revisions. Public `SOURCE_ROOTS` was read as a
literal AST value.

| Producer | Immutable source revision | Names | Recomputed full-name digest | Result |
|---|---|---:|---|---|
| Checked native v2 | `407ab9fea5e4f793a2a5088f566a87f3e631aa84` | 270 | `d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108` | Exact equality |
| Public native v1 | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c` | 676 | `f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da` | Exact equality |

`_sources()` requires the complete mandatory set to remain present even when
additions preserve the original row count. Additional names must be below an
exact reviewed root followed by `/`; prefix lookalikes do not qualify. Original
singletons outside the roots are allowed only by their exact mandatory names.
The checked roots are `ci/project`, `sim`, `sw/common`,
`tests/unittest/checked_counters` and `third_party/ramulator_ext`. Public adds
`sw/include`, `sw/runtime`, `sw/kernel/include` and
`tests/regression/ai_bench_common`. New workflow names, other repository roots,
and removal or renaming of original bodies are not admitted.

### Exact schema, scalar types and bounded parsing

The manifest and descriptor field sets are exact. Plain dict/list/string/int
types are checked at the relevant boundary; bool, float, subclass and coercion
substitutes for values are rejected. Schema version is exactly integer one.
The producer contract is one of the two supported exact strings; the source
revision must match an externally supplied lowercase 40-hex expectation.
Hashes are lowercase 64-hex strings. Descriptor sizes are integer values from
zero through 256 MiB, including both endpoints; uint64-sized or larger
substitutes fail this smaller explicit bound.

Paths are inert canonical ASCII POSIX relative names. Empty, absolute, drive,
backslash, traversal, `.git` component, control, non-ASCII, and malformed
separator forms fail. The 4096-byte, 64-component and 255-byte component bounds
are enforced. ASCII validation makes the length bound a byte bound as well as a
character bound. Strictly increasing names reject both duplicates and unsorted
input. Lists are nonempty and capped at 20,000 entries.

The decoder requires nonempty exact bytes of at most 8 MiB and checks the
mandatory external SHA-256 over those exact bytes before parsing. Whitespace is
therefore digest-bound. `load_json_bytes()` provides strict UTF-8, duplicate-key
rejection, finite numeric parsing and depth/token/number bounds; the manifest
schema then rejects numeric forms outside its exact integer types. The JSON
limits remain compatible with a serialized 20,000-descriptor manifest.

### External trust, full equality and no fallback

The decoder and file loader require explicit external digest, revision and
producer-contract arguments. The digest is never obtained from the manifest or
archived report. A correctly formatted but wrong digest rejects before parsing;
invalid externally supplied expectations reject before loader I/O.

`validate_archive_sources()` revalidates both complete lists and compares every
path, SHA-256 and size in their strict order. It does not reduce the comparison
to row count, selected compiled files or a name-only hash. Validated output is a
detached copy, so returned descriptor mutation does not change the inputs.

The pure dictionary validator intentionally does not claim to authenticate a
dictionary's origin. Its documentation requires external callers to obtain
expectations through the digest-pinned decoder/loader or an explicitly trusted
caller. Retained archive members still require the reader's separate byte hash
and length checks. Updating an original body's hash in a newly caller-pinned
manifest is the stated extension contract, not evidence of Git provenance.

The helper contains no fallback path. A small integration spot-check confirmed
the replay callers pass the original fixed name digests when no external
manifest is supplied, enforce all-or-none manifest path/hash arguments, and
propagate explicit-load failures. The external route invokes complete descriptor
comparison. This spot-check does not replace the separately assigned full
integration review or its replay tests.

### Filesystem and execution boundary

Only `load_source_inventory()` reads runtime input. It passes the explicitly
selected manifest parent/name to the trusted `PacketReader` with a one-file,
8 MiB budget. No descriptor path or recorded producer path reaches filesystem
access. There is no source discovery, resolution, import, shell, Git invocation,
build or retained-code execution in the helper's runtime API.

The inherited fd implementation checks every directory component without
following symlinks, rejects nonregular files, opens nonblocking, bounds reads,
and compares file and directory identities before and after. Tests cover leaf
and ancestor symlinks, missing/nonregular files, FIFO and opening races, same-size
content drift with restored mtime, inode replacement, growth/truncation and
parent replacement. The stated limitation against malicious concurrent writers
is retained; no stronger filesystem-authentication claim is made.

## Tests run

The independently authored test module was loaded by exact module name, without
full test discovery, using `PYTHONDONTWRITEBYTECODE=1` and `python3 -B`. Its FIFO
child inherits the no-bytecode environment. A standard `TextTestResult`
subclass counted `addSubTest()` calls while delegating unchanged to unittest.

**Result: 48 test methods, 278 subtests, 0 failures, 0 errors, 0 skips, 1.752
seconds.** Subtests are not misrepresented as additional test methods.

The fixture first verifies both independently pinned original ZIP hashes,
then checks their original revisions, complete source-name digests, before/after
inventory equality and all 946 retained source-byte descriptors. The public
original's failed execution remains failed; these tests use it only as an
original source-inventory anchor. This review independently rechecked tree-name
selection; it did not repeat the separate native auditor's Git-blob comparison
or native provenance audit.

Eight additional focused probe scenarios passed:

1. A complete 20,000-row public manifest passes actual digest-bound JSON decode.
2. A canonical additional path at exactly 4096 ASCII bytes passes decode.
3. A canonical additional path at exactly 64 components passes decode.
4. Excessive JSON nesting rejects as `SourceInventoryError` through the decoder.
5. A 1025-character JSON integer rejects through the decoder.
6. Excessive JSON token structure rejects through the decoder.
7. An invalid external revision rejects before patched filesystem functions can
   be called.
8. An unsupported external producer contract rejects before patched filesystem
   functions can be called.

## Scope and remaining obligations

No native build or execution, full project discovery, archive extraction,
retained-code import, repository edit, commit or push was performed. Only this
scratch review note was written. No additional optional test run is required to
resolve a remaining helper risk found in this review.

The helper and tests make no implicit Git/GitHub authentication, binary/object
payload proof, native execution, warm readiness, counter-lifetime theorem,
performance acceptance or phase-qualification claim. The corrected public
native artifact and replay-reader integration have their own independent audits
and must retain those scopes and evidence identities. Existing failed originals
and all qualification exclusions remain part of the overall release record.
