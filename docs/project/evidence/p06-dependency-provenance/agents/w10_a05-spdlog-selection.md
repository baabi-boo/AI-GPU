# W10-A05 supplemental review: spdlog archive selection

## Finding and scope

**F2; high confidence; actual retained execution and static proof.** Before
attempt 05 was prepared, the parent identified a second map-admission issue.
This independent review reproduced it using attempt 04's untouched map and
archives. The actual link child had exited zero, but the original record failed
earlier while retaining its map. This review does not repair that failed record,
complete its missing fields or establish a successful dependency original.

The [supplemental receipt](../host-diagnostic/review-04-spdlog-selection.json)
records the inspected helper hashes, pinned source identities, generated inputs,
actual record counts and protected originals. Its SHA-256 is
`d2ebdd8da2fb1c30ff17ad843a5f892718f682a64717617d1843233cab6063e5`;
the targeted inspection completed in 9.983482 seconds. The binary parser was
the separately reviewed working-tree map-size correction, identified by its
hash in that receipt. It was not the original published parser and its result
is explicitly supplemental.

## Actual selected inputs and source explanation

The unchanged 18,084,083-byte map has SHA-256
`9d6fa3c32d3e5f821d830ebd23373d4f8e626d89f801e8ba00af3fe643d16ec4`.
It contains one `LOAD` for each actual yaml-cpp and spdlog archive. All 25
selected archive members and all 25 archive-member section contributions
belong to yaml-cpp. No spdlog archive member was extracted. The archive itself
was still built and supplied to the actual linker.

The pinned Ramulator top-level CMake file links `ramulator` to both yaml-cpp and
spdlog, and its source subdirectories create separate object libraries. For
example, the base object library is linked into `ramulator`; that base library
does not itself link to the spdlog target. The generated base compilation flags
therefore have an empty `CXX_DEFINES`, while the spdlog archive's own flags include
`-DSPDLOG_COMPILED_LIB`.

The actual records independently show this distinction: all **60 Ramulator
compiles omit `SPDLOG_COMPILED_LIB`**, while all **seven spdlog compiles define
it**. Of those 60 Ramulator records, **59 include the pinned
`spdlog/include/spdlog/common.h`**. That header chooses `SPDLOG_HEADER_ONLY` and
inline definitions when `SPDLOG_COMPILED_LIB` is absent. This source and actual
compile evidence explains the observed zero extraction; an archive appearing
in a link command does not imply that its members contribute to the output.
The receipt binds the relevant CMake, header, generated flags and link-file
identities. The upstream pins and recipes were not changed.

## Reproduction and narrow correction

The existing Ramulator callsites require both archives in `required_archives`.
The generic validator interprets that parameter as requiring an extracted
member and a unique `LOAD` from each archive. With the size correction alone,
the actual map therefore rejects with:

```text
link map lacks required archive-member evidence
```

Using the existing validator parameters with **yaml-cpp as the required member
selection** and **both yaml-cpp and spdlog as required unique loads** admits the
actual selected-member evidence. The targeted receipt project-load validator
also passes all **62 original direct inputs** with that narrow policy. That
check used a clearly separate in-memory map descriptor; the original record's
`link_map: null`, empty `inputs_after`, failed outcome and retained bytes stayed
unchanged.

Two actual-map mutations remain rejected: deleting spdlog's `LOAD`, or repeating
it, each fails with `link map lacks a unique required LOAD record`. The generic
validator's default still rejects this map when all admitted archives are
implicitly required to select a member. No generic default or archive-member
validator was weakened by this inspection.

The justified implementation change belongs only to the fixed Ramulator
producer/reader/diagnostic callsites. Preserve mandatory construction of all
seven spdlog objects, its exact archive membership and creator/index joins,
its actual linker-input bytes and chronology, and its unique `LOAD`. Any
spdlog member that does appear must still belong to that fully verified
archive. Do not require a made-up contribution and do not force one with
`--whole-archive`, source changes or compiler-definition changes.

## Preserved boundary

No production file, driver, prepared attempt or original execution evidence was
modified by this review. The separate failed attempt 04 remains failed. Fresh
attempt 05 must use a published reviewed revision and an explicitly reviewed
diagnostic callsite change in addition to its revision literal. The original
revision-only driver assumption is therefore superseded before any preparation.
Native execution remains `not_run`; all seven qualification, warm and acceptance
fields remain false.
