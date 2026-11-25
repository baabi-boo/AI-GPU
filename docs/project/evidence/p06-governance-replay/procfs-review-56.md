# Same-context follow-up to assignment 56 — published process-state read race

## Independent diagnosis

**The retained failure is in the existing test's observation of an already terminating descendant, not in an observed timeout/kill failure.** The minimal justified correction is to accept `ProcessLookupError` alongside the existing `FileNotFoundError` only around the `/proc/<child>/stat` read. Preserve every timeout, signal, retained-output and readable-state assertion. No production timeout change, skip, retry, sleep or waiver is indicated by this failure.

This is an independent read-only diagnosis before root's correction. No production/test source was edited, and no test or reproduction was executed. No commit, push, new agent, network lookup or download occurred. Only this follow-up report was written. Numbered report 56 and the completed 60-assignment ledger were left unchanged. Root owns the correction and targeted execution; final review will follow those exact bytes/results.

## Exact published evidence and source identities

The checkout was clean at `00a6c275af918b51a36dbbdb454e9b480e25bb98`. Local provider observation `validation/published-ci-governance/observation-0059.json` records Project Governance run **45671761974**, attempt **1**, job **139408624408**, exact published head on `master`, with completed/failure status. This is supplied retained provider evidence, not a new provider query by this reviewer.

The saved job log reports `Ran 5406 tests in 3157.906s`, `FAILED (errors=1)`, `Strict governance FAILED`, and exit 1. The single error is `test_governance_env.GovernanceEnvironmentTests.test_command_timeout_kills_its_process_group_and_retains_output`. Its traceback is:

```text
ci/project/test_governance_env.py, line 488
    state = process_state.read_text().rsplit(")", 1)[1].split()[0]
/usr/lib/python3.12/pathlib.py, line 1030, in read_text
    return f.read()
ProcessLookupError: [Errno 3] No such process
```

The original remains a failed strict invocation. Diagnosing a test race cannot retroactively change that result or qualify the revision. Root reports original artifact **15054650929**, SHA-256 `050f3b408d0befc37a0a3cb3e722f45551c9a5365ab5dd72eac263a281c620fb`; this reviewer did not independently read or hash that archive.

| Input | Bytes | Independently computed SHA-256 |
| --- | ---: | --- |
| `ci/project/governance_env.py` | 17,256 | `af4538a894a96abaf4848b19126ba0b55f8b5d1c3404f7bda3c24f8ac3d9dbe1` |
| `ci/project/test_governance_env.py` | 28,401 | `710ca0f7a9d23728cb3f4689aa2432e4bb6909ee3d5e59addc612d6180261551` |
| `validation/published-ci-governance/job-139408624408.log` | 1,155,091 | `90512c2d1ec03eaee7631d9c9d1fd9345b427dbf00fe1a5f5c3c63788707a6ed` |

Both Python files are byte-identical across the current checkout, exact published revision, and base `f3123513bb5bc5fa1c409bf0e7366d2f47c2d85b`. The scoped `git diff` is empty; `git show` hashes independently agree. This was an unchanged test and unchanged producer. The newly implemented replay code is not on the recorded failing stack.

## Race and production behavior

`governance_env.command` launches the probe with `start_new_session=True`, captures its output, and calls `communicate(timeout=timeout)`. On timeout it sends `SIGKILL` to `os.killpg(process.pid, ...)`, drains/waits through `communicate()`, marks `timed_out`, records the signal return code and retained streams, and raises the required time-bound `ValueError`.

The test's probe starts a descendant without creating another session, prints its PID with flush, and sleeps. Before reaching the failing read, the test has already required:

1. The expected time-bound `ValueError from command`.
2. `result["timed_out"]` is true.
3. The supervised leader's return code is exactly `-signal.SIGKILL`.
4. Retained stdout contains an integer descendant PID.

The remaining observation accepts an absent proc path or a readable terminal state `Z`/`X`; it rejects a readable live state. The descendant can finish disappearing while that observation is in progress. The traceback is specifically at `f.read()`, after `Path.read_text` opened the path, so the error is a read-time “no such process” result rather than the currently handled path-lookup “not found” result. The interpretation that the task disappeared between successful open and data retrieval is strongly supported by those exact frames and error, but this audit did not instrument the kernel to observe the transition directly.

Both disappearance outcomes are consistent with the existing assertion that no live descendant remains. The current exception handler recognizes only one. No evidence here warrants changing `os.killpg`, signal handling, process-group scope, the production timeout, or command receipt semantics. A hypothetical different race at `os.killpg` would have a different stack and is outside this observed defect.

## Minimal proposed correction

Change only the existing exception tuple:

```diff
-        except FileNotFoundError:
+        except (FileNotFoundError, ProcessLookupError):
             pass
```

Leave the `else: self.assertIn(state, ("Z", "X"), "timed-out descendant remained alive")` branch and every preceding assertion unchanged. Catching generic `OSError`, returning success on malformed proc data, dropping the state assertion, skipping the method or increasing sleeps would erase useful failure discrimination and is unnecessary.

The module statically contains 27 existing test methods. This one-line proposal preserves every method ID and all existing assertions. It recognizes an additional terminal-observation error already demonstrated by the strict run; it does not permit a living process or waive a cleanup obligation.

## Meaningful narrow validation for root

The real existing process-group test must still execute after correction, with no mock of `command`, `os.killpg` or subprocess behavior. Its targeted command is:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -m unittest -v test_governance_env.GovernanceEnvironmentTests.test_command_timeout_kills_its_process_group_and_retains_output
```

For deterministic discrimination, exercise the existing method under a strictly targeted patch of only the final `/proc/<numeric child>/stat` read. Preserve the actual process launch/timeout/kill and preceding assertions. A controlled read-time `ProcessLookupError` should fail before correction and pass afterward. A path-absence `FileNotFoundError` and readable `Z`/`X` should retain acceptance; readable `R`/`S` must still fail. A different read error such as `PermissionError` or `OSError(EIO)` must still escape as failure. These cases can be temporary focused control invocations, not a new broad suite or duplicate runtime test population.

A local ordinary pass alone cannot deterministically prove this rare branch: the forced ESRCH control is the important before/after regression. Conversely, a mocked reader alone does not prove actual group cleanup, hence retaining the unmodified real-process method is essential. Review the one-line diff and exact final file hashes after root's execution. Then the changed published revision needs its own new complete strict canonical invocation and retained original. Do not reuse this failed run as a pass or claim 5,406 successes.

## Actual read-only commands and limits

- `git rev-parse HEAD` and `git status --short`: exact published HEAD, clean checkout.
- `git diff f3123513bb5bc5fa1c409bf0e7366d2f47c2d85b 00a6c275af918b51a36dbbdb454e9b480e25bb98 -- ci/project/governance_env.py ci/project/test_governance_env.py`: exit 0, no differences.
- `sed` and `rg` read the exact test, its fixture setup, producer command/timeout implementation and failure frames in the saved job log.
- `PYTHONDONTWRITEBYTECODE=1 python3 -` standard-library reads hashed both files and exact `git show` versions, the job log and unchanged prior report, parsed the existing test-method inventory with `ast`, and read the saved provider observation. No project module was imported.
- A local documentation inventory found no procfs kernel source; no external lookup or dependency acquisition followed. An initial `rg --files` named the not-yet-created follow-up directory and reported it absent; only the authorized directory/report was subsequently created.

Original numbered report 56 still hashes to `4f7f56b5df078dd335dc413f98fdf61df58fb06b5c3dbcd8b76825531c983bff`. The ledger was neither opened for modification nor rewritten. No targeted test result is claimed in this diagnosis. Final correction approval is pending the exact diff and meaningful control results described above.


## Final independent R3 correction review — closed at exact reviewed bytes

**Verdict: land the correction at the hashes below. No unresolved F0–F3 defect was found in this scoped correction or its deterministic validation controls.** This follow-up independently reviewed every changed hunk, the complete temporary control program, both result JSONs and both raw logs. It supplies the requested independent R3 review of the correction, not maintainer approval, a waiver or final strict-governance qualification.

The prior diagnosis's pending-correction disposition is superseded by this closure. The failed published run remains failed. The selected next published revision still requires a fresh complete strict CI invocation and source-bound original.

### Exact reviewed source and minimal-change proof

| File | Final reviewed SHA-256 |
| --- | --- |
| `ci/project/test_governance_env.py` | `e4a0e1a89a54af92af48393a7551122ce8ac827635964f6e76a443461e32ca89` |
| `ci/project/governance_env.py` — unchanged production | `af4538a894a96abaf4848b19126ba0b55f8b5d1c3404f7bda3c24f8ac3d9dbe1` |

HEAD remained `00a6c275af918b51a36dbbdb454e9b480e25bb98` during review. The correction was an uncommitted working-tree change, so the exact corrected file hash identifies the reviewed bytes. At the initial check, this was the only modified repository file.

The entire diff is the exception tuple adding `ProcessLookupError` plus one explanatory comment about removal between opening and reading the procfs record. Production is unchanged. An independent AST comparison preserves all **27 ordered test IDs**; after replacing only the new tuple with the previous `FileNotFoundError` node in memory, the complete old and new module ASTs are identical. This verifies that every original assertion, process setup, timeout, signal check, stdout PID conversion and `Z`/`X` state constraint remains unchanged. No skip, expected-failure annotation, retry, additional sleep or threshold change was introduced. `git diff --check` on both source files returned zero with no diagnostics.

### Controller and retained observations

`controls.py` invokes exactly the existing test method through ordinary `unittest.TestSuite`/`TextTestRunner`. Its actual-procfs case installs no patch. For the other cases, only `Path.read_text` for an absolute `/proc/<positive integer>/stat` path is intercepted; all other reads delegate to the real method. No mock replaces `environment.command`, `Popen`, `communicate`, `os.killpg` or the timeout assertions. Thus each case reaches the observation only after executing the real process-group timeout and its original preceding assertions.

The controller requires exactly one test execution, zero skips and the correct result category for each case. Injected cases require exactly one targeted proc read. It checks the ESRCH exception name before correction, PermissionError for the unrelated failure, and the original live-descendant assertion message for `S`. A zero exit of this controller means these discriminating expectations agree; it does not mean seven canonical tests all passed.

The reviewer independently parsed both JSONs and raw logs and matched all seven case names, expected/observed categories, one-test counts and zero-skip counts. Source hashes in the before record match the exact published file; hashes in the after record match the current correction. Both identify unchanged production.

| Final proc observation | Before correction | After correction | Interpretation |
| --- | --- | --- | --- |
| Actual procfs, no patch | Pass | Pass | Original real-process timeout check still executes successfully. |
| `FileNotFoundError` / ENOENT | Pass | Pass | Previously accepted disappearance remains accepted. |
| `ProcessLookupError` / ESRCH | Error | Pass | Deterministic reproduction of the diagnosed unhandled observation is corrected. |
| Readable `S` | Assertion failure | Assertion failure | A live-state observation still fails with the original message. |
| Readable `Z` | Pass | Pass | Existing terminal-state rule preserved. |
| Readable `X` | Pass | Pass | Existing terminal-state rule preserved. |
| `PermissionError` / EACCES | Error | Error | Unrelated read failure is not swallowed. |

The injected `S` case validates rejection of a live-state observation; it does not deliberately leave a real descendant alive. Likewise, injected ESRCH validates the exact exception path without reproducing kernel scheduling. The unpatched case supplies the separate actual process-group execution. These complementary scopes are appropriate and stated accurately.

### Exact control evidence

All paths in this table are under `validation/governance-proc-race/` and were independently hashed by this reviewer:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `controls.py` | 4,034 | `dfcb77442108a9c4a8fa419bacd733264380e70394bdbadad32654404ee745d8` |
| `before-controls.json` | 2,459 | `09ec4c31e366f73437db4c063f786b924ee6d7de528158b172c5cbd5b5649118` |
| `before-controls.log` | 4,758 | `b8c9a7baa70c0258e03fe0fc8ac74c1ebd2e2bf57a2f6a37b64c012b99898f8f` |
| `after-controls.json` | 2,457 | `fceb2d95d7194ef991184ef5b9373c28a394da4a74c3b8c3bc8b0b49dca55e5d` |
| `after-controls.log` | 3,843 | `d9db0a63909610204258846db34380f6855a1b3bd3dbf72790534f51ed843729` |

The controller accepts `--phase before` or `--phase after`; the corresponding retained records preserve both the original ESRCH error and the corrected outcome. Deliberate live-state and unrelated-error failures remain in the raw logs. These are root's executions inspected independently here, not newly rerun tests by this reviewer.

### Actual independent checks and final limits

The final review ran `git diff --` and `git diff --check --` on the exact test/producer files, `git status --short`, and a `PYTHONDONTWRITEBYTECODE=1 python3 -` standard-library audit. The audit used `git show` for the published original, AST comparison for the complete test module, SHA-256 for current source and five control files, and independent JSON/raw-log category reconciliation. All assertions and commands completed successfully. No project/test modules were imported and no test bodies were rerun.

A duplicate control run would resolve no remaining concrete risk after the exact source, preserved assertions and deterministic before/after discrimination matched. No extra test or production edit is requested. Only this follow-up report was appended. Numbered report56 remained SHA-256 `4f7f56b5df078dd335dc413f98fdf61df58fb06b5c3dbcd8b76825531c983bff`; the completed ledger was not modified.

The correction closes the diagnosed procfs observation race at the reviewed source hash. Retain the failed published original and its failed result, publish the reviewed correction with the failure follow-up, and require the next exact revision's complete zero-skip strict run. Nothing here supplies native, performance, hardware or phase acceptance.
