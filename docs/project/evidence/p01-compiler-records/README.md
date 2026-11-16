# P01 compiler-record tooling evidence

This packet records verification of the shared [compiler-record
contract](../../p01-compiler-records.md) and its preparation/execution callers.
It supports the bounded P01-T05 tooling correction. It supplies no new GPU,
vendor-emulation or physical-device execution, and does not accept P01-A03.
The [verification index](verification.json) identifies the retained files by
SHA-256 and byte size; the [handoff](../../p01-compiler-records-handoff.md)
records review dispositions and delivery state.

## Exact execution checkpoints

| Observation | Revision | Result |
|---|---|---|
| Starting tooling baseline | `97405322dfcb2944d50eb285008725f79eb733d8` | 1,075 tests passed |
| Compiler-record implementation | `f11190c87778ef049237650bbba4234ca62026b2` | 1,120 tests passed; zero failures, errors or skips |

The implementation tree is `36335b94da7392e4c5fd24618d4ce85addbf2d20`.
The full suite ran from a clean checkout, remained clean afterward, and retained
unchanged hashes for all 93 selected project Python source files. Its wall-clock
duration was 137.897 seconds; unittest reported 137.649 seconds. These measure
different intervals. Later documentation and publication commits are not
relabeled as executions of this checkpoint.

The command, run from the source root, was:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

Read [implementation metadata](implementation-tests.json) with its
[original log](implementation-tests.log), and [baseline metadata](baseline-tests.json)
with its [original log](baseline-tests.log). Absolute checkout, interpreter and
log paths inside the metadata describe the execution environment at that time;
the adjacent published files are the reviewable copies. Reproduction uses the
named revision and source-root command, rather than assuming those machine
paths still exist.

### Recover the tested local commit

The tested local commit is not an ordinary remote commit. Published implementation
[`623544c`](https://github.com/baabi-boo/AI-GPU/commit/623544cdd51f9c70a4e2fcef29ed3b56d8cce3fe)
has the identical tree and parent; the [publication map](publication-map.json)
records both identities. The [retained local commit](local-implementation.commit)
contains the original commit object's exact bytes.

From the repository root of a full clone containing that published implementation
and this evidence packet, import the local commit object:

```sh
git hash-object -t commit -w --stdin \
  < docs/project/evidence/p01-compiler-records/local-implementation.commit
```

The command must print `f11190c87778ef049237650bbba4234ca62026b2`. It writes only
the Git object; it moves no branch and changes no working files. Preserve the
retained file's exact bytes and verify the printed identity. Obtain the complete
published source tree and parent objects before checking out the recovered
revision. The original 1,120-test execution remains attributed to this local
commit; recovering it does not constitute another test run.

The tests include actual host-preprocessor observations, actual generated Make
stamp recipes, invalid-input checks, launch prevention and retained-helper drift
checks. Stamp-target tests do not compile the application or kernel; runner
orchestration tests use inert command fixtures. The
[governance record](w05f-governance.json) separately records passing preflight and
project checks. [Historical compatibility](historical-compatibility.json) retains
the earlier dirty-worktree observation and verifies 228 protected baseline files;
that observation is not presented as the clean implementation test run.

The later [hosted-CI observation](code-ci-final.json) confirms successful Project
Governance on published implementation `623544c`, including 1,120 tests in
178.162 seconds. This is a separate hosted execution; the local checkpoint's
result and timing remain unchanged. The general CI workflow was still queued
at that observation. [Release invariants](release-invariants.json),
[resource observations](resources-final.json), and
[documentation checks](documentation-governance.json) retain their own scopes
and timestamps.

## Classifier filenames

The immutable-base classifier reported **R1**, with no contract or evidence
findings. Its original metadata remains byte-for-byte preserved. The relative
names inside `change-impact-summary.json.records` refer to the original scratch
layout; use this explicit publication mapping here:

| Original filename | Published file |
|---|---|
| `commands.json` | [change-impact-commands.json](change-impact-commands.json) |
| `extraction.json` | [change-impact-extraction.json](change-impact-extraction.json) |
| `classify.json` | [change-impact-classify.json](change-impact-classify.json) |
| `explain.txt` | [change-impact-explain.txt](change-impact-explain.txt) |
| `summary.json` | [change-impact-summary.json](change-impact-summary.json) |

The verification index also records this mapping. Renaming the published copies
does not change their bytes or reinterpret the classifier's result.

## Remaining vendor prerequisite

The later [read-only probe metadata](vendor-probe.json) and
[original probe output](vendor-probe.log) record exit code **1** and outcome
**blocked**. Required vendor executables and roots were unavailable, and a
qualified platform/artifact packet still requires independent review. This is
the expected prerequisite outcome, not a failure of the passing tooling suite.
The probe records documentation changes separately and verifies that the Python
source still matches the implementation checkpoint.

Source hashes establish retained source identities and drift observations. They
do not authenticate stamp production, prove binary provenance, or attest the
interpreter, loaded code objects or bytecode caches. Historical export checks
likewise do not prove original raw-log authenticity or redaction relationships.
P01-A01/A02 retain their earlier accepted evidence; P01-A03 remains blocked and
P02 remains not started.
