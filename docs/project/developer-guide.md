# Developer onboarding and resource policy

Start with [status](status.md), [backlog](backlog.md), [roadmap](../../ROADMAP.md)
and [AGENTS.md](../../AGENTS.md). This guide separates inexpensive project checks
from GPU execution. Commands below are instructions, **not evidence of a run**.
Completed work must carry the [evidence record](evidence/README.md) it earned.

## 1. Obtain the correct source

Use authorized access to the private target repository. Its default branch is
`master`; do not substitute the upstream Vortex repository or rename the branch.
For a new checkout:

```sh
git clone --branch master https://github.com/baabi-boo/AI-GPU.git
cd AI-GPU
git status --short
git rev-parse HEAD
git submodule status --recursive
```

For an existing checkout, inspect its remote identity, branch and local changes
before updating it. Preserve other contributors' work. Do not expose credentials
from remote URLs in logs. Create a task branch from the current target revision;
follow [CONTRIBUTING.md](../../CONTRIBUTING.md) for review and delivery.

## 2. Run the lightweight checks first

These commands run from the **source root** on Linux, with Python's standard
library and Git available. The unit suite also requires a native C++17 compiler
(`c++`, `g++` or `clang++` on `PATH`) with UBSan support and runtime libraries for
bounded tensor-oracle host tests. No RISC-V compiler, Verilator, initialized
submodules, vendor tools or FPGA is needed. The CI workflow defines its Python
version.

```sh
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py'
git diff --check
```

Preflight is read-only: it reports prerequisites, resource availability and asset
integrity; it never installs, builds or cleans. Use `--json` for machine-readable
output, `--root PATH` to inspect a different checkout, and `--min-free-gib N` only
after choosing a justified disk reserve. Governance preflight inventories host
compilers as optional and does not test C++17 or UBSan support; its success alone
does not establish readiness to run the full unit suite. These checks do not
establish GPU correctness or hardware readiness.

## 3. Choose an execution budget before downloading

| Work tier | Prerequisites to resolve | Budget and stop condition |
|---|---|---|
| Governance | Python, Git, Linux host with native C++17/UBSan, and this source tree | Small local checks and bounded host tests; at least 1 GiB free on temporary storage; no GPU downloads |
| Simulation / processor RTL | Supported Linux host, compiler/build dependencies, pinned tools, required submodules; Verilator for RTL | Inventory downloads, unpacked tools, objects, traces and available RAM before selecting cases |
| FPGA integration / physical FPGA | Vendor compiler/runtime, licensed tool access where required, exact platform/shell; authorized board access for hardware | Approve disk, RAM, jobs, runtime and output retention per target; stop when the reserve is threatened |
| ASIC analysis / realization | Explicit flow, libraries/PDK/IP access, compute budget and the separate human decisions in P10/P11 | No automatic foundry, IP, spending or manufacturing commitment |

Run the corresponding `--tier simulation`, `--tier fpga` or `--tier asic`
preflight before its work, then resolve its blockers. It is a prerequisite screen,
not a substitute for target-specific readiness review. Use `df -h .`, `free -h`
on Linux, and `du -sh` on explicitly selected build/tool directories to monitor
the actual resource budget. Do not publish machine-sensitive inventory details.

Start with one small catalog case and one build variant. Set a deliberate job
limit, but inspect nested builds too: [third_party/Makefile](../../third_party/Makefile)
currently invokes Ramulator's build with `make -j4`; an outer `-j1` alone is not
a strict whole-process cap. Do not start a flow that exceeds the agreed host
budget. The inherited whole-GPU Beacon recipe estimates roughly **95 GB per
build** before a separate reference build; it is not an onboarding requirement.

Keep debug/VCD/performance tracing off unless needed. Retain concise logs,
configuration hashes and necessary failing traces; put large generated outputs
in approved artifact storage, not Git. Never delete source, shared tools or user
data to make room. Clean only exact, owned generated targets after checking what
their cleanup command removes; preserve evidence before any recoverable cleanup.

## 4. Prepare a pinned simulation environment separately

The initial source pins in [VERSION](../../VERSION) are Vortex `3.0`, toolchain
`v3.0.2`, gem5 `v25.0.0.1`, and FireSim
`57bb93f1e23daf46198659ddd93608f70121fee0`. Treat the file as authoritative when
it changes. Record resolved repository commits and downloaded bundle hashes as
well as tags; a tag alone does not prove immutable tool content. gem5, FireSim,
Foldsim, graphics and vendor tools are not prerequisites for governance checks.

After budget/access approval, initialize the recorded submodules with
`git submodule update --init --recursive`; do not use `--remote` to float them.
Use the host dependencies in the [installation guide](../install_vortex.md),
checking its supported OS/bundle combinations. The legacy environment guide's
institution-specific server setup is not a prerequisite for this project.

The [installer](../../ci/toolchain_install.sh.in) replaces named component
directories. Give it a **dedicated, versioned tool directory**, never a shared
general-purpose directory or one containing unrelated files. Select an absolute
path without spaces before adapting this example:

```sh
# From the source root; replace the example path before execution.
AI_GPU_TOOL_DIR=/absolute/dedicated/ai-gpu-tools-v3.0.2
mkdir -p build64-ai
cd build64-ai
../configure --xlen=64 --tooldir="$AI_GPU_TOOL_DIR"
# Native RV64 simulation components; review the generated installer's help first.
./ci/toolchain_install.sh --riscv64 --llvm --libc64 --libcrt64 --verilator
make -j1 -C ../third_party softfloat ramulator
make -j1 -C sw/kernel
make -j1 -C sw/runtime/stub
./ci/blackbox.sh --driver=simx --app=sgemm --args="-n16"
```

This is a small scalar-GEMM smoke recipe derived from the inherited build rules,
not tensor-baseline acceptance and not a guarantee of host compatibility. Check
all command results before proceeding. Avoid the installer's no-argument default
or `--all` unless the broad dependency set is intentionally budgeted. Catalog
runs also require their pytest/PyYAML dependencies; install them in a dedicated
environment using the reviewed [CI setup](../designs/continuous_integration.md).

### Host compiler compatibility for WGMMA

Pin the host compiler separately from the RISC-V toolchain, including its resolved
executable, support files, runtime dependencies and final `--host-bin` aliases.
Before a formal retry, retain a C++17 compile/link/run smoke and the failing
`dram_sim.cpp` compile through both the direct compiler and its final alias.
Preserve warnings, includes, defines, optimization and dependency flags; only
compiler/output paths change in these compatibility probes.

The first formal WGMMA attempt at local `7360bba` failed under GCC 14.2.0 in
bundled fmt `core.h:1735` on `-Werror=dangling-reference`. It verified zero
cases, launches or words; arithmetic, witness and parity were `not_run`. The
separate Clang 20.1.8 probe failed at `format.h:4168` on
`-Wdeprecated-literal-operator` under `-Werror`, producing no object. Preserve
both failures with their original identities.

Debian GCC `12.2.0-14+deb12u1` passed the retained C++17 smoke and direct/alias
compile probes with the original warning policy and no warning suppression.
The InRelease → Packages.xz → six-package SHA-256 chain and extracted compiler
identities were checked; **InRelease signature validation was not performed**.
This hash chain is not signature authentication, and reused runtime libraries
remain host-dependent.

The subsequent full witnessed matrix finished successfully at published source
`4af2307e57202c1269e20f893267a5583ad3cba0`. The
[WGMMA handoff](p02-wgmma-handoff.md) records its frozen inputs, actual results,
resource limits, corrected original-packet verification CLI and independently
reviewed [P02-A03 acceptance](evidence/p02-wgmma/processor/acceptance.json). Keep failed
attempts, compiler compatibility and processor qualification separately
attributed; a passing probe or verifier does not close an acceptance gate.

## 5. Freeze the AI baseline and run generated scripts

Use separate build directories for RV32/RV64, incompatible profiles, FPGA and
reference revisions. Re-run `../configure` from the relevant build directory
after source/config/build-input changes. Keep application and backend `CONFIGS`
identical; stale generated headers or mismatched flags invalidate a comparison.
Do not repair mismatches by overriding generated configuration in Makefiles.

GPU tests run from that **configured build tree**, not source `.in` scripts.
The current catalog selector is `--test '<marker expression>'`:

```sh
./ci/regression.sh --test 'tensor and simx'
./ci/regression.sh --test 'tensor and rtlsim'
./ci/regression.sh --test 'tensor_wg and rtlsim'
```

These are multi-case examples, not the approved bounded matrix. Inspect
[tensor](../../ci/testcases/tensor.yaml) and
[WGMMA](../../ci/testcases/tensor_wg.yaml) cases before execution; use
[P01](phases/p01-baseline.md) to freeze cases, formats, dimensions and backend.
Native TFR and C/DPI arithmetic are different evidence. Processor `rtlsim` does
not cover the full AFU; XRT `hw_emu` is not physical FPGA execution. See
[verification](verification.md) and [hardware](hardware.md) for those gates.

## 6. Leave an auditable handoff

Record the exact source revision and dirty state, tool/submodule identities,
generated config hashes, driver/arithmetic backend, workload/seed, commands,
exit codes, logs and limitations. Preserve failed and blocked results. Simulated
cycles are not measured board speed; functional-only SimX cycles are not a timing
result. Do not weaken tolerances or regenerate golden baselines to pass a gate.

Update the relevant phase evidence, [status](status.md) and [backlog](backlog.md)
with the next bounded task, remaining blockers and required decisions. Obtain the
independent review required by [review policy](../review/code-review-policy.md).
Before authorized publication, check the target head for concurrent work and
verify the delivered revision afterward. A local commit is not a confirmed push.
