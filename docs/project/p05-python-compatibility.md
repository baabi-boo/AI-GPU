# P05 Python compatibility and reproduction v1

This matrix describes `vortex-ai==0.1.0`, binding API 1, and the
[implemented contract](../designs/python_binding_v1.md). **P05-A01 is accepted**
for the declared copying Python interface and clean installed SimX execution at
[`e1420fd550f716df33a2556057b7086a03032cbe`](https://github.com/baabi-boo/AI-GPU/commit/e1420fd550f716df33a2556057b7086a03032cbe).
Both FP16 and BF16 installations passed independent numerical, dispatch and
provenance review. Their shared 22-input binding-source SHA-256 is
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.
The [acceptance record](evidence/p05-python/acceptance-binding.json) and
[execution packet](evidence/p05-python/README.md) define that exact tested scope.

Hosted qualification used Linux x86_64, GIL CPython **3.12.14**, G++ **11.4.0**,
Clang **20.1.8** and GNU Make **4.3**. The separate local unbound packaging check
used CPython **3.12.14**, GCC/G++ **14.2.0** and glibc **2.41**. Its eight real
packaging commands and the injected-runtime checks are
[host development evidence](evidence/p05-python/development/host-validation.md);
they do not substitute for the actual installed SimX executions.
The clean hosted governance suite passed 2,174 tests at the recorded commit.

**P05 is complete for its bounded inference scope.** The separate
[PyTorch compatibility matrix](p05-torch-compatibility.md) and
[P05-A02/A03 evidence packet](evidence/p05-torch-replay/README.md) accept
PyTorch 2.15.0+cpu / CPython 3.12.14 / Linux x86_64 / RV64 SimX at
`c6fb039e706e812b6b3f4d2a5db1828076fe50df`. That later framework result does
not relabel the historical plain-Python packages or add an adapter to them.
Live phase state and accepted records remain in [status](status.md) and
[roadmap.json](roadmap.json).

## Compatibility matrix

| Surface | Supported boundary | Qualified evidence or limit |
|---|---|---|
| Interpreter | Linux x86_64 CPython 3.12 with the GIL, main interpreter | Installed 3.12.14 qualified; no other Python/platform, free-threaded or subinterpreter qualification |
| Host compiler/build | C++17 CPython C API | Hosted bound builds use G++ 11.4.0; local unbound packaging uses GCC/G++ 14.2.0; platform-specific `cp312` wheels, no ABI3 or manylinux claim |
| Build tools | setuptools 84.2.1, wheel 0.48.0, packaging 26.3 | Exact [`pyproject.toml`](../../pyproject.toml) pins; preprovision for offline builds |
| Python dependencies | None at runtime | Core API has no NumPy or PyTorch adapter |
| Package modes | Unbound import/API checks; bound native execution | Empty bundle pin cannot open a session; bound execution needs the exact external bundle |
| Backend/profile | RV64 SimX, `p02_tfr_wmma_v1`, one FP16 or BF16 variant per wheel/process | Both fresh installed variants qualified; Python processor-RTL/XRT/hardware routes unqualified |
| Matmul | `(M,N,K)` = `(8,4,8)`, `(8,4,16)`, `(16,8,16)` in each format; copied A row-major/B column-major; FP32 output | All six signatures compared with the independent native executable, twice with distinct poisons; strides are packed **byte** strides |
| Model | Ten frozen P04 cases, five per format; batch 16, `16 → 8 → 4` MLP | All ten cases qualified; fixed executor, no arbitrary model/weight API |
| Ownership | Explicit copies/close, one live context, one outstanding matmul, recoverable pending work | Completed wait alone does not release ownership; no zero-copy, concurrent queues, bounded destructor cancellation, or post-fork use |
| Framework | No implemented PyTorch custom operator | No tested PyTorch version; scoped custom-op execution and framework compatibility remain the A02/A03 obligations |
| Broader execution | No autograd/training, ONNX execution, general device backend, multi-device or CUDA binary compatibility | Separate contracts and qualification required |

The [package guide](../../python/README.md) provides clean source staging,
bound sdist → offline wheel → clean venv commands and an installed API example.
An sdist retains its source inventory and generated compiled-pin header; a bound
sdist additionally retains the exact manifest. Its offline rebuild needs host
Python/build tools/compiler, but neither the original bundle nor a GPU toolchain.
The external bundle is required again when executing the installed package.

## Installation and portability limits

The hosted bound sdist → offline wheel → fresh copied-interpreter venv path
passed for both formats. Each installed package resolves outside the source
checkout and loads the five identified project libraries. The actual hosted
offline-wheel command compiles two fresh groups of six translation units and
links twice. The local W06 unbound wheel command compiled one group and linked
once; those distinct command paths must not be reported as one observation.

The hosted extension retains
`RUNPATH=/opt/hostedtoolcache/Python/3.12.14/x64/lib`, while `libsimx.so` retains
its original Ramulator search paths. Compatible host Python and system ELF
libraries remain prerequisites. This qualification does not establish an
arbitrary-host or manylinux wheel, a complete archived operating-system runtime,
or reproducible compilation of every transitive dependency. Keep the
[dependency notices](evidence/p05-python/THIRD_PARTY_NOTICES.md) with the retained
archives when redistributing the evidence packet.

The original archives also passed a
[relocated data replay](evidence/p05-python/relocated-replay.json) through all
three independent auditors. Follow the
[replay instructions](evidence/p05-python/reviews/README.md#relocated-data-replay)
to inspect them without executing downloaded binaries. A fresh native/package
execution uses the separate two-stage procedure below.

## Two top-level qualification stages

Use a clean, pinned source checkout with its required submodules/dependencies,
the provisioned native toolchain, and the exact Python build-tool pins. Check
the [resource budget](developer-guide.md) before building. All four work/output
directories below must be fresh, separate, outside source/tools, and under an
existing parent. Runner roots use only ASCII letters/digits and `/_.+-`, with
no symlink traversal. Keep the completed native build and output intact for stage 2.
Run these commands sequentially from the selected source root; do not call P04
through an imported P05 runner or nest their process-group monitors.

```sh
set -eu
P05_SOURCE="$PWD"
P05_TOOLS=/absolute/provisioned/tools
P05_RUN=/absolute/new/p05-fp16
P05_FORMAT=fp16
mkdir "$P05_RUN"

python3.12 "$P05_SOURCE/ci/project/p04_execute.py" run \
  --source-dir "$P05_SOURCE" --tools-dir "$P05_TOOLS" \
  --work-dir "$P05_RUN/native-work" --output "$P05_RUN/native-output" \
  --backend simx --format "$P05_FORMAT" --iterations 2 --jobs 2 \
  --timeout-seconds 1800 --run-timeout-seconds 180

python3.12 "$P05_SOURCE/ci/project/p05_execute.py" run \
  --source-dir "$P05_SOURCE" --tools-dir "$P05_TOOLS" \
  --native-build "$P05_RUN/native-work/simx-$P05_FORMAT" \
  --native-output "$P05_RUN/native-output" \
  --work-dir "$P05_RUN/python-work" --output "$P05_RUN/python-output" \
  --format "$P05_FORMAT" --jobs 2 \
  --timeout-seconds 1800 --run-timeout-seconds 180
```

Repeat both stages with `P05_FORMAT=bf16` and a new `P05_RUN` directory. The
source and selected tool files must remain unchanged between stages.
P05 requires the P04 report's normalized `source`, `tools`, `host_bin`, and
`verilator` paths to equal its own, including an omitted `host_bin`. Repeat any
`--host-bin` and `--verilator` selection in both invocations. The default
Verilator root is `TOOLS/verilator`; SimX records this path without executing it.
`--native-build` is the generated `simx-FORMAT` directory, not its parent;
`--native-output` is the completed P04
packet containing `report.json`. P05 has no `--backend` or `--development` option.
The [P05 workflow](../../.github/workflows/p05-python.yml) uses this same split.

Stage 2 revalidates and retains the original P04 packet/live build, prepares the
exact bundle, and builds/runs the unchanged native matmul comparison path. It
stages package sources outside the checkout, creates a bound sdist, rebuilds a
wheel offline without `VORTEX_AI_BUNDLE`, and installs it in a fresh venv. It
copies [`p05_installed_check.py`](../../ci/project/p05_installed_check.py) outside
the checkout and invokes the installed launcher, equivalent to:

```sh
VENV=/absolute/fresh/venv
BUNDLE=/absolute/qualified/bundle
SCRIPT=/absolute/installed-check/p05_installed_check.py
REQUEST=/absolute/installed-check/request.json
OBSERVATIONS=/absolute/installed-check/observations.json
"$VENV/bin/python" -I -B -m vortex_ai.launch --bundle "$BUNDLE" -- \
  "$SCRIPT" --request "$REQUEST" --output "$OBSERVATIONS"
```

The runner creates and validates that exact request; a hand-written request is
not a substitute for native provenance. The parent must have no nonempty loader
override. The launcher starts a child with only the verified canonical bundle
library directory on `LD_LIBRARY_PATH`. Native code independently checks its
compiled receipt/artifact pins before creating a context.

## Qualified observations and remaining gates

For each format, both comparison routes run three frozen standalone matmul
cases twice and five frozen model cases twice, using the two prescribed poisons.
The installed route observed six matmul launches plus 30 model launches;
the native comparison side supplies the same 36-launch total. Both formats and
both routes together passed **144 observed launches**: 72 through Python and
72 through the native executables. The copied original native packet identifies
the same native executions and is not added to those totals.

The consumer checks exact raw output bits against immutable fixtures and the
independent native executables, actual native dispatch/argument bytes, five
event/profile pairs per installed launch and per native model launch, completed
cleanup, memory accounting, source and bundle identities, and installed
package/extension paths. It preserves raw
`P05_MATMUL` and `P05_MODEL` lines; model records use the existing P04 serializer.
No missing output, trace, or resource observation may be manufactured by a host
reference. Host ReLU/cast/assembly remain separately identified; no CPU matmul
fallback is available.

The twelve standalone native comparison launches are unprofiled. The other
132 launches account for **660 queried event/profile pairs**: 360 Python and
300 native. Host steady-clock service, wait and advance intervals overlap;
they are not additive physical device latency or a speedup measurement.

Retain `python-output/report.json`, `logs/`, the copied `native/` packet,
`packages/sdist/`, `packages/wheel/`, `artifacts/bundle/`, installed-file hashes,
and `artifacts/installed-observations.json`, including failed attempts. A
successful selected-format packet still has `acceptance_claimed: false`.
The runner does not grant acceptance itself. The independent full-matrix and
lifecycle reviews support the separate
[P05-A01 decision](evidence/p05-python/acceptance-binding.json) under the
[acceptance policy](acceptance.md). Earlier failed development runs remain in
the linked host-validation history.

P05-A01 accepts this bounded binding/installation scope. The separate
[P05-A02 execution](evidence/p05-torch-replay/acceptance-torch.json) and
[P05-A03 compatibility](evidence/p05-torch-replay/acceptance-compatibility.json)
decisions complete [P05](phases/p05-framework.md) for the documented framework
scope; this historical plain-Python slice supplies no framework proof by itself.
SimX remains simulation evidence, with no native processor RTL, physical
FPGA/silicon or physical performance qualification for the Python route.
[P01-A03 vendor XRT `hw_emu`](evidence/p01-xrt-blocked.json) remains blocked and
required before P07 completion. The inherited **267 → 283 DSP** area-gate failure
remains unresolved in the [P04 audit](p04-executor-audit.md); Python work does not
change that gate, its thresholds, or its goldens.
