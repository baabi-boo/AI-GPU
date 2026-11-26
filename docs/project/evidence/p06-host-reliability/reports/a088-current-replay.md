# A088 supplemental — independent current-original replay

**PASS: one authorized local replay completed with exit 0 at 10:59:00–10:59:10 UTC on 2026-11-26.** The original A088 report is unchanged. Used clean master `81d7a35c641f3a969c23c8e604f7468a4d88644a`, tree `9da606f541ecb85248ef00995e8288c1266eea88`, as both trusted reader and canonical source. Read A084’s exact isolation procedure, A087’s independent terminal provider selection and the replay/source/collection helpers before execution.

## Original and invocation

Authenticated selection predates acquisition: run **45796540254**, attempt **1**, artifact **15109565376**; expected original length **1,414,721 bytes**, SHA-256 **`5596e541ebf8eb272d813ee353b8e5eb998a641aef7b675f5b014cfd8e2ef045`**. The existing original matched before execution and remained mode **0400**, single-link, with identical device/inode, length, timestamps and digest afterward. No extraction or repacking occurred.

Executed `governance_replay.py` exactly once with `--archive`, `--expected-revision`, `--source-dir`, `--expected-sha256` and a fresh external `--output`. Used Python **3.12.14**, `-B`, A084’s exact `env -i` variables and `timeout -k 5s 180s`. The retained wrapper records every literal argument. No test bodies, native work, source/audit edits or Git publication ran.

## Reconciled receipt

| Original execution measure | Reconciled value |
| --- | --- |
| Canonical tests | **5,575** |
| Successful subtests | **39,419** |
| Ordered events | **56,144** |
| Recorded original execution duration | **2,744.522179 seconds** |
| Canonical ID SHA-256 | `28c75e1288706ae64139ac5e4ebed1a240ad24e757a5647a00a6b816ea41426a` |

These are the retained original’s executed population, not new local test execution. `replay.json` exactly equals stdout; stderr is empty. Before/after identity files are byte-identical, covering the original, ancestor directory identities, **nine reader/runtime hashes** and complete materialized source binding: **8,488 entries / 536,536,028 bytes**, tracked SHA-256 `aad3110755cd820cb2ca81a5050e974c6b5f8ec35d3283d9e99486cc0e987985`. Porcelain including ignored paths remained empty.

The development storage gate required **1,107,296,256 free bytes**: 1 GiB reserve plus 32 MiB metadata, with the original already acquired. Observed tmpfs free space was **1,353,760,768 before / 1,353,723,904 after**. Host available-memory observations were **3,386,806,272 / 3,354,890,240 bytes**, with no swap; effective cgroup capacity was not established.

## Claims, retention and limits

`independent_packet_replay` and `trusted_source_imported` are true. All six other claim fields remain false: `provider_authenticated`, `retained_code_executed`, `tests_executed_by_replay`, `native_acceptance`, `phase_acceptance` and `performance_acceptance`.

`governance-current/` retains the original, receipt, exact wrapper, logs, identities, resource observations, `a088-replay-metadata.json` and `a088-replay-sha256.json`. Separate authenticated provider evidence and its subsequent reobservation belong to the coordinator. This local reconciliation does not establish full hosted admission, qualify a later documentation commit, reproduce recorded execution, or waive the native 15 GiB/4 GiB gates and private-input prerequisites.
