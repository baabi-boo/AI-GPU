# A35 — Post-publication directory-replacement test review

## Decision

**No blocking test-validity finding.** The reviewed correction to
`test_changed_restored_bytes_and_unexpected_entries_are_detected` keeps the
deleted empty-directory descriptor alive through production verification,
proves that the intended directory replacement actually has a different
`(st_dev, st_ino)` identity, and requires the specific `output-changed`
diagnostic. The precondition and diagnostic assertions execute outside
`restore_archive`'s exception mapper, so a fixture setup failure cannot satisfy
the new directory subcase merely by becoming a `RestoreError`.

This is a follow-up by the same A35 reviewer, not another independent-agent
count. A57 owns the independent production/contract review; the coordinator
owns the complete 19-test restore-module run. A35 reviewed the exact changed
test and ran one bounded probe invocation containing two distinct controls.
No full module, full suite, native workload, source edit, public report edit,
commit, or rerun was performed by A35.

## Reviewed source and change

Source root: `/home/agent/ai-gpu-d37f66a85d88/AI-GPU`.
HEAD was `0c32d04c5d37679bb0273f07a50bd26a2e21a5e8`, tree
`e20c21c8aeeaa1751f49f43de3b38e7872bbcaa6`. The only working-tree change
observed was `ci/project/test_p06_qualified_warm_restore.py`: 20 insertions
and 7 deletions. The production modules remained published bytes.

The diff adds the `ExitStack` import and changes only the existing four-case
test. The `bytes`, `extra`, `link`, and `directory` cases and the incomplete
marker checks remain present. The directory branch now:

1. Opens the original empty directory and immediately registers `os.close`
   with the enclosing `ExitStack`.
2. Obtains the original fd identity, removes the directory name, creates the
   replacement, and obtains its named identity.
3. Records both identities and calls the real original `_verify_tree`.
4. After `run_restore` returns its expected rejection, asserts two recorded
   identities, inequality of those identities, and code `output-changed`.
5. Checks the incomplete marker before leaving the `ExitStack` scope.

The callback is registered before `fstat`, `rmdir`, `mkdir`, or replacement
`stat` can fail. The stack remains active through the external assertions and
marker check, and releases the fd during exception unwinding as well as normal
completion. The closure's `held` reference is bound by the surrounding `with`
before `mutate` is called. No production descriptor-identity predicate or
failure mapping is weakened.

The original `assertRaises(RestoreError)` alone could accept an unrelated setup
error after production maps it. The three new directory assertions are after
that context and after `self.run_restore`, not inside the injected callback.
Consequently their `AssertionError` cannot be caught by production and converted
into an expected rejection. This was checked dynamically below.

## One probe invocation: two distinct controls

The retained probe invokes the **exact working-tree test method**, without
editing, copying, narrowing, or replacing its assertions. It uses the existing
fixture and real filesystem operations. Observer wrappers delegate to the saved
real `os.open`, `os.close`, `os.fstat`, and production `_verify_tree`; the second
control adds precisely one synthetic setup fault. This is one invocation with
two deliberately different controls, not a rerun of a test command.

| Control | Actual test-method result | Directory behavior | Held fd cleanup | Descriptor/hook audit |
| --- | --- | --- | --- | --- |
| Actual replacement | 1 method; all 4 subcases pass; 0 failures/errors/skips | Real verification raises `output-changed` | Exactly one close | No fd identity change; global hooks restored |
| One-shot held-fd `fstat` setup fault | 1 method; exactly the directory subcase fails; 0 errors/skips | Restore maps the injected `OSError` to `filesystem-failed`; external assertion fails `0 != 2` | Exactly one close | No fd identity change; global hooks restored |

The actual directory observation, taken immediately before delegating to real
production verification, was:

| Observation | Value |
| --- | --- |
| Held original identity `(st_dev, st_ino)` | `(41, 76055)` |
| Named replacement identity `(st_dev, st_ino)` | `(41, 76062)` |
| Original `st_nlink` while still open | `0` |
| Observed public rejection | `RestoreError("output-changed")` |

Thus this execution verifies a real removed-but-open directory and a distinct
replacement. It does not merely assume that the filesystem allocated a new
inode after an unheld remove/recreate sequence.

For the setup-fault control, the observer identifies the descriptor returned by
the fixture's absolute `Path(.../private/empty)` open. It injects one `EIO`
`OSError` at the fixture's following `os.fstat(old_fd)`, after the `ExitStack`
callback has been registered. Production maps it to `filesystem-failed`.
The test then fails at its own identity-count assertion:

```python
self.assertEqual(len(directory_identities), 2)
```

The captured failure is `AssertionError: 0 != 2`, with the test source at line
285 in this exact revision. Its traceback has no `restore_archive` frame.
The `bytes`, `extra`, and `link` subcases pass in this control; the directory
case is explicitly recorded as a failure, never relabelled as a passing test.

The probe snapshots every open descriptor using `/proc/self/fd` and saved real
`fstat`, comparing fd numbers and `(st_dev, st_ino, st_mode, st_rdev)` identities
before and after each control, including fixture cleanup. Both snapshots match.
The probe performs no extra leaked-descriptor cleanup that could conceal a
failure. It independently checks restoration of the global observation hooks.

## Exact commands and results

Executed once from the source root on 2026-11-25:

```sh
env PYTHONDONTWRITEBYTECODE=1 \
  TMPDIR=/home/agent/ai-gpu-d37f66a85d88/tmp/a35-post-publication \
  /home/agent/ai-gpu-d37f66a85d88/governance-environment/venv/bin/python3 -B \
  /home/agent/ai-gpu-d37f66a85d88/tmp/a35-post-publication/probe.py

git diff --check -- ci/project/test_p06_qualified_warm_restore.py
```

Both commands exited 0. The probe's exit 0 means that the actual-replacement
control passed **and** the setup-fault control failed in the required external
assertion, with clean descriptor/hook state in both. It does not mean that the
injected-fault test passed. Probe elapsed time was 0.055096 s; the enclosing
command's reported wall time was approximately 0.103 s.

Interpreter: `3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]`.
The script refuses to rerun if its report already exists. No rerun was needed.
All four source/dependency/test hashes were unchanged before and after execution.

## Exact source identities

| File/state | SHA-256 |
| --- | --- |
| Corrected working `ci/project/test_p06_qualified_warm_restore.py` | `9ef2cb211135a3b4f024056208492a9aef389823d452174c7bfdd8efcab15fb6` |
| Published test at `0c32d04c5d37679bb0273f07a50bd26a2e21a5e8` | `fee089dbe7823d04ecfe7f2dc8f3e378a2e8c49a9fef307e0ad721cd93d646fe` |
| `ci/project/p06_qualified_warm_restore.py` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |
| `ci/project/p06_qualified_warm_retention.py` | `4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe` |
| `ci/project/p06_qualified_warm_encrypt.py` | `4beadf5cd67fe8847fb00b881a45661e710b6275fb5d5e5baa0a52a1440de275` |

## Private artifacts

The structured report is
`/home/agent/ai-gpu-d37f66a85d88/notes/a35-post-publication-test-review.json`.
It includes both observed test outcomes, identities, traceback, source hashes,
command/environment, stable-source checks, and limitations.

| Artifact | SHA-256 |
| --- | --- |
| `notes/a35-post-publication-test-review.json` | `c419940b97152041ca0b9a1d8e49dd8b654a2c1c429900bf15d3ae528cbffc14` |
| `tmp/a35-post-publication/probe.py` | `7deb9b1f9a14cffb0d9ba9b85d96bdb92f9731e6613dc5979bb1f43b02d02b80` |
| `tmp/a35-post-publication/actual_replacement.log` | `5b05692b8e1a047980c8f9499143cfc7ecfe2f697be5521d6f11e601856a1dc7` |
| `tmp/a35-post-publication/setup_fault.log` | `1fe1b1047340d88d2a61609d9c919cc4d9129a5940a5a45e6337ad47d579fe92` |
| `tmp/a35-post-publication/reviewed-test.patch` | `76e9ffaabca70dce80aa9ad7452c5e23d554179b00a688e7421307f41a068f53` |

## Limits and handoff

The coordinator reports that hosted strict run `45575499141` on the published
revision failed in the original unheld directory-replacement subcase. A35 did
not independently inspect that hosted run's original logs or observe its inode
values. Inode reuse is therefore a supported explanation for the fixture's
vulnerability, not a retrospectively measured fact about that hosted failure.

The positive control establishes the intended replacement on this Linux
filesystem. The negative control covers one setup failure after callback
registration; static review establishes the same external-assertion placement
for the other sequential setup operations, but they were not individually
fault-injected. This focused evidence grants no full strict governance,
native, performance, or phase acceptance.

No additional test change is requested by this review. Combine it with A57's
independent production/contract review and the coordinator's one complete
restore-module execution before the coordinator's publication decision.
