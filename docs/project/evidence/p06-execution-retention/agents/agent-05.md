# Agent 05 — encryption publication path identity

## Scope and actual work

Reviewed `AGENTS.md`, task brief, current project status/backlog/roadmap and acceptance policy, retention contract, the complete streaming encryption implementation and existing encryption tests. Base revision: `622662ad9cece6da4e3375be7e977dbe04cde862`. Other agents' working changes were present and left untouched. No commits.

Owned changes only:

- `ci/project/p06_qualified_warm_encrypt.py`
- New `ci/project/test_p06_encrypt_operational_failures.py`

## Reproduced defect

The wrapper retained output and private directory descriptors, but never revalidated their named ancestor chains before publication. Its source chain was captured but not rebound to the later inventory. Renaming/replacing a selected source, output, private directory or output parent after final inventory therefore returned success, including when the requested output name was absent, a different directory or a symlink. Renaming during publication directory fsync also committed success at the displaced directory. Replacing the source before the first inventory encrypted the replacement and returned success.

The initial focused run against unchanged production code ran four methods in 0.620 s: 17 fault cases failed because the expected exception was **not raised**; the committed-cleanup interruption control passed. These are deterministic filesystem operations at real orchestration boundaries using the existing explicit synthetic age subprocess; they are not cryptographic or native evidence.

## Correction

Added one bounded helper that opens each full named directory chain with the existing no-follow traversal and compares original device/inode identities. Source, public output and private output are checked after initial inventory, before linking public files, after publication fsync but before commit, and after private cleanup before success returns. Output/private expected chains include the originally opened parent chain, so replacing an ancestor while restoring the original leaf directories is also rejected.

Existing descriptor-relative rollback and commit ordering are unchanged. Precommit failures withdraw only owned public links and retain private ciphertext. Postcommit path drift reports failure and preserves the already committed pair. KeyboardInterrupt after deleting the private ciphertext and private summary cannot withdraw the last public ciphertext. No format, recipient, native admission, proof, gate or resource-limit changes.

## Validation

Command from source root:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PYTHONPATH=ci/project /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -m unittest -v test_p06_encrypt_operational_failures test_p06_qualified_warm_encrypt
```

Final result: **51 tests passed in 3.794 s**, zero failures/errors/skips. Six new test methods cover 21 operational scenarios, including replacement by absence/directory/symlink, preinventory source rebinding, during-publication replacement, unchanged leaf identity under a new ancestor, postcommit drift, and interruption after the final private-link cleanup. Existing rollback, collision, process bounds, privacy and private-ciphertext-loss checks all passed. Exact output: `/tmp/ai-gpu-ae456f837c05/notes/agent-05-tests.log`. `git diff --check` passed for the owned files.

Final SHA-256:

| File | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_encrypt.py` | `015ef01b1418ef5ef5328859c905854c928ab7c996aba9352603383ef648ca24` |
| `ci/project/test_p06_encrypt_operational_failures.py` | `5804c519149e3131c6183286c3c599d1b27f9849a4139d24765c311691169e88` |
| Reviewed, unchanged `ci/project/test_p06_qualified_warm_encrypt.py` | `10a104f429e47584339e3bcc0cf77ed6bf3ad13b054b1233de7253c0d8323b4c` |

## Limits and next action

Observed identity changes fail closed; this is not exclusion of malicious concurrent same-user mutation, an atomic multi-file transaction or guaranteed recovery after abrupt termination/storage failure. No real age roundtrip, GPU run, strict governance qualification or acceptance was performed. The native warm experiment remains unstarted. Independent review should inspect the four check boundaries and confirm unchanged cleanup ordering; root owns final frozen-source strict qualification and publication.
