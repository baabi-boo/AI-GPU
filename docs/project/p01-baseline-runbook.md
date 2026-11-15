# Reproduce the P01 native baseline

This guide prepares and runs the frozen RV64 baseline. Commands are a recipe;
passing results belong in reviewed [evidence records](evidence/README.md).
[P01](phases/p01-baseline.md), [acceptance](acceptance.md) and
[status](status.md) define the current obligations and their disposition.

## 1. Freeze the checkout and execution budget

Use a clean checkout of `baabi-boo/AI-GPU`, with the exact source revision recorded
before building. For reproduction, use the `source_revision` in the reviewed
packet; for a new packet, record the chosen revision of `master`. The runner's
`--source` option can point to a separate immutable worktree while development
continues elsewhere. Keep the runner and matrix revisions as well as the GPU
source revision in the packet.

Choose absolute paths without spaces, shell metacharacters or symlink traversal.
The examples below require replacing `/absolute/dedicated/p01` with a directory
owned by this run. Tool, download-cache and result directories must be outside
the source tree. A build inside the checkout must be a top-level `build*`
directory. Result directories must be new; never reuse a previous run's output.

```sh
AI_GPU_WORK=/absolute/dedicated/p01
AI_GPU_SOURCE="$AI_GPU_WORK/source"
AI_GPU_TOOLS="$AI_GPU_WORK/tools-v3.0.2"
AI_GPU_CACHE="$AI_GPU_WORK/download-cache"
AI_GPU_SETUP="$AI_GPU_WORK/setup-logs"
AI_GPU_HOST_BIN="$AI_GPU_WORK/host-gcc11/usr/bin"
AI_GPU_BUILD="$AI_GPU_SOURCE/build64-p01-gcc11"
mkdir -p "$AI_GPU_WORK" "$AI_GPU_SETUP"
git clone --depth 1 --branch master https://github.com/baabi-boo/AI-GPU.git "$AI_GPU_SOURCE"
cd "$AI_GPU_SOURCE"
git rev-parse HEAD HEAD^{tree}
git status --porcelain
git submodule update --init --recursive --depth 1
git submodule status --recursive
```

Do not use `git submodule update --remote`. Preserve the resolved recursive
gitlinks, all command exits and source cleanliness. Generated third-party build
outputs are ignored by their repositories; changes to tracked inputs still
block the baseline.

The default execution budget is **two compile workers**, **15 GiB free-disk
reserve**, **6 GiB sampled process-group RSS**, **16 MiB per command log**, and
**1,800 seconds per runner command**. Inspect `df -h` and `free -h` before setup
and during dependency builds. These are monitored budgets, not hard quotas.
Host `MemAvailable` does not prove a container's memory limit; record unavailable
cgroup information explicitly. Keep debug/VCD/SAIF/performance tracing disabled.
Whole-GPU synthesis or Beacon is outside this recipe.

## 2. Prepare the minimal tools

The host needs Git, Python with the runner's standard-library requirements,
GNU Make, a compatible C/C++ compiler, and CMake for Ramulator. Its host code
requires C++20. Follow the [installation guide](../install_vortex.md) for host
headers and libraries. Direct baseline execution does not require pytest,
OpenCL, HIP, graphics, gem5, FireSim, synthesis tools or an FPGA. The separate
catalog pytest harness needs its own pytest/PyYAML environment.

Record host compiler and CMake versions. **Compiler availability alone is not a
compatibility pass.** An initial Debian GCC 14.2 build failed with
`-Werror=dangling-reference` in the pinned spdlog/fmt dependency while building
SimX. Preserve that failure; it occurred before numerical execution. The
subsequent host compiler smoke and first 64×64×64 FP16 GEMM on SimX passed with
Debian GCC **11.3.0-12**, including the inherited CPU-reference check with zero
numerical errors. This qualifies that observed case, not the complete matrix.
Keep compiler warnings, inherited tolerances and toolchain pins unchanged.

The observed GCC 11 setup extracted six Debian bookworm packages user-locally:
`cpp-11`, `g++-11`, `gcc-11`, `gcc-11-base`, `libgcc-11-dev` and
`libstdc++-11-dev`, all version `11.3.0-12`. Their combined compressed size is
**41,926,820 bytes** (about 41.9 MB). The retained `host-packages.json` records
the package-index identity, filenames, sizes and verified SHA-256 hashes.
Extraction does not install or register system packages. Check the required
host libraries separately; a package archive alone does not establish them.

Provision a verified GNU 11 host compiler before native build commands. Set
`AI_GPU_HOST_BIN` to its directory, with `gcc`, `g++` and `cpp` resolving to the
verified versioned executables. For the user-local layout above these are links
to `gcc-11`, `g++-11` and `cpp-11`. Put this directory first on `PATH` before
configuration, dependency builds, planning and execution:

```sh
export PATH="$AI_GPU_HOST_BIN:$PATH"
export CCACHE_DISABLE=1
export OBJCACHE=''
command -v gcc g++ cpp
gcc --version > "$AI_GPU_SETUP/host-gcc-version.txt"
g++ --version > "$AI_GPU_SETUP/host-gxx-version.txt"
cmake --version > "$AI_GPU_SETUP/host-cmake-version.txt"
```

Check that the selected executables and versions match the provisioning record.
The native runtime and nested Verilator make both resolve `g++` through `PATH`;
setting a compiler for only one build step does not select it for the other.
Use a fresh generated build directory after changing compiler identity, and
retain the actual compiler used to produce each reused dependency library.

The first successful FP16 SimX execution had this compiler provenance:

| Build stage | Observed compiler |
|---|---|
| Initial Ramulator and SoftFloat dependency libraries | Host Debian GCC 14.2 |
| Native simulator, runtime and application host code | Host Debian GCC 11.3.0-12 |
| RISC-V device kernel | Pinned RISC-V GNU 12.2.0 and Vortex LLVM 20.1.8 |

The GNU 11 recipe selects that compiler from setup onward for a new run. It
does not relabel the existing dependency libraries as GNU 11 builds. The
prebuilt Verilator identifies version 5.050 and its own producing compiler as
Ubuntu GCC 11.4.0; that is separate from the compiler selected for this run's
generated simulator code.

The [toolchain lock](../../ci/project/p01_toolchain.lock.json) fixes Vortex
`v3.0.2` to commit `e3db4bcdf819a17f618ad9fc2472f8f7dea3192b` of
`vortexgpgpu/vortex-toolchain-prebuilt`, with the `ubuntu/focal` bundle family.
It contains RISC-V GNU RV64, Vortex LLVM, Verilator, libc64 and libcrt64:
18 archive parts totalling 720,873,529 compressed bytes, about 688 MiB.
Selecting that bundle on another Linux distribution does not qualify that host;
the actual executable/library identities and successful build must be retained.

```sh
python3 ci/project/baseline_bootstrap.py install \
  --tool-dir "$AI_GPU_TOOLS" --cache-dir "$AI_GPU_CACHE" \
  --manifest ci/project/p01_toolchain.lock.json --min-free-gib 15 \
  > "$AI_GPU_SETUP/toolchain-install.json"
python3 ci/project/baseline_bootstrap.py verify \
  --tool-dir "$AI_GPU_TOOLS" --manifest ci/project/p01_toolchain.lock.json \
  > "$AI_GPU_SETUP/toolchain-verify.json"
```

Check both exits before proceeding. Bootstrap and inventory bind the supplied
manifest to the reviewed canonical lock digest
`f7638b92912ee8b61640d32431814e676950124b9455649f16400cb54b2a4eb3`;
matching repository, tag and commit labels alone is insufficient. Installation
validates part sizes, Git blob identities and SHA-256 hashes, then writes an
installation receipt tied to that manifest. Existing completed installations
are verified; partial or unreceipted installations are
preserved and refused. The tool never deletes an existing installation to retry.
Receipt verification covers its recorded primary executables/libraries, not
every shared-library file. An earlier independently provisioned tool directory
must retain its own provenance; do not fabricate this installer's receipt for it.

## 3. Build the source dependencies with two workers

Run from the generated build directory. Configure also identifies the dedicated
tool path; it does not install dependencies or qualify a workload.

```sh
mkdir -p "$AI_GPU_BUILD"
cd "$AI_GPU_BUILD"
../configure --xlen=64 --osversion=ubuntu/focal --tooldir="$AI_GPU_TOOLS"
cmake -S ../third_party/ramulator -B ../third_party/ramulator/build \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  > "$AI_GPU_SETUP/ramulator-configure.log" 2>&1
timeout --kill-after=5s 1200 cmake --build ../third_party/ramulator/build --parallel 2 \
  > "$AI_GPU_SETUP/ramulator-build.log" 2>&1
make -j2 -C ../third_party softfloat ramulator \
  > "$AI_GPU_SETUP/third-party-build.log" 2>&1
```

Stop at any failure. Prebuilding Ramulator explicitly is necessary because the
inherited `third_party/Makefile` invokes its missing-library build with `-j4`;
an outer `make -j2` does not constrain that nested command. Once the library
exists, the final command builds SoftFloat and the required Vortex Ramulator
extension without triggering that four-worker build. Monitor setup resources
separately: these manual dependency commands do not automatically use the
baseline runner's RSS/log/disk monitoring.

Ramulator's pinned source fetches three additional repositories during CMake
configuration. Record and compare their resolved commits before accepting the
build; a moving tag is not an immutable identity.

| Dependency in `third_party/ramulator/ext/` | CMake tag | Resolved baseline commit |
|---|---|---|
| `yaml-cpp` | `yaml-cpp-0.7.0` | `0579ae3d976091d7d664aa9d2527e0d0cff25763` |
| `spdlog` | `v1.11.0` | `ad0e89cbfb4d0c1ce4d097e134eb7be67baebb36` |
| `argparse` | `v2.9` | `997da9255618311d1fcb0135ce86022729d1f1cb` |

For example, from the source root, `git -C
third_party/ramulator/ext/spdlog rev-parse HEAD` observes the spdlog identity.
Retain equivalent observations for all three; stop and investigate a mismatch.

## 4. Inspect the plan, then run the frozen cases

Return to the checkout containing the versioned baseline tools. `plan` is
read-only and prints prerequisites, identities, selection and blockers. It does
not build, install, execute a GPU kernel or accept a phase gate.

```sh
cd "$AI_GPU_SOURCE"
python3 ci/project/baseline.py plan \
  --source "$AI_GPU_SOURCE" --build-dir "$AI_GPU_BUILD" \
  --tool-dir "$AI_GPU_TOOLS" --bundle-manifest ci/project/p01_toolchain.lock.json \
  > "$AI_GPU_SETUP/native-plan.json"
python3 ci/project/baseline.py run \
  --source "$AI_GPU_SOURCE" --build-dir "$AI_GPU_BUILD" \
  --tool-dir "$AI_GPU_TOOLS" --bundle-manifest ci/project/p01_toolchain.lock.json \
  --output "$AI_GPU_WORK/native-run-01" \
  --jobs 2 --timeout-seconds 1800 --min-free-gib 15 --max-log-mib 16 --max-rss-gib 6
```

The runner reconfigures the build, builds the kernel and runtime libraries, then
uses generated `ci/blackbox.sh` commands sequentially. Application and backend
configuration stamps, generated files and binaries are recorded. Inherited
configuration/profile/debug/performance environment overrides are removed.
The runner also fixes `CCACHE_DISABLE=1` and `OBJCACHE=''`, so Verilator compiles
directly. The first processor RTL attempt failed before workload execution
because the prebuilt Verilator makefile selected an unavailable `ccache`.
Preserve that failed packet alongside any direct-compilation retry; disabling
cache use alone does not prove the RTL case passed.

Build validation compares 13 selected copied Makefiles, templates and helper
files with their source contents, and independently regenerates all four configuration
headers for byte comparison. File timestamps alone cannot establish freshness.
The runner rehashes built dependency libraries before launch and around each
case, checks source/build identities, and rejects changed or missing inputs.

Host identity reports record the selected `gcc`, `g++`, `make`, `ld`, `as`,
Python and optional CMake executables, their hashes and bounded version output.
They also hash the `cc1plus` frontend resolved by `g++`. The runner checks these
identities before execution and after a successful matrix. These observations
do not inventory every host header or shared library, or establish compiler
compatibility without actual compilation and workload results.

The [frozen matrix](../../ci/project/p01_baseline.json) has six cases: each row
below runs once with the `-simx` suffix and once with `-rtlsim`.

| Case prefix | Input/output | Arguments | Threads / warps / issue width |
|---|---|---|---|
| `gemm-fp16` | FP16 / FP32 | `-m 64 -n 64 -k 64` | 8 / 4 / 2 |
| `gemm-bf16` | BF16 / FP32 | `-m 64 -n 64 -k 64` | 16 / 4 / 1 |
| `attention-tf32` | TF32 / FP32 | `-N 32 -D 16 -c 8 -t 8` | 4 / 4 / 4 |

All cases use one cluster/core and explicitly select native TFR tensor and STD
scalar arithmetic for their RTL pairing. SimX remains software simulation.
`rtlsim`'s `SV_DPI` infrastructure flag alone does not identify its arithmetic
implementation; the resolved TCU/FPU selections must agree with the matrix.
Attention's small RTL case uses TF32, not FP16. These are bounded derivatives
of named catalog cases, including added native BF16 RTL coverage; the inherited
catalog entries remain unchanged.

Reference seed 50 and inherited tolerances remain fixed: GEMM uses relative
error strictly below 1% with exact zero pairs accepted; attention uses
`atol=rtol=0.001`. These checks establish only their declared normal-workload
scope, not P02 exceptional-value or arithmetic edge-case qualification.

For diagnosis, repeat `--case` with exact IDs, for example
`--case gemm-fp16-simx`. A selected subset is identified in the report and cannot
stand in for the complete six-case matrix. Never reduce case dimensions or
loosen a tolerance after observing a failure.

## 5. Retain failures and review acceptance separately

Each run retains `report.json`, its matrix, bounded raw command logs, sanitized
configuration copies and binary hashes. It also retains snapshots of the six
executing runner/helper files under `artifacts/tooling`, with hashes and separate
checkout metadata. This identifies the instrumentation even when `--source`
points to another GPU checkout. Keep both identities; a source revision alone
does not identify the runner. Earlier packets retain the checks performed by
their recorded runner version, not checks added later.

The report is checkpointed after each command/case. Exit zero alone is
insufficient: the reference success marker,
configuration and source identities must also pass. A failed command stops
later cases, which remain `not_run`. Timeout or resource stops preserve partial
evidence and terminate the monitored process group.

Use a **new output directory** for a retry and preserve the failed packet. Review
raw logs for machine paths before publishing; retain the original digest and
describe any deterministic path redaction. A run report is input to the
[evidence procedure](evidence/README.md), not automatic gate acceptance. Keep
source/tool identities, setup logs, dependency revisions, failure disposition
and independent review together. Simulation cycle counts do not establish
physical frequency, throughput, power or GPU product equivalence.

P01-A01 requires reviewed successful clean-build provenance. P01-A02 requires
the complete required native numerical results. **P01-A03 remains a separate
vendor XRT `hw_emu` obligation**, requiring an identified supported platform,
vendor tools and matching emulation artifacts; missing prerequisites are
`blocked`, never passed. The runner leaves `phase_complete` false.

An optional `--driver=xrt --target=xrtsim` smoke uses the repository's local XRT
shim and full AFU RTL without the vendor runtime. It also needs the UUID header
normally supplied by `uuid-dev`. A separately extracted header must retain its
source revision and content digest. The setup investigation retained
`libuuid/src/uuid.h` from util-linux v2.41 at commit
`caa26876bc75041833c9644491cc2670d623f750` with a `uuid-header.json` record;
this supplies a header for the local shim, not a vendor XRT installation.
Use a separate build and bounded execution, record
DMA/module-launch/completion/reference markers, and retain its XRT/AFU
stamps. This can add useful integration evidence, but it does not reproduce the
vendor `hw_emu` path, physical PCIe/coherency behavior, or all AXI backpressure
cases. Follow [verification](verification.md) and keep that distinction in the
report and the next-action handoff.
