# Agent 31 — hosted warm operator guide

## Work and scope

Owned repository file: `docs/project/p06-hosted-warm-guide.md` only. Updated the
current continuation to the execution/retention audit and packet, recording
audited base `622662ad9cece6da4e3375be7e977dbe04cde862`, strict run
45583904526/job 139100502944: 5,114 canonical tests, 37,449 successful subtests,
52,791 ordered events, 3,122.11397 seconds, zero failures/errors/skips. Preserved
the 25543e1 and e8e7334 historical results and their exact-revision scope.

The guide requires the published changed revision's own complete strict
invocation, exact Actions result and original receipts without predicting its
result. The 24-process/792-launch/25,344-word experiment remains unstarted and
P06-A02/A03 open. Private control-delivery input/public recipient were not
supplied; live provider secrets were uninspected. The private identity remains
reviewer-owned outside Actions and this session for later decryption.

Added operational guidance for determinate prelaunch failures, matching
finished native receipts, partial bytes, unknown launch/cleanup state,
interruption finalization and observed directory replacement. Recovery does not
promote a failed attempt. Unknown cleanup blocks packaging/encryption.

Agent 25's real-age controls establish that unsuccessful payload decryption
can leave partial private plaintext. The guide now requires discarding it or
retaining it as rejected private failure evidence before normal inspection,
restoration or replay. Successful age decryption remains separate from strict
tar validation, restoration, producer authentication and native acceptance.

## Verification

Read BRIEF, AGENTS, current project status/backlog/roadmap/acceptance, audit,
packet, agent-25 report, retention contract, workflow and relevant production
interfaces/failure paths. Documentation-only change: no production/test edits,
new tests, native commands, dispatch, secrets access, commits or pushes.

Structural check under pinned CPython 3.12.14: all **13 Bash fences** are
byte-for-byte unchanged from HEAD and pass `/bin/bash -n`; **28 local links**
resolve, including **2 heading anchors**; **7 Actions URLs** pass structural
checks. External URLs were not fetched. `git diff --check --
docs/project/p06-hosted-warm-guide.md` passes. Scoped diff: 74 insertions,
22 deletions. Command flags agree with the inspected pack/encrypt/restore/replay
parsers. No governance or real-age execution was repeated by this agent.

## Recorded SHA-256 identities

Hashes record the inspected working-tree snapshot, not a source freeze.
Helper filenames below are relative to `ci/project/`.

| File | SHA-256 |
| --- | --- |
| `docs/project/p06-hosted-warm-guide.md` | `b6e3c2768d99da3966bc1985aad401d84ab066c6a5f3ef91b9e4cdb889a37a93` |
| `docs/project/p06-execution-retention-audit.md` | `a9d0c6e36553ebe0d4085a6118d15ed08ea47328b4168937d4eee262cdc2f964` |
| `docs/project/evidence/p06-execution-retention/README.md` | `d65a40befe070939fc00e6e9ff6dc918b2587893b1043907a4b7b599e81f2c5e` |
| `p06_qualified_warm_hosted.py` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `p06_qualified_warm_run.py` | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `p06_qualified_warm_inputs.py` | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `p06_qualified_warm_control.py` | `a303c3dc56076bbb203376521534e465c5d97b997c9ae1b93e6375e98d298fcd` |
| `p06_qualified_warm_pack.py` | `e4cff314b8a2a0dbb277baef1bc5b3eb78b10a90f777a4d3b60ff74b682dac0e` |
| `p06_qualified_warm_encrypt.py` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |
| `p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |
| `p06_qualified_warm_replay.py` | `1f6cb5cb1dec4c45553d19b3f3e76f1594a570fcac80eabf9d39d5f2564068e4` |
| `.github/workflows/p06-qualified-warm.yml` | `261efa4bcf9c2ca7a9bca8a25dcb03eefd70848426a4c6c61ca55b68a14a7b2e` |

## Remaining action

Root integrates reviews and final source, retains qualification evidence and
publishes/verifies exact-revision CI. The operator must satisfy unchanged
configuration and admission before one complete native attempt, then retain,
decrypt, validate/restore and independently replay its original before the
frozen performance decision. No trigger, acceptance, proof or resource gate
changed here.
