# P01 XRT tooling review

## Revision and disposition

Review date: 2026-11-16 UTC. Shared source base:
`91b82fe300f94ab0a70dd0e0e4a69a0e23b16101`.

| Scope | Exact revision and tree | Validation boundary |
|---|---|---|
| Original XRT implementation | `42e36724a2f2a02766b26de8deb9b04b7557fa27`, tree `c0f28a660c0a5c8b16d3f82adee06d104668d4e5` | Historical 875-test pass and original XRT production review |
| First integration preserving concurrent `81e35e97d2fa410bbfbb970b53ccc179b0aa8d27` | `236770d6083ae88749e1830dd08eb72ee4327f97`, tree `449e538d1066df343b501ab365fa521cb2cdc2fa` | Historical 1,071-test pass and A49–A54 merge/evidence scopes |
| Latest integration preserving concurrent correction `e9e36c1cdccf975e330d9a9d2d67f3df9e50ba98` | `ae27591d1e4b7c9f2ec802c75fd6556b95a0483b`, tree `9d2be910dd14ce4e6fabf2e30e4d84db98d835c7` | 1,075-test exact-integration pass, separate from earlier results |

The concrete original XRT findings below have bounded corrections and passing
regressions. No unresolved concrete F2/F3 remains in that recorded correction
chain. The separate read-only preparation planner's **F1 compiler-glob finding
remains open and unwaived**. Review attribution retains each assignment's
actual scope; earlier review is not relabelled as inspection of later hunks.
A56 synthesizes the retained A42 draft and later records without running tests
or extending a review beyond the bytes its author inspected. This document and
its evidence packaging are subsequent documentation, separate from the named
source checkpoints. No waiver, vendor qualification or phase acceptance is
granted here.

The user's existing instruction authorizes implementation, testing, commits
and direct delivery to `baabi-boo/AI-GPU` on `master`. It establishes the delivery
route for the [review policy](../review/code-review-policy.md), without invented
PR approval or external sign-off. The [handoff](p01-xrt-handoff.md) separates
publication from local commits; no combined-continuation push, remote readback
or hosted-CI outcome is yet observed here. Assignment identifiers attribute
actual work and do not establish completion of a requested assignment count.

## Impact and applicable obligations

A39 classified the original exact base-to-implementation delta using immutable,
hash-verified copies of the **base revision's** classifier and policy. A53
separately classified both immutable integrations using those base-policy inputs.

| Classified delta from the shared base | Paths by class | Result |
|---|---|---|
| Original `42e36724a` | 32 total: seven R0, 24 R1, one R2 | Determinate R2, policy version 3; `xrt.ini.in` supplies `path:sw-stack` |
| First integration `236770d6` | 58 total: 11 R0, 45 R1, two R2 | Determinate R2, policy version 3; shared INI and Tcl supply `path:sw-stack` |
| Latest integration `ae27591d` | 59 total: 11 R0, 46 R1, two R2 | Determinate R2, policy version 3; shared INI and Tcl supply `path:sw-stack` |

Classification and explanation exited 0, and no R3 contract detector fired.
These are advisory classifications of the named source deltas; they do not
classify later documentation as if it were already in a tested tree or waive
any finding. The original
[verification packet](evidence/p01-xrt-tooling/verification.json) remains
historical; the separate
[merge packet](evidence/p01-xrt-merge/merge-verification.json) retains the
combined observations and latest exact-revision result separately.

The `configure-copied` reminder applies to
[xrt.ini.in](../../sw/runtime/xrt/xrt.ini.in). The
[generated-INI regression](../../ci/project/test_xrt_configuration.py) and
[generated-build integration test](../../ci/project/test_xrt_generated_build.py)
execute actual `configure` in fresh, separate RV64 build trees. They passed in
the original suite; reconciled configuration behavior also passed in A50's
four-test focused run and both combined suites. No RTL or SimX timing
implementation changed, so conditional Beacon and `model_parity` obligations
are not triggered. Neither workload is represented as run or passed.

## Findings, corrections and attribution

These closed findings have high-confidence `static-proof` evidence, with
concrete reproductions or regression observations where stated. Production
authors and independent test/review assignments are identified separately.

| Concrete failure or mismatch | Bounded correction and verification |
|---|---|
| The generated XRT INI named a nonexistent Tcl path; the inherited `run-xrt` recipe also overwrites an exported INI and enables unbounded wave logging. | A09 corrected the source path, with an actual-configure regression failing before and passing after. A06 identified the override; A10 implemented direct demo launch with a retained tracing-disabled INI. A13 independently checked command/environment routing; A36 reviewed the final command path. The later merge separately preserves lean generated INI defaults and an opt-in Tcl waveform guard. |
| JSON numeric overflow became infinity, and effective flags missed compiler-valid separated `-D`/`-U` forms. | Root corrected finite-number parsing in [the contract](../../ci/project/xrt_contract.py) and token parsing in [the inventory](../../ci/project/xrt_inventory.py). A11's [40 contract tests](../../ci/project/test_xrt_contract.py) and A12's [36 inventory tests](../../ci/project/test_xrt_inventory.py) independently cover rejection. |
| Log budgets could exceed the parser ceiling; enormous numeric inputs escaped validation; positive fractional timeouts were inconsistently rejected. | Root aligned the 16 MiB ceiling and numeric validation in [the runner](../../ci/project/xrt_baseline.py). A14's [37 boundary tests](../../ci/project/test_xrt_boundaries.py) pass, including exact-size and overflow cases. |
| A malformed post-plan manifest escaped without a checkpoint; final retention could copy changed configuration or permit late input/binary/log drift. Receipt-linked logs and emconfig bytes also needed portable retention. | Root moved and repeated identity checks around retention, verifies copied bytes, and preserves safe failure checkpoints. A13 identified the manifest case; A17's [15 independent drift tests](../../ci/project/test_xrt_drift.py) include three initially failing false-pass reproductions, exact retained bytes and the corrected manifest transition. |
| Retained writes could consume the disk reserve before command monitoring, and parent header-generation temporary storage was unmonitored. | A18 reproduced both gaps. A19 added per-payload/checkpoint headroom checks, parent-temp monitoring and an explicitly capped 16 KiB emergency failure-status checkpoint, with [11 resource tests](../../ci/project/test_xrt_resources.py). A28 independently reviewed these changes without an additional resource finding. |
| SIGTERM during host probing could leave a process group alive and a running checkpoint. | A18 reproduced the leak; A21 supplied [temporary signal handling](../../ci/project/xrt_signals.py), and root integrated it around execution. The [six cancellation tests](../../ci/project/test_xrt_cancellation.py), including the initially failing probe cases, pass after integration. A28 reviewed the wrapper and checkpoint behavior. |
| Vendor-first library lookup could shadow generated Vortex libraries, and the unversioned coreutil alias did not bind its actual SONAME lookup. Relative PATH entries could also select different compilers across working directories. | A20 demonstrated these failures. Root fixed search order and PATH validation and separately bound `clang++`; A22 added [selected-runtime inspection](../../ci/project/xrt_runtime.py) with real CPU ELF tests. A23's [15 independent tool-selection tests](../../ci/project/test_xrt_tool_selection.py) and A26's [20 independent runtime-integration tests](../../ci/project/test_xrt_runtime_integration.py) pass. |
| Git could report clean source while `skip-worktree` or `assume-unchanged` hid tracked modifications. | A24 reproduced the bypass. A25 added the bounded recursive [source-index guard](../../ci/project/xrt_source.py) and [15 real-Git tests](../../ci/project/test_xrt_source.py). A30 independently reviewed the guard/integration, reran those tests, and reported no F2/F3 finding. |
| Cached build/output roots could be retargeted after planning, causing writes into protected source or an unrelated populated build. | A28 reproduced both wrong-root writes. Root added canonical-root, destination, cwd and make-directory revalidation at execution/write/launch boundaries, plus repeated initial freshness checks. A32's [22 independently authored regressions](../../ci/project/test_xrt_path_revalidation.py) confirm protected bytes remain unchanged and affected commands do not launch. A43 subsequently reviewed the exact final production hunks at `42e36724a`. |
| A valid but incompatible ELF32 coreutil could be skipped by a 64-bit loader in favor of an alternate RUNPATH library, while unchanged inspector observations claimed the pinned selection. | A29 reproduced actual CPU-loader fallback. A31 added basic ELF validity and class/data/machine compatibility checks for all four selected objects. A33's [eight independent regressions](../../ci/project/test_xrt_elf_compatibility.py) produced 16 expected assertion failures against the preserved old helper, then passed with zero skips after correction. This includes real fallback rejection; A29's earlier review is not represented as a later parser-hunk review. A43 subsequently reviewed the final header parser and four-object compatibility checks at the exact candidate bytes. |

A34 independently reconciled the [integration guide](p01-xrt-integration.md)
with the final runtime/path behavior. A35 audited protected assets and
governance, with no finding: existing accepted evidence, phase gates, goldens,
toolchain pins, workflows, licensing, attribution and the protected SVG remain
unchanged. Its project metadata check passed. A36 independently reviewed the
candidate's selected command/build path and found no concrete reachable
mismatch. A39 checked relevant recorded file hashes against candidate blobs;
earlier uncommitted snapshots are not silently relabelled as final-revision
reviews.

## Final production review and merge preservation

A43 independently read the complete final `xrt_runtime.py` and
`xrt_baseline.py`, compared A31's preserved old helper, and explicitly inspected
the final ELF-header parser, four-role probing and compatibility checks. Its
path scope included initial freshness, canonical roots, retained writes,
checkpoint behavior and command cwd/Make/log validation. It reviewed A32's
22 path regressions and A33's eight ELF regressions without rerunning them.
The two production files and three reviewed regression files were byte-bound
to `42e36724a`; no additional concrete supported-configuration finding emerged.
This closes the earlier final-hunk review coverage gap without changing the
recorded test authorship or the ELF/path limitations below.

| Assignment | Actual merge-related scope and outcome |
|---|---|
| A49 | Read-only coexistence review of the original XRT and concurrent preparation implementations: separate schemas, build roots, command construction and budgets; no new production compatibility defect. It preserved the open planner F1 and reviewed A51's wording. |
| A50 | Reconciled the shared configuration file from one local and four concurrent tests into four behavioral tests, preserving both parents' assertions. Actual focused `test_xrt_configuration.py` run: four pass, zero skips, exit 0, 3.441 seconds. |
| A51 | Reconciled README/status/navigation/runbook wording for inventory versus plan, distinct input schemas, lean shared INI, direct smoke INI and no automatic promotion. No code execution or suite result was claimed. |
| A52 | Independent exact-identity and semantic preservation audit at `236770d6`: all original XRT modules and other XRT tests preserved; concurrent preparation modules/tests/docs preserved; shared INI/Tcl match `81e35e97`; protected assets, historical evidence, pins and goldens unchanged. No new merge-induced F1/F2/F3 was identified. |
| A53 | Retained distinct first/latest merge identities and base-policy classifications; its latest object comparison confirms XRT helpers match `42e36724a`, preparation modules match `e9e36c1`, and shared INI/Tcl match `81e35e97`. Historical raw evidence is not relabelled as a later run. |
| A54 | Audited collection/composition and root's actual 1,071-test first-merge result, including all selected source hashes and all test IDs/statuses; no discrepancy found and no test rerun. This scope remains bound to `236770d6`. |
| A57 | Independently parsed all 1,075 unique test blocks with terminal `ok`, including the multiline SST case; verified all 92 selected source hashes against `ae27591d` and current files, all 21 merge-packet artifacts, and exact preservation of eight preparation modules and seven XRT helpers. Reviewed the Git correction's private child environment and separate XRT wrapper; no merge-attributable issue. No test rerun. |
| A58 | Project governance and whitespace checks passed; 104 local Markdown targets, 34 retained artifact identities and 19 packet JSON files verified. Exact test checkpoints, independent workflow contracts and acceptance/F1 boundaries remain consistent. |
| A59 | Confirmed the final concurrent update is documentation only, the pending payload contains only small UTF-8 text files, and 283 protected paths retain their base identities and bytes. Recorded actual available storage and preserved the SVG embedding and attribution. |
| A60 | Independently verified the third merge's exact parents and two-document delta, preservation of concurrent delivery records, all 92 tested-source identities, 21 packet hashes, actual sixty-agent identities and 59 prior completions, all 56 prior note hashes, and 207 local targets. No concrete release blocker found; its completed report then supplies the sixtieth ledger completion. |

The shared configuration consolidation is **1 + 4 → 4**, because both parents
checked the same generated hook. The merged cases preserve the exact tracked
path and file check, a stronger no-`@` assertion, lean INI defaults, no waveform
calls for unset or non-opt-in values, and exactly one recursive waveform call
for the exact string `1`. The original fresh RV64 configure isolation and
explicit unused tool/install destinations remain. Missing Tcl is an explicit
skip; the actual focused and first combined executions recorded zero skips.

The later concurrent correction changes `hwemu_source.py` to supply fixed
`GIT_CONFIG_NOSYSTEM=1` and `GIT_CONFIG_GLOBAL=os.devnull` after stripping
inherited Git environment values. Repository/worktree configuration and explicit
includes remain visible to unsafe-filter and partial-clone inspection. Its four
new regressions are preserved exactly in the latest integration. The concurrent
[preparation handoff](p01-hwemu-handoff.md) retains its own correction review and
historical hosted-failure evidence. A52's first-merge review is not represented
as review of this later correction, and local merge validation does not imply
hosted recovery.

A subsequent documentation-only merge, `91d52abdf41b6994e4184b7a4566fa055649e6e7`,
preserves the concurrent completed handoff and ledger from `fb53ef0`. Its exact
delta from `ae27591d` consists of those two documents. It changes none of the
production or test identities in the 1,075-test run; the two independent
continuations' assignment ledgers remain separate.

The same A60 performed a publication-transport follow-up after the terminal
could not obtain HTTPS credentials. Independent GitHub readbacks verified all
five imported commits' exact trees and ordered mapped parents. The
[publication map](p01-xrt-publication-map.json) retains raw local commit bytes;
their lengths, SHA-256 values and Git object SHA-1 identities reproduce every
original local checkpoint. The actual test runs retain their original local
revision/tree and timestamps, and the map does not authorize manifest or receipt
revision substitution. No identity blocker was found. This follow-up is neither
an additional agent nor a new test execution; object-import verification remains
separate from the later branch update and hosted checks.

The two tools remain independent. `hwemu.py` planning inspects its own existing
build and emits a candidate with `launch_ready=false`; the XRT runner requires
its own reviewed manifest/receipt and a fresh build, constructs fixed commands
and applies its own CLI budget. Shared `schema_version: 1` is not schema
compatibility. There is no adapter or automatic promotion. The planner's
unquoted-compiler-glob limitation and required effective-invocation review
remain in the [backlog](backlog.md), with no waiver or acceptance change.

## Executed evidence and limits

Root used the following source-root command for the retained full-suite checkpoints:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

Original `42e36724a` result: **875 tests passed, zero skips, exit 0**, from
2026-11-16 00:29:34 to 00:31:12 UTC. The retained log reports 98.655 seconds of
test execution; metadata records 98.862 seconds wall time. The
[verification record](evidence/p01-xrt-tooling/verification.json) binds the
command, revision, logs and classification evidence. This document synthesizes
those records; its authorship does not add a test run.

First integration `236770d6` result: **1,071 tests passed, zero skips, exit 0**,
from `2026-11-16T00:57:41.503468+00:00` to
`2026-11-16T00:59:43.774332+00:00`; 121.926 seconds unittest execution and
122.255 seconds wall time. The count is `875 + 193 + (4 - 1) = 1,071`, retaining
the original runner coverage, concurrent preparation tests and consolidated
shared configuration behavior. The record retains clean before/after state and
unchanged selected source files, which A53/A54 independently checked against
the immutable tested commit. Those selected bindings are not a full-filesystem
snapshot.

Latest integration `ae27591d` result: **1,075 tests passed, zero failures,
errors or skips, exit 0**, from `2026-11-16T01:05:12.345327+00:00` to
`2026-11-16T01:07:19.931192+00:00`. The actual log records 127.156 seconds
unittest execution and terminal `OK`; metadata records 127.569 seconds wall
time, clean before/after checkout state and unchanged hashes for 92 selected
source files. The count is `1,071 + 4 = 1,075`, including the preserved
Git-configuration regressions. The separate merge packet binds this later run;
earlier results remain historical, and subsequent documentation is not
represented as part of a previously tested tree.

The suite includes inert file-backed orchestration, disposable local Git
repositories, tiny host-compiled CPU ELF fixtures, process-cleanup tests and
actual configuration generation. A38's read-only live `probe` remains blocked
by absent `v++`, `vivado`, `emconfigutil`, `platforminfo`, `xsim`, vendor roots
and reviewed platform/artifact inputs. The deliberately invalid example `plan`
also blocks. Neither launched a vendor workload.

No qualified vendor build or `hw_emu` smoke, FPGA synthesis, physical-board
measurement, GPU numerical result or performance measurement was produced by
this continuation. Resource monitoring is sampled, not a hard quota. Path and
identity checks do not provide an atomic filesystem snapshot; unsafe output
replacement can prevent a final checkpoint. The source guard does not compare
every blob or lock the checkout. Selected ELF checks do not establish complete
loadability, symbol ABI, dependency closure or actual loaded-map provenance.
Receipts and review text remain assertions requiring independent qualification.

P01-A01/A02 retain their existing acceptance. **P01-A03 and P01 remain blocked;
P02 remains not started.** Runner records retain `phase_complete=false` and
`acceptance=not_evaluated`. The next bounded action remains preparation and
independent review of one compatible vendor release/platform and matching
`hw_emu` artifacts, followed by the actual bounded smoke and review described
in the integration guide.
