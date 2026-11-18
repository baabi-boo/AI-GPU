# P02 WGMMA implementation and qualification handoff

The full witnessed processor matrix has finished with passing arithmetic,
metadata ordering and paired performance results at clean source
`4af2307e57202c1269e20f893267a5583ad3cba0`, tree
`42e5d6f2c9c0c2035c4d3ec8c86125e8cca45192`. The
[processor packet](evidence/p02-wgmma/processor/README.md) records 113 commands,
12 builds, 24 case executions, 48 launches and 24,576 exact output-word
comparisons. All 12 performance pairs pass with exact instruction counts; the
largest cycle difference is 1.356484%, within the unchanged 5% bound. The original
report SHA-256 is
`b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78`.

The separate directed native unit passed at clean source
`9006939aa123452b198bc0987e34aae8fab45fdd`; its
[reviewed packet](evidence/p02-wgmma/unit/README.md) retains nine commands,
eight groups, 392 accepted/committed transactions and 3,072 exact arithmetic
checks. Its 417-file RTL/harness bridge is unchanged at the processor source;
this preserves applicability without relabelling the historical unit execution.

The corrected original-packet verifier checked 1,103 files successfully.
Independent engineering and publication-integrity reviews support
[P02-A03 acceptance](evidence/p02-wgmma/processor/acceptance.json), record
`p02-a03-wgmma-4af2307-359a8c0`. P02-T02 and P02 are complete. P03 has now
started its separate [native operator contract](p03-operators-handoff.md). Consult [status](status.md), [phase](phases/p02-tensor.md)
and [canonical gates](roadmap.json) for acceptance state. P01-A03 vendor
integration remains a separate blocked gate required before P07.

The canonical A03 requirement remains: “WGMMA synchronization, metadata,
multi-warp and backpressure cases preserve correctness with no unexplained model
divergence.” The [historical proposal](p02-wgmma-validation-plan.md) records the
initial design. This guide describes the implemented checks and their boundaries.

## Frozen processor matrix

[p02_wgmma_matrix.json](../../ci/project/p02_wgmma_matrix.json) binds the fixture
producer, JSON corpus and C++ header by SHA-256. The new
[host adapter](../../tests/regression/p02_wgmma/main.cpp) executes the existing
dense and sparse WGMMA kernels without changing their source or argument ABI.

All variants use RV64, an empty profile, one cluster/core, eight threads per warp,
eight warps, issue width four, four TCU blocks, native TFR tensor arithmetic and
STD scalar floating point. LMEM is 16 KiB with eight banks; tensor latency is
four, DSP use is off, and FEDP2K, LDST_MATRIX and scaled formats are excluded.
ALU/LSU/FPU block counts are one. The format bank enables FP16 and BF16 support.
Use bare boolean `-DVX_CFG_*_ENABLE`/`_DISABLE` flags: integer `=1` spellings can
fail the inherited Makefiles' exact source-selection filters.

Every processor case has M=64, N=8, K=16, NRC8 and KUNROLL=1, with initial C=+0.
Grid `{1,2}`, block `{32,1}` and 640 bytes of dynamic LMEM provide two CTAs with
four warps each. Each warp contributes an 8×8 output tile over two K8 tiles.
Global dense A and B are row-major; the layout column below describes shared A.

| Configuration ID | Inputs and output | Mode / shared A | Exact fixture IDs |
|---|---|---|---|
| `dense-fp16-ss` | FP16 → FP32 | SS / block-major | `fp16-dense-signatures-a`, `fp16-dense-signatures-b` |
| `dense-fp16-rs` | FP16 → FP32 | RS / register A | `fp16-dense-signatures-a`, `fp16-dense-signatures-b` |
| `dense-bf16-ss` | BF16 → FP32 | SS / block-major | `bf16-dense-signatures-a`, `bf16-dense-signatures-b` |
| `dense-bf16-rs` | BF16 → FP32 | RS / register A | `bf16-dense-signatures-a`, `bf16-dense-signatures-b` |
| `dense-fp16-ss-row-major-a` | FP16 → FP32 | SS / row-major | `fp16-dense-signatures-a`, `fp16-dense-signatures-b` |
| `sparse-fp16-ss` | Sparse FP16 → FP32 | SS / compressed row-major | `fp16-sparse-signatures-a`, `fp16-sparse-signatures-b` |

RS uses register A; its manifest and log `a_layout` tag remains `block-major`.

The [independent producer](../../ci/project/p02_wgmma_fixture_oracle.py) directly
encodes integer inputs within −7…7 and exact FP32 sums. Sparse fixtures encode
all six legal two-of-four masks. Warp and CTA signatures distinguish stale or
missing tile data and stale metadata; expected values do not come from the
production arithmetic model. Regeneration is checked byte-for-byte.

The completed formal inventory is **12 backend/configuration builds, 24 case executions,
48 launches and 24,576 exact output-word comparisons**. Each case runs twice,
with a distinct poisoned output buffer before each launch. Complete BEGIN,
RESULT and PASS records retain all 512 actual and expected words per launch.
Missing writes, mismatches, incompatible devices or cleanup errors fail the host.

## Directed native protocol harness

[p02_wgmma_unit.py](../../ci/project/p02_wgmma_unit.py) builds the four-slot
[native harness](../../hw/unittest/tcu_wgmma/). It directly supplies expanded
micro-operations to the existing TCU unit/shared path and independently checks
headers, exact results, ownership, queue accounting and bounded drain.
The unit forbids DPI and FEDP2K, enables assertions, and computes exact expected
FP32 values from bounded integer matrices, including intermediate C feedback.

| Ordered group | Accepted / committed transactions | Arithmetic words |
|---|---:|---:|
| `dense_ss_initial` | 64 | 512 |
| `dense_ss_descriptor_reuse` | 64 | 512 |
| `dense_ss_row_major` | 64 | 512 |
| `dense_rs_bf16` | 64 | 512 |
| `cta_exclusion` | 32 | 256 |
| `sparse_metadata_initial` | 36 | 256 |
| `sparse_metadata_reload` | 36 | 256 |
| `dense_rs_commit_pressure` | 32 | 256 |
| **Total** | **392** | **3,072** |

Arithmetic words include checked intermediate reductions. The metadata inventory
is eight requests, sixteen writes and sixty-four lanes. Finite schedules stagger
warp arrivals, exclude a conflicting CTA before eventual entry, hold LMEM ready
low, delay responses, split metadata lane masks, and reuse then replace slabs.

The separate dense RS pressure group uses NRC16 to supply enough independent
first-K work. A pending compute commit is held until the same slot has blocked
core-result, execute and dispatch interfaces with ready operands, no CTA conflict,
and asserted admission blockage. Eight further stable cycles follow that causal
observation. Coverage must be nonzero within 256 cycles. This exercises the common
compute path; it does not claim a forced sparse-compute pressure window.

Unused non-first B descriptors and unused SS A descriptors point to distinct
zero-filled slabs, while RS register fragments remain valid. Required poison
counts are 357 B and 238 A descriptors. Reading live unused operands must change
the checked arithmetic. Every group also has a 100,000-cycle watchdog.

## Full-processor metadata witness

`--witness` binds the passive [scoreboard monitor](../../sim/rtlsim/p02_wgmma_scoreboard_monitor.sv)
only into the sparse RTL configuration. It observes metadata reservation, a real
wait by the same sparse instruction while XREG0 is busy, matching metadata
writeback release and eventual issue. Legal same-cycle release/issue is allowed.
The existing kernel prepares descriptors between the load and WGMMA in source.
Independent review of the executed sparse binary confirms the metadata load at
`0x18000017c` and dependent sparse WGMMA at `0x180000180` are adjacent. Retain
that disassembly/binary identity separately from the scoreboard records proving
the actual busy interval and dependency ordering.

The [witness validator](../../ci/project/p02_wgmma_witness.py) requires, per launch,
sixteen completed loads across eight physical warps, four issue instances with
both local warp identities, two loads per warp, and two CTA groups of four warps.
CTA ownership stays stable within each warp's pair; CTA numbers may change between
launches. At least one real wait must occur in each launch. This does not require
every warp to wait and does not create an artificial processor memory delay.

The finished two-case sparse RTL result exceeds that minimum: all 64 metadata
transactions across four launches completed with observed waits, sixteen per
launch. Each case records 723 and 651 slot-wait cycles for its first and second
launches. These sums across slots are not elapsed launch time. Complete arithmetic
and witness results passed on the same logs.

Correlation uses instance, warp, reset epoch, sequence, PC and CTA alongside UUID;
the release-build UUID alone is not unique. Complete arithmetic validation and
complete witness validation must accept the same log. Direct unit dispatch and
aggregate stall counters cannot establish processor scoreboard dependency order.

## Reproduce a qualification packet

Run these Python entry points from a clean committed source checkout. Prepare
the pinned tools and dependency libraries using the [developer guide](developer-guide.md).
The runners create fresh out-of-tree builds, configure them themselves, and
execute generated Makefiles. They do not download tools or rebuild dependency
libraries. Replace the example paths; work and output destinations must not exist
and must be separate from the source and tool directories.

Reused simulator dependencies also need their matching headers, including
`third_party/ramulator/ext/spdlog/include` and
`third_party/ramulator/ext/yaml-cpp/include`. Copying only the three dependency
libraries leaves the processor build incomplete. Retain the external header
identities alongside the library hashes when recovering a prepared environment.

The hardened input checks bind the compiler/configuration and retained-byte
boundaries independently:

- Every runtime, backend C++, RTL, kernel and host compiler record rejects
  conflicting `VX_CFG_LMEM_SIZE` values. Omission is allowed; an explicit value
  must be `16384`. Effective headers accept that literal or the canonical
  `__POW(2, VX_CFG_LMEM_LOG_SIZE)` form with log-size 14 and function-like
  `__POW(x,y)` bound to `__vx_cfg_pow((x), (y))`. Object-like substitutes or
  changed helpers reject; stamp expansion supplies no missing evidence.
- Both Ramulator include trees have bounded inventories checked through
  execution and finalization, alongside the three-library inventory. Missing or
  empty trees, links, special files and changing headers reject.
- Retained source/build copies must match original inventory paths, SHA-256 and
  sizes. Matching declarations alone do not prove copied-byte identity.

Use the [host compiler guidance](developer-guide.md#host-compiler-compatibility-for-wgmma)
for the bounded GCC 12 preparation and retained GCC 14/Clang failures. The
workload, fixtures, arithmetic, production RTL, warnings and parity bound stay
unchanged.

```sh
python3 ci/project/p02_wgmma_unit.py run \
  --tools-dir /path/to/vortex-tools --host-bin /path/to/host-bin \
  --work-dir /path/to/fresh/unit-builds \
  --output /path/to/fresh/unit-evidence

python3 ci/project/p02_wgmma_matrix.py run --witness \
  --tools-dir /path/to/vortex-tools --host-bin /path/to/host-bin \
  --work-dir /path/to/fresh/matrix-builds \
  --output /path/to/fresh/matrix-evidence
```

Run the commands sequentially with at most two compiler workers total. Both
runners retain a 15 GiB free-disk reserve, require 6 GiB available memory, monitor
sampled process-group RSS against 6 GiB, and cap each log at 16 MiB. Build commands
are limited to 1,800 seconds; the unit runtime defaults to 120 seconds. Waveform
capture is disabled. By default, successful build trees remain available for review.

Both runners check the remaining disk reserve before retaining each artifact and
copy in 1 MiB chunks. This bounds copying memory and avoids consuming the reserve
with a known-size artifact; it is not an atomic reservation against unrelated
writers. Processor RTL compiler records must contain exactly one `--assert`,
including witness builds, so assertion-based ordering checks cannot silently
disappear from a qualified build.

For investigation, explicitly add `--development`. Matrix subsets additionally
use `--backend`, `--variant` and `--case`; an unlabelled partial matrix is rejected.
Development packets cannot establish clean-source acceptance. Retain failed and
interrupted attempts with their original source identities before any correction.

## Verify a complete original packet offline

Use a trusted checkout containing the corrected
[packet verifier](../../ci/project/p02_wgmma_packet.py), published as
`359a8c007f450a8146540f795cb576b29818fa03` (tested local
`5e3b74fd569169ad921315223c121a037ae656b7`, tree
`97116818da872f43f952a351eb6616fc327be438`). From that checkout's source root,
replace both placeholders:

```sh
python3 ci/project/p02_wgmma_packet.py \
  /path/to/complete/original-matrix-evidence \
  --require-witness --report-sha256 INDEPENDENT_REPORT_SHA256
```

Obtain the original report digest from an independently trusted receipt or
reviewed publication. Computing it only from the submitted packet supplies no
independent authenticity anchor. Without `--report-sha256`, the verifier reports
`self_consistency_only`. The completed packet above verified with the independently
supplied digest, `packet_valid: true` and all three outcomes `pass`.

Exit 0 means a consistent complete packet, including one that consistently
records witness or parity failure. `--require-witness` requires requested witness
evidence, not a passing witness outcome. Inspect `recorded_outcome`,
`arithmetic_outcome`, `witness_outcome`, `parity_outcome` and
`qualification_status`. The tool retains `acceptance_claimed: false`,
`qualifies_P02_A03: false` and `phase_complete: false`; independent acceptance
is separate.

The verifier reparses retained evidence using trusted local helpers. It does
not execute packet code, replay binaries or fetch missing bodies from original
source/build paths. Exactly eight generic checkout inputs are required. All
execution-inventory overlaps must match; only unused `ci/blackbox.sh` may be
checkout-only identity evidence, explicitly exposed in
`checkout_inputs_outside_execution_inventory`, with its body unverified.
Mandatory consumer sources, helper closure, fixtures, copied inputs, compiler
records and command provenance remain enforced. Original tools/dependencies and
omitted bodies remain identity-only evidence; hierarchy semantics and disassembly
still require independent review. The earlier verifier's real checkout/source
binding failure remains retained alongside the correction.

This entry point requires a complete packet at its recorded original output
path. Interrupted/build-failed packets, relocation and normalized exports are
unsupported. Preserve failures separately. Publication inventories keep original
hashes for original bytes and separate published hashes for normalized text;
never replace an original identity with a normalized hash. Published-only checks
cannot verify absent original binaries, compiler bodies or dependencies and are
a separate operation from this original-packet CLI.

## Review evidence and close the gate

Review complete command logs, source/tree identity and stability, fixture hashes,
tool/dependency identities, generated headers, native hierarchy, binary hashes
and disassembly. Validate each runtime, backend, kernel and host compiler record
independently; unit C++ and RTL records are also separate. Preserve the executing
validator and transitive helper sources. Reconfigure after Makefile changes.

Performance dumps are cumulative within each two-launch process; compare launch
deltas. Retired-instruction counts must match exactly. The cycle rule remains
`abs(SimX_cycles - RTL_cycles) * 100 <= RTL_cycles * 5`. Arithmetic, witness and
performance outcomes remain distinct; a failed comparison stays failed in its
packet. Any documented timing applicability limit needs a concrete explanation
and independent review, and cannot waive numerical or concurrency correctness.

The completed matrix satisfies the frozen instruction/cycle predicates.
Auxiliary cache/stall counters still differ in some rows; their equality and
causal attribution are unclaimed. This does not alter the frozen parity rule.

The [catalog smoke](../../ci/testcases/p02_wgmma.yaml) runs only dense and sparse
FP16 SS pattern A on both backends; the added native unit lane is also discoverable
through CI. These entries supplement the complete bounded runners. Python tests
and host stubs validate tooling; SimX is a model; processor RTL and the direct
unit cover different boundaries. Native TFR/STD processor arithmetic still has
inherited integer multiply/divide DPI helpers. No full-AFU, vendor `hw_emu`,
physical FPGA, synthesis/PPA or silicon qualification follows from these checks.

The immutable packet, independent engineering and publication-integrity reviews,
and [acceptance record](evidence/p02-wgmma/processor/acceptance.json) close the
bounded A03 gate. Original runner/verifier flags remain unchanged; they never
accept A03, complete P02 or advance P03 automatically.

P03-T01 now implements the bounded ordinary WMMA input and argument contract.
Continue with [P03-T02](p03-operators-handoff.md): matching kernel reader,
managed runtime dispatch and independently verified arithmetic/lifetimes. The
accepted WGMMA scope does not establish a general sparse operator. P03 remains
`in_progress` until its own exit gates are demonstrated.
