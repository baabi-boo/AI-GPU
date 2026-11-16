# P02 numerical contract and executable fixtures

**P02-T01 is complete.** The reviewed numerical contract and independent
fixtures support [P02-A01 at `source_present`](evidence/p02-numerics/acceptance.json).
The phase remains `in_progress`: P02-A02 whole-processor arithmetic/layout
coverage and P02-A03 WGMMA concurrency remain pending. The authoritative
acceptance entries are in [roadmap.json](roadmap.json). P01's vendor `hw_emu`
obligation remains separate and blocked.

## What is implemented

- The [versioned numerical specification](../designs/tensor_numerics_v1.md)
  and [machine manifest](../../ci/project/p02_tensor_contract.json) freeze the
  native TFR FP16/BF16-to-FP32 four-product unit profile and comparison rules.
- The [independent producer](../../ci/project/p02_fixture_oracle.py) derives
  [98 deterministic fixtures](../../ci/project/fixtures/p02_tfr_v1.json) using
  integer and rational arithmetic. It records exact-real references separately
  from the specified fixed-window results. No production arithmetic model
  generates the expected outputs.
- The [runnable application profile](../../profiles/p02-tfr.json) freezes
  the first ordinary WMMA application geometry and native arithmetic settings.
  Twenty [independent layout fixtures](../../ci/project/fixtures/p02_layout_v1.json)
  define matrix storage, packed input words and exact outputs at FEDP and tile
  boundaries. Their source checks are separate from device execution.
- The [strict unit harness](../../hw/unittest/tcu_contract/main.cpp) consumes
  the same frozen bits through native RTL or the production model function.
  It checks signed zero, NaN bits, rounding, cancellation, subnormals, finite
  extremes and packed lanes. Its stall mode checks the leaf pipeline's enable
  behavior; it does not exercise WGMMA scheduling.
- The native [tensor API](../../sw/kernel/include/vx_tensor.h) rejects TFR
  input formats that are absent from the compiled configuration when WMMA or
  WGMMA contexts are instantiated. This is a C++ compile-boundary contract;
  raw unsupported instructions do not acquire a hardware trap.

The distinct historical P01 application geometries and tolerances are preserved.
The new BF16 four-product unit profile must not be presented as the historical
eight-product BF16 application configuration.

## Tested source and observed results

Qualifying execution used the clean implementation commit
[`a25321496d802f43830c1658487f1adf79c838c3`](https://github.com/baabi-boo/AI-GPU/commit/a25321496d802f43830c1658487f1adf79c838c3),
tree `7e459269e22f90691cf410e42068982f5a8c7a2d`. Every formal command
records that revision and a clean working state before and after execution.
Subsequent evidence and documentation commits retain this tested identity.
The [evidence index](evidence/p02-numerics/README.md) provides the command logs,
source/tool/configuration identities, selected header provenance, reviews,
artifact hashes and historical failure records.

| Check | Observed result | Evidence boundary |
|---|---|---|
| Full offline suite | 1,343 tests passed in 369.310 seconds; no failures, errors or skips | Project tooling, source contracts and host model-function tests |
| Frozen fixture reproduction | All 98 arithmetic cases, generated C++ header and 20 layout cases reproduced byte-for-byte | Deterministic source data; layout cases have not executed on a GPU |
| Fresh native TFR leaf | 98 dense cases passed | Exact raw FP32 bits through direct `VX_tcu_fedp_tfr`; no DPI arithmetic |
| Native leaf enable stalls | The same 98 cases and 306 hold checks passed | Leaf pipeline enable behavior; repeated dense runs add no unique coverage |
| Production model function | All 98 cases passed | Host `TfrFedp`, distinct from full SimX processor execution |
| Actual RISC-V API matrix | 47 cases passed: 17 positive compilations, 30 intended rejections; both contexts in each case | 94 WMMA/WGMMA context checks; compile-boundary rejection only |
| Existing FP16/BF16 consumer kernels | Four actual RISC-V relocatable objects compiled | WMMA uses `p02-tfr`; WGMMA uses explicit overrides outside ordinary profile qualification |

The leaf fixture inventory contains 49 FP16 and 49 BF16 cases. Numerical
comparisons use exact `uint32_t` equality, including signed zero and canonical
NaN bits. Compiler negatives exit nonzero as intended; their rejection checks
pass only with the exact required diagnostics. They are not successful compiler
invocations or raw-instruction trap tests.

## Reproduce the checks

From the source root, check the frozen artifacts and the offline tests:

```sh
python3 ci/project/p02_fixture_oracle.py --check
python3 ci/project/p02_layout_fixture_oracle.py --check
python3 -m unittest discover -s ci/project -p 'test_p02_*.py'
python3 ci/project/check_project.py
```

The full offline suite is `python3 -m unittest discover -s ci/project -p
'test_*.py'`. Native C++ model checks require a C++17 compiler and UBSan; they
do not execute a full SimX processor.

### Fresh native leaf and model build

Run the following from the source root, replacing the absolute path placeholders
with the pinned tool locations and **new** build directories. Tool versions and
executable hashes are in the [evidence packet](evidence/p02-numerics/README.md).
The native build and model build run sequentially; keep the same `THREADS=2`
setting for subsequent invocations so the configuration stamp stays consistent.

```sh
P02_SOURCE="$(pwd)"
P02_TOOLS=/absolute/path/to/riscv-tool-bundle
P02_VERILATOR=/absolute/path/to/verilator
P02_NATIVE_BUILD=/absolute/path/to/new-p02-native-build
mkdir "$P02_NATIVE_BUILD"
(cd "$P02_NATIVE_BUILD" && "$P02_SOURCE/configure" --xlen=64 \
  --profile=p02-tfr --tooldir="$P02_TOOLS" --osversion=ubuntu/focal)
p02_unit() {
  make -C "$P02_NATIVE_BUILD/hw/unittest/tcu_contract" -j2 THREADS=2 \
    VERILATOR_PATH="$P02_VERILATOR" "$@"
}
p02_unit all
p02_unit model
p02_unit run OPTS='--format=all'
p02_unit run OPTS='--format=all --stalls'
p02_unit run-model OPTS='--format=all'
```

The unit Makefile supplies both raw profile flags and resolved C++ selectors.
Use the generated Makefiles; an extra backend define is not a substitute for
fresh configuration. Keep at least 15 GiB free, use no more than two compile
workers, and leave waveform/debug output disabled. Qualifying evidence collection
also retains the recorded time, memory, log and cleanup budgets; the archived
bounded runner and command records show those limits. The
[specification](../designs/tensor_numerics_v1.md#8-reproduction-and-evidence-levels)
defines fixture selection and the distinct execution scopes.

### Separate compiler matrix

The [actual compiler runner](../../ci/project/p02_api_compile.py) requires a
fresh RV64 build with an **empty profile**, because each of its 47 cases supplies
its exact backend and format configuration. Its output directory must not exist.
Using the source and tool variables above:

```sh
P02_API_BUILD=/absolute/path/to/new-p02-api-build
P02_API_OUTPUT=/absolute/path/to/new-p02-api-results
mkdir "$P02_API_BUILD"
(cd "$P02_API_BUILD" && "$P02_SOURCE/configure" --xlen=64 \
  --profile= --tooldir="$P02_TOOLS" --osversion=ubuntu/focal)
(cd "$P02_API_BUILD" && python3 "$P02_SOURCE/ci/project/p02_api_compile.py" \
  --build-dir "$P02_API_BUILD" --tools-dir "$P02_TOOLS" \
  --output "$P02_API_OUTPUT")
```

### Existing consumer objects

The retained consumer checks use a supplemental object-only Makefile, because
the ordinary application target also proceeds through linking. Extract the
exact `formal-compiler/object-only.mk` member into a new scratch file:

```sh
P02_OBJECT_ONLY_MK=/absolute/path/to/new-object-only.mk
python3 - "$P02_SOURCE/docs/project/evidence/p02-numerics/evidence-bundle.json.gz" \
  "$P02_OBJECT_ONLY_MK" <<'PYEXTRACT'
import gzip, hashlib, json, sys
from pathlib import Path
bundle = json.loads(gzip.decompress(Path(sys.argv[1]).read_bytes()))
member = next(m for m in bundle['files']
              if m['path'] == 'formal-compiler/object-only.mk')
body = member['content'].encode('utf-8')
assert hashlib.sha256(body).hexdigest() == member['published_sha256']
with Path(sys.argv[2]).open('xb') as destination:
    destination.write(body)
PYEXTRACT
```

For each row, configure a separate new RV64 build directory with
`--profile=p02-tfr`, as in the native example. Set `P02_CONSUMER_BUILD` to that
directory, `P02_APP` and `P02_APP_FLAGS` to the row's values, and run the two
commands below. Supply `CONFIGS` through the environment as recorded, allowing
the generated profile configuration to be merged by the Makefiles.

| Consumer | `P02_APP` | `P02_APP_FLAGS` |
|---|---|---|
| WMMA FP16 | `sgemm_tcu` | `-DITYPE=fp16 -DOTYPE=fp32 -DKUNROLL=1` |
| WMMA BF16 | `sgemm_tcu` | `-DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1` |
| WGMMA FP16 | `sgemm_tcu_wg` | `-DITYPE=fp16 -DOTYPE=fp32 -DKUNROLL=1 -DVX_CFG_TCU_WGMMA_ENABLE -DVX_CFG_NUM_WARPS=4 -DVX_CFG_ISSUE_WIDTH=4 -DWGMMA_RS` |
| WGMMA BF16 | `sgemm_tcu_wg` | `-DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1 -DVX_CFG_TCU_WGMMA_ENABLE -DVX_CFG_NUM_WARPS=4 -DVX_CFG_ISSUE_WIDTH=4 -DWGMMA_RS` |

```sh
CONFIGS="$P02_APP_FLAGS" make -C "$P02_CONSUMER_BUILD/tests/regression/$P02_APP" \
  -j1 -f Makefile -f "$P02_OBJECT_ONLY_MK" kernel-inputs
CONFIGS="$P02_APP_FLAGS" make -C "$P02_CONSUMER_BUILD/tests/regression/$P02_APP" \
  -j1 -f Makefile -f "$P02_OBJECT_ONLY_MK" kernel.o
```

The packet retains the before/after dependency-set and identity checks for these
compilations. WGMMA overrides are outside ordinary profile qualification. These
commands produce relocatable objects; they do not execute kernels or qualify
WGMMA concurrency.

## Review and retained failures

Independent reviews checked fixture derivations, matrix layouts, build
invalidation, compiler input provenance, contract completeness and the R3 native
API change. The [P02-A01 record](evidence/p02-numerics/acceptance.json) accepts
the source contract only. Agent review supplies scoped engineering evidence;
the [collaboration ledger](evidence/p02-numerics/agent-execution.json) does not
constitute a GPU test or human waiver.

Two unexpected failures are retained. The first dirty-source stall run failed
when a second Verilator model reused a nonzero-time context; each DUT now owns
its own context. Its pre-fix harness bytes were not retained, and the historical
record states that provenance limitation. The first clean candidate,
`135cfec14d1fed0b4e950bc243e69a91879e4275`, failed native compilation because
raw profile enum flags did not provide the required C++ selector macros. The
resolved-flag correction and its real-profile regression precede the clean
passing revision above. Neither failure is overwritten by its later pass.

Forbidden fast-math configurations were intentionally rejected before and after
build invalidation was strengthened. A native stale-object bypass was not
reproduced. Production arithmetic, inherited golden data and accepted P01
tolerances remain unchanged.

## Next bounded action

**P02-T02: implement a fixture input adapter for the existing WMMA regression,
then execute the frozen cases on full SimX and native processor RTL.**
The existing `sgemm_tcu` host still generates its own matrices; it does not yet
consume `p02_layout_v1.json`. Add explicit fixture/case selection, copy the
declared packed inputs without reinterpretation, and compare returned FP32 bits
against the independent expected outputs. Keep unknown/empty selections and
unsupported combinations explicit failures.

Use matching application/backend `p02-tfr` configurations for FP16 and BF16,
with FP32 output and `KUNROLL=1`. Exercise the frozen compact layouts, single
and multiple tiles, FEDP/K boundaries and multi-instruction accumulation.
Retain normal, edge and cancellation comparisons at the appropriate arithmetic
and processor boundaries. Preserve the v1 rules and inherited tolerances;
the 20 exact-integer layout fixtures are not a general whole-GEMM rounding
oracle.

Then qualify WGMMA synchronization, descriptor/metadata handling, multiple
warps and backpressure with applicable model-parity evidence and explicit
configuration limits. Leaf enable stalls and compiled WGMMA objects cannot
satisfy those obligations. Full-shell/vendor and physical-device evidence
remain separately scoped.

P03 remains `not_started` until all P02 exit obligations are met. Preserve
P01-A03's blocked vendor integration evidence and the P07 dependency.

The frozen specification's section 8 reference to applicability limits applies
only to model-parity applicability. As the authoritative
[phase guide](phases/p02-tensor.md) states, a reviewed parity limit does not waive
WGMMA synchronization, metadata, multi-warp or backpressure correctness tests.
