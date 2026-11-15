# Hardware target and realization plan

**Current evidence: source inspection only.** This setup has not selected or
purchased a board, produced a validated bitstream, measured external memory, or
fabricated silicon. The [baseline](baseline.md) records inherited capabilities;
[roadmap.json](roadmap.json) owns the phase gates and their completion state.

## 1. Select one reproducible target

The first physical milestone is one supported FPGA platform running the frozen
native AI configuration and tiny-model workload. Prefer evaluating the inherited
Xilinx/AMD XRT path first; this is an engineering direction, not a board purchase
or a guarantee that every listed card works. The inherited
[FPGA guide](../fpga_setup.md) marks Intel/OPAE as deprecated and unmaintained.

Before implementation, record these decisions under the
[decision log](decisions.md). Role names express responsibility, not assigned staff.

| Decision | Required evidence before commitment | Accountable role |
|---|---|---|
| Board, device and host | Exact part/revision, authorized access, host PCIe and power/cooling compatibility | FPGA platform lead |
| Platform and tools | Supported shell/platform, firmware, runtime and compiler versions; tool-license access | FPGA platform lead |
| AI configuration | ISA width, native tensor backend, enabled formats, core/warp geometry, caches and shared-memory budget | Compute architecture lead |
| External memory | Accessible banks, addressing, usable capacity, reserved ranges and controller/PHY ownership | Memory lead |
| Implementation budget | Available disk/RAM, bounded jobs, timing/resource target and allowed build duration | FPGA platform lead |
| Validation workload | Fixed model/operator fixtures, correctness contracts and measurement protocol | Verification lead |

Do not announce memory capacity, clock speed, TOPS, power, process node or delivery
dates before the corresponding configuration and evidence exist.

## 2. Real memory is a system, not a simulator setting

The existing [memory fabric](../../hw/rtl/mem/),
[cache hierarchy](../designs/cache_subsystem.md),
[DXA engine](../designs/dxa_async_copy_multicast.md) and
[AFU shell](../designs/fpga_afu_shell.md) are reusable foundations. The FPGA
platform supplies the physical PCIe and memory interfaces. GPU RTL is not by
itself a DDR/GDDR/HBM controller, physical-layer interface (PHY), or package.

The integration contract must specify:

- Host-to-device/device-to-host DMA, alignment, length limits, completion and
  error semantics; command-ring visibility and any host-memory bridge setup.
- Device address width, bank mapping, allocation limits and reserved ranges;
  accesses near every boundary must be tested rather than inferred from a card's
  advertised memory capacity.
- Cache visibility, fences and synchronization between compute and DMA. Preserve
  the inherited coherence requirements when adding cores or clusters.
- Memory/controller reset and initialization, outstanding-request drain,
  backpressure, timeout recovery, and available ECC/error reporting.
- Separate measured useful payload bandwidth from bus peak bandwidth; record
  transfer direction, size, banks, cache state and achieved clock.

Existing platform descriptors need target-specific review:
[U250](../../hw/syn/xilinx/platforms/u250.toml) currently binds DDR bank 0;
[U200](../../hw/syn/xilinx/platforms/u200.toml) flags incomplete memory-offset
handling. The [V80 path](../xilinx_slash_setup.md) requires SLASH/AVED and has its
own host-bridge constraints. These are selection risks, not new support claims.
DXA's tiled global-to-shared copies must not be described as a general replacement
for bidirectional host DMA.

## 3. P07 — physical FPGA acceptance

Preparation may investigate platform access earlier, but phase completion obeys
the dependencies and exact criteria in [roadmap.json](roadmap.json).

1. **Freeze readiness — P07-A01.** Record source and submodule commits, toolchain
   identity, board/platform/firmware, configuration, memory map, constraints,
   bitstream hash, utilization and post-route timing. Read the achieved clock:
   the [XRT Makefile](../../hw/syn/xilinx/xrt/Makefile) permits frequency
   downscaling by default. A successful build is not proof of the requested clock.
2. **Exercise the full path — P07-A02.** Verify host enumeration, authorized
   programming, reset and device open; DMA round trips; bank/address boundaries;
   repeated allocation/free; native tensor GEMM, attention and the fixed model.
   Compare against the frozen numerical references, including repeated runs and
   failure cases. Retain logs identifying the actual physical device.
3. **Measure stable operation — P07-A03.** Run the canonical initial soak and
   capture throughput, resets/errors, temperature and power where instrumentation
   supports them. Explicitly mark unavailable telemetry; do not manufacture a
   watts or efficiency result. Unexplained errors block phase exit.

Use the [FPGA guide's](../fpga_setup.md) explicit
`--driver=xrt --target=hw` runtime selection for physical XRT tests, with a matching
hardware bitstream. `TARGET=hw` is the build setting; exporting it alone does not
select hardware in `blackbox.sh`. `rtlsim`, XRT simulation and `hw_emu` remain
simulation evidence. Device identity, target selection and successful physical
execution are required for `fpga_measured`.

The AFU design documentation lists synthesis-hardening work as proposed. Resolve
that documentation against current source and actual reports; neither the note
nor a bitstream filename substitutes for implementation evidence. Keep builds and
large traces within the [resource policy](developer-guide.md).

## 4. P10 — ASIC feasibility is a separate go/no-go gate

The inherited [synthesis flows](../synthesis_analysis.md) and
[Yosys](../../hw/syn/yosys/) / [Synopsys](../../hw/syn/synopsys/) scripts support
analysis, not an automatic manufacturing commitment. Predicted power/performance/
area, black-box SRAM estimates and predictive-library results are not silicon
measurements. A generated GDS file alone is not foundry sign-off.

| Gate | Required feasibility package |
|---|---|
| P10-A01 | Qualified foundry/PDK access; real SRAM macros; PCIe and selected memory controller/PHY IP; package/interposer strategy where applicable; tool and IP licenses; written availability/cost evidence and responsible owners |
| P10-A02 | Bounded architecture and memory target; verification/formal and CDC/reset plans; scan/DFT/MBIST; timing across qualified corners; power/IR-drop/electromigration; DRC/LVS and package/board sign-off plans; explicit estimated-versus-qualified report labels |
| P10-A03 | Human-approved scope, funding, schedule, partners, procurement and risk disposition before tapeout commitments |

HBM would introduce controller/PHY, package, assembly, thermal and supply-chain
dependencies; it is not a software upgrade. A smaller inference ASIC may proceed
without P09 training/multi-device research, but not without P10 approval. No agent
may authorize fabrication, paid IP, board orders or partner commitments.

## 5. P11 — manufactured silicon and board bring-up

After the approved P10 decision, complete foundry-qualified verification and
physical sign-off, manufacturing test insertion and reviewed exceptions before
an explicitly authorized tapeout (**P11-A01**). Plan the package and board together:
power rails/sequencing, clock/reset, signal integrity, memory routing, connectors,
debug access, protection, cooling and production test access are part of the design.

Bring-up proceeds from safe power/clock/reset checks to memory initialization,
host enumeration, DMA and compute tests (**P11-A02**). Record board/die revisions,
test conditions, failures and recovery steps. Run the frozen model suite on the
actual silicon and publish measured limits, performance, power and yield evidence
with appropriate uncertainty (**P11-A03**). FPGA success, synthesis estimates and
ASIC feasibility approval cannot satisfy `silicon_measured` criteria.

Use the [acceptance policy](acceptance.md), [verification plan](verification.md)
and [release policy](releases.md) to review each evidence package. Missing hardware,
licenses, instrumentation or authority means **blocked/not run**, never passed.
