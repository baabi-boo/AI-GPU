# Attention operand coverage correction

The recorded matrix with SHA-256
`f0ad2390b983c3e9a0804fc6309d22bb85ba23ba39635309e0193c9a54d6df97`
incorrectly describes its two attention cases as using **RS operand mode**.
The actual pinned kernel uses **SS: both matrix operands come from shared
memory**. This correction concerns the coverage description; it does not change
the executed commands, dimensions, arithmetic backend, oracle or tolerance.

At GPU source `03181532b81fe95b1cfeac2ffb25d8597af689b2`, both GEMMs in
`tests/regression/flash_attn_tcu_wg/kernel.cpp` construct `desc_a` and `desc_b`
using `vx_make_smem_desc`, then pass those descriptors to `ctx::wgmma_sync`.
In `sw/kernel/include/vx_tensor.h`, the intrinsic selects its SS branch with
`if constexpr (a_is_smem && b_is_smem)`. Its flags include `a_from_smem`.

The recorded `-DWGMMA_RS` macro is unused by this kernel and intrinsic. It is
retained in the frozen command metadata so the exact invocation remains
reproducible. Its presence does not establish register/shared operand coverage.
No RS attention execution is claimed by this packet.

The original matrix snapshots and archived instrumentation remain unchanged.
Read their descriptive strings together with this erratum. The current matrix's
two attention descriptions are corrected separately; all executable fields are
preserved. No inherited source, test selection, golden result or numerical
tolerance is changed.

Independent source review: `/root/w08e_attention_contract_review`; integration
review: `/root`. The source review compared fourteen relevant files with the
pinned GPU revision. Actual numerical acceptance requires the separate completed
execution packet and its review; static operand inspection alone is not a pass.
