# Directed native WGMMA unit evidence

This compact packet preserves the completed native-unit execution at source
`9006939aa123452b198bc0987e34aae8fab45fdd`, tree
`c815d75bcd13395618b7fbd9924bcedf6347c6c8`. All nine commands passed.
Eight groups accepted and committed **392 transactions** and checked
**3,072 arithmetic words**. Independent arithmetic and protocol reviews are
retained alongside the execution report.

This component does not by itself accept P02-A03 or complete P02. Full-processor
metadata ordering, matched SimX/native processor results and the applicable
timing comparison remain separate obligations.

## Files

- [Publication manifest](publication.json): source identity, executed packaging
  commands, observed counts, independent-review members and omissions.
- [Inventory](inventory.json): all 498 text-member identities, explicit selection
  and normalization policy.
- [Evidence bundle](evidence-bundle.json.gz): deterministic compressed JSON
  containing the selected reports, logs, source/build metadata and reviews.
- [Selection](selection.json): explicit completed-unit inputs; no processor
  matrix, tools directory or complete build tree is selected.
- [Packaging log](packaging.log): successful build and both verification modes.

## Integrity and scope

The 498 selected text members occupy 1,243,040 compressed bytes, below the unchanged
4 MiB cap. Verification checked all original and published member hashes, then
repeated published-only verification. The aggregate exporter source identity is
intentionally absent; the retained unit report and source snapshots identify the
actual tested revision.

Original and published hashes have different purposes. Embedded historical
hashes continue to identify original execution bytes. Literal workspace-path
normalization produces separately hashed published bytes; it does not rewrite
the embedded original digests.

The executable body is omitted, together with `.gitmodules` and two BHF include
files excluded by the unchanged text allowlist. Their hashes remain in retained
records. The packet contains 433 source bodies and 37 retained build text files,
including generated headers, compiler stamps and Verilator identity metadata.
The independent reviewers inspected the original retained packet before export;
their reports state the precise scope and limitations of that review.
