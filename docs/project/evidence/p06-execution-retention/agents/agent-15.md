# Agent 15 — independent cancellation review

## Disposition and scope

**No F2/F3 finding in the assigned additive cancellation changes.** This is an
independent source-bound review, not maintainer approval or phase acceptance.
Base HEAD is `622662ad9cece6da4e3375be7e977dbe04cde862`; the tested working tree
includes predecessor fixes and concurrent disjoint operational work.

Read the project brief, AGENTS.md, agent-10 report, status/backlog/roadmap,
acceptance/review policies and `qualified_warm_automation_v1.md`. Reviewed the
three new imports, three `main()` decorators and the explicit run-source helper
entry, together with the new real-signal tests and unchanged signal/process
helpers. Removing only those additive imports/decorators/source entry reproduced
all three agent-10 predecessor SHA-256 values exactly. No production source,
test, acceptance state, resource constant, golden, proof or Git object was
changed by this reviewer. No new test file was necessary.

## Findings and reasoning

- `terminate_as_interrupt()` is a reusable context-manager decorator. Entry
  rejects non-main threads before installing a handler or entering `main()`.
  Its `finally` restores the precise enclosing SIGTERM handler. SIGINT is not
  changed by this outer scope.
- All three operational `main()` calls now translate SIGTERM into the existing
  `KeyboardInterrupt` failure paths while running between child monitors.
  `baseline_process.run_bounded()` retains its own SIGINT/SIGTERM monitoring and
  cleanup, then restores the enclosing cancellation handler. Neither helper
  implementation changed.
- Existing real-signal tests observe readiness, wait for a completed child to
  be reaped before the between-stage signal, check the retained running receipt,
  and subsequently require a finished failure with no later native stage.
  The live-child case verifies actual child reaping and monitor interruption.
  Hosted packaging/encryption remain fixtures, so they prove reached control
  flow only.
- Source closure is complete for the reviewed local imports. AST traversal of
  explicit local imports found 78 modules from acquisition, 84 from run and 87
  from hosted, with zero missing entries in the corresponding retained closure.
  Acquisition imports are included in the run/hosted operational envelopes;
  standalone `acquire()` does not gain a separate snapshot mechanism. The helper
  itself imports only stdlib `contextlib`, `signal` and `threading`.
- Actual `selected_sources()` reads retained inventories of **106 files /
  2,769,944 bytes** for run and **113 files / 2,930,781 bytes** for hosted,
  including the unchanged 730-byte `ci/project/xrt_signals.py`. Both remain
  within the existing 256-file, 4-MiB/file and 32-MiB total bounds. Hosted obtains
  the helper through `runner.SOURCE_FILES`; existing copy verification binds its
  bytes along with the other selected files.
- The additions change cancellation handling and operational source retention
  only. They introduce no native admission, hard resource reservation,
  descendant-containment guarantee, hard-kill recovery or acceptance claim.

## Actual validation

Prepared CPython 3.12.14; source-root working directory;
`PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`,
`PYTHONPATH=ci/project`.

```sh
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v \
  test_p06_operational_cancellation test_xrt_cancellation test_baseline_process
```

**30 tests passed, zero skips, 7.488 s, exit 0.** Full output is in
`notes/agent-15-focused.log`. `git diff --check` passed for the three reviewed
production files.

A separate Python-stdin reviewer harness reused the operational fixtures in
fresh subprocesses and installed a custom enclosing SIGTERM handler before
calling the real `main()` paths. The parent waited for the fixture readiness
barrier, sent a real SIGTERM, required normal probe-process exit and checked
that the recorded inert child PID had disappeared from `/proc`:

| Scenario | Additional observed lifecycle |
| --- | --- |
| Acquisition between children | Custom handler restored; self-SIGTERM after `main()` reaches it exactly once |
| Run after preparation | Same custom-handler restoration and delivery |
| Hosted after recipient probe | Same restoration; existing fixture closeout reached |
| Acquisition with live bounded child | Extra enclosing `terminate_as_interrupt()` restored and responds to real self-SIGTERM; leaving it restores the custom handler |

All **4 external-SIGTERM probes passed**. Each retained a finished failure with
`native_execution="not_run"`, restored the enclosing handler after the nested
monitor, and left SIGINT unchanged. The custom handler received no signal during
the cancelled operational call; it received the explicit signal sent after
return. The same harness called each actual `main(["--help"])` twice and checked
restoration after `SystemExit(0)` (**6 passes**). It called each `main()` from a
worker thread with an observed parser and confirmed the documented `ValueError`
before parser entry (**3 passes**). Output: `notes/agent-15-enclosing-signals.log`.

Static closure counts, the exact helper inventory row, current source hashes and
predecessor reconstruction are retained in `notes/agent-15-source-audit.json`.

## Reviewed identities

All source paths below are under `ci/project/`; final rehash matched the initial
review snapshot.

| File | SHA-256 |
| --- | --- |
| `p06_qualified_warm_inputs.py` | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `p06_qualified_warm_run.py` | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `p06_qualified_warm_hosted.py` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `xrt_signals.py` | `a9531608094a233e5336a35e9fa7ebd028aaa3fc6dd7d3ed0f6f4d3f83a94fb8` |
| `baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `test_p06_operational_cancellation.py` | `9e04008693a5410a1ede7e6d88ccb86800ed7514a56852fdfffa2fb90877fc6b` |
| `test_xrt_cancellation.py` | `66aae27da0a4edaaecf47def347cd8ba38d77146812302f995f2a4cec119325b` |
| `test_baseline_process.py` | `f9a9b2a62d0dbdfb7408bc868214ad943a56f614dd0139c56b97a3026d871762` |

Evidence SHA-256:

- `agent-15-focused.log`: `14f82fc5b5faeea143ba4898d6b0f95f6ec4e0f35b4886f4f1a6101645c82469`.
- `agent-15-enclosing-signals.log`: `ff88c4ff7cd6577cc66b78fede657e54a932dbf0be277ae13ad41a293f5968a1`.
- `agent-15-source-audit.json`: `9b175852f1f71225f9cb89f15277d8f379ac76048e922ec0076e3a10b515df87`.

## Limits and next action

These are focused host-only development checks. No fresh qualified native run,
network acquisition, age encryption, provider upload, strict governance or
performance evaluation ran. The AST check covers explicit local imports, not a
complete operating-system or arbitrary dynamic-loading closure. Signals before
the installed CLI scope or before receipt creation, SIGKILL, provider loss,
repeated interruption and finalization I/O failure can still prevent retention.
Undecorated programmatic `acquire()`/`execute()` calls retain their prior signal
behavior. No stronger graceful-closeout promise is justified. P06-A02/A03 and
vendor XRT remain open/blocked at their existing scope.

Root should consolidate this review with agent 10's change record, preserve
these exact identities, and perform the final-source strict run and publication
checks. No additional production fix is requested by this review.
