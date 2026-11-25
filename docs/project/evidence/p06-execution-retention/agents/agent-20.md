# Agent 20 — capacity and admission review

## Scope and conclusion

Read-only review of the current execution/retention fixes over base
`622662ad9cece6da4e3375be7e977dbe04cde862`, guided by `AGENTS.md`,
`notes/BRIEF.md`, `p06-execution-retention-audit.md`, the developer resource policy,
and the hosted operator guide. No source edits, native experiment, toolchain
execution, network acquisition, or governance qualification were performed.
No concrete F2 was found in the assigned capacity/admission scope.

The capacity observer never establishes effective capacity or launch authority.
Even complete all-`max` visible samples keep `effective_capacity_status=unknown`,
`ancestry_complete=null`, and every acceptance/launch claim false. Missing,
unsupported, changing, or unreadable visible observations remain incomplete and
cannot satisfy `hosted.capacity_gate`. A complete visible observation can satisfy
that preliminary screen while effective capacity remains unknown; the wrapper
explicitly returns `effective_capacity_established=false` and proceeds through
separate production admission. This is not evidence that hidden ancestors are
unlimited or that RAM has been reserved.

The native/acquisition reserve remains **16,106,127,360 bytes (15 GiB)** and the
available-memory/RSS threshold remains **4,294,967,296 bytes (4 GiB)**. The budget
still specifies two build jobs, one simulation worker, 16 MiB command logs, and
the supervisor's 5,400-second outer execution limit. Exact threshold equality
passes the resource screen; one byte below either threshold fails. Each hosted
volume is checked independently. Current source diffs do not change those limits.

The hosted lower disk floor (`min_free_bytes=1`) is passed only to explicitly
retention-marked stages. Host setup, control intake, input acquisition and native
supervision retain the full disk reserve. Encryption separately checks its
uncompressed tar/ciphertext bound plus a 64 MiB margin; a small failure packet can
therefore be retained below 15 GiB without authorizing native work.

## Actual validation

- **36 focused unittest methods passed in 1.785 seconds**, zero failures, errors
  or skips; invocation exited 0. The exact method IDs and outcomes are retained
  in `validation/agent-20-focused.log`.
- Scope: the complete capacity module; hosted capacity-screen, unchanged-budget
  composition and observed-prelaunch closeout tests; input command budgets and
  pre/post resource-failure tests; supervisor fixed-budget, resource-block and
  incomplete-cleanup tests; four encryption storage-boundary tests.
- **27 independent checks passed**, invocation exited 0. The reproducible probe
  is `validation/agent-20-boundaries.py`; results and source identities are in
  `validation/agent-20-boundaries.json`.
- Both invocations used pinned CPython 3.12.14, `PYTHONDONTWRITEBYTECODE=1`, the
  task-specific `TMPDIR`, source-root `PYTHONPATH=ci/project`, and the prepared
  environment path. The independent probe command was the pinned Python
  executable followed by `validation/agent-20-boundaries.py` from the source
  root, with that script path resolved under the task directory.
- Tests use synthetic command/age fixtures and temporary inert Git repositories.
  They do not run the GPU, acquired toolchains, or retained artifact code.

Independent resource-error results:

| Fault boundary | Observed result |
| --- | --- |
| Input inventory before acquisition | `blocked`, zero commands/parts, `native_execution=not_run`, no input identity |
| Input inventory after acquisition | `fail`, 21 synthetic completed commands and 15 retained parts, no input identity, native `not_run` |
| Supervisor initial disk inventory | `blocked`, zero stages, native `not_run` |
| Native stage resource block after preparation/build fixtures | Attempt `fail`; native stage explicitly unstarted and cleaned; native `not_run`; no completed counts |
| Hosted capacity inventory error | Attempt remains `fail`, orchestration false, native `not_run`, even though synthetic packaging/encryption closeout succeeds |

## Current local blockers

Snapshot at **2026-11-25 12:08:05 UTC**: source and attempt storage each had
**2,773,561,344 bytes free (2.583 GiB)**, below the unchanged 15 GiB reserve.
Host `MemAvailable` was **6,587,498,496 bytes (6.135 GiB)**, but the cgroup mapping
reported `mapping:missing_or_ambiguous_v2_mount`. Observation completeness was
false, effective capacity unknown, visible headroom absent, and the local
capacity screen false. Native launch authorization and effective-capacity
establishment both remained false. No private machine paths were retained in
this summary.

The next native action still requires an admitted runner, the unchanged private
control original and recipient configuration, and final-revision strict
qualification. This audit supplies none of those missing prerequisites and does
not advance P06-A02/A03 or other acceptance gates.

## Reviewed source identities

All paths below are relative to `ci/project/`. Hashes were equal before focused
validation, after the independent probes, and at report creation.

| File | SHA-256 |
| --- | --- |
| `p06_qualified_warm_capacity.py` | `fe3f6eb302e86e7db403c6f5fdc97718ef784d246b579a880f321ca9324411f0` |
| `p06_qualified_warm_hosted.py` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `p06_qualified_warm_inputs.py` | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `p06_qualified_warm_run.py` | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `p06_qualified_warm_encrypt.py` | `015ef01b1418ef5ef5328859c905854c928ab7c996aba9352603383ef648ca24` |
| `p06_dependency_contract.py` | `d6151024fbe7e8a651075fd76b9bdc006bb18c0f61c538a2928842f865ddd364` |
| `baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `preflight.py` | `102c174cb6e3baa082957a88e05080f9b18e80340e663702f8585586eecf6032` |
| `test_p06_qualified_warm_capacity.py` | `1c63367c12ad38b1bdb96ab468bf22f7d556959f552f7d953dfb6ff782e854bd` |
| `test_p06_qualified_warm_hosted.py` | `d14fef2b03981987b8d313cad56a3d0085c577a5a6c615832acd3422d6f5ea6f` |
| `test_p06_qualified_warm_inputs.py` | `b396baf71d274919798f54eb9ef5a49dbebf62909b7bdeab548fa28ce441a5f7` |
| `test_p06_qualified_warm_run.py` | `6d695dcc9f4217a999033f38e5594e3efb1072e432a92288143bf11be1bccf27` |
| `test_p06_qualified_warm_encrypt.py` | `10a104f429e47584339e3bcc0cf77ed6bf3ad13b054b1233de7253c0d8323b4c` |

## Retained validation identities

| Artifact | SHA-256 |
| --- | --- |
| `validation/agent-20-focused.log` | `dc408539c8edaa1f78cf0675f8fd56e242a84b5a7bc1ee665cdaef876b3da2b6` |
| `validation/agent-20-boundaries.py` | `2d82d95f553d5036537e002b0c27ffd3ab83cf1646e9884bd98897b7c46eecc8` |
| `validation/agent-20-boundaries.json` | `ad04d9549f2a504a2dbf5eed18a6c2286684930e2c44b4881475bc8f273deac0` |
