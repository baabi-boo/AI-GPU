# P01 supplemental local qualification handoff

**All eight selected local AFU/RTL cases passed at frozen source `7e4ac585`,
across 32 monitored commands. A later clean two-unit follow-up passed at
`143c69fe`, across five commands, with the strengthened CP/LLC oracle.** The
original 1,260-test tooling-suite result belongs to `7e4ac585`; that full suite and the
eight-case matrix were not rerun at the follow-up revision. This supplemental
work leaves P01-A03 blocked on qualified vendor `hw_emu` and P02–P11
`not_started`.

After initial publication, a separate workflow-contract correction at `420937e`
passed all 1,260 tooling tests again in 257.346 seconds. The
[CI follow-up](evidence/p01-local-qualification/ci-followup/README.md) retains the
hosted failure that exposed the stale timeout expectation and the complete new
local result. It does not relabel or repeat the native executions above.

Use the [qualification guide](p01-local-qualification.md) for reproduction and
the [evidence index](evidence/p01-local-qualification/README.md) for the finished
packets, failed attempts, independent reviews and integrity checks. Local
execution, prepared GitHub objects, branch delivery and hosted CI remain
separate records.

## Source identities and delivery checkpoint

| Role | Exact tested local commit | Exact tree | Corresponding GitHub object |
| --- | --- | --- | --- |
| Starting delivered base | `4f193b0967812db9f0d13b59e10e3a2bfae6bcd9` | `8566f63c61577c080d1f8431825ac79a11e94e17` | [Delivered base](https://github.com/baabi-boo/AI-GPU/commit/4f193b0967812db9f0d13b59e10e3a2bfae6bcd9) |
| First implementation and failed attempt | `9532327e6006e0b6b09bae761745bc0d36a79b1e` | `aeedbf4d7a042e86ec8d1326370a87dd73587494` | [Prepared `b40fafe7`](https://github.com/baabi-boo/AI-GPU/commit/b40fafe705b9a38790cf0dfce3dbaa4fe48914a6) |
| Corrected eight-case retry and full tooling suite | `7e4ac5851f1f71d292ed1802c3f92456d96faf8d` | `89c28a445e0e269e53b36213a04e593f9e76b6d2` | [Prepared `dc85faeb`](https://github.com/baabi-boo/AI-GPU/commit/dc85faebd9a24ed452bc50727181b0e79c41d252) |
| CP oracle/governance follow-up and fresh unit packet | `143c69fe284bc2a1628721cf8a4237ac82d2547d` | `e8bfd26fccec91bfbcf50242d197217c64d7078e` | [Prepared `1927ea1e`](https://github.com/baabi-boo/AI-GPU/commit/1927ea1e6be06067351a1ea8048c395c8d2bc9d9) |

The [identity map](evidence/p01-local-qualification/identity-map.json) records
these local-to-GitHub mappings. Different commit metadata and parent identities
produce different commit IDs despite identical source trees. Results remain
attached to the local commit/tree actually executed; the packet retains the
original local commit objects.

The earlier prepared-object audit, retained as `identities/b09d.json` and
`identities/b09d.md` in the [archive](evidence/p01-local-qualification/packet.tar.gz),
covered the first two mappings and observed `master` still at `4f193b0` through
**2026-11-16 03:54:15.963 UTC**. It is a historical audit, not a review of the
later third mapping or proof that a branch moved. The subsequent release-integrity
review, retained as `agent-notes/b10d.md`, verifies all three mappings, their
parent chain and exact source trees. These audits preserve the branch heads
observed at their recorded times.

For delivery and hosted CI, inspect the GitHub commit containing this handoff
and its checks through [the master branch](https://github.com/baabi-boo/AI-GPU/tree/master)
and [Actions](https://github.com/baabi-boo/AI-GPU/actions). Attribute each hosted
result to its actual revision. An earlier base run does not attest a later
documentation or implementation commit.

## Completed execution and tooling results

The eight-case retry finished **2026-11-16 04:01:26 UTC**, with `state=finished`,
`outcome=pass`, all 32 commands exiting zero, cleanup complete and final
source/helper/input checks passing. All selected cases retain identical
before/after workload artifacts. The full matrix is the same fixed selection
reviewed before execution; dimensions, seeds and numerical thresholds were not
reduced to obtain the pass.

| Case at `7e4ac585` | Observed result | Exact scope |
| --- | --- | --- |
| `demo` | **Pass** | All 16 integer points / 64 bytes compare exactly, with ordered transfer/launch/readback/check stages. |
| `reopen-cold` | **Pass** | One point in each of two complete sessions; `XRTSIM_WARM_OPEN=0`; original nonce/result and session checks. |
| `reopen-warm` | **Pass** | Same two-session oracle with `XRTSIM_WARM_OPEN=1`; this is a local-shim warm-open request. |
| `axi-store-order` | **Pass** | Actual `stencil3d -n64 -b2`, all 262,144 outputs against the original six-ULP reference bound; 122 measured seed-1 reordered responses; run command 907.036865 seconds. |
| `cp-llc-port` | **Pass with original harness** | All six source test functions and all 37 original assertions. Stronger checks belong to the later unit packet below. |
| `mm-axi-arb` | **Pass** | All 13 checks; random seeds 1–8, data-before-address seeds 11–14, and 1,000 writes in 1,000 cycles within the inherited 1,016-cycle throughput bound. |
| `gemm-fp16` | **Pass** | Native TFR FP16 → FP32, `64×64×64`, eight threads, issue width two, one iteration and `match (0 errors)`. |
| `gemm-bf16` | **Pass** | Native TFR BF16 → FP32, `64×64×64`, sixteen threads, issue width one, one iteration and `match (0 errors)`. |

Both GEMMs use seed 50, CPU double accumulation of converted-input products,
strict relative error `<0.01`, and exact zero-pair acceptance. **Six ULP and
0.01 are inherited thresholds, not observed maximum errors.** Successful text
is corroborated by bounded exit, cleanup, stable artifacts and independent
output-oracle review. The retained command-processor polling warning is
warn-only without an explicit runtime override; completion and the final
numerical checks establish the result, not that warning.

The fresh follow-up finished **2026-11-16 04:03:57 UTC** from clean source
`143c69fe`, with both `cp-llc-port` and `mm-axi-arb` passing all five configure,
build and run commands. It used new build/output roots and retained final
identity checks. Only these two unit selections were rerun at this revision;
the original eight-case pass is not relabelled as execution of the follow-up.

At `7e4ac585`, the unchanged source-root discovery command completed
**1,260 tests, zero failures/errors/skips, in 293.241 seconds**, exit 0:

```sh
python3 -B -m unittest discover -s ci/project -p 'test_*.py'
```

Monitored process time was **293.547442 seconds**, cleanup was complete, the
checkout remained clean and unchanged, and all 104 inventoried source hashes
matched. The retained suite log and JSON are indexed with the independent
review. At `143c69fe`, the focused low-privilege workflow guardrail test passed:

```sh
cd ci/project
python3 -B -m unittest test_repository_contract.RepositoryContractTests.test_workflow_retains_declared_low_privilege_guardrails -v
```

That one-test check and the two-unit run do not establish a new full-suite pass.
The [member index](evidence/p01-local-qualification/index.json) locates the
suite records, `extras/ci-guardrail/record.json` and the final execution review.

## Corrections and bounded operation

- Stencil getopt recognizes `n:b:k:h`. A guard rejects zero matrix or block
  size before division/device access, including malformed block text converted
  to zero by inherited `atoi`. Nine actual-parser tests pass. This is narrow
  zero-geometry protection; general numeric parsing is unchanged.
- Helper drift retains a false check before reporting failure, including
  malformed helper files. Three additional isolated-import regressions cover
  planning, execution preflight and post-command corruption.
- Configure/build/workload children use `TMPDIR=<fresh build-root>/tmp`, created
  with mode `0700`; inherited `TMPDIR`, `TMP` and `TEMP` cannot redirect them.
  Compiler temporaries therefore use the monitored build filesystem. Parent
  inventory probes retain their separate bounded contract.
- The later governance timeout change raises the job budget from five to ten
  minutes and updates both matching CI-contract descriptions. The measured
  293.547442-second suite left only 6.452558 seconds of the earlier job budget.
  Test selection, low-privilege guardrails and failure behavior remain intact;
  this administrative timeout does not change a workload's numerical or resource
  contract.

The runner requires clean committed source, matching recursive dependency
inputs, fresh separate build/output roots, and retained tool/helper/generated
recipe identities. It reuses the pinned v3.0.2 tools and separately inventoried
prepared libraries; reuse does not establish a fresh dependency build. Actual
budgets stayed at two compile workers, **1,800 seconds per command**, **6 GiB
sampled process-group RSS**, **16 MiB combined log per command**, **15 GiB
free-disk reserve**, and **512 MiB packet ceiling**.

| Finished packet | Highest sampled process-group RSS | Free disk after completion |
| --- | --- | --- |
| Eight-case retry | **3,978,248,192 bytes** during BF16 runtime preparation | **48,867,790,848 bytes**, about **45.5 GiB** |
| Two-unit follow-up | **562,900,992 bytes** | **48,848,904,192 bytes**, about **45.5 GiB** |

These are polled observations, not hard memory/filesystem quotas or physical
performance measurements. RSS can miss peaks and double-count shared pages.
Per-command caps do not impose a single 1,800-second deadline on the entire
sequence. No numerical kernel, reference data, seed or comparison tolerance
changed.

## Configuration and arithmetic scope

All groups use RV64, one cluster, one core and four warps. Scalar/unit groups
use four threads, issue width one, explicit STD floating point and
`VERILATOR_RESET_VALUE=1`. Tensor groups retain their explicit TFR/STD/type
selectors and do not inherit the scalar reset override. Default runner
selection remains the six core cases; the executed retry explicitly selected
both optional GEMMs as well. The [fixed catalog](../../ci/project/local_qualification_cases.py)
and [guide](p01-local-qualification.md#3-select-the-fixed-cases) retain their
complete contracts.

Independent scalar and tensor reviews compare runtime, application/kernel/host,
and simulator compiler records separately, then corroborate them with actual
build commands and generated model files. The tensor model includes native TFR
arithmetic and STD scalar floating-point modules. The generated DPI headers
retain integer multiply/divide and utility imports, with **no floating-point
arithmetic DPI imports**. Thus the supported native claim is specific to TFR
tensor and STD floating-point arithmetic; integer multiply/divide remain
DPI-assisted. Passing integer applications alone does not establish
floating-point numerical correctness, and the whole AFU is not DPI-free.

Linked SoftFloat/common DPI support does not itself prove a floating-point DPI
tensor datapath was exercised. Compiler-to-artifact evidence is corroborated,
not authenticated; no historical dynamic-loader trace was collected. The
vendor compiler-record validator continues to reject these XRTSIM shim records.
The unchanged validator was not relaxed to admit a vendor-free run.

## CP oracle strengthening and fault detection

The implemented [CP/LLC harness](../../hw/unittest/cp_llc_port/main.cpp) preserves
all six functions, their order and all 37 original `EXPECT` statements. Its
44 assertions add upstream accepted-read and DMA completion counts, independent
data/tag expectations for the dedicated two reads, checks of all 48 submitted
first-word burst address/value pairs, and final total-read completion equality.
The exact strengthened source hash is
`96ec63165a5064d2a5a10a9c4e0a385d36080899ab393caad281b9765cc64282`.

Before integration, isolated paired proofs compiled original and strengthened
C++ harnesses against identical copied model bytes. Both normal baselines
passed. Three injected faults passed the original harness and failed the
strengthened harness as expected:

| Isolated fault | Strengthened detection |
| --- | --- |
| Drop all ordinary read responses | Exit 1: `exactly two DMA read responses must complete` |
| Drop only the final burst-read response | Exit 1: `DMA read completions missing` |
| Corrupt the first burst word | Exit 1: `burst write value mismatch` |

A final normal rerun of the same strengthened binary passed. Expected negative
command exits remain recorded as failures; only the enclosing mutation proof's
expectation verdict is passing. Independent review rehashed the retained proof
and verified that each pair differs only by the declared strengthening and
isolated fault. This proof reused an existing model; it did not re-elaborate
RTL. The later committed two-unit packet supplies the separate fresh
configure/build/run evidence.

The stronger checks remain limited: total completion equality is not unique
per-request identity proof, later read values are not all independently
compared, first-word checks do not establish all-word integrity, and response
backpressure is not covered. No RTL or numerical tolerance changed.

## Retained failures and independent review

The first native attempt at `9532327` finished **failed**, launcher exit 1.
`demo`, `reopen-cold` and `reopen-warm` passed; `axi-store-order` failed because
the advertised `-b2` option was rejected before device opening. Both unit and
both tensor cases remained `not_run`. All 15 command logs and 98 snapshots
remain retained. The retry preserves the same fixed dimensions and thresholds.

The independent tooling suite at that source also failed: **1,246 test
methods**, with one failure and one error in the two subcases of
`test_helper_drift_before_and_after_launch_is_detected_from_actual_bytes`.
The prelaunch case lacked its check record; the postlaunch case retained
`helpers_match=true`. This is separate from the stencil CLI failure.

The first CP mutation-proof attempt stopped during inventory, before any
harness compilation or simulation: it incorrectly required a dangling shared
`libstdc++.so` path. The corrected inventory retains the actual static library
identity and all original flags, faults and expectations. Its failed report and
five metadata-command logs remain alongside the successful proof. The smaller
stencil diagnostic is retained as nonqualification evidence; it does not stand
in for the completed `64×64×64` case.

The [review index](evidence/p01-local-qualification/index.json) locates the
runner/inventory/process review, case-oracle and stencil reviews, scalar and
tensor compiler evidence, original failed-packet review, CP implementation and
mutation audits, documentation review, and final execution review. Earlier
reviews remain at their original checkpoints: for example, the initial tensor
review observed FP16 complete and BF16 pending; the finished retry and final
review establish the later BF16 result.

The final independent execution review passes with no required fix. It
reconstructs all ten selected-case evaluations across the two finished passing
packets, verifies all 37 monitored command exits and cleanup results, checks
retained identities, and confirms that earlier failures and expected negative
mutation exits remain intact. Its review is `agent-notes/b10b.md` in the indexed
archive, alongside the underlying execution and mutation-proof records.

The final preservation audit at `143c69fe` passes with the CP and timeout
changes applied. RTL, simulator, native runtime, kernel, tensor arithmetic,
reference tolerances, catalogs, golden files, protected README SVG, historical
acceptance records and all 36 acceptance criteria remain preserved. The stencil
host CLI and CP test harness are the explicit test-source exceptions; the whole
test tree is not described as byte-identical. Independent reviews are scoped
engineering evidence, not invented human approvals or phase acceptance.

## Published evidence and verification inputs

All final public locations are under
[`evidence/p01-local-qualification/`](evidence/p01-local-qualification/README.md).
The linked files provide the complete verification inputs requested by the
independent documentation review:

| Input | Public location and purpose |
| --- | --- |
| Evidence entry point | [README.md](evidence/p01-local-qualification/README.md): packet layout, verification and final bundle identity |
| Complete public packet | [packet.tar.gz](evidence/p01-local-qualification/packet.tar.gz): deterministic archive of retained text evidence |
| Raw/public file mapping | [manifest.json](evidence/p01-local-qualification/manifest.json): exact raw/public sizes and SHA-256 values with declared substitutions |
| Member/review index | [index.json](evidence/p01-local-qualification/index.json): native attempts, unit follow-up, diagnostics, reviews and raw commit objects |
| Actual distributed digests | [SHA256SUMS](evidence/p01-local-qualification/SHA256SUMS): final archive, manifest, index, identity/ledger and verifier-file checksums |
| Tested-to-GitHub identities | [identity-map.json](evidence/p01-local-qualification/identity-map.json): exact source-tree mappings and timestamped identity audits |
| Completed assignment records | [agent-ledger.json](evidence/p01-local-qualification/agent-ledger.json): actual tasks, review outcomes and note identities |
| Native-attempt verifier | [export_local_packets.py](evidence/p01-local-qualification/export_local_packets.py): retained reviewed native format implementation |
| Complete-packet verifier | [export_final_packets.py](evidence/p01-local-qualification/export_final_packets.py): final wrapper, requiring the adjacent native verifier |

The archive's `native-attempts/` holds the failed and successful eight-case
attempt records; `local-units-followup/` holds the separately committed unit
report, logs, snapshots and launch sidecars. `extras/` holds the nonqualification
stencil diagnostic and both CP mutation-proof attempts. `agent-notes/` and
`identities/` retain the scoped reviews, assignment evidence, earlier prepared
identity audit and original commit bytes. Resolve individual receipt names
through the linked index and manifest; these are archive member paths, not
unpublished scratch prerequisites.

Public copies may have declared local paths substituted. Embedded report hashes
identify **raw bytes**; the manifest's public hashes identify **distributed
bytes**. The previously reviewed failed-attempt export had **125 files /
1,722,383 bytes**: a public copy of every raw report/log/snapshot, seven sidecars
and four metadata files; declared path substitutions are recorded per file.
Its earlier staged identities below remain historical anchors, not the final
combined archive identity.

| Retained anchor | SHA-256 |
| --- | --- |
| First failed raw `report.json` | `94945483a8e98ffd3bbcecc9cc7d834e83854fd4be50dec9269dac40db108fac` |
| Completed eight-case raw `report.json` | `2eff867a0acddc669e134720c3d927a9c757722a8d178ccb70a8c5d88186df18` |
| Completed two-unit raw `report.json` | `74ec643d147a6ffb167381bbf9795e78a295b5368ac1b6e2b9d49eff0e721c3c` |
| Earlier failed-attempt public manifest | `dd7a35acb5088c30b3376090a46409f5b1be706a369aba99bb1c39d67c11f077` |
| Earlier failed-attempt staged archive | `3b85bd44c9788d573811b940bffff12404553d9e7bce5d80c6d868561c4b5662` |
| Corrected full tooling-suite raw log | `95ed5e2133ac717fe280c5aaf6de8076743e316a3fe3604233ad559128e87b1b` |

Use the [guide's verification procedure](p01-local-qualification.md#7-verify-raw-evidence-and-public-copies-separately)
with the final checksum inventory and both adjacent verifier files. Public-only
checking verifies manifest-relative integrity and recorded linkage; original
workspace verification additionally reconstructs the declared transformations.
The manifest is unsigned and does not authenticate execution. Binary models,
compiled applications and kernel images retain identities but are not copied
into this text packet.

## Publication follow-up — exact governance timeout assertion

The first published-head [governance run](https://github.com/baabi-boo/AI-GPU/actions/runs/43804865837)
at `1b1bf572` completed 1,260 tests in 197.634 seconds with one failure: an
existing workflow-contract assertion still expected five minutes after the
reviewed workflow budget changed to ten. The complete failed log and terminal
run/job metadata are retained in the separate
[CI follow-up evidence](evidence/p01-local-qualification/ci-followup/README.md).

Local source `420937ede5c72653cf4abc7042caf9bec19c88b2`, corresponding to
[GitHub `f269505c`](https://github.com/baabi-boo/AI-GPU/commit/f269505cd15b69c853c04fd0b9c3d0adae7d81a1),
changes only that exact assertion from five to ten. Its source tree is
`726d6e77166e1e47a0ee8e271696a5982c3b0e90`. The workflow and all other guardrails
remain unchanged. Independent review confirms exact equality is preserved.

The clean corrected source completed **1,260 tests, zero failures/errors/skips,
in 257.346 seconds**, with exit zero, completed cleanup and all 104 source-input
hashes unchanged. The follow-up retains the full result, log, original commit
bytes, source mapping and independent completion review. Its later hosted result
belongs to the GitHub commit containing these files and must be read from that
commit's checks. The original nine evidence files, archive and 60-note ledger
remain byte-for-byte unchanged; this correction reuses existing agents and
records their later work separately.

## Preserved acceptance and next bounded action

P00 remains complete. [P01-A01](evidence/p01-build.json) and
[P01-A02](evidence/p01-native.json) retain their accepted historical clean-build
and six-case numerical evidence. [P01-A03](evidence/p01-xrt-blocked.json)
remains blocked on a qualified vendor release/platform and full XRT `hw_emu`
DMA/launch/completion evidence. P02–P11 remain `not_started`.

The prerequisite observations did not establish usable `v++`, Vivado, `xsim`,
`platforminfo`, `emconfigutil`, or matching platform/xclbin/emconfig runtime
closure. No qualified bundle fitting the observed environment was identified;
that does not prove every smaller or older installation impossible. The local
shim models host/device memory and loads no vendor device image. Its results
cannot establish physical DMA/cache coherence, FPGA operation or silicon
behavior. `vendor_execution_performed`, `qualifies_P01_A03` and `phase_complete`
remain false even for the finished passing packets.

The next bounded action is to identify a compatible vendor release and supported
platform whose compiler, simulator, runtime and build inputs fit the recorded
resource budget; freeze their identities, retain actual matching build
provenance, and independently review the execution runner's own manifest and
receipt before bounded DMA/launch/completion execution. Follow the
[XRT integration guide](p01-xrt-integration.md) and
[acceptance policy](acceptance.md), preserving all failed attempts and the
separate local-evidence scope.
