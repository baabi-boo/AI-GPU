# A049 — final focused integration

## Result

**PASS:** one uninterrupted invocation executed **258 unique test methods** across **18 modules**, with **752 successful subtests**, at code commit `d31e8879e7c248b1a72615128882533ccdd0b3b4`. There were zero failures, errors, skips, expected failures, unexpected successes, duplicate executed IDs, missing selected IDs or retries. Unittest duration was **28.921 seconds**; total runner elapsed time was **29.784138 seconds**.

The selection is the earlier A023 16-module checkpoint/consumer selection plus `test_p05_launcher` and `test_p05_launcher_signals`. It includes the 24 new checkpoint methods, the eight new launcher methods, the 25 existing launcher methods and relevant existing P02/P04/P06 consumers. Overlapping earlier runs are not added to this count.

## Source and observed isolation

- Start: `2026-11-26T07:04:41.558086+00:00`; finish: `2026-11-26T07:05:11.342199+00:00`.
- Exact code HEAD remained `d31e8879e7c248b1a72615128882533ccdd0b3b4`.
- All **122 observed or explicitly required local Python source files** have matching before/after SHA-256 hashes, with no missing baseline.
- An additional whole-repository Python inventory captured **932 files** before and after; every hash matched. This includes files imported only transiently by scoped import sandboxes even when they are absent from the final module registry.
- The retained full porcelain status (including every untracked file), branch and HEAD are identical before and after. Documentation/evidence changes were already present and are enumerated in the JSON; this was not a clean-tree full-revision qualification.
- No observed import, execution or total process-state differences: cwd, environment hashes, signal dispositions, blocked signal mask, Python threads, Linux task IDs, or open descriptor identity/mode/flags.
- Source stability statements refer to the recorded Python bytes and observed git/process states. The runner does not claim a complete filesystem/process-tree attestation.

| Source | Before/after SHA-256 |
|---|---|
| `ci/project/p02_matrix.py` | `c7544854b1fda853fad7c382e6e51605e812f5a377128fa6198f4da8662d7432` |
| `python/vortex_ai/launch.py` | `01bdadc8469b50fc2b6e511684d37f1bc92d2f4030d3a0900481b8fb5173a128` |
| `ci/project/test_p05_launcher.py` | `55d6d31580ceca32c6ca91e94191bcd9c55c6eac8e57b09f00da2c593f1da5ea` |
| `ci/project/test_p05_launcher_signals.py` | `21583916f92b8bc6d44a5f7743052dd8222216979d3922f62dcf545ef03f1eed` |

## Invocation and retained artifacts

Executed once from `/tmp/ai-gpu-2bfab0261c05/repo`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/ai-gpu-2bfab0261c05/validation/a049-focused-runner.py
```

- Runner: `validation/a049-focused-runner.py`.
- Complete selected IDs, events, subtests, source hashes, dirty-state records and process observations: `validation/a049-focused-results.json`.
- Raw unittest output: `validation/a049-focused.log`.

The runner exited **0**. The strict source/state/count conditions were evaluated after the single invocation. No test retry, source edit, commit or push was performed.

## Qualification limit

These are selected-module, host-side development tests. Real launcher probes execute inert Python child processes and verify process ownership; producer integration uses synthetic records. No native GPU, full governance suite, installed native binding build, numerical execution, warm-workspace experiment or performance acceptance was performed. The eventual selected published revision still needs its own strict unfiltered governance result and independent original replay.
