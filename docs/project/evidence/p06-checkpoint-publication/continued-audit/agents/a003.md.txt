# A003: P06 orchestration failure audit

## Scope and conclusion

Audited source: `858090410a992756808256ace90d36b9b3b88dd3` (`master` at the start of this audit). Read `AGENTS.md`, current status/backlog, roadmap/acceptance material, and the qualified-warm runner, acquisition, hosted closeout, and dependency checkpoint callers. Repository worktree was clean before and after the reproduction. No repository files were edited, full governance was not run, and no native work or downloads were executed.

**Confirmed user-impacting defect:** one caught checkpoint interruption can leave the exclusive temporary receipt behind, prevent the caller's separate final failure receipt, and block both packaging and encrypted retention after completed work. This is the existing limitation explicitly documented in current status/backlog, now reproduced at the orchestration and hosted-observation boundaries. It is the strongest bounded next implementation; this audit does not claim another independent defect.

## Root cause and call chain

`ci/project/p02_matrix.py:92-100` creates `<receipt>.tmp` with `xb`, writes/flushes/fsyncs it, then replaces the committed receipt. It has no exceptional cleanup. A catchable write, flush, fsync, close, or prepublication replacement failure can leave that filename present. The next write attempts the same exclusive create and raises `FileExistsError`.

The qualified-warm wrapper catches the original failure and builds the proper terminal failure state, but cannot publish it:

- `p06_qualified_warm_run.py:382-383` delegates every checkpoint to this helper.
- `:463-470` correctly records nonstart for an interrupted launch-intent checkpoint.
- `:478-481` observes a finished child's report and log before its post-child checkpoint.
- `:509-510` records the interruption as a sticky failure.
- `:562-564` separately prepares and saves the final `state=finished` receipt. This final call instead encounters the abandoned temporary filename.

The same shared writer is used by acquisition (`p06_qualified_warm_inputs.py:255-256,343-349`), dependency preparation (`p06_dependency_local_prepare.py:255-259`), dependency build (`p06_dependency_build.py:233-234`), and managed/native execution (`p06_managed_preflight_execute.py:312-318`). A single helper repair therefore addresses the shared cause without adding command retries or changing native measurement code.

Hosted correctly refuses to infer completion from an uncommitted temporary receipt. `p06_qualified_warm_hosted.py:449-481` requires the authoritative acquisition/wrapper receipt to be `finished` and its command inventories to establish stopped writers. A missing or old `running` receipt returns false. At `:659` and `:676`, that observation blocks packaging and encryption. The original work remains local, but its ordinary hosted retention path is unavailable and the native disposition remains unknown.

## Reproduction and actual observations

Saved reproducible script:

`/tmp/ai-gpu-2bfab0261c05/a003-orchestration-repro.py`

Saved original stdout:

`/tmp/ai-gpu-2bfab0261c05/a003-orchestration-repro.jsonl`

Command, from the repository root:

```sh
python3 -B /tmp/ai-gpu-2bfab0261c05/a003-orchestration-repro.py
```

The script runs the production `runner.execute` through its existing `QualifiedWarmRunTests` synthetic child fixture. It does not launch the GPU or any real child stage. The fixture uses tiny inert originals, copied source files, and synthetic complete reports. It supplies a complete empty dependency command inventory so the successful reference also passes the production hosted writer observation. A one-shot `KeyboardInterrupt` from `os.fsync` occurs after the selected temporary checkpoint has been written and flushed. All later fsync calls are allowed to succeed. Thus the final failure is caused by the abandoned exclusive filename, not by persistent storage failure.

| Injected checkpoint | Synthetic children completed | Committed receipt | Remaining temporary receipt | Hosted writers finished |
| --- | --- | --- | --- | --- |
| None, reference | preparation, dependency-build, qualified-warm | `finished`, native `run` | None | `true` |
| 1, first receipt | None | Absent | Present, native `not_run` | `false` |
| 3, first launch intent | None | `running`, native `not_run`, no stages | Present | `false` |
| 10, post-native child | All three | `running`, native `unknown` | Present, native `run` | `false` |

All three injected cases raised `FileExistsError` from the subsequent final save. In the post-native case, the child `qualified-warm/report.json` was `finished`; the wrapper had already observed native `run` into its in-memory report and temporary checkpoint, yet the authoritative wrapper remained `running/unknown`. Production `hosted.observed_native_execution` returned `unknown`. The reference returned `run` and passed `writers_finished`, isolating the poisoned checkpoint as the cause.

This demonstrates lost durable closeout and blocked retention, not false success or a demonstrated process leak. The fixture is source-scoped failure-path evidence only; it does not qualify native execution, performance, or the changed revision.

## Safe bounded repair contract

Repair the shared checkpoint writer's cleanup, preserving its caller-visible failure semantics:

1. Keep exclusive temporary creation. An already-existing temporary entry remains a collision and must never be truncated, adopted, or deleted.
2. Capture ownership from the descriptor actually created by this invocation. Keep the containing directory identity pinned or checked so parent-directory replacement cannot redirect cleanup.
3. On an exception after owned temporary creation, close each owned handle once and remove only the temporary directory entry whose non-following identity still matches the created file. An absent entry is already cleaned; a symlink or different inode is a foreign replacement and must be preserved.
4. Preserve the prior committed receipt on all failures before publication. Never remove or rewrite the committed destination during cleanup.
5. Re-raise the original failure. Cleanup must not convert the interrupted invocation to success or replace the causative error with a cleanup failure.
6. Do not retry the interrupted write or any child/native work. The existing caller catches the error, records the failed/blocked outcome, and performs its already-defined separate final failure save. With the owned temporary removed, that final save can succeed.

The concrete before/after acceptance is the saved reproduction: first-checkpoint and prelaunch failures should produce a finished blocked receipt; the post-child interruption should produce a finished failure receipt retaining the observed native `run` disposition and original child data, without another child invocation. The stale temporary must be gone, while pre-existing collisions and unrelated replacements remain intact. Published success must not be claimed following any interrupted invocation.

A final write can itself fail, repeated interruptions can prevent cleanup, and uncatchable kills remain outside this bounded repair. Removing the owned abandoned temporary does not promise power-loss durability, resume support, native qualification, or permission to weaken the hosted writer gate. Frozen measurement sources, the 24-process/792-launch/25,344-word population, proofs, goldens, dependency descriptors, and resource/performance thresholds remain unchanged.
