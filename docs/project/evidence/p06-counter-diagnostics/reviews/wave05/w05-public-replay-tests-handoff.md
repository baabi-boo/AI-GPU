# Wave 5 public replay test handoff

Owner: `/root/w05_public_replay_tests`, agent 30 (wave 5, assignment 6).

Only repository file authored: `ci/project/test_p06_counter_public_replay.py`.
No reader/producer/record parser, production source, evidence ZIP or metadata was
modified. No native build, full test discovery, commit or push was performed.

## Executed result

Focused command from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -m unittest -v test_p06_counter_public_replay
```

The final run passed **11 test methods in 0.164 seconds** with zero failures and
zero errors. One class-level skip represents **29 additional methods not run**
because a genuine successful public packet is not yet available. There are 40
test methods in the file: 8 input/receipt/CLI methods, 3 failed-original methods,
and 29 pending original-success integration methods. A class-level skip is not a
passing native or replay result.

Final log:
`/workspace/scratch/98908dfa3444/w05-public-replay-tests-final.log`

Log SHA-256:
`8f4d3052cef22ac6fc06409dcb0c0a475dc6eb8380bf896cf83cfffe8e81bf72`

Test source SHA-256:
`0bcc97736f976849f71c981dd6cca4fb61572ca3d6f9160593f9669529926f7b`

An earlier 7-method run is retained separately in
`w05-public-replay-tests-initial.log`; it precedes four receipt-contract tests.
Eight raw model/public compiler-command mutation selectors were additionally
checked against the actual failed original's completed build logs. This was an
in-memory helper-selection check, not a successful replay or native execution.

## Original failed evidence

The immutable original is
`docs/project/evidence/p06-counter-diagnostics/native/run-45029135146-attempt1.zip`.
Its externally supplied SHA-256 is
`d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` and producer
revision is `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`.

The original report is finished/fail, with normal mode failed and four later
modes blocked. The normal log reports `terminal CP ring is not drained` and
contains no public result record. Model and public compiler summaries retain
45 and 19 translation units respectively, with four public links; these facts
do not convert the failed runtime packet into a passing diagnostic.

The actual replay rejects this ZIP with `producer outcome: value differs` while
process creation and ZIP extraction are patched to raise. Another executed test
rejects a wrong external ZIP digest before interpreting its failed report. The
failed artifact was never rewritten into a purported successful native fixture.

## Successful-original integration contract

Root agreed to create
`docs/project/evidence/p06-counter-diagnostics/native/public-runtime-pass.json`
only after retrieving a genuine complete successful original. Its exact fields
must be:

```json
{
  "archive": "run-<decimal-id>-attempt<positive-integer>.zip",
  "sha256": "<externally recorded lowercase 64-hex original ZIP digest>",
  "source_revision": "<actual lowercase 40-hex producer revision>"
}
```

The test fixture loader skips only when this successful-original receipt is
absent. An existing receipt with a missing ZIP, wrong digest, malformed external
revision, unsafe name or unexpected fields fails. The receipt loader's missing
ZIP/digest/revision behaviors were actually tested using intake-only mocks; no
synthetic complete native result was created.

The pending 29 methods cover original completion counts; all false acceptance
flags; rehashed public DMA before/attempted/after corruption; terminal selector,
component, half-read, clock, ownership, CP and destruction evidence; overflow
callback/suppression/fresh-context evidence; strict JSON types/keys; original
model summary recomputation; exact public DSO roles and five Processor wraps;
source/tool/configuration/object/binary before/after identity closure; 28 ordered
stability rows; full retained member/source inventory; external source/digest
mismatches; duplicate/unsafe/symlink ZIP members; and inert replay with retained
producer code poisoned while local digest-pinned parser import remains allowed.

One pending positive consistency test deliberately changes a reported Git tree
and an absent binary's consistent recorded hash. Its purpose is to preserve the
reader's documented distinction between internal consistency and independent Git
or binary authentication. It establishes neither execution nor source trust.

## Required next review

Root reports the CP repair changes public observations to **schema v2**. A later
agent must review these 29 pending methods against the genuine corrected packet
and rerun the complete focused file. Their assumptions are currently those of
the native-v1 reader: 676 source bodies, 14 commands, 6 cells, 9 binding groups,
28 stability rows, and the independently frozen source-name digest
`f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da`.

Do not weaken the source closure to admit a new checkpoint. Review any changed
inventory and schema explicitly with the reader author. The 11 executed tests
and 29 pending tests must remain separately reported until that work occurs.
