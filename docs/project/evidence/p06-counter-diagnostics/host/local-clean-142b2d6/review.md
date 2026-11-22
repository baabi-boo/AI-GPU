# Independent clean local governance review — checkpoint 142b2d6

Reviewer: Agent 54, `/root/w09_hosted_checkpoint_review`.

## Actual completed result

**The isolated clean local governance run passed all 3,318 distinct tests in
1,918.414 seconds.** Every method has an `ok` terminal result. There are zero
failures, errors, skips, expected failures or unexpected successes. The four
recorded commands all returned exit code 0, with no resource or time termination.
This is a completed **local** full-suite result using **CPython 3.12.14 on Linux**.
It is not a hosted execution result.

The exact source is commit `142b2d6aaea2fa4226118b857514113032d2e26c`, tree
`754ef8577f9a72785c0809048762c70b16cb4857`, in the clean detached worktree
`/tmp/ai-gpu-governance-142b2d6`. The producer receipt began at
`2026-11-22T16:16:29.395312+00:00` and finished at
`2026-11-22T16:48:45.273881+00:00`. The completion marker was written at
`2026-11-22T16:48:45.319426+00:00`.

The unittest footer's **1,918.414 s** is the suite duration. The wrapper's
**1,920.839 s** elapsed value for the unittest command includes its separate
process-monitoring interval; these values are retained distinctly.

## Commands and original output

Each command ran from the isolated source root using the producer's recorded
Python executable, with `PYTHONDONTWRITEBYTECODE=1` and a separate temporary root
`/tmp/ai-gpu-governance-temp-142b2d6`. The command arguments are preserved exactly
in [execution-receipt.json](execution-receipt.json).

| Command following the recorded Python executable | Exit | Original output |
|---|---:|---|
| `ci/project/preflight.py --tier governance --json` | 0 | [preflight.log](preflight.log) |
| `ci/project/check_project.py` | 0 | [project-metadata.log](project-metadata.log) |
| `ci/project/check_baseline_packets.py` | 0 | [baseline-packets.log](baseline-packets.log) |
| `-m unittest discover -s ci/project -p test_*.py -v` | 0 | [unittest.log](unittest.log) |

The unittest output is **578,913 bytes**, SHA-256
`dd05f5f1b09e8e97ae5fc13b2da5c739d39ef6d22a34d035f1cc9142f564e4c7`.
These are the exact raw combined stdout/stderr bytes written directly by the
local subprocess wrapper. No GitHub download, decoding step or log normalization
is claimed for this local file. The exact original producer receipt is retained
with SHA-256
`7572f52d74385fafe4c26364e663f1c4c43fa800ca8249495c70ac6cd3191355`.

## Independent source and process-record checks

I read the producer wrapper while the suite was still running and preserved its
7,004 original bytes, SHA-256
`cbd21f05dceafb5e1f057c897ddd1a405a1b7db6413deb39a8156a0d02b1e7c5`.
At completion the wrapper source was unchanged. Its completed command records,
log hashes, clean-status observations, source snapshots and success calculation
reconcile with the original logs and completed status record.

The wrapper records **365 source files** spanning `ci/project`,
`.github/workflows`, `tests/unittest/checked_counters` and
`sim/simx/checked_counters.mk`. I independently obtained the complete immutable Git
path list, checked exact membership and order, and compared every recorded hash
and size against both **Git's checkpoint bytes and the actual isolated worktree
bytes**. All 365 match. Before and after source records are identical; the logged
initial and final Git status are clean. A fresh independent status check including
untracked files is also clean. HEAD, tree and detached state were checked directly.

The selected committed checked original, failed public original, successful-public
original, intake receipt and pinned archive parser also match immutable checkpoint
bytes in the isolated worktree. These are retained-data inputs; their use does not
rerun the native producers.

The entire 4268-to-142b commit delta changes only two test modules. Their hashes
match the separately completed Agent 60 review:

| File | SHA-256 |
|---|---|
| `ci/project/test_p06_counter_diagnostics_replay.py` | `c8d213737b6332a5e6c924114b3e403a2ddcea3e0a2eac2f1fd431a5f4842430` |
| `ci/project/test_p06_counter_public_replay.py` | `241299ec7abfbbafe857c9d23ea10a0350b2606b10af4d942912780068d01a5d` |

A final comparison of all **353 current main-checkout CI/workflow files** also
matches the tested 142b checkpoint. Concurrent narrative/evidence changes are
outside the clean checkout tested here. The unchanged production readers,
interpreter enforcement and native workflow still retain the native CPython
3.12.14 pin; no production, workflow or native budget was weakened by this
fixture repair.

## Exact test-ID and result reconciliation

The completed log contains the same **3,318 unique IDs** as the pre-run independent
AST/unittest discovery. All 3,312 prior IDs remain, including both methods that
failed in the original hosted 4268 run. Exactly six IDs were added; none was
removed. [test-results.json](test-results.json) retains every ID, result and log
line association.

A strict single-line header count yields 3,316 `ok` results. Independent review
reconciles the remaining two rather than treating that shortcut as the total:

- One existing test description continues on a second line before its `... ok`.
- The SST hostless-dispatch fixture writes its four stdout lines after the test
  header, followed by unittest's standalone `ok` at line 2986.

There are therefore **3,317 ellipsis `ok` terminals plus one standalone `ok`**,
associated with exactly 3,318 distinct method headers. The first use of the
GitHub-oriented review parser stopped at that interleaved SST output. I adapted
only the reviewer parser to associate its pending method with the standalone
terminal, then verified the total and complete ID set. The producer log, tests
and source were never changed, and no test was rerun to obtain this reconciliation.

| Replay/inventory group | Executed methods | `ok` | Skips |
|---|---:|---:|---:|
| Checked replay and shared path guards | 47 | 47 | 0 |
| Public replay | 42 | 42 | 0 |
| Inventory integration | 23 | 23 | 0 |
| Source-inventory helper | 48 | 48 | 0 |
| **These four modules** | **160** | **160** | **0** |

The two previously failed inert-replay guards are explicitly `ok` at lines 2074
and 2212. All six new regression methods are also explicitly `ok`:

| Added regression | Log line |
|---|---:|
| Checked replay with collocated current/producer roots | 2073 |
| Checked forged parser rejected before execution | 2075 |
| Active helper resolution blocks siblings and ancestor reads | 2082 |
| Current helper allowance rejects write-capable opens | 2083 |
| Public replay with collocated current/producer roots | 2211 |
| Public forged parser rejected before execution | 2213 |

These results complete actual full-suite verification on the recorded local
CPython 3.12.14 environment. They do not prove an execution on the still-unassigned
GitHub host or its eventual interpreter. The separate Agent 60 report remains the
independent source/delta review; this report adds the completed full-suite
source/log verification.

## Resource observations and limits

The wrapper enforces the separate documented governance budget at command entry
and through five-second samples. It terminates a process group when a sampled
floor or the 40-minute per-command limit is breached. No termination occurred.

| Observation | Configured floor | Minimum retained sample |
|---|---:|---:|
| Temporary-filesystem free space | 1,073,741,824 bytes (1 GiB) | **2,264,096,768 bytes** |
| Host `MemAvailable` | 536,870,912 bytes (512 MiB) | **1,633,263,616 bytes** |

These are sampled host/resource observations, not continuous or cgroup memory
attestation. The separate governance budget does not relax native build gates.
No native GPU build or execution is claimed by this suite or review.

## Failure history and hosted status remain separate

The original [4268 hosted review](../checkpoint-4268d2d/failed-review.md) remains a
failed attempt: 3,312 tests, 3,310 `ok`, two failures, 1,811.712 s and exit code 1.
Its original decoded log, all older failed attempts and the historical e5 pass
are preserved. The new local attempt is appended separately to
[the host index](../index.json), with `hosted_execution=false`.

The [142b hosted pending receipt](../checkpoint-142b2d6/pending-receipt.json)
retains a specific API observation: run `45040805357`, job `137264592244`, queued
with no runner, steps or conclusion as of `2026-11-22T16:22:56Z`. Later observations
are separate files in that directory. Pending observations state their timestamp;
they do not predict an eventual result. No GitHub run ID is assigned to this
local execution, and no hosted pass is inferred from it.

## Assessment

No open finding was identified in this bounded local source/log verification.
The 4268 failure is preserved, the exact reviewed test repair has now passed the
complete documented governance suite in a clean source checkout, and the
six added rejection/collision controls and two formerly failed methods executed
successfully. This is independent advisory evidence, not maintainer approval or
a gate waiver.

Qualification, warm readiness, warm execution and acceptance remain **false**.
The result does not establish seed-free native measurement-binary qualification,
loaded-dependency authentication, a complete warm caller, physical hardware
performance, a warm speedup or new phase acceptance. The original source/log
boundaries remain explicit.
