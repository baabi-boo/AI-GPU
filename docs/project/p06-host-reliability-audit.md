# Host preparation and CI completion reliability

## Scope and findings

This continuation starts from published `master`
`30b2e8ca69fba47646392c0cf6650cbb75155843`. Independent provider observation
confirmed all 15 workflows and all 43 main-CI jobs successful at that revision.
The two long SimX regressions completed with 44 RV64 and 54 RV32 cases passing.
Their successful job logs nevertheless exposed a checkout-cleanup error, which
the source audit reproduced using small local Git repositories.

The implementation addresses three concrete host-side defects:

1. **Cached submodule metadata.** Main-CI test cells and Apptainer smoke restored
   a `third_party` cache containing submodule gitfiles without first creating
   their referenced repositories under the checkout's `.git/modules` directory.
   Recursive Git traversal then failed with exit 128. Both consumers now perform
   recursive checkout before cache restoration, matching the other shared-action
   consumers. Late initialization after restoring the broken gitfiles did not
   repair the reproduced failure. Cache keys, P04 preparation, test selection,
   permissions and required numerical/performance checks are unchanged.
2. **Incomplete CI treated as success.** The aggregate `complete` job previously
   rejected only the literal `failure` result. Cancelled prerequisites and the
   resulting skipped execution could therefore receive a successful aggregate
   check. The gate now requires a successful plan and either all required jobs
   successful (`run=true`) or all downstream jobs skipped after an explicit
   empty plan (`run=false`). Missing, unknown and inconsistent states fail.
   Provider values enter through environment variables, not executable shell
   interpolation. This strengthens the existing required-job boundary.
3. **Bundle-reader descriptor leaks.** The installed Python bundle reader and
   its packaging producer opened a raw file descriptor before wrapping it in
   a Python stream. A stream-construction exception could leave the descriptor
   open. A real CPython audit hook reproduced repeated leaks in both readers.
   Each reader now owns its raw descriptor through `finally` and uses a stream
   with `closefd=False`. Bounds, hashes, same-handle checks, exception conversion,
   sink behavior, manifest schemas and supported numerical operations remain
   unchanged.

## Verification and limits

The [evidence packet](evidence/p06-host-reliability/README.md) records the actual
independent assignments, focused checks, baseline failures and publication
observations. Development checks exercise local Git repositories, actual Bash
gate execution, real file descriptors and subprocess-isolated Python audit hooks.
They do not use a native GPU or substitute for full strict governance.

Neither changed Python reader is one of the 69 frozen measurement sources.
Those source bytes, the 21 dependency descriptors, proofs, golden data, accepted
historical records and the frozen warm population remain unchanged. The active
P05-A01 acceptance already refers to retained historical bundle-reader source;
old execution is not rebound to this repair. Updated bundle source identities
follow the existing producer's normal inventory calculation.

The code changes do not execute the qualified warm experiment or establish
performance improvement. P06/P06-T01 remain `in_progress`, P06-A02/A03 remain
open, and P01 vendor integration remains blocked.

## Next bounded action

Use the selected published revision's own successful strict-governance original
and independent replay. Verify the exact historical private control archive and
the intended public age recipient, then execute the unchanged 24-process,
792-launch, 25,344-word qualified warm attempt on a runner meeting the 15 GiB
free-disk and 4 GiB available-memory gates. Those private inputs were not
provided to this continuation, and the temporary development checkout does not
meet the native disk reserve. Preserve complete or explicitly partial originals
through the existing encrypted delivery and independent native-replay route.

Follow the [qualified warm handoff](p06-qualified-warm-handoff.md). Earlier
[checkpoint-publication evidence](p06-checkpoint-publication-audit.md) retains
its original execution and qualification scope.
