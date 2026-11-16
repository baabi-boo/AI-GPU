# P01 compiler-record validation handoff

**The compiler-record correction is implemented and locally verified. P01 remains
blocked on vendor `hw_emu`; P01-A01/A02 retain their accepted evidence and P02
remains `not_started`.** This continuation supplies `source_present` tooling
evidence for P01-T05. It supplies no new GPU, vendor-emulation or physical result.

## Identity and scope

The repository is `baabi-boo/AI-GPU`, with authorized publication to `master`.
The execution and integration owner is the primary coding agent, `/root`.

| Identity | Exact value |
|---|---|
| Starting revision | `97405322dfcb2944d50eb285008725f79eb733d8` |
| Tested implementation | `f11190c87778ef049237650bbba4234ca62026b2` |
| Tested implementation tree | `36335b94da7392e4c5fd24618d4ce85addbf2d20` |

The implementation checkout was clean before and after its complete test run.
All 93 captured `ci/project/*.py` identities remained unchanged. Later
documentation and delivery records are separate from that execution and must
not be described as additional runs of a later revision.

The shared [validator](../../ci/project/compiler_records.py) checks runtime,
kernel and host records independently, consumes option operands before crediting
definitions, and verifies direct kernel RV64 ISA/ABI and the runtime linker
binding. The [contract](p01-compiler-records.md) specifies accepted syntax.
Preparation and execution manifests remain separate; sharing validation grants
no automatic launch readiness.

The runner retains the validator's complete local dependency closure and rejects
invalid records before launch or changed records/helpers before final success.
Source hashes detect drift without authenticating stamp production, binary
provenance, loaded Python code, the interpreter or bytecode caches.

## Verification

The [verification record](evidence/p01-compiler-records/verification.json) binds
the following observations to their commands, logs and source identities:

| Source-root check | Observed outcome |
|---|---|
| `python3 -m unittest discover -s ci/project -p 'test_*.py'` on the starting revision | 1,075 tests passed |
| Same command on the clean implementation revision | **1,120 tests passed; zero failures, errors or skips** |
| `python3 ci/project/preflight.py --tier governance` | Passed, exit 0 |
| `python3 ci/project/check_project.py` | Passed, exit 0 |
| `python3 ci/project/check_baseline_packets.py` and explicit export checks | Retained native and clean-build packets passed their declared consistency checks |
| `python3 ci/project/xrt_baseline.py probe` | Expected blocked result, exit 1; no vendor program invoked |

The retained [vendor probe](evidence/p01-compiler-records/vendor-probe.json)
found `v++`, `vivado`, `emconfigutil`, `platforminfo` and `xsim` absent from
`PATH`, with all three vendor roots unavailable. Its Python sources match the
implementation checkpoint; documentation edits during that observation are
recorded separately.

The implementation adds 45 tests, with further cases covered through subtests.
A real host preprocessor reproduces consumed macro arguments and the wildcard
counterexample. Fresh Make stamp targets establish generated-flag compatibility;
compiler sentinels prevent application/kernel compilation. File-backed negative
cases and inert runner fixtures verify launch prevention, post-smoke failure
and helper-snapshot drift. These fixtures provide no vendor execution evidence.

Python 3.12.14 completed the implementation suite in 137.897 seconds of wall
time, within its 240-second limit. The retained log is 1,300 bytes. Free disk
afterward was 51,152,777,216 bytes, approximately 47.6 GiB, above the 15 GiB
reserve. No toolchain download or GPU build was performed.

All 228 audited historical evidence files, goldens, packet-parser inputs,
matrix/toolchain lock and README illustration match the starting revision byte
for byte. Published-packet consistency does not establish original raw-log
authenticity or the asserted redaction relationship.

## Review disposition

| Concrete finding | Disposition and verification |
|---|---|
| Tracked F1: `-I*` can expand to standalone `-I` and consume a required definition | Resolved by conservative expansion rejection; actual shell/preprocessor oracle reproduces the original defect |
| XRT credited consumed operands and aggregated separate compiler records | Resolved by shared operand-aware, per-record checks; file-backed and prelaunch regressions pass |
| Non-LF separators could manufacture records | Resolved by LF-only boundaries and control/separator rejection |
| Host/runtime records accepted Verilator transports or free source operands | Resolved by compiler-role grammar checks and negative tests |

The immutable starting revision's classifier and policy report **R1**, with
`path:default` and no contract or evidence findings. See the retained
[classification](evidence/p01-compiler-records/change-impact-classify.json).
Independent reviews cover the project rule for enforcement changes: assignment
19 reviewed compiler semantics; 24 reviewed test quality;
26 reviewed runner failure paths; 27 reviewed helper closure/provenance; and
28 reviewed generated-recipe compatibility. Their scoped reviews found no
remaining blocking defect. They grant no human approval or waiver. No gate,
tolerance or golden was waived or relaxed.

## Delivery state

The user explicitly authorized implementation, commit and push to `master`.
The implementation is published as
[`623544cdd51f9c70a4e2fcef29ed3b56d8cce3fe`](https://github.com/baabi-boo/AI-GPU/commit/623544cdd51f9c70a4e2fcef29ed3b56d8cce3fe).
Authenticated GitHub readback and independent review confirm the exact tested
tree and original parent. The [publication map](evidence/p01-compiler-records/publication-map.json)
and [original local commit bytes](evidence/p01-compiler-records/local-implementation.commit)
preserve the distinction between the local test identity and the API-created
commit. No test execution is relabelled. The update used the expected old head
and no force, and local branch alignment preserved the index and working files.

The [initial hosted-CI observation](evidence/p01-compiler-records/code-ci.json)
records both workflows queued at its stated timestamp. The later
[hosted result](evidence/p01-compiler-records/code-ci-final.json) verifies that
[Project Governance](https://github.com/baabi-boo/AI-GPU/actions/runs/43790120429)
succeeded on published implementation `623544c`, including **1,120 tests in
178.162 seconds**. General CI was still queued at that observation; no result
is attributed to it. The local 137.897-second wall-clock observation and the
hosted test duration are separate executions.

The [continuation ledger](p01-compiler-records-agent-execution.json) records
**60 completed distinct agent assignments in ten logical waves of six**, with
at most three subagents active concurrently. Each completion was recorded after
its actual result returned; coordinator work, failed spawns and historical
ledgers are excluded. This handoff, contract, verification packet and completed
ledger accompany the published implementation in a subsequent documentation
commit. Its source code is unchanged from the tested implementation; the final
branch identity is available in Git history. Agent counts grant no phase acceptance.

## Next bounded action

The FPGA platform and verification owners must resolve
[P01-T05](backlog.md)'s qualified vendor release/platform prerequisite and retain
a matching artifact-production packet with real commands, outcomes and hashes.
Independently review the execution runner's own manifest and receipt before
the bounded DMA/launch/completion smoke in the
[XRT integration guide](p01-xrt-integration.md). Freeze the resource budget and
stop while any prerequisite, provenance requirement or resource limit is
unresolved. The [roadmap](roadmap.json) and [acceptance policy](acceptance.md)
remain authoritative: only compatible execution evidence and review can close
P01-A03.
