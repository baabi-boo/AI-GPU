# P07 — Physical FPGA prototype

**Goal:** prove real compute, external DRAM and host transfers on one selected
supported board. This is a realization plan, not a claim of hardware availability
or successful execution. Live state and canonical gates are in
[roadmap.json](../roadmap.json); the accountable role is FPGA platform lead.

## Entry and boundaries

- P01's complete baseline (including genuine vendor XRT `hw_emu` P01-A03),
  P04 native tiny-model inference and P06 memory/performance scaling must be
  accepted **before P07 can close**. Preparatory platform research may occur
  earlier without claiming an accepted result. P05 may proceed separately;
  Python is not required for this native demo.
- Record authorized board/host access, compatible platform/firmware, tool and
  runtime versions, required licenses, power/cooling and a reviewed build budget.
  Missing access or authority is a blocker, not permission to purchase hardware.
- Follow the [hardware plan](../hardware.md) and [FPGA setup](../../fpga_setup.md).
  A listed platform, compiled bitstream or emulation result does not demonstrate
  an operational physical target. No memory-capacity or clock claim is assumed.
- FPGA evidence does not establish ASIC readiness, production reliability,
  multi-tenant security or NVIDIA performance/compatibility.

## Ordered work packages

1. Select one supported, obtainable board through the [decision log](../decisions.md).
   Review host PCIe compatibility, usable memory banks/reservations, platform
   restrictions and ownership of physical memory/controller/PHY facilities.
2. Freeze the source/submodules, toolchain, AI configuration, platform, firmware,
   constraints and memory map. Reproduce implementation within bounded disk/RAM
   and job limits. Preserve logs, utilization, timing and bitstream checksum.
3. Read the achieved clock from implementation/runtime metadata. The inherited
   XRT flow allows frequency downscaling; a successful build does not establish
   its requested frequency. Resolve unmet timing against the frozen target.
4. On the authorized board, verify safe programming, host enumeration, reset and
   device open. Exercise host-to-device and device-to-host DMA, alignment/length
   constraints, completion/error behavior and repeated allocation/free.
5. Test usable address/bank boundaries and reserved-range rejection without
   accessing unrelated host/device memory. Check compute/DMA visibility, fences,
   synchronization, reset/recovery and available memory-error reporting.
6. Run native tensor GEMM, attention and the P04 model against frozen references.
   Retain device identity, actual execution target, dispatch/transfer records,
   repeated-run results and any failure. Do not substitute host or emulated work.
7. Complete the one-hour initial soak with zero unexplained numerical, transfer
   or reset errors. Capture timestamped throughput and available power/temperature
   telemetry. Mark unavailable instruments explicitly; do not infer watts or
   energy efficiency from specifications or synthesis estimates.

## Physical execution contract

For XRT, `TARGET=hw` selects a hardware **build**. Runtime selection must explicitly
use `--driver=xrt --target=hw` with its matching bitstream. Exporting `TARGET=hw`
alone does not select the physical backend in `blackbox.sh`.
Processor `rtlsim`, XRT simulation and `hw_emu` remain nonphysical evidence.
Equivalent non-XRT paths require equally explicit physical-device provenance.

## Deliverables and acceptance

| Gate | Required deliverable and proof | Evidence level |
|---|---|---|
| `P07-A01` | Approved target/readiness record; pinned platform, firmware, configuration, memory map, bitstream hash and achieved clock | `source_present` |
| `P07-A02` | Actual-board DMA, bank/address-boundary, tensor, attention and tiny-model results against frozen references | `fpga_measured` |
| `P07-A03` | Timestamped one-hour physical soak with no unexplained errors; throughput and telemetry measured or explicitly unavailable | `fpga_measured` |

Use the [acceptance](../acceptance.md) and [verification](../verification.md)
policies. Record raw logs and artifact hashes, device/board revisions, backend,
test commands, operating conditions and limitations; emulation cannot close
either physical-measurement gate.

## Stop conditions and handoff

Stop for unsafe power/thermal conditions, unavailable licenses/access, unexplained
corruption, hangs, reset failures or a mismatched platform/bitstream/configuration.
Do not suppress errors or quietly reduce the frozen acceptance workload.

Hand P08 the reproducible board setup, physical reports and known limitations;
its release hardening includes a separate 24-hour soak. Update [status](../status.md)
and [backlog](../backlog.md). Initial FPGA success does not authorize fabrication.
