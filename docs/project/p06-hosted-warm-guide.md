# Manual hosted qualified warm operator guide

## Current result and next action

**No fresh 24-process qualified warm experiment has run.** The current execution
and retention continuation corrects prelaunch failure accounting, preserves
finished native dispositions without promoting failed attempts, and repairs
interruption handling, directory identity, descriptor ownership and control
cleanup. The [current audit](p06-execution-retention-audit.md) and
[evidence packet](evidence/p06-execution-retention/README.md) record the
corrections, source-scoped focused checks, independent reviews and real-tool
synthetic retention controls. These establish tooling behavior only.
Measurement sources, proofs, sampling, numerical comparisons, performance
predicates and resource admission remain frozen. P06-A02/A03 remain open.

The audited base `622662ad9cece6da4e3375be7e977dbe04cde862` passed strict
governance in
[run 45583904526](https://github.com/baabi-boo/AI-GPU/actions/runs/45583904526),
[job 139100502944](https://github.com/baabi-boo/AI-GPU/actions/runs/45583904526/job/139100502944):
**5,114 canonical tests, 37,449 successful subtests and 52,791 ordered events
in 3,122.11397 seconds**, with zero failures, errors or skips and stable source,
interpreter and environment. That result qualifies the exact base only. The
final published changed revision requires its own complete, uninterrupted strict
invocation under the [checked environment](governance-runbook.md). Verify its
exact Actions result and retained original receipts before dispatch; focused
checks do not replace that qualification.

The next operational action is to verify or configure delivery of the exact
private control original and the public age recipient below. The owner's
private control-delivery input and public recipient were not supplied to this
session; live provider secret configuration was not inspected and no admitted
native runner is established. The reviewer keeps the matching private identity
outside Actions and this session for later private decryption. Require the
published revision's own full strict result, observe actual runner capacity and
pass unchanged native admission before one complete **24-process, 792-launch,
25,344-word** attempt. Preserve the original and confirm encrypted delivery.
After private decryption, use checked plaintext inspection and restoration, then
independently replay a usable complete native original from a separate trusted
reader checkout before evaluating every frozen performance predicate. Follow the
[qualified warm handoff](p06-qualified-warm-handoff.md). Restoration does not
establish native completeness, producer authentication or performance acceptance;
failed or partial attempts retain their scope.

The preceding retention and replay continuation repaired direct-CLI
trusted-source binding, required explicit command inventories for started
dependency/native writers, and added checked inert plaintext retention
inspection and private restoration with corrected cleanup. Its
[audit](p06-retention-review-audit.md),
[retention review contract](../designs/qualified_warm_retention_review_v1.md) and
[tooling packet](evidence/p06-retention-review/README.md) retain those boundaries
and their recorded validation scope. Its audited base
`25543e1cf96530264746c0e2d130018dd0dba465` passed strict governance in
[run 45475313555](https://github.com/baabi-boo/AI-GPU/actions/runs/45475313555),
[job 138733849431](https://github.com/baabi-boo/AI-GPU/actions/runs/45475313555/job/138733849431):
**5,036 tests in 2,136.484 seconds**, `OK`, and `Strict governance PASSED`.
That historical result qualifies its exact base only.

The earlier independently verified automation base
[run 45422819749](https://github.com/baabi-boo/AI-GPU/actions/runs/45422819749),
[job 138546650668](https://github.com/baabi-boo/AI-GPU/actions/runs/45422819749/job/138546650668),
passed at `e8e73347ba598c9cd0ceed353148163721b7603d`: **4,812 canonical tests,
36,821 subtests and 51,257 events in 3,211.672274 seconds**, zero failures,
errors or skips, complete ordered accounting and stable source, interpreter
and environment. The separate
[general CI run 45422819767](https://github.com/baabi-boo/AI-GPU/actions/runs/45422819767)
passed **43 of 43 jobs**. Preserve the
[first strict failure](governance-readiness-audit.md#first-strict-hosted-invocation-failed-and-preserved)
at its original scope. None of these results establishes new native execution.

The preceding manual hosted route and its focused validation remain documented
in the [earlier tooling packet](evidence/p06-hosted-warm-automation/README.md),
[automation contract](../designs/qualified_warm_automation_v1.md),
and [hosted audit](p06-hosted-warm-audit.md).

## 1. Configure private inputs and the recipient

Run these command blocks in a dedicated Bash script with `set -euo pipefail`
and `umask 077`. Keep shell tracing disabled while handling private inputs,
keys and decrypted evidence.

The repository is public. The unchanged attempt-04 control ZIP is **47,632,218
bytes**, SHA-256
`d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`.
Retained Ramulator verification files include Micron proprietary/confidential
notices. This original and fresh full dependency packets are **not cleared for
public redistribution**. Preserve the original bytes; do not remove members,
repack it, upload it publicly or replace it with a summary.

| Owner configuration | Required value and handling |
| --- | --- |
| Private control object | The exact original ZIP in owner-managed Azure Blob or S3 storage. Use a supported signed HTTPS object URL with enough lifetime for dispatch and intake. No public mirror or redirect. |
| Actions secret `P06_CONTROL_ARCHIVE_URL` | The signed URL, supplied only through the named secret/environment channel. Keep it out of workflow inputs, command arguments, terminal output and evidence. |
| Actions variable `P06_EVIDENCE_AGE_RECIPIENT` | One valid lowercase `age1` X25519 public recipient. SSH keys, plugins and passphrases are outside this route. |
| Private decryption identity | Held by the intended reviewer outside Actions. The workflow needs only the public recipient. Verify privately that the identity matches before a run. |

Using a separately verified age installation on the recipient's private
machine, create a new identity only if an appropriate one does not already exist.
The key directory must be an existing private owned directory; the output must
be absent.

```bash
umask 077
: "${P06_KEY_DIRECTORY:?Set an existing private key directory}"
test ! -e "$P06_KEY_DIRECTORY/p06-evidence.agekey"
age-keygen -o "$P06_KEY_DIRECTORY/p06-evidence.agekey"
P06_EVIDENCE_AGE_RECIPIENT="$(age-keygen -y "$P06_KEY_DIRECTORY/p06-evidence.agekey")"
```

The owner uploads the unchanged control ZIP through the approved private
provider and saves its signed URL in a private file. Configure the repository
without putting that URL in a command argument or shell history:

```bash
: "${P06_CONTROL_URL_FILE:?Set the private file containing the signed object URL}"
: "${P06_EVIDENCE_AGE_RECIPIENT:?Set the verified public age recipient}"
gh secret set P06_CONTROL_ARCHIVE_URL \
  --repo baabi-boo/AI-GPU < "$P06_CONTROL_URL_FILE"
gh variable set P06_EVIDENCE_AGE_RECIPIENT \
  --repo baabi-boo/AI-GPU --body "$P06_EVIDENCE_AGE_RECIPIENT"
```

These are operator setup instructions, not a claim that configuration was
performed. Missing or invalid configuration must block before acquisition or
native work. Intake verifies the unchanged raw size and SHA-256; transport
success alone does not satisfy historical replay or authenticate an earlier job.

## 2. Select the published revision and dispatch

[The workflow](../../.github/workflows/p06-qualified-warm.yml) is
`workflow_dispatch` only, has no inputs, and accepts only the trusted
`baabi-boo/AI-GPU` repository's `master` branch. It executes its exact provider
`github.sha`. It requires a successful Project Governance run for that same SHA,
on `master` from an allowed push/manual event, including the required full-run
steps. An older green run cannot satisfy that requirement.

Inspect the current revision and its governance results:

```bash
P06_EXPECTED_REVISION="$(gh api repos/baabi-boo/AI-GPU/git/ref/heads/master --jq '.object.sha')"
gh run list --repo baabi-boo/AI-GPU \
  --workflow project-governance.yml --branch master \
  --commit "$P06_EXPECTED_REVISION" --limit 20 \
  --json databaseId,headSha,event,status,conclusion,url
```

Review the strict original under the [governance runbook](governance-runbook.md).
Require zero skips, complete successful ordered accounting and final stability.
The operator inspection does not replace the workflow's exact-revision check.
When the selected revision and configuration are ready:

```bash
gh workflow run p06-qualified-warm.yml --repo baabi-boo/AI-GPU --ref master
gh run list --repo baabi-boo/AI-GPU \
  --workflow p06-qualified-warm.yml --branch master \
  --event workflow_dispatch --limit 5 \
  --json databaseId,headSha,status,conclusion,url
```

Select the actual dispatch ID from that list and verify its SHA; if `master`
advanced, do not attribute the new run to the earlier inspected revision.

```bash
: "${P06_HOSTED_RUN_ID:?Set the actual selected hosted run ID}"
gh run view "$P06_HOSTED_RUN_ID" --repo baabi-boo/AI-GPU \
  --json databaseId,headSha,event,status,conclusion,url
gh run watch "$P06_HOSTED_RUN_ID" --repo baabi-boo/AI-GPU --exit-status
```

A dispatch request is not an execution result. Record the actual run ID,
attempt, SHA and observed conclusion. Preserve unsuccessful attempts, including
configuration, capacity, build and retention failures.

## 3. Host, capacity and stage boundaries

The route selects Ubuntu 24.04, CPython **3.12.14**, GCC/G++ **12**, CMake
**3.22.6** and the reviewed age **1.3.2** transport tool. Historical GCC 12.2.0
was an observed installation, not a frozen minor-version constraint. Retain the
actual exact package/compiler/support-file/shared-runtime identities from this
runner. Package names or version banners alone do not establish the whole host
toolchain. The native launch contract also requires the reviewed `python3`
executable alias; a version-suffixed `python3.12` path is not interchangeable,
even when it resolves to the same CPython 3.12.14 binary.

The selected runner must actually satisfy **15 GiB free disk** and **4 GiB
available memory** before acquisition/native admission, with enough margin for
growth. Preserve two build jobs, one simulation worker, 4 GiB sampled process-group
RSS, 120/1,800/180-second native configure/build/process limits, 16 MiB per
recorded child log and the wrapper's 90-minute polled outer budget. These are
observed and polled budgets, not hard reservations or complete descendant
containment. A standard runner label does not prove capacity.

The existing readiness report remains advisory. The new visible-cgroup report
records exposed bounds and known shortfalls while leaving effective capacity
`unknown` when hierarchy visibility is incomplete. Neither an unknown result
nor `no_shortfall_observed` authorizes native work. Actual production admission
remains mandatory. Supported absence of non-root memory interfaces at a visible
cgroup-v2 root is recorded separately; it never proves unlimited capacity or
complete ancestry.

| Stage/helper | What the retained result can establish |
| --- | --- |
| [Private control intake](../../ci/project/p06_qualified_warm_control.py) | Exact frozen raw bytes received through the named secret; no archive extraction or execution. |
| [Input acquisition](../../ci/project/p06_qualified_warm_inputs.py) | Locked toolchain parts and pinned dependency Git objects acquired; originals unchanged. No build or native launch. |
| [Capacity observation](../../ci/project/p06_qualified_warm_capacity.py) | Bounded host/visible-hierarchy observations; no launch authorization. |
| [Supervised run](../../ci/project/p06_qualified_warm_run.py) | Fresh preparation, dependency build and explicit qualified-warm execution, reconciled with original child records. |
| [Private packaging](../../ci/project/p06_qualified_warm_pack.py) | Byte-preserving complete or explicitly partial retention after writers finish. |
| [Encryption](../../ci/project/p06_qualified_warm_encrypt.py) | An encrypted copy for the selected public recipient; no native/replay/performance acceptance. |

Each attempt uses fresh disjoint source/input/workspace/output roots. The new
wrapper creates its absent workspace; do not precreate it with the direct
runbook recipe. Do not resume a populated attempt, mix attempts, replace samples
or execute the retained historical supervisor with its old hard-coded paths.

## 4. Retain success and failure privately

A complete replay original has exactly `dependency-build/` and
`qualified-warm/` roots. Acquisition, orchestration and hosting records belong
in a separate envelope. Partial packaging does not establish completeness or
qualification and must not be represented as a qualified complete original.
The default reader rejects the partial layout. A partial ZIP containing only
the two native subtrees can reach semantic verification with explicit
`--prefix partial-attempt/evidence`; every frozen native, dependency,
prerequisite and source check still applies. The
[packaging/replay review](evidence/p06-hosted-warm-automation/reviews/A47.md)
records this structural limit. Explicit subtree selection never substitutes
for complete independent replay; no genuine fresh original has been replayed.

After all required writer observations finish, hosted closeout attempts
`success` or `partial` packaging as appropriate. Its outputs can include
`qualified-warm-original.PRIVATE.zip`,
`qualified-warm-envelope.PRIVATE.zip` or `partial-attempt.PRIVATE.zip`, and
private inventory/failure receipts. Retain all hidden regular files, opaque
outputs and available failure bytes in the selected evidence roots; do not
invent missing stages or repair raw records.

Read failure receipts with their actual invocation status. Acquisition and
native-supervisor launch checkpoint failures record an unstarted child only
when execution was never entered; earlier completed commands and partial bytes
remain evidence. A failed hosted supervisor may retain `native_execution=run`
or `not_run` from a matching finished receipt only after source stability and
writer cleanup are observed. This does not change the failed invocation into
success. Unknown launch status and unresolved cleanup remain unknown or
unresolved and block packaging and encryption. Scoped interruption handling
attempts failure finalization; it does not guarantee closeout after abrupt
termination. The [current audit](p06-execution-retention-audit.md) records these
operational failure boundaries.

For this workflow, `attempt/` below means
`$RUNNER_TEMP/p06-qualified-warm-attempt/`. Hosted closeout attempts to encrypt
the entire `attempt/retention/` tree: `packet/` contains the packaged original/envelope or
partial products and their receipts; `packaging.log` and `hosted-closeout.json`
record packaging and the pre-encryption disposition. A packaging failure may
leave only incomplete copied bytes there. Encrypting those bytes does not prove
that all original failure evidence was captured.

Packaging and encryption also reject observed directory replacement or
ancestry changes at their checked boundaries. Cleanup and finalization errors
remain failures even when private partial bytes, a success-shaped receipt or
committed ciphertext survive. Preserve their actual failure records and any
unknown cleanup state; existing output paths do not authorize a retry in place
or establish successful delivery.

The hosted evidence selection includes a private `hosted/sources/` snapshot of
the native wrapper's helper closure, the hosted/control/capacity/pack/encrypt
helpers and both workflows. Its repeated source identities accompany the
separate envelope; retained copies remain inert evidence.

Fetched toolchain archives, dependency Git repositories, installed host tools
and other unselected workspace files remain private runner-local inputs. The
final `attempt-final.PRIVATE.json`, `encryption-invocation.PRIVATE.log`, sibling
`public.PRIVATE/`, and the preflight/entry stderr files in `$RUNNER_TEMP` are
also outside the encrypted selection. Keep them private; their presence on an
ephemeral runner is not durable retention. Unresolved writers, unavailable
encryption or abrupt provider termination can prevent encrypted delivery, and
such an attempt cannot pass. Only a successfully uploaded, validated ciphertext
and sanitized summary establish durable hosted delivery.

### Failure and delivery matrix

Delivery eligibility below requires a successful encryption invocation, full
hosted validation and successful upload. Packaging and encryption remain
attempted operations; local bytes alone do not establish delivery. The
[failure-retention review](evidence/p06-hosted-warm-automation/reviews/A48.md)
records the source-level matrix.

| Condition | Retention and delivery boundary | Result scope |
| --- | --- | --- |
| Missing workflow configuration | Checkout and attempt creation are skipped; no attempt packet exists. | Failure; native work does not run. |
| Governance preflight or pinned-Python setup fails | After checkout, closeout is best effort. `host_setup` fails before age provisioning, so any local partial bytes cannot be encrypted through the absent fresh age path. | Failure; native work does not run. Composition mocks do not establish delivery here. |
| Confirmed prelaunch block | `process_started=false` with `cleanup_complete=true` permits partial closeout if encryption tools, recipient and retention capacity are already available. | Failure; no completed experiment. |
| Unknown launch or unresolved cleanup | `process_started=null`, non-Boolean launch status or incomplete cleanup blocks packaging and encryption; available originals and receipts remain local. | Failure; an unobserved native-supervisor launch is `unknown`. |
| Finished native failure | Partial packaging and delivery are eligible only after all required writer and cleanup observations finish. | Retention success does not change the failed native attempt. |
| Packaging failure | Only already-created `retention/` bytes are candidates for encryption; completeness is unestablished. Duplicate surviving receipt hardlinks fail encryption's single-link inventory check. | Packaging remains failed, including when a success-shaped receipt and verified final ZIPs survive. |
| Encryption failure or interruption | No upload authorization. Interrupted cleanup after commit can leave a valid public-named ciphertext/summary pair locally. | Failure; file existence or a pass-shaped summary does not establish successful invocation or delivery. |
| Cancellation or abrupt termination | `!cancelled()` prevents starting hosted work after observed cancellation. Active closeout and delivery are best effort; a previously validated pair may upload if the `always()` upload step is reached. | Record the actual provider conclusion; infer no acceptance from cancellation or retained bytes. |
| Complete valid experiment, failed hypothesis | Complete original/envelope delivery is eligible after the same retention checks. | Hosted orchestration can pass while independent replay reports `not_satisfied`; no performance, phase or hardware acceptance follows. |

For separately supervised local packaging, the exact interface is:

```bash
: "${P06_PYTHON:?Set the reviewed absolute CPython 3.12.14 python3 executable}"
[[ "$P06_PYTHON" == /*/python3 ]]
: "${P06_PACK_MODE:?Set success or partial from the actual attempt disposition}"
: "${P06_SOURCE:?Set the trusted source checkout}"
: "${P06_WORKSPACE:?Set the completed or stopped attempt workspace}"
: "${P06_PRIVATE_PACK:?Set a fresh private packaging directory}"
"$P06_PYTHON" -B "$P06_SOURCE/ci/project/p06_qualified_warm_pack.py" \
  "$P06_PACK_MODE" --source-dir "$P06_SOURCE" \
  --workspace-dir "$P06_WORKSPACE" --output-dir "$P06_PRIVATE_PACK" \
  --writers-finished
```

Add explicit `--extra-root LABEL=ABSOLUTE_PATH` arguments for acquisition and
supervision evidence outside the workspace. Assert `--writers-finished` only
after stopping and waiting for every actual writer. Packaging checks cannot
prove complete descendant containment.

For the direct local example, encryption consumes the entire private packaging
directory. The hosted route instead selects its enclosing `attempt/retention/`
tree as described above:

```bash
: "${P06_PUBLIC_OUTPUT:?Set a fresh output directory for encrypted delivery}"
: "${P06_AGE_BINARY:?Set the verified absolute age executable}"
: "${P06_SOURCE_REVISION:?Set the exact 40-character execution revision}"
"$P06_PYTHON" -B "$P06_SOURCE/ci/project/p06_qualified_warm_encrypt.py" \
  --input-dir "$P06_PRIVATE_PACK" --output-dir "$P06_PUBLIC_OUTPUT" \
  --recipient "$P06_EVIDENCE_AGE_RECIPIENT" --age-binary "$P06_AGE_BINARY" \
  --expected-revision "$P06_SOURCE_REVISION"
```

The only public upload paths are
`attempt/public/qualified-warm-retention.tar.age` and
`attempt/public/encryption-summary.json`. The sibling
`attempt/public.PRIVATE` contains private failure/stderr/partial-output records
and must never be uploaded. Do not upload raw source trees, native reports,
prerequisite archives or plaintext logs as Actions artifacts.

Before enabling upload, the hosted helper requires a successful encryption
invocation with completed cleanup and checks the exact summary contract,
revision, successful disposition, counts, actual ciphertext size and SHA-256,
and equality with the encryption command's terminal summary. The workflow
requires its `encrypted_retention_ready` output. A valid encrypted partial
attempt can satisfy that retention gate while the native attempt and job remain
unsuccessful; an encryption failure cannot enable upload. Recovery is best
effort, not an atomic crash transaction: interrupted cleanup after commit can
leave both public-named files locally. Their existence or a pass-shaped summary
does not satisfy the successful-invocation and full-validation gate. Confirm
the upload's actual success before reporting durable delivery.

Encryption has a separate retention-space guard: it budgets the exact
uncompressed tar size, conservative ciphertext overhead and a 64 MiB margin.
That permits a small failure packet to be retained after a native disk-reserve
failure. It does not lower the native/acquisition 15 GiB reserve. If encryption
or upload fails, report retention failure; do not relabel it as successful or
silently discard the private evidence.

## 5. Download, decrypt privately and replay

Download the selected run's artifacts to a fresh owned directory. The workflow
publishes only the ciphertext and minimal summary; a failed native attempt may
still have valid encrypted failure retention. The checked inspection and
restoration below implement the
[retention review contract](../designs/qualified_warm_retention_review_v1.md);
the [continuation audit](p06-retention-review-audit.md) records their development
and review scope.

```bash
: "${P06_DOWNLOAD:?Set a fresh absolute local download directory}"
test ! -e "$P06_DOWNLOAD"
test ! -L "$P06_DOWNLOAD"
gh run download "$P06_HOSTED_RUN_ID" --repo baabi-boo/AI-GPU \
  --dir "$P06_DOWNLOAD"
```

Locate the fixed ciphertext and summary beneath the downloaded artifact
directory. Set `P06_CIPHERTEXT` and `P06_ENCRYPTION_SUMMARY` to their absolute
paths. Before decryption, check `encryption_passed=true` and compare actual
ciphertext size and SHA-256 with `ciphertext_bytes` and `ciphertext_sha256` in
the summary. Require its `expected_revision` to match the selected run's actual
execution revision. The summary also records `file_count`, `directory_count`
and `input_bytes`; these are retention counts, not native process or launch
counts. Retain the ciphertext checks and actual download provenance separately.

Using the separately verified age installation, decrypt only on the intended
reviewer's private machine into an absent file in an existing private directory:

```bash
: "${P06_CIPHERTEXT:?Set the absolute downloaded qualified-warm-retention.tar.age path}"
: "${P06_ENCRYPTION_SUMMARY:?Set the absolute downloaded encryption-summary.json path}"
: "${P06_IDENTITY_FILE:?Set the absolute matching privately held age identity path}"
: "${P06_RESTORED_TAR:?Set an absent absolute private plaintext tar path}"
umask 077
test ! -e "$P06_RESTORED_TAR"
test ! -L "$P06_RESTORED_TAR"
age --decrypt -i "$P06_IDENTITY_FILE" \
  -o "$P06_RESTORED_TAR" "$P06_CIPHERTEXT"
```

Require a zero decryption exit status before proceeding. A failed or
interrupted `age` command can leave private partial plaintext at the output
path. Discard that partial output or retain it privately as rejected failure
evidence before any normal inspection, restoration or replay; never treat it
as a usable archive. Use another absent private path for a later retry. The
dedicated script's `set -e` stops this sequence on decryption failure.

The [real-tool controls](p06-execution-retention-audit.md) observed partial
plaintext after ciphertext truncation, a payload bit flip and appended
ciphertext, all with nonzero decryption exits. A separate malformed tar in a
valid age envelope decrypted successfully but failed strict archive inspection
even with a matching plaintext digest. Successful age decryption therefore
does not establish strict tar validity, completed restoration, producer
authentication or native acceptance; the following validation remains required.

After successful decryption, select and record the raw plaintext tar SHA-256
in the private intake record; `sha256sum -- "$P06_RESTORED_TAR"` hashes those
bytes. Use that recorded 64-character lowercase digest
as `P06_PLAINTEXT_TAR_SHA256`. It is separate from the public summary's
`ciphertext_sha256`: the encrypted object and plaintext tar have different
byte identities. A locally selected digest binds subsequent review to those
bytes; it does not authenticate their producer. Do not take an expected digest
from the tar's own manifest or replace a recorded expectation to admit changed
bytes.

Use a separately trusted reviewed reader checkout, never a source tree restored
from the candidate. Select `P06_SOURCE_REVISION` from the reviewed execution
record: it must be the exact 40-character lowercase commit for the original
attempt, not `HEAD`, a branch name or the reader checkout's revision. The
archive, optional summary and restoration destination must use canonical
absolute paths without symlink ancestors. Stop all writers to these inputs and
the destination parent before inspection or restoration; repeated stability
checks do not exclude every malicious concurrent same-user writer.

Inspect the complete decrypted archive without creating a restored tree:

```bash
: "${P06_PYTHON:?Set the reviewed absolute CPython 3.12.14 python3 executable}"
[[ "$P06_PYTHON" == /*/python3 ]]
: "${P06_READER_SOURCE:?Set the absolute trusted reviewed reader checkout}"
: "${P06_SOURCE_REVISION:?Set the exact lowercase 40-hex execution revision}"
: "${P06_PLAINTEXT_TAR_SHA256:?Set the recorded lowercase 64-hex plaintext tar digest}"
"$P06_PYTHON" -B "$P06_READER_SOURCE/ci/project/p06_qualified_warm_restore.py" \
  inspect --archive "$P06_RESTORED_TAR" \
  --sha256 "$P06_PLAINTEXT_TAR_SHA256" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --summary "$P06_ENCRYPTION_SUMMARY"
```

`--summary` is an optional existing input, never an output receipt. Omit that
option and its value when no summary is being reviewed. When supplied, it checks
the summary schema, advertised success fields, revision, file and
directory counts, and input-byte count against the validated archive. It does
not read the ciphertext or verify its actual size, digest or relationship to
the plaintext. Those earlier ciphertext checks and age decryption remain
separate required operations for encrypted delivery.

The tar contains `manifest.json` and `private/`. The reader verifies the entire
producer-format archive, canonical manifest, exact member inventory and every
regular-file size and SHA-256. It rejects links, special entries, duplicate or
aliased paths, undeclared members and malformed archive bytes. The manifest's
empty directory path denotes the `private/` root. Inspection emits JSON on
stdout; require exit status zero with `outcome="pass"` and
`retention_verified=true` before continuing.

Restore into a new absent directory whose private owned parent already exists.
Keep that directory disjoint from the archive and optional summary paths; do
not precreate it or reuse a previous restore:

```bash
: "${P06_RESTORE_DIRECTORY:?Set an absent absolute private restoration directory}"
test ! -e "$P06_RESTORE_DIRECTORY"
test ! -L "$P06_RESTORE_DIRECTORY"
"$P06_PYTHON" -B "$P06_READER_SOURCE/ci/project/p06_qualified_warm_restore.py" \
  restore --archive "$P06_RESTORED_TAR" \
  --sha256 "$P06_PLAINTEXT_TAR_SHA256" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --summary "$P06_ENCRYPTION_SUMMARY" \
  --output-dir "$P06_RESTORE_DIRECTORY"
```

Restoration independently repeats full validation before creating output. It
preserves the original `manifest.json` bytes and all declared files and
directories under `private/`, including hidden files and empty entries. New
directories have mode `0700`; regular files have mode `0600`. Retained executable
modes and ownership are not applied. This command does not extract or
semantically replay inner ZIPs; retained scripts and binaries must remain inert.

Require exit status zero and a terminal JSON report with `outcome="pass"`,
`retention_verified=true` and `restoration_completed=true`. Retain the actual
command disposition and report privately. There is no persistent pass receipt.
A failure after output creation preserves owned incomplete bytes and attempts
to retain `.restore-incomplete.PRIVATE.json` beside `manifest.json`. Its presence
or absence, or the existence of an output tree, does not establish success.
Filesystem failure or abrupt termination can prevent marker retention; this is
not an atomic crash transaction. Preserve a failed restoration unchanged and
use another absent destination for any later retry.

Paths below are relative to `P06_RESTORE_DIRECTORY`; use the actual validated
manifest to identify the selected layout:

| Encryption input | Restored complete original ZIP | Restored packaging receipt |
| --- | --- | --- |
| Direct local packaging directory | `private/qualified-warm-original.PRIVATE.zip` | `private/qualified-warm-pack.PRIVATE.json` |
| Hosted `attempt/retention/` tree | `private/packet/qualified-warm-original.PRIVATE.zip` | `private/packet/qualified-warm-pack.PRIVATE.json` |

For example, hosted manifest path
`packet/qualified-warm-original.PRIVATE.zip` maps to
`$P06_RESTORE_DIRECTORY/private/packet/qualified-warm-original.PRIVATE.zip`.
The hosted layout also retains `private/hosted-closeout.json` and
`private/packaging.log` when those files were captured. A
`partial-attempt.PRIVATE.zip` or incomplete copied packaging tree retains its
recorded partial or failed scope even when inspection and restoration succeed.
Apply the partial-layout boundaries in section 4 before selecting any native
replay input; restoration does not establish a complete replay original.

For successful complete-original packaging, require the invocation status to
agree with the private receipt and, for hosted delivery, with
`hosted-closeout.json`. Require the receipt's
`packaging_passed=true`, `complete_replay_original_created=true` and
`partial_attempt=false`, with matching retained inventories and hashes.
Inspect `packaging-failure.PRIVATE.json` and the packaging log as well. Failed
withdrawal of an owned success receipt can preserve that receipt and its
verified final ZIPs after a failed invocation; a failure receipt can record
`published_receipt_withdrawal_unresolved=true`. The success-shaped receipt alone
cannot override the failed invocation or establish successful packaging.
Preserve surviving bytes unchanged and keep incomplete or failed retention at
its recorded scope. Encryption success does not prove that a complete native
original exists.

### Independent complete replay from a fresh shell

After retention review, use this standalone setup for
[complete independent replay](evidence/p06-qualified-warm/runbook.md#5-independent-intake-and-complete-inert-replay).
It runs the trusted reader directly and requires no earlier `p06_run_stage`,
`P06_ENV`, native workspace or host-tool setup from that runbook. Native
preparation, dependency building and execution are separate operations; do not
repeat them to initialize a review.

Keep both **unchanged complete original prerequisite ZIPs** separately available
to the reviewer: the diagnostic original and the owner-retained local
attempt-04 control original. The diagnostic can be selected from the trusted
checkout at
`docs/project/evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip`.
Preserve their raw bytes and private handling; do not rebuild, repack or replace
either with a report. Hosted success packaging retains copies in
`qualified-warm-envelope.PRIVATE.zip` at
`additional-evidence/originals/diagnostic-original.zip` and
`additional-evidence/control/control-original.zip`. The restored envelope
remains an opaque ZIP and is not itself either prerequisite. The command below
uses separately available original ZIP files; stop if either is unavailable.
Direct local packaging includes such copies only when their roots were
explicitly selected for retention.

Select and record these inputs outside the candidate before running the reader.
The source revision identifies the original execution; the reader revision
identifies the separately reviewed code used now. Record their distinct roles,
input paths, raw sizes and hashes, and intake provenance privately.

| Variable | Required independent selection |
| --- | --- |
| `P06_PYTHON` | Reviewed absolute Linux CPython **3.12.14** executable named `python3`. |
| `P06_READER_SOURCE` | Trusted reviewed reader checkout, including its helper closure, original qualification proof, diagnostic source inventory and frozen warm manifest. Never use restored candidate code. |
| `P06_READER_REVISION` | Exact reviewed 40-character lowercase commit of that clean reader checkout. |
| `P06_ORIGINAL_ZIP` | Selected restored complete original with exactly `dependency-build/` and `qualified-warm/` roots. |
| `P06_SOURCE_REVISION` | Actual original execution commit, 40 lowercase hexadecimal characters. |
| `P06_ZIP_SHA256` | Independently recorded digest of the exact complete original ZIP bytes. |
| `P06_DEPENDENCY_RECEIPT_SHA256` | Independently recorded digest of raw `dependency-build/report.json` bytes. |
| `P06_NATIVE_REPORT_SHA256` | Independently recorded digest of raw `qualified-warm/report.json` bytes. |
| `P06_NATIVE_SOURCE_BEFORE_SHA256` | Independently recorded digest of raw `qualified-warm/snapshots/source-before.json` bytes. |
| `P06_PROOF_SHA256` | Current extended qualification proof identity from the trusted contract, shown below. |
| `P06_DIAGNOSTIC_ARCHIVE`, `P06_DIAGNOSTIC_SHA256` | Separate unchanged original diagnostic ZIP and its frozen identity below. |
| `P06_CONTROL_ARCHIVE`, `P06_CONTROL_SHA256` | Separate unchanged owner-retained attempt-04 control ZIP and its frozen identity below. |
| `P06_REPLAY_DIRECTORY` | Absent absolute private review directory under an existing owned private parent, outside the reader checkout, restoration tree and all input roots. |

The three frozen CLI identities are:

| Input | SHA-256 |
| --- | --- |
| Current `ci/project/p06_qualified_warm_proof.json` | `172721c671ddaa79541dde9c37c154b5ab5a99b8abb0caabf2e07036dd429efb` |
| Original diagnostic ZIP, **4,290,949 bytes** | `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb` |
| Original attempt-04 control ZIP, **47,632,218 bytes** | `d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f` |

Every SHA-256 value must contain 64 lowercase hexadecimal characters. The native
source snapshot pin is its raw JSON-byte digest, not a Git tree, proof digest or
semantic dependency-source manifest digest. This procedure supplies no fresh
ZIP, dependency receipt, native report or source snapshot expectation before
actual execution and independent intake. Do not derive those expectations from
the candidate's self-reported fields or treat the outer retention manifest or
packaging receipt as their independent authority. Stop on a mismatch; never
replace an expected digest merely to obtain a passing replay.

Run the following blocks together in a new dedicated Bash script. Use canonical
absolute paths without symlink ancestors for the checkout, archives and review
directory, and stop all writers to the reader and input files. The first block
checks the selected reader revision and interpreter, creates fresh private
output/log locations, and defines its own sanitized child environment. It does
not create a native execution workspace.

```bash
set -euo pipefail
set +x
umask 077
: "${P06_PYTHON:?Set the reviewed absolute CPython 3.12.14 python3 executable}"
: "${P06_READER_SOURCE:?Set the absolute trusted reviewed reader checkout}"
: "${P06_READER_REVISION:?Set the exact reviewed lowercase 40-hex reader commit}"
: "${P06_ORIGINAL_ZIP:?Set the absolute restored complete original ZIP path}"
: "${P06_SOURCE_REVISION:?Set the exact lowercase 40-hex original execution commit}"
: "${P06_ZIP_SHA256:?Set the independently recorded complete original ZIP digest}"
: "${P06_DEPENDENCY_RECEIPT_SHA256:?Set the independently recorded dependency report digest}"
: "${P06_NATIVE_REPORT_SHA256:?Set the independently recorded native report digest}"
: "${P06_NATIVE_SOURCE_BEFORE_SHA256:?Set the independently recorded raw source snapshot digest}"
: "${P06_PROOF_SHA256:?Select the frozen current qualification proof digest above}"
: "${P06_DIAGNOSTIC_ARCHIVE:?Set the absolute separate original diagnostic ZIP path}"
: "${P06_DIAGNOSTIC_SHA256:?Select the frozen original diagnostic ZIP digest above}"
: "${P06_CONTROL_ARCHIVE:?Set the absolute separate owner-retained attempt-04 ZIP path}"
: "${P06_CONTROL_SHA256:?Select the frozen original attempt-04 ZIP digest above}"
: "${P06_REPLAY_DIRECTORY:?Set an absent absolute private review directory}"
[[ "$P06_PYTHON" == /*/python3 ]]
[[ "$P06_READER_REVISION" =~ ^[0-9a-f]{40}$ ]]
[[ "$P06_SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]]
for P06_DIGEST in "$P06_ZIP_SHA256" "$P06_DEPENDENCY_RECEIPT_SHA256" \
  "$P06_NATIVE_REPORT_SHA256" "$P06_NATIVE_SOURCE_BEFORE_SHA256" \
  "$P06_PROOF_SHA256" "$P06_DIAGNOSTIC_SHA256" "$P06_CONTROL_SHA256"; do
  [[ "$P06_DIGEST" =~ ^[0-9a-f]{64}$ ]]
done
for P06_PATH in "$P06_READER_SOURCE" "$P06_ORIGINAL_ZIP" \
  "$P06_DIAGNOSTIC_ARCHIVE" "$P06_CONTROL_ARCHIVE" "$P06_REPLAY_DIRECTORY"; do
  [[ "$P06_PATH" == /* ]]
done
test -x "$P06_PYTHON"
test -d "$P06_READER_SOURCE"
for P06_INPUT in "$P06_ORIGINAL_ZIP" "$P06_DIAGNOSTIC_ARCHIVE" "$P06_CONTROL_ARCHIVE"; do
  test -f "$P06_INPUT"
  test ! -L "$P06_INPUT"
done
P06_OBSERVED_READER_REVISION="$(git -C "$P06_READER_SOURCE" rev-parse HEAD)"
test "$P06_OBSERVED_READER_REVISION" = "$P06_READER_REVISION"
P06_READER_STATUS="$(git -C "$P06_READER_SOURCE" status --porcelain --untracked-files=all)"
test -z "$P06_READER_STATUS"
test ! -e "$P06_REPLAY_DIRECTORY"
test ! -L "$P06_REPLAY_DIRECTORY"
mkdir -m 700 -- "$P06_REPLAY_DIRECTORY"
mkdir -m 700 -- "$P06_REPLAY_DIRECTORY/home" "$P06_REPLAY_DIRECTORY/tmp"
cd -- "$P06_REPLAY_DIRECTORY"
test "$(pwd -P)" = "$P06_REPLAY_DIRECTORY"
P06_REPLAY_OUTPUT="$P06_REPLAY_DIRECTORY/replay.json"
P06_REPLAY_ENV=(/usr/bin/env -i
  "PATH=${P06_PYTHON%/*}:/usr/bin:/bin"
  "HOME=$P06_REPLAY_DIRECTORY/home" "TMPDIR=$P06_REPLAY_DIRECTORY/tmp"
  LANG=C LC_ALL=C TZ=UTC PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1)
set -o noclobber
pwd -P > "$P06_REPLAY_DIRECTORY/replay.cwd.txt"
printf '%s\n' "$P06_READER_SOURCE" > "$P06_REPLAY_DIRECTORY/reader-path.txt"
printf '%s\n' "$P06_OBSERVED_READER_REVISION" > "$P06_REPLAY_DIRECTORY/reader-revision.txt"
"${P06_REPLAY_ENV[@]}" "$P06_PYTHON" -I -B - \
  > "$P06_REPLAY_DIRECTORY/interpreter.json" \
  2> "$P06_REPLAY_DIRECTORY/interpreter.stderr.log" <<'PY'
import hashlib, json, os, pathlib, sys
executable = pathlib.Path(sys.executable).resolve(strict=True)
with executable.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
print(json.dumps({'executable': str(executable), 'sha256': digest,
                  'version': sys.version, 'platform': sys.platform,
                  'environment': dict(os.environ)}, sort_keys=True))
if (sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 12, 14)
        or sys.platform != 'linux'):
    raise SystemExit('review requires Linux CPython 3.12.14')
PY
```

The checkout and interpreter must already be independently trusted; these setup
checks record their selected identities and do not authenticate them. The reader
still validates its complete trusted helper/input inventory and repeated source
stability. Run the complete inert reader and retain its actual disposition:

```bash
P06_REPLAY_COMMAND=("$P06_PYTHON" -B
  "$P06_READER_SOURCE/ci/project/p06_qualified_warm_replay.py"
  --archive "$P06_ORIGINAL_ZIP"
  --sha256 "$P06_ZIP_SHA256"
  --source-revision "$P06_SOURCE_REVISION"
  --dependency-receipt-sha256 "$P06_DEPENDENCY_RECEIPT_SHA256"
  --native-report-sha256 "$P06_NATIVE_REPORT_SHA256"
  --source-manifest-sha256 "$P06_NATIVE_SOURCE_BEFORE_SHA256"
  --counter-qualification-sha256 "$P06_PROOF_SHA256"
  --diagnostic-archive "$P06_DIAGNOSTIC_ARCHIVE"
  --diagnostic-archive-sha256 "$P06_DIAGNOSTIC_SHA256"
  --control-archive "$P06_CONTROL_ARCHIVE"
  --control-archive-sha256 "$P06_CONTROL_SHA256"
  --output "$P06_REPLAY_OUTPUT")
printf '%q ' "${P06_REPLAY_ENV[@]}" "${P06_REPLAY_COMMAND[@]}" \
  > "$P06_REPLAY_DIRECTORY/replay.command.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$P06_REPLAY_DIRECTORY/replay.started.txt"
if "${P06_REPLAY_ENV[@]}" "${P06_REPLAY_COMMAND[@]}" \
  > "$P06_REPLAY_DIRECTORY/replay.stdout.log" \
  2> "$P06_REPLAY_DIRECTORY/replay.stderr.log"; then
  P06_REPLAY_STATUS=0
else
  P06_REPLAY_STATUS=$?
fi
printf '%s\n' "$P06_REPLAY_STATUS" > "$P06_REPLAY_DIRECTORY/replay.exit-code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$P06_REPLAY_DIRECTORY/replay.finished.txt"
exit "$P06_REPLAY_STATUS"
```

The complete packaging layout uses no prefix. A separately selected original
with one common literal prefix requires an explicit `--prefix PREFIX` recorded
at intake; do not search for a favorable subtree. Preserve section 4's partial
layout boundaries and every semantic check. The reader creates `replay.json`
exclusively. Keep unsuccessful outputs and logs unchanged and select a fresh
review directory for another invocation.

Require exit zero, the terminal stdout `outcome="pass"`, and a complete output
with contract `p06-qualified-warm-replay-v1`, scope
`complete-qualified-warm-retained-consistency`,
`counter_qualification_passed=true` and `qualified_warm_passed=true`.
Inspect `analysis.hypothesis_evaluation` separately: either `satisfied` or
`not_satisfied` can accompany a valid complete replay. A nonzero exit or an
incomplete output establishes no usable replay result, including an output I/O
failure after otherwise valid checks.

The reader reconstructs the full dependency receipt, both format builds, all
**57 native command receipts**, all **24 raw process transcripts**, proof,
source and dependency relationships, both complete historical prerequisite
replays, stability and exact member inventories before running the arithmetic
reducer. The selected native report retains its **64 MiB**, **750,000 value-node**
and depth-**64** bounds; all other record and historical parser bounds remain
unchanged. Duplicate keys, nonfinite values and oversized numeric tokens reject.
Do not truncate inputs, widen limits, weaken budgets or switch
readers to admit a rejected candidate. Retain the reader/helper identities and
independently review the original native observations.

Retention success does not supply independent native expectations or replace
these semantic checks. Both retention commands report
`native_execution="not_run"`, `retained_code_executed=false`,
`origin_authenticated=false` and false native, performance and phase acceptance.
Complete replay also executes no native process or retained code, reports
`native_execution="not_run"`, `retained_code_executed=false`,
`execution_origin="local"` and `origin_authenticated=false`, and leaves all seven
historical qualification/readiness/warm/acceptance fields false. Consistent
records do not authenticate the producer or independently establish Git
membership. Hosted provider context remains separate from native
retained-consistency proof.

## 6. State the actual experimental result

The frozen full population is **24 fresh processes, 792 launches and 25,344
checked FP32 words**; the measured subset is 20 processes and 640 operations.
Preserve all 57 native command receipts, primes and warm-ups. Evaluate FP16 and
BF16 independently against every frozen predicate: candidate median at most
95% of reference, no slower measured candidate pair in instrumented host time,
and no increase in any measured pair's qualified modeled cycles.

`orchestration_passed` reconciles local child records. In the native
`qualified-warm/report.json`, `qualified_warm_passed` describes a complete valid
native population. The hosted top-level `qualified_warm_passed` and
`counter_qualification_passed` fields remain false, including when its
orchestration succeeds. A complete, correctly retained experiment can produce
a green hosted job while independent replay's `analysis.hypothesis_evaluation`
is `not_satisfied`. Report that unfavorable complete result without sample
replacement or optional stopping. A green job does not establish independent
replay, performance, phase or hardware acceptance.

All seven historical qualification/readiness/warm/acceptance fields remain
false. P06 and P06-T01 remain in progress; P06-A02/A03, vendor XRT integration,
physical hardware qualification and the inherited DSP/resource finding retain
their separate obligations. Update [status](status.md) and [backlog](backlog.md)
only with actual source-scoped execution, retention, replay and review evidence.
