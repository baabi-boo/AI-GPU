# Agent 042 — independent launcher SIGTERM regressions

## Owned change

Added only `ci/project/test_p05_launcher_signals.py`: eight host-only methods. No native libraries, GPU work, downloads, full suite, contract edits, commits or pushes were performed. A041 owns the production implementation and existing launcher-test adaptations.

The real-process probes invoke actual `launch.main` with only bundle verification replaced by an environment-copy stub. They use ordinary isolated Python child scripts and PID-directed SIGTERM, never a signal to a process group. Child readiness and continuation use pipe events; no timing sleeps select the race window. A retained pidfd identifies the exact owned probe for failure cleanup. Child alarms bound malfunctioning fixtures, and stream/descriptors close in `finally` blocks.

## Coverage

1. Real PID-directed SIGTERM reaches the direct child; the launcher returns normalized status 143 only after reaping it. No post-return child event is emitted, and the prior SIGTERM disposition is restored.
2. A real child that handles SIGTERM remains owned while waiting for explicit input. The launcher stays alive until that child actually exits with status 21; no premature success, timeout or escalation is inferred.
3. The installed signal callback is invoked synchronously inside the Popen factory before its process result is assigned. No Popen operation occurs in the callback; forwarding happens only after ownership publication. This is a deterministic injected startup-window test, not a real-signal scheduling claim.
4. A real ordinary child exit preserves status 37 and restores the caller's prior custom handler.
5. A process-creation exception is preserved and the prior handler restored.
6. A one-shot wait exception on a real child triggers kill/reap, preserves the exact first exception object, and restores the prior handler.
7. A pending callback after a real child's status has already been collected preserves that status (17), without attempting to signal an unrelated process.
8. A worker-thread caller fails before spawning or changing signal disposition, as required by the implementation's explicit main-thread boundary.

## Current result and source identity

Retained invocation: `/tmp/ai-gpu-2bfab0261c05/a042-current-runner.py`.
Raw log: `/tmp/ai-gpu-2bfab0261c05/a042-current.log`.
Structured result: `/tmp/ai-gpu-2bfab0261c05/a042-current.json`.

One final selection passed **8/8 methods in 0.394 seconds**, with zero failures, errors or skips. Before/after source hashes matched. Observed cwd, environment, open-fd inventory, thread inventory and all queryable signal dispositions were unchanged. Recorded HEAD was `a693d6f8828e4e10b5374db7fef8c727aa69d34e`; production and test modifications were uncommitted.

- `python/vortex_ai/launch.py`: SHA-256 `01bdadc8469b50fc2b6e511684d37f1bc92d2f4030d3a0900481b8fb5173a128`.
- `ci/project/test_p05_launcher_signals.py`: SHA-256 `21583916f92b8bc6d44a5f7743052dd8222216979d3922f62dcf545ef03f1eed`.

## Explicit old-revision negative control

The old launcher was extracted with `git show 858090410a992756808256ace90d36b9b3b88dd3:python/vortex_ai/launch.py` to a separate scratch file. No checkout files were overwritten. The same actual-main probe used that old launcher with the current inert package import support and the same verification-only stub.

The parent exited **-15**, after which the controller supplied a previously unavailable input. Its still-running child then emitted `continued` with `finish-after-parent-exit` and exited 21. The exact regression test also failed once against that old launcher, with zero test errors. A dedicated isolated Linux subreaper retained and reaped the intentionally orphaned negative-control child. No children, fd changes or signal-disposition changes remained after the control.

Retained files: `a042-negative-runner.py`, `a042-baseline-launch.py`, `a042-baseline.log`, and `a042-baseline.json` under `/tmp/ai-gpu-2bfab0261c05/`. The JSON binds the exact baseline launcher and tested new-file SHA-256.

## Limits

These tests establish direct-child host-process ownership for the stated signal and failure cases. They do not establish cleanup after SIGKILL, arbitrary descendant/process-group cancellation, native teardown, native performance, general Python-thread compatibility, or full-revision qualification. The earlier individual development executions overlap this final eight-test result and must not be added to its count.
