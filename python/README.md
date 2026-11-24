# Vortex AI Python binding

`vortex-ai==0.1.0` exposes binding API **1** as `vortex_ai`, with a C++17 CPython
extension wrapping the existing managed matmul and frozen P04 model owners.
The historical copying-binding qualification targeted Linux x86_64 CPython
**3.12.14** with the GIL and main interpreter, using separate installed SimX
FP16 and BF16 bundles. That hosted qualification used G++ **11.4.0**,
Clang **20.1.8** and GNU Make **4.3**.
The separate local unbound packaging check used GCC/G++ **14.2.0** and glibc
**2.41**. Build dependencies are pinned to setuptools **84.2.1**, wheel **0.48.0**,
and packaging **26.3**; the core package declares no Python runtime
dependencies. Wheels are platform-specific `cp312`, with no ABI3 or manylinux
claim.

The [versioned contract](../docs/designs/python_binding_v1.md) specifies exact
representations, ownership, errors, and supported shapes. The
[compatibility and qualification guide](../docs/project/p05-python-compatibility.md)
records the separate P04 → P05 commands and
[accepted P05-A01 evidence](../docs/project/evidence/p05-python/acceptance-binding.json)
at source `e1420fd550f716df33a2556057b7086a03032cbe`. Both installed formats passed
native comparison, lifetime/error review and clean-install provenance checks.
Those historical packages share the 22-input binding-source SHA-256
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.
See the [execution packet](../docs/project/evidence/p05-python/README.md) for the
144 native/Python launches, 660 profile pairs and clean hosted 2,174-test result.
Host failure injection and unbound import checks remain separately scoped.

The current package adds the optional `vortex_ai.torch_ops` module and its
[eager custom-operator contract](../docs/designs/torch_custom_ops_v1.md).
`import vortex_ai` remains independent of PyTorch; importing the optional module
requires the separately installed **PyTorch 2.15.0+cpu** closure below. The
[framework compatibility matrix](../docs/project/p05-torch-compatibility.md)
separates implementation, host tests and the accepted installed SimX matrix at
`c6fb039e706e812b6b3f4d2a5db1828076fe50df`. The
[P05-A02 execution](../docs/project/evidence/p05-torch-replay/acceptance-torch.json)
and [P05-A03 compatibility](../docs/project/evidence/p05-torch-replay/acceptance-compatibility.json)
decisions complete P05 for the declared eager operators, six format/signature
combinations and fixed model on CPython 3.12.14 / Linux x86_64 / RV64 SimX.
The [replay handoff](../docs/project/p05-torch-replay-handoff.md) preserves exact
original identities and the limits of reviewing recorded execution.

Adding this module changes the current package inventory to **23 inputs**.
Build a fresh matching bundle, sdist and wheel; the historical 22-input packages
above do not contain the adapter. This package has no CPU matmul fallback,
general model loader, autograd, training, multi-device support or CUDA binary
compatibility.

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

The hosted extension records
`RUNPATH=/opt/hostedtoolcache/Python/3.12.14/x64/lib`; `libsimx.so` retains its
original Ramulator search paths. The installed checks establish the named
project-library closure in the recorded environment. They do not establish
arbitrary-host binary portability or eliminate compatible system-library and
Python prerequisites. Exact ELF observations and required redistribution
notices accompany the [retained archives](../docs/project/evidence/p05-python/THIRD_PARTY_NOTICES.md).

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

Each current extension build copies and verifies exactly the 23 inventoried inputs into
a fresh private directory under its build temporary directory. Its native project
sources, include paths, and header dependencies all use that staged tree, with
the generated receipt directory first in the project include search. Unlisted
headers in the original checkout cannot shadow the pinned native inputs.

The hosted qualification runner uses its recorded `setup.py build build_ext
bdist_wheel` command, which compiled two fresh groups of six translation units
and linked twice. The separate local W06 unbound pip-wheel command compiled
once. These results identify their respective command paths; the example above
is a usage recipe, not a claim of another executed qualification run.

For inspection without building or executing native code, the original archives
have passed a [fresh relocated replay](../docs/project/evidence/p05-python/relocated-replay.json).
The [data-replay instructions](../docs/project/evidence/p05-python/reviews/README.md#relocated-data-replay)
verify the exact archives and run the independent auditors. Keep the associated
dependency notices with those archives when redistributing them.

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
float, layout, stride, byte-order, or dtype conversion. `strides` counts **bytes**:
packed row-major uses `(2 * columns, 2)` and packed column-major
uses `(2, 2 * rows)`. Arbitrary strides, transposes and broadcasting are rejected.

Invalid Python types raise `TypeError`; unsupported dtype/shape/layout/stride
values raise `ValueError`, and integer or extent overflow raises `OverflowError`.
`BindingError` carries mapped native-status, ownership-state, cleanup or bundle
failures with the available owner and status details. Inspect returned statuses
and call `raise_for_status()` as in the example. Other exceptions, including
allocation failure or interruption, can propagate while work remains owned.
No error selects a CPU implementation or performs an implicit conversion.

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

## Optional PyTorch installation

Provision Linux x86_64 CPython **3.12.14**, with the GIL and main interpreter,
before using this recipe. The selected framework is exactly **2.15.0+cpu**.
Its eleven dependency wheels and hashes are frozen in the
[requirements lock](../ci/project/p05_torch_requirements.lock) and
[framework manifest](../ci/project/p05_torch_contract.json). The base binding
package does not install this optional dependency set automatically.

Use the newly built bound wheel from the current 23-input source inventory and
its exact matching bundle. The package-output directory below must contain
exactly that one wheel. Create a separate venv and use a fresh process for each
FP16/BF16 bundle. These are installation instructions; successful installation
alone does not earn framework qualification.

```sh
P05_TORCH_LOCK=/absolute/AI-GPU/ci/project/p05_torch_requirements.lock
P05_TORCH_WHEELS=/absolute/new/framework-wheels
P05_TORCH_PACKAGE=/absolute/new/package-run/wheel
P05_TORCH_VENV=/absolute/new/torch-venv
mkdir "$P05_TORCH_WHEELS"
python3.12 -I -B -m pip --isolated download \
  --disable-pip-version-check --no-cache-dir --only-binary=:all: \
  --no-deps --require-hashes \
  --index-url https://download.pytorch.org/whl/cpu \
  --extra-index-url https://pypi.org/simple \
  --dest "$P05_TORCH_WHEELS" -r "$P05_TORCH_LOCK"
python3.12 -I -B -m venv --copies "$P05_TORCH_VENV"
"$P05_TORCH_VENV/bin/python" -I -B -m pip --isolated install \
  --no-index --find-links "$P05_TORCH_WHEELS" --require-hashes --no-deps \
  --no-compile --no-cache-dir --disable-pip-version-check \
  -r "$P05_TORCH_LOCK"
"$P05_TORCH_VENV/bin/python" -I -B -m pip --isolated install \
  --no-index --no-deps --no-compile --no-cache-dir \
  --disable-pip-version-check "$P05_TORCH_PACKAGE"/*.whl
```

The network download prepares a local wheelhouse. Both installation commands
then run offline. The lock fixes the optional framework closure; the bound
wheel and launcher independently enforce the native bundle/source identity.
Keep the wheel's full manifest-derived build tag when copying it.

## Eager PyTorch example

Save the following successful-call example as `/absolute/torch_example.py`
outside the checkout. It invokes both registered operators, using the selected
bundle's format. `TorchSession` borrows the native session and supplies its
process-local token; closing the adapter does not close that native session.

```python
import sys
import torch
from vortex_ai import Session
from vortex_ai.torch_ops import TorchSession

session = Session.open(sys.argv[1])
adapter = TorchSession(session, timeout_seconds=30.0)
format_name = session.info["format"]
dtype = {"fp16": torch.float16, "bf16": torch.bfloat16}[format_name]

# M=8, N=4, K=8. B's caller-requested copy packs columns physically.
a = torch.zeros((8, 8), dtype=dtype, device="cpu")
b_row_major = torch.zeros((8, 4), dtype=dtype, device="cpu")
b = b_row_major.t().contiguous().t()
assert a.stride() == (8, 1)
assert b.stride() == (1, 8)
result = torch.ops.vortex_ai.matmul_v1(a, b, adapter.token, 0x7FC0DEAD)

# This executor owns frozen inputs and weights; it is not a model loader.
model_result = adapter.fixed_mlp(format_name + "-seeded_dense")
assert result.shape == (8, 4) and result.dtype == torch.float32
assert model_result.shape == (16, 4) and model_result.dtype == torch.float32
assert not session.pending_operations()
adapter.close()
session.close().raise_for_status()

# Both results retain independent CPU storage after native shutdown.
print("matmul:", result.shape, result.dtype, result.device)
print("fixed MLP:", model_result.shape, model_result.dtype, model_result.device)
```

Launch it with the framework venv and the bundle paired with its installed wheel:

```sh
P05_BUNDLE=/absolute/qualified/bundle
"$P05_TORCH_VENV/bin/python" -I -B -m vortex_ai.launch --bundle "$P05_BUNDLE" -- \
  /absolute/torch_example.py "$P05_BUNDLE"
```

PyTorch strides count **elements**, unlike the binding `Tensor` byte strides in
the earlier example. A must be row major `(K,1)` and B column major `(1,K)`;
both need offset zero and exactly their packed storage extent. The adapter
preserves FP16/BF16 bits and returns independent CPU FP32 results only after
successful native completion and explicit close. CPU tensors supply storage;
the declared matmul work goes through the native SimX owner.

The example shows the normal path. An application must keep `session` and
`adapter` alive when a call raises, including on interruption or allocation
failure. Inspect `session.pending_operations()` and explicitly retry the
retained operations' bounded wait, advance and close methods; the authoritative
owners can exist even when assignment of a returned operation failed. Inspect
all resulting status channels before detaching the adapter and closing the
native session. A timeout is not cancellation, and destructors may drain
indefinitely. The retry deadline is checked between native calls; it is not a
strict whole-call wall-clock limit.

If construction registers an adapter but interruption prevents assignment,
retry `TorchSession(session)`. The duplicate-attachment `BindingError.adapter`
identifies the existing adapter even if the native session now has pending
work or is closed. Complete any pending operation before detaching it; recovery
does not reopen a closed native session. A failed `Session.open` can retain its
native owner on the error;
close that owner before creating another session. An incompletely initialized
session cannot be attached to the adapter.

Use ordinary eager inference, `torch.no_grad()` or `torch.inference_mode()`
with non-differentiable inputs. Original reverse-gradient requests and forward
tangents are rejected, including under those contexts. Autocast, transforms,
graph capture and scripted execution are unqualified. Some higher-level APIs
evaluate ordinary eager work before entering a detectable transform; a later
exception therefore does not prove that no native work ran. See the
[matrix and failure boundaries](../docs/project/p05-torch-compatibility.md)
for exact tested paths and limitations.
