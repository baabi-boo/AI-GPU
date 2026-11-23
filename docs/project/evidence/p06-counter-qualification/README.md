# Complete counter qualification: four-process original

The separately selected [complete counter qualification v1 route](../../../designs/complete_counter_qualification_v1.md)
passed a fresh local RV64 timing-SimX preflight at
[`17e0284496bab10c7632a48e4f91efb6fb4fec0b`](https://github.com/baabi-boo/AI-GPU/commit/17e0284496bab10c7632a48e4f91efb6fb4fec0b).
Its four FP16/BF16 by allocation-policy processes completed **132 launches and
4,224 exact FP32 output-word checks, with zero mismatches**. Complete public
replay also passed. The derived qualification applies only to those recorded
four processes; the qualified 24-process warm route, its execution and
P06-A02/A03 remain open.

Start with the [audit](../../p06-counter-qualification-audit.md) for the priority
decision and findings, the [handoff](../../p06-counter-qualification-handoff.md)
for the next development step, and the [runbook](runbook.md) for the exact
three-stage execution, packaging and public replay procedure.

## Implemented route

| Boundary | Implementation and responsibility |
| --- | --- |
| Frozen source argument | [Contract](../../../../ci/project/p06_counter_qualification_contract.py) and [proof](../../../../ci/project/p06_counter_qualification_proof.json): 33 available selectors, 40 cumulative components, 12 unavailable selectors and ten lifetime premises |
| Historical prerequisite evidence | [Prerequisite reader](../../../../ci/project/p06_counter_qualification_prerequisites.py): replay the independently pinned diagnostic and local attempt-04 control originals, retaining their separate populations and source identities |
| Admission before launch | [Admission](../../../../ci/project/p06_counter_qualification_admission.py): verify proof, source/dependency projections and prerequisite originals before any recorded build or native command |
| Fresh qualified preflight | [Explicit executor](../../../../ci/project/p06_counter_qualification_execute.py): bind proof and admission into build identities and each process identity before launch; require lifetime and fresh-dependency modes |
| Complete retained consistency | [Explicit replay reader](../../../../ci/project/p06_counter_qualification_replay.py): reconstruct dependency compilation, both builds, raw process observations, source/product stability and complete archive inventory without executing retained payloads |

The native configuration is the fixed `p02-tfr` topology with `PERF=1`, checked
64-bit counters, one simulation worker, one context and one submitter. L2, L3,
virtual memory, WGMMA and CP-on-LLC are disabled. Pending reads are a transient
balance, not a forty-first cumulative component. Qualification retains the
existing meaning of `memory_lt`; it introduces no physical-latency claim.

## Actual execution and independent review

The [execution summary](native/attempt-01-execution-summary.json) records a
950.992224-second successful three-stage attempt: preparation 86.505590 seconds,
fresh dependency compilation 541.182389 seconds, and native qualification
323.245897 seconds. The [supervision receipt](native/attempt-01-supervision.json)
retains exact invocations, stage outcomes and observed cleanup.

| Verified original population | Count |
| --- | ---: |
| FP16/BF16 by allocation-policy processes | 4 |
| Launches, including each process's prime | 132 |
| Exact FP32 output words, including primes | 4,224 |
| Counter snapshots | 16 |
| Available selector queries / successful half replies | 528 / 1,056 |
| Unavailable rows, without queries | 192 |
| Separately accounted cache-flush reads / DCR reads | 132 / 1,188 |
| Native outer command receipts | 37 |
| Retained native source files | 1,057 |

The [numerical review](agents/w07_a01.md) independently reconstructs expected
bits and verifies every prime and sample. The [lifetime review](agents/w07_a02.md)
checks run/reset ordering, pending balances, terminal vectors and all four
destructions. The [build/load review](agents/w07_a03.md) joins 864 immutable
superproject blobs and 193 pinned dependency headers to actual builds and loaded
libraries; both allocation policies share the same guarded binary per format.
The [binding review](agents/w07_a04.md) independently reconstructs both build
bindings, all four process bindings, raw echoes and stability observations.
The [dependency review](agents/w06_a04.md) separately validates the fresh receipt's
406 compilations, three archive operations, two index operations and two links.

These counts describe different evidence populations. Diagnostic controls,
historical prerequisite processes, replay invocations and repeated reviewer
tests are not additional native qualification processes.

## Original archive and selected replay inputs

The complete original is supplied separately as
`AI-GPU_P06_counter_qualification_17e02844_2026-11-23.zip`.
It is **41,577,668 bytes**, with SHA-256
`9a0f1088f7a6d70a2ec17c705a61bdbbb2ea59cb815a3327aec817d0120d05a0`.
It contains **5,045 regular-file members**, expanding to 201,249,945 bytes,
under exactly `dependency-build/` and `native-qualification/`. The ZIP is not
committed here. Its [archive summary](native/attempt-01-archive-summary.json),
[compressed complete member inventory](native/attempt-01-archive-members.json.gz)
and [independent completeness review](agents/w07_a06.md) remain in this packet.
Every member was compared with the completed original directories; originals
were not rewritten during packaging.

The [actual public CLI invocation](native/attempt-01-replay-execution.json)
retains the separately selected expectations. These are the raw-byte SHA-256
pins for this original, not interchangeable semantic or Git-tree digests:

| Selected input | SHA-256 |
| --- | --- |
| Qualification ZIP | `9a0f1088f7a6d70a2ec17c705a61bdbbb2ea59cb815a3327aec817d0120d05a0` |
| `dependency-build/report.json` | `5b754be521277cd133ea28a8c1cac3e71105639a2e3cd314bf1ca9db6c8a4dbc` |
| `native-qualification/report.json` | `576b77872d6b918e3dbe30cef4107481f39ee73c346a813562e7e916b2afd7c4` |
| `native-qualification/snapshots/source-before.json` | `ad48858ab29a605747c19679bdbee82fd1a260cd36b9f3df8f27b297657b5fc1` |
| Frozen qualification proof | `d12718e9b182a3c93eab346901b380031516d556dd823017a63831d4a0304b4e` |
| Historical diagnostic `run-45034575685-attempt1.zip` | `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb` |
| Historical `AI-GPU_P06_local_attempt_04_passed_2026-11-23.zip` | `d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f` |

The diagnostic original is retained in the
[diagnostic packet](../p06-counter-diagnostics/native/run-45034575685-attempt1.zip).
The historical control ZIP is a separate required input, not a subtree of the
new original. The proof also freezes the diagnostic
[public source inventory](../p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json)
at SHA-256 `bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`.
If any required original is unavailable or its identity differs, stop replay;
do not substitute a summary, repacked ZIP or newly selected digest.

## Original and corrected reader evidence

The original reader at `17e02844` passed public CLI replay in 35.747677 seconds.
Its [compact result](native/attempt-01-replay-summary.json) is a derived summary;
the [complete unchanged result](native/attempt-01-replay-full.json.gz) is retained
separately, with uncompressed SHA-256
`7675edaaee1c7baedb9016382cdbdc6250f670f3a534194436701be12c2dddbd`.
The independent [guarded ZIP replay](agents/w07_a05.md) obtained the identical
result, admitted only the three selected ZIPs and 94 trusted files for file-byte
reads, and observed zero prohibited events. Its documented trusted Python
execution exceptions are separate from retained-payload execution.

That review identified twelve already pinned reference files absent from the
reported 82-helper inventory. The correction explicitly inventories all **94
trusted inputs** before and after replay. The exact corrected reader bytes,
later published at
[`220399748ecab84d48ba5a5f123457c44a0c8699`](https://github.com/baabi-boo/AI-GPU/commit/220399748ecab84d48ba5a5f123457c44a0c8699),
passed [unmocked replay of all three unchanged originals](agents/w08_a03.md).
The [complete corrected result](validation/w08_a03-updated-reader-replay-full.json.gz)
has uncompressed SHA-256
`c42dbcd166cbcb284cfa1e59da3767d59255bdd29fd6edb431733c7fa0ce7fc6`.
**Only `trusted_reader_sources` differs** from the original complete result.
The 77 runner helpers, 79 admission inputs, proof, native observations and all
claim fields remain unchanged. This was an inventory/stability improvement,
not an observed admission bypass.

The [publication receipt](validation/corrected-checkpoint-publication.json)
records that reviewed local commit `0093cf60d881a177634ce1a2247e053fc9d2b94e`
and published `22039974` have identical tree
`037a667b7a3238061ff1d4894503bd26c741c7c3`.
The [independent correction review](agents/w08_a05.md) covers every changed hunk,
the 94-file inventory, twelve late-reference mutation subcases and the fixture
correction. The [compatibility review](agents/w08_a06.md) verifies historical
route rejection and all 76 protected inputs.

## Adversarial checks and governance scope

Actual-packet [numerical and pending-balance mutations](agents/w08_a01.md) and
[interior-stability and process-proof mutations](agents/w08_a02.md) were rejected
through the unmocked public reader after dependent digests were repaired. They
exercise semantic rejection, not merely a mismatched outer archive hash. All
selected originals remained unchanged. Reviewer instrumentation interruptions
are retained separately and contribute no product-test pass or failure.

The initial full governance execution exposed a shared CMake fixture selecting
tools from the caller's PATH before invoking them in a sanitized environment.
The [fixture correction](agents/w08_a04.md) matches production PATH selection;
all 24 affected tests passed with zero skips, and the poisoned-PATH regression
failed against the old behavior. The corrected reader's 23 focused tests also
passed. These scoped, overlapping results are not a full-suite count. Consult
the [coordinator audit](../../p06-counter-qualification-audit.md) and retained
validation receipts for the complete governance and final publication outcomes.

## Claims that remain separate

`counter_qualification_passed=true` is scoped to
`recorded-four-process-preflight-only`. All seven historical fields remain
false: `qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`,
`acceptance_claimed`, `performance_acceptance` and `phase_acceptance`.
Replay reports `native_execution="not_run"`, `retained_code_executed=false` and
`origin_authenticated=false`. Retained consistency does not authenticate an
arbitrary producer or establish independent Git membership; the source-object
reviews supply their separately stated checks.

The [next bounded action](../../p06-counter-qualification-handoff.md#next-bounded-development)
is to implement and independently review the explicit qualified route for the
unchanged 24-process warm contract, then execute that experiment. Historical
warm-v1 rejection, the accepted cold baseline, P06-A02/A03, vendor P01-A03,
physical FPGA/silicon obligations and the inherited DSP-area finding remain
unchanged. This packet establishes no speedup or phase completion.
