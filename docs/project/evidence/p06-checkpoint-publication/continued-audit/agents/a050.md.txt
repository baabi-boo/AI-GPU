# A050 final canonical discovery

**Discovery passed at `d31e8879e7c248b1a72615128882533ccdd0b3b4`: 5,547 unique test IDs.** No test bodies were executed.

## Invocation and source

- Source root: `/tmp/ai-gpu-2bfab0261c05/repo`; committed tree `364ae3cb38750521a0404d6f55ab037d6af64e14`.
- Python 3.12.14; `-B` and `PYTHONDONTWRITEBYTECODE=1`.
- Ordinary unmodified `unittest.TestLoader().discover(start_dir="ci/project", pattern="test_*.py", top_level_dir="ci/project")`, with no test-name filtering. The explicit top-level directory equals the start directory, the default used by the canonical governance runner.
- Discovery duration: **2.735989 seconds**.
- The exact before/after HEAD, tree, worktree status and hashes of **549 Python files** under `ci/project` and `python` match. The working tree contained ongoing documentation/evidence changes; no repository file was edited by this audit.

## Exact population comparison

The retained base original at `858090410a992756808256ace90d36b9b3b88dd3` contains **5,515 IDs**. Its `run/discovered.json` count and ID digest agree with the actual ordered manifest. The ZIP SHA-256 agrees with the retained provider metadata:

`21c1c6bda5e8513d99642dd12d5db8c52d4b2bcae8726119b12236e7708fc74e`

The current manifest contains **5,547 IDs**, all unique, with **zero loader errors, failed-import placeholders, duplicate IDs or removals**. All **5,515 base IDs retain their relative discovery order**. The **32 additions** exactly match the AST-defined methods in seven new modules:

| Module | Added methods |
|---|---:|
| `test_checkpoint_directory_access` | 2 |
| `test_checkpoint_ownership` | 7 |
| `test_checkpoint_write_failures` | 4 |
| `test_p05_launcher_signals` | 8 |
| `test_p06_checkpoint_input_recovery` | 2 |
| `test_p06_checkpoint_prepare_build` | 5 |
| `test_p06_checkpoint_run_recovery` | 4 |

Comparison with the A029 discovery record at `a693d6f8828e4e10b5374db7fef8c727aa69d34e` gives **8 additions, zero removals**, preserving all **5,539 prior IDs** in their relative order. These eight additions are exactly the new launcher lifecycle methods.

The current ordered-ID digest, computed from each ID followed by a newline, is:

`0e8dbaad34266093f76db937eba670ce8f628ceb500998cb9094cdd2f12071fa`

## Retained evidence and limit

- Complete ordered IDs, source hashes, before/after status, exact deltas and 16 passing checks: `/tmp/ai-gpu-2bfab0261c05/validation/a050-discovery.json`.
- Exact invocation script: `/tmp/ai-gpu-2bfab0261c05/validation/a050-discovery-runner.py`.

The archive was read as inert JSON. This audit did not run a test suite or test method, replay governance execution, run native workloads, build artifacts, qualify a complete revision or change acceptance. No source edits, commits or pushes were performed.
