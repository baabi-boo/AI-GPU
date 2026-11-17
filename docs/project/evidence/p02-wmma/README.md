# P02 ordinary WMMA processor evidence

**The original ordinary WMMA matrix and its corrected-host replay both pass.** The separate [canonical acceptance record](acceptance.json) records the independent P02-A02 decision; this packet does not close P02. [summary.json](summary.json) binds the completed results, two source identities, preserved failures and scope limits. Apply the [acceptance policy](../../acceptance.md) and [evidence contract](../README.md).

## Source and build identity

| Observation | Source identity | Meaning |
|---|---|---|
| Fresh formal processor builds and actual API compiler matrix | Commit `58faf6d68879e1db92122df493172eab59c02458`, tree `cd35869ee89cb42685e9bac367667a7dffbe1b1d` | Clean, stable source. These are the original complete four-variant processor and compiler-boundary results. |
| Host-only reporting child | Commit `c9cf9ba0730f236e110a1d48a54d8f47a9faf9af`, tree `df62aa14b7dee5e02ad85027ac0e3225d1d8e4a1` | Direct child of the formal source. Only `tests/regression/sgemm_tcu/main.cpp` changed, restoring the live legacy random `int`/`%d` reporting while preserving fixture `size_t`/`%zu` reporting. |
| Completed child host supplement | Four rebuilt hosts; 184 commands, 352 launches and 14,336 exact words passed | All 108 nonhost artifacts and original backend/kernel inputs remain unchanged. This is not a fresh backend/RTL build at the child. |

The focused source-contract test and all 15 host-adapter tests passed on the
exact uncommitted reporting patch before the child commit. Its source hash and
diff match the child. Those particular tests are host/source checks. The separate clean-child full suite passed all 1,448 tests, and the patched processor application passed the complete host replay described above.

## Observed formal processor result

The retained original matrix reports **209 bounded commands, 176 case/backend
executions, 352 launches and 14,336 checked output words**, with no mismatches.
It uses **88 fixtures: 68 numerical and 20 unchanged layout cases**. Each
format has 44 fixtures, run twice on each backend.

| Backend and input format | Fixture commands | Launches | Exact output words | Observed result |
|---|---:|---:|---:|---|
| SimX FP16 → FP32 | 44 | 88 | 3,584 | Pass |
| SimX BF16 → FP32 | 44 | 88 | 3,584 | Pass |
| Processor rtlsim FP16 → FP32 | 44 | 88 | 3,584 | Pass |
| Processor rtlsim BF16 → FP32 | 44 | 88 | 3,584 | Pass |
| **Total** | **176** | **352** | **14,336** | **Pass at the original formal source** |

Each launch checks every returned `uint32_t` word against independently
produced frozen expected bits and retains every word in a `P02_RESULT` record.
Both output destinations are poisoned with `expected XOR 1` before every
launch so missed writes or reads cannot reuse a previous passing result. Independent reviews reconstructed the 3,584 words in one fixture inventory,
replayed 9,472 FEDP steps and checked exact cross-backend equality. The corpus
and expected values were not changed to resolve the development failure.

The processor configuration is the frozen `p02-tfr` RV64 profile: one cluster
and core, four warps of four threads, issue width one, ordinary dense/unscaled
WMMA, FP16 or BF16 input with FP32 output, element tile **8×4×8**,
`KUNROLL=1`, `TCU_LATENCY=4` and `TCU_USE_DSP=0`. A is compact row-major,
B is compact column-major, and output is compact row-major. TFR tensor and STD
scalar floating-point arithmetic are native RTL. The processor simulator still
uses inherited integer multiply/divide DPI helpers, including `dpi_lmul` and
`dpi_ldiv` in RV64; it is not a universally DPI-free processor.

## Unsupported-input evidence

The separate actual RISC-V API matrix met **47 expectations**: **17 successful
syntax-only compiles and 30 intended compiler-exit-1 rejections**. Each
translation unit forces both WMMA and WGMMA class contexts, producing 94
context checks: 34 successful contexts and 60 intended rejections. The complete
packet has 150 command/log records, including 47 dependency probes.

| API category | Expectations |
|---|---:|
| Enabled TFR format controls | 13 successful compiles |
| Other-backend compatibility controls | 4 successful compiles |
| Disabled format families | 9 intended rejections |
| Missing prerequisite guards | 12 intended rejections |
| Unsupported input encodings | 4 intended rejections |
| Invalid output types | 5 intended rejections |

This compiler matrix uses an explicit empty-profile RV64 eight-thread
configuration with WGMMA enabled for class-instantiation coverage. It is
separate from the four-thread execution profile. The negatives require the
precise public-header assertion in both contexts. They establish a C++ API
boundary, not a hardware trap. Other-format/backend positives establish
compatibility only and do not expand the FP16/BF16 numerical qualification.
Compile-only WGMMA contexts do not demonstrate WGMMA concurrency.

The 15-test host-adapter suite exercises raw fixture input packing, every output
word, repeated poison/launch/read behavior, corruption controls and early
rejection. The reviewed inventory identifies 94 rejection scenarios and 84
negative-control scenarios. These are host/runtime-stub scenario counts, not
extra device launches or arithmetic results.

## Preserved failures and their disposition

### Development SimX selector failure

The original development packet failed after 17 successful case commands on
`fp16-numerical-cancel_large_with_tiny`. Its two failing launches returned
`33800000` where the frozen expected word remained `00000000`, giving 64
mismatched words. The observed `make` exit was 2. The exact command, environment
and log are retained in `dev-matrix-packet/report.json` and
`dev-matrix-packet/logs/simx-fp16-fp16-numerical-cancel_large_with_tiny.log`.
The failed report's original SHA-256 is
`a1cb0e9b59a28e6f49cf984a8d4a25bf59ae795915a070b8fb1b560c5f7a87f0`.

That execution used a dirty development tree based on
`e829e6c6ec638c66910871a3be30eb562acf6903`, not either later clean revision.
The exact changed and untracked input bytes are bound by the identical retained
before/after source inventories; the base commit alone is not the tested tree.
Their original SHA-256 is
`6cffa6814c084e04bdf91af81d71be9484fef7173d1eb095089252e51d98e665`.

Independent source, compiler-record and disassembly reviews found that
`sim/simx/Makefile` did not append resolved `XCONFIGS` to `CXXFLAGS`.
Raw `TCU_TYPE=TFR` suppressed the generated default, while the resolved
`TCU_TYPE_TFR` selector was missing. SimX therefore selected fallback arithmetic
and preserved the small `2^-24` residual that the declared TFR fixed alignment
window discards before cancellation. The build now passes the resolved selectors,
and the runner checks them independently. The corrected development pass and
original clean formal four-variant pass are separate retained records. The
failed evidence and expected words remain unchanged.

### Original formal offline-suite failure

The complete offline suite at `58faf6d...` ran **1,448 tests: 1,447 passed,
one failed, with no errors or skips**. The source remained clean and stable.
The retained wrapper invoked the pinned Python interpreter on
`${WORK}/run_offline_suite.py` from `${SOURCE}` and returned exit 1. The runner
uses `unittest.defaultTestLoader.discover` with `test_*.py` and retains the exact
before/after source inventories.

The failure was
`test_local_qualification_cases.CaseSourceContractTests.test_synthetic_oracles_match_original_source_output_and_reference_checks`.
Its inherited assertion expects the live random path's exact `int iter_errors`
and `%d` reporting expression. The shared `%zu` fixture/random summary no
longer matched that contract. The child restores the real legacy reporting
branch and keeps the fixture branch's exact-bit behavior. The test was neither
removed nor weakened.

Retained members are `reports/formal-offline-suite.json`,
`reports/formal-offline-suite-results.json`, `logs/formal-offline-suite.log` and
`run_offline_suite.py`. The results file's original SHA-256 is
`9b979eab41c84229ec35686b0893a735c8d23790e6aafdc98f153f545a076258`;
its log's original SHA-256 is
`551a6f71ce2a413eafea341a017ad9df9e5c67a2dabef32b96d7876b0873422d`.
The complete child-source suite subsequently passed all 1,448 tests with no failures, errors or skips in 589.248 seconds. Its identical test inventory and stable clean source are independently audited; that later pass does not overwrite this failure.

The independent legacy review also records an inherited `int` mismatch-counter
capacity issue for extremely large random matrices. It is outside the bounded
fixture corpus and was neither introduced nor worsened by the restoration;
this packet does not claim it fixed.

## Coverage boundaries and phase effect

- Every processor fixture starts with **FP32 C=+0**. Constructed nonzero
  intermediate accumulators are exercised, but arbitrary external initial C
  remains outside this application evidence.
- K is **8 or 16**, with two or four sequential four-product FEDP groups.
  Observed matrix shapes are **8×4×8, 8×4×16 and 16×8×16**. Longer reductions,
  arbitrary strides, padding, tails and transpositions are not qualified.
- Four K16 numerical cases detect reversal of complete K8 tiles. They do not
  distinguish independently rounded tile partials followed by summation.
- BF16 provides applicable signed overflow and FP32 output-FTZ checks. The
  FP16 finite input range does not imply equivalent overflow sensitivity.
- Processor `rtlsim` bypasses the AFU. There is no full-shell/vendor `hw_emu`,
  physical FPGA, silicon, synthesis/timing, throughput, power or model-cycle
  parity result here.
- Catalog runtime checks preserve their inherited tolerance contracts. The three local RV64 representatives passed 3,072 output checks. Their results and the separately recorded hosted recovery are compatibility supplements, not additional exact A02 fixtures or qualification of more formats. See [CI recovery](ci-recovery.json).
- P02-A03 WGMMA synchronization, metadata, multiple-warps and backpressure
  remain separate obligations. **P02 stays `in_progress`, P01-A03 stays
  blocked, and P03 stays `not_started`.** The arithmetic result does not finish
  P02-T02's existing arithmetic-and-concurrency scope.

## Compact retention and finalization

The final packet contains `evidence-bundle.json.gz` and `inventory.json`
alongside the summary and canonical acceptance report. The bundle retains all
209 formal matrix command records, all 150 API command records, their logs and
source/configuration/compiler identities, historical failures and independent
reviews. The acceptance report contains nine representative actual commands;
it does not duplicate the complete command arrays. The summary names exact
member paths and hashes for the supporting records.

Original files and published normalized text have distinct identities. A literal
replacement of source/work/tools path prefixes changes published bytes. All
`original_sha256` fields in this summary identify original retained bytes;
existing embedded hashes keep that meaning. The final inventory must identify
both original and published member hashes. Do not compare a normalized member
directly with an original-byte digest or rewrite embedded historical digests.

The core bundle contains **1,426 members** and is **3,860,472 bytes**, below its 4 MiB cap. Both original-byte and published-only verification passed. Its SHA-256 is `a4e95bfe1043c3964d9017c1f89d37a04bccfff93d8b6b341adbbeeb2a38e36d`.

The eight old/new host executable bodies are excluded; their identities remain in the reports. The 326-member, 6,938,609-byte host copy of the original matrix is an exact duplicate. The retained `w08_a04_host_packet_aliases.json` maps each omitted mirror member to its canonical formal member and binds both original and normalized digests. Reconstruct the mirror by copying each canonical published member to its declared alias path and verifying its published hash; no unique original evidence is removed.

The bundle retains a clearly labelled 51-agent core checkpoint. The preserved historical [51-assignment checkpoint](agent-execution.json), [source publication](source-publication.json), [CI recovery](ci-recovery.json), and [independent recovery review](recovery-review.json) are separate, avoiding circular or changing bundle hashes. These delivery records do not relabel the source of the numerical executions.

## Verify the published bundle

```sh
python3 - <<'PYVERIFY'
import gzip, hashlib, json
from pathlib import Path
p = Path('docs/project/evidence/p02-wmma')
sha = lambda b: hashlib.sha256(b).hexdigest()
i = json.loads((p / 'inventory.json').read_text())
z = (p / i['bundle_path']).read_bytes()
assert len(z) == i['bundle_size_bytes'] and sha(z) == i['bundle_sha256']
b = gzip.decompress(z)
assert sha(b) == i['uncompressed_bundle_sha256']
f = json.loads(b)['files']
assert len(f) == i['file_count'] == len({x['path'] for x in f})
assert [{k:v for k,v in x.items() if k != 'content'} for x in f] == i['files']
for x in f:
    body = x['content'].encode('utf-8')
    assert len(body) == x['published_size_bytes'] and sha(body) == x['published_sha256']
print('Verified', len(f), 'published members')
PYVERIFY
```
