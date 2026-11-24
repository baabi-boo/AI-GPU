# Manual hosted qualified warm operator guide

## Current result and next action

**No fresh 24-process qualified warm experiment has run.** The new manual route
composes the existing frozen experiment; it does not change measurement sources,
proofs, sampling, numerical comparisons or performance predicates. The seven
helpers and manual workflow are implemented. Recorded focused validation covers
**224 tests and 413 successful subtests**; the
[tooling evidence packet](evidence/p06-hosted-warm-automation/README.md) records
the tested identities and independent reviews. These development checks do not
replace the published revision's own full strict governance result. Read that
result from its exact Actions run; no new full strict or native result is
claimed here.

The independently verified base
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

The next operational action is to configure private control storage and the
recipient key arrangement below, verify full strict governance for the exact
published automation revision, and dispatch one complete attempt on a runner
that passes unchanged native admission. Follow the
[automation contract](../designs/qualified_warm_automation_v1.md),
[hosted audit](p06-hosted-warm-audit.md) and
[qualified warm handoff](p06-qualified-warm-handoff.md).

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

For this workflow, `attempt/` below means
`$RUNNER_TEMP/p06-qualified-warm-attempt/`. Hosted closeout attempts to encrypt
the entire `attempt/retention/` tree: `packet/` contains the packaged original/envelope or
partial products and their receipts; `packaging.log` and `hosted-closeout.json`
record packaging and the pre-encryption disposition. A packaging failure may
leave only incomplete copied bytes there. Encrypting those bytes does not prove
that all original failure evidence was captured.

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
still have valid encrypted failure retention.

```bash
: "${P06_DOWNLOAD:?Set a fresh local download directory}"
test ! -e "$P06_DOWNLOAD"
gh run download "$P06_HOSTED_RUN_ID" --repo baabi-boo/AI-GPU \
  --dir "$P06_DOWNLOAD"
```

Locate the fixed ciphertext and summary beneath the downloaded artifact
directory. Check `encryption_passed=true` and compare actual ciphertext size
and SHA-256 with `ciphertext_bytes` and `ciphertext_sha256` in the summary.
The summary also records `expected_revision`, `file_count`,
`directory_count` and `input_bytes`; these are retention counts, not native
process or launch counts.

Decrypt only on the intended reviewer's private machine into an absent file:

```bash
: "${P06_CIPHERTEXT:?Set the downloaded qualified-warm-retention.tar.age path}"
: "${P06_IDENTITY_FILE:?Set the matching privately held age identity}"
: "${P06_RESTORED_TAR:?Set an absent private tar output path}"
umask 077
test ! -e "$P06_RESTORED_TAR"
age --decrypt -i "$P06_IDENTITY_FILE" \
  -o "$P06_RESTORED_TAR" "$P06_CIPHERTEXT"
```

The tar contains `manifest.json` and `private/`. The manifest records
`expected_revision`, relative `directories` and `files` with `path`,
`size_bytes` and `sha256`. An empty directory path denotes the `private/`
root. Inspect it as inert data; validate every member identity and reject links,
special files, duplicate or noncanonical names before restoring any selected
regular files. Do not execute retained scripts or binaries.

In a hosted complete packet, manifest path
`packet/qualified-warm-original.PRIVATE.zip` maps to tar member
`private/packet/qualified-warm-original.PRIVATE.zip`; its packaging receipt is
`private/packet/qualified-warm-pack.PRIVATE.json`. The direct local example,
which encrypts the packaging directory itself, instead produces
`private/qualified-warm-original.PRIVATE.zip` and
`private/qualified-warm-pack.PRIVATE.json`. Use the actual manifest paths;
do not assume the two layouts are identical.

For successful complete-original packaging, require the invocation status and
hosted `hosted-closeout.json` to agree with the private receipt's
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

From a separately trusted reviewed reader checkout, follow
[complete independent replay](evidence/p06-qualified-warm/runbook.md#5-independent-intake-and-complete-inert-replay).
Select ZIP/report/source identities from the independently reviewed intake
record. The reader remains inert and records `native_execution="not_run"`,
`retained_code_executed=false` and unauthenticated local execution origin; hosted
provider context remains separate from native retained-consistency proof.

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
