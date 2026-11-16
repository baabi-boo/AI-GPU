# P01 supplemental tensor harness and oracle reproduction

This continuation hardens the existing WMMA and FEDP unit-test harnesses.
Frozen execution source: **`ca8686d668ed9f2ff733ce7e3c12dd458b9776d8`**. Final matrix disposition:
**`pass — nine builds, 62 commands and 95 CLI checks`**. The [evidence index](evidence/p01-tensor-oracles/README.md)
retains exact source/publication mappings, command logs, failures and reviews.
Start from the publication checkout so the retained scripts are available. For
an exact source reproduction, copy those scripts out first, then select the
recorded implementation commit as described below. The mapped GitHub commit has
the same tree with different commit metadata.

This is supplemental P01 evidence. [P01-A03](phases/p01-baseline.md) still needs
qualified vendor XRT `hw_emu`; P01 remains blocked and P02–P11 remain
`not_started`. Unit RTL, host tests and DPI compatibility do not close those gates.

## What the harness now checks

- The shared [FP32 comparator](../../hw/unittest/common/fp32_compare.h) separates
  NaNs, infinities and finite numbers before measuring finite ULP distance.
  Two NaNs compare equal regardless of payload/sign; infinities require matching
  signs; signed zeros compare equal. Finite ordering uses unsigned wide arithmetic.
  **Both harness defaults remain 1 ULP. This matrix explicitly requests 0 ULP.**
- [Exact FP16/BF16 WMMA fixtures](../../hw/unittest/common/tensor_exact_cases.h)
  supply independent expected outputs for packed positions, row/column layout,
  cancellation, C values, boundaries and special values. Their comparisons always
  use **0 ULP**, independently of `--ulp`; the same NaN/signed-zero policy applies.
  The two older FP16 directed cases and random TFR cases still use `TfrFedp`.
- The [FEDP harness](../../hw/unittest/tcu_fedp/main.cpp) interprets C's FP32
  register bits by bit-cast. Its integer oracle uses
  [explicit modulo-2^32 arithmetic](../../hw/unittest/common/int_dot_reference.h),
  with unsigned products/accumulation and exact result-bit comparison.
- Both parsers reject malformed values, empty feature lists, zero test counts,
  unavailable compiled formats, unsupported rounding and out-of-range options
  before constructing the DUT.
  Selected cases regenerate the full preceding random stream, including MX scales,
  and report the number actually executed. Empty executed selections fail; for
  example, TF32 `--directed` is rejected after DUT construction/reset because no
  directed fixtures match.
- The two unit Makefiles track the new helper headers. Reconfigure after source
  Makefile changes so execution uses current generated build rules.

## Prepare the minimal dependencies

The recorded host was **Debian GNU/Linux 13.6 (trixie), GCC/G++ 14.2.0**.
`--osversion=ubuntu/focal` selects the pinned prebuilt bundle; it does not describe
the host OS. Automatic Debian detection rejected the initial configure attempt.

Only host build tools, Python, pinned Verilator and pinned SoftFloat are needed
for this matrix. Verilator **5.050** comes from the three `verilator/ubuntu/focal/`
parts in the [toolchain lock](../../ci/project/p01_toolchain.lock.json), immutable
toolchain commit `e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`.
SoftFloat is the source gitlink `b51ef8f3201669b2288104c28546fc72532a1ea4`.
The provisioning helper verifies each archive part before extraction; its receipt
is Verilator-only. RISC-V/LLVM, Ramulator, vendor tools and unrelated submodules
are outside this unit-test dependency set.

Start in a clean, reviewed checkout named `AI-GPU`. The retained scripts resolve
that directory as a sibling of `tensor-work`, so copy them out of the evidence
directory before running them. Use absolute paths without spaces.

```sh
TENSOR_SOURCE="$(pwd -P)"
TENSOR_WORK="$(dirname "$TENSOR_SOURCE")/tensor-work"
TENSOR_TOOLS="$TENSOR_WORK/tools"
TENSOR_EVIDENCE="$TENSOR_SOURCE/docs/project/evidence/p01-tensor-oracles"
mkdir -p "$TENSOR_WORK/reports" "$TENSOR_WORK/logs" "$TENSOR_WORK/tmp" "$TENSOR_TOOLS"
cp "$TENSOR_EVIDENCE/run_final_matrix.py" \
   "$TENSOR_EVIDENCE/provision_verilator.py" \
   "$TENSOR_EVIDENCE/bounded_command.py" "$TENSOR_WORK/"
df -h "$TENSOR_WORK"
free -h
```

To reproduce the exact native/full-suite source, after copying the helpers and
with a clean checkout, select its mapped GitHub commit:

```sh
git -C "$TENSOR_SOURCE" checkout --detach 9058c156c0b4c984455bbb25888304bfe4397ad2
```

That tree predates these documentation/evidence files; the copied scripts remain
available outside it. To test the current publication instead, keep its current
commit and record that distinct revision. The later host UTF-8 diagnostic helper
change does not alter the recorded native source files.

Provision once in this dedicated work directory. Materialize only the Verilator
subtree of the immutable toolchain checkout; initialize only the pinned SoftFloat
gitlink. The following checkout/extraction paths must be fresh.

```sh
git clone --filter=blob:none --no-checkout \
  https://github.com/vortexgpgpu/vortex-toolchain-prebuilt.git \
  "$TENSOR_WORK/toolchain-source"
git -C "$TENSOR_WORK/toolchain-source" sparse-checkout set --cone verilator/ubuntu/focal
git -C "$TENSOR_WORK/toolchain-source" checkout --detach \
  e3db4bcdf819a17f618ad9fc2472f8f7dea3192b
git -C "$TENSOR_SOURCE" submodule update --init -- third_party/softfloat
PYTHONDONTWRITEBYTECODE=1 python3 "$TENSOR_WORK/provision_verilator.py"
python3 - "$TENSOR_SOURCE" "$TENSOR_WORK" <<'PY'
import json, pathlib, sys
source, work = map(pathlib.Path, sys.argv[1:])
spec = {"id": "softfloat-build", "argv": ["make", "-j2", "-C", "third_party", "softfloat"],
        "cwd": str(source)}
(work / "softfloat-command.json").write_text(json.dumps(spec) + "\n")
PY
PYTHONDONTWRITEBYTECODE=1 python3 "$TENSOR_WORK/bounded_command.py" \
  "$TENSOR_WORK/softfloat-command.json"
```

Keep the provisioning receipt and SoftFloat command report/log. A later matrix
attempt can reuse these verified dependencies while taking fresh binary hashes.
Do not invoke the full toolchain installer's default/all-components selection.

## Run the host oracles separately

From the source root:

```sh
cd "$TENSOR_SOURCE"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s ci/project -p 'test_tensor_*.py' -v
```

These tests compile small C++17 host programs with warnings-as-errors and UBSan.
They check the comparator, modulo arithmetic and independent fixture decoders.
The fixture checks cover **6,988 expected output lanes** over FP16/BF16 and seven
shapes from `1×1` through `8×8`, including a separate exact rational decoder.
That is host fixture proof; it establishes no native 64-lane execution.
The native WMMA matrix below selects only four and eight threads.

## Execute the fixed nine-variant matrix

Run the retained [runner](evidence/p01-tensor-oracles/run_final_matrix.py) from
the restored layout. `--plan` only prints the selection; it does not test source
cleanliness, dependencies or hardware. For execution, use the checkout's full
commit ID and a fresh output path whose parent already exists:

```sh
cd "$TENSOR_SOURCE"
TENSOR_REV="$(git rev-parse HEAD)"
TENSOR_PACKET="$TENSOR_WORK/reproduction-$TENSOR_REV-01"
PYTHONDONTWRITEBYTECODE=1 python3 "$TENSOR_WORK/run_final_matrix.py" \
  --expected-revision "$(git rev-parse HEAD)" --plan
PYTHONDONTWRITEBYTECODE=1 python3 "$TENSOR_WORK/run_final_matrix.py" \
  --expected-revision "$(git rev-parse HEAD)" --output "$TENSOR_PACKET"
```

The runner rejects a dirty or changed source checkout, reused output directories,
and outputs overlapping source/tools. It configures each variant in its own
`builds/<id>` directory with `--xlen=32` or `--xlen=64`, the explicit tool path,
and `--osversion=ubuntu/focal`. It invokes the generated
`hw/unittest/tcu_unit` or `hw/unittest/tcu_fedp` Makefile from that build tree.

| Variant ID | Arithmetic | XLEN / threads | FEDP N / SF | Format IDs | Tests per format |
|---|---|---|---|---|---:|
| `wmma-rv32-t4-tfr` | Native TFR | 32 / 4 | — | 2, 3 | 1,000 |
| `wmma-rv64-t4-tfr` | Native TFR | 64 / 4 | — | 2, 3 | 1,000 |
| `wmma-rv64-t8-tfr` | Native TFR | 64 / 8 | — | 1, 2, 3 | 1,000 |
| `wmma-rv32-t8-dpi` | DPI C arithmetic | 32 / 8 | — | 1, 2, 3 | 1,000 |
| `fedp-rv64-n2-tfr-float` | Native TFR | 64 / 4 | 2 / 1 | 1, 2, 5, 8, 9, 10, 11 | 100,000 |
| `fedp-rv64-n4-tfr-float` | Native TFR | 64 / 4 | 4 / 2 | 3, 4, 8, 9, 10, 11 | 100,000 |
| `fedp-rv64-n2-tfr-integer` | Native TFR | 64 / 4 | 2 / 1 | 17, 18, 19, 20 | 100,000 |
| `fedp-rv32-n1-dpi-float` | DPI C arithmetic | 32 / 4 | 1 / 1 | 1, 2, 3, 4, 5 | 1,000 |
| `fedp-rv32-n2-dpi-integer` | DPI backend; RTL integer arithmetic | 32 / 4 | 2 / 1 | 17, 18, 19, 20 | 1,000 |

IDs are 1 TF32, 2 FP16, 3 BF16, 4 FP8/E4M3, 5 BF8/E5M2,
8 MXFP8, 9 MXBF8, 10 MXFP4, 11 NVFP4, 17 INT8, 18 UINT8,
19 INT4 and 20 UINT4. All variants set `SIMULATION`, `SV_DPI`,
`VX_CFG_EXT_TCU_ENABLE`, `VX_CFG_ISSUE_WIDTH=1`, the backend and thread count.
The T8 WMMA variants enable TF32; DPI floating FEDP enables TF32 and FP8.
Native floating FEDP sets `USE_FEDP` and all TF32/FP8/MX/FP4/MXFP4/NVFP4 enables;
integer FEDP enables INT8 and INT4. FEDP sets `USE_DSP=0` with N/SF as listed.

Every numerical invocation uses `--ulp=0 --no-trace`, the default seed 12345
and RNE. FEDP explicitly uses `--W=25`; WMMA retains its fixed window 25.
**DPI floating FEDP uses N=1 and `--no-fused`, without `USE_FEDP`.** With N>1,
the inherited DPI register-wise reduction and the harness's serial discrete
reference have different floating-point associations. Integer grouping is valid
modulo 2^32. DPI floating-point paths call C arithmetic; the selected DPI integer
paths use behavioral RTL multiplication/accumulation. `dpi_c_arithmetic` in the
retained report labels the backend family, not every selected integer result.

The planned total is **62 monitored commands**: four tool-version commands,
18 configure/build commands, 36 full format runs, two selected-case runs and
two CLI invocations. Each build uses `make -j2`, `THREADS=2`, explicit host
CC/CXX and source/tool paths, `OBJCACHE=` and `CCACHE_DISABLE=1`.
Budgets are 15 GiB free disk, 6 GiB sampled process-group RSS, 16 MiB per log,
1,200 seconds per build and 120 seconds per other command. They are sampled
budgets, not hard quotas; detached descendants and peaks between samples can
escape measurement. Tracing stays disabled.

## Inspect actual counts and reproduce selected checks

The runner validates output counts as well as exit status. FP16/BF16 WMMA
selections must report 20 independent exact cases; T4 FP16 additionally reports
two modeled directed cases. TF32 has neither fixture category. Full WMMA runs
report 1,000 random cases; FEDP reports its actual executed count.
Keep the original `--tests=N` when replaying FEDP: N determines its feature
blocks. Selected WMMA runs still execute the exact/modeled fixture prefix:

```sh
cd "$TENSOR_PACKET/builds/wmma-rv64-t4-tfr"
./hw/unittest/tcu_unit/tcu_unit --fmt=2 --tests=1000 --test=999 \
  --W=25 --ulp=0 --no-trace
cd "$TENSOR_PACKET/builds/fedp-rv64-n2-tfr-integer"
./hw/unittest/tcu_fedp/tcu_fedp --fmt=17 --tests=100 --test=50 \
  --W=25 --ulp=0 --no-trace
```

The first command expects `Coverage: exact=20 modeled-directed=2 random=1`;
the second expects `1 test(s) PASSED!`. These are expected markers, not results
established merely by this guide.

The [CLI checker](../../hw/unittest/common/tests/check_tensor_cli.py) executes
**58 + 37 = 95 checks**, including repeated baseline FEDP checks in the disabled
format profile. They verify early parser behavior and claim no numerical coverage:

```sh
cd "$TENSOR_PACKET/builds/wmma-rv64-t4-tfr"
TMPDIR="$TENSOR_PACKET/tmp" PYTHONDONTWRITEBYTECODE=1 python3 \
  "$TENSOR_SOURCE/hw/unittest/common/tests/check_tensor_cli.py" \
  --wmma "$TENSOR_PACKET/builds/wmma-rv64-t4-tfr/hw/unittest/tcu_unit/tcu_unit" \
  --fedp "$TENSOR_PACKET/builds/fedp-rv64-n2-tfr-float/hw/unittest/tcu_fedp/tcu_fedp" \
  --wmma-tfr-no-tf32
cd "$TENSOR_PACKET/builds/fedp-rv64-n2-tfr-integer"
TMPDIR="$TENSOR_PACKET/tmp" PYTHONDONTWRITEBYTECODE=1 python3 \
  "$TENSOR_SOURCE/hw/unittest/common/tests/check_tensor_cli.py" \
  --fedp "$TENSOR_PACKET/builds/fedp-rv64-n2-tfr-integer/hw/unittest/tcu_fedp/tcu_fedp" \
  --fedp-no-tf32-fp8-mx
```

Expect totals of `58/58` and `37/37`, each ending with
`CLI checks passed; no numerical coverage claimed`. A parser abort, timeout,
missing diagnostic or simulation/pass marker fails the checker. Each probe has
its own five-second and 64-KiB limits and separate process group; the outer
runner's process-group RSS does not include those separate groups.

## Preserve provenance and limitations

Retain `report.json`, logs, source/tree/submodule identities, runner/helper
snapshots, tool and SoftFloat hashes, binary hashes and generated configuration
and Makefile hashes. A non-pass command, incomplete cleanup or invalid execution
count stops the matrix. Keep failed packets when rerunning at a new revision.

The first frozen attempt at `20ea50d98d41684451c99df3b6f4eb43396f0c17`
failed on `wmma-rv64-t8-tfr-build`: GCC rejected the unavailable-format diagnostic's
array index under `-Werror=array-bounds`. Fourteen preceding commands completed;
only the RV32/T4/TFR and RV64/T4/TFR numerical variants and the selected RV64
FP16 case ran. T8 numerics, DPI, FEDP and both CLI suites were not reached.
The diagnostic correction and any later matrix belong to their own source and
packet. No nine-variant pass or 95-check result follows from that failed attempt.

This matrix does not execute the full AFU, vendor `hw_emu`, physical FPGA or
silicon. Its random native TFR floating-point checks share the windowed model; exact WMMA
fixtures supply the separately counted independent expected values. Other
backends, native 64-lane WMMA, alternate latencies, WGMMA concurrency and full
P02 numerical qualification remain outside this selection. Source-root
governance/full tooling checks and publication verification are recorded
separately in the [evidence index](evidence/p01-tensor-oracles/README.md).
