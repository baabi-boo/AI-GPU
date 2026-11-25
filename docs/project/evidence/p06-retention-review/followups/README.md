# Directory replacement fixture correction after hosted governance

## Observed failure

The first published continuation was
[`0c32d04c5d37679bb0273f07a50bd26a2e21a5e8`](https://github.com/baabi-boo/AI-GPU/commit/0c32d04c5d37679bb0273f07a50bd26a2e21a5e8),
tree `e20c21c8aeeaa1751f49f43de3b38e7872bbcaa6`.
[Project Governance run 45575499141](https://github.com/baabi-boo/AI-GPU/actions/runs/45575499141),
attempt 1, executed all **5,114 tests in 2,311.191 seconds** and failed. The
original packet records 5,113 successful parent tests, one failed parent,
37,448 successful subtests and one failed directory subtest, with zero skips.
The two failure records belong to one canonical test:
`QualifiedWarmRestoreTests.test_changed_restored_bytes_and_unexpected_entries_are_detected`.

The directory subcase expected `RestoreError`, but none was raised. Its
subsequent incomplete-marker assertion also failed. Source, environment and
interpreter receipts remained stable; the full invocation completed and its
logs were not truncated. This is failed qualification evidence, not a passing
run or an environment waiver.

A40 independently retrieved and audited the original
[artifact 15006112807](https://github.com/baabi-boo/AI-GPU/actions/runs/45575499141/artifacts/15006112807):
**1,316,303 bytes**, SHA-256
`bc40f99327415fc753cf49749b6b4e75b3186d98ec218485f5aef505c735392d`.
The [original-receipt review](governance-failure-audit.md) and
[structured audit](governance-failure-audit.json) retain its actual outcome.

## Fixture defect and correction

The old fixture removed an empty directory with `rmdir()` and immediately
recreated it with `mkdir()`. It assumed that the replacement would have a
different device/inode tuple. Once the old directory is no longer referenced,
that tuple may be reused. The hosted failure did not record either tuple, so
the exact allocator event remains an inference. The uncontrolled fixture
precondition is independently visible in the source.

The reader/restore contract requires stopped writers and detects observed
identity, membership, metadata and byte changes. It does not claim to identify
every malicious concurrent replacement that leaves all observed invariants
unchanged. No production integrity defect was established by this failure.

The corrected test keeps a descriptor to the removed directory open through
verification and the incomplete-output checks. This keeps its inode allocated
while the replacement is created. An `ExitStack` closes the descriptor on all
context exits. The fixture captures both identities and checks that they differ
**outside** `restore_archive`, whose exception mapper could otherwise convert a
fixture assertion into the expected `RestoreError`. The directory subcase also
requires the exact `output-changed` code.

All four original mutations remain: changed file bytes, unexpected membership,
a symlink replacement and a directory replacement. Every case still requires
rejection and the private incomplete marker. Marker checks now sit within their
respective subtests, avoiding a redundant parent failure after a failed subtest.
No test is skipped, retried, removed or given a weaker accepted outcome. No
production source, resource limit, workflow, golden or phase gate changes.

## Source-scoped validation and review

Root ran the complete **19-test restore module once** under the prepared local
CPython 3.12.14 environment: **19 passed in 0.458 seconds**, zero failures,
errors or skips. The module retains exactly the same 19 method IDs. Its source
hashes were stable before and after the run. This is focused development
validation; the failed hosted run used CPython 3.12.3, and each revised provider
SHA requires its own complete strict invocation and original receipts.

- [Focused execution record](restore-module-validation.json) and its
  [original stderr](restore-module.stderr.txt) / [stdout](restore-module.stdout.txt).
- [A57 independent contract and test review](directory-fixture-review.md), with
  the [once-only held-descriptor probe](held-directory-probe.py) and
  [original result](held-directory-probe.json).
- [A35 independent test and fault-control review](independent-test-review.md)
  and [structured observations](independent-test-review.json).
- [Source identity follow-up](source-identities.json), which preserves the
  prior manifests and identifies the corrected test bytes separately.
- [Artifact index](artifact-index.json), binding retained follow-up evidence to
  its supplied original bytes.

The corrected test module is SHA-256
`9ef2cb211135a3b4f024056208492a9aef389823d452174c7bfdd8efcab15fb6`.
All production identities still match the earlier retained observations.
The original A01–A60 reports, 60-row ledger, A36 focused run and other historical
artifacts remain unchanged and retain their original source scopes. These are
follow-ups to existing assignments, not additional agents or a replacement of
failed evidence with a later pass. Qualification of the current published SHA
comes from that SHA's own completed Actions run and original receipts.
