# Agent 010 independent checkpoint publication review

**Result: no blocking findings.** No concrete F2/F3 defect found. Confidence: high for the inspected supported Linux publication paths. Evidence type: static-proof (production/control-flow inspection); test sources were inspected, not executed by this reviewer.

## Scope and policy

Reviewed every production hunk in `858090410a992756808256ace90d36b9b3b88dd3..ba88572af0bea1e355af08038abcc1f62773a438`: `ci/project/p02_matrix.py:92-145` and all of `docs/designs/checkpoint_publication_v1.md`. Read `AGENTS.md`, `docs/review/code-review-policy.md`, relevant project status/roadmap/backlog/acceptance material, the three requested test modules, and relevant P06 caller closeout paths. No source changes, commits, pushes, or test executions.

## Findings and evidence

- **Original exception and committed state:** serialization/size validation precede filesystem operations. Write, flush, fsync, stream-close, ownership-check, and precommit replacement failures enter one cleanup path; the destination is replaced only after complete writing and synchronization. Cleanup exceptions cannot replace an earlier exception (`p02_matrix.py:119-145`). A successful replacement is retained when raw descriptor cleanup subsequently fails (`117-118`, `128-143`).
- **Descriptor lifetime:** `fdopen(..., closefd=False)` leaves ownership with the writer. The file descriptor remains open during ownership comparison and unlink, preventing inode reuse during that interval. Each raw descriptor receives one close attempt, including fdopen failures, without retrying a possibly reused descriptor number (`103-108`, `128-143`).
- **Foreign entries and directory anchoring:** exclusive creation refuses preexisting temporary entries. Both identity observations use no-follow directory-relative stat; cleanup only removes a matching owned inode. Create/stat/unlink/replace use the original directory descriptor, so a renamed/replaced pathname does not redirect cleanup or publication (`95-117`, `128-140`).
- **Scope remains bounded:** production changes are confined to the shared writer. No automatic checkpoint retry, child relaunch, receipt schema, resource gate, measurement population, golden data, or performance predicate changes occur. Existing caller finalization performs a distinct later write and retains failure accounting. The design accurately scopes this behavior and the host-only evidence.

## Limitations

The requested tests were reviewed, not rerun; this review does not establish passing execution or strict governance qualification. `test_checkpoint_ownership.py` was untracked in the observed working tree and is supplemental source evidence, not part of commit `ba88572`. No concrete suspected defect justified a reproducer. The documented limits remain: cleanup is best effort before trustworthy identity or after further failures, identity checks do not lock out concurrent writers, and directory metadata is not fsynced for crash durability. No GPU or performance acceptance is implied.
