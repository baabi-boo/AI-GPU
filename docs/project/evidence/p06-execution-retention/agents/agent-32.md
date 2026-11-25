# Agent 32 — independent governance evidence reconciliation

**Result:** the original base packet independently reconciles as a consistent completed strict-governance pass for `622662ad9cece6da4e3375be7e977dbe04cde862`. No discrepancy with `validation/base-governance-reviewed.json` was found. This is evidence review, not a new suite execution.

## Actual evidence

- Original ZIP: **12 members, 1,320,535 bytes**, SHA-256 `928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156`; expanded member sizes total 21,541,503 bytes.
- Independently rehashed ordered manifest: **5,114 unique IDs**, digest `a33e6215dd12a601aefe3161615083699a8e9fef0ef22a9faaef0331939a71cd`.
- Exactly **5,114 starts, successful terminal outcomes, and stops**, in manifest order; **37,449 successful subtests** attached to their active parents; **52,791 contiguous events**, 19,039,540 event bytes. No fixture or non-success events. All summary accounting agrees.
- Both logs contain all 5,114 IDs in order and finish with `Ran 5114 tests in 3122.101s` / `OK`; the outer log also has the matching strict-pass marker. Summary duration is **3,122.113970 seconds**. Expected compiler/SST fixture diagnostics explain additional outer-log bytes; three descriptions span two lines. Twenty-three oversized subtest labels use the observed SHA-256 encoding.
- Started/summary identities and before/after source, interpreter, and environment records agree. HEAD/index/worktree inventory digests agree, source is recorded clean, and the preparation receipt's actual bytes/hash bind all **11 tools**. Retained Python is **3.12.3**, CMake **3.22.6**. Reviewed runner, preparer, and runbook bytes equal their base-revision versions.

## Deliverables and verification

Only `notes/agent-32-reconcile.py`, `notes/agent-32.json`, and this report were written. The standalone standard-library reviewer reads bounded ZIP contents in memory, rejects duplicate/missing relevant members and duplicate JSON keys, and checks the observed successful v1 schema. It executes no retained code and extracts nothing.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 notes/agent-32-reconcile.py notes/base-governance.zip \
  --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 \
  --expected-sha256 928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156
```

Actual CLI result: exit **0**, `verified-consistent-pass`. Nine focused reviewer-only negative controls all rejected: wrong external hash, missing/duplicate event member, reordered canonical population, wrong subtest parent, inconsistent source despite a copied stable flag, duplicate summary key, incorrect outer-log test count, and oversized preparation receipt. These in-memory corruptions exercised concrete reconciliation/read-bound risks; no project tests ran. JSON retains their rejection reasons, member hashes, reviewed-source hashes, and reviewer hash.

## Limits and next action

The caller-supplied expected hash is the external trust input. This reviewer authenticates neither provider origin nor original runtime/source/tool bytes; it checks retained bindings and consistency. The provider process exit code is not independently observed. The result covers the base only and establishes no native execution, performance acceptance, phase acceptance, or later-edit qualification. Reuse the script with independently obtained revision/hash pins for the later actual governance packet; incompatible schemas or reviewer-limit excesses require review rather than weakening the checks. No repository/source edits, full-suite run, commits, or pushes were performed.
