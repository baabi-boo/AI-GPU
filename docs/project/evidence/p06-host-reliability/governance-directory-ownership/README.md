# Governance archive directory ownership

The [independent archive review](a042.md) found a raw directory descriptor leak
when the initial root-directory identity check raises. The [retained original
source](archive-before.py) comes from published `4c9c612ba17e8b69b29083ad9743fe0e1710f0bc`;
its SHA-256 is `cf9f721c3e54282113b81b97b7269a34b1ad50720a46bcc09832e71bbf76f65a`.

The repair puts that first identity check within the directory walk's existing
ownership region and preserves its primary failure if cleanup also raises.
Directory traversal, path constraints, original/source identity verification,
ZIP parsing and all archive limits remain unchanged. These are synthetic host
fault checks, not native execution or a full governance qualification.

## Focused checks and independent review

The [retained focused receipt](a044-evidence/receipt.json) and
[execution log](a044-evidence/focused.log) record **40 passing tests**, zero
failures, errors or skips, and unchanged hashes for the reader and all three
selected test modules. The [implementation report](a044.md) explains the seven
new isolated methods; the [independent effective-R2 review](a045.md) verified the
final source, tests and retained log hashes without claiming another execution.

Five old-source controls reproduce missing-close, descriptor-exhaustion and
primary-error replacement failures. The original nested-directory success
control passes. The receipt records their exact commands, exit status and log
identities. The additional source copy inside the receipt directory is the
same original as the top-level source snapshot.

Retained command paths describe the historical temporary workspace. From the
repository root, the final focused checks can be run without that layout:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B -m unittest -v test_governance_replay_archive test_governance_replay_archive_controls test_governance_directory_ownership
```

The source and tests are unchanged from the independently reviewed hashes.
A successful focused run does not qualify full governance or establish native
admission; the selected published revision still needs its own strict original
and independent replay.

## Final discovery and preservation

The [final source receipt](a047-validation/receipt.json) records one canonical
discovery-only invocation: **5,575 unique IDs**, exactly seven additions over
the encryption follow-up's 5,568, with no removals, duplicates or changed order
among existing IDs. No test bodies executed. All 549 Python source files stayed
unchanged through discovery and the metadata checks. The [review](a047.md)
and [preservation record](a047-validation/preservation.json) confirm all 69
measurement identities, both frozen proofs, 21 dependency descriptors, 32
original acceptance records including 18 active records, 25 baseline goldens,
roadmap and protected SVG/README embedding are preserved against the starting
revision. Project and baseline-packet checks and whitespace validation passed.

The [packet manifest](manifest.json) binds the retained source, logs, reports
and receipts. Their original bytes are preserved. Discovery is not a completed
strict test execution and cannot substitute for the published revision's CI.
