# Agent 50 — Publication-candidate focused invocation

## Result and scope

**Passed: 328 distinct test methods across 26 modules in one audited unittest subprocess.** Collection, execution and result accounting occurred in that same process. All 328 IDs were started, succeeded and stopped exactly once in discovery order; the retained trace contains 984 ordered start/success/stop events and 645 successful subtests. Failures, errors, skips, expected failures, unexpected successes, unfinished tests, duplicate IDs, loader errors and active skip decorations are all zero. The post-run evidence review independently reconciled the complete event sequence, ID digest, raw result and combined log without executing tests again.

The runner used CPython 3.12.14 at `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`, `-B`, source-root working directory `/tmp/ai-gpu-ae456f837c05/AI-GPU`, and these environment overrides:

```text
PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin
PYTHONDONTWRITEBYTECODE=1
TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp
PYTHONPATH=ci/project
```

Test execution ran from `2026-11-25T13:05:52.185230+00:00` to `2026-11-25T13:07:05.638327+00:00` and took **73.452944 seconds**; the observed subprocess interval was 74.584592 seconds. Exit status was **0**. The exact argv, complete driver, ordered module selection, every discovered/start/outcome/stop ID, per-module counts, event trace, timing and zero-skip flags are retained in `agent-50.json`. Complete combined stdout/stderr is retained in `agent-50-tests.log` (62,431 bytes).

## Selection and source identity

The exact ordered 25-module selection and audit driver from `agent-42.json` were reused, with `test_p06_pack_final_cleanup` appended. Actual collection comprises **11 existing modules / 275 methods** and **15 new regression modules / 53 methods**. The new cleanup module contributes three methods. No earlier 325-test result was combined with this invocation.

The checkout remained based on `622662ad9cece6da4e3375be7e977dbe04cde862` with uncommitted publication-candidate changes. All **23 frozen-file snapshots** matched the publication manifest before and after execution. All **26 selected-module snapshots** were also unchanged, covering **33 unique source files** in total. Each snapshot retains SHA-256, size and mode. The manifest itself was unchanged; 74 in-run source observations detected no changes.

| Identity | SHA-256 |
|---|---|
| Publication 23-file freeze | `6c90e8e2c097b1d8db3534835d4f8ae94c4f6dc2c20b1c59283342c0b1c2dbf8` |
| Final packaging helper | `585341fd1a7734f06468d8ca25ad8d9f4dc2a08dc861111e98c94e3cf4028134` |
| New final-cleanup regression | `fe8a7835b51d132f286f5f3e453d873ac52408b7b0ab59f5c5eebd58de3484af` |
| Exact reused audit driver | `9acfdece0f89db913197ac469dc4cdb8e918f46f182b1903509827db2fd7ba72` |
| Ordered discovered-ID list, newline terminated | `1cb12e6f4d9ab7d9c753c7fe8f4274e1ef2eff2ad2f0ee3694b1c3c55b68c24f` |
| Complete combined test log | `0655bc257ceecfe9ad74df55b4419e74f55b88efab62ee24bc50819e89edf18c` |
| Retained historical 22-file freeze | `714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb` |

## Limitations and next action

This is focused operational development evidence for the retained source identities. **Full strict governance qualification, native execution, performance acceptance and phase acceptance were not performed or claimed.** No repository/source edits, network lookups or downloads, commits, child agents or additional unittest invocations were made by Agent50. The historical 22-file freeze and earlier evidence remain independently scoped and unchanged.

Root can incorporate these records alongside the independent final-cleanup review. The published changed revision still requires its own complete strict result and unchanged native admission before the qualified warm experiment.
