# Independent P03 native operator contract review

**Approve P03-T01 and P03-A01 at source-contract scope. No blocking source or test-semantics finding remains.** Reviewer: `/root/phase_review`. I authored neither the validator nor its tests. This review does not accept P03-A02/A03, complete P03, or claim device execution.

The accompanying `p03-contract-review.json` binds all six new source/specification/test files by SHA-256 and size, records 84 passing independent consistency checks, identifies the actual host-test and cross-compilation receipts, and distinguishes source review from execution performed by other agents. The implementation remains a hashed working-tree candidate; its coordinator must freeze it and record the planned full-suite result before final publication.

## Contract and implementation

The manifest explicitly inventories all eight required families. Only matmul has a contract: FP16 or BF16 inputs, FP32 output, compact row-major A, column-major B and row-major D, rank two, batch count one, positive-zero initial accumulation, and exactly `(M,N,K) = (8,4,8), (8,4,16), (16,8,16)`. I independently checked those shape tuples against the accepted ordinary-WMMA fixture union. Unsupported shape combinations, formats, layouts, flags, operators and profiles fail explicitly.

The C++ implementation correctly checks multiplication before using dimension/byte products, offset and byte-span bounds using subtraction, and addition before constructing device addresses. Entire allocations and accessed subranges must fit the declared address representation. Aliasing uses inclusive endpoints only after proving nonzero, representable ranges, so its endpoint additions cannot overflow. All three accessed ranges must be disjoint; adjacent subviews of a consistent allocation are permitted. Duplicate allocation IDs require consistent metadata, and device identity and access permissions are checked independently.

Both public entry points build their results locally and assign the caller's output only after every check succeeds. This preserves the documented atomic failure behavior. Successful plans remain `execution_available == false`; there are no allocations, transfers, enqueues, fallback computation or device readers hidden behind planning success.

The 56-byte argument schema has explicit field widths, a declared eight-byte alignment, and static assertions for every offset and the complete size. The encoder emits little-endian bytes explicitly rather than copying C++ object representation, padding, pointers or `size_t`. The schema is expressly incompatible with the existing regression kernel argument block. A matching device reader or reviewed adapter is still required before submission; no installed runtime ABI or install rule changes here.

## Independent test-semantics review

The tester's final focused run passed **12 tests**, with no failures, errors or skips: eight actual compiled host groups with C++17, warning-as-error flags and UBSan, plus four manifest/profile/ABI checks. I inspected the actual receipt and raw log, rehashed their inputs, and confirmed all six source identities remained stable. I did not duplicate that execution.

The tests exercise valid format/shape combinations; rejection of unsupported shape cross-products; versions, enum values and ranks; compact strides and layouts; overflow and final-address edges; device identity and access; duplicate allocation metadata; aliasing and adjacent subviews; exact profile attestations; and unchanged outputs on failure. Literal byte arrays independently verify RV32/RV64 representation and endian/offset rules.

A concrete integration gap was corrected during review: separate tests of planner fields and encoder output did not prove that successful planning retained the encoded bytes. The successful suballocation test now compares all **56 returned argument bytes** with an independent literal containing the checked `0x1020`, `0x2020` and `0x3020` addresses. The final focused test receipt includes this correction.

## Actual target-compilation evidence inspected

The author separately ran four actual pinned LLVM 20.1.8 compilations: a static ABI probe and the complete implementation for **RV32IM/ILP32 and RV64IM/LP64**. All four exited zero with empty diagnostics. I inspected the exact commands, rehashed the two tools and 49 transitive source/header dependencies, checked the input and object hashes, and independently read each object's ELF identification and RISC-V machine field. The probes require actual target XLEN and pointer width; these are real target compilations rather than host macro simulations.

This establishes compile-time layout/portability at the declared targets. No target linking, GPU execution or RV32 operator execution is claimed. The planner continues to require the qualified RV64 execution profile; accepting a 32-bit representation in the encoder does not broaden that profile.

## Address semantics correction

The first wording risked conflating RV64's 64-bit representation with the actual device aperture. The inherited RV64 memory-address width is 48 bits, and real runtime allocations can occupy a smaller mapped space. The final header, manifest and specification now explicitly distinguish these concepts. Trusted allocation metadata and qualified profile binding must establish actual physical/virtual addressability before future dispatch. High-address test cases establish only checked representation and arithmetic behavior.

Those registry identities, access flags and profile flags are caller attestations. The planner does not authenticate arbitrary metadata, discover missing numerical-backend capabilities or prove that an address is physically mapped. The specification now makes that boundary clear.

## Remaining implementation obligations

P03-T02 must introduce the matching kernel reader/adapter, managed allocation metadata, real runtime capability/profile binding, retained buffer/module/kernel/queue/event lifetimes, explicit transfer and dispatch records, independent device numerical comparisons, and failure/cleanup tests. Timeout cannot imply completion or permit freeing in-flight resources. None of those runtime properties follows from the current pure planner.

The coordinator should now freeze the exact reviewed source, preserve the working-tree receipt mapping, run the planned full offline suite and governance checks once, and record their real outcome. P03 may be `in_progress` with this source-only acceptance; P03-A02/A03 remain pending and the phase remains incomplete. No physical hardware, vendor integration, broader numerical behavior or manufactured-silicon result is established.
