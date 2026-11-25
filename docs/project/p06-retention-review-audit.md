# P06 retention and independent replay continuation

## Outcome and scope

This continuation repairs the documented independent replay entry point and a
failure-closeout writer observation, then implements the decrypted-retention
inspection and private restoration that previously required manual validation.
It does not execute the frozen native experiment or establish a performance or
phase acceptance.

The audited base is `25543e1cf96530264746c0e2d130018dd0dba465`. Its existing
[Project Governance run](https://github.com/baabi-boo/AI-GPU/actions/runs/45475313555)
completed successfully: the original job log records **5,036 tests in
2,136.484 seconds**, `OK`, and `Strict governance PASSED`. All 15 observed
workflows at that revision completed successfully. Those results qualify the
base only. Changed-source verification and publication are recorded in the
continuation's evidence packet after they actually complete.

## Findings and implemented corrections

| Finding | Concrete failure | Correction |
| --- | --- | --- |
| Direct qualified-warm replay did not start | `python3 ci/project/p06_qualified_warm_replay.py --help` raised a trusted-reader error before argument parsing because the running module's name was `__main__`. The documented replay command used that invocation. | Bind each of the three reader modules to its explicit trusted repository path. Preserve resolved-location checks, byte hashes and source-stability checks. Exercise the real CLI in subprocesses. |
| Missing child command inventory could satisfy writer observation | A started dependency/native child with `state=finished` but no `commands` field was treated as an empty list by `writers_finished`. | Default to an empty list only for the preparation schema. Started dependency/native children must retain an explicit list. Missing or malformed records prevent closeout authorization. |
| Decrypted retention validation was a manual step | The hosted guide required the reviewer to validate every tar member, file hash and path before restoring bytes, but supplied no implementation of that complete operation. | Add a bounded offline reader and an exclusive private restore command for the existing deterministic producer format. |
| A late close failure could interrupt cleanup in the new restore implementation | A fault review released a root directory descriptor and then raised an error. The direct API exposed the raw error and skipped the independently owned parent descriptor. Related cleanup paths could replace an earlier operation error or retry an uncertain descriptor. | Attempt each owned resource once, transfer descriptor ownership before closing the previous directory, preserve the first failure, and prevent success after failed cleanup. Fifteen targeted regressions cover cleanup and descriptor reuse. |
| Future edits of the new contract would miss the governance path filter | The workflow listed the existing warm and automation contracts explicitly, but no existing path matched the new retention contract. | Add the new contract's literal path to both push and pull-request filters and the existing exact test oracle. No job or native admission behavior changes. |

The initial supervision and acquisition audits found no additional confirmed
execution blocker. Their real parser checks, existing focused tests and source
inspection support that bounded conclusion; they do not prove a fresh native
run or live private-provider availability.

## Implementation boundaries

The [retention reader](../../ci/project/p06_qualified_warm_retention.py) accepts
the existing plaintext tar produced before age encryption. It requires a
caller-selected SHA-256 and exact revision, validates the entire manifest and
member inventory, reconstructs canonical producer headers, streams every file
hash, and checks payload padding and the exact archive ending. Hidden files,
empty directories, Unicode paths and long path-only PAX records are supported.
It rejects links, special entries, duplicate or aliased paths, undeclared
members, changed bytes and malformed or unbound revision records.

The [restore command](../../ci/project/p06_qualified_warm_restore.py) verifies
the complete archive before creating a destination. It creates only a fresh
private directory and writes through owned directory descriptors with exclusive
no-follow operations. It preserves the original manifest and file bytes,
creates directories with mode `0700` and files with mode `0600`, verifies the
restored tree, and checks source and destination stability before reporting
success. Failure preserves owned incomplete output; it does not recursively
delete a replacement or unrelated tree.

The reader does not decrypt, extract inner ZIPs, run retained code, acquire
inputs, dispatch a workflow or launch a native process. A separately trusted
age installation still performs authenticated decryption. The optional public
encryption summary is checked for retention revision/count consistency; its
ciphertext identity is not the caller's plaintext tar identity and this helper
does not authenticate a producer. A retained partial or failed attempt can pass
retention inspection without establishing a complete native original.

Repeated descriptor observations and hashes detect observed changes. They do
not exclude every malicious concurrent same-user writer or promise an atomic
crash transaction. The incomplete marker is diagnostic: its presence or absence
is not a successful restoration receipt.

## Verification and independent review

The implementation has focused tests for direct replay entry, trusted source
binding, child writer records, producer-format compatibility, complete archive
validation, private restoration and failure behavior. Integration checks use
the actual existing partial packager and the producer's plaintext tar helpers.
Real age encryption/decryption is a separately recorded development check;
synthetic payloads and test doubles are never described as native evidence.

The [tooling evidence packet](evidence/p06-retention-review/README.md) separates
focused execution, real encryption transport checks, independent reviews and
publication qualification. Its execution ledger distinguishes actual audit,
implementation, testing and review assignments. Independent agents review
changed production code and its contract boundaries. Requested assignment totals
are not completion evidence; the ledger records actual completed work and the
source identities each review observed.

Root integration also moved bytecode suppression before the restore helper's
first local import, made the reader's ciphertext-verification limitation
explicit, and selected/recorded a private current directory in the standalone
replay instructions. Later source-bound tests and independent reviews include
those changes. Current status and backlog require each published revision's
own strict qualification without asserting an unobserved pass or retaining a
permanently stale unpublished-state claim. The root collected the supplied
reports and selected execution artifacts without rewriting their historical
outcomes; that integration is not counted as another agent assignment.

## Preserved project state and next action

P06 and P06-T01 remain `in_progress`; P06-A02/A03 remain open. This continuation
does not change the frozen proof, measurement sources, golden baselines,
sampling or performance predicates. The full experiment still requires
**24 processes, 792 launches and 25,344 checked FP32 words**, including primes
and warm-ups, with the unchanged native resource admission.

The next experimental action remains a complete qualified-warm attempt on a
runner with the exact private control input, explicit public age recipient,
successful exact-revision strict governance and actual capacity. Preserve its
original, restore retained bytes with the new checked command, then replay it
from a separate trusted reader checkout and evaluate every frozen predicate.
No original, report or expected identity may be replaced merely to obtain a
passing result. A valid complete run can reject the performance hypothesis.

The inherited vendor XRT `hw_emu`, physical hardware, synthesis/resource and
DSP findings retain their separate obligations. Native execution was not
attempted in the development environment: its available filesystem capacity
does not meet the unchanged 15 GiB native reserve.
