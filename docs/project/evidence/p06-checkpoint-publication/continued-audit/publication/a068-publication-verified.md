# A068 — independent publication verification

## Result and scope

**PASS: 47 read-only assertions.** Remote `master` was independently read back as
`30b2e8ca69fba47646392c0cf6650cbb75155843`. Its complete tracked tree equals local
`9f369a579ca764800b22eedd15e09795f09615da` at root tree
`548b85370e3d13119730b5a30d1ec388d3e141a9`. The final file diff is empty.

GitHub API commit observations were read at **2026-11-26 07:29:45 UTC**; the final Git readback and local checks completed at **2026-11-26T07:31:02.615413+00:00**.

## Verified commit mapping

| Local commit | Published API commit | Exact common tree |
|---|---|---|
| `ba88572af0bea1e355af08038abcc1f62773a438` | `3a4df86e1de0307132086b5c7be873008848c09b` | `21b1a2247078d376d61a25523e9f74cf93fafbcf` |
| `93bb3f0342eff0b469a0da06cb067916af7c539e` | `913465324786ced3f8ff7acb6c225ff1a165218c` | `2d1d19b5f48a18f9c72569683752c6d5bddc165f` |
| `a693d6f8828e4e10b5374db7fef8c727aa69d34e` | `7cf44e7cbdbc1d09c5ab7f44a3928cd5baf5992f` | `7d36a4dab10389ef3fce843cf4cb4b488ae2bab2` |
| `d31e8879e7c248b1a72615128882533ccdd0b3b4` | `2e789c1edc16dd60fad57c72be7470f51d16da68` | `364ae3cb38750521a0404d6f55ab037d6af64e14` |
| `9f369a579ca764800b22eedd15e09795f09615da` | `30b2e8ca69fba47646392c0cf6650cbb75155843` | `548b85370e3d13119730b5a30d1ec388d3e141a9` |

For every pair, independently fetched GitHub commit metadata and fetched Git
objects agree on the recorded tree and API parent. Both chains start at the
published base `858090410a992756808256ace90d36b9b3b88dd3`. All five API commits
are ancestors of the final published head. Complete recursive tree entries match
for each local/API pair, including paths, modes, blob identities and gitlinks.

The five retained raw local commit bodies match the original local Git objects.
Both direct Git-object SHA-1 computation and read-only `git hash-object -t commit`
reproduce every original local commit ID. Their original UTF-8 bytes and terminal
newlines remain intact. These bodies plus the corresponding reachable trees allow
the original local commits to be reconstructed in order; this audit wrote no Git
objects and changed no refs.

## Identity and preservation limits

The API commit IDs differ from the local IDs. This is an explicit metadata and
parent-identity mapping, not a claim that the original commit objects were pushed
unchanged. Source-tree equality does not turn the focused local tests into a full
CI qualification of the API revision. The actual published head needs its own
strict governance original and independent replay.

The raw local commit bodies were verified in the local publication directory.
Their planned later audit-branch retention is a separate action and is not claimed
as already published by this report.

The original source checkout stayed on the same HEAD with an empty porcelain
status throughout this review. No source/worktree/ref changes, commits, pushes,
test bodies, builds, native execution or CI-status queries were performed.

## Retained evidence

- `a068-publication-verified.json`: all assertions, per-commit identities, raw-body hashes and final diff result.
- `a068-remote-observation.json`: independently queried API tree/parent metadata and observation time.
