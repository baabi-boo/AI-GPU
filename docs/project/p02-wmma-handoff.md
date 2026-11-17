# P02 ordinary WMMA processor qualification and runbook

**The ordinary WMMA fixture adapter is implemented, and the full FP16/BF16
SimX and native processor RTL matrix passed at the revision below.** The
[evidence index](evidence/p02-wmma/README.md) retains the execution packet,
independent reviews and historical failure. The scoped
[P02-A02 acceptance record](evidence/p02-wmma/acceptance.json) and
[canonical roadmap](roadmap.json) govern acceptance; a successful runner packet
does not grant it automatically.

**P02-T02 remains active:** it covers both P02-A02 arithmetic/layout and P02-A03
WGMMA concurrency. P02 remains `in_progress`, P02-A03 remains pending, and P03
remains `not_started`. P01-A03 vendor `hw_emu` remains separately blocked. The
[numerical handoff](p02-numerics-handoff.md) and
[P02-A01 source acceptance](evidence/p02-numerics/acceptance.json) retain their
historical source, leaf and compiler results; this packet adds processor
execution evidence without rewriting those results.

## Implemented path and frozen inputs

The existing [`sgemm_tcu` host](../../tests/regression/sgemm_tcu/main.cpp) now
accepts `-f CASE_ID -r 2`. Its [adapter](../../tests/regression/sgemm_tcu/p02_fixture_adapter.h)
selects compiled fixtures from the generated
[header](../../tests/regression/sgemm_tcu/p02_fixtures.h). The
[exporter](../../ci/project/p02_wmma_fixtures.py) validates and combines the
unchanged 20 [layout cases](../../ci/project/fixtures/p02_layout_v1.json) with
68 [numerical cases](../../ci/project/fixtures/p02_wmma_numerical_v1.json):
88 unique cases, 44 per input format. The
[independent numerical producer](../../ci/project/p02_wmma_numerical_fixture_oracle.py)
uses integer and rational arithmetic to apply the frozen four-product FEDP
contract sequentially and retain intermediate results. Production arithmetic
never supplies expected outputs.

Four additive `cross_tile_rounding_positive` / `cross_tile_rounding_negative`
cases, one pair per format, extend numerical coverage to K=16. They distinguish
forward accumulation across two WMMA K tiles from reversing those tiles:
forward execution returns `00000000`; reversing the tiles retains positive or
negative `2^-24`. They supplement the original cases without modifying the
98 frozen leaf fixtures, the 20 layout fixtures or their expected bits.

Fixture mode copies raw little-endian packed A words in row-major order and B
words in the declared column-major order. It uses the
[existing kernel](../../tests/regression/sgemm_tcu/kernel.cpp), whose accumulator
starts at `+0`; the kernel was not changed for this adapter. Before **every**
launch, the host and device destination buffers receive `expected XOR 1` so a
missed write or read cannot inherit a passing result. Every returned FP32 word
is compared as `uint32_t`, including signed zero and NaN bits. A `P02_RESULT`
JSON record contains the case, format, dimensions, zero-based iteration,
checked count, mismatch count and all actual words. Fixture mode does not call
the host GEMM reference to construct its expected output.

Unknown, ambiguous or empty fixture IDs, duplicate `-f`, incompatible
`-m`/`-n`/`-k`/`-z`, malformed or zero counts, format mismatch and unsupported
compiled configurations fail explicitly. Shape and packed-word checks precede
device access. Matrix products use wide arithmetic and check both host byte
capacity and the existing uint32 indexing range before allocation or launch;
sub-byte indexing is included. Device capability checks enforce the observable
profile geometry. The [application Makefile](../../tests/regression/sgemm_tcu/Makefile)
tracks `common.h` through `VX_HDRS`, as well as the host adapter and generated
fixture headers, so shared kernel arguments invalidate the kernel build.

## Exact execution scope and observed results

The clean tested source is
[`58faf6d68879e1db92122df493172eab59c02458`](https://github.com/baabi-boo/AI-GPU/commit/58faf6d68879e1db92122df493172eab59c02458),
tree `cd35869ee89cb42685e9bac367667a7dffbe1b1d`. Source snapshots before,
between and after the four variants agree. Evidence/documentation publication
must preserve that tested identity even if its own commit is later.

The unchanged [`p02-tfr` profile](../../profiles/p02-tfr.json) selects RV64, one
cluster/core, four warps of **four threads**, issue width one, native TFR tensor
and STD scalar floating-point arithmetic, FP16/BF16 inputs, FP32 outputs and
`KUNROLL=1`. The ordinary tile is 8×4×8 elements, with a 2×2×2 packed micro-tile
and four products per FEDP. Other tensor format banks, sparse/scaled paths,
DSM, WGMMA, FEDP2K and matrix load/store instructions are disabled. Use
`*_DISABLE` for boolean banks; `*_ENABLE=0` still defines a macro.

| Variant | Unique case executions | Launches | Checked output words | Bit mismatches |
|---|---:|---:|---:|---:|
| SimX FP16 | 44 | 88 | 3,584 | 0 |
| SimX BF16 | 44 | 88 | 3,584 | 0 |
| Processor RTL FP16 (`rtlsim`) | 44 | 88 | 3,584 | 0 |
| Processor RTL BF16 (`rtlsim`) | 44 | 88 | 3,584 | 0 |
| **Total** | **176** | **352** | **14,336** | **0** |

These are 176 case/backend commands, each with two launches, within **209
bounded commands** including tool, configuration and build checks. Repeats do
not add unique fixtures. Independent result review parsed raw records,
reconstructed expected outputs, and checked SimX/RTL equality within each
format: 44 case pairs, 88 launch pairs and 3,584 word pairs per format, all
exact. This establishes result parity for the retained cases; it does not
establish cycle or performance parity.

The native claim is specifically **native TFR tensor and STD scalar
floating-point datapaths**. `SV_DPI` remains enabled for inherited RV64 integer
multiply/divide helpers, including `dpi_lmul` and `dpi_ldiv`. Compiler records,
effective macro probes and the elaborated-path audit establish the selected
floating-point paths. The processor is not universally DPI-free. Processor
`rtlsim` bypasses the AFU; full-shell XRT, vendor emulation, physical FPGA and
silicon evidence require their own runs.

The separate actual RISC-V API matrix met **47 expectations**: **17 successful
syntax-only compilations and 30 intended compiler rejections**, with both WMMA
and WGMMA contexts instantiated in each translation unit (**94 context checks**).
Each negative requires the exact public-header assertion for both contexts;
an arbitrary compiler/tool failure is not a passing rejection. This explicit
empty-profile RV64 matrix uses eight threads and enables WGMMA. Its additional
format/backend positives establish C++ compatibility only and do not extend
the four-thread ordinary numerical profile. Neither compilation nor rejection
executes a kernel or establishes a raw-instruction hardware trap. The public API
guard adds no hardware trap for raw unsupported instructions.

## Retained failures and narrow corrections

The original development SimX run failed
`fp16-numerical-cancel_large_with_tiny`: every output was `33800000` instead of
the unchanged expected `00000000`. Raw `VX_CFG_TCU_TYPE=TFR` / `VX_CFG_FPU_TYPE=STD` enum
flags suppressed generated default selector companions, but the SimX Makefile
did not append the resolved companions to `CXXFLAGS`. Retained compiler flags
and disassembly showed scalar fallback arithmetic. It retained `2^-24`, which
the specified TFR fixed window discards before cancellation.

The [SimX Makefile correction](../../sim/simx/Makefile) appends only the
canonical resolver's `VX_CFG_TCU_TYPE_*` and `VX_CFG_FPU_TYPE_*` selectors, matching the
existing processor RTL selection pattern. It preserves raw configuration and
header-derived scalar/boolean settings. The original and freshly generated
headers match; this was not a stale-header workaround. Configuration stamps
invalidate affected objects, and the matrix validator now checks the actual
backend record and effective selectors. Production arithmetic, RTL, the
profile, goldens and expected output bits remain unchanged. The failed packet,
compiler record, object identity, disassembly and failure log remain retained alongside
the later pass in the [evidence index](evidence/p02-wmma/README.md).

### Legacy reporting compatibility and the final host

The full offline suite at `58faf6d` ran 1,448 tests: 1,447 passed and one
inherited source-contract check failed. That check requires the original
random-input iteration report, including its `int` mismatch counter and `%d`
format. Sharing the new fixture path's `size_t`/`%zu` report changed that
source contract even though ordinary displayed counts were equivalent.

The clean child
[`c9cf9ba0730f236e110a1d48a54d8f47a9faf9af`](https://github.com/baabi-boo/AI-GPU/commit/c9cf9ba0730f236e110a1d48a54d8f47a9faf9af),
tree `df62aa14b7dee5e02ad85027ac0e3225d1d8e4a1`, restores the actual random
branch's reporting and keeps fixture reporting separate. Only that host block
changes. The focused inherited check and all 15 host-adapter methods pass;
the failed full-suite record remains available. No test or expected bit was
changed to obtain those passes.

The final host revalidation reconfigures all four original build trees,
replays only their validated host compiler/linker commands, and checks every
fixture again. It requires unchanged source inputs outside `main.cpp` and
unchanged tools, dependencies, generated configuration, runtime, backend and
kernel artifacts before and after reuse. The original backend/kernel build
identity remains `58faf6d`; the new host identity is `c9cf9ba`. This is a
supplemental host rebuild and complete fixture replay, not a fresh backend
build at the child revision. `The corrected-host replay passed **184 commands, 176 case/backend executions, 352 launches and 14,336 exact output words**. Four hosts changed; all 108 nonhost artifacts remained identical.`

`The full suite at clean `c9cf9ba` passed all **1,448 tests**, with zero failures, errors or skips in 589.248 seconds. Source remained stable; the earlier failed suite is retained.`

An independent review also records an inherited, separate limit: the random
branch's `int` mismatch counter can overflow above `INT_MAX` mismatches if
very large allocations succeed. Bounded fixtures use `size_t` and are not
affected. That follow-up must preserve the established random-path output
contract; it is not a numerical qualification of enormous matrix shapes.

## Provenance to retain with a replay

The packet records the clean commit/tree and submodule pins; source, fixture,
profile and validator/helper snapshots; generated C++/Verilog headers and
reproduction checks; independent runtime, backend, host and kernel compiler
records; each command's argv, environment, exit, log hash and resource result;
and binary identities before and after execution. The RTL Verilator record
and native-path audit are necessary in addition to its C++ runtime shim.

The toolchain pin is `v3.0.2`. Observed tools were Clang 20.1.8 from Vortex LLVM
revision `f44a6bb2af4c62847585305bbdc760fbe0e3645f`, RISC-V GCC 12.2.0,
GNU host G++ 11.3.0, GNU Make 4.4.1 and Verilator 5.050. The packet retains
executable hashes and the version strings, including the RISC-V GCC bundle's
`g2ee5e430018-dirty` suffix. Reused `softfloat.a`, `libramulator.so` and
`libramulator-vortex.so` have matching before/after hashes. The runner neither
downloads nor rebuilds those dependencies. Hashes identify retained inputs;
they are not complete attestation of every system header, compiler support
file or dynamically loaded library.

## Reproduce from a clean source checkout

Use the tested revision, pinned tools and prepared dependency libraries. From
the source root, first verify the independent data without rewriting it:

```sh
python3 ci/project/p02_fixture_oracle.py --check
python3 ci/project/p02_layout_fixture_oracle.py --check
python3 ci/project/p02_wmma_numerical_fixture_oracle.py --check
python3 ci/project/p02_wmma_fixtures.py --check
```

### Full ordinary WMMA matrix

Replace the absolute tool/directory paths below. Work and output directories
must **not exist**, must have existing parents, and must not overlap each other,
the source or tools. Use simple absolute paths without spaces. The runner
creates a fresh generated build tree for each backend/format, supplies
`--xlen=64 --profile=p02-tfr`, and applies matching `ITYPE`, `OTYPE=fp32` and
`KUNROLL=1` application flags. Do not reuse incompatible build trees.

```sh
P02_SOURCE="$(pwd)"
P02_TOOLS=/absolute/path/to/pinned-tools
P02_HOST_BIN=/absolute/path/to/pinned-host-bin
P02_VERILATOR="$P02_TOOLS/verilator"
P02_WORK=/absolute/path/to/new-p02-matrix-builds
P02_OUTPUT=/absolute/path/to/new-p02-matrix-packet

python3 "$P02_SOURCE/ci/project/p02_matrix.py" run \
  --source-dir "$P02_SOURCE" --tools-dir "$P02_TOOLS" \
  --host-bin "$P02_HOST_BIN" --verilator "$P02_VERILATOR" \
  --work-dir "$P02_WORK" --output "$P02_OUTPUT" \
  --jobs 2 --iterations 2 --timeout-seconds 1800 --run-timeout-seconds 180
```

Omit selection filters and `--development` for qualification. Development mode
permits selected cases and dirty source and is not a substitute for the full
clean run. The generated application's invocation is `make run-simx` or
`make run-rtlsim` with `OPTS='-f CASE_ID -r 2'`; the runner records the full
command, matching flags and runtime path. It rejects absent/duplicate/malformed
result records and output/configuration/source drift.

Keep at least 15 GiB free, at least 6 GiB available memory at entry, and no more
than two compiler workers. Recorded limits are 1,800 seconds per build,
120 seconds per configure, 180 seconds per case command, 6 GiB sampled
process-group RSS and 16 MiB per command log. These are polled budgets, not
hard cgroup quotas; brief peaks can escape sampling. Debug and waveforms remain
disabled. Review `report.json`, raw logs, snapshots and independent results;
`outcome: pass` deliberately leaves `acceptance_claimed` and phase completion
false.

### Separate API rejection matrix

Run after the processor builds, using a **new RV64 build with an empty
profile** and a new, nonexistent results directory. Each case supplies its own
configuration, so the ordinary profile must not leak into this matrix.

```sh
P02_API_BUILD=/absolute/path/to/new-p02-api-build
P02_API_OUTPUT=/absolute/path/to/new-p02-api-results
mkdir "$P02_API_BUILD"
(cd "$P02_API_BUILD" && LC_ALL=C PYTHONDONTWRITEBYTECODE=1 \
  "$P02_SOURCE/configure" --xlen=64 --profile= \
  --tooldir="$P02_TOOLS" --osversion=ubuntu/focal)
(cd "$P02_API_BUILD" && LC_ALL=C PYTHONDONTWRITEBYTECODE=1 \
  python3 "$P02_SOURCE/ci/project/p02_api_compile.py" \
  --build-dir "$P02_API_BUILD" --tools-dir "$P02_TOOLS" \
  --output "$P02_API_OUTPUT")
```

The offline project suite is separately reproduced from the source root with
`python3 -m unittest discover -s ci/project -p 'test_*.py'`, followed by
`python3 ci/project/check_project.py`. It validates tooling and host guards;
its pass count must not be counted as processor launches.

## Remaining work and boundaries

The observed matrix covers compact complete tiles at 8×4×8, 8×4×16 and
16×8×16, initial `C=+0`, and K=8 or 16. It is not an arbitrary-shape/stride or
arbitrary-initial-C GEMM qualification. It supplies no WGMMA scheduling,
synchronization, descriptor/metadata, multiple-warp concurrency or backpressure
result. API compilation and earlier leaf enable stalls do not close P02-A03.

| Check | Result |
|---|---|
| Final offline suite | 1,448 passed; zero failures/errors/skips at `c9cf9ba` |
| Final host replay | 352 launches and 14,336 exact words passed; original backends retained |
| Local catalog recovery | Three RV64 representatives passed their unchanged tolerance checks |
| Hosted validation | Governance passed; source CI observation is in the separate [CI recovery record](evidence/p02-wmma/ci-recovery.json) |

Continue **the same P02-T02 task** with a bounded WGMMA test matrix
for synchronization, metadata, multiple warps and backpressure, together with
applicable model-parity evidence or explicitly reviewed applicability limits.
A parity applicability limit does not waive those correctness tests. Keep
P02 `in_progress`, P03 `not_started`, P01-A03 blocked and the P07 dependency
intact until their own obligations are met.

The next implementation is specified in the [WGMMA validation plan](p02-wgmma-validation-plan.md). Its candidate configurations and directed witnesses are plans, with no new A03 execution claim.
