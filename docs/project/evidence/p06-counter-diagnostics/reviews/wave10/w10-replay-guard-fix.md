# Wave 10 replay-guard fixture repair — agent 59 of 60

## Disposition

The two hosted failures are reproduced and repaired in test fixtures only. The final frozen two-file candidate passes **87 tests in 114.517 seconds**, with zero failures, errors or skips. A separately recorded final focused execution passes **6 methods in 4.287 seconds** and observes all **350 intended negative subtests**. No production reader, helper, workflow, source manifest, original ZIP, index or receipt was edited by this repair. Root retains commit/push ownership; agent 60 is independently reviewing and testing this exact delta. A clean hosted retry remains outstanding; the prior failed hosted receipt remains a failure.

Base revision: `4268d2d5d811063bb886cde7bd0e27e61a79c9b4`. Actual interpreter: `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3`, CPython **3.12.14**, Linux. Commands ran from `/workspace/scratch/98908dfa3444/AI-GPU`. No full local unittest discovery, GPU build or native execution was performed.

## Root cause and trust distinction

Hosted Project Governance run `45034575638`, job `137245340992`, completed 3,312 tests in 1,811.712 seconds with exactly two failures and zero errors. Both path guards rejected the current `ci/project/baseline_inventory.py` while the real `_reader_sources()` performed `Path(module.__file__).resolve()`. The current hosted checkout and the archived producer checkout share `/home/runner/work/AI-GPU/AI-GPU`. The guards treated every pathname under the recorded producer root as forbidden, including the explicitly trusted current reader closure. Local scratch paths did not previously overlap, hiding the fixture error.

The archive is untrusted retained data. The current reader closure is caller-selected trusted code whose exact files are hashed before/after real replay. Its files remain trusted when their current pathname happens to equal a recorded old producer pathname. The fixture now independently enumerates 25 checked-reader source paths and 28 public-reader source paths, plus the separately pinned archive-reader source. It does not derive permission from archive contents, production `_reader_sources()` output, a checkout-prefix exemption or a success mock.

Only these exact current helper filenames receive read/probe/resolve permission. `open` permits `r`, `rb` and `rt`; `os.open` rejects write access, creation, truncation and append flags, including combinations with `O_RDONLY`. Real file reads, real resolution, original source-byte checks, the archive-reader digest pin and before/after reader stability checks still execute. Each guarded successful replay must report the exact independent source-name inventory and actually open every expected helper. The public guard retains its import-location restriction and additionally restricts `exec` to the current pinned archive parser.

Python 3.12 `Path.resolve()` performs `os.lstat()` on path ancestors. An exact approved helper resolution therefore permits `os.lstat()` of its exact ancestors only while that real resolution call is active. `finally` removes the scope on success or failure. Direct ancestor probes outside this scope, ancestor reads inside it and sibling operations inside it remain forbidden. No directory or subtree gets general permission.

## Failure reproduction before editing

Both original modules were loaded from their unchanged files into isolated in-memory test-module namespaces. The only in-memory edit appended the current checkout root to each existing guard's denied roots:

```python
# Checked fixture, original line plus the synthetic collision:
roots = tuple(Path(value) for value in report["paths"].values()) + (ROOT,)
# Public fixture, original line plus the synthetic collision:
roots = tuple(PurePosixPath(value) for value in report["paths"].values()) + (PurePosixPath(ROOT),)
```

The actual successful retained original, mutation helpers, source hashing, pure replayer, import and execution guards remained genuine. Running the two original named guard methods produced **2 expected failures in 0.982 seconds**, zero errors and zero skips. Both failures named the current local `/workspace/scratch/98908dfa3444/AI-GPU/ci/project/baseline_inventory.py`, proving that reproduction does not depend on a real GitHub runner pathname. The full tracebacks and pre-edit hashes are retained in `w10-replay-guard-fix.log`.

The committed regression uses the same stronger union of recorded roots and current `ROOT`; it does not rewrite any archived report, identity, source manifest or original artifact to manufacture a pass.

## Final regression coverage

All prior method names remain, and four methods were added:

- `ci/project/test_p06_counter_diagnostics_replay.py:CounterDiagnosticsReplayTests.test_replay_allows_only_current_helpers_when_producer_root_is_current_checkout`
- `ci/project/test_p06_counter_diagnostics_replay.py:ProducerPathGuardTests.test_active_helper_resolution_rejects_sibling_access_and_ancestor_reads`
- `ci/project/test_p06_counter_diagnostics_replay.py:ProducerPathGuardTests.test_current_helper_allowance_rejects_write_capable_opens`
- `ci/project/test_p06_counter_public_replay.py:OriginalPublicReplayTests.test_replay_allows_only_current_helpers_when_producer_root_is_current_checkout`

The original checked/public guard methods still execute successful original-derived packets containing deliberately failing retained producer source. Retained source remains inert. The full modules also replay the genuine unchanged original ZIPs and reject the retained failed public original. Extraction, subprocess/native validation and retained-code execution prohibitions remain active; the public path guard now covers the checked guard's full read/resolve/probe surface.

The final focused run observed these exact negative subtest counts:

| Method | Passing negative subtests |
|---|---:|
| `test_p06_counter_diagnostics_replay.CounterDiagnosticsReplayTests.test_replay_allows_only_current_helpers_when_producer_root_is_current_checkout` | 160 |
| `test_p06_counter_diagnostics_replay.ProducerPathGuardTests.test_active_helper_resolution_rejects_sibling_access_and_ancestor_reads` | 6 |
| `test_p06_counter_diagnostics_replay.ProducerPathGuardTests.test_current_helper_allowance_rejects_write_capable_opens` | 24 |
| `test_p06_counter_public_replay.OriginalPublicReplayTests.test_replay_allows_only_current_helpers_when_producer_root_is_current_checkout` | 160 |

Each collocation replay crosses eight denied paths with twenty access operations. The paths are the checkout root, its `ci` and `ci/project` directories, actual non-helper `sim/simx/core.cpp`, actual non-helper `ci/project/p06_counter_public_execute.py`, a sibling of `baseline_inventory.py`, a sibling of the pinned archive parser and a recorded producer/tool identity. The operations are `builtins.open`, `io.open`, `os.open`, `os.stat`, `os.lstat`, `os.readlink`, `os.listdir`, `os.scandir`, `os.access`, `Path.open`, `Path.resolve`, `Path.stat`, `Path.lstat`, `Path.exists`, `Path.is_file`, `Path.is_dir`, `Path.glob`, `Path.rglob`, `Path.read_bytes` and `Path.read_text`. All 320 calls must raise the fixture's producer-path assertion before the underlying access succeeds.

The six active-resolution negatives inject sibling `Path.read_bytes`, sibling `Path.resolve`, sibling `os.stat`, sibling `os.lstat`, ancestor `os.listdir` and ancestor `Path.open` during the real approved helper's ancestor `lstat`. They also assert resolution-scope cleanup after rejection.

The 24 write-open negatives cover modes `w`, `wb`, `a`, `r+` and `x` for builtins/io/Path, keyword `mode=w`, `O_WRONLY`, `O_RDWR`, `O_RDONLY|O_CREAT`, `O_RDONLY|O_TRUNC`, `O_RDONLY|O_APPEND` and keyword flags. Their underlying opens are intercepted and asserted uncalled, so a guard regression cannot overwrite real trusted sources. Successful replay is never mocked. The log records every observed successful negative subtest with its actual parameters.

## Execution record

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B -m unittest -v \
  test_p06_counter_diagnostics_replay test_p06_counter_public_replay
```

| Execution | Result |
|---|---|
| Original two guards with only synthetic root collision | 2 expected failures / 0 errors / 0 skips; 0.982 s |
| Initial candidate focused guards and active-resolution checks | 5 passed; 4.175 s |
| Initial candidate complete modules, before explicit read-only-open tightening | 86 passed; 115.620 s |
| Final frozen candidate complete affected modules | **87 passed** / 0 failures / 0 errors / 0 skips; **114.517 s** |
| Final frozen candidate focused original guards, collocation replays and scope/open negatives | **6 passed**, observed subtests **160 + 160 + 6 + 24**; **4.287 s** |
| Final two-file `git diff --check` | Passed |

The final focused run selected both `ProducerPathGuardTests` methods, both original guard methods and both added collocation methods. It used `unittest.TextTestResult.addSubTest` only to record passing parameter sets; all test and replay behavior remained real. Exact names and all 350 parameter sets are in the log.

## File identities and preserved evidence

| Changed test file | Before SHA-256 | Final SHA-256 |
|---|---|---|
| `ci/project/test_p06_counter_diagnostics_replay.py` | `f954840178f739f21ef7f352985e9bbd3f6080d762bdf6fba72bd7665ac1956a` | `e5ac78f0662d8d32c93b3d518a934b7dd57c6d04af81fe1264fae8f3a8754874` |
| `ci/project/test_p06_counter_public_replay.py` | `6d9c4c541a0e68acd021a3d2bf3ffb989ed4300b8339314e80551947498df6e0` | `f1c5f13b34794f3cb53c96fce68236445591ac6446436ecbed27d3566be776ec` |

All **29 production reader/closure files** and the successful-public intake receipt match their pre-edit hashes. The production source-inventory validator is included in that unchanged closure. All four original archives are also unchanged:

| Original archive | SHA-256 before and after |
|---|---|
| `run-45026112992-attempt1.zip` | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` |
| `run-45029135146-attempt1.zip` | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` |
| `run-45031746149-attempt1.zip` | `05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276` |
| `run-45034575685-attempt1.zip` | `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb` |

The complete before/after map is in the log. The two-file patch is `w10-replay-guard-fix.patch`, SHA-256 `4aec1eb3041e04805260973849c9e287252c26546ebe1398a2ac9c0d57523a76`. This repair requires no production-code change. Qualification, warm readiness/execution, phase/performance acceptance and acceptance claims remain false; replay remains retained-data consistency checking with `native_execution=not_run`.
