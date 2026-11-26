# P08 Threat Model, Soak Protocol, and Experimental Release Package

**Phase status: `not_started`** in [roadmap.json](roadmap.json). This document is
**preparatory governance and verification engineering** for [P08](phases/p08-reliability.md)
(`P08-A01`, `P08-A02`, `P08-A03`). It defines the threat/failure model, the
24-hour physical soak protocol, and the experimental release checklist. Creating
these specifications and the companion validator
[`p08_release_tools.py`](../../ci/project/p08_release_tools.py) does **not**
execute physical hardware tests, replace [P07](phases/p07-fpga.md) or
[P01-A03](phases/p01-baseline.md), or advance `P08` past `not_started`.

Follow [the acceptance policy](acceptance.md), [verification strategy](verification.md),
[release policy](releases.md), [risk register](risks.md) (especially RK-006,
RK-015, and RK-017), and [SECURITY.md](../../SECURITY.md).

---

## 1. Trust boundary and explicit threat/failure model (P08-A01)

AI-GPU is an experimental Vortex-derived accelerator prototype, not a production
multi-tenant GPU or a safety-critical controller. Under
[SECURITY.md](../../SECURITY.md), kernels, model importers, build inputs,
runtime components, and bitstreams are **trusted inputs** unless a release
explicitly proves a stronger boundary.

### 1.1 Implemented vs. unsupported isolation guarantees

| Boundary | Implemented / planned enforcement | Unsupported / out-of-scope claims |
|---|---|---|
| Host process & native runtime | Explicit input validation (`contract.h`, `vortex2.h`, `vortex_ai`), bounded copies, no silent CPU matmul fallback | Multi-tenant OS isolation, hostile/untrusted kernel sandboxing, arbitrary host-pointer dereference protection without platform IOMMU |
| Device memory & DMA | Pairwise disjoint range checks, 4-byte alignment checks, representable address-width checks (`VX_CFG_XLEN` / 48-bit RV64 aperture), explicit allocation extents | Hardware MMU per-tenant virtual isolation across arbitrary untrusted kernels (unless VM/IOMMU is separately configured and qualified on target hardware) |
| Asynchronous completion | `AsyncRun` serial ownership, sticky terminal failure on processor exceptions, `VX_ERR_TIMEOUT` non-destructive retry | Preemptive hardware kernel cancellation, safe forced thread killing, recovery of a terminally faulted SimX process without context/process restart |
| Framework & Python binding | `p05-torch-custom-ops-v1` rejects `requires_grad`, CUDA/meta/FakeTensor, mismatched layouts, and concurrent/reentrant callers; native loader verifies bundle SHA-256 | Zero-copy sharing, fork-safe runtime reuse, arbitrary model execution, CUDA binary compatibility |

### 1.2 Required P08-A01 fault classes

Physical fault-injection qualification for `P08-A01` MUST exercise and pass all
five canonical fault classes defined in
[`p08_release_tools.py`](../../ci/project/p08_release_tools.py)
(`fault-matrix-check`). Missing a class or recording an unexplained/failing case
blocks `P08-A01`.

1. **`malformed_args` — Malformed kernel and operator arguments**
   - **Vectors:** Unaligned device or host buffer offsets (non-4-byte aligned);
     overlapping A/B/D buffer ranges (including read-only A/B aliasing);
     zero-address (`0x0`) or unmapped/null device pointers; unsupported dtypes
     (e.g., mixed FP16/BF16, FP8/INT4 when disabled in `p02-tfr`), unsupported
     shapes/ranks/strides, non-zero initial C, corrupt `MatmulArguments`
     `abi_version`/`byte_size`/`reserved` fields, and zero-byte or overflowing
     size calculations.
   - **Expected behavior:** Synchronous or pre-launch rejection (`invalid_argument`,
     `unsupported_dtype`, `unsupported_shape`, `VX_ERR_INVALID_VALUE`, or
     `ValueError`/`TypeError`/`BindingError`) before any device DMA or kernel
     execution; destination buffer retains poison/prior bytes; zero stale
     completions; no silent CPU fallback.

2. **`resource_exhaustion` — Memory, handle, and queue exhaustion**
   - **Vectors:** Device allocation beyond usable `VX_CAPS_GLOBAL_MEM_SIZE` or
     bank capacity (`VX_ERR_OUT_OF_DEVICE_MEMORY`); host staging/scratch
     `std::bad_alloc` (`VX_ERR_OUT_OF_HOST_MEMORY`, as exercised in
     [`test_ai_lifecycle.cpp`](../../tests/runtime/test_ai_lifecycle.cpp));
     repeated allocate/free and queue/event create/release loops under memory
     pressure; exceeding queue ring/event capacity.
   - **Expected behavior:** Explicit allocation/exhaustion error returned to
     caller; prior valid buffers remain uncorrupted; intermediate staging is
     unwound with zero leaked device/host allocations (`vx_device_memory_info`
     returns to baseline free bytes after cleanup); healthy subsequent work
     succeeds once pressure clears.

3. **`error_propagation` — Asynchronous simulator/device exceptions and timeouts**
   - **Vectors:** Asynchronous device/memory exceptions (`OutOfRange`,
     `BadAddress` in [`mem.h`](../../sim/common/mem.h) / hardware bus error on
     FPGA); `VX_ERR_TIMEOUT` on `vx_queue_finish` / `vx_event_wait_value` /
     `operation.wait`; failed dependency events (`VX_ERR_EVENT_FAILED`);
     device loss (`VX_ERR_DEVICE_LOST`) or XRT execution error.
   - **Expected behavior:** Failures propagate deterministically through
     `AsyncRun`, CP completion polling, `vx_queue_finish`, and `vx_event_wait_*`
     without retiring the failing launch as success (following
     [simulator completion contract v1](../designs/simulator_completion_v1.md)).
     Repeated waits retain the terminal error; timeouts remain retryable without
     forging output or releasing active native ownership prematurely.

4. **`reset_recovery` — Reset and recovery after fault**
   - **Vectors:** Controlled fault injection followed by queue drain/close,
     device release/re-open, and XRT/FPGA platform reset (`xbutil reset` or
     runtime device reset where supported); host `SIGINT`/`SIGTERM` interruption
     mid-operation and cleanup verification.
   - **Expected behavior:** Outstanding work has a defined disposition (aborted,
     drained, or explicitly closed—never silently re-used); clean teardown
     leaves no hung host threads or poisoned global accounting; a **fresh
     workload** submitted after recovery executes and matches its frozen
     numerical reference bit-for-bit. Failing traces and registers are preserved
     for root-cause analysis.

5. **`memory_isolation` — Host↔device and allocation-boundary isolation**
   - **Vectors:** Out-of-bounds DMA read/write/copy past buffer extent or across
     FPGA DDR/HBM bank boundaries; unaligned or boundary-straddling transfers;
     canary/guard-band buffers placed adjacent to A, B, and D allocations;
     illegal access to host-only (`VX_MEM_HOST`) vs. device-only buffers and
     reserved platform aperture addresses.
   - **Expected behavior:** Out-of-bounds requests are rejected by runtime
     bounds checks; on physical hardware, adjacent canary words and unrelated
     host/device buffers remain bit-identical before and after every kernel and
     DMA operation; no stale data leaks across freed/reallocated buffers without
     explicit initialization or poison write.

---

## 2. Canonical 24-hour physical soak protocol (P08-A02)

`P08-A02` requires a continuous **24-hour (`>= 86,400 s`) physical FPGA soak**
on the exact frozen board, shell/firmware, bitstream hash, achieved clock, and
supported software stack qualified in [P07](phases/p07-fpga.md).

### 2.1 Execution rules and stop conditions

- **Driver and target requirement:** Must execute on physical hardware
  (`driver: "xrt"`, `target: "hw"` or explicitly named physical board backend).
  Simulators (`simx`, `rtlsim`, `xrtsim`, `gem5`, `firesim`) and vendor
  emulation (`hw_emu`) are **strictly rejected** by
  `ci/project/p08_release_tools.py soak24-analyze`.
- **Minimum duration:** Continuous elapsed wall-clock duration MUST be
  `>= 86,400` seconds (24 hours). Do not stitch together shorter runs, shorten
  the soak, or drop failing iterations.
- **Zero unexplained errors:** Every iteration must check numerical outputs
  against the frozen P02/P04 reference or bit-exact oracle, verify allocation
  watermarks (zero net leak), and verify queue/event completion. Any
  unexplained numerical mismatch, hang, stale read, unrecovered reset, or
  unaccounted error fails the soak (`unexplained_errors == 0` required).
- **Declared sustained-load matrix:** Interleave supported native matmul
  signatures (`(8,4,8)`, `(8,4,16)`, `(16,8,16)` in FP16/BF16), the P04
  fixed tiny-model workload, host↔device DMA transfers across usable bank
  boundaries, and periodic resource-pressure/allocation-churn cycles.
- **Thermal, power, and resource telemetry:** Sample timestamped device
  temperature (deg C), board power (W) where sensors exist, clock frequency
  (MHz), host RSS / device free memory, and iteration throughput at regular
  intervals (e.g., every 60 s). If a board sensor is physically unavailable,
  record `"unavailable"` explicitly—never fabricate watts or temperature.
- **Issue disposition:** Any expected/injected recovery test or observed
  recoverable environmental warning MUST carry an explicit disposition record
  with root cause and linked issue ID; unexplained errors are unconditionally
  disqualifying.

---

## 3. Experimental release checklist and provenance rules (P08-A03)

No artifact may use the **Hardened experimental FPGA release** label defined in
[releases.md](releases.md) until `P05`, `P07`, `P08-A01`, `P08-A02`, and all
items below pass and receive human maintainer sign-off.

### 3.1 Provenance, licensing, and exclusion rules

1. **Apache-2.0 provenance and Vortex attribution:** Retain root
   [LICENSE](../../LICENSE) (Apache-2.0), upstream Vortex attribution in
   [README.md](../../README.md), and third-party notices for redistributed
   components (see [P05 third-party notices](evidence/p05-python/THIRD_PARTY_NOTICES.md)).
2. **Protected asset integrity:** Verify the preserved README illustration
   [`docs/assets/img/vortex_framework_stack.svg`](../assets/img/vortex_framework_stack.svg)
   matches its canonical SHA-256
   `db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`.
3. **SBOM and non-redistributable exclusion:** Run
   `python3 ci/project/p08_release_tools.py sbom` to generate a reproducible
   JSON inventory of tracked files, submodules, packaging metadata, and licenses.
   - **Critical exclusion:** `third_party/ramulator` (MIT overall) contains
     `verilog_verification/sources/*` files carrying **Micron Technology, Inc.
     confidential/proprietary/all-rights-reserved** headers (e.g.,
     `ddr4_model.svp`, `MemoryArray.svp`, `StateTable.svp`, `StateTableCore.svp`,
     `tb.sv`, `timing_tasks.sv`, `readme.txt`), and `hw/syn/libs/` contains
     proprietary/restricted foundry/cell libraries (`cln28hpm/`, `cln28hpc/`,
     Nangate restricted-use notices). **Never bundle** flagged proprietary or
     non-redistributable files into public source archives, wheels, or release
     packets.
4. **Compatibility matrix alignment:** Publish the exact tested host OS/arch,
   Python/PyTorch pins (matching [pyproject.toml](../../pyproject.toml),
   [p05-python-compatibility.md](p05-python-compatibility.md), and
   [p05-torch-compatibility.md](p05-torch-compatibility.md)), XLEN, hardware
   profile (`p02-tfr`), FPGA board/shell/firmware/bitstream SHA-256, achieved
   clock, supported operator/model signatures, and explicitly unsupported paths
   (no CUDA binary compatibility, no training, no multi-tenant isolation).
5. **Clean-venv wheel install verification:** Build the source distribution and
   wheel in a clean environment pinned to `pyproject.toml`, install `vortex-ai`
   into a fresh isolated virtual environment (`python -I -B`), verify
   `vortex_ai.build_info()` and bundle checksum verification, and reproduce the
   declared smoke matrix without source-tree leakage.
6. **Governance & review sign-off:** Run full strict governance
   (`check_project.py` + `governance_run.py` zero-skip discovery), record
   independent review under [the code review policy](../review/code-review-policy.md),
   verify remote repository/branch state, and obtain explicit human maintainer
   approval before tagging or publishing.

### 3.2 Release sign-off checklist

- [ ] `P05` and `P07` (including `P01-A03`) are `complete` with accepted evidence in `roadmap.json`.
- [ ] `P08-A01` fault-matrix report passes `p08_release_tools.py fault-matrix-check` on physical FPGA (`fpga_measured`).
- [ ] `P08-A02` 24-hour soak report passes `p08_release_tools.py soak24-analyze` (`>= 86400 s`, physical hardware, `unexplained_errors == 0`).
- [ ] `p08_release_tools.py sbom` passes with protected SVG SHA-256 verified and zero non-redistributable/Micron/proprietary files included in release bundle manifests.
- [ ] Clean-venv wheel install and compatibility matrix reproduced and archived with SHA-256 digests.
- [ ] Independent review findings resolved and human maintainer release approval recorded.
