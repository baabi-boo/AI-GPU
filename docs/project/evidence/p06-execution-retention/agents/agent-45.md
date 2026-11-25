# Agent45 — scope and provenance preservation audit

**Result: pass for the inspected candidate snapshot.** Read-only comparison against `622662ad9cece6da4e3375be7e977dbe04cde862`; HEAD remains that base. Snapshot completed `2026-11-25T12:54:16.162636+00:00`. Only this report and its companion JSON were written; no repository edits, Git writes, tests, native builds, installations or deletions.

## Exact change scope

Independently hashed all **7,700 tracked blobs** using Git’s raw blob framing and SHA-1, plus SHA-256 and file modes. **7,688 are unchanged, 12 modified, none missing**. Five unpopulated submodules retain identical Gitlink commits. The index exactly matches the base.

The candidate contains **167 changed paths**: **6 production helpers, 1 existing fixture, 14 new regression modules, 6 documentation files, 140 evidence files**. All 155 additions are untracked at this snapshot. No unexpected paths. `agent-45.json` records every exact path by category and its current Git blob/SHA-256 identity; existing modifications also record base blob identities.

Production changes are exactly `ci/project/p06_qualified_warm_{control,encrypt,hosted,inputs,pack,run}.py`. The existing fixture is `ci/project/test_p06_qualified_warm_control.py`. Documentation is exactly `README.md` and `docs/project/{backlog,p06-execution-retention-audit,p06-hosted-warm-guide,p06-qualified-warm-handoff,status}.md`. All evidence additions are under `docs/project/evidence/p06-execution-retention/`.

## Preserved invariants

Raw content and modes match the base for: kernel **25**, runtime **70**, simulator **200**, hardware **882** (including RTL **415**), native test files **1,418**, build/configuration selection **475**, `VERSION`, golden/baseline selection **25**, acceptance files **7**, roadmaps **2**, proof paths **8**, workflow files **20**, and all **4,007 existing evidence files**. Counts overlap; group selections and canonical inventory hashes are recorded in JSON. The exhaustive raw comparison covers remaining tracked paths too.

The protected SVG is byte-identical and its original README image embedding remains. SVG SHA-256: `db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`. `LICENSE` and all nine license/notice paths remain unchanged; README’s entire “License and upstream credit” section is byte-identical.

All **304 existing project test modules** preserve their **5,029 statically defined test functions/methods**. The sole old-file delta is exactly the three-line `Response.close()` fixture addition. Fourteen new modules define **50** test functions/methods; this is a static count, not test collection or execution. All **21 scoped production/fixture/regression files** retain Apache-2.0 SPDX headers. Evidence scripts/log formats were not refactored.

## Frozen identities and visibility

Operational source freeze: **22/22** hashes, sizes and modes match. Frozen inputs: **5/5** match both manifest and base. Measurement sources: **69/69** match current bytes, base and the frozen proof’s exact records. Manifest identities are in JSON; operational freeze SHA-256 is `714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb`.

All **7,705 index flags are H**: no assume-unchanged or skip-worktree entries. Sparse checkout, ignore-stat, fsmonitor, custom excludes and external diff settings are absent; no active local exclusions, ignored untracked files, replacement refs or grafts. The declared shallow boundary is the audited base. Changed bytes and untracked path inventory remained stable across this audit.

**Limit:** this proves snapshot scope and provenance, not execution, acceptance or strict governance. Evidence assembly can legitimately add paths later; root should reconcile final publication scope. Companion JSON SHA-256: `f1950c38170aa352c8df6fe35ea2027cf4b14927a04c40ecf04a1e8b1e0fbcbe`.
