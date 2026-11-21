# Final P05 governance and publication preparation

The [review](review.json) records successful current metadata and local-reference
checks. It adds no native execution or acceptance decision. The actual qualified
implementation remains `e1420fd550f716df33a2556057b7086a03032cbe`, with P05-A01
accepted at simulated scope and P05 still in progress. A02/A03 remain unearned.

The project checker passed. A separate bounded check verified 16 documents,
538 local references, all 57 acceptance artifact hashes, the exact A01-only
roadmap delta, unchanged other phases, license, protected SVG and image embedding.
[Commands](commands.json) and [metadata details](metadata-links.json) retain
the actual invocation results and reviewed identities. Final receipt/ledger
files may be added afterward and require the primary agent's final scope check.

## Actual-object classification remains a final publication step

The [plan](classifier-plan.json) is explicitly **prepared, not run** for the
final candidate. The [frozen policy manifest](immutable-base.json) identifies
the exact classifier, path policy and review policy read from the audited base.
The first implementation's actual R2 result and independent conservative R3
reviews remain in the earlier development history.

After creating and fetching the real final candidate object, the primary agent
can run the read-only wrapper with its full commit ID and a fresh output path:

```sh
python3 -B docs/project/evidence/p05-python/final-governance/classify_candidate.py \
  --repo "$PWD" --head "$P05_FINAL_COMMIT" \
  --output /absolute/fresh/p05-final-classification
```

The wrapper verifies the commit and its ancestry, extracts the classifier and
policy from immutable Git objects, checks their fixed hashes, and classifies both
the full continuation and the final evidence/documentation delta. It writes
results without staging, creating commits, moving refs, publishing or granting
approval. The primary agent must compare the candidate tree with the reviewed
tree, inspect those actual results, check the current remote head and use a
non-force update with an expected SHA. Remote head/tree verification follows.

## Whitespace observations

The [diagnostic record](whitespace.json) preserves the nonzero complete-base
whitespace result. It identifies original receipt hard breaks/blank EOF and the
already reviewed, source-pinned `_bundle.py` EOF. The post-implementation tracked
documentation diff passed. Six new evidence text files retain whitespace from
the original hosted output, upstream license/CMake text and symbol dumps.
These are F0 observations. Their exact bytes, including spdlog's CRLF, are kept;
no product fix, rewritten historical observation or waiver is claimed.
