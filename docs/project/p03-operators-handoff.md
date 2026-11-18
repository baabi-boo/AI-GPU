# P03 native operator contract handoff

P03 is `in_progress`. P03-T01 implements an internal operator manifest, checked
C++17 planner and explicit device-argument encoder. P02 is complete with its
independently reviewed numerical and concurrency evidence; P01-A03 vendor
integration remains blocked and required before P07.

## Implemented boundary

The [manifest](../../ci/project/p03_operator_manifest.json) and
[v1 specification](../designs/ai_operator_contract_v1.md) define exactly six
matmul signatures: FP16 or BF16 inputs, FP32 accumulation/output and
`(M,N,K) = (8,4,8), (8,4,16), (16,8,16)`. These are the actual ordinary WMMA
fixture tuples, not a Cartesian product of dimension ranges. A is compact
row-major, B compact column-major and D compact row-major; C starts at exact
positive zero. The separate WGMMA sparse proof does not expand this API.

The [planner](../../sw/runtime/ai/contract.h) checks versions, operator IDs,
rank, dtype, shape, exact byte strides, batch/transpose/options, profile and
capability inputs, allocation ownership/access, alignment, checked byte sizes,
offsets, address representation and pairwise accessed-span aliasing. All error
returns preserve the caller's output. Registry IDs and device addresses remain
separate from host pointers.

The encoder writes a new 56-byte little-endian argument schema with explicit
fixed-width fields, reserved zero words and asserted offsets. This schema has
no device reader yet and is **not compatible with the regression kernel's
`kernel_arg_t`**. Width-32 encoding tests do not qualify RV32 execution; the
planner requires the accepted ordinary RV64 profile. Representation checks do
not authenticate an allocation or prove that a device's physical aperture maps
that address. The future wrapper must establish actual allocation/addressability
and profile identity through its trusted registry and configuration records.

Every plan reports `execution_available=false`. GEMV, reductions, softmax,
normalization, activations, casts/layout conversion and attention are explicitly
unavailable. There is no dispatch, runtime resource ownership, CPU fallback,
installed API or new arithmetic implementation in this milestone.

## Validation and acceptance

Run the focused host/contract tests from the source root:

```sh
python3 -m unittest discover -s ci/project -p 'test_p03_operator_contract.py'
python3 ci/project/check_project.py
```

The test module compiles the real planner under C++17 with strict warnings and
UBSan, executes positive and negative groups, compares literal independent ABI
bytes, and cross-checks the manifest against the accepted P02 shape/profile
inventory. It needs a native compiler, not a GPU build. Target compilation and
host execution are distinct observations; formal source-bound results are
recorded after the implementation is frozen and independently reviewed.

Only P03-A01 source-level contract acceptance can follow from these checks.
P03-A02 needs actual operator launches and independent arithmetic comparisons;
P03-A03 needs runtime resource, failure and completion evidence. A planner result
cannot substitute for either gate or complete P03.

## Next bounded action: P03-T02

1. Add the matching device reader or an explicitly reviewed adapter for the new
   argument schema. Preserve the accepted ordinary WMMA arithmetic/order and
   restrict dispatch to the declared format/shape tuples.
2. Wrap the existing `vortex2.h` device, buffer, queue, module, kernel and event
   interfaces. Track trusted allocation metadata at allocation/reservation;
   arbitrary handles do not expose enough extent or owner information.
3. Query the available runtime capabilities and bind the actual module and
   device configuration to the accepted profile. A tensor-feature bit does not
   establish TFR/STD arithmetic, the format bank or excluded features.
4. Retain buffers, modules, kernels, queues and dependent events until completion
   or an established terminal error. A timeout may leave work outstanding and
   must not free in-flight resources. Preserve primary and cleanup errors.
5. Execute every advertised signature on matching SimX/native RTL with the
   independent fixtures and retained dispatch/transfer records. Test bounds,
   allocation/transfer failures, failed events and repeated cleanup separately.

Use separate generated builds and the existing bounded runner/resource rules.
Keep unsupported operations explicit, and update the manifest only alongside
matching implementation and evidence. P04 model composition follows accepted
P03 execution and lifetime gates, not this source-only contract.
