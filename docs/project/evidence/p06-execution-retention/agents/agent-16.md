# Agent 16 — control acquisition outer finalization

Base HEAD: `622662ad9cece6da4e3375be7e977dbe04cde862`, preserving the existing control changes by agents 06/13 and concurrent disjoint edits. Read the task brief, repository AGENTS instructions, current status/backlog/roadmap/acceptance material, resource/review policy, qualified-warm automation failure/retention contract, and agent 06/12/13 reports. No commits or other Git writes/publication.

## Owned files and correction

- `ci/project/p06_qualified_warm_control.py`
- New `ci/project/test_p06_control_finalization.py` (eight test methods).

The preexisting outer `acquire_control` finalizer wrote its receipt, then closed the archive, then closed the output directory. A real archive descriptor close followed by injected EIO skipped directory closure. A real output-directory close followed by EIO left a success-shaped receipt. Either cleanup exception could also overwrite the primary finalization diagnosis. Four initial regressions failed against the exact pre-change source; root approved the bounded correction design after the reproduction.

Archive closure now precedes receipt publication. A failed close marks an otherwise passing report `storage_failed` (or `interrupted` for interruption) while retaining an existing primary reason. Receipt finalization and output-directory closure are still attempted; the first finalization error is raised with the existing sanitized `IntakeError` API. Subsequent cleanup cannot turn failure into success or replace the primary receipt failure.

The existing receipt invalidation logic is factored into one bounded helper. Successful receipt writing returns the original receipt and directory identities internally; no on-disk schema changes. If output-directory closure fails after descriptor release, repair opens the canonical directory once and requires its saved identity, owner and private mode. Receipt recovery requires original inode/type/link/mode/owner checks before open and descriptor/path/ownership checks after `O_NOFOLLOW | O_NONBLOCK` open before any truncation. Each acquired recovery descriptor gets one cleanup attempt even if the other close raises. No duplicate-descriptor chain, uncertain-fd retry, original-archive rewrite or unowned replacement mutation is introduced.

## Reproduction and executed checks

Environment: checked CPython 3.12.14 at `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`; repository source root; `PYTHONDONTWRITEBYTECODE=1`; `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`; `PYTHONPATH=ci/project`.

Before implementation, `python3 -m unittest -v test_p06_control_finalization` ran **4 tests in 0.012 seconds; FAILED (failures=4)**. The log is `notes/agent-16-red-tests.log`. Cases established skipped directory cleanup, retained `pass/true` after directory close, primary interruption loss and raw cleanup replacement of `receipt_failed`. All injected closes released the real descriptor before raising EIO.

After correction and directly affected recovery-safety coverage:

```sh
env PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PYTHONPATH=ci/project /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_control_finalization test_p06_control_closeout_review test_p06_control_operational_failures test_p06_qualified_warm_control
```

**55 tests in 0.570 seconds, OK**, zero skips/failures/errors. Original archive bytes remain exact; partial interruption bytes remain exact. The eight new tests cover outer real-close failures, first-error preservation, regular/symlink/archive-hardlink receipt replacements after descriptor release, directory replacement, a hardlink-to-original substitution between receipt precheck and open, and errors after both recovery closes. Recovery descriptors are verified released with EBADF and their close attempts remain bounded. The existing tests retain production pin/proof, bounds, exclusivity, private permissions, sanitization, receipt fsync and transport cleanup coverage. Full output: `notes/agent-16-tests.log`.

Scoped `git diff --check -- ci/project/p06_qualified_warm_control.py ci/project/test_p06_control_finalization.py` passed. No full strict governance, native experiment, live network/storage, private original, key, dispatch or acceptance evaluation was performed.

## Exact source and log identities

| Path | SHA-256 |
| --- | --- |
| Before: `ci/project/p06_qualified_warm_control.py` | `ef5c127094e8e51aa5d5cfc101135e493de13c4be25c6979002cc7e6acc11a9d` |
| Final: `ci/project/p06_qualified_warm_control.py` | `edb6c8e65191087da0278d5235d31cc4080d3b4e6f9f30c2147d3f5de4fa4ccc` |
| `ci/project/test_p06_control_finalization.py` | `7020fea4b05a002f8d6353aed429d66e4162f9e2d4f202a0ca401edfb2c6e06c` |
| `ci/project/test_p06_control_closeout_review.py` | `8502a9c800a864aaa947e3f9a68f112a5213ce8401a59121ad16514a811b72a2` |
| `ci/project/test_p06_control_operational_failures.py` | `b281681fdf158062be763ce46aecff9b18634faba937072e490636a99b494e09` |
| `ci/project/test_p06_qualified_warm_control.py` | `9dddf361cc18d72b40636156e36f40d359c36872bebae9925e6c96a063808ead` |
| `notes/agent-16-tests.log` | `ebc955feaad0525d79a9b309cb8a32d317b8d96749ffe1f78c560bf41a399a48` |
| `notes/agent-16-red-tests.log` | `45b24e98b462c98a81385bf6e47b6e885bb225a24d8a1ba12d6a0a0ec96e8268` |

## Limits and next action

Repair remains best effort. Continuing storage failure can prevent rewriting. If the owned receipt or directory is renamed after its last descriptor closes, recovery refuses an unowned replacement and does not search for the renamed inode; the invocation still raises a sanitized failure even though an inaccessible renamed success-shaped receipt can survive. There is no crash atomicity or malicious same-user exclusion claim. Pins, proof/gate formats, schema, resource thresholds, frozen/native files and phase records are unchanged.

Root should assign a fresh independent review of the complete final lifecycle and retain strict governance for the final combined source before publication. Source/test files were declared frozen to root and agent 19 after the successful final targeted run.
