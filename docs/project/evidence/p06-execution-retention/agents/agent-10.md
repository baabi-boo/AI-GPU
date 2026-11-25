# Agent 10 — operational SIGTERM closeout

## Scope and finding

Read the project brief, AGENTS.md, canonical status/acceptance/roadmap/backlog context,
the automation contract, the prior acquisition finding, and operational signal
and writer handling. Base revision remains
`622662ad9cece6da4e3375be7e977dbe04cde862`; predecessor edits were present.

**F2, high confidence, reproduced runtime failure with static cause:** acquisition,
local supervision and hosted composition had no lifetime SIGTERM scope. Their
bounded child executor restored the enclosing default handler after each child.
An external SIGTERM in subsequent orchestration therefore terminated Python
directly, bypassing existing KeyboardInterrupt handling and failure finalization.

The regression runs each actual `main()` in a separate Python process. A real
bounded inert child completes and is reaped; an explicit readiness barrier then
stops the orchestrator at its completed-child receipt checkpoint (acquisition
and local supervisor), or before the next hosted capacity observation. The test
parent sends SIGTERM only after readiness and uses bounded startup/completion
timeouts. Before the fix all three processes exited **-15**. Acquisition and
local supervision had retained `running` checkpoints; hosted closeout was never
reached. No native executable or network acquisition ran.

## Owned changes

- `ci/project/p06_qualified_warm_inputs.py`: import the existing helper and
  decorate the operational `main()` with `terminate_as_interrupt()`.
- `ci/project/p06_qualified_warm_run.py`: the same CLI boundary plus explicit
  `ci/project/xrt_signals.py` in operational `SOURCE_FILES`.
- `ci/project/p06_qualified_warm_hosted.py`: the same CLI boundary; its source
  closure inherits the added helper from the local supervisor.
- New `ci/project/test_p06_operational_cancellation.py`: four real-signal tests.

No changes to `xrt_signals.py`, `baseline_process.py`, frozen producers/proofs,
budgets, native paths or acceptance state. Existing nested `run_bounded` handlers
continue to own signals while monitoring a child, then restore the enclosing
handler. The tests verify real child reaping, retained completed-command status,
failure receipts, no later acquisition/native stage, restored SIGTERM handling,
and unchanged SIGINT. Hosted packaging/encryption are existing inert fixtures;
their reached closeout path is not real encrypted delivery.

Agent 08 finished independent review of predecessor hunks before these edits.
Byte reconstruction removing only these new imports/decorators/source entry
reproduced all three reviewed SHA-256 values exactly. Agent 08 and root received
the before/after identities. The new cancellation hunks require their own
independent review.

## Validation

Runtime: prepared CPython 3.12.14, source-root execution,
`PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`,
`PYTHONPATH=ci/project`.

Before fix:

```sh
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_operational_cancellation
```

Result: **4 tests, 4 failures**, 3.200 s, exit 1. Three failures show actual
signal exit -15; the live-child control completed cleanup but lacked an enclosing
SIGTERM handler. Log: `notes/agent-10-before.log`. The final test additionally
asserts the completed-child checkpoint state before sending the signal.

Initial fixed signal run: **4 passed**, zero skips, 3.527 s, exit 0;
`notes/agent-10-after-initial.log`.

Final focused command:

```sh
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v \
  test_p06_operational_cancellation test_p06_qualified_warm_inputs \
  test_p06_qualified_warm_run test_p06_qualified_warm_hosted \
  test_p06_qualified_warm_writer_receipts test_p06_input_operational_failures \
  test_p06_warm_supervision_failures test_p06_hosted_operational_failures \
  test_p06_prelaunch_review test_xrt_cancellation
```

Result: **123 passed**, zero skips, 21.062 s, exit 0;
`notes/agent-10-after.log`. This includes preserved prelaunch and writer-disposition
regressions plus helper nesting/custom-handler controls. `git diff --check` passed
for the three changed production files. Direct source retention observed **106**
runner files and **113** hosted files, both including the unchanged 730-byte
signal helper under the existing bounds.

## Source identities

All source paths below are under `ci/project/`.

| File / scope | SHA-256 |
| --- | --- |
| `p06_qualified_warm_inputs.py` before (agent 08 reviewed) | `56d65c98d543757d0d42bc85e90d7377ffcd2976f6343da12f1e4eefd29e9834` |
| `p06_qualified_warm_inputs.py` after | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `p06_qualified_warm_run.py` before (agent 08 reviewed) | `7108581a9317f4dc22741975173e8fd7dd6bfcbfacbd80ac35e30622320b9337` |
| `p06_qualified_warm_run.py` after | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `p06_qualified_warm_hosted.py` before (agent 08 reviewed) | `eba46917d1cdc7dafea97c98ac92a41313f7ce86b62db40f66de36356651cda5` |
| `p06_qualified_warm_hosted.py` after | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `test_p06_operational_cancellation.py` final | `9e04008693a5410a1ede7e6d88ccb86800ed7514a56852fdfffa2fb90877fc6b` |
| `xrt_signals.py` unchanged | `a9531608094a233e5336a35e9fa7ebd028aaa3fc6dd7d3ed0f6f4d3f83a94fb8` |
| `baseline_process.py` unchanged | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |

## Limits and next action

These are focused operational development checks, not strict governance or a
fresh qualified warm execution. No real archive transfer, tool provision,
native GPU work, age encryption or provider delivery ran. Cancellation closeout
remains best effort: SIGKILL, provider loss, repeated interruptions and failures
before an attempt receipt exists can still prevent retention. Programmatic
`acquire()`/`execute()` calls are unchanged; the installed scope is the operational
CLI boundary. No hard-kill recovery or descendant containment is claimed.

Root owns independent review, final-source strict governance, consolidation,
commit and publication. No commit or Git write was performed by this agent.
