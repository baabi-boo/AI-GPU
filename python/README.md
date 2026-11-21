# Vortex AI Python binding

`vortex-ai==0.1.0` exposes binding API **1** as `vortex_ai`, with a C++17 CPython
extension wrapping the existing managed matmul and frozen P04 model owners.
The implemented target is Linux CPython 3.12 with the GIL. The recorded local
host is CPython **3.12.14**, GCC/G++ **14.2.0**, Linux x86_64, glibc **2.41**.
Build dependencies are pinned to setuptools **84.2.1**, wheel **0.48.0**, and
packaging **26.3**; there are no Python runtime dependencies. Wheels are
platform-specific `cp312`, with no ABI3 or manylinux claim.

The [versioned contract](../docs/designs/python_binding_v1.md) specifies exact
representations, ownership, errors, and supported shapes. The
[compatibility and qualification guide](../docs/project/p05-python-compatibility.md)
records pending bound native/CI qualification and the separate P04 → P05 commands.
Packaging/import or injected host tests do not qualify native execution.
PyTorch custom operators and full P05 acceptance remain unearned; this package
has no CPU matmul fallback, general model loader, autograd, or CUDA compatibility.

## Package identity and native startup

Import does not load a Vortex runtime, install tools, or compile kernels.
`build_info()` loads only the extension and returns `binding_api`,
`bundle_sha256`, and `source_sha256`. An empty bundle hash identifies an
**unbound** package: import/host checks work, but session creation fails.
A bound wheel accepts only the exact canonical manifest and six native artifacts
embedded in its compiled pin. Callers cannot override provenance or module bytes.
Use a separate venv and fresh process for each SimX FP16/BF16 wheel/bundle.

Run installed scripts through the launcher so the native dependency path is set
before the child interpreter starts:

```sh
P05_VENV=/absolute/installed/venv
P05_BUNDLE=/absolute/qualified/bundle
"$P05_VENV/bin/python" -I -B -m vortex_ai.launch --bundle "$P05_BUNDLE" -- \
  /absolute/example.py "$P05_BUNDLE"
```

The parent must have no nonempty `LD_PRELOAD`, `LD_AUDIT`, or `LD_LIBRARY_PATH`,
and no conflicting `VORTEX_DRIVER`. The launcher validates the wheel pin and
bundle, then runs the same interpreter with `-I -B`, `VORTEX_DRIVER=simx`, and
`LD_LIBRARY_PATH` exactly the canonical `BUNDLE/lib`. That directory must contain
only `libramulator.so`, `libramulator-vortex.so`, `libvortex.so`, `libsimx.so`, and
`libvortex-simx.so`, all regular nonsymlink files. Native code verifies the pin
and all artifacts itself and checks loaded project-library paths. It retains
the selected runtime for process life. Compatible system ELF libraries are
still required; the launcher is not a process/filesystem sandbox.

Use a canonical absolute bundle root without symlink components or `:`, `;`,
`$`, ASCII controls (0–31 and 127). Native paths must be shorter than 4096 UTF-8
bytes; for relative inputs the current directory is included in those checks.

## Clean staged sdist and offline wheel

Provision the pinned build dependencies and inventoried host compiler first.
The package build does not create or qualify a GPU bundle. Use the two-stage
runner in the qualification guide to obtain one, or prepare a bundle from an
already completed clean native P04 packet and its still-present build:

```sh
python3.12 ci/project/p05_bundle.py --source-dir "$PWD" \
  --build-dir /absolute/native-work/simx-fp16 \
  --native-output /absolute/native-output --format fp16 \
  --destination /absolute/new/bundle
```

From that same clean, unchanged source root, stage only the package inventory
and build a bound sdist. Replace the absolute paths; the output directory must
be new and outside the checkout. Use a separate output directory for each pin
because sdist archive names share the package name/version.

```sh
set -eu
P05_SOURCE="$PWD"
P05_BUNDLE=/absolute/qualified/bundle
P05_OUT=/absolute/new/package-run
mkdir "$P05_OUT"
python3.12 -B - "$P05_SOURCE" "$P05_OUT/source" <<'PY'
from pathlib import Path
import runpy
import shutil
import sys
source, stage = map(Path, sys.argv[1:])
paths = runpy.run_path(str(source / "python/vortex_ai/_bundle.py"))["SOURCE_PATHS"]
stage.mkdir()
for name in (*paths, "LICENSE", "python/README.md"):
    target = stage / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / name, target)
PY
mkdir "$P05_OUT/sdist" "$P05_OUT/unpacked" "$P05_OUT/wheel"
(
  cd "$P05_OUT/source"
  VORTEX_AI_BUNDLE="$P05_BUNDLE" python3.12 -B -c \
    'import sys; from setuptools.build_meta import build_sdist; print(build_sdist(sys.argv[1]))' \
    "$P05_OUT/sdist"
)
tar -xzf "$P05_OUT/sdist/vortex_ai-0.1.0.tar.gz" -C "$P05_OUT/unpacked"
env -u VORTEX_AI_BUNDLE CC=gcc CXX=g++ python3.12 -m pip --isolated wheel \
  --no-index --no-deps --no-build-isolation --no-cache-dir \
  --wheel-dir "$P05_OUT/wheel" "$P05_OUT/unpacked/vortex_ai-0.1.0"
python3.12 -m venv --copies "$P05_OUT/venv"
"$P05_OUT/venv/bin/python" -I -m pip --isolated install \
  --no-index --no-deps --no-compile "$P05_OUT"/wheel/*.whl
"$P05_OUT/venv/bin/python" -I -c \
  'import vortex_ai; print(vortex_ai.__file__); print(vortex_ai.build_info())'
```

`--no-build-isolation` uses the preprovisioned exact build tools; an isolated
offline build needs their local distributions too. For an unbound sdist, replace
the sdist command's `VORTEX_AI_BUNDLE=...` prefix with
`env -u VORTEX_AI_BUNDLE`. Keep bound and unbound source stages separate;
an already prepared sdist cannot be rebound through an environment variable.

The generated `python/p05_build/` in the sdist retains `p05_build_config.h`,
`source_inventory.json`, and, for bound builds, exact `manifest.json` bytes.
Normal builds do not rewrite tracked source. The archive excludes native
libraries, kernels, generated GPU configuration, and unrelated repository files.
Rebuilding it needs no Git checkout, original bundle, RISC-V compiler, or
simulator. Changed sources/configuration or replacement pins fail explicitly.
Bound wheel filenames include build tag `1` plus the full bundle SHA-256.
Wheel building recopies verified Python sources and rebuilds the extension;
stale/extra payloads and `--skip-build` are rejected. The bundle remains external
and is needed for execution, even though the offline wheel build needs no bundle.

Each extension build copies and verifies exactly the 22 inventoried inputs into
a fresh private directory under its build temporary directory. Its native project
sources, include paths, and header dependencies all use that staged tree, with
the generated receipt directory first in the project include search. Unlisted
headers in the original checkout cannot shadow the pinned native inputs.

## Installed copying example

Save this as `/absolute/example.py` outside the checkout, and invoke it through
the launcher above, using the newly installed venv and matching bundle. Each
wait/close below uses the default 100 ms **per native wait** and retries until
completion; the example imposes no aggregate deadline.

```python
import sys
from vortex_ai import Session, Tensor

def close_complete(owner):
    while True:
        status = owner.close()
        if status.complete:
            status.raise_for_status(owner)
            return

session = Session.open(sys.argv[1])
dtype = session.info["format"]
a = Tensor(bytes(128), dtype=dtype, shape=(8, 8), layout="row_major",
           strides=(16, 2))
b = Tensor(bytes(64), dtype=dtype, shape=(8, 4), layout="column_major",
           strides=(2, 16))
operation = session.submit(a, b)
while not operation.wait().complete:
    pass
close_complete(operation)
print("matmul raw FP32 words:", operation.output_words())

model = session.model(dtype + "-seeded_dense")
while not model.advance().terminal:
    pass
close_complete(model)
model.status.raise_for_status(model)
print("model raw FP32 words:", model.output_words())
print("native model record:", model.record(iteration=0))
session.close().raise_for_status()
```

`Tensor` retains input storage; submission copies it into native ownership.
Input words are little-endian FP16/BF16, and output methods return independent
little-endian FP32 bytes or unsigned raw-word tuples. Only `(M,N,K)` values
`(8,4,8)`, `(8,4,16)`, and `(16,8,16)` are implemented. There is no implicit
float, layout, stride, byte-order, or dtype conversion.

Keep owners on errors: `session.pending_operations()` returns retained work
even if an interruption or allocation failure prevented normal return. Retry
bounded close while incomplete and inspect separate validation/primary/cleanup
codes. Context exit tries one bounded close and can raise while retaining work.
Destructors drain indefinitely; dropping references does not cancel execution.
Only one live SimX context is allowed, and a completed matmul wait still requires
completed explicit close before new work. Models suspend an idle matmul session;
later submission/memory queries resume it only after the model releases its
lease. Cleanup failure blocks new work in that process. See the versioned
contract for recovery and process restrictions.
