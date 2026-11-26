# Verified encryption-reader ownership repair

This follow-up starts from published `4c9c612ba17e8b69b29083ad9743fe0e1710f0bc`.
The [independent discovery](a034.md) reproduced a raw source descriptor leak
when stream construction raises an ordinary exception or cancellation.
The [retained probe](a034-probe.py) and [exact original source](a034-encrypt-before.py)
preserve that control. The original source SHA-256 is
`95ac65f43e09752d4df6286acaf4e1ef79ff81b7528770ffda1dd8c471cda5e8`.

The changed helper owns the source descriptor explicitly, wraps the stream with
`closefd=False`, and drains each owned resource once. Construction and failed
read scopes preserve their original error; successful scopes still surface
cleanup failures. Source identity, limits, hashes, encryption framing and
publication rules are unchanged.

Focused development checks do not qualify a complete revision or execute the
native warm experiment. The selected final revision requires its own strict
governance original and independent replay before native admission.

## Final focused verification

The [combined focused receipt](a039-validation/receipt.json) records **73 unique
tests and 211 successful subtests**, with zero failures, errors, skips, expected
failures or unexpected successes. Its [executed IDs](a039-validation/focused-result.json),
[source identities](a039-validation/source-before.json),
[test log](a039-validation/focused-tests.log) and [counting harness](a039-run.py)
are retained. All eight selected source/test files remained byte-identical
through the run. Project metadata, baseline-packet metadata and whitespace
checks each passed. These checks cover the changed source identified in the
receipt, before publication, and are separate from full strict governance.

The [implementation report](a036.md), [regression report](a037.md) and
[independent effective-R2 review](a038.md) record the repair and its limits.
The eight new test methods run 54 isolated child probes and 52 subtests.
The [same-ID old-source controls](a037-negative-summary.json) produce 51 assertion
failures, zero errors and zero skips, while normal-read and real-wrapper controls
pass. Their [original log](a037-negative.log.gz) is stored as lossless gzip;
the [identity record](a037-negative.identity.json) binds the unchanged decompressed
bytes. The [control driver](a037-negative-controls.py) and independent
[error-precedence probe](a038-primary-error-probe.py) preserve reproducibility.

The independent reviewer verified all 69 frozen measurement hashes and unchanged
read/verify logic, constants and tar structure. No real encryption, private-input
access, native execution, performance acceptance or phase completion is claimed.

Canonical discovery, performed without running test bodies, collected **5,568
unique IDs**: the prior 5,560 plus exactly eight new methods, with no removals,
duplicates or changed relative order among existing IDs. The discovery records
are retained in the [validation directory](a039-validation/).

## Replaying the focused controls

Retained reports and runners describe the original temporary workspace. Their
`../reports` paths and absolute workspace paths are historical invocation
records, not paths relative to this published packet. From the repository root,
the current eight-method regression module can be run directly:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B -m unittest test_p06_encrypt_reader_ownership
```

To run those same IDs against the retained original source without recreating
the historical directory layout, use the following command. Its expected result
is exit status 1, 51 assertion failures, zero errors and zero skips; it deliberately
tests the unrepaired source. Child fixtures remain synthetic and temporary.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B - <<'CONTROL'
from pathlib import Path
import unittest
import test_p06_encrypt_reader_ownership as tests

tests.SOURCE = Path(
    "docs/project/evidence/p06-host-reliability/"
    "encrypt-reader-ownership/a034-encrypt-before.py"
).resolve()
suite = unittest.defaultTestLoader.loadTestsFromModule(tests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
CONTROL
```

The [packet manifest](manifest.json) binds retained files by SHA-256. Where a
prose report had trailing blank lines, only those terminal blank lines were
removed; its original hash is recorded alongside the retained hash. Original
execution logs and source snapshots are preserved byte-for-byte.
