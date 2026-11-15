# P01 offline packet verification handoff

## Current disposition

This continuation implements offline verification for P01-T06's retained
execution packets. It has performed **no new GPU build or workload execution**.
P01-A01's clean generated-build and P01-A02's six-case native numerical evidence
remain accepted after their existing independent reviews. P01-A03 remains
blocked on qualified vendor XRT `hw_emu` tools/platform, P01 remains incomplete,
and P02 remains `not_started`. The [roadmap](roadmap.json) owns phase state;
the [acceptance policy](acceptance.md) governs any later change.

Read the reusable [packet verification guide](p01-packet-verification.md) for
the complete interfaces, limits and interpretation. The original
[execution handoff](p01-handoff.md), accepted
[clean-build](evidence/p01-build.json) and [native](evidence/p01-native.json)
reports, [review record](evidence/p01-review.md), historical failures and
existing execution ledgers remain the execution evidence. This document adds
the packet tooling continuation; it does not replace those records.

## Implementation identity and publication

| Item | Identity or state |
|---|---|
| Intended repository / branch | `baabi-boo/AI-GPU`, `master` |
| Initial continuation checkpoint | `e9c9ac01f93b0d84915340999100260f2599ec44` |
| Incorporated reviewed baseline delivery | `25ca2e69bcb0c360cff273bf9edfd213fd53bd4c` |
| Incorporated baseline tree | `a124bac9609f1e620014583a2ae8375933d7a77d` |
| Published packet implementation | [22c545c632628f9da9f18ccf8fb512a8bfac7f81](https://github.com/baabi-boo/AI-GPU/commit/22c545c632628f9da9f18ccf8fb512a8bfac7f81) |
| Exact tested implementation tree | `ba797a53cbef12d1dd2e00cee3b8d487824fe7e1` |
| Implementation's sole parent, preserved by publication | `25ca2e69bcb0c360cff273bf9edfd213fd53bd4c` |
| Implementation publication and GitHub ref readback | Lease-checked, non-force fast-forward of `master` to `22c545c632628f9da9f18ccf8fb512a8bfac7f81`; published ref verified |
| Completion documentation | This handoff, the complete validation log and the ledger of all 60 completed assignments; implementation code and accepted phase evidence remain unchanged |
| Hosted Project Governance for the implementation | [Run 43772656018](https://github.com/baabi-boo/AI-GPU/actions/runs/43772656018) completed successfully, including both packet checks and all 591 tests |
| Separate main GPU CI for the implementation | [Run 43772656041](https://github.com/baabi-boo/AI-GPU/actions/runs/43772656041) remained queued at 2026-11-15 23:06:25 UTC; no success or GPU execution claimed |
| GPU source of the retained execution | `03181532b81fe95b1cfeac2ffb25d8597af689b2` |
| Executing helper revision of the retained execution | `e9c9ac01f93b0d84915340999100260f2599ec44` |
| Integration and final validation owner | Primary agent `/root` |

The incorporated delivery supplies the reviewed six-case native packet and
separate fresh generated-build packet. Its source and instrumentation identities
remain distinct from the new offline verifier. A passing check of those records
does not mean the new verifier revision ran the workloads.

The implementation's exact-commit local validation, independent review,
publication and hosted governance verification are complete. Publication used
the incorporated baseline as the expected remote parent and preserved that
history. This completion record preserves the final documentation and ledger.
Local and hosted implementation results below belong to the implementation commit and
tree above; the earlier baseline's hosted CI result remains evidence only for
that earlier delivery. The separate main GPU workflow is not included in the
passing governance result.

## Implemented interfaces and claim boundaries

| Interface | What it checks or writes | Boundary |
|---|---|---|
| [`verify`](../../ci/project/baseline_packet.py) | Original retained report, frozen matrix, command logs, snapshots and recorded provenance; optional comparison with an external seal manifest | Integrity can pass for a valid failed or selected-case run; use `--require-native-pass` to require all six complete native cases and final provenance |
| `seal` | The same original-byte verification, followed by a deterministic unsigned inventory of referenced members | The output must be a new file outside the packet; it does not copy evidence, authenticate execution or alter the packet |
| [`verify-export`](../../ci/project/baseline_packet_export.py) | An explicit export mapping, published bytes and the unchanged report's retained record contract | `--require-native-records` requires complete consistent native records; original log bytes and the redaction relationship remain unverified |
| [`check_baseline_packets.py`](../../ci/project/check_baseline_packets.py) | Both retained repository exports: complete native records and the passing selected-case clean-build packet | Requires each retained run to pass, reports both packet results, and grants no phase or hardware acceptance |

Every mode retains `phase_complete: false`. Original mode reports `integrity`
and `native_matrix_passed`; export mode reports `published_integrity` and
`native_matrix_records_consistent`. Export mode always reports
`raw_log_bytes_verified: false` and `redaction_relationship_verified: false`.
A public hash mapping is not proof that the original log was preserved by the
declared transformation. Keep the original and publication derivative separate.

The [packet reader](../../ci/project/baseline_packet_io.py) uses bounded,
directory-relative no-follow reads on supported POSIX systems. It rejects
symlinked ancestors, unsafe member paths, nonregular files, duplicate JSON
fields and out-of-budget input. It rechecks observed files before success.
Retained helper text and manifest source paths are inert evidence: the verifier
does not import helpers, execute a workload, open original workspace paths,
download tools or reconstruct nonretained binaries. Stop a producer before
verification; a concurrent writer can still change evidence after a check.

## Repeatable source-root commands

Check both repository publication packets, or inspect them individually:

```sh
python3 ci/project/check_baseline_packets.py
python3 ci/project/baseline_packet.py verify-export docs/project/evidence/p01/native \
  --require-native-records
python3 ci/project/baseline_packet.py verify-export docs/project/evidence/p01/clean-build
```

The [Project Governance workflow](../../.github/workflows/project-governance.yml)
adds the first command to its existing metadata and unit-test checks. The native
packet must describe all six passing cases. The clean-build packet remains a
passing selected FP16 SimX run and cannot satisfy the full-matrix requirement.

For an original stopped-run packet, use its original bytes and an existing
output parent directory. These example paths must be replaced with actual paths:

```sh
python3 ci/project/baseline_packet.py verify /absolute/path/native-run \
  --require-native-pass
python3 ci/project/baseline_packet.py seal /absolute/path/native-run \
  --output /absolute/path/native-run-manifest.json --require-native-pass
python3 ci/project/baseline_packet.py verify /absolute/path/native-run \
  --manifest /absolute/path/native-run-manifest.json --require-native-pass
```

The seal contains sorted member hashes and sizes, with no timestamp or copied
logs. Existing destinations are never overwritten. A failed strict native
requirement writes no manifest; a write failure may leave a partial destination
and a retry will not replace it. Only referenced packet members are inventoried.
The unsigned seal does not protect against someone replacing both the evidence
and the seal. Review and retain it through the normal provenance process.

## Corrections and retained provenance

The published implementation and independent regression files address these
concrete review findings. The exact-commit review reconciled their closure and
found no unresolved blocking code, review or test finding.

| Concern | Implemented correction and regression coverage |
|---|---|
| Configuration text could hide a nonnative override or supply a required macro as another option's operand | The stamp parser handles supported split, quoted and transported definitions, consumes known compiler/preprocessor operands, and rejects opaque or ambiguous flag sources. [Stamp](../../ci/project/test_baseline_packet_stamps.py) and [operand](../../ci/project/test_baseline_packet_operands.py) tests cover all retained roles without executing text or reading option files. |
| Numeric RV64 could be accepted without its effective companion selector | Passed stamps now require both `VX_CFG_XLEN=64` and effective `VX_CFG_XLEN_64=1`; every other `VX_CFG_XLEN_*` selector is rejected, including one defined as zero. The [independent XLEN regressions](../../ci/project/test_baseline_packet_xlen.py) cover missing, swallowed, empty, zero and conflicting companions at all 18 stamp positions, with genuine definition and operand positive controls. |
| A finished interruption could be mistaken for a malformed run or a completed native case | Ordered completed prefixes are preserved; workload success remains provisional until reference, capture and boundary provenance finish. [Interruption tests](../../ci/project/test_baseline_packet_interruptions.py) distinguish failed/blocked, interrupted and unrun cases and reject gaps or post-terminal execution. |
| Recursive source inventory could be confused with top-level declarations | The expected five declarations and eight recursive entries remain separate; missing nested paths, substituted entries and boundary drift are rejected by the [provenance tests](../../ci/project/test_baseline_packet_provenance.py). GPU and helper revisions need not be equal. |
| Alternate path spellings could place a seal inside the retained packet | Output containment normalizes POSIX leading separators before checking location; exclusive no-follow output creation preserves existing files. [Containment tests](../../ci/project/test_baseline_packet_containment.py) cover aliases and unsafe parents. |
| Published redacted logs differ from their original reported hashes | Explicit export verification preserves original identity assertions and checks mapped public identities independently. [Export tests](../../ci/project/test_baseline_packet_export.py) reject altered non-log evidence, inconsistent source bindings and incomplete mappings. |
| Historical and corrected matrix descriptions must both remain reviewable | The contract accepts exactly the two reviewed complete semantic snapshots. [Matrix-version tests](../../ci/project/test_baseline_packet_matrix_versions.py) cover both and reject partial prose corrections, arbitrary edits and executable/reference drift. |

The two approved matrix versions differ only in the two attention `derivation`
descriptions. The historical prose said RS; the correction identifies SS
operands for both GEMMs and the unused `WGMMA_RS` command macro. See the
[erratum](evidence/p01/attention-operand-erratum.md) and
[description correction](evidence/p01/matrix-description-correction.json).
Executable flags, dimensions, references, seeds and numerical tolerances are
unchanged. The historical snapshot is retained; allowing that exact snapshot
does not restore an RS coverage claim.

The runner records the input matrix identity but reserializes the retained
`matrix.json`. The verifier checks the retained matrix against the frozen
semantic contract and inventories its actual retained bytes. The original input
digest remains a provenance assertion, as do nonretained dependency and binary
identities. Neither mode replaces independent clean-build review or proves the
truth of an execution solely from hashes and reference markers.

## Exact implementation release validation

Assignment 47 ran the four required checks from the source root of a detached
release checkout at commit `22c545c632628f9da9f18ccf8fb512a8bfac7f81`, tree
`ba797a53cbef12d1dd2e00cee3b8d487824fe7e1`, with **Python 3.12.14** and
`PYTHONDONTWRITEBYTECODE=1`. Before and after the run, HEAD remained detached
at that same commit/tree and tracked/untracked porcelain status was empty.

| Executed command | Actual result |
|---|---|
| `python3 ci/project/preflight.py --tier governance` | Exit 0; pass |
| `python3 ci/project/check_project.py` | Exit 0; pass |
| `python3 ci/project/check_baseline_packets.py` | Exit 0; native and clean-build published packets pass |
| `python3 -m unittest discover -s ci/project -p 'test_*.py'` | Exit 0; **591 tests passed in 58.595 seconds**, no failures, errors or skips |

All **4/4 commands passed**. Exactly one complete discovery invocation ran.
The four-command sequence ran from 2026-11-15 23:01:13.199890 UTC through
23:02:12.714330 UTC. The complete, unchanged
[release validation log](evidence/p01-packet-validation.log) is retained with SHA-256
`3b5901b5944e910ce8155625c4e10fae0b21fefbda4838f41caed0675b437313`.
The governance preflight's uninitialized-submodule warning is permitted for this
tier. These are governance and synthetic-tooling results. The prior baseline
handoff's 346-test result remains historical evidence for that earlier delivery.

The packet guard reports `native_matrix_records_consistent: true` for the native
export and `false` for the passing selected-case clean-build export. Both retain
`phase_complete: false`, `raw_log_bytes_verified: false` and
`redaction_relationship_verified: false`. Independent read-only verification
also accepted the original native packet with the strict native requirement:
`native_matrix_passed: true`, `phase_complete: false`.

Assignment 53 exercised the published CLI against the original stopped packet:
strict verification, sealing to a separate temporary file, verification against
that seal, and sealing again to a new filename all returned exit 0. The two
7,635-byte manifests were identical, SHA-256
`3926555f5fec245ece911e8705aa3c67395125264cd2e245fb534952e0534b3d`.
An existing-destination retry returned exit 1 and preserved its bytes. Independent
before/after checks found all 41 referenced files, totaling 649,848 bytes,
unchanged in hashes, sizes and observed filesystem identities. Temporary outputs
were cleaned up; the retained packet and release checkout stayed unchanged.

## Hosted implementation verification

[Project Governance run 43772656018](https://github.com/baabi-boo/AI-GPU/actions/runs/43772656018)
completed successfully at the exact implementation commit. Its
[job log](https://github.com/baabi-boo/AI-GPU/actions/runs/43772656018/job/132991802661)
records Python 3.12.3, successful prerequisite/project checks, execution of the
new published-packet step, and **591 tests passed in 90.099 seconds**. Both
published packets passed with the conservative integrity and phase fields
described above. Assignment 51 checked the completed hosted log independently
of the local release result.

The separate [main CI run 43772656041](https://github.com/baabi-boo/AI-GPU/actions/runs/43772656041)
was still queued at 2026-11-15 23:06:25 UTC, with no executed plan or test-cell
logs. That observation is not a pass, failure or GPU result. Hosted governance
success does not certify main GPU CI, vendor integration, FPGA or silicon.

## Independent review and correction closure

The exact-commit policy review in assignment 48 used the classifier and policy
copied from parent `25ca2e69bcb0c360cff273bf9edfd213fd53bd4c`, verified their
byte identity against that parent, and ran isolated `python3 -I` classification
with explicit base/head revisions. The implementation is **R2**, solely because
of `path:ci-enforcement`. Its 21-file, 6,606-addition diff passed the whitespace
check. The workflow adds only the packet-checker step; its triggers, runner,
permissions, checkout restrictions, timeout and existing gates are preserved.
No new workflow trust exposure or unresolved required review was identified.

| Independent review assignments | Completed scope and disposition |
|---|---|
| 35 and 42 | Workflow/checker enforcement and documented interfaces; strict mode and claim boundaries verified |
| 38 | Both complete frozen matrix snapshots; independent 91-test contract/export/matrix run passed, including 14 matrix-version methods |
| 39 | Every new reader hunk and CLI/manifest boundary; 72 tests passed, with bounded hostile-file probes and no blocking finding for stopped, stable packets on the tested POSIX filesystem |
| 40 | Baseline preservation: all 161 parent evidence files, inherited GPU sources/tests/goldens, pins, protected illustration and historical ledgers preserved |
| 44 | Every non-stamp contract hunk and the complete export module; no actionable finding |
| 45 | Both fixture builders and all 12 packet-test modules: 4,611 lines and 245 test methods independently reviewed; no blocking defect |
| 37, 41, 43 and 46 | RV64 companion defect identified, independently reproduced, corrected and independently closed as detailed below |
| 48 | Exact-commit reconciliation of all scopes and final file identities; all runtime/test changes covered and no remaining code, review or test gate for this implementation |

Assignment 37 found that numeric `VX_CFG_XLEN=64` alone did not establish the
effective RV64 companion used by generated headers and decode paths. Assignment
41's unchanged independent specification first produced **217 expected assertion
failures across 14 methods, with zero errors** against the defective verifier.
After assignment 43's three-line contract correction, it produced **14 passing
tests in 8.105 seconds**. Assignment 46 independently reviewed that correction
and its positive/negative controls, then ran **39 tests successfully in 22.112
seconds**. Its read-only audit accepted all **18 unchanged original native
stamps**, verified their recorded identities and unchanged before/after hashes,
and rejected **144/144 independent in-memory invalid variants**. The RV64 finding
is closed for this frozen retained-stamp contract.

Review retains one nonblocking coverage observation: interrupted runs have
dedicated original-byte integration regressions, while interrupted exports rely
on the shared contract rather than a dedicated `verify-export` interruption test.
Reader rechecks also remain subject to the documented concurrent-writer and
filesystem limitations. Independent agent reviews are advisory; the user's
existing direct-commit/push authorization supplied the maintainer delivery
decision. No PR requirement or policy waiver was introduced.

All new fixture packets are synthetic test data. No new SimX, processor RTL,
full-AFU `xrtsim`, vendor `hw_emu`, synthesis, physical FPGA or silicon execution
is claimed by this continuation. The prior accepted numerical and clean-build
reviews retain their exact original scope; packet consistency does not extend it.

The separate [packet continuation ledger](p01-packet-agent-execution.json)
records **60 distinct completed worker assignments in ten logical waves of six**,
scheduled with at most three workers alongside the coordinator. Adjacent review
waves overlapped while earlier notes finalized. Follow-up messages and the
coordinator are excluded from the count. Every assignment has a result and an
evidence basis. Assignments 1–3 retain the contemporaneous coordinator discovery
checkpoint basis; separate worker note files were not retained for those three.
Assignments 4–60 retain the hashes of their individual completion notes. The
original [P00 ledger](agent-execution.json) and
[P01 execution ledger](p01-agent-execution.json) retain their own historical
counts and are not counted again. Agent counts do not qualify hardware or grant
acceptance. Assignment 60's independent final review found no remaining code,
evidence or acceptance blocker for this continuation's delivery.

The storage audit observed 53.18 GiB free with the source checkout and clean
release worktree present. The implementation's 21 changed blobs total 337,756
bytes and use only standard-library and local Python dependencies. No new tool
download, GPU build, binary, debug trace or temporary test result was published.
The 5,844-byte local validation log is archived unchanged in this documentation
completion. Existing native build directories and original evidence were not
removed or repurposed.

## Next bounded action

For P01 execution, the next bounded action remains P01-T05: resolve the qualified
vendor `hw_emu` release/platform prerequisites, pin their identities and resource
budget, then obtain and independently review the required DMA/launch/completion
evidence. Keep P01-A03 blocked while prerequisites or required execution are
missing. Offline checks and the existing vendor-free `xrtsim` result cannot close
that gate.
