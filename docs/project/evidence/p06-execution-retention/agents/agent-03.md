# Agent 03 — qualified warm packaging operational audit

Base: `622662ad9cece6da4e3375be7e977dbe04cde862`. Read `AGENTS.md`, current phase/status/backlog/acceptance/resource/review guidance, the automation contract, operator retention guidance, packaging implementation and existing interruption/recovery controls. No commits, network acquisition, native execution, proof edits or acceptance changes.

## Finding and reproduction

**F2, high confidence, executable reproduction:** the new output directory was not identity-bound. Renaming the newly created empty output directory during initial evidence inventory and recreating its pathname at mode 0755 caused baseline `package_partial` to return `packaging_passed=true`, put the ZIP and success receipt in the replacement directory, and leave the originally created private directory empty. This is a concrete pathname replacement failure; no malicious-writer isolation claim is made. It also applies to complete packaging.

`agent-03-reproduction.json` records an execution of the exact baseline helper retrieved read-only with `git show 622662ad9cece6da4e3375be7e977dbe04cde862:ci/project/p06_qualified_warm_pack.py` and the changed helper against this same small stopped-attempt fixture. Baseline passed despite changed output identity; changed code raises `ValueError("packaging output directory changed")`, leaves the replacement untouched, and retains a failure receipt in the originally opened directory.

## Changes (only assigned files)

- `ci/project/p06_qualified_warm_pack.py`: hold the initially opened output directory descriptor and device/inode/mode observation; recheck after inventory, copy, ZIP verification and publication. Recovery observes owned files relative to that descriptor, uses anchored withdrawal when the pathname changed, hashes retained bytes through that descriptor, and writes the private failure receipt there. Always close the descriptor.
- New `ci/project/test_p06_pack_operational_failures.py`: four focused tests, including complete and partial initial replacement, copied-byte retention after replacement, replacement by another directory or a symlink after final receipt publication, and directory permission change. Unrelated replacement-directory files survive; owned success names are withdrawn; source bytes remain unchanged.

Existing evidence schemas, limits, archive names, public APIs, source/proof/golden assets and acceptance predicates remain unchanged. Internal file helpers gain an optional directory descriptor used only by recovery.

## Validation actually run

From the source root:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin python3 -B -m unittest discover -s ci/project -p 'test_p06*pack*.py' -v
```

Final retained run: **37 tests passed in 2.237 seconds**, zero failures/errors/skips, including all 33 existing packaging tests. Full log: `agent-03-tests.log`. `git diff --check` passed. The baseline/changed standalone reproduction also completed successfully. Reviewed existing controls cover writer-state/cleanup checks, malformed partial retention, source identities, archive corruption, limits, no-clobber collisions and interruption recovery; this audit found no additional justified change in those areas.

## SHA-256 identities

| File | SHA-256 |
|---|---|
| Baseline `ci/project/p06_qualified_warm_pack.py` | `5a7bf6f435126f20e8a6c1c91ad49c9a65b96c568a238a70dcb0b78d83201b99` |
| Changed `ci/project/p06_qualified_warm_pack.py` | `0e8f19e49d1f05b686eb904cc5b840eb8968c5f6ec60cf8d44c64e0ad4108349` |
| New `ci/project/test_p06_pack_operational_failures.py` | `a7e93f6deb807c6cea46816c822cb2740b16ddba6d8ab892057bc18582fbe372` |
| Unchanged `ci/project/test_p06_qualified_warm_pack.py` | `290a67b637f5507e97f9bd5f073864edc47a179943e5ccd95493d01f5c754a6b` |
| Reviewed `ci/project/p06_qualified_warm_run.py` | `7108581a9317f4dc22741975173e8fd7dd6bfcbfacbd80ac35e30622320b9337` |
| Reviewed `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |
| `agent-03-tests.log` | `e35f84b690d719e42256dba476716f6b85e761ca05731089f6869d98593cbf5e` |
| `agent-03-reproduction.json` | `5fd31686f4b21e778c332b0da0903c29da5d5fbc812a7fc2bd7e4ab29754eb8d` |

## Limits and next action

These are host fixtures, not native evidence or full strict governance. Repeated directory checks observe replacement; they do not exclude hostile same-user changes between observations or establish a multi-file crash transaction. Recovery remains best effort. Root should independently review the changed hunks, consolidate focused evidence, and run the required exact-revision governance gate before publication/dispatch. Fresh qualified warm execution remains unstarted.
