# Agent 30 — independent packaging setup lifetime review

## Disposition

**Pass for the assigned setup correction; no remaining concrete finding in this boundary.** Read `BRIEF.md`, Agents 27/28, repository instructions and applicable status/gate/retention contracts. Reviewed the dirty working tree over `622662ad9cece6da4e3375be7e977dbe04cde862`; no repository files were edited.

Verified the complete Agent28 delta by reconstructing the previous setup block in memory: its SHA-256 exactly matches Agent27's `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a`. The retained `agent-30-setup.diff` therefore isolates every new setup hunk, independently of earlier packaging changes.

The `None` sentinel prevents closing an unacquired output. The nested `finally` makes one parent-close attempt. If it consumes the parent and raises after output acquisition, the outer handler closes output once and re-raises the original exception; secondary output-cleanup `OSError` or `KeyboardInterrupt` is suppressed. The failure exits before the later normal output lifetime guard, preventing a second output close. Source closes before output-parent acquisition and is not retried. Successful setup continues into the existing packaging guard.

The new regression uses real opens/closes, proves exact parent-number reuse by `/dev/null`, checks original exception identity, verifies unrelated descriptor survival and output EBADF, counts close attempts, and confirms inventory never starts. Both complete and partial public APIs are covered.

## Independent checks

Prepared CPython 3.12.14; source-root cwd; `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, `PYTHONPATH=ci/project`. Exact commands, hashes, results and logs are in `agent-30.json`.

- Unmodified Agent27 preserved reproducer: **1 test passed**, zero skips, 0.001 seconds, exit 0. Parent fd 3 was consumed/reused; output fd 4 is closed; original EIO and unrelated fd 3 survive. Log: `agent-30-agent27-probe.log`.
- `python3 -m unittest -v test_p06_pack_setup_cleanup test_p06_qualified_warm_pack test_p06_pack_operational_failures test_p06_directory_cleanup_review`: **41 tests passed**, zero failures/errors/skips, 2.062 seconds, exit 0. Includes the new 2 methods/6 subcases. Log: `agent-30-focused.log`.
- Independent outside-repository `agent-30-close-trace.py`: **12 cases passed** across both APIs. Tracks logical source/parent/output lifetimes even when fd numbers are reused; all acquired lifetimes close exactly once. Covers consumed parent close, secondary output-cleanup errors, consumed source close, mkdir failure and output-open failure. All original errors survive, reused unrelated descriptors survive, and inventory remains uncalled. An initial reviewer-harness assumption about automatic source-fd reuse was corrected using real `dup2`; its failed log/source remain retained and classified in JSON. Parent-reuse cases still use natural `open` reuse.
- Targeted `git diff --check`: exit 0.

## Exact reviewed identities

| File | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_pack.py` | `e4cff314b8a2a0dbb277baef1bc5b3eb78b10a90f777a4d3b60ff74b682dac0e` |
| `ci/project/test_p06_pack_setup_cleanup.py` | `206756440cdfc4bbac6370d8f664db5c4dfdb9acc4b2eb3f644a48817ed85991` |
| Agent27 preserved reproducer | `0e7b251e175c2784e7a551b3295e8e7a2fe404334c0a43d6c520ae0c4151d482` |

Hashes were unchanged at completion. This is host Python/filesystem fault-injection evidence only. No native/hardware execution, full strict suite, fresh warm measurement, phase acceptance, commits or pushes. Next action: coordinator integration and full strict governance on the final source.
