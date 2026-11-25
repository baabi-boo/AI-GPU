# Agent 09 — independent packaging identity/recovery review

## Scope and verdict

Base: `622662ad9cece6da4e3375be7e977dbe04cde862`. Reviewed every changed hunk of
`ci/project/p06_qualified_warm_pack.py` against HEAD, all 134 lines of the new
`test_p06_pack_operational_failures.py`, existing packaging regressions and the
automation/retention contracts. Read the assigned brief, AGENTS guidance and
Agent 03 report. No production or repository test edits, no commits. The only
owned artifacts are this report and the `agent-09-*` notes/probe files.

**No additional F2/F3 finding demonstrated.** Agent 03's concrete F2 is
independently reproduced on the baseline and rejected by the candidate. The
candidate meets its stated output-leaf identity observation scope and preserves
owned bytes under the independently injected recovery failures below. One
narrow F1 descriptor-lifetime finding was reproduced, corrected by root, and
independently rechecked successfully on the final candidate.

## Findings and observations

1. **Known F2 fixed; high confidence; executable reproduction.** During initial
   inventory, rename the new output directory and recreate the requested name
   with mode 0755. The exact HEAD helper returns `packaging_passed=true` and
   writes into the replacement. Candidate raises `ValueError`, leaves the
   replacement's unrelated file unchanged, and writes its failure receipt into
   the retained original directory. Source evidence bytes remain unchanged.

2. **F1, corrected; high confidence; static-proof plus executable fault injection.** At
   initial candidate line 420, `os.fstat(output_fd)` ran before the package try/finally
   beginning at line 457. Injecting `KeyboardInterrupt` at that first fstat of
   the valid newly opened output descriptor leaves exactly one descriptor open.
   No invalid descriptor was injected. The output is still empty; no success is
   returned and no archive bytes are lost. The probe closes its leaked fd after
   observing it. This is a narrow early-interruption lifetime issue, not a
   demonstrated supported-run failure or gate bypass. Root moved that initial
   fstat into the existing try/finally (final line 458), initializing the captured
   identity to `None` beforehand. Independent review of that narrow correction
   and rerun of the same valid-output-fd fault confirmed zero leaked descriptors,
   propagation of the original interrupt, and a private failure receipt with
   `created_files=[]`. This resolves the demonstrated trigger; it is not a
   claim that asynchronous termination cannot occur elsewhere during setup.

3. **F0 scope observation; high confidence; executable.** Replacing an output
   ancestor and moving the original output leaf back beneath the replacement
   ancestor is accepted. The leaf's device, inode and mode remain identical,
   and mode stays 0700. This is consistent with the stated leaf-directory
   observation contract; it is not evidence of full ancestor-chain stability.
   No encryption-style ancestor guarantee is imposed by this review.

4. **Recovery/ownership controls verified.** Replacing an ancestor while leaving
   the original leaf displaced is detected. After final receipt publication,
   recovery uses the original directory, withdraws owned final names and
   preserves unrelated colliding names in the replacement. Interruption after
   an archive hardlink but before its temporary-name unlink retains one
   single-link incomplete archive. A failed receipt-withdrawal link, both
   before and after creation of that recovery link, retains the owned final
   receipt and every archive it references. The failure receipt marks
   withdrawal unresolved and records the actual archive hashes/lengths.

## Changed-hunk review

The optional `directory_fd` helpers duplicate the supplied fd and close their
duplicate. Source inventory/copy behavior is unchanged. Output comparisons
observe device/inode/mode while deliberately excluding ordinary directory
mtime/size changes caused by packaging itself. Normal files remain private
under permissive umask, covered by the existing passing test, and the new test
rejects observed mode drift. Published-name ownership checks now use the held
original directory, preventing recovery from acting on identically named
replacement-directory files. Withdrawal links before removing the final name,
or removes it only after observing an existing temporary hardlink of the same
identity. Anchored retained-byte reads and failure-receipt writes survive
renaming. The four independent recovery probes observed no descriptor leak.

The four new test methods cover initial complete/partial replacement, copied
bytes, post-receipt replacement by directory/symlink, and mode drift. Existing
tests additionally cover collisions, corruption, boundedness, interruption,
failed withdrawal and last referenced archive retention. No missing critical
scenario justified a new `test_p06_pack_identity_review.py`.

## Validation actually run

From `/tmp/ai-gpu-ae456f837c05/AI-GPU`:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin python3 -B -m unittest discover -s ci/project -p 'test_p06*pack*.py' -v > /tmp/ai-gpu-ae456f837c05/notes/agent-09-tests.log 2>&1
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin python3 -B /tmp/ai-gpu-ae456f837c05/notes/agent-09-probes.py > /tmp/ai-gpu-ae456f837c05/notes/agent-09-probes.log 2>&1
git diff --check -- ci/project/p06_qualified_warm_pack.py ci/project/test_p06_pack_operational_failures.py
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin python3 -B -m unittest discover -s ci/project -p 'test_p06*pack*.py' -v > /tmp/ai-gpu-ae456f837c05/notes/agent-09-final-tests.log 2>&1
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin python3 -B /tmp/ai-gpu-ae456f837c05/notes/agent-09-fd-final.py > /tmp/ai-gpu-ae456f837c05/notes/agent-09-fd-final.log 2>&1
git diff --check -- ci/project/p06_qualified_warm_pack.py
```

- Initial candidate, CPython 3.12.14: **37 tests passed in 2.386 seconds**, zero
  failures/errors/skips.
- **8 independent probe scenarios completed**, all expected observations
  asserted; includes the known baseline failure and the F1, not eight new
  correctness passes. Retained details are in `agent-09-probes.json`.
- Final candidate after root's narrow F1 correction: **37 tests passed in 2.041
  seconds**, zero failures/errors/skips. One repeated independent first-fstat
  fault probe passed with zero leaked fds and retained failure receipt; exact
  result is in `agent-09-fd-final.json`. Earlier eight-probe evidence remains
  bound to the initial candidate; it has not been relabelled as a final-tree run.
- Tracked pack diff whitespace check passed. No full strict governance, native
  work, encrypted delivery, malicious-writer exclusion or crash-atomicity
  claim. No attempt was made to exhaust inter-observation races or storage
  failure combinations. The next required integration gate remains root's
  complete exact-revision governance run.

## SHA-256 identities

| File | SHA-256 |
|---|---|
| HEAD `p06_qualified_warm_pack.py` | `5a7bf6f435126f20e8a6c1c91ad49c9a65b96c568a238a70dcb0b78d83201b99` |
| Initial candidate `p06_qualified_warm_pack.py` | `0e8f19e49d1f05b686eb904cc5b840eb8968c5f6ec60cf8d44c64e0ad4108349` |
| Final candidate `p06_qualified_warm_pack.py` | `b67c66bace419f08fa57ae244e81af21477f634d2d9d3be853393ea8f287fd6f` |
| `test_p06_pack_operational_failures.py` | `a7e93f6deb807c6cea46816c822cb2740b16ddba6d8ab892057bc18582fbe372` |
| `test_p06_qualified_warm_pack.py` | `290a67b637f5507e97f9bd5f073864edc47a179943e5ccd95493d01f5c754a6b` |
| `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |
| `agent-09-tests.log` | `788d9455db84ff25e3bf04283d96c2a84bf974a0d5c760ccf327eae6fb3c2691` |
| `agent-09-probes.py` | `b63ecca5c3690688bacdb5154720281fb2936afb70897683c45abb5888a00abf` |
| `agent-09-probes.json` | `600c14f593b93d81b8c95b7f867c10fc335767f1d6fd2ae2efd403c0133f2c5a` |
| `agent-09-probes.log` | `418b550c629c99d73c546c0193cf24eaf06fd9c2658af35a0c3375b3b95f14d0` |
| `agent-09-final-tests.log` | `79cf6fd4c6c13b76ae6c0d93e936c622186612fbdad3f3f4054fe044f7694eaf` |
| `agent-09-fd-final.py` | `73c358864dbe4a2bf5ad20920859a7b189885d9246566a280f7bcc9ab968b2ee` |
| `agent-09-fd-final.json` | `277d739a3fa7a8888d797d7eab85468b975000d5d1130f5308fe9f2dc0e9c70a` |
| `agent-09-fd-final.log` | `726ef35af0194857bc138cab21745928bd6f25135fbb3c0d6a4e3177f865ba78` |
