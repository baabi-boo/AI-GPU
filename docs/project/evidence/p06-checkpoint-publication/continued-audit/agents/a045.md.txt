# A045 — Independent historical P02 reference review

## Disposition

No blocking defect found in the concrete source-retention correction. The implementation preserves the historical P02 execution and its exact artifact digest while giving the corrected location binding a separate record identity. It does not substitute the repaired live helper for the source associated with the old numerical result.

This review is independent of the root-authored correction and the A043 design recommendation. It is advisory source/evidence review, not a new native acceptance, human approval or waiver.

## Reviewed source

Repository: `/tmp/ai-gpu-2bfab0261c05/repo`.
Observed HEAD: `a693d6f8828e4e10b5374db7fef8c727aa69d34e`, with the uncommitted correction and concurrent unrelated launcher/documentation work.
Comparison base: `858090410a992756808256ace90d36b9b3b88dd3`.

The reviewed files are the new `docs/project/evidence/p02-wmma/acceptance-retained-source.json`, `source-retention.json`, and `retained-source/p02_matrix.py.txt`, the packet README change, and the P02-A02 evidence-pointer change in `docs/project/roadmap.json`. The unchanged original acceptance record, policy, and validator were also inspected. Per-file hashes, byte lengths and the semantic roadmap delta are retained in `a045-reference-assertions.json`.

## Verified preservation

A single read-only Python assertion invocation passed **28 assertions**. These are metadata/content assertions, not additional unittest or native-execution counts.

- The original `acceptance.json` is byte-identical to the exact base: **17,015 bytes**, SHA-256 `364f49da0eb495ffcd2ea9ff5a402396eab531db3422819a972ccb2f7be9396a`.
- The retained helper is byte-identical to `git show 858090410a992756808256ace90d36b9b3b88dd3:ci/project/p02_matrix.py`: **30,055 bytes**, SHA-256 `e65eca7ac42705f175c296165d9579389d7db8a2deb7542d6eded8337bc83c17`. That digest exactly equals the original acceptance artifact digest. This retrieval establishes retention identity; it does not identify base8580904 as the original native execution revision.
- The repaired live helper remains distinct from the retained historical bytes. No old expected digest was replaced by the repaired implementation's digest.
- The corrected record has the same field population. Only four top-level values differ: `record_id`, `artifacts`, `limitations`, and `reviewer`. Every other value, including source revision, configuration, outcome, evidence level, numerical scope, acceptance IDs, commands and exit codes, is identical to the original.
- Every original artifact digest and artifact order is preserved. Only the helper path redirects to the historical text artifact. The sole appended artifact binds the separate source-retention manifest by its actual SHA-256.
- All old limitations remain an exact prefix, followed by one explicit retention limitation that makes no new native-execution or repaired-helper qualification claim. The original numerical reviewer text remains intact and is followed by a separately named advisory retention reviewer.
- The retention manifest correctly binds the original acceptance record, original helper path/digest, retained helper bytes, and exact retrieval command. Its `new_execution_claimed` field is exactly false.
- The complete roadmap semantic diff contains only `/phases/2/evidence/1/record`, changing P02-A02's evidence path from the original acceptance record to the corrected record. Every phase state, acceptance criterion, required level, dependency and other evidence reference is unchanged.
- The existing project validator, acceptance policy, evidence policy, P03 manifest, original P02 summary, inventory and compact evidence archive are byte-identical to the base.
- The existing unchanged `_validate_report` validator accepts the concrete corrected record and actual artifact hashes with **zero errors**. All nine hashed review-input files remained unchanged during the assertion invocation.

## Documentation and scope

The packet README clearly distinguishes the unchanged original acceptance record from the corrected retained-helper reference and states that this maintenance adds no native execution and does not qualify the changed helper. The old P03 manifest reference remains historical, without changing that manifest's numerical contract or bytes.

This satisfies the evidence policy's requirement for a corrected, reviewable record while preserving tested revision, commands, outcomes and raw historical identities. The root's checkpoint tests and the selected published revision's own governance remain separate obligations for the changed implementation.

No tests beyond the described read-only assertion invocation, full suites, builds, native work, repository edits, commits or pushes were performed. This report and its compact assertion JSON are the only outputs of A045, both outside the repository.
