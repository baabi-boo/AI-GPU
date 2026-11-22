# W07 independent review of public replay test corrections

## Disposition

No F2/F3 defect was found in agent 41's bounded changed hunks in `ci/project/test_p06_counter_public_replay.py`. The earlier F2 stale-schema mutation finding is corrected: numeric mutations target schema 2 and assert that their input bytes changed. The earlier obsolete CP-field observation is corrected with current raw fields, while explicit unknown-field rejection remains separately exercised.

Reviewer: `/root/w07_replay_inventory_integration` (agent 40), read-only review at root's request. The reviewer did not author or edit the reviewed test file. This review is separate from the reviewer's own source-inventory reader integration; that integration still requires another independent reviewer.

Reviewed file SHA-256: `6d9c4c541a0e68acd021a3d2bf3ffb989ed4300b8339314e80551947498df6e0`. It matched before and after the independent probes. The baseline was `/workspace/scratch/98908dfa3444/w07-public-replay-integration-tests-before.py`, corresponding to the previously reviewed test bytes.

## Changed-hunk review

- `replace` now reads the existing targeted value and rejects a same-type equal replacement. This catches absent/obsolete field paths and no-op mutations while preserving intentional Boolean-versus-integer type corruptions.
- Retained-payload and normalized build-command mutations reject unchanged bytes/commands. These guards do not alter the producer, reader or golden expectations.
- The original-success assertion uses schema 2 and the exact per-mode check counts `1668`, `1176`, `1176`, `1173`, `1814`, matching the current raw-record contract in normal/immediate/delayed/cache/coherent order.
- Suppressed-DMA corruption now exercises all three words of each before/attempted/after payload. Each selected original or complemented word is nonzero, so replacing it with zero is a real mutation.
- CP mutations target `head_writeback_raw`, `tail_register_pair_raw`, `runtime_tail` and `retired`. The head's required raw value is zero; terminal tails exceed 64 because the current validator requires at least 22 retired commands and the exact cacheline accounting. The selected replacement values are therefore guaranteed changes. The old `head` insertion is gone, and unknown keys are still tested explicitly inside `cp_after`.
- Teardown mutations exercise both destruction rows, including reset generation. Both current reset generations are positive, both completed flags are true, both final tick counts are zero, and both generation labels differ from the selected corruptions.
- Raw duplicate-key, floating-point, nonfinite, prefix/trailing-line and repeated-record mutations all assert changed bytes. Numeric cases require exactly one canonical `"schema_version":2` token and replace it with `2.0`, `NaN` or `Infinity` before the strict parser rejection.
- The genuine-original intake function is byte-for-byte unchanged in the old and new AST source segments. It still requires the three exact intake fields, a safe sibling original ZIP filename, an external digest and revision, and a matching original ZIP digest. No synthetic success receipt or archive bypass was added.

## Independent execution evidence

Command, from the repository source root:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 /workspace/scratch/98908dfa3444/w07-public-replay-test-delta-review.py
```

Result: **9 methods passed, 103 subtests, 116 actual raw corruptions rejected, 0 failures, 0 errors, 0 skips**, in 1.337 seconds. The six actual replay-test mutation method bodies were invoked through a fresh minimal raw-log adapter. Three additional methods checked unchanged-value, unchanged-payload and unchanged-build-command rejection, including the Boolean/integer distinction and absent field path.

The adapter used explicitly synthetic raw-record unit fixtures. It did not construct a complete native archive or a report claiming successful native execution. It compared each changed raw log with its input and required the current raw parser to reject it. Filesystem opens, subprocess creation and `replay_archive` were guarded during the probes. Thus these checks resolve mutation validity and parser coverage only; they do not stand in for the original archive integration tests.

Artifacts:

- `/workspace/scratch/98908dfa3444/w07-public-replay-test-delta-review.py`
- `/workspace/scratch/98908dfa3444/w07-public-replay-test-delta-review.log`
- `/workspace/scratch/98908dfa3444/w07-public-replay-test-delta-review.json`

The JSON records every rejected mutation and the unchanged reviewed source digest. The 116 corruption checks exceed the 103 explicitly labelled unittest subtests because some method-level checks occur outside a `subTest` block; these are separate exact counts.

## Scope and limits

No repository file was edited in this review. No native execution, complete synthetic public success packet, receipt substitution, full discovery, commit or push occurred. The genuine corrected public original and its success-dependent replay methods were unavailable to this bounded review and remain a separately owned task. This review closes the stale-schema/no-op mutation concern in the changed test bytes; it does not establish that a public native run passed or approve the separately authored reader integration.
