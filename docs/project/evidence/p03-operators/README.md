# P03-A01 native operator contract evidence

P03-A01 is accepted at **source scope**, completing P03-T01. P03 stays
`in_progress`: actual operator execution and runtime lifetime gates A02/A03
remain open. See [acceptance.json](acceptance.json), [summary.json](summary.json)
and [the handoff](../../p03-operators-handoff.md).

## Exact validation

Clean implementation `6367ce34e12915e12271207b207f93bd4d391869`, tree
`6b4273a75415f0277a67576d31316c96ddf625c9`, passed **1636 tests**, with zero failures,
errors or skips in **397.573 seconds**. Source and working-tree state
remained unchanged across the run. [verification.json](verification.json)
retains bounded command results, source identities and resource observations;
[full-suite.log](full-suite.log) contains every test result. The full suite
includes the twelve new P03 checks: eight actual C++17/UBSan host groups and
four manifest/profile/ABI checks.

Independent [contract review](contract-review.md) approves the source contract
after 84 consistency checks. The separately retained
[implementation review](implementation-review.json) covers checked bounds,
error behavior, manifest agreement and independent literal-byte tests.

Four actual [target compilations](cross-compile.json) passed: ABI-layout probes
and the complete implementation for RV32IM/ILP32 and RV64IM/LP64. ELF inspection
confirmed 32/64-bit RISC-V relocatable objects. These ran before the clean source
freeze; their explicit dirty-source observations and unchanged file hashes are
preserved. They are not relabelled as clean-source runs, linked kernels or
operator execution. The two probe bodies are retained under [probes](probes/).

The equivalent source tree is stored in published implementation commit
`04c3cbf42c68e3b116051343083b86119f67f53d`; [source-map.json](source-map.json)
retains original local Git commit bytes and the verified remote parent/tree.
Git metadata differs; the tested source files do not. [Change classification](change-impact.log)
is R2 for the internal software addition, with independent contract review also
performed. Preserved historical P02 raw logs/patches keep their original trailing
whitespace; all other changed source/documentation passes the whitespace check.

The final [delivery review](delivery-review.json) passed 341 checks of the
assembled receipts, source identities, publication mappings and canonical phase
state before its own receipt was appended. No tests were repeated by that review.

## Reproduce and interpret

```sh
python3 -m unittest discover -s ci/project -p 'test_p03_operator_contract.py' -v
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

The first and third commands require a native C++17 compiler and UBSan. Exact
cross-target compiler arguments, LLVM/GNU tool/header hashes and object identities
are in the target receipt. Toolchains, full build trees and object bodies are
not included in this evidence. [publication.json](publication.json) distinguishes
original receipt hashes from path-normalized published bytes.

The planner has no runtime calls and always returns `execution_available=false`.
Its 56-byte schema has no device reader. Address representation bounds cannot
prove actual memory mappings, and caller-supplied metadata must come from a
trusted registry before future dispatch. No CPU fallback, device launch,
arithmetic, queue/event lifetime, transfer recovery or physical hardware result
is claimed. P03-T02 must implement and qualify those boundaries separately.
