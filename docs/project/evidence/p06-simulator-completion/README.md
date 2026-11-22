# P06 simulator completion evidence

## Status and boundary

This is a **development evidence packet**, based on
`42809ff0c1b81384d7c9b079e4ef786be8407600` with uncommitted completion changes.
It preserves the initial failures, focused repairs, source identities and
independent worktree reviews. It is not a clean-checkpoint qualification or an
acceptance record. The base commit identifies the starting point; each retained
receipt's source hashes identify its particular development state.

**Actual native completion execution remains `not_run`, pending hosted CI.**
The real linked SimX Processor/bounded-RAM unit and generated public-runtime
success regression still require their declared execution and source-bound
review. Pinned RISC-V preprocessing was not run by these host proofs. The
[completion contract](../../../designs/simulator_completion_v1.md) defines the
required native scope and the limits of framework and injected-host evidence.
The [development audit](../../p06-simulator-completion-audit.md) records the
implementation history and outstanding qualification work.

The retained evidence supports the specific host completion and full-platform
accounting behavior described below. It does not close P06-A02/A03, accept a new
warm measurement, change the historical `qualified=false` decision, establish
native functional execution or supply RTL/physical-device/performance evidence.

## Retained initial host records

These original records precede later helper, runner and framework refinements.
All 13 `host/initial-*` files are preserved unchanged and covered by the
[packet manifest](manifest.json). They must not be relabeled as a final
candidate rerun.

| Record | Recorded observation | Scope |
|---|---|---|
| [Backend and command processor](host/initial-backend-tests.log) | Six groups across two backends and RAM/LLC, 24 cells | Production backend/CP with controlled Processor/RAM faults |
| [Public runtime integration](host/initial-public-runtime-tests.log) | Three groups across two backends and RAM/LLC, 12 cells | Actual callback adapter, device polling, queue and event path with controlled faults |
| [Initial completion owner](host/initial-async-owner-tests.log) | Seven earlier groups pass | The later eighth group and targeted mutation proof are retained separately |
| [Pinned parent report](host/initial-parent-report.json) | Eight successfully built old-backend exception cells fail their intended assertions | The eight original raw parent logs remain beside the report; failure establishes sensitivity |
| [Initial public-fixture build failure](host/initial-public-build-failure.log) | Original failed build attempt | Preserved history, not a behavioral sensitivity result |

## Development repairs and sensitivity

The [development archive index](development/README.md) gives exact archive entry
paths. The [machine-readable index](development/index.json) records archive
hashes, sizes, scope and retained-file counts. Each archive has a per-file
manifest both beside it and inside it. Logs, commands, receipts, patches and
available original source snapshots retain their original bytes.

| Proof | Retained result |
|---|---|
| [Initial runner findings](development/w03-a05-runner-review.tar.gz) | 26 host tests ran with 10 subtest failures. Fast-math and unretained include-shadowing defects are reproduced across the five independent compiler roles; original preprocessor comparisons are retained. |
| [Runner repair](development/w04-a01-runner-repair.tar.gz) | Actual generated stamps, four host preprocessing results, option/include rejection checks and generated-template/path checks. No kernel/native execution is inferred. |
| [Assertion preservation](development/w04-a02.tar.gz) | All 15 original failure-test methods and existing assertions remain. The final source-stable receipt records 26 passing host tests; the earlier compiler-selection gap and fixture diff remain available. |
| [Ready-check mutation proof](development/w04-a03.tar.gz) | Eight helper groups pass. A built targeted mutation passes all seven older groups and fails the new `immediate_check` assertion, proving sensitivity to loss of the initial busy observation. |
| [Original framework leak](development/w04-a04-native-probe.tar.gz) | Actual timing-framework probe reproduces `inflight=1`, `idle=false` after full destruction and after fresh work is consumed. Its exit zero confirms reproduction of the defect. Despite the historical directory name, it executes no native Processor. |
| [Timing-framework repair](development/w05-a01.tar.gz) | Old header builds and fails the recovery assertion; repaired header passes release/debug checks. Both complete headers, patch and commands are retained. |
| [Actual framework regression](development/w05-a02.tar.gz) | Eight candidate timing/functional cells pass. Six successfully built parent fault/abandonment cells fail their intended behavioral assertions; two parent normal controls pass. Both source snapshots and all raw outcomes are retained. |
| [Functional-framework repair](development/w05-a03.tar.gz) | Old functional header builds and fails in release/debug; repaired header builds and passes in both. Before/after source snapshots, commands and failures remain intact. |
| [Independent lifecycle probe](development/w05-a04-cleanup-probe.tar.gz) | Four timing/functional × debug/release cells pass healthy two-executor-thread shutdown, event/inbox disposal, destruction-only late owners and fresh accounting. The two threads are the coordinator and one persistent internal worker. This supplies no internal-worker exception transport evidence. |

The framework fault tests use a joined asynchronous host task and actual
production framework headers. A failed live context remains non-idle before
full cleanup. Teardown retires abandoned accounting; it does not rehabilitate a
failed backend or permit operations on finalized objects. Same-thread direct
exception recovery, simultaneous contexts, hung-worker recovery and internal
multiworker exception transport remain outside this evidence.

## Independent reviews

The exact originals of the [native fixture review](reviews/w04-a04-native-review.md.gz)
and [cleanup review](reviews/w05-a04-cleanup-review.md.gz) are retained as gzip files.
Their adjacent readable Markdown copies remove trailing spaces only. The
development index records both the original and display-copy identities; no
finding or technical statement was changed.

These are original advisory worktree reviews with their exact recorded source
identities. Later repairs do not rewrite earlier findings. The reviews do not
constitute a maintainer waiver or exact-final-commit approval.

| Review | Scope and disposition |
|---|---|
| [Initial R3 review](reviews/w03-a06-r3-review.md) | Historical production/contract review retains fixture-brace, required-native-evidence and ready-`check()` coverage findings. The eighth helper case is addressed by the later mutation proof; native execution remains open. |
| [Native fixture source review](reviews/w04-a04-native-review.md) | Source/build-path review discovered the actual-framework accounting leak and preserved its reproduction. It ran no native unit or public regression. |
| [Runner repair review](reviews/w04-a06-runner-review.md) | No open F2/F3 runner defect at the reviewed host/source scope; native qualification remains unearned. Its [supporting proof](reviews/w04-a06-runner-proof.json) retains generated Makefile tool-prefix and record checks. |
| [Cleanup review](reviews/w05-a04-cleanup-review.md) | No concrete code blocker in the two cleanup hunks; actual framework regression receipts and the independent lifecycle probe support proceeding to required native CI. Native qualification remains open. |

## Source bounds and retention

The [source bindings](development/source-bindings.json) distinguish the stages.
The [source-at-assembly archive](development/source-at-assembly.tar.gz) retains
70 relevant source/build/contract files, including the shared compiler validator
and transitive local Python helpers. All 11 source hashes in the final 26-test
receipt match this later snapshot. Earlier proofs retain their own independent
identities; the later snapshot is not evidence that those bytes ran earlier.
This historical assembly snapshot is not final release source. Subsequent
parent-runner provenance changes are intentionally outside this development
bundle and require their separate final evidence.

| Source state | SHA-256 |
|---|---|
| Final reviewed runner | `373ed9ba9141db73e740c87ec812872bb1dc2131b29819a7f001eda7e59e5641` |
| Timing header before repair | `e5ca3afcc9b856a74d97d83c285dcfc97e40050391a7f26b9f72b1d298345df6` |
| Timing header after repair | `0e0369f5ea1ba85f5e461e03b85e9723bb47f0e118499ba2b21a7923594f7004` |
| Functional header before repair | `280e23c2a84ba5be2c563014870de7cf6b4d120af0f1221527b2919c44978616` |
| Functional header after repair | `0a62df63e18f340096bda900ccb858e00a3c2d54d7688c92737c5cca06210984` |

The initial runner `b3b5013…` and intermediate runner `9326bbc…` have original
receipts, commands, logs and full recorded hashes, but their complete exact
runner source snapshots were unavailable to this assembly. This is a retained
provenance limitation. The final runner must not be substituted for either.
The original timing/functional parent headers are available in the before/after
and actual-framework parent archives.

Compiled executables, temporary build products and Python caches are excluded;
each archive manifest identifies its exclusions. Original reports may still
refer to those historical files or to temporary absolute paths. Those reports
are copied verbatim. Small source snapshots, raw failure logs, empty stderr
receipts, compiler stamps and command records are retained.

## Outstanding checkpoint and qualification records

The following records are still separate work: final parent refresh,
full-governance verification, reviews bound to the exact checkpoint/final
commit, hosted native artifact receipts, and independent reconciliation of that
execution. Add them with their actual source identity and outcome after they
exist. A workflow definition, generated stamp, successful parser test or
header-only probe cannot supply native execution. No requested agent total or
completed-assignment ledger is asserted by this packet.
