# Agent 030: independent review of checkpoint test corrections

## Scope and conclusion

Reviewed only the changes from `93bb3f0342eff0b469a0da06cb067916af7c539e`
to `a693d6f8828e4e10b5374db7fef8c727aa69d34e` in
`ci/project/test_checkpoint_ownership.py` and
`ci/project/test_p06_checkpoint_input_recovery.py`, with their surrounding
test code and the A021, A022, and A024 reports. Read the root `AGENTS.md`.
The checkout HEAD matched the requested revision. Its preexisting untracked
publication audit was left untouched.

**No concrete unresolved flaw found in the two corrections.** The changes
address A021's failure-path descriptor leakage and A022's false-claim
assertion gap without weakening the existing assertions.

## Descriptor cleanup

In `test_checkpoint_ownership.py`, the changed method records each opened
descriptor together with its device/inode identity. The exact injected
exception assertion, expected descriptor count, `assert_closed` checks,
previous-content assertion, and temporary-file assertion remain before the
fallback cleanup.

The `finally` covers both the writer invocation and the postconditions. Thus,
if a deliberately regressed writer leaves descriptors live, `assert_closed`
still raises; cleanup then releases any still-owned descriptors and does not
catch or return over that assertion failure. Both patches have already exited
before cleanup runs, and cleanup uses the saved real `os.close`.

A descriptor reused for an unrelated object with a different device/inode
does not pass the identity comparison and is left open. Already-closed
descriptors produce the expressly accepted `EBADF`; other cleanup OS errors
remain visible. This matches the two failure-isolation modes documented by
A024: suppressed writer closes leave failing subtests but no owned leaks,
while sentinel reuse leaves the unrelated descriptors intact.

## Required false claims

In `test_p06_checkpoint_input_recovery.py`, the new loop explicitly indexes
every field in `inputs.dependency.FALSE_CLAIMS` and the five additional named
claims. A missing key now fails the test through `KeyError`, and
`assertIs(result[field], False, field)` rejects `True`, `0`, `1`, strings,
`None`, and other non-identical substitutes. The existing scan of additional
Boolean fields remains. `network_acquisition` retains its separate assertion
against the fixture's modeled fetch observations.

## Verification boundary

This was an independent static review. No tests, negative probes, builds,
commits, or pushes were run. The two current SHA-256 digests exactly match
A024's reported tested source identities:

- Ownership: `7f18c215bcfb1b8cd69bbbfaad55e54fee651ef5b2d843ce05c761cfb17ff127`
- Input recovery: `ed1a9315c42883b4b3c9e0405e00424d153357a9b352dfbff599d16e961f9bbc`

`git diff --check 93bb3f0..a693d6f -- ci/project/test_checkpoint_ownership.py ci/project/test_p06_checkpoint_input_recovery.py`
returned exit 0. A024's execution outcomes are attributed to its report,
not represented as rerun by this reviewer. This review adds no native,
performance, or strict governance qualification claim.
