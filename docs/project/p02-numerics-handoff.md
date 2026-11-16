# P02 numerical contract and executable fixtures

This continuation implements P02-T01 and starts the focused verification work
for P02-T02. The phase remains `in_progress`; its authoritative acceptance
entries are in [roadmap.json](roadmap.json). P01's vendor `hw_emu` obligation
remains separate and blocked.

## What is implemented

- The [versioned numerical specification](../designs/tensor_numerics_v1.md)
  and [machine manifest](../../ci/project/p02_tensor_contract.json) freeze the
  native TFR FP16/BF16-to-FP32 four-product unit profile and comparison rules.
- The [independent producer](../../ci/project/p02_fixture_oracle.py) derives
  [98 deterministic fixtures](../../ci/project/fixtures/p02_tfr_v1.json) using
  integer and rational arithmetic. It records exact-real references separately
  from the specified fixed-window results. No production arithmetic model
  generates the expected outputs.
- The [runnable application profile](../../profiles/p02-tfr.json) freezes
  the first ordinary WMMA application geometry and native arithmetic settings.
  Twenty [independent layout fixtures](../../ci/project/fixtures/p02_layout_v1.json)
  define matrix storage, packed input words and exact outputs at FEDP and tile
  boundaries. Their source checks are separate from device execution.
- The [strict unit harness](../../hw/unittest/tcu_contract/main.cpp) consumes
  the same frozen bits through native RTL or the production model function.
  It checks signed zero, NaN bits, rounding, cancellation, subnormals, finite
  extremes and packed lanes. Its stall mode checks the leaf pipeline's enable
  behavior; it does not exercise WGMMA scheduling.
- The native [tensor API](../../sw/kernel/include/vx_tensor.h) rejects TFR
  input formats that are absent from the compiled configuration when WMMA or
  WGMMA contexts are instantiated. This is a C++ compile-boundary contract;
  raw unsupported instructions do not acquire a hardware trap.

The distinct historical P01 application geometries and tolerances are preserved.
The new BF16 four-product unit profile must not be presented as the historical
eight-product BF16 application configuration.

## Reproduce the checks

From the source root, check the frozen artifacts and the offline tests:

```sh
python3 ci/project/p02_fixture_oracle.py --check
python3 ci/project/p02_layout_fixture_oracle.py --check
python3 -m unittest discover -s ci/project -p 'test_p02_*.py'
python3 ci/project/check_project.py
```

The full offline suite is `python3 -m unittest discover -s ci/project -p
'test_*.py'`. Native C++ model checks require a C++17 compiler and UBSan; they
do not execute a full SimX processor.

For native RTL, configure a fresh RV64 build tree with the recorded Verilator
tool bundle. Run generated Makefiles from that build tree. Use two workers,
keep at least 15 GiB free, and keep waveform/debug output disabled. The
[specification](../designs/tensor_numerics_v1.md#8-reproduction-and-evidence-levels)
records the fixed build settings and detailed commands.

## Review and execution state

The implementation is undergoing independent review and bounded validation.
Diagnostic runs from a changing working tree are not a frozen-source
acceptance packet. Final reviewed evidence will name the actual tested commit,
configuration, command exits, artifact hashes, omissions and retained failures.

## Next bounded action

Advance P02-T02 by extending these independent fixtures to whole-processor
WMMA application execution on both SimX and native processor RTL. Freeze and
test the actual application reduction widths, matrix layouts, tile boundaries
and multi-instruction K accumulation. Then exercise WGMMA synchronization,
descriptor/metadata handling, multiple warps and backpressure with applicable
model-parity evidence. Leaf enable stalls cannot satisfy those obligations.

P03 remains `not_started` until all P02 exit obligations are met. Preserve
P01-A03's blocked vendor integration evidence and the P07 dependency.
