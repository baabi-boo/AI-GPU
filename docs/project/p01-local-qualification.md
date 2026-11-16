# Supplemental local AFU and RTL qualification

[`ci/project/local_qualification.py`](../../ci/project/local_qualification.py)
plans and runs a fixed RV64 matrix through the local `xrt`/`xrtsim` AFU path and
two focused RTL unit tests. The contract is `local-afu-rv64-v1`. A completed
passing run establishes the selected simulated behavior under its retained
configuration, resource budget and input identities.

The local XRT shim models host/device memory; it does not load a vendor device
image. This route does not qualify vendor XRT/Vitis `hw_emu`, a vendor platform,
physical DMA/cache coherence, FPGA operation, silicon, or P01-A03. Native
arithmetic claims are specific to the selected **STD floating-point** and
**TFR tensor** implementations. Integer multiply/divide DPI helpers and simulator
utilities can remain in the local AFU model; the whole AFU is not claimed to be
DPI-free. An imported helper or linked symbol alone does not establish that a
particular workload exercised it. The unit cases cover their named modules,
not every whole-system backpressure condition.

This document is a procedure. Exact attempts, failures, observed results,
reviewed packets and publication hashes belong in the separate
[local qualification handoff](p01-local-qualification-handoff.md). A tooling
test pass, a passing plan and a partially completed native run are distinct
evidence. None is an all-case execution result or phase acceptance. For the
vendor route, use the [XRT integration guide](p01-xrt-integration.md).

## 1. Freeze the inputs and prepare the tools

Use a clean, committed source checkout with initialized recursive submodules.
Retain its exact commit, tree, submodule identities and dirty-state observation.
The dependency supplier must also be a clean checkout: its recursive submodule
pins and the runner's selected dependency extension inputs must match the source.
Its top-level commit is retained separately; matching labels alone do not prove
matching inputs. Tracked edits, nonignored untracked files, unresolved index
entries, `assume-unchanged` and `skip-worktree` are blockers. Keep the source,
tools, dependency libraries and headers, host tools, and executing helper files
unchanged throughout the attempt.

The runner reuses prepared libraries; it neither downloads tools nor builds
those dependencies. Prepare missing prerequisites separately using the
[baseline runbook](p01-baseline-runbook.md) and
[developer resource guidance](developer-guide.md). Check available disk and
memory before preparation or execution.

| CLI input | Required contents and identity |
| --- | --- |
| `--source` | Frozen checkout root with all recursive submodules initialized. Run the helper from this checkout. |
| `--tool-dir` | Prepared `riscv64-gnu-toolchain`, `llvm-vortex`, `verilator`, `libc64` and `libcrt64` layout from the pinned bundle below. |
| `--dependency-source` | Checkout root, **not** its `third_party` directory. It supplies the three libraries and external header trees listed below. |
| `--header-dir` | Narrow prepared include root containing `uuid/uuid.h`. The bounded entire tree is inventoried; use regular files/directories without symlinks. |
| `--build-root` | New, nonexistent directory under an existing parent, outside all input roots. Each selected configuration receives its own generated child tree. |
| `--output` | New, nonexistent packet directory under an existing parent, separate from the build and input roots. Required for `run`; accepted but not created by `plan`. |

The immutable [toolchain lock](../../ci/project/p01_toolchain.lock.json) fixes
`vortexgpgpu/vortex-toolchain-prebuilt` tag `v3.0.2`, commit
`e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`, bundle family `ubuntu/focal`. The
canonical archive-manifest digest is
`f7638b92912ee8b61640d32431814e676950124b9455649f16400cb54b2a4eb3`.
The prepared versions described by the baseline runbook are RISC-V GNU
**12.2.0**, Vortex LLVM **20.1.8** and Verilator **5.050**. The inventory checks
the reviewed lock and records the installed executables, versions and libraries
by hash. Installed-file observation does not itself re-extract the archives to
prove their relationship; retain the provisioning receipt as well.

Select the prepared **GNU 11 host compiler**, with `gcc`, `g++` and `cpp`
resolving to the intended executables. The documented user-local compiler is
Debian **11.3.0-12**. Put its directory first on `PATH` for both planning and
execution; nested Verilator builds also resolve `g++` there. Arbitrary inherited
`CC`/`CXX` overrides are not carried into the cleaned child environment. The
prebuilt Verilator's own producing compiler is a separate identity from the
compiler selected to build this run's model. A compiler version string is an
inventory observation, not a compatibility result.

Use a prepared Python **3.12 or newer** environment to follow the baseline
provisioning recipe. This direct runner uses the standard library; the separate
catalog harness needs pytest/PyYAML. Host execution needs Linux `/proc`, POSIX
process groups, Git, Make, the host compiler, assembler and linker. CMake is
needed when preparing Ramulator; the local runner reuses the prepared libraries.
No package installation is part of the plan/run commands below.

The dependency supplier must provide:

- `third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a`;
- `third_party/ramulator/libramulator.so`;
- `third_party/ramulator_ext/libramulator-vortex.so`;
- `third_party/ramulator/ext/spdlog/include` and
  `third_party/ramulator/ext/yaml-cpp/include`.

The runner sets `THIRD_PARTY_DIR` to the supplier's `third_party` directory and
`CPLUS_INCLUDE_PATH` to `--header-dir`. Ignored dependency build products are
reused by hash, not rebuilt or relabelled as fresh dependencies. Retain their
actual producing compiler where available: choosing GCC 11 for new work does
not make a previously GCC 14-produced library a GCC 11 build. External-header
hashes identify content; they do not certify upstream origin. Host/tool
inventories do not cover every system header, dynamically loaded library or
compiler support file.

Use absolute argument paths with only letters, digits, `/`, `_`, `.`, `+` and
`-`, without symlink traversal. Shell quoting does not relax this path contract.
Do not create the build or output directory yourself: the runner requires fresh
roots and creates them exclusively.

## 2. Set portable local paths

This is a **Bash template**. Replace every `/absolute/...` placeholder with a
verified local path. The first six paths must already exist. Keep each `PATH`
component nonempty and absolute. The workspace parent can be created here;
`build-01` and `run-01` must remain nonexistent.

```bash
AI_GPU_SOURCE='/absolute/source/AI-GPU'
AI_GPU_TOOLS='/absolute/tools-v3.0.2'
AI_GPU_DEPS='/absolute/dependency-source'
AI_GPU_HEADERS='/absolute/host-headers'
AI_GPU_HOST_BIN='/absolute/host-gcc11/usr/bin'
AI_GPU_VENV='/absolute/python-env'
AI_GPU_WORK='/absolute/local-qualification'
AI_GPU_BUILD="$AI_GPU_WORK/build-01"
AI_GPU_OUTPUT="$AI_GPU_WORK/run-01"

mkdir -p "$AI_GPU_WORK"
export PATH="$AI_GPU_HOST_BIN:$AI_GPU_VENV/bin:/usr/local/bin:/usr/bin:/bin"
set -o noclobber

git -C "$AI_GPU_SOURCE" rev-parse HEAD 'HEAD^{tree}'
git -C "$AI_GPU_SOURCE" status --short --untracked-files=all
git -C "$AI_GPU_SOURCE" submodule status --recursive
git -C "$AI_GPU_DEPS" rev-parse HEAD 'HEAD^{tree}'
git -C "$AI_GPU_DEPS" status --short --untracked-files=all
git -C "$AI_GPU_DEPS" submodule status --recursive
command -v gcc g++ cpp make ld as python3
gcc --version
g++ --version
python3 --version
"$AI_GPU_TOOLS/verilator/bin/verilator" --version
"$AI_GPU_TOOLS/llvm-vortex/bin/clang" --version
"$AI_GPU_TOOLS/riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc" --version
df -h "$AI_GPU_WORK" "$AI_GPU_TOOLS" "$AI_GPU_DEPS"
free -h
```

Inspect every exit and identity before proceeding. A default-`PATH` miss for
`verilator` or `clang` does not establish that the prepared tools are absent:
probe the selected layout directly. The runner independently inventories inputs,
host tools, the `g++`-resolved `cc1plus` frontend, and its transitive local helper
closure. Source and GPU configuration changes require a new committed freeze
and a new attempt.

## 3. Select the fixed cases

With no `--case` option, the runner selects the **six core cases**. Repeated
`--case` options **replace** that selection; they do not append to it. The
selection must be nonempty, unique and drawn from the fixed catalog. Execution
uses catalog order regardless of flag order. Selecting just `--case gemm-fp16
--case gemm-bf16` runs only the two tensor cases. List all eight IDs explicitly
for core plus tensor coverage.

| Group | Case IDs | Fixed workload and required result |
| --- | --- | --- |
| `scalar` | `demo` | `demo -n1`; 16 integer points / 64 bytes, inherited exact comparison and complete ordered execution stages. |
| `scalar` | `reopen-cold`, `reopen-warm` | `reopen -n1 -i2`; one point in each of two complete sessions, with `XRTSIM_WARM_OPEN=0` or `1`. These are local-shim cold/warm requests. |
| `scalar` | `axi-store-order` | `stencil3d -n64 -b2`; all 64-cubed outputs, original six-ULP reference bound, reorder seed 1, requested stall 6, and one positive measured response-reordering count. |
| `units` | `cp-llc-port` | Command-processor/LLC ordering harness; all six source test functions, independent dedicated read results, all 48 submitted first-word burst values, and completed read/drained traffic checks before success. |
| `units` | `mm-axi-arb` | All 13 original checks: eight random-backpressure seeds, four data-before-address seeds and the 1,000-write throughput check; original cycle bounds remain unchanged. |
| `gemm-fp16` | `gemm-fp16` — optional | Native TFR FP16-to-FP32 GEMM, `64 × 64 × 64`, eight threads, issue width two, one iteration, unchanged reference comparison. |
| `gemm-bf16` | `gemm-bf16` — optional | Native TFR BF16-to-FP32 GEMM, `64 × 64 × 64`, sixteen threads, issue width one, one iteration, unchanged reference comparison. |

All groups carry RV64, one cluster, one core and four warps. Scalar and unit
groups carry four threads, issue width one, `VX_CFG_FPU_TYPE_STD` and
`VERILATOR_RESET_VALUE=1`. Tensor groups retain their explicit TFR/STD/type flags
and do **not** inherit the scalar reset-one override. Both GEMMs retain the
original strict relative-error bound `< 0.01` and exact zero-pair acceptance.
Case-specific cold/warm and memory-stress environment values do not carry into
other cases. Default selection creates two generated groups; all eight cases
create four. The selected fixed records and their oracles are in
[`local_qualification_cases.py`](../../ci/project/local_qualification_cases.py).

The current [CP/LLC harness](../../hw/unittest/cp_llc_port/main.cpp) retains all
37 original assertion sites and adds seven. Its dedicated two-read test counts
accepted upstream requests and completed DMA responses before comparing both
returned data/tag pairs with independent expectations. The burst check covers
all 48 submitted first-word address/value pairs; a final total-read equality
also detects missing later completions. These checks do not establish every
read's unique identity, independent later-read values, all-word integrity or
response-backpressure coverage. The handoff distinguishes the earlier original
harness run from the separately committed and executed strengthened version.

## 4. Plan, inspect, then execute

Groups and cases run sequentially. The compile worker count is one or two and
also bounds nested Make/CMake settings. The fixed CLI ceilings apply to **each
monitored command**, including configure, preparation, build and launch:

| Budget | Default and permitted direction |
| --- | --- |
| Compile workers | `--jobs 2`; select 1 or 2. |
| Command duration | `--timeout-seconds 1800`; may be tightened, never raised above 1,800 seconds. |
| Sampled process-group RSS | `--max-rss-gib 6`; may be tightened, never raised above 6 GiB. |
| Combined stdout/stderr retained per command | `--max-log-mib 16`; may be tightened, never raised above 16 MiB. |
| Free-disk reserve on monitored filesystems | `--min-free-gib 15`; may be increased, never reduced below 15 GiB. |

These are polled budgets, not hard memory or filesystem quotas. RSS can count
shared pages more than once, excludes page cache, and can miss peaks between
samples. Host available RAM is not a certified container/cgroup allocation.
Descendants that deliberately leave the process group are outside its
containment. Termination and output cleanup add bounded overhead; a per-command
deadline is not a whole-run deadline. Input inventories, snapshots and multiple
sequential commands also contribute to elapsed time. Keep debug, waveform and
performance collection off.

Every configure/build/workload child receives
`TMPDIR=<fresh build-root>/tmp`. Inherited `TMPDIR`, `TMP` and `TEMP` are removed
before that value is installed. Run mode creates this private directory with
mode `0700` before its first command, on the monitored build filesystem. Plan
mode records the path without creating it. This prevents child compiler
temporary files from silently falling back to a smaller `/tmp` filesystem; it
does not turn the polled disk reserve into a hard quota. Parent-side inventory
probes are separate from this child temporary-directory contract.

```bash
AI_GPU_ARGS=(
  --source "$AI_GPU_SOURCE"
  --tool-dir "$AI_GPU_TOOLS"
  --dependency-source "$AI_GPU_DEPS"
  --header-dir "$AI_GPU_HEADERS"
  --build-root "$AI_GPU_BUILD"
  --output "$AI_GPU_OUTPUT"
  --jobs 2
  --min-free-gib 15
  --max-rss-gib 6
  --max-log-mib 16
  --timeout-seconds 1800
)
AI_GPU_CASES=(
  --case demo --case reopen-cold --case reopen-warm
  --case axi-store-order --case cp-llc-port --case mm-axi-arb
  --case gemm-fp16 --case gemm-bf16
)

python3 -B "$AI_GPU_SOURCE/ci/project/local_qualification.py" plan \
  "${AI_GPU_ARGS[@]}" "${AI_GPU_CASES[@]}" \
  > "$AI_GPU_WORK/plan-01.json"
```

Proceed only if the command exits zero and the plan has no blockers, the intended
selected IDs/configurations, expected input identities and sufficient resources.
A plan's `outcome: pass` means prerequisites passed; its cases remain `not_run`.
Planning performs read-only inventories and bounded version/frontend probes, not
GPU builds or workloads. It creates neither build nor packet directories.

```bash
python3 -B "$AI_GPU_SOURCE/ci/project/local_qualification.py" run \
  "${AI_GPU_ARGS[@]}" "${AI_GPU_CASES[@]}" \
  > "$AI_GPU_WORK/run-01.stdout.json" \
  2> "$AI_GPU_WORK/run-01.stderr.log"
```

`run` recomputes its plan from live inputs; it does not consume `plan-01.json`.
Keep inputs and the effective `PATH` unchanged between the two commands. For
core-only coverage, omit `"${AI_GPU_CASES[@]}"` from **both** invocations. The
runner exits zero only when its overall `outcome` is `pass`; otherwise it exits
nonzero. A failing command, oracle or identity check stops subsequent work.

## 5. Understand the execution stages

The runner configures each generated group with
`--xlen=64 --osversion=ubuntu/focal`. It executes generated-tree recipes rather
than source templates. Stage IDs in `commands` and `active_command` have these
meanings:

| Stage ID | Work performed; what success establishes |
| --- | --- |
| `<group>-configure` | Creates the selected generated tree; subsequent generated-input inventory checks copied recipes and configuration against the frozen source. No workload has run. |
| `<group>-kernel`, `<group>-stub` | App groups build the kernel libraries and runtime stub. Unit-only groups omit these stages. Success is preparation evidence. |
| `<case>-runtime` | App-only `make -j<jobs> -C tests/regression/<app> runtime-xrt TARGET=xrtsim` prepares the runtime through that application's recipe and canonical destination. |
| `<case>-build` | Builds the selected app with `TARGET=xrtsim`, or the selected unit. Captures declared artifact identities and text stamps before launch. |
| `<case>-run` | Launches generated `./ci/blackbox.sh --driver=xrt --target=xrtsim ...` for an app, or `make ... run` for a unit. The wrapper can rebuild; child creation alone does not prove workload completion. |
| Post-launch checks | Require a passing bounded command, exit zero, completed cleanup, identical pre/post artifacts, and the fixed case's output oracle before recording its pass. |
| Final identity check | Rechecks source/tools/dependencies/host/headers/helpers and all generated inventories before overall success. |

Application preparation and launch must use the same canonical runtime
destination. Directly prebuilding `sw/runtime/xrt` with a different `DESTDIR`
spelling can change its stamp during blackbox launch and invalidate the attempt.
The runner already uses the app's `runtime-xrt` target to avoid that mismatch.
Do not add a separate `make -n` as an assumed inert check: parsing some recipes
can invoke Verilator or write a cache.

`configure` does not copy `sw/runtime/xrt/xsim.tcl` into the build tree. The
generated XRT INI references the source hook, which the runner retains for app
selections. A missing generated Tcl copy is expected. Its presence as an input
does not establish that XSim or vendor emulation executed.

## 6. Interpret the report without promoting partial evidence

The packet has a checkpointed `report.json`, combined command logs under
`logs/`, and byte-preserving text snapshots under `artifacts/`. It retains the
executing helper closure and lock, selected source inputs, generated recipes and
configuration, and relevant prelaunch stamps. Declared binary/library identities
are recorded, but this is not a complete binary archive. Compiler records are
retained for independent review; this runner does not claim generic
[compiler-record validation](p01-compiler-records.md).

| Field or result | Meaning |
| --- | --- |
| `state: planned` | A prerequisite inventory exists. A passing plan is not execution. |
| `state: running`, `active_command` | A checkpoint names work being attempted. Read the active log and process state; this is not a final disposition. |
| Command `process_started: true` | The monitored child was actually created. A prelaunch refusal or failed launch remains false. This is not an output-oracle result. |
| Report `execution_performed` | At least one monitored command started, possibly only configure/build. Inventory probes are not counted as workload execution. |
| Report `workload_command_started` | At least one workload wrapper started. Its rebuild can still fail before the workload runs. |
| Report `workload_execution_verified` | At least one selected case passed command, cleanup, stable-artifact and output-oracle checks. This is **not** an all-cases flag. |
| Case `outcome: pass` | That particular case satisfied its retained checks; consult its `observations` and `command_id`. |
| Case `outcome: fail` | A failure occurred while processing that case; it may have occurred during preparation, launch, comparison or identity checking. Read the reason and command evidence. |
| Case/command `outcome: not_run` | No completed evaluation is recorded. In an active checkpoint this is an unfinished placeholder, not proof that no child is currently executing. After an earlier stop, later cases remain unexecuted. |
| `outcome: blocked` | A prerequisite or pre-execution requirement prevented qualification; inspect `blockers`/`reason`. It is not a pass. |
| `state: finished`, overall `outcome: pass`, all selected cases passing | The entire selected local matrix completed under the retained contract. Independent review and the stated scope limits still apply. |

Aggregate execution flags are updated when a monitored command returns, so a
running checkpoint can lag the active process and log. Require the finished
record, final exit and cleanup results before reporting an attempt's outcome.
`vendor_execution_performed`, `qualifies_P01_A03` and `phase_complete` remain
false for this supplemental route, including when all selected cases pass.

The runtime's ten-second command-processor polling warning is not a terminal
result. Without an explicit runtime poll-timeout override it is warn-only; it
does not measure instruction progress. Its diagnostic wording and sampled
status cannot establish either idle hardware or continued productive execution.
Use the bounded command's final result, numerical/reordering oracle and
post-launch identity check; keep the declared command cap in force.

Command records contain exit codes, duration/RSS observations, retained log
sizes/hashes and cleanup status. Individual snapshots are capped at 2 MiB, the
normal report at 8 MiB, and the retained packet at 512 MiB. A failed final report
checkpoint can leave `failure.json`; inspect it before treating an earlier
`report.json` checkpoint as final. Preserve the runner's stdout/stderr and final
process exit even when the normal report could not be retained.

## 7. Verify raw evidence and public copies separately

Preserve raw packets unchanged. Stdout substitutes declared root paths, but it
is not a fully sanitized publication packet. Raw reports, logs, snapshots and
other environment paths can contain local details. Review a separate public
copy and retain a reproducible mapping to the originals.

For a **finished raw packet**, recompute file sizes and SHA-256 identities:

1. Hash the raw `report.json` and compare it with the attempt's handoff anchor.
2. For each command with a retained log identity, compare the actual file at
   `commands[].log` with `log_size_bytes` and `log_sha256`.
3. For every snapshot, compare its `retained.path` with `retained.size_bytes`
   and `retained.sha256`. Its retained size/hash must also match the recorded
   source size/hash because raw snapshots preserve bytes.
4. For each passing case, require `artifacts_before == artifacts_after`. If the
   build tree is still retained, rehash those relative paths under
   `<build-root>/<case.group>` against the records. A packet containing only
   binary identities cannot independently recreate missing binary files.
5. Review selected IDs, exact source/tree, completed commands, oracles, final
   checks, failure records and omissions. Identity equality alone is not a
   numerical or native-selector review.

These read-only commands show individual raw anchors without modifying files;
repeat the log command for the paths actually declared in the report:

```bash
sha256sum "$AI_GPU_OUTPUT/report.json"
sha256sum "$AI_GPU_OUTPUT/logs/demo-run.log"
wc -c < "$AI_GPU_OUTPUT/logs/demo-run.log"
```

Only run the example log check if that case produced the named log. Missing,
unfinished or unrecorded logs must be explained, never substituted by a later
attempt. Check the whole packet using the reviewed verifier supplied with the
handoff when available.

For a **public packet**, the publication manifest maps each original file's
`raw_sha256` / `raw_size_bytes` to the distributed file's `public_sha256` /
`public_size_bytes`, with the transformation and replacement counts. A path
substitution changes bytes and usually changes the hash. Embedded raw log and
snapshot hashes in `report.redacted.json` still identify the **raw originals**;
compare a distributed log with its manifest **public** hash. Do not rewrite
embedded evidence hashes, results, source identities or execution flags to fit
the redacted bytes. The canonical raw-report mapping is the manifest row for
`report.redacted.json`, not the separately retained stdout copy.

The [published evidence index](evidence/p01-local-qualification/README.md) and
the [handoff's evidence table](p01-local-qualification-handoff.md#published-evidence-and-verification-inputs)
name the final archive, manifest, member index, identity map, retained review
records and both publication helpers. The
[SHA256SUMS inventory](evidence/p01-local-qualification/SHA256SUMS) supplies
the actual distributed archive and verifier-file digests; do not substitute an
earlier staged-export hash for a final artifact. The manifest and verifier
output supply the distinct public-member and bundle identities described by the
evidence index.

Use the distributed
[`export_final_packets.py`](evidence/p01-local-qualification/export_final_packets.py)
with the adjacent unchanged
[`export_local_packets.py`](evidence/p01-local-qualification/export_local_packets.py)
dependency. The final helper checks the complete archive, including the two
native attempts, the committed two-unit follow-up, nonqualification diagnostics
and reviews. The earlier helper verifies only its native-attempt packet format.
These publication-side helpers are not subcommands of `local_qualification.py`
or general exporters for arbitrary new runs. Both accept their corresponding
readable directories and deterministic gzip/tar archives. After checking the
distributed files against their recorded SHA-256 identities, use:

```bash
AI_GPU_EVIDENCE='/absolute/source/AI-GPU/docs/project/evidence/p01-local-qualification'
AI_GPU_EXPORTER="$AI_GPU_EVIDENCE/export_final_packets.py"
AI_GPU_PUBLIC="$AI_GPU_EVIDENCE/packet.tar.gz"
AI_GPU_RAW_WORKSPACE='/absolute/original-attempt-workspace'

(cd "$AI_GPU_EVIDENCE" && sha256sum -c SHA256SUMS)
python3 -B "$AI_GPU_EXPORTER" verify "$AI_GPU_PUBLIC"
python3 -B "$AI_GPU_EXPORTER" verify "$AI_GPU_PUBLIC" \
  --raw-workspace "$AI_GPU_RAW_WORKSPACE"
```

Use the second verification invocation only where the original workspace and
its required mapping/sidecars remain available. Public-only verification checks
distributed integrity and recorded linkage; adding `--raw-workspace` also
reconstructs and compares the transformation from the original evidence. The
manifest inventories every packet member except itself; the verifier's
bundle digest includes member names, sizes and hashes, including the manifest.
Compare the evidence index's manifest, bundle and archive anchors separately.
The manifest is unsigned. Hash checking does not authenticate the original
execution, establish vendor qualification, or replace independent review.

## 8. Preserve failures and make retries distinct

Keep blocked and failed attempts, logs, source/input identities and publication
anchors. Never rerun over an existing build, packet, stdout, stderr or plan
file. A justified retry uses new names such as `build-02`, `run-02`,
`plan-02.json`, `run-02.stdout.json` and `run-02.stderr.log`. Record the prior
failure, diagnosis, exact correction, changed identities and unchanged
contract before retrying. New source must be committed and clean before the
runner can inventory it as a qualifying input. A later pass does not erase an
earlier failure.

Do not reduce dimensions, alter fixed seeds, relax numerical tolerances, suppress
warnings-as-errors or loosen the declared budget to obtain a pass. Changes to
the contract or operational policy need their own documented reason and review.
Tooling/governance test outcomes remain source/tooling evidence; hosted CI
outcomes require an actual observed hosted run at its delivered revision.

Record the final source commit/tree, selected cases, command and per-case
outcomes, measured resources, packet anchors, independent review, failures and
remaining gaps in the [handoff](p01-local-qualification-handoff.md). Leave this
guide's procedure independent of the latest execution result. P01-A03 and
physical-hardware qualification remain separate obligations under the
[acceptance policy](acceptance.md).

Implementation references:
[`local_qualification.py`](../../ci/project/local_qualification.py),
[`local_qualification_cases.py`](../../ci/project/local_qualification_cases.py),
[`local_qualification_inventory.py`](../../ci/project/local_qualification_inventory.py)
and [`baseline_process.py`](../../ci/project/baseline_process.py).
