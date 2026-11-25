# Agent 27 — independent directory cleanup review

## Scope and disposition

Read `BRIEF.md`, `agent-23.md`, repository `AGENTS.md`, relevant project status/gate context, the two `_directory` implementations, their production diffs, and the new directory cleanup regression. Reviewed source is the dirty working tree over HEAD `622662ad9cece6da4e3375be7e977dbe04cde862`, identified by the SHA-256 values below.

**The two `_directory` corrections pass this focused review.** Ownership transfers to the child before parent close. If parent close consumes its descriptor and then raises, cleanup closes the child, never retries the consumed parent number, and preserves the original exception even when child cleanup also raises. The existing real-descriptor regression was independently run: actual parent closure, exact-number `/dev/null` reuse, unrelated descriptor survival, child EBADF, and original exception identity all pass for both pack and encrypt. The sibling success/publication tests also pass. Encryption's existing ancestor-identity collection remains in place.

**One unresolved concrete F2 finding, high confidence:** at the coordinator's explicit follow-up request, independently probed `_package`'s newly added output descriptor lifetime. The `output_fd` is opened before `os.close(parent)` in an earlier `finally`; the outer `try/finally` that owns `output_fd` begins later at `stage = "inventory"`. A consumed parent-close error therefore escapes before output cleanup is established.

The real-fd probe calls `package_partial` with separate temporary source/workspace/output paths. It observes output fd **4**, consumes parent fd **3**, immediately opens `/dev/null` as fd **3**, and raises the same EIO instance. Original EIO and unrelated fd 3 survive, but fd 4 remains open and resolves to the created output directory. The probe explicitly closes leaked/unrelated descriptors afterward. The shared `_package` setup serves both public packaging routes; only the partial route was directly exercised by this reproduction. No native execution or age subprocess is needed to reach the defect.

## Validation

All commands ran from `/tmp/ai-gpu-ae456f837c05/AI-GPU` with `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`, `PYTHONPATH=ci/project`, and prepared CPython 3.12.14 at `/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`.

```sh
python3 -m unittest -v test_p06_directory_cleanup_review test_p06_qualified_warm_pack test_p06_qualified_warm_encrypt test_p06_pack_operational_failures test_p06_encrypt_operational_failures test_p06_encrypt_publication_review
```

**91 tests passed, zero skips, 4.570 seconds, exit 0.** These tests do not cover the newly discovered setup leak.

```sh
python3 /tmp/ai-gpu-ae456f837c05/notes/agent-27-package-setup-probe.py
```

**One test failed as expected, zero skips, 0.001 seconds, exit 1**, specifically asserting that the opened output fd must be released. Full retained output: `agent-27-package-setup-probe.log`. Probe SHA-256: `0e7b251e175c2784e7a551b3295e8e7a2fe404334c0a43d6c520ae0c4151d482`.

`git diff --check -- ci/project/p06_qualified_warm_pack.py ci/project/p06_qualified_warm_encrypt.py ci/project/test_p06_directory_cleanup_review.py`: exit 0.

## Reviewed source identities

| File | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_pack.py` | `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a` |
| `ci/project/p06_qualified_warm_encrypt.py` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `ci/project/test_p06_directory_cleanup_review.py` | `0ae6b592c82c81b7191280137c73a7f5109cded9f0fa5e377eb2315f30ab32aa` |

Hashes were unchanged at review completion. No repository files were edited; no commits or pushes were made. Outside-repository artifacts are this report, `agent-27.json`, `agent-27-package-setup-probe.py`, and its log.

## Remaining scope and next action

The coordinator was notified immediately and will assign a fresh implementer plus a separate reviewer for the setup-lifetime correction. Retain the failing regression and ensure the newly opened output descriptor is owned before parent-close failure can propagate, without retrying a consumed descriptor or replacing the original error. This report does not approve that future change.

Evidence is limited to host Python/filesystem fault injection and focused development tests. No native/hardware execution, performance measurement, cryptographic authentication, complete strict governance, fresh warm result, or phase acceptance is claimed. Full strict governance belongs to the coordinator on the final source tree.
