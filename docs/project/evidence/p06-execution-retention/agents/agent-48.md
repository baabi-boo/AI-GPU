# Agent 48 — Final packaging descriptor cleanup

## Result and ownership

Corrected only `ci/project/p06_qualified_warm_pack.py` and added `ci/project/test_p06_pack_final_cleanup.py`. The shared checkout remains uncommitted at base `622662ad9cece6da4e3375be7e977dbe04cde862` plus the prior operational corrections. No commits, native execution, child agents, budget/schema changes, or unrelated repository edits were made.

The final unconditional output-directory close replaced an existing packaging error when the close consumed its fd and then raised EIO. Both public APIs lost their original `RuntimeError`, `KeyboardInterrupt`, and `ValueError` from inventory. The retained private failure receipt still named the original error, making the returned exception inconsistent with that evidence.

A per-invocation `package_failed` flag now distinguishes a primary error from an otherwise successful invocation. Final close errors are suppressed only during this call's failure; an isolated cleanup error remains fatal even when the caller invokes packaging inside an unrelated `except` block. The owned output fd is closed once without retry. Receipt formats, selection, bounds, publication, and recovery are unchanged.

## Reproduction and verification

The new tests use real descriptors and actual package success paths. Their injected close really consumes the owned output fd, then `dup2` puts an unrelated `/dev/null` descriptor at that exact number before EIO is raised. Assertions check a single close attempt, surviving foreign identity, unchanged input bytes, the primary exception object, and failure-receipt attribution. Both public APIs are covered.

Before changing production source, the three new test methods executed ten subcases: all six primary-error subcases failed as expected; both ordinary cleanup-only cases and both cleanup-only cases inside caller `except` passed. `agent-48-red.log` and `.json` preserve the exact command, exit 1, hashes before/after, and original failure output. The original source is preserved in `agent-48-pack-before.py`.

After the fix, the focused command used `Python 3.12.14` at `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3` with `PYTHONDONTWRITEBYTECODE=1`, task-specific `TMPDIR`, and `PYTHONPATH=ci/project`:

```text
python3 -m unittest -v test_p06_pack_final_cleanup test_p06_pack_setup_cleanup test_p06_pack_operational_failures test_p06_qualified_warm_pack test_p06_directory_cleanup_review
```

**44 tests passed, zero failures/errors/skips, exit 0**, including all ten new subcases. Exact invocation/environment and stable per-file hashes are in `agent-48-focused.json`; complete output is in `agent-48-focused.log`. The module run reported 2.858 seconds. Focused checks are development evidence, not complete strict governance qualification. The scoped diff check passed, and the new test has no trailing whitespace.

## Source binding and historical evidence

| Source | SHA-256 |
|---|---|
| Prior pack source | `e4cff314b8a2a0dbb277baef1bc5b3eb78b10a90f777a4d3b60ff74b682dac0e` |
| Final pack source | `585341fd1a7734f06468d8ca25ad8d9f4dc2a08dc861111e98c94e3cf4028134` |
| New regression module | `fe8a7835b51d132f286f5f3e453d873ac52408b7b0ab59f5c5eebd58de3484af` |
| Unchanged historical 22-file freeze | `714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb` |

`agent-48-pack.diff` records only this correction against the exact prior pack bytes. `agent-48.json` binds retained artifacts and source hashes. The original `operational-source-freeze.json` was not rewritten; its 22-file snapshot is now historical, and root must produce a subsequent final source manifest.

Root received the ready-for-independent-review notification after the green focused run. Independent review and eventual exact published-revision qualification remain root's next steps. This correction establishes no native, performance, or phase acceptance.
