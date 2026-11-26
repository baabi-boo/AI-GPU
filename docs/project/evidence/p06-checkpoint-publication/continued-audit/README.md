# Publication and continued review evidence

The published source is [30b2e8ca69fba47646392c0cf6650cbb75155843](https://github.com/baabi-boo/AI-GPU/commit/30b2e8ca69fba47646392c0cf6650cbb75155843).
Its complete tracked tree is identical to the locally reviewed delivery commit
`9f369a579ca764800b22eedd15e09795f09615da`:
`548b85370e3d13119730b5a30d1ec388d3e141a9`.

This separate audit branch retains observations made after source publication.
It does not move the source revision under qualification. The source's own
strict governance result and independently reconciled original are retained
below; audit-branch CI cannot substitute for that master-branch result. Hosted
native admission still performs its own current provider and source checks.

This branch also corrects the stale leading section in the
[operational handoff](../../../p06-qualified-warm-handoff.md), labeling the prior
closeout continuation historical and pointing to the current source evidence.
It changes no operational gate or production source. The source `master` commit
named above remains the revision under qualification.

## Publication identity

The ordinary HTTPS shell push had no configured write credential and made no
remote ref update. Publication used the connected GitHub Git Data API, following
the repository's established exact-tree procedure. All 89 newly uploaded blob
identities and all five commit trees and parent mappings were checked before a
single non-forced, expected-head update of `master` from `8580904`.

The [publication record](publication/master-publication.json),
[upload record](publication/uploads-089.json) and
[independent verification](publication/a068-publication-verified.md) retain the
readbacks. The latter passed 47 read-only assertions, including an independent
Git remote observation, API parent/tree reads and an empty final source diff.

| Local commit | Published API commit | Meaning |
|---|---|---|
| `ba88572af0bea1e355af08038abcc1f62773a438` | `3a4df86e1de0307132086b5c7be873008848c09b` | Owned temporary cleanup |
| `93bb3f0342eff0b469a0da06cb067916af7c539e` | `913465324786ced3f8ff7acb6c225ff1a165218c` | Directory-access compatibility and producer tests |
| `a693d6f8828e4e10b5374db7fef8c727aa69d34e` | `7cf44e7cbdbc1d09c5ab7f44a3928cd5baf5992f` | Test isolation and required false claims |
| `d31e8879e7c248b1a72615128882533ccdd0b3b4` | `2e789c1edc16dd60fad57c72be7470f51d16da68` | Launcher termination forwarding and reaping |
| `9f369a579ca764800b22eedd15e09795f09615da` | `30b2e8ca69fba47646392c0cf6650cbb75155843` | Verification and historical source retention |

GitHub assigns the API commit metadata, so the commit IDs differ while the
complete source trees remain identical. The five exact raw local commit bodies
are retained in `publication/raw/`; their original IDs were reproduced with both
Git-object hashing and `git hash-object`. The API chain keeps every corresponding
intermediate tree and blob reachable. The original local commits can be
reconstructed by passing each retained body, in table order, to
`git hash-object -t commit -w --stdin`; this adds objects without moving a branch.

A085 independently reconstructed all five original commits in an isolated bare
database using only objects reachable from the published history and those raw
bodies. All 49 assertions passed: the original IDs were initially absent, their
parents and trees matched after restoration, the final source diff was empty,
and full strict Git integrity checking passed. The retained
[restoration report](agents/a085.md.txt) and
[machine observations](supporting/a085-restoration.json) record that check.

## Distinct agent assignments

All **100 distinct agent assignments are complete**. The
[ledger](agent-ledger.json) records each completed assignment and its exact
report hash. Reports are stored as `.md.txt` files or losslessly compressed
`.md.txt.gz` files, retaining their original source scopes, references and
whitespace. Compressed entries record both original and retained identities. At most
three agents ran concurrently alongside the root agent. A report is not a test
pass, a native execution or an acceptance decision. Early defect reproductions,
implementation work, test authorship and later independent reviews have distinct
roles; their counts are not added to test totals.

The Python files in `supporting/` are retained historical probe source. They are
nonexecutable evidence copies, separate from the canonical governance tests;
retaining them does not execute their contents. Original logs are compressed
losslessly, with both original and retained identities in
[the supporting index](supporting-index.json).

## Verification boundaries

The [source evidence packet](../README.md) retains the final focused invocation:
258 unique methods and 752 successful subtests, with zero failures, errors,
skips or retries. All 32 new methods were included. Canonical discovery found
5,547 unique IDs, exactly 32 additions and zero removals from the 5,515-ID base.
Discovery did not execute test bodies. The prior base original's independent
replay applies only to that base, and the focused selection does not qualify the
entire published revision.

## Published revision's complete governance result

The source's [Project Governance run](https://github.com/baabi-boo/AI-GPU/actions/runs/45775559523)
completed successfully on attempt 1. The exact `master` revision is
`30b2e8ca69fba47646392c0cf6650cbb75155843`; the sole governance job is
`139758253740`, and all returned workflow steps succeeded.

The unchanged original ZIP, provider observations, trusted reader snapshots,
invocation records and replay receipt are retained in `current-governance/`.
Artifact `15098885472` contains 1,397,895 bytes with provider SHA-256
`446526e0735f450081978566f713f1288d56562bf2ce65e9e4fb3f9b3bd9b864`.
Its name binds the full revision, run and attempt; the downloaded original
matches that size and digest.

A092 independently replayed it against the clean exact published source and
reader. The complete uninterrupted execution reconciles **5,547 canonical
methods, 38,738 successful subtests and 55,379 events**, with zero failed,
errored, skipped, missing or duplicate method outcomes. The retained execution
lasted **2,368.617247 seconds**. Canonical order and the earlier discovery digest
match exactly. The replay itself took 10.426044 seconds and did not execute test
bodies. Its receipt SHA-256 is
`42b30ac59d6dc41b3c49ca0677b354a9a94d39c612bb49ad66049486eeffe247`.

Provider evidence is recorded separately from the offline reader, whose
`provider_authenticated`, native, performance and phase acceptance fields remain
false. The connector did not expose artifact-detail and workflow-active-state
reads; this review did not execute the full hosted admission protocol. A manual
qualified attempt still has to repeat that protocol on its actual selected
master revision. These governance results establish project tooling execution,
not a qualified native workload or performance decision.

## Remaining native boundary

The frozen qualified-warm attempt remains unstarted. Its declared population is
24 processes, 792 launches and 25,344 checked FP32 words. The automatic legacy
Warm Workspace workflow uses matching counts but explicitly does not establish
the separate qualified route. Exact private control delivery, the public age
recipient, the selected master revision's governance admission and an actual
runner meeting 15 GiB free disk / 4 GiB available memory remain required.
P06-A02/A03 and P01 vendor integration remain open; no performance or physical
hardware acceptance is added by these source changes or review reports.
