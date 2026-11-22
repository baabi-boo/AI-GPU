# W07 source inventory interface

## Scope and ownership

Agent `/root/w07_source_inventory` owns only the new `ci/project/p06_counter_source_inventory.py` and these scratch notes. The existing replay readers, their tests, producer code, evidence reports, workflow files, qualification claims, phase gates, and native execution routes are not modified by this assignment. Root owns later CLI integration and independent reviewers own tests/review.

The inspected policies are `AGENTS.md`, `docs/review/code-review-policy.md`, and the current project/status/roadmap/acceptance context. This helper changes an external validation contract and requires independent review. It cannot grant itself a waiver or mark a qualification gate accepted.

## Problem and intended behavior

The inert counter readers correctly pin complete original source-name inventories: 270 for `simx-checked-counters-native-v2` and 676 for `simx-counter-public-native-v1`. That rejects omitted uncompiled headers and helper bodies. It also rejects a legitimate later producer revision whose complete source inventory includes new helper files.

The new shared helper adds an opt-in external complete-inventory manifest. All original names remain mandatory. Within reviewed roots, a manifest can supply updated file hashes/lengths and new names for a later revision. The caller must supply the manifest's SHA-256 independently and specify the expected producer revision and producer contract. The original no-manifest reader path keeps its existing frozen inventory pin. An explicitly supplied malformed or missing manifest must fail; it never falls back.

## Exact schema

Top-level fields are exactly:

| Field | Required value/type |
|---|---|
| `schema_version` | Exact Python/JSON integer `1`, excluding Boolean and float |
| `contract_id` | String `simx-counter-source-inventory-v1` |
| `producer_contract_id` | Exact caller-selected `simx-checked-counters-native-v2` or `simx-counter-public-native-v1` |
| `source_revision` | Exact caller-supplied 40-character lowercase hexadecimal revision |
| `sources` | Complete nonempty sorted list of exact source descriptors |

Each descriptor has exactly `path`, `sha256`, and `size_bytes`. Paths are canonical ASCII POSIX relative names using letters, digits, underscore, dot, plus, minus, and slash. Empty, absolute, backslash, colon/drive, traversal, control/non-ASCII, duplicate, unsorted, and `.git` component names fail. Each component is at most 255 characters, path depth at most 64, total path length at most 4096. SHA-256 is an exact 64-character lowercase hexadecimal string. `size_bytes` is an exact integer from zero through 256 MiB; empty helpers remain compatible with the existing ArchiveReader descriptor contract. Unknown fields and subclass/coercion-style substitutes for the specified container/scalar types fail.

There are at most 20,000 descriptors. External JSON bytes must be nonempty and at most 8 MiB. JSON parsing uses the already trusted `baseline_packet_io.load_json_bytes`, retaining its depth/token/number bounds, duplicate-key rejection, strict UTF-8 decoding, and rejection of nonfinite numbers. All manifest fields additionally enforce their exact types. Whitespace is included in the external hash; the parser does not rewrite or canonicalize before hashing.

## Allowed additions

For the checked producer, additional names may lie below `ci/project/`, `sim/`, `sw/common/`, `tests/unittest/checked_counters/`, and `third_party/ramulator_ext/`. The helper and diagnostic fixture directories permit future explicit producer helper dependencies without expanding to arbitrary repository roots.

For the public producer, additional names may lie below the original producer's reviewed source roots: `ci/project/`, `sim/`, `sw/common/`, `sw/include/`, `sw/runtime/`, `sw/kernel/include/`, `tests/unittest/checked_counters/`, `tests/regression/ai_bench_common/`, and `third_party/ramulator_ext/`.

Original singleton paths outside these prefixes remain mandatory and allowed. Additional workflow files, new top-level directories, or original-name removal/renaming require a separately reviewed contract change. A manifest cannot authorize them merely by naming them.

## Public API

- `required_source_names(producer_contract_id)` returns an immutable tuple of every original required source name after checking exact count, uniqueness, sort order, and its independently derived SHA-256. The checked 270 names are frozen literally, with 406 public additions. No current-checkout discovery occurs.
- `validate_source_inventory(manifest, *, expected_revision, producer_contract_id)` is pure. It validates exact schema and expectations and returns a detached copy. A raw dict alone has no provenance; external reader callers must first use the digest-pinned decoder/loader.
- `decode_source_inventory(contents, *, expected_sha256, expected_revision, producer_contract_id)` is pure. It requires an externally supplied digest, hashes the exact bytes before accepting/parsing their content, parses strict bounded JSON, and calls the schema validator.
- `load_source_inventory(path, *, expected_sha256, expected_revision, producer_contract_id)` reads only the explicitly supplied manifest file. It validates externally supplied expectations first, then uses `baseline_packet_io.PacketReader` with a one-file/8 MiB budget. The existing trusted fd implementation rejects symlinks in every path component and nonregular files, performs bounded reads, and checks descriptor/named-file/directory identities before and after. It does not resolve a path with `Path.resolve` and never receives source descriptor paths for filesystem access.
- `validate_archive_sources(sources, inventory, *, expected_revision, producer_contract_id)` is pure. It revalidates both complete lists and requires exact ordered equality of every path, hash, and size, returning copied observed descriptors. Callers still must hash the archive's actual retained member bytes against those descriptors.

All rejected content or external-file loading failures raise `SourceInventoryError`, a `ValueError` subclass. No external digest can be omitted from decoder/loader calls, and neither has fallback behavior.

## Independent baseline derivation

No archived Python was imported or executed. Read-only Git commands inspected the immutable producer code and trees. The original retained ZIP identities were checked before reading reports. The producer's static CRITICAL selection and SOURCE_ROOTS were applied independently to `git ls-tree -r --name-only -z` at the immutable revision, then compared exactly to the report's complete source-name list. Every descriptor was also independently checked against `git show REVISION:PATH` bytes: both SHA-256 and exact size. All 946 descriptor comparisons passed (270 checked and 676 public), and both tree-name comparisons were exact.

| Producer | Original source revision | Required names | Names SHA-256 |
|---|---|---:|---|
| Checked native v2 | `407ab9fea5e4f793a2a5088f566a87f3e631aa84` | 270 | `d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108` |
| Public native v1 | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c` | 676 | `f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da` |

The names digest is SHA-256 of each sorted relative path followed by LF, concatenated and encoded as ASCII. It validates the actual full required-name catalog in code; it is not a count-only test.

Original report data came from:

| Archive/report | Exact SHA-256 |
|---|---|
| `run-45026112992-attempt1.zip` | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` |
| Its `checked-counters/report.json` | `3e7fb048cf8c1a9e6b274104fb5d6c2581fa50cb9dfabe68b6bab955ffd967f0` |
| `run-45029135146-attempt1.zip` | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` |
| Its `public-counters/report.json` | `c0b889295eba1dec1ab102fb480399fb596c1362bfd6550992d8279c7a593e8b` |

The public original report records failed native execution. Its retained source inventory is used solely as the original producer inventory; no failed outcome is changed or treated as passing.

The scratch derivation record includes all original descriptors and exact comparison outcomes: `/workspace/scratch/98908dfa3444/w07-source-inventory-derivation.json`.

## Integration obligations for root

The two optional CLI arguments must be all-or-none. Any explicit external manifest input must be loaded, validated, and used for exact archive-descriptor comparison; errors propagate. The existing no-manifest route preserves its original inventory digest. The new helper belongs in trusted reader-source identity output, while `baseline_packet_io` already belongs to that closure. Existing source-retention, report-before/after, compile-record, source-revision, and no-qualification checks remain in force.

This helper does not insist that a later reader helper existed in an older producer: only the literal original names are mandatory. Its own name and the two new replay reader names are absent from those original frozen inventories.

## Trust and limits

The caller's independently supplied manifest SHA-256 defines the trusted expected descriptors. The helper does not independently authenticate GitHub provenance, establish a source-tree proof merely from a revision label, attest to absent binary/object contents, or prove any build/execution occurred. A caller-pinned internally consistent forged manifest/packet remains a forged manifest/packet. Original-body names are mandatory, but their bytes may change when the caller explicitly pins a new revision's manifest; that is the intended extension interface.

Only the explicit external manifest is a runtime filesystem input to this helper. Trusted local helper imports are part of the reader implementation. Source descriptors and recorded producer paths stay inert. No shell, Git process, build, import of retained code, or source-body opening occurs in its runtime API. Before/after file identity checks do not claim to defeat a malicious concurrent filesystem writer.

Success is diagnostic consistency only, always nonqualification. It establishes no warm readiness, warm run, phase/performance acceptance, full counter-lifetime proof, native execution authenticity, hardware result, or permission to lower any gate.

## Verification in this assignment

Passed: original ZIP SHA-256 verification, both independently reconstructed Git tree listings, all 946 Git blob SHA-256/size comparisons, and direct decoder + no-follow loader + exact archive-descriptor smoke checks for both original complete inventories. These are host data checks only. No native build or execution was run, and no archived code was executed. Independent mutation/bounds/filesystem tests are owned by `/root/w07_source_inventory_tests`; its result will be recorded separately.

`git diff --check -- ci/project/p06_counter_source_inventory.py` returned zero, but the new file is untracked, so that command alone does not inspect its content. A separate direct trailing-whitespace/newline inspection is recorded with final verification. No commit or push was performed.

## Implementation identity

`ci/project/p06_counter_source_inventory.py`: SHA-256 `8961331993ceb112f80a83314ee7a6a3020163a89ca1b8781139c103e98f6862`, 33730 bytes, 905 lines.

Scratch derivation JSON: SHA-256 `023edb060a1093a9235ba5a29b6649d1d7ef1e7a7fa66b7ee569886eccdd4942`.
