# Wave 10 independent replay-guard fixture review

## Disposition

**The exact two-file repair is suitable for publication as a test-only checkpoint and for a clean hosted retry. F2-01 and F2-02 are resolved. No open F1/F2/F3 finding remains in this bounded delta.** This is independent R3 review advice, not maintainer approval, a waiver or full release approval.

The original hosted run **45034575638 / job 137245340992 remains failed**: **3,312 tests, two failures, zero errors, 1,811.712 seconds**. I independently checked its tracebacks and unchanged original log, SHA-256 `1d093819f62493536a2444b6efec31a75e522e7e3a3cfc197a0a101c833160a8`. A clean hosted result on the repair is still required. It was not run or verified by this reviewer.

Reviewer: `/root/w10_replay_guard_review`, **agent 60 of 60**, wave 10. Author: agent 59. I reviewed `AGENTS.md`, the review/acceptance/bug-fix policies, relevant project state, the frozen integrated review, and every changed hunk. No repository file was edited by this reviewer. I performed no commit, push, native build or native execution.

## Exact reviewed identity

Base: `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`. Its tree is `061ecbddc9b321edbd70c054c8efce4d188de04f`. During closeout root prepared local checkpoint **`142b2d6aaea2fa4226118b857514113032d2e26c`**. I independently verified that its parent is the base and its complete commit delta contains exactly these two reviewed files. Remote publication remains root-owned and was not verified here.

| File | Final bytes | Final SHA-256 |
|---|---:|---|
| `ci/project/test_p06_counter_diagnostics_replay.py` | 51,962 | `c8d213737b6332a5e6c924114b3e403a2ddcea3e0a2eac2f1fd431a5f4842430` |
| `ci/project/test_p06_counter_public_replay.py` | 42,713 | `241299ec7abfbbafe857c9d23ea10a0350b2606b10af4d942912780068d01a5d` |

The complete patch is **20,470 bytes**, SHA-256 **`31b2f389479187f15fd1c4698100220d619eb653affb8fe2de608aedf5179585`**. It matches the committed base-to-checkpoint diff and `w10-replay-guard-fix-exec-identity.patch`. Source hashes were checked before/after independent execution and at closeout. The two-file whitespace check passes.

All tracked implementation/workflow changes under `ci/project`, `sim`, `hw`, `sw` and `.github` are restricted to these tests. Concurrent documentation/evidence work is outside this exact-delta publication review.

## F2-01 — producer/current-root collocation

**Resolved; high confidence; observed failure, independent reproduction, static proof and executed regression.**

The original test guards denied every pathname beneath archived producer roots. On GitHub the current reader checkout and archived producer source root coincide, so required resolution of current `baseline_inventory.py` was falsely rejected. I reproduced both immutable original failures by appending only current `ROOT` to the denied roots in memory: **two expected failures in 0.865 seconds**, zero errors or skips. Both named the current trusted helper. Original archive-derived inputs and the genuine replayer remained intact.

The final tests independently enumerate **25 checked-reader source files**, **28 public-reader source files**, and the exact pinned archive parser. No trusted path is derived from an archive, the production reader's returned inventory or a subtree exemption. Only exact current helper filenames receive permission. Ordinary producer source, sibling names, metadata, direct ancestor operations and recorded tool/dependency identities remain denied. Explicit checked/public tests add current `ROOT` to the denied roots on every host.

The allowance is read-only: modes `r`, `rb`, `rt`; `os.open` rejects write access, creation, truncation and append flags. Only `os.lstat` of an exact helper's ancestors is allowed during that helper's real `Path.resolve` call. `try/finally` removes the scope; a nested call uses only its top active scope. Independent probes verified inner-exception restoration, outer-exception cleanup and direct ancestor denial after exit. Earlier additional probes rejected **288 combinations** of producer/non-helper/prefix/metadata paths, strings, bytes, `PathLike` representations and read/resolve/probe operations. This path-guard implementation is unchanged in the final candidate; the final focused execution reruns the required collision/sibling/scope/read-only checks.

Real archive reads and source-stability checks remain active. Existing extraction, subprocess and native-validation prohibitions remain in place. Both original guard-test names remain, and no skip or expected-failure was added.

## F2-02 — filename-only executable identity

**Resolved; high confidence; complete-fixture bypass and subsequent pre-dispatch rejection demonstrated.**

The first candidate's execution callbacks accepted a code object solely because `co_filename` named the pinned parser. At root's request I compiled the exact pinned parser body plus an extra harmless marker statement under that same filename and substituted it through `SourceFileLoader.get_code`. **Both complete collocated replay fixtures passed and the extra marker executed**, while on-disk parser bytes stayed unchanged. This demonstrated a test-witness gap. It did not establish retained-code execution by the unchanged production implementation. Approval was withheld, and the author independently reproduced the gap before repair.

The final shared `ArchiveReaderExecGuard` verifies an independently specified literal parser digest, compiles those exact current bytes with `flags=0`, `dont_inherit=True` and `optimize=sys.flags.optimize`, and requires exact `CodeType` and compiled identity before recording execution or dispatching to real `exec`. Code equality is supplemented by `co_filename`, `co_stacksize` and `co_qualname`, recursively on nested code objects. Independent field experiments confirmed that ordinary code equality omits those fields.

Final independent controls reject **11 variants**: altered executable bodies at the same filename, all three omitted fields at both top and nested levels, strings, bytes and a non-code object with custom equality. Invalid inputs reach neither execution nor custom equality. Exact valid code passes a controlled dispatch check, while successful genuine replay executes the actual pinned parser once.

Both complete previous forged-loader exploits now fail at the specific compiled-identity assertion **before any underlying exec dispatch or marker effect**. Each replay test class also contains this complete regression, including unchanged parser-byte verification. A later incidental replay error cannot satisfy it. The earlier 87-test pass, bypass reproduction and subsequent repair evidence all remain retained.

## Execution evidence

| Evidence | Exact result |
|---|---|
| Immutable original root-collision controls, reviewer | 2 expected failures / 0 errors / 0 skips; 0.865 s |
| Final new/changed-method scope, reviewer | **8 passed / 670 subtests**, 0 failures/errors/skips; **4.956 s** |
| Final code-identity and genuine-original probes, reviewer | **3 methods / 15 subtests passed**, 0 failures/errors/skips; **4.437 s** |
| Complete affected modules, author; terminal log independently verified | **89 passed**, 0 failures/errors/skips; **139.141 s** |
| AST inventory | **83 → 89 methods**; six additions, zero removals |
| Two-file diff check | Passed |

The complete-module command was:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B -m unittest -v \
  test_p06_counter_diagnostics_replay test_p06_counter_public_replay
```

Execution used actual **CPython 3.12.14**, from the source root. I did not duplicate the author's full two-module run or run full project discovery. Exact selected method names, results and integrity maps are in the companion log/JSON.

### Latest original replay under the final guards

I replayed byte-identical temporary copies of original `run-45034575685-attempt1.zip`, SHA-256 **`6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb`**, and the selected external manifest, SHA-256 **`bd81faa7590e053685dfa78d8baa41478969c3b4ec750646cddb5796b949ba0c`**. No archive member was extracted. The final path and compiled-execution guards were active with forced current-root collocation, plus process/extraction/write prohibitions.

| Route | Sources | Commands | Cells | Current files actually opened | Source snapshots |
|---|---:|---:|---:|---:|---|
| Checked original inventory | 270 | 17 | 7 | 26 including parser | Checked closure: 3, identical |
| Public external manifest | 683 | 14 | 6 | 29 including parser | Checked closure: 4; public closure: 2; each stable |

Both passed genuine retained-data consistency checking. Actual opens of the selected ZIP and public manifest were observed. Every current reader source was read at least three times for checked replay and twice for public replay. Only the exact current compiled parser executed, once per route. Observed opens were limited to current helpers, selected inputs and the manifest's exact descriptor-traversal ancestors. Observation wrappers preserved only OS capabilities already supported by the functions they forwarded; actual manifest opens retained `O_NOFOLLOW` and read-only flags.

Independent negative controls also changed the final observed current-source snapshot and verified that the real checked/public replay rejected the mismatch. Original input and protected source bytes remained unchanged. All qualification, warm and acceptance flags remained false; `native_execution` remained `not_run`.

## Integrity and honest failure accounting

All **29 production reader/helper/parser files** match immutable base bytes. All **four original ZIPs**, the successful-public intake receipt and selected external manifest retain their original hashes. The failed public original remains unchanged and its rejection tests remain active. Production reader/helper/security logic, workflows, configuration, contracts and golden data were not changed by this fixture repair.

The review log preserves my unsuccessful initial extra instrumentation runs. One expected two checked snapshots where production takes three; another replaced OS function identities without preserving their pre-existing capability-set membership; a later observation retained a diagnostic list by reference while the public reader extended it. These caused the recorded initial two failures/one error and one subsequent observation failure. Corrections changed only reviewer instrumentation, never production or test source. Final exact-hash focused and identity/replay executions have zero failures/errors/skips.

The local checkpoint appeared during report formatting. Closeout therefore compared the complete committed delta against the immutable base, rather than requiring a still-dirty working-tree diff. It independently matches the previously reviewed patch and source hashes. This is local identity verification, not a remote publication claim.

## Remaining obligation and limits

Root may publish the exact reviewed test checkpoint and trigger a clean hosted governance retry. Its terminal receipt must be reviewed before claiming the full gate passed; the original failed run retains its failed disposition. This review supplies independent advice and does not invent a maintainer decision or supersede the separately owned documentation/native audits.

No new native run, source-to-binary authentication, complete dependency authentication, RTL/vendor/physical result, full warm experiment, qualification or acceptance is established. Qualification, readiness, warm execution, full-warm coverage and all acceptance flags remain **false**. Existing P06/P06-T01 and acceptance obligations remain unchanged.

## Artifacts

- `w10-replay-guard-review.json`: exact final identities, both resolved findings, execution records, historical harness failures and integrity maps.
- `w10-replay-guard-review.log`: original failure reproduction, executable-witness bypass, independent final passes and closeout.
- `w10-replay-guard-fix-exec-identity.md` / `.patch`: final author addendum and complete two-file patch.
- `w10-replay-guard-fix.md` / `.patch`: preserved earlier candidate, superseded for publication by the executable-identity repair.
- `w10-integrated-code-review.md` / `.json`: frozen integrated base review, whose F2-01 is closed by this independent exact-delta review.
