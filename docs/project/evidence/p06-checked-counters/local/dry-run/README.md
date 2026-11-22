# Checked-counter build grammar packet

**Configuration and make dry-run evidence only. No C++ translation unit was
compiled, no executable was linked and no native model ran.** The object-file
identity observation inside the grammar validator was explicitly mocked because
there were no object files. This packet grants no warm readiness or acceptance.

## Original result and identity

The original [report](report.json) records six successful bounded host commands:
fresh configure, the actual compiler-stamp target and `make -n`, separately for
ordinary and checked RV64 `p02-tfr`, `PERF=1` trees. Each emitted command stream
contains **44 compilation commands and one link command**. The ordinary stream
has no checked-counter definition; the checked stream selects
`SIMX_CHECKED_COUNTERS=1`. Both include the actual Core, Processor, CSR, cache,
TCU and directed harness sources and exclude the standalone SimX CLI entry.

The original report SHA-256 is
`cf192557e267fce361f43d6975d1cc91e7cf1bcd4ac897fda5d9950dfe6de7e3`.
Its source revision remains `53f4ad08c469a1cc73fa604249b302f9416055e0`.
That local reviewed checkpoint and published
`a9227933c340fd44e73deaffafdd353fecf65492` have the identical tree
`80553bb237af44b187dd6d18178e851cd6671ec8`. Every source body listed in the
original report also matches published
`9fd7eac203c77fa54c7af80fa0220ae09553cd55`. These mapping checks do not rewrite
the original receipt or present it as a new execution at either published SHA.

## Retained files and integrity

The [index](index.json) maps each retained file to its original absolute path,
size, SHA-256 and evidence-binding category. All original file bytes are
unchanged. The packet contains:

- The original report and all six command logs, including four empty configure/
  stamp logs whose empty-file hashes match their receipts.
- Both compiler-command-only streams. Each is exactly the compiler lines from
  its report-bound raw `make -n` log. Raw logs retain hidden stamp/mkdir recipes
  that would not be echoed by a successful real build.
- Both original compiler stamps, verified against the report's stamp hashes.
- The copied configuration generator and executed SimX Makefile chain, verified
  against the report's before/after source hashes.
- The selected generated configuration, software/hardware headers and Verilator
  configuration from the original dry-run trees.

**Generated-file capture boundary:** the original report did not record hashes
for the generated headers or `config.mk`. Their index hashes describe the files
present when this packet was assembled. They are not retroactive execution-time
observations. Compiler stamps and copied source inputs have the separate
original-report bindings stated above.

The copied generator and Makefiles are inert evidence. Packet assembly read and
hashed them; it did not execute retained code. This is a selected packet rather
than a copy of either complete build tree. It contains no dependency library,
model object, native executable or toolchain archive.

## Scope limits

`make -n` prints prospective compilation/link commands. The grammar pass checks
that the runner can parse that real command shape and inventory; it cannot prove
that compilation, linkage or a model scenario succeeds. Fresh configure and
stamp generation likewise do not establish native execution.

The explicit `ubuntu/focal` configuration label permits generation on the
Debian host used for this check. It is not evidence of Ubuntu execution.
Formal native requirements, including the unchanged **15 GiB disk reserve**,
remain separate. Hosted native builds, complete source/tool/binary bindings,
actual selector and failure diagnostics, all-33 transport, public native fault
handling and lifetime qualification require their own original execution
packets. `qualified`, `ready_for_warm` and `acceptance_claimed` stay false here.
