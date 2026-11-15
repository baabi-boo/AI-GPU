# AI development configuration candidate

**Status: unqualified configuration only.** [`profiles/ai-dev.json`](../../profiles/ai-dev.json)
is a small, opt-in starting point for the P01 baseline investigation. It is not
an accepted machine, a passing GPU test, an FPGA target or an NVIDIA-equivalent
product. [ODR-001](decisions.md#open-decisions) remains unresolved until the
reviewed configuration and numerical coverage earn their required evidence.

The profile uses the existing [configuration system](../designs/build_configuration_system.md).
It does not change `VX_config.toml`, the generator, existing profiles, test cases
or global defaults. Running without this profile keeps the inherited behavior.

## Source-grounded choices

The design basis is source commit
`da55a516a48b49013724f697d3c12a48932b449f`. The geometry comes from
[`tensor_wg:sgemm_tcu_wg-2`](../../ci/testcases/tensor_wg.yaml), whose declared
driver is **SimX only**. Its presence is not native-RTL qualification. Selecting
RV64 and pinning a native scalar FPU creates an explicitly unqualified candidate
that must be built and tested on its own merits.

| Selection | Value | Reason and boundary |
|---|---|---|
| `xlen` | 64 | Choose the RV64 leg allowed by the catalog; pointer/ABI and numerical behavior still require qualification |
| `VX_CFG_NUM_CLUSTERS`, `VX_CFG_NUM_CORES` | 1 each | Pin the small inherited topology; do not begin by scaling core count |
| `VX_CFG_NUM_WARPS`, `VX_CFG_NUM_THREADS` | 8 each | Use the selected catalog case's geometry |
| `VX_CFG_ISSUE_WIDTH` | 2 | Preserve that case's issue geometry |
| `VX_CFG_NUM_ALU_BLOCKS`, `VX_CFG_NUM_LSU_BLOCKS`, `VX_CFG_NUM_FPU_BLOCKS` | 1 each | Preserve the catalog's bounded execution-unit replication |
| `VX_CFG_FPU_TYPE` | `STD` | Native scalar FPU option, also used by [`config2:dogfood-2`](../../ci/testcases/config2.yaml); prevents an ambient `SV_DPI` setting from choosing scalar DPI |
| `VX_CFG_EXT_TCU_ENABLE`, `VX_CFG_TCU_WGMMA_ENABLE` | `true` | Enable the existing tensor/WGMMA path for this profile only |
| `VX_CFG_TCU_TYPE` | `TFR` | Pin the native tensor implementation instead of a software-delegating DPI choice |
| `VX_CFG_TCU_FP16_ENABLE` | `true` | Pin the inherited FP16-family enable; format semantics/support remain P01/P02 work |

There are **two tensor blocks**, not one: `VX_CFG_NUM_TCU_BLOCKS` inherits
`ISSUE_WIDTH`, and [`VX_tcu_block.sv`](../../hw/rtl/tcu/VX_tcu_block.sv) requires
that equality. Tensor lanes likewise inherit eight threads. Do not reduce the
tensor block count independently to make a build smaller.

All unlisted fields inherit the exact source revision's defaults, including
caches, local memory and platform-model parameters. This profile selects no
physical board, usable DRAM capacity, memory technology, clock or bandwidth.
Those inherited modeling values must not be advertised as measured hardware.
No `reference` performance block is supplied because no measurements exist.

## Hardware configuration is not an application signature

The selected GEMM case also specifies `ITYPE=fp16`, `OTYPE=fp32` and
`WGMMA_NRC=16`. Those are application compilation choices, **not hardware-profile
fields**. The operator's dimensions, layouts, seed and reference tolerance are
separate experiment inputs. The current application Makefile defaults to
16×16×16 when dimensions are omitted; P01 must record explicit dimensions rather
than relying on an unstated default.

Profiles are lower priority than explicit `CONFIGS` flags. A later `-D` can
replace native TFR/STD or disable a feature; a profile name alone therefore does
not prove the effective machine. Retain the merged flags and generated config
hashes, and rebuild both application and backend with matching settings. A
modified configuration is a distinct experiment, not automatically `ai-dev`
qualification. See the [developer guide](developer-guide.md).

## Source-only checks

From the source root, these commands validate the JSON against the existing
configuration schema and print its selected XLEN/merged flags. They require
Python only; they do not install, build, simulate or program hardware:

```sh
python3 ci/gen_config.py --config VX_config.toml --profile ai-dev --profile-xlen
python3 ci/gen_config.py --config VX_config.toml --profile ai-dev --xlen 64 --merge-configs
python3 ci/gen_config.py --config VX_config.toml --profile ai-dev --xlen 64 --merge-configs --cflags='-DITYPE=fp16 -DOTYPE=fp32 -DWGMMA_NRC=16'
python3 -m unittest discover -s ci/project -p 'test_ai_profile.py'
```

The XLEN query should print `64`; an explicit `--xlen 32` with
`--merge-configs` is rejected. The unit tests exercise the inherited parser,
selected flags, geometry constraints, native arithmetic selections, override
precedence and unchanged source defaults. A pass establishes configuration
plumbing only, not P01 acceptance or numerical correctness.

## Qualification is the next step, not implied completion

After P00 acceptance, follow **P01-T01/T02** in the [backlog](backlog.md): record
the environment and approve a bounded native matrix/resource budget. With the
required dependencies available, a dedicated future build can be configured as
follows; this is an **unexecuted recipe**, not an installation instruction:

```sh
# Replace the example path with the approved dedicated tool directory.
AI_GPU_TOOL_DIR=/absolute/dedicated/ai-gpu-tools-v3.0.2
mkdir -p build64-ai-dev
cd build64-ai-dev
../configure --profile=ai-dev --xlen=64 --tooldir="$AI_GPU_TOOL_DIR"
```

Before workload execution, review the exact effective configuration and rebuild
the application/backend together. The candidate's SimX origin does not supply a
matching native RTL test; identify or add bounded coverage without weakening
existing cases. Attention, BF16, concurrency, full AFU integration and physical
FPGA behavior each require their own selected tests and results. Keep P01/P02
open until [their gates](roadmap.json) pass under the [acceptance policy](acceptance.md).

No simulation, RTL elaboration, synthesis, FPGA run, performance measurement or
silicon test is established by adding this profile or passing its source checks.
