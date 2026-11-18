# P03 exact-tree publication mapping

The executor could read the public repository but had no HTTPS Git write
credentials. The authorized connected GitHub account supplied the Git database
API publication route. Each uploaded blob and each reconstructed tree was
checked against its original local Git object ID before creating commits.

The API assigns commit metadata, so its commit IDs differ. **The trees are
identical; the tested revision remains the original local revision.** No test,
acceptance source identity, archive, index or existing review was relabelled.
[publication-map.json](publication-map.json) retains the observed IDs, verified
parents/trees, exact original commit bodies and all uploaded blob identities.

| Original local commit | Identical published tree commit | Scope |
|---|---|---|
| `b066586448823ffcc1ef406da5490f897fc4e3f2` | [063cac2](https://github.com/baabi-boo/AI-GPU/commit/063cac2bb4ac3247c575d2fbbab0f8d6b3f15ac9) | Initial implementation |
| `319ad63532cee17ae88fa75757a5ac87ed5c6a77` | [1c1852f](https://github.com/baabi-boo/AI-GPU/commit/1c1852f1a5c425858e6bd31404e41512c7d797ca) | Exact source used for formal qualification |
| `54e1a4c920d8bd848c4524a0a5f87de6b68f23aa` | [5b964eb](https://github.com/baabi-boo/AI-GPU/commit/5b964ebef8d00a56e092639d3077bd35137d1c6f) | Reviewed acceptance and documentation closeout |

The final publication adds only this mapping, its explanation and independent
review above the reviewed closeout. The coordinator updates `master` once with
the expected previous head and `force=false`, then checks the remote head.
No existing remote history is replaced. The source-map and final-delivery
receipts continue to describe the exact reviewed closeout tree above.

## Reconstruct the original tested commit

After fetching the published `master`, all necessary trees and blobs are
reachable through the three API commits. From the repository root, restore the
original commit objects with the retained raw bodies:

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess

path = Path('docs/project/evidence/p03-managed-matmul/publication-map.json')
for row in json.loads(path.read_text())['mappings']:
    body = row['raw_local_commit_utf8'].encode('utf-8')
    framed = b'commit ' + str(len(body)).encode('ascii') + b'\0' + body
    assert hashlib.sha1(framed).hexdigest() == row['local_sha']
    restored = subprocess.check_output(
        ['git', 'hash-object', '-t', 'commit', '-w', '--stdin'], input=body
    ).decode().strip()
    assert restored == row['local_sha']
    observed_tree = subprocess.check_output(
        ['git', 'rev-parse', restored + '^{tree}'], text=True
    ).strip()
    assert observed_tree == row['local_tree'] == row['api_tree']
PY
```

The original tested commit can then be checked out in a separate worktree using
`319ad63532cee17ae88fa75757a5ac87ed5c6a77`, with the pinned submodules and identified
tool/dependency inputs from the [qualification packet](README.md). Reconstructing
Git objects does not claim a new execution or change the acceptance scope.
