# Local continuation validation — source and evidence scopes

The completed checks below establish tooling, reader, producer and regression
behavior at their recorded source profiles. They are separate from actual
native execution and from full-original inert replay. Overlapping runs must
not be added into an invented unique-test total or a complete-suite claim at a
later commit.

## Completed regression observations

| Observation | Result | Exact source scope | Retained record |
| --- | --- | --- | --- |
| Full governance discovery | **4,256 unique tests passed**, no failures/errors/skips; exit 0; 2,954.292 unittest seconds | Clean initial checkpoint `ac2f2ae761c3644103278f7a41cc6ae7db734a86`, tree `5e7caa2b008fe8b1924811aeda5a079845a37343` | [Original log, gzip](validation/full-governance-ac2f2ae7.log.gz), [process receipt](validation/full-governance-ac2f2ae7.process.json) |
| Ten affected modules after ordering/host-path/lock corrections | **136 unique tests passed**, no failures/errors/skips; exit 0; 306.635 unittest seconds | Clean corrected checkpoint `7251f078972c1d524de06d069e91b014b55896f5`, tree `c44b5a93ab3aabaf2438e9e7d102339c9dc80542` | [Original log](validation/w07_a02-affected-reader-regression.log), [receipt](validation/w07_a02-affected-reader-regression.json) |
| Explicit managed-report JSON intake | **118 unique tests passed**, exit 0; 21.025 unittest seconds | Six recorded corrected files over base `7251f078`; their before/after hashes are identical and match the correction committed as `0f9aaa36d46364c297254164f5dab0d4f0e88349` | [Original log](validation/w08_a02-json-regression.log), [receipt and six-file identities](validation/w08_a02-json-regression.json) |
| Hosted cache relocation and workflow contract | **40 unique tests passed**, exit 0; 4.517 unittest seconds | Three recorded corrected files over base `0f9aaa36`, including the hosted producer and its two test modules; hashes stable before/after and projected into `8d735eba0016cdc64592d9c40a98e6b52574e64b` | [Original log](validation/w09_a01-hosted-prepare-tests.log), [receipt](validation/w09_a01-hosted-prepare-tests.json) |
| Corrected replay guards at the actual GitHub pathname | **Seven tests passed**, exit 0; 45.301 unittest seconds | Three corrected test files over base `0f9aaa36`, in `/home/runner/work/AI-GPU/AI-GPU` with `TMPDIR` also beneath `/home/runner`; their profile is projected into `8d735eba` | [Original log](validation/w08_a05-hosted-layout-final.log), [source and provider review](validation/w08_a05-hosted-review.json) |
| Complete control runtime-diagnostic accounting | **22 distinct tests passed**, no failures/errors/skips: eight new tests in 18.323 seconds and fourteen existing tests in 39.898 seconds | Three corrected reader/test files over base `8d735eba`, with exact reviewed bytes committed in `ba2d649d4150e046c2ba610de02725d9d062b1be` | [New test log](validation/w10_a02-runtime-diagnostic-tests.log), [existing test log](validation/w10_a02-existing-control-tests.log), [correction profile](validation/w10_a02-runtime-diagnostic-review.json) |

The full governance command was
`python3 -B -m unittest discover -s ci/project -p 'test_*.py' -v`.
Its uncompressed original log has 755,075 bytes and SHA-256
`ba12713784d72d28a69c61fb5baf1017107b6c746fb12b973b092e3dfccd9f63`.
The affected 136-test log has 26,033 bytes and SHA-256
`4bb719843591f26c3463dc4b2631a87d610f77ee072b16db747139b9890d59f7`.
The compressed storage identities and original uncompressed identities are
both recorded in the [evidence index](evidence-index.json).

The [independent test-evidence audit](agents/w07_a05.md) enumerated every test
identifier and checked both logs and receipts. The observed complete-suite
count is **4,256**; the earlier 4,233 estimate was incorrect. All 115 tests
added in the initial implementation occur in the full log. All 12 later
ordering/host-path/lock regressions occur in the affected log.

The corrected 136-test run repeats 124 IDs from the full run and adds 12 new
IDs. The other 4,132 initial IDs were not rerun in that command. The later
118-test, hosted-boundary and 22-test reader observations have their own source profiles and
overlap earlier modules; none is a complete-suite rerun at the final published
tree.

## Source-integrity limits

The full-run receipt records its initial revision/tree and clean Git status
before and after. The frozen checkout still matches that revision/tree. It
does not contain an explicit after-run revision/tree or a before/after file
byte manifest, and its `python3` command token has no recorded executable hash.
Those observations are not retroactively added to the original receipt.

The 136-test corrected run records identical before/after revision, tree,
clean status, eight recursive submodules and all **413 tracked Python/JSON
files** under `ci/project`. Independent review rehashed all 413 current files
and the selected Python/CMake binaries against that record.

The parser, hosted-boundary and final diagnostic-reader runs were executed against reviewed edits over
their recorded base commits. Their exact changed-file profiles stayed stable
during testing. Mapping those profiles into a later commit is a source
projection, not a new execution at that commit. The actual native attempt 04
is separately pinned to clean `0f9aaa36`; a later hosted-only preparation or
test or reader correction does not become part of that historical native execution.

## Independent boundary reviews

The [parser review](agents/w08_a04.md) independently inspected every corrected
hunk, passed 52 existing/new parser tests and 17 separate real-original
admission controls, and confirmed exact pending/substitution helper inventories.
The actual 3,679,258-byte native-03 report has 265,793 structural tokens and
depth ten. Generic/historical intake still rejects it; the explicit pinned
dependency-managed route accepts its declared completed scope. Wrong receipt,
revision, contract, population and elevated acceptance flags remain rejected.

The [hosted preparation review](agents/w09_a01.md) exercises real temporary Git
repositories with initialized fixture submodules. It reproduces dirty source
from a small restored cache and the 65,536-byte Git-status bound from a larger
one. The corrected producer relocates the validated cache first and then
performs the unchanged strict source inventory. Dirty files outside the cache,
wrong revision, tracked tools, symlink roots, existing destinations, invalid
cache identity, insufficient resources and changed gitlinks remain blocked.
Remote acquisition in those fixtures is mocked; no native GPU run is claimed.

The [hosted path review](agents/w08_a05.md) reproduced three synthetic bridge
failures in the actual `/home/runner/work/AI-GPU/AI-GPU` layout at uncorrected
`0f9aaa36` before applying the three test-file corrections. The corrected seven
tests pass there, including an input ZIP in the hosted temporary directory.
The allowlist comes from current trusted reader files and the caller-selected
ZIP, never from packet-controlled paths. Write, subprocess, extraction and
live-reader denial remain. Historical producer source paths can coincide with
trusted reader paths, so this test guard alone does not prove their origin;
the pinned source and complete semantic checks remain necessary.

These independent runs overlap author regressions and are reported as review
evidence, not added test coverage. Additional scoped compiler, toolchain,
failure-preservation, source and native-subpacket reviews are retained in the
[evidence index](evidence-index.json), each with its own original report.

The [runtime diagnostic correction review](agents/w10_a03.md) inspected every
reader/fixture/test hunk and independently passed the same eight new rejection
tests in 18.030 seconds. The original controls require exactly
`ramulator.stats.log` and `work/ramulator.stats.log`, 2,103 and 2,248 bytes,
under the unchanged 16 MiB log bound. The reader checks their source-declared
origin, fixed paths, nonempty bytes and exact final inventory placement. It
keeps `.nan` and all other contents opaque: interpretation and numerical,
performance and qualification evidence flags are all false. Missing, empty,
oversized, unknown, incorrectly frozen and rebound mismatching diagnostics
remain rejected. The reviewer also ran both complete real control semantics
on the unchanged actual original; these are distinct from synthetic tests.

## Historical hosted failures retained as failures

At the later [provider observation](validation/provider-observation-current.json),
fresh dependency run
[45162083701](https://github.com/baabi-boo/AI-GPU/actions/runs/45162083701),
attempt 1 at `19333193192ba5a2d3667c0111235ec9e21a5898`, had failed in
preparation. Its dependency build, native lifetime and control stages were
skipped. The original artifact is retained at
[artifact ZIP](originals/p06-hosted-failed-19333193-run45162083701.zip),
9,225 bytes, SHA-256
`6c130c17cc944f633f04835dbad6fd512880e6d987f477b01c48d32d4dd68472`.

The failure record locates the source-status stage but omits complete status
stdout/stderr. The cache-size explanation is a high-confidence inference from
the observed stage, identical producer ordering and the actual Git reproduction;
it is not a retained original subprocess exception. No source-status limit or
source cleanliness check was weakened.

Governance run
[45165109737](https://github.com/baabi-boo/AI-GPU/actions/runs/45165109737),
attempt 1 at `849469e1111870fbcfe0346afd33b284a5a1edd8`, ran **4,141 tests and
failed two** synthetic bridge path guards. The original failure remains failed;
the later local 4,256-test pass and the actual hosted-path correction are
different observations. Neither local result establishes a successful hosted
retry.

## Complete actual execution and independent inert replay

[Attempt 03](attempt-03.md) contains independently reviewed successful dependency
and native lifetime subpackets, while its local envelope failed and both
controls remained unrun. The [FP16 review](agents/w08_a01.md) and
[BF16 review](agents/w08_a03.md) each reconstruct the actual build, binary,
loaded-library, numerical and lifetime observations for their own variants.

The later [attempt-04 execution](validation/local-attempt-04-execution-summary.json)
passed all five stages in **894.591061 seconds** at clean `0f9aaa36`, with
all original reports sealed. The native matrix completed four processes,
132 launches and 4,224 exact words. The two pending-control processes and one
33-launch / 1,056-word substitution process remain separate populations.

The [actual native review](agents/w10_a01.md) independently reconstructed the
43-model-translation-unit / four-backend-translation-unit / two-shared-link
graph and 30-command application graph for each format. It compared all four
raw transcripts with an integer-only fixture calculation, verified source,
tools, configuration, build/process bindings and loaded products, and checked
run/reset/destruction state. Every original byte remained unchanged. The
[actual control review](agents/w10_a03.md) separately verified the two scalar
contexts and exact always-zero assertion, alternate-source derivation,
compilation/link/loader joins, 1,056 correct result words and the precise
original-provenance rejection.

The first public reader call at `0f9aaa36` failed with
`complete control packet member inventory: value differs`; its
[original process receipt](validation/local-attempt-04-replay-initial-failure-process.json)
and [terminal output](validation/local-attempt-04-replay-initial-failure.stdout.log)
remain unchanged. That reader had omitted the two actual destructor diagnostic
files. The original execution and ZIP remained successful and unchanged; the
failure belongs to this reader invocation.

After the reader-only correction, the unmodified public local CLI at
`ba2d649d4150e046c2ba610de02725d9d062b1be`, tree
`a9db358818a66f2a241ed2d8a7453edf938ccb2c`, accepted the same externally pinned
ZIP in **18.657440 seconds**, exit 0. Its [summary](validation/local-attempt-04-replay-summary.json)
and [complete result](validation/local-attempt-04-replay.json.gz) record all
5,597 members, 5,763 reads and 271,449,823 charged bytes. All real dependency,
native, control and local-envelope semantics ran, and the closing archive
check passed. No retained command, source or binary was executed.

The [independent guarded public-CLI review](agents/w10_a05.md) passed the same
exact-pin case in **20.738125 seconds** and rejected all eight individually
wrong external arguments: ZIP, revision, dependency receipt, native report,
native source snapshot, probe, substitution and local envelope. Every negative
returned exit 1 and produced no result file. The final harness denied all
producer-path opens/resolves/traversal, process/network/dynamic-loader events,
filesystem mutation and every write except the exclusive result. It recorded
zero prohibited events in all nine cases and returned through the closing
archive check. This is explicit instrumentation evidence, not an OS sandbox
or execution-origin authentication claim.

Both successful public results are byte-identical: **1,595,517 bytes**,
SHA-256 `2a28ebd63c136ccfde0b0b98c109e45765911fe1c53765ee0ca2b6cbdd669c3d`.
The [final independent receipt](validation/w10_a05-guarded-public-replay-review.json)
is 25,802 bytes, SHA-256
`6d46be8bd3c947c62eb64ab3abf2c9f219bc5c11b0fb0922cccf9bd94982536a`.
Its earlier, less comprehensive instrumentation result is preserved separately;
the repeated eight wrong-pin cases are eight distinct controls, not sixteen.

The exact original ZIP remained
`d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`
before and after both public reviews. Replay reports
`native_execution="not_run"`, `retained_code_executed=false` and
`origin_authenticated=false`; actual native execution belongs to the
separately pinned producer original at `0f9aaa36`.

## Final source/policy correspondence

The [independent final policy review](agents/w10_a04.md) used the audited base
classifier and policy for the `849469e1..ba2d649d` code range. It records R1,
with no R3 detector or R2 evidence escalation, and verifies **5,769 protected
entries unchanged**: 5,764 blobs and five superproject gitlinks. The protected
scope includes production hardware/model/software/tests, fixtures, numerical
goldens, workflow trust, immutable toolchain/version/configuration inputs,
governance policy, acceptance and the required SVG. It also verifies the final
three-file reader correction is exactly the reviewed profile. Its project
structure check and governance preflight pass in their metadata/tooling scope.
Those checks are not a clean full unit-suite or native rerun at `ba2d649d`.

Every result in this document leaves all seven qualification, warm and
acceptance flags false. None closes P06-A02/A03, vendor integration, absolute
no-wrap qualification, warm performance, RTL, FPGA or silicon acceptance.
