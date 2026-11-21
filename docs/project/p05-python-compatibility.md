# P05 Python compatibility and reproduction v1

This matrix describes `vortex-ai==0.1.0`, binding API 1, and the
[implemented contract](../designs/python_binding_v1.md). It separates the
implemented surface from qualified execution. The recorded local host is
CPython **3.12.14**, GCC/G++ **14.2.0**, Linux x86_64, and glibc **2.41**.
An actual clean unbound sdist → wheel → fresh-venv import passed at binding
source SHA-256 `7a724e5b309ff714cf0b89df32518d1d6b09ac42692fc8fc96e6c90deefef6a3`.
That retained W04 result predates the current compiler staging, loader path,
and native state hardening. This run and the injected-runtime checks provide
host development evidence;
**final bound native installed qualification and hosted CI remain pending**.
An implemented workflow or a passing host-only check does not establish those
results. Live phase state and accepted records remain in [status](status.md)
and [roadmap.json](roadmap.json).

## Compatibility matrix

| Surface | Implemented boundary | Evidence/limit |
|---|---|---|
| Interpreter | Linux CPython 3.12 with the GIL, main interpreter | Local 3.12.14 observed; no other Python/platform qualification |
| Host compiler/build | C++17 CPython C API; GCC/G++ 14.2.0 observed | Platform-specific `cp312` wheel; no ABI3 or manylinux claim |
| Build tools | setuptools 84.2.1, wheel 0.48.0, packaging 26.3 | Exact [`pyproject.toml`](../../pyproject.toml) pins; preprovision for offline builds |
| Python dependencies | None at runtime | Core API has no NumPy or PyTorch adapter |
| Package modes | Unbound import/API checks; bound native execution | Empty bundle pin cannot open a session; bound execution needs the exact external bundle |
| Backend/profile | SimX, `p02_tfr_wmma_v1`, one FP16 or BF16 variant per wheel/process | Both fresh variant packets still required; Python RTL/XRT/hardware routes unqualified |
| Matmul | Three rank-two shapes in each format; copied A row-major/B column-major; FP32 output | Six implemented signatures; final installed/native comparison pending |
| Model | Ten frozen P04 cases, five per format | Fixed qualification executor; no arbitrary model/weight API |
| Ownership | Explicit copies/close, one live context, recoverable pending work | No zero-copy, concurrent queues, bounded destructor cancellation, or post-fork use |
| Framework | No implemented PyTorch custom operator | No tested PyTorch version; P05-A02 is the next unearned framework gate |
| Broader execution | No autograd/training, ONNX execution, general device backend, multi-device or CUDA binary compatibility | Separate contracts and qualification required |

The [package guide](../../python/README.md) provides clean source staging,
bound sdist → offline wheel → clean venv commands and an installed API example.
An sdist retains its source inventory and generated compiled-pin header; a bound
sdist additionally retains the exact manifest. Its offline rebuild needs host
Python/build tools/compiler, but neither the original bundle nor a GPU toolchain.
The external bundle is required again when executing the installed package.

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

## Required observations and remaining gates

For each format, both comparison routes run three frozen standalone matmul
cases twice and five frozen model cases twice, using the two prescribed poisons.
The installed route must observe six matmul launches plus 30 model launches;
the native reference side supplies the same 36-launch total. Both formats and
both routes together require 144 observed launches. These are required counts,
not a claim that this pending qualification has run.

The consumer checks exact raw output bits against immutable fixtures and the
independent native executables, actual native dispatch/argument bytes, all five
event/profile pairs per launch, completed cleanup, memory accounting, source and
bundle identities, and installed package/extension paths. It preserves raw
`P05_MATMUL` and `P05_MODEL` lines; model records use the existing P04 serializer.
No missing output, trace, or resource observation may be manufactured by a host
reference. Host ReLU/cast/assembly remain separately identified; no CPU matmul
fallback is available.

Retain `python-output/report.json`, `logs/`, the copied `native/` packet,
`packages/sdist/`, `packages/wheel/`, `artifacts/bundle/`, installed-file hashes,
and `artifacts/installed-observations.json`, including failed attempts. A
successful selected-format packet still has `acceptance_claimed: false`.
Independent external-contract review and a recorded acceptance decision remain
necessary under the [acceptance policy](acceptance.md).

P05-A01 still needs the complete bound installation/lifecycle evidence;
P05-A02 still needs the scoped PyTorch custom-op model and native-dispatch proof;
P05-A03 needs the tested framework compatibility matrix. This plain-Python slice
does not complete [P05](phases/p05-framework.md). SimX is simulation evidence,
not native processor RTL, physical FPGA/silicon, or physical performance proof.
[P01-A03 vendor XRT `hw_emu`](evidence/p01-xrt-blocked.json) remains blocked and
required before P07 completion. The inherited **267 → 283 DSP** area-gate failure
remains unresolved in the [P04 audit](p04-executor-audit.md); Python work does not
change that gate, its thresholds, or its goldens.
