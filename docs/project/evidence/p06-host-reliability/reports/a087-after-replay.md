# A087 supplemental — post-replay provider reobservation

**Provider/source/artifact observations remain stable; main CI remains queued.** Authenticated read-only observations ran at **2026-11-26 11:02:26.673–11:02:45.859 UTC**, after A088's retained independent replay finished at **10:59:10 UTC**. Read A088's replay metadata/current report and A087's terminal provider evidence. Neither earlier A087 report was modified. No download, replay, tests, dispatch, rerun or provider mutation occurred.

## Governance and original stability

Current `master` remains `81d7a35c641f3a969c23c8e604f7468a4d88644a`, tree `9da606f541ecb85248ef00995e8288c1266eea88`. Governance run **45796540254**, current attempt **1**, remains **completed/success**, bound to the same repository/head-repository IDs, workflow, `push` event and source. The sole attempt job **139828665982** has **all 13 successful steps**, including each required step exactly once.

The only original remains artifact **15109565376**, exactly named `project-governance-81d7a35c641f3a969c23c8e604f7468a4d88644a-run45796540254-attempt1`: **1,414,721 bytes**, provider SHA-256 **`5596e541ebf8eb272d813ee353b8e5eb998a641aef7b675f5b014cfd8e2ef045`**, `expired:false`, expiry **2026-12-26 10:51:00 UTC**. URLs, source/run/repository binding and timestamp ordering match.

All **seven complete provider bodies** comparable with A087's pre-replay terminal observation are **raw-byte and canonical-JSON identical**, including master, initial/final run, both jobs pages and both artifact pages. Final governance and main-CI run re-fetches also equal their respective initial responses exactly. This establishes observed before/after stability, not continuous monitoring.

## Complete workflow and CI snapshot

Every collection used `per_page=100` and closed with an empty page 2, consistent totals and unique IDs: **15 workflow runs, one governance job, one artifact and two main-CI jobs**. All runs bind the exact source, `master`, `push` and attempt 1. There are **14 completed/success runs and one queued run**, with no observed failures.

| Workflow | Run | Provider state |
| --- | --- | --- |
| Project Governance | `45796540254` | completed/success |
| CI | `45796538630` | queued / no conclusion |
| P06 Managed Preflight Replay | `45796538549` | completed/success |
| P06 Frozen Baseline Replay | `45796538468` | completed/success |
| P06 Managed Counter Preflight | `45796538442` | completed/success |
| P05 Installed Python | `45796538386` | completed/success |
| P06 Checked Counters | `45796538602` | completed/success |
| P06 Native Counter Lifetime | `45796538406` | completed/success |
| P05 Installed PyTorch | `45796538636` | completed/success |
| P04 Native Model | `45796538669` | completed/success |
| P06 Serial Workspace | `45796538670` | completed/success |
| P06 Fresh Dependency Provenance | `45796538759` | completed/success |
| P06 Host MPM Transport | `45796538713` | completed/success |
| P06 Warm Workspace | `45796538767` | completed/success |
| P06 Simulator Completion | `45796538824` | completed/success |

Main CI **45796538630**, attempt **1**, remains **queued**, conclusion null. Its complete current job population is **change-impact 139828517153** and **plan 139828517584**, both queued with empty step lists. No complete main-CI result is established.

## Retention and limits

`governance-current/provider-after/` retains **13 exact provider bodies**, request windows/URLs, complete comparison and workflow summaries, and verified raw/canonical checksums for **17 entries**. Authored metadata contains no connector identifiers or signed URLs; no newline was added to provider bodies.

These non-atomic authenticated observations remain separate from A088's local replay, whose `provider_authenticated:false` claim is unchanged. Workflow-active/artifact-detail checks, production token-isolated transport and anonymous staging were not performed; full hosted admission remains unestablished. Main CI is outstanding. No native, performance or phase acceptance is granted.
