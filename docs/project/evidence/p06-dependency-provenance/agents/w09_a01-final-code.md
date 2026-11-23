# W09-A01 follow-up — final production code and validation lineage

## Result and scope

**The final frozen production changes have independent review and focused test
coverage at their exact published bytes. No F2/F3 finding remains within this
code-diff, classification, protected-boundary and validation-lineage scope.**
This is a follow-up by the same W09-A01 agent, not a new distinct assignment.

The review inspected published Git object
`19333193192ba5a2d3667c0111235ec9e21a5898`, tree
`baeeb7bc7078e9301c68e94b1207032329be343d`. Its tree exactly equals local tested
commit `c21641a34a65e510cbf4d0e054d9acb2263d81c3`. The earlier full-suite checkpoint
is local `ba4deccd25b8f2cd08581af6785348e5ee0781bd`, tree
`80146459e865581508315a18ffd1e11dd1a0773c`, identical to published
`8b71ee07392c1ed86f654b2d683d9a8d2d1f50ea`.

The parent supplied the published identity. This assignment independently read
its fetched Git objects and verified both local/published tree equivalences;
it made no provider request. The exact
[final receipt](../validation/final-code-review.json) contains commands,
classification outputs, source-profile comparisons, protected-file identities
and metadata results.

## Production hunks and independent review

The entire `ci/project` production diff after `8b71ee07` touches four files.
Every changed hunk was inspected directly and reconciled with the corresponding
independent review and final source identities:

| Correction | Production changes | Independent review and retained limits |
| --- | --- | --- |
| Repeated compiler prerequisites | `dependency_paths()` bounds raw tokens, then retains normalized names once in first-seen order | [W09-A06](w09_a06.md) reproduces the actual GCC depfile and tiny real-compiler case. Raw depfiles remain retained; prepass/compile inventories and before/after byte identities must agree. Duplicate receipt rows and repeated build operations remain invalid. |
| Link-map payload category | Recorder retention and map parsing use existing `MAX_FILE_BYTES` | [W10-A04](w10_a04.md) proves the actual 18,084,083-byte map fits the existing 64 MiB file category. JSON and command logs remain 16 MiB; numerical resource constants, map line limits and packet bounds are unchanged. |
| Archive inputs versus selected members | Builder and receipt require yaml-cpp selection and the exact unique loads of both yaml-cpp and spdlog | [W10-A06](w10_a06.md) verifies the actual header-defined spdlog behavior and scoped real-tool controls. All spdlog compiles, archive/index, input identities and actual selected-member checks remain required. Zero selected spdlog members are recorded honestly. |

The design changes document those same distinctions. The final production hashes
are:

| File | Final SHA-256 |
| --- | --- |
| `p06_dependency_binary.py` | `81397956f856e5658864ee59f198c760699160f5d7a78d73d80db41f361814e1` |
| `p06_dependency_build.py` | `57d4840b18b9788fb01b78badb813efd58fe7090ae59a0d9acb45b7c154f980e` |
| `p06_dependency_receipt.py` | `fb277709072b1c0d589aa2a8ecb828225013eb4c984afd0e6b843a7870e27b5b` |
| `p06_dependency_record.py` | `5364a5036fb03bebed3aba6267d302cf36c379b30e7085ded1b59db077c33205` |

Those four final hashes match the relevant latest independent review identities.
The earlier W09-A06 recorder hash naturally predates the separately reviewed
map-retention correction; its specific prerequisite hunk is preserved. No
additional production hunk appears in this increment. The dependency contract,
source pins, process budgets, warnings, generic archive-member default and
native/model SoftFloat selection requirement are unchanged.

This mapping covers the formal production helpers under `ci/project`. Retained
diagnostic drivers and reviewer scripts under the evidence packet have their
own execution/review identities. This assignment does not review the running
attempt-05 original or promote a diagnostic to formal/native evidence.

## Exact relationship to the 125-test run

The [focused receipt](../validation/w10_a06-spdlog-tests-01.json) records 380
Python files before and after the run; the profiles are identical. This
assignment independently read all 380 corresponding final Git blobs as inert
archive data and found an exact set, byte-size and SHA-256 match. No source was
extracted or executed for that comparison.

The [retained log](../validation/w10_a06-spdlog-tests-01.log) is 22,766 bytes,
SHA-256 `103d1b407ad2cf5f8d9daf07ab3d6bd18ad0435bbe56aa03ad5ae7a4538a3df7`.
It matches the supervisor receipt and terminates with **125 tests in 6.283
seconds, `OK`**. The receipt's recorded HEAD is the preceding map-limit commit;
its complete before/after file profiles, now matched to final Git blobs, identify
the working correction actually tested. This assignment did not rerun those
125 tests.

Comparison with the exact 377-file `ba4deccd`/`8b71ee07` source population gives
**372 unchanged files, five modified files, three added files and no removals**.
The complete changed-file mapping is:

| Python file | Change | Focused modules present in the actual 125-test command |
| --- | --- | --- |
| `p06_dependency_binary.py` | modified | `test_p06_dependency_binary`, `test_p06_dependency_map_limits` |
| `p06_dependency_build.py` | modified | `test_p06_dependency_build`, `test_p06_dependency_spdlog_selection` |
| `p06_dependency_receipt.py` | modified | `test_p06_dependency_receipt`, `test_p06_dependency_spdlog_selection` |
| `p06_dependency_record.py` | modified | `test_p06_dependency_record`, `test_p06_dependency_repeated_inputs`, `test_p06_dependency_map_limits` |
| `test_p06_dependency_map_limits.py` | added | `test_p06_dependency_map_limits` |
| `test_p06_dependency_record.py` | modified | `test_p06_dependency_record` |
| `test_p06_dependency_repeated_inputs.py` | added | `test_p06_dependency_repeated_inputs` |
| `test_p06_dependency_spdlog_selection.py` | added | `test_p06_dependency_spdlog_selection` |

Thus every changed or added Python file is covered by an identified module in
that one focused run. The suite includes real tiny host compiles/archive/link
operations and explicit fixture substitutions; [W10-A06](w10_a06.md) states the
substituted upstream boundaries. It does not establish the entire pinned
406-unit graph, formal staging or native lifetime execution.

**The full governance run at `ba4deccd`/`8b71ee07` predates all three corrections.**
Any eventual outcome of that run belongs to the earlier checkpoint. It must not
be presented as a full-suite pass of `19333193`, and the overlapping 125, 101 and
91 focused-test results must not be added as unique tests.

## Classification from the original policy

The original `832ae981` classifier and policy copies from the earlier W09-A01
review were reused only after their hashes were checked against original,
prior and final Git blobs. Both files remain identical. Classification used
explicit immutable SHA arguments and `python3 -I`.

| Range | Actual machine classification |
| --- | --- |
| `832ae981` → `19333193` | **R2**, determinate, policy version 3; reasons `path:ci-enforcement` and `path:build-config`; no detected contract edits |
| `8b71ee07` → `19333193` | **R1**, determinate, policy version 3; reasons `path:default` and `path:normative-docs`; no detected contract edits |

The exact [aggregate JSON](../validation/final-code-aggregate-classification.json)
and [explanation](../validation/final-code-aggregate-explain.txt), and
[incremental JSON](../validation/final-code-increment-classification.json) and
[explanation](../validation/final-code-increment-explain.txt), are retained.
Independent contract review remains separately attributed; a classifier result
is not a maintainer approval, waiver or semantic proof.

## Preserved boundaries and lightweight checks

All 14 protected or historical files from the earlier boundary inventory remain
byte-identical to the original base and prior checkpoint. The three progress
documents retain their authorized milestone updates. The protected SVG and
README embedding are intact. Exact aggregate diffs remain empty for goldens,
the test catalog, RTL, SimX, software, pins, configuration, review policy,
canonical gates, acceptance policy, AGENTS, licensing and `.gitattributes`.
No historical evidence outside this new packet was modified or deleted.

The canonical roadmap remains unchanged: P06 is `in_progress` with only P06-A01
evidence, A02/A03 are open, P01 remains vendor-`hw_emu` blocked, P05 remains in
progress, and P07–P11 remain not started. The dependency contract still has the
same seven false qualification, warm and acceptance fields. The replay readers
and their claim boundaries are unchanged from the prior reviewed checkpoint.

The two lightweight checks ran from the exact clean detached
`/workspace/p06-dependency-corrected` checkout at `19333193`, using Python
3.12.14 with bytecode writes disabled. That helper checkout was clean before
and after this assignment's read-only checks:

| Check | Actual result |
| --- | --- |
| [Project structure/metadata](../validation/final-code-project-check.log) | **Pass**, exit 0, 1.628 seconds |
| [Published baseline consistency](../validation/final-code-baseline-check.log) | **Pass**, exit 0, 0.167 seconds |
| Both classifier JSON commands and explanations | Exit 0 |

The metadata outputs preserve their explicit limits: no GPU execution is
certified, no phase is completed, and original raw-log bytes or redaction
relationships are not newly verified by the baseline consistency check.

Only this new report and `validation/final-code-*` evidence were written. No
production edit, Git mutation, publication, full-suite run, dependency recipe,
original repair or native execution was performed. The later diagnostic result,
its independent original review, the complete formal/native original and final
documentation publication remain separately attributed work.
