# Archive stream ownership and resident-workspace fault coverage

This continuation starts from published `master`
`81d7a35c641f3a969c23c8e604f7468a4d88644a`. The
[evidence packet](evidence/p06-archive-ownership/README.md) retains its source
identities, host checks, independent reviews and actual agent assignments.

## Reproduced defects and repairs

The private qualified-warm packer opened raw input and output descriptors
before wrapping them in Python streams. Real CPython audit-hook rejection of
`os.fdopen` left a descriptor open in both paths. The reader now retains explicit
raw-descriptor ownership; the output helper owns the descriptor throughout its
context. Stream construction cannot silently transfer or abandon that owner.
Cleanup attempts the stream, raw descriptor and directory independently, never
retries a potentially consumed descriptor, and preserves an existing primary
failure. A cleanup error after otherwise successful work still fails the call.
Created partial output remains available under the existing retention policy.

Independent review found a related defect in the governance archive input
context. A raw-descriptor close failure could skip parent-directory cleanup;
stream and final-directory close errors could also replace the original
construction, body or identity-validation failure. The repaired input context
owns its stream, raw descriptor, initial directory and final verification
directory separately, attempts every close once, and retains the primary error.
The archive grammar, bounds, identity checks and accepted evidence are unchanged.

## Resident workspace coverage

The runtime review found no reproduced production defect in the inspected
serial/workspace paths. It identified a host-test gap: the reusable policy's
three address queries during submission were not faulted after successful
workspace creation. Added cases verify no work is enqueued, resident buffers
remain owned, the operation lease is released, and a subsequent healthy
submission can reuse the workspace. Production runtime bytes are unchanged.

## Native trace ownership follow-up

A separate source review found outstanding SimX traces lack a complete owner
during exceptional teardown. A reduced host probe using production trace,
allocator and simulator-framework headers retained 65 shared instruction
witnesses after reproducing the raw-pointer ownership pattern; explicit trace
destruction released them. It did not execute native Core or the public runtime.
Copied micro-operations, dispatch splits, LSU fragments and deferred stores make
cleanup of the Core pending list alone insufficient.

The affected native sources overlap the frozen experiment. No native repair or
leak-free qualification is claimed. A future change needs an owner covering all
allocation sites, independent review, failure/lifetime tests, native repeated
fault validation and a separately reviewed source-qualification decision.

## Evidence boundaries and next action

The recorded focused tests establish host behavior at their named source
identities. They do not replace the selected published revision's complete
strict-governance invocation and independent original replay. The starting
revision's CI results remain historical evidence and do not qualify these edits.

All 69 measurement sources, 21 dependency descriptors, source proofs, golden
data and existing acceptance decisions are preserved. The qualified warm
experiment remains unstarted, with its fixed population of 24 processes,
792 launches and 25,344 checked FP32 words. It still requires exact private
control delivery, the intended public age recipient, successful governance
admission, and a runner with 15 GiB free disk and 4 GiB available memory.
P06/P06-T01 remain `in_progress`; P06-A02/A03 and P01 vendor integration remain
open. Continue with the [qualified warm handoff](p06-qualified-warm-handoff.md).
