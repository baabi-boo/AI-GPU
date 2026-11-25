# Agent52 — publication invariants after final packaging correction

**Pass for the inspected snapshot.** Read-only audit of base `622662ad9cece6da4e3375be7e977dbe04cde862` plus current working changes; HEAD remains the base. Snapshot: **2026-11-25 13:09:03.545571–13:09:10.680399 UTC**. No repository edits, tests, builds, Git mutations, installations, deletions, or child agents. Only this report and companion JSON were written outside the repository.

## Frozen source and evidence identities

**23/23** publication-freeze records match current SHA-256, byte size, and permissions. The manifest SHA-256 is `6c90e8e2c097b1d8db3534835d4f8ae94c4f6dc2c20b1c59283342c0b1c2dbf8`. Its packet copy is identical.

The historical **22-file** freeze remains byte-identical: `714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb`. Comparing the manifests yields exactly one changed source, `p06_qualified_warm_pack.py`, and one addition, `test_p06_pack_final_cleanup.py`; no removal. The other 21 historical records remain current. Final pack SHA-256: `585341fd1a7734f06468d8ca25ad8d9f4dc2a08dc861111e98c94e3cf4028134`; new regression: `fe8a7835b51d132f286f5f3e453d873ac52408b7b0ab59f5c5eebd58de3484af`.

**69/69** measurement identities match current bytes, base blobs, and the warm proof's exact records. **5/5** frozen inputs match their manifest and base, including both proofs. The warm proof's base-proof and contract hash bindings match. All four manifest packet copies match their originals. Exact identities are retained in JSON.

## Raw Git and provenance scope

Independently hashed **7,700 base blobs** with raw Git blob framing: **7,688 unchanged, 12 expected modifications, zero missing**. All five unpopulated submodule Gitlinks and every index entry match the base. Git's raw diff agrees with the independent scan.

Protected bytes and Git modes remain unchanged: kernel 25; runtime 70; simulator 200; hardware 882, including RTL 415; native tests 1,418; configuration selection 470; VERSION; 25 baselines; 23 acceptance-named project files; 12 phase documents; both roadmaps; eight proof paths; 20 workflows; and all 4,007 existing evidence files. These overlapping counts use explicit JSON selectors; exhaustive hashing also covers every other base file.

The protected SVG, original README embedding, complete upstream-credit section, LICENSE, and selected license/notice files are preserved. All 22 scoped production/fixture/new-regression files retain Apache-2.0 SPDX headers.

## Regression and publication scope

AST comparison preserves all **5,029** existing test definitions across **304 modules**; old/current canonical AST hashes match. The existing fixture delta is exactly the three-line `Response.close()` addition. **15 new modules define 53 test methods/functions**. These are static counts, not collection or execution claims.

The snapshot contains **196 changed paths**: six production helpers, one old fixture, 15 new regressions, six documentation files, and **168 evidence files**; 184 additions remain untracked. No unexpected or ignored untracked files. All **7,705 index flags are H**; no skip-worktree/assume-unchanged flags, active local exclusions, sparse-checkout file, replacement refs, grafts, or configured hiding/diff hooks. Source bytes, changed-path inventory, HEAD, and index bytes stayed stable during inspection.

Since Agent45, operational source changed only in the final pack correction/new regression. Documentation bytes are unchanged; evidence has two ledger edits and 28 additions. Packet/docs assembly remains active: these counts describe this snapshot and do not claim final publication completeness, strict governance, native execution, performance, or phase acceptance.

Companion JSON SHA-256: `1811d88d3b4db8939414a96f798f269b18a8e1c0382d88b03d26b4c284463e7a`.
