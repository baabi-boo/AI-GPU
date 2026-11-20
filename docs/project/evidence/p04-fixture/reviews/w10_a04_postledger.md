# Wave 10 assignment 4 — compiled-ledger follow-up review

**Disposition: approve the compiled sixty-agent ledger and the observed
60-artifact acceptance-packet delta. No new F2/F3 finding.**

Reviewer: `/root/w10_a04_final_agent_ledger`, continuing the same assignment.
This follow-up creates no additional agent and does not replace or modify the
original `w10_a04.md` receipt. Its SHA-256 remains
`390b502d1b11d8cf64e4772fe484b52d148ae96e894d2df364e9c218eb17ff4a`.

Observation: `2026-11-20T09:21:53.434274+00:00`.
The reviewed work is the uncommitted evidence/documentation follow-up to
qualified source `10ace66193686e3862c3c218760b66c044f1d4ae`.
No future child-commit identity, branch update or CI result is asserted.

## Compiled ledger verified against every original receipt

| Item | Observed result |
|---|---:|
| Distinct agent identities and completed entries | 60 |
| Distinct wave/assignment slots and original receipt filenames | 60 |
| Waves / assignments per wave | 10 / 6 |
| Exact portable receipt bodies matched | 60 |
| Raw and retained SHA-256 comparisons | 120 |
| Distinct raw hashes / distinct portable hashes | 60 / 60 |
| Markdown assignment rows matched | 60 |
| Confirmed sensitive or private-path marker hits | 0 |

The JSON ledger is **304,765 bytes**, SHA-256
`406c6c63ffa5fa53cd75b36fcb85c228bfbecfcd089f496322858fc88b57b875`.
Its metadata, exact entry fields, typed counts, unique identities, registered
slots, task labels, original filenames and `completed` statuses agree with the
final registry. Canonical reserialization reproduces the JSON bytes, detecting
unexpected duplicate-key or formatting ambiguity in this generated artifact.

For all sixty entries, I independently reread the original receipt, computed
its raw digest, applied the documented portable transformation, compared the
entire retained body, and recomputed the retained digest. Every comparison
passed. The transformation substitutes the three controlled workspace prefixes
and replaces transient sandbox links with their labels; it does not silently
rewrite the substantive receipt text. The Markdown table has exactly the same
sixty ordered assignments and task labels, and links the JSON payload.
The packet README links both ledger files.

Scanning covered the raw JSON, decoded receipt strings, ledger Markdown and
packet README. It found no confirmed credential prefix, private-key header,
signed-query token, transient local link or private machine path. Canonical
agent identities and generic path-category words are distinguished from
private path data. The earlier review's generic slash-separated scan-category
sentence contains no machine identifier and remains benign.

The original accounting receipt and all sixty input receipts stayed unchanged
through this follow-up. Registry and receipt files do not independently
authenticate historical tool sessions; the coordinator confirms the actual
successful spawns. This is not a claim of sixty simultaneous workers. Reusing
this agent for the follow-up does not increase the distinct-agent count.

## Exact change since the payload-portability snapshot

Relative to the 68-file `w10_a05.json` snapshot:

- **66 existing files are byte-identical**, with unchanged regular-file modes.
- The only changed existing files are the packet README and `acceptance.json`.
- The only new files are `agent-ledger.json` and `agent-ledger.md`, both regular
  UTF-8 files with mode `0644` and no NUL content.
- All **60 acceptance artifact hashes** match, with unique coverage of every
  current packet file except the acceptance record itself.

I reconstructed the preceding acceptance bytes by removing the two new ledger
entries and restoring the former README digest. The reconstructed SHA-256 is
`175e828ca57f2b181866e73a985747fa272afe9300d593834ef414b838f18cd3`,
exactly matching the payload review's prior acceptance identity. This proves
that no acceptance field, command, reviewer, limitation, source identity or
phase claim changed beyond the artifact-list update.

P04-A01 remains the only accepted criterion, at `design_review` /
`source_present` scope. The source revision remains the qualified implementation.
The ledger is work-accounting evidence; it does not add model execution, GPU
numerical proof, physical results or a new phase acceptance.

## Actual read-only validation and stability

Two narrow commands ran from the current source root with bytecode writing
disabled and a 60-second timeout each:

1. `python3 ci/project/check_project.py` — exit 0; project metadata validation
   passed, explicitly without GPU certification.
2. `python3 ci/project/p04_model_contract.py --check --json` — exit 0; the frozen
   source contract passes and still reports unavailable model execution and
   no GPU execution claim.

Exact arguments, raw stdout/stderr, exits and output digests are retained in
`w10_a04_postledger.json`. No test suite, compiler or GPU backend was run.
All reviewed ledger bytes, original receipt hashes, registry bytes, README,
acceptance record and sixty artifact digests remained stable after validation.

## Remaining coordinator work

Retaining this separate review creates later packet additions, so the
coordinator must refresh their artifact hashes and complete final validation,
actual committed-pair classification, non-forced expected-head publication and
remote readback. This review neither changes the original receipt nor claims
those future actions have completed. No repository, registry, ledger, Git
index or remote state was modified by this reviewer; only the two separate
scratch follow-up review files were written.
