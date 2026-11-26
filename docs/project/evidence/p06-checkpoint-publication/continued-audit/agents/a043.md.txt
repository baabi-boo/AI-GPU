# A043 — Historical P02 acceptance artifact binding

## Decision

The live helper's changed digest correctly fails the existing artifact integrity check. Do **not** replace the recorded digest with the repaired helper's digest, remove the artifact, or weaken `check_project.py`.

Retaining the exact previously bound helper bytes and creating an explicitly corrected acceptance record is a valid, bounded preservation operation. It keeps the historical numerical execution bound to the same bytes and does not claim that it executed or qualified the repaired checkpoint implementation.

The parent selected a new `acceptance-retained-source.json` with a unique record ID and a single P02-A02 roadmap evidence-pointer update, while leaving `acceptance.json` byte-for-byte unchanged. I agree this meets policy. The existing path is also named by `ci/project/p03_operator_manifest.json:20` as `profile.arithmetic_evidence`; it can remain a clearly identified historical reference. No executable Python consumer of that field was found, and no P03 manifest or numerical contract change is needed.

This is a source/evidence review, not native qualification, an acceptance expansion, a human approval or a waiver.

## Observed identities

Reviewed repository HEAD: `a693d6f8828e4e10b5374db7fef8c727aa69d34e`. Concurrent launcher and documentation work was left untouched.

| Object | Bytes | SHA-256 |
|---|---:|---|
| Original canonical P02 acceptance record | 17,015 | `364f49da0eb495ffcd2ea9ff5a402396eab531db3422819a972ccb2f7be9396a` |
| `ci/project/p02_matrix.py` from exact base `858090410a992756808256ace90d36b9b3b88dd3` | 30,055 | `e65eca7ac42705f175c296165d9579389d7db8a2deb7542d6eded8337bc83c17` |
| Repaired live helper at observation | — | `c7544854b1fda853fad7c382e6e51605e812f5a377128fa6198f4da8662d7432` |

The old helper's SHA-256 exactly equals `acceptance.json.artifacts[2].sha256`. Recovering those bytes from base `8580904` establishes their retention identity; it does not relabel that base as the original native execution revision. Keep the acceptance record's original `source_revision`, command provenance and historical limitations unchanged.

The production diff against the base is confined to `_write_json`; it changes publication/cleanup behavior and leaves the numerical runner, selected data, configurations and comparison code untouched. The old native result therefore has not been shown invalid by this tooling repair, but it cannot qualify the new publication behavior. The new checkpoint regressions and selected revision's own qualification cover that separate development claim.

## Policy and schema basis

- `AGENTS.md`, project contract: preserve provenance; advance evidence rather than claims; do not weaken gates, change goldens or self-authorize waivers.
- `docs/project/acceptance.md`, evidence scope and acceptance procedure: retain exact tested source, commands, raw results and hash-checked artifacts; do not substitute a different tested revision or relabel unexecuted work as passing.
- `docs/project/evidence/README.md`, producing a record: changed artifacts require a corrected, reviewable record. Here the historical artifact bytes and expected digest remain unchanged; the canonical record is explicitly corrected to a retained location, and its prior bytes remain available.
- `ci/project/check_project.py`, `_artifact`: requires the canonical repository-relative artifact path and checks the named file's digest. It does not require executable source files to remain under `ci/project/` or require them to be live implementation files.
- `ci/project/check_project.py`, roadmap evidence processing: only referenced canonical records enter acceptance validation. A clearly labeled original-record snapshot can be retained without becoming a second active acceptance record or inventing a new pass.
- Existing `test_check_project.py` checks reject missing/tampered artifacts, invalid digests, traversal and escaping symlinks. No direct hard-coded P02 helper-path expectation was found in the Python project tests. Preserve these validators/tests unchanged.

## Precise selected amendment

1. Keep `docs/project/evidence/p02-wmma/acceptance.json` byte-for-byte unchanged at the length and SHA-256 above. This remains the original historical record; its descriptive P03 reference remains unchanged too.
2. Extract `ci/project/p02_matrix.py` from explicit base `858090410a992756808256ace90d36b9b3b88dd3` into a nonexecuted historical text artifact, for example `docs/project/evidence/p02-wmma/historical-source/p02_matrix.py.txt`. Preserve all bytes, licensing header and line endings. Assert 30,055 bytes and the existing `e65eca...` digest before using it.
3. Create `acceptance-retained-source.json` as a corrected location-binding record. Preserve original source revision, configuration, outcomes, commands, acceptance IDs and all existing artifact digests. Redirect only the helper artifact path to the retained text. Give the new record a unique `record_id`; append an explicit retention limitation and distinguish original numerical review from the actual advisory retention review. Do not describe the original numerical reviewer as having reviewed this new correction.
4. Change only the P02-A02 `record` reference in `docs/project/roadmap.json` to the new corrected record. Preserve every phase status, acceptance criterion, required level, dependency, entry condition and other evidence reference. The validator must see one active record for this acceptance rather than treating the original and correction as duplicate active records.
5. Add a separate retention record/note binding the original acceptance bytes, extracted helper bytes, old and new artifact locations, extraction base, corrected acceptance digest, purpose and actual independent review identity (`/root/a043_historical_acceptance_binding`, historical binding review only). Bind the original acceptance SHA-256 there, or as an additional artifact in the new corrected record. Avoid circular hashes. A short section in the packet README should distinguish the corrected canonical reference from the unchanged original and state that the repaired live helper is qualified separately.
6. Assert programmatically that the original record remains byte-identical and that the new record's semantic differences are limited to the declared unique ID, helper location, explicit retention limitation/review attribution and any separately declared original-record provenance artifact. Every original artifact digest and every original execution/source/outcome value must remain identical. Also verify the original compact evidence archive, inventory, summary, fixture/golden files and phase/acceptance states remain unchanged.
7. Have a separate reviewer inspect the concrete resulting correction and bindings, then run existing project and baseline metadata checks. The selected final revision still requires its own strict governance and retained-original replay. No new native pass follows from the metadata check.

This is a corrected, reviewable location binding with preserved originals. It does not suppress the original mismatch: record the mismatch and its cause in the retention note as the reason for correction.

## Alternative considered

A path-only amendment to the existing canonical acceptance record, paired with a byte-exact pre-amendment snapshot and separate retention identity, would also retain the same historical artifact bytes. The selected separate-record form makes the correction identity and unchanged original clearer. Its additional roadmap pointer update changes neither acceptance meaning nor phase state. The old P03 descriptive reference must be explained as historical, not silently presented as a newly qualified current-source record.

## Work performed and limits

Read-only inspection of policy, schema, relevant test definitions, references and the production diff; direct hashing of the original record and explicit-base helper bytes. No tests, builds, native execution, source/validator/acceptance edits, commits or pushes were performed. This report is the only file written by A043 and is outside the repository.
