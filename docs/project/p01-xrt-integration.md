# P01 vendor XRT integration runbook

This is the prepared-artifact route for **P01-T05 / P01-A03**. The
[runner](../../ci/project/xrt_baseline.py) inventories a qualified environment,
builds a fresh RV64 integer application and vendor runtime, and executes one
`xrt` / `hw_emu` smoke. The matching vendor image and emulation configuration
must already exist. The runner does not install vendor software, synthesize an
image, download a platform or authorize licensed access.

The separate [read-only preparation route](p01-hwemu-runbook.md) uses
`hwemu.py inventory` to report prerequisites and `plan` to inspect an existing
generated build. This runner requires a fresh build directory and its own
independently reviewed manifest and build receipt. The routes have distinct
manifest, receipt and report schemas despite both using `schema_version: 1`;
there is no automatic adapter or promotion from a preparation plan to execution.
The runner constructs fixed commands and does not consume the preparation
planner's candidate commands or budget; execution budgets come from this runner's
own CLI. Both routes now use the
[shared compiler-record contract](p01-compiler-records.md), which resolves the
planner's compiler-glob follow-up and validates each execution record separately.
Sharing this validator does not make their manifests, receipts or reports
interchangeable.

**P00 remains complete; P01-A01/A02 remain accepted; P01-A03 and P01 remain
blocked; P02 remains not started.** No vendor `hw_emu` job has run in this
tooling continuation. This runbook, a successful plan, and tooling tests do not
change those states. A real successful smoke supplies a candidate
integration result for independent review under the
[acceptance policy](acceptance.md). Follow [status](status.md), the
[P01 guide](phases/p01-baseline.md) and [roadmap.json](roadmap.json) for the
authoritative gates. Keep the accepted [native baseline](p01-baseline-runbook.md)
and supplemental vendor-free `xrtsim` packet separate.

## 1. Know what each mode does

Run the orchestration CLI from the reviewed source checkout containing its
Python helpers. Its GPU build commands run in the new generated build tree.

```sh
python3 ci/project/xrt_baseline.py --help
python3 ci/project/xrt_baseline.py probe
```

| Mode | Work performed | Meaning of its result |
|---|---|---|
| `probe` | Checks whether `v++`, `vivado`, `emconfigutil`, `platforminfo` and `xsim` are on `PATH`, and whether `XILINX_VITIS`, `XILINX_VIVADO` and `XILINX_XRT` name directories. It does not execute those tools. | Always reports `blocked`: even an installed environment still needs the pinned manifest, reviewed artifacts and build receipt. Exit status is 1. |
| `plan` | Reads the strict manifest; inspects clean source/submodule identities, selected vendor/native files, artifact receipt/logs and resources; emits exact planned commands. Git inspection is permitted; no configure, Make, vendor program or GPU workload runs. It creates no build or output directory. | `outcome: pass` means the implemented prerequisite checks passed. `commands` remains empty and `integration.outcome` remains `not_run`. It is not execution or qualification. |
| `run` | Repeats planning, creates the fresh packet, identifies host tools, configures/builds sequentially and runs the smoke under resource monitoring. | A complete successful execution can set `integration.outcome: pass`. Every report keeps `phase_complete: false` and `acceptance: not_evaluated`. |

The CLI returns 0 for `outcome: pass`, and 1 for blocked/failed reports. Invalid
CLI syntax is handled by `argparse`. A plan with exit 0 is not a passing A03
record. Run mode replans its inputs; it does not consume or trust a saved plan.

## 2. Prepare real prerequisites

Select and independently review a compatible installed Vitis, Vivado/XSim and
XRT combination, its supported host OS, the exact platform/shell and any license
entitlement. A release label, executable name or file hash cannot establish
compatibility. Record the basis for choosing the release and platform in the
qualification review. Resolve resources and access under the
[developer guide](developer-guide.md) before preparing vendor artifacts.

The implementation requires:

- A Linux host exposing `/proc` process-group accounting, Git and Python 3, plus
  the shell/build utilities required by the checked-out build rules. The host
  inventory requires `gcc`, `g++`, `make`, `ld`, `as` and `python3` on the retained
  `PATH`; it also identifies the C++ frontend. `cmake` is inventoried when
  available. Every retained `PATH` entry must be nonempty and absolute: empty
  entries, leading/trailing/doubled colons, `.` and relative entries are rejected.
  Use a compiler compatible with the pinned source/dependencies.
- A host `readelf` on that reviewed `PATH`, resolving outside the vendor and
  generated-build roots. The runner executes it read-only to inspect generated
  ELF objects and the pinned XRT coreutil library before the smoke and again
  before recording success. This check requires the fresh build; a passing
  plan does not establish runtime bindings.
- UUID development headers/library and the real vendor XRT headers/library used
  by [the XRT runtime build](../../sw/runtime/xrt/Makefile). Finding their names
  alone does not prove the runtime will compile or link.
- A clean Git checkout whose commit/tree match the artifact manifest, with all
  recursive submodules initialized at recorded revisions. Tracked edits and
  nonignored untracked inputs block planning. The read-only
  [source-index guard](../../ci/project/xrt_source.py) also rejects
  `assume-unchanged`, `skip-worktree` and unmerged index entries in the checkout
  and its indexed recursive submodules. Its bounded observations are retained
  under `source.index_flags`; they supplement Git status without locking the
  checkout or independently comparing every working file with its committed
  blob. Keep preparing artifacts and execution outputs outside this checkout.
- A dedicated native tool root for the reviewed
  [RV64 toolchain lock](../../ci/project/p01_toolchain.lock.json). The inventory
  currently requires `riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc`,
  `llvm-vortex/bin/clang`, `llvm-vortex/bin/clang++`, `verilator/bin/verilator`,
  `verilator/bin/verilator_bin`, `libc64/lib/libc.a`, `libc64/lib/libm.a` and
  `libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a`. Verilator is required
  by this shared inventory even though the vendor smoke does not run it.
  Provisioning is a separate task; this runner hashes selected installed files
  and checks the reviewed lock, without reinstalling them. The native inventory
  separately records the actual `clang++` lookup as `llvm_clangxx`, including
  its resolved target and bytes, and rechecks that identity between stages.
  An internal symlink may select the same file as `clang`; the `clang++` lookup
  must still exist, remain executable and resolve inside the native tool root.
- The platform `.xpfm`, a matching `vortex_afu.xclbin` built for `hw_emu`, its
  matching `emconfig.json`, original successful build-command records/logs and
  a substantive independent qualification review. Preserve failures from
  preparation separately. Do not substitute synthetic test-fixture files.

The six vendor roles in the manifest bind to these actual lookups:

| Manifest role | Required lookup beneath the declared root |
|---|---|
| `vendor.files.vpp` | `vitis_root/bin/v++` |
| `vendor.files.vivado` | `vivado_root/bin/vivado` |
| `vendor.files.emconfigutil` | `vitis_root/bin/emconfigutil` |
| `vendor.files.platforminfo` | `vitis_root/bin/platforminfo` |
| `vendor.files.xrt_header` | `xrt_root/include/experimental/xrt_device.h` |
| `vendor.files.xrt_coreutil` | `xrt_root/lib/libxrt_coreutil.so` |

The first four must be executable. Inventory additionally requires executable
`vivado_root/bin/xsim` and the XRT experimental headers `xrt_bo.h`,
`xrt_device.h`, `xrt_error.h`, `xrt_ip.h`, `xrt_kernel.h` and `xrt_xclbin.h`.
It records these additional identities without adding new manifest fields.
Vendor roots must be canonical directories. A lookup may resolve an internal
symlink, but its resolved target must stay inside the declared root, and the
manifest must pin that canonical regular file. An external symlink target is
blocked. Hashing these wrappers, headers and libraries does not inventory a
complete installation, all shared dependencies or everything referenced by an
`.xpfm` file; the independent review must address that boundary.

## 3. Freeze the manifest and prepared build evidence

Copy [the environment example](../../ci/project/p01_xrt_environment.example.json)
to a separate records directory and replace every placeholder using actual
observations. The example is deliberately rejected: revision/digest placeholders
are not hexadecimal identities, and `size_bytes: 0` means unknown. Merely
replacing them with plausible hexadecimal strings or invented sizes supplies
no evidence. There is no `qualified`, `approved` or `pass` field to toggle.

### Exact manifest contract

[xrt_contract.py](../../ci/project/xrt_contract.py) is authoritative. JSON must be
a UTF-8 object of at most 1 MiB, with no duplicate keys, nonfinite numbers,
comments or extra keys. The manifest has exactly these fields:

| Field | Required value or structure |
|---|---|
| `schema_version` | Integer `1` |
| `id` | `p01-xrt-hw-emu-demo-v1` |
| `driver`, `target` | `xrt`, `hw_emu` |
| `source` | Exactly `revision` and `tree`, each an observed 40-character lowercase hexadecimal Git identity |
| `configuration` | Exactly the fixed object below |
| `platform` | Exactly `name` and `file`; `file` is a file record for a path ending in `.xpfm` |
| `vendor` | Exactly `release`, `vitis_root`, `vivado_root`, `xrt_root` and `files`; `files` contains exactly the six roles listed above |
| `artifacts` | Exactly `xclbin` and `emconfig`, each a file record |
| `build_receipt` | File record for the completed build-receipt JSON, at most 1 MiB |
| `qualification_review` | File record for nonempty UTF-8 review text without NUL bytes, at most 1 MiB |

`platform.name` and `vendor.release` are bounded labels: 1–128 characters,
starting with a letter, digit or underscore; subsequent characters may also be
`.`, `:`, `+` or `-`. They are labels, not a compatibility database lookup.

```json
{
  "xlen": 64,
  "configs": [
    "-DVX_CFG_NUM_CLUSTERS=1",
    "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4",
    "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1",
    "-DVX_CFG_FPU_TYPE_STD"
  ],
  "app": "demo",
  "args": ["-n1"],
  "expected_points": 16
}
```

Keep the ordered `configs` list exact for the prepared image, host application
and runtime. This fixes one cluster/core, four warps/threads, issue width one
and STD scalar arithmetic. The integer demo's `-n1` on this configuration must
report 16 points and 64-byte buffers. The workload does not establish tensor
arithmetic coverage. There is no CLI option to select another app, workload,
configuration, execution target or platform.

Every **file record** has exactly `path`, `sha256` and `size_bytes`. `sha256` is
64 lowercase hexadecimal characters; `size_bytes` is a positive integer, never
a Boolean. The general maximum is 16 GiB; manifest/receipt/review/emconfig inputs
are limited to 1 MiB, and receipt-linked build logs to 16 MiB. File checks stream
regular files, reject symlink traversal in every path component and detect
changes during the read. Both artifact files must share one directory, with
the exact basenames `vortex_afu.xclbin` and `emconfig.json`. Emconfig must decode
to a nonempty JSON object; the inventory does not validate the vendor's entire
emconfig schema or prove the image actually matches it.

Paths written into records must already be absolute and normalized, at most
4096 characters, using only letters, digits, `_`, `.`, `/`, `+` and `-`. Empty
components, trailing slashes, `.`/`..` components and spaces are rejected.
Record canonical file targets, including a versioned library target when its
lookup name is a symlink. To obtain one real file record, use the helper from
the reviewed runner checkout, replacing both absolute paths first:

```sh
AI_GPU_RUNNER=/absolute/reviewed-runner-checkout
AI_GPU_FILE=/absolute/canonical/observed-file
python3 - "$AI_GPU_RUNNER" "$AI_GPU_FILE" <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / "ci/project"))
from xrt_contract import file_identity
path = Path(sys.argv[2])
print(json.dumps({"path": str(path), **file_identity(path)}, indent=2))
PY
```

### Exact build-receipt contract

Prepare the vendor image in its own reviewed build flow; retain the actual
compiler/linker and emconfig-generation commands and their original outputs.
The smoke runner never executes commands supplied in this receipt. Its JSON
object has exactly `schema_version`, `driver`, `target`, `source`,
`configuration`, `platform`, `vendor`, `artifacts` and `commands`. The first
eight fields must equal the manifest's corresponding fields exactly. Do not
include the manifest's `id`, `build_receipt` or `qualification_review` fields
inside the receipt.

`commands` is an array of 1–32 actual successful command records. Each record
has exactly these fields:

| Field | Contract |
|---|---|
| `argv` | Actual argument array, not a shell command string: 1–128 nonempty strings, each at most 4096 characters and together at most 32768 characters; no control characters |
| `cwd` | The recorded absolute, normalized safe working-directory path |
| `exit_code` | Integer `0`, backed by the actual successful preparation command |
| `log` | File record for the retained original command output, at most 16 MiB |

Receipt validation binds the declared inputs/outputs and verifies log bytes.
It does not prove that commands ran, identify a required vendor command by
name, inspect the complete binary format, or establish that reviewer claims
are truthful. Do not manufacture zero exits or trim a failed log into a pass.
Keep failed preparation evidence and resolve its cause before recording a
successful replacement attempt. If original logs exceed the receipt limit,
resolve the preparation/retention contract rather than silently truncating
them and describing the result as the original log.

The qualification review should identify its reviewer and actual review date,
source/tree/submodules, installed release/host compatibility, platform and
dependencies, license/access basis, exact hardware configuration, original
build records and artifact hashes, unresolved limitations and disposition.
The loader checks only that this text exists and is nonempty UTF-8; independent
review must evaluate its substance. Hash the finished receipt and review and
place their real file records into the final manifest. The receipt does not
contain a manifest hash, so this order does not create a circular dependency.

For read-only checks, `load_manifest(path)` validates the manifest's structure;
`load_receipt(path, manifest)` additionally checks the manifest-bound receipt
path, digest and structure. Neither grants qualification. The full
`xrt_inventory.inspect_manifest(manifest, source)` inventory also checks source
identity, vendor lookup bindings, prepared files and receipt logs. The first
two functions are in `xrt_contract`; the supported orchestration CLI is
`xrt_baseline.py`.

## 4. Choose fresh paths and run the plan

Replace the following paths with real dedicated locations. Their parent
directories must already exist. CLI path arguments are normalized to absolute
paths and rejected if they traverse symlinks; use canonical absolute paths for
clarity. Unlike some older native-baseline examples, this runner requires the
source, build and native tool roots to be pairwise nonoverlapping. In
particular, the new build directory must be outside the source checkout.

| Location | Requirement |
|---|---|
| Runner checkout | Reviewed implementation and every helper named by `xrt_baseline.TOOLING_FILES`; may be distinct from the clean GPU source checkout |
| `--source` | Existing clean Git checkout at the artifact's exact commit/tree |
| `--build-dir` | Nonexistent or empty directory under an existing parent, separate from source/tools |
| `--tool-dir` | Existing dedicated native tool root with the inventory above |
| `--manifest` | Existing completed manifest with real identities |
| `--bundle-manifest` | Reviewed native toolchain lock; defaults to `p01_toolchain.lock.json` beside the runner |
| `--output` | Nonexistent path under an existing parent, separate from source/build/tools; required for `run` |
| Parent `TMPDIR` | Existing temporary directory on a filesystem meeting the selected reserve; set in the environment that invokes the runner |

Build/output paths must also avoid overlap with the manifest, bundle lock,
vendor roots and every manifest-pinned input. Keep the entire prepared vendor
artifact/receipt/log directory separate from both outputs. Reusing a populated
build tree or an existing output directory is rejected; use fresh paths for
each retry and retain the failed packet.

The runner revalidates canonical roots and packet subdirectories during
execution, retained-file destinations before writing, and working directories,
Make `-C` directories and log destinations before command launch. Keep these
paths under controlled ownership throughout the run: these boundary checks do
not isolate the filesystem from concurrent changes. If the output path becomes
unsafe, execution can stop without a final checkpoint; the runner must not
follow a substituted symlink to write a failure report.

```sh
AI_GPU_RUNNER=/absolute/reviewed-runner-checkout
AI_GPU_SOURCE=/absolute/clean-gpu-checkout
AI_GPU_TOOLS=/absolute/dedicated-tools-v3.0.2
AI_GPU_BUILD=/absolute/work/build64-xrt-01
AI_GPU_MANIFEST=/absolute/qualified-xrt/environment.json
AI_GPU_OUTPUT=/absolute/work/xrt-smoke-01
AI_GPU_PARENT_TMP=/absolute/work/runner-tmp

TMPDIR="$AI_GPU_PARENT_TMP" python3 "$AI_GPU_RUNNER/ci/project/xrt_baseline.py" plan \
  --source "$AI_GPU_SOURCE" \
  --build-dir "$AI_GPU_BUILD" \
  --tool-dir "$AI_GPU_TOOLS" \
  --manifest "$AI_GPU_MANIFEST" \
  --bundle-manifest "$AI_GPU_RUNNER/ci/project/p01_toolchain.lock.json" \
  --output "$AI_GPU_OUTPUT" \
  --jobs 2 --timeout-seconds 1800 --min-free-gib 15 \
  --max-log-mib 16 --max-rss-gib 6
```

Inspect every blocker. A source mismatch requires matching artifacts/source,
not editing the recorded commit to fit an unrelated image. An absent library,
license, supported platform or qualified receipt remains a blocker. The plan
does not test compiler compatibility, execute vendor version commands or prove
license entitlement.

### Resource budget

| Option | Default and enforcement |
|---|---|
| `--jobs` | `2`; only `1` or `2` accepted; forwarded through Make and thread-related variables |
| `--timeout-seconds` | `1800` per command |
| `--min-free-gib` | `15` GiB reserve on the inspected/monitored filesystems |
| `--max-log-mib` | `16` MiB per command; must be positive and at most 16 MiB |
| `--max-rss-gib` | `6` GiB sampled aggregate RSS for the monitored process group |

Planning checks the filesystems containing source, the build parent, native
tools, prepared artifacts, the output parent when supplied, and the parent
Python process's actual temporary directory (`tempfile.gettempdir()`). Execution
continues to check those resources through the build/output trees and also
monitors the packet's `tmp` directory used by child commands. Parent-side
probes and generated-header validation can use the parent temporary directory;
the child `TMPDIR` binding does not redirect those operations.

Set `AI_GPU_PARENT_TMP` above to an existing directory on a filesystem with
enough free space before invoking the CLI. A small `/tmp` tmpfs can block the
default 15 GiB reserve even when the build/output filesystem has ample space.
Select an appropriate parent temporary filesystem while preserving the chosen
reserve and retain the resource observations for each location.

All numeric budgets must be positive, finite and representable. Fractional
positive timeouts are accepted; byte budgets must convert to at least one byte. The
monitor checks disk, elapsed time, output and Linux process-group RSS, stops the
group on a budget violation and retains the partial log and stop reason. These
are sampled execution limits, not hard kernel quotas; peaks between samples
and descendants leaving the process group are outside that guarantee. Nested
tools may not honor all job/thread hints. Review their behavior for the chosen
release. The report records host available RAM but leaves
`effective_cgroup_limit_bytes` null; it does not claim the cgroup budget is known.
Choose resources before execution; do not relax bounds after a failing run to
convert its existing result into a pass.

The runner also checks available bytes before every retained input, receipt
log, generated-configuration snapshot, smoke INI and full report write. Each
write requires room for its complete payload above the reserve, and successive
copies recheck the remaining space. If a full report cannot fit above the
reserve, a blocked or failed run may write only an emergency failure-status
checkpoint of at most **16 KiB**, marked `checkpoint_scope: failure_status_only`.
It preserves status, the bounded reason/blockers and command statuses; it omits
the full inventory. A reserve failure while finalizing an otherwise successful
smoke changes the run to failure. This emergency checkpoint may use the reserve,
but still requires a safe output path and writable storage; it is not guaranteed
to succeed. These pre-write checks remain subject to concurrent filesystem use
and do not establish a hard quota.

## 5. Run the bounded smoke without tracing

After prerequisites and the concrete plan are ready, invoke the same reviewed
runner with the same inputs and budgets:

```sh
TMPDIR="$AI_GPU_PARENT_TMP" python3 "$AI_GPU_RUNNER/ci/project/xrt_baseline.py" run \
  --source "$AI_GPU_SOURCE" \
  --build-dir "$AI_GPU_BUILD" \
  --tool-dir "$AI_GPU_TOOLS" \
  --manifest "$AI_GPU_MANIFEST" \
  --bundle-manifest "$AI_GPU_RUNNER/ci/project/p01_toolchain.lock.json" \
  --output "$AI_GPU_OUTPUT" \
  --jobs 2 --timeout-seconds 1800 --min-free-gib 15 \
  --max-log-mib 16 --max-rss-gib 6
```

The six planned build/smoke commands execute sequentially. The plan's
`planned_commands` contains the exact argument arrays and working directories;
host probes and validation steps run around this sequence:

| Command ID | Operation |
|---|---|
| `configure` | Run the selected source's `configure --xlen=64 --osversion=ubuntu/focal --tooldir=...` from the fresh build directory |
| `kernel-library` | `make -C sw/kernel` in the generated tree |
| `runtime-stub` | `make -C sw/runtime/stub` in the generated tree |
| `application` | `make -C tests/regression/demo all` in the generated tree |
| `vendor-runtime` | `make -C tests/regression/demo runtime-xrt` in the generated tree |
| `smoke` | Execute the built `demo -n1` directly from `build/tests/regression/demo` |

Every Make invocation receives `-j1`/`-j2`, `TARGET=hw_emu`, the exact frozen
`CONFIGS`, `JOBS` and `IMPL_MAX_THREADS`. The runner does not call the inherited
`run-xrt` target or `blackbox.sh` for the smoke, and never uses the receipt as
an executable command list. Generated headers, copied build inputs and source
bindings are inspected. The [shared validator](p01-compiler-records.md) requires
one runtime compiler record and three ordered demo records: kernel, host and
linker. Every compilation record independently establishes the frozen
configuration, `VX_CFG_XLEN=64` and `VX_CFG_XLEN_64=1`, without `XRTSIM`, protected
configuration undefines or non-native arithmetic substitutions. Include and
dependency-output operands cannot contribute definitions; definitions from one
record cannot fill another record's omissions.

The kernel must select exactly one direct `-march=rv64imafd` and `-mabi=lp64d`;
consumed or forwarded selections do not qualify. Host/runtime records cannot
select these kernel ISA/ABI flags. The linker must contain exactly
`-L<build>/sw/runtime -lvortex`. Ordinary quoting, split definitions and supported
preprocessor forwarding remain valid, while response files, Verilator/Make
transports, unsupported options and free source operands are rejected.

Only LF separates records; spaces, tabs and blank lines are allowed. CRLF,
other controls and Unicode whitespace separators are rejected. Shell operators,
dollar signs, backticks, glob characters (`*`, `?`, `[` and `]`), braces,
parentheses and tilde are excluded even when quoted or escaped. Inspection never
expands patterns. A failed effective-record check prevents smoke launch; changed
or invalid records after execution prevent a successful final packet.

The generated XRT INI must select the tracked source's `xsim.tcl`, even though
the smoke uses its own no-trace INI.

The child environment retains only `PATH`, `HOME`, `XILINXD_LICENSE_FILE` and
`LM_LICENSE_FILE` from the caller, then sets controlled locale, target,
configuration, native-build resource and vendor-root values. It disables
compiler caching with `CCACHE_DISABLE=1` and `OBJCACHE=''`. Choose the host
compiler through the reviewed, nonempty absolute `PATH` entries; arbitrary
inherited build/debug variables are not forwarded. The smoke adds these exact
bindings:

| Environment variable | Value |
|---|---|
| `VORTEX_DRIVER` | `xrt` |
| `XCL_EMULATION_MODE` | `hw_emu` |
| `XCLBIN_PATH` | The manifest's absolute `vortex_afu.xclbin` path |
| `EMCONFIG_PATH` | Directory containing the manifest's `emconfig.json` |
| `XRT_INI_PATH` | The packet's `artifacts/xrt.ini` file |
| `XRT_DEVICE_INDEX` | `0` |
| `LD_LIBRARY_PATH` | `<build>/sw/runtime:<xrt_root>/lib`, in exactly that order |
| `TMPDIR` | The packet's `tmp` directory, also used by build commands |

### Inspect the selected runtime bindings

[xrt_runtime.py](../../ci/project/xrt_runtime.py) records `runtime_before` before
launch and `runtime_after` after a successful smoke, before a passing result
can be recorded. It invokes the selected host `readelf -h -d --wide` with a
minimal host environment to inspect four objects: the built `demo`,
`libvortex.so`, `libvortex-xrt.so` and the manifest-pinned XRT coreutil library.
Each probe has a five-second timeout and 64 KiB output ceiling. The inspection
executes no inspected object or vendor tool. It validates selected ELF header
and program-table structure, requires matching ELF class, data encoding and
machine across all four objects, and requires each library to have `DYN` type;
the demo may have `EXEC` or `DYN` type. It checks dynamic tags and identities
against these selected lookups:

| Requester and lookup | Required selected file |
|---|---|
| `demo` → `DT_NEEDED: libvortex.so` | The generated `sw/runtime/libvortex.so` |
| `libvortex.so` → `dlopen: libvortex-xrt.so` under `VORTEX_DRIVER=xrt` | The generated `sw/runtime/libvortex-xrt.so` |
| `libvortex-xrt.so` → its one `DT_NEEDED` coreutil name, including any version suffix | The manifest-pinned canonical `vendor.files.xrt_coreutil` target |

The fixed loader path searches the generated runtime directory first and the
vendor XRT `lib` directory second. Required aliases must resolve to the pinned
files; an unexpected coreutil shadow in the generated directory is rejected.
The guard also rejects legacy `DT_RPATH`, recognized hardware-capability
lookup directories, active system `/etc/ld.so.preload` entries, extra `LD_*`
controls and `GLIBC_TUNABLES`. The before/after observations and identities must
match for success.

This establishes selected structural compatibility and lookup bindings only.
Matching headers do not establish complete ELF loadability or ABI compatibility.
The inspection does not inventory the complete vendor/system dependency
closure, observe loaded process maps or establish symbol-level provenance.
Review the remaining dependencies and installed-release behavior independently.

### Retained no-trace configuration

The retained smoke INI is exactly:

```ini
[Runtime]
runtime_log=console

[Emulation]
debug_mode=off

[Debug]
profile=false
timeline_trace=false
data_transfer_trace=off
stall_trace=off
```

It contains no pre-simulation Tcl hook. The generated template is retained and
checked separately; its debug/profiling defaults are also off, and its tracked
`xsim.tcl` hook collects waveforms only with explicit debug configuration plus
`VORTEX_XRT_WAVEFORM=1`. The generic `run-xrt` recipe still assigns its own
`XRT_INI_PATH`. The runner's direct launch selects the retained smoke INI above;
exporting that path alone does not override the generic recipe.
AMD/Xilinx's [XRT INI documentation](https://xilinx.github.io/XRT/master/html/xrt_ini.html)
describes `XRT_INI_PATH`; the
[2021.1 INI reference](https://xilinx.github.io/XRT/2021.1/html/xrt_ini.html)
documents the emulation/debug controls used here. **Verify these settings and
the file-path interpretation against the chosen installed release before
execution.** Those references do not qualify every later release. The intent
is a bounded smoke with debugging/profiling/tracing disabled; vendor diagnostic
outputs remain subject to resource and retention review.

## 6. Read and retain the result honestly

The runner checks frozen source, vendor/artifact, native-tool and helper
identities before/after commands, identifies the actual host tools in run mode,
and checks the generated build, effective configuration and selected runtime
bindings again around the smoke. A zero exit alone is insufficient. The smoke
log must contain each of these lines exactly once, in order, without
failure/error markers:

```text
open device connection
data type: integer
number of points: 16
buffer size: 64 bytes
upload source buffer0
upload source buffer1
launch kernel
download destination buffer
wait for completion
verify result
cleanup
PASSED!
```

These are host-observed API/reference milestones. They do not constitute bus
traces, all DMA/backpressure coverage, tensor numerical qualification, physical
PCIe evidence or accelerator throughput measurements.

The output packet contains `report.json`, `logs`, `artifacts` and `tmp`.
`report.json` is checkpointed atomically during execution and includes command
arguments, exits, resource observations, identity checks, limitations and the
candidate `integration` outcome. Each executed command has a bounded
`logs/<command-id>.log`; future commands are not executed after a failure.

During the execution sequence, `SIGINT` and `SIGTERM` interrupt the active
command, stop its process group and retain its cleanup result and partial log.
Host/identity probes also unwind on `SIGINT`; `SIGTERM` is converted into the
same interruption path. Probe cleanup terminates and reaps the probe child.
The runner records `state: finished`,
`outcome: fail` and a stop reason for handled execution cancellation, restores
the enclosing signal handlers and prevents later commands from launching.
Inspect `cleanup_complete` for any active command and the actual final report;
forced termination, unavailable storage or an unsafe output path can prevent a
final checkpoint.

Retained paths, once their respective stages are reached, are:

| Packet path | Contents |
|---|---|
| `artifacts/manifest.json` | Original manifest bytes |
| `artifacts/build_receipt` | Original build-receipt JSON bytes |
| `artifacts/qualification_review` | Original qualification-review text |
| `artifacts/emconfig.json` | Original matching emulation configuration |
| `artifacts/build-logs/0.log`, `1.log`, … | Receipt-linked original build logs in receipt command order, starting at index zero |
| `artifacts/tooling/` | Snapshots of all `TOOLING_FILES`: `xrt_baseline.py`, `xrt_contract.py`, `xrt_inventory.py`, `xrt_runtime.py`, `xrt_signals.py`, `xrt_source.py`, `compiler_records.py`, `baseline_packet_contract.py`, `baseline_matrix.py`, `baseline_packet_io.py`, `baseline_host.py`, `baseline_inventory.py`, `baseline_process.py` and `preflight.py` |
| `artifacts/xrt.ini` | Selected no-trace smoke INI |
| Generated snapshots under `artifacts/` | The two effective configuration stamps, `.config.stamp`, `config.mk`, generated XRT INI and the four generated configuration/type headers; original relative paths have `/` replaced by `_` |

The tooling snapshots include the shared validator and its complete local
import dependency chain. Their hashes identify source bytes and detect drift;
they do not attest the Python interpreter, loaded code objects or bytecode caches.
Valid compiler records and matching hashes also do not prove which inputs
produced a binary or authenticate producer statements.

Copied input records include retained-byte hashes in `report.retained`; the
smoke INI has its own `smoke_ini` identity. Generated snapshots are copied after
the six commands succeed and must match their pre-smoke identities; later final
checks can still fail. Prepared-file and binary identities are recorded;
keep the separate source, vendor artifact directory and build tree available
for review because the packet does not embed the entire XRT installation,
platform, image or produced binaries. This is not a self-contained vendor
installation or an automatically accepted offline evidence packet.

A plan-stage blocker in run mode attempts to retain a blocked packet when the
manifest and output paths are valid; invalid arguments/contracts can fail before
an output directory exists. Inspect the CLI result, actual report and `commands`
list rather than assuming any build or GPU command ran. Under disk pressure,
the retained `report.json` can be the emergency failure-status-only checkpoint
described above. If final checkpointing fails, any earlier report can remain
incomplete and must not be treated as the final outcome. Timeout, cancellation,
command failure, incomplete cleanup, altered frozen inputs, runtime binding
failures or missing reference milestones prevent a pass. Retain failed packets
and use fresh build/output paths for retries.

Reports replace known machine paths with tokens; raw logs and retained input
files can still contain machine paths or vendor output. Review all retained
bytes for credentials, sensitive paths and redistribution rights before
publication. Preserve original identities and describe any published redaction
using the [evidence procedure](evidence/README.md); replacing original bytes
changes the evidence identity.

An independent reviewer must reconcile the actual vendor/runtime execution,
source/configuration/artifact provenance, transfer/launch/completion/reference
records, failures, limitations and acceptance scope before any A03 decision.
The runner never changes [roadmap.json](roadmap.json) or accepts a gate. A03
remains blocked while its real prerequisites or required evidence are absent.
Even a reviewed `hw_emu` pass would establish only its named integration scope;
physical FPGA, performance and silicon obligations remain separate.
