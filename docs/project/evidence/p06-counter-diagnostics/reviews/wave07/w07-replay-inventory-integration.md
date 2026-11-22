# W07 replay source-inventory integration

## Disposition and ownership

Agent `/root/w07_replay_inventory_integration` (agent 40, wave 7) integrated the optional caller-pinned source manifest into the two inert replay readers. The implementation and its new focused tests pass the bounded checks below. This is author verification, not independent approval of these reader changes; root has reserved independent review for wave 8.

Repository: `/workspace/scratch/98908dfa3444/AI-GPU`. Inspected HEAD: `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`. These new reader files are untracked inputs, so their content identities below identify the change more precisely than HEAD alone. `AGENTS.md`, the code-review policy and current project/status/roadmap/backlog/acceptance context were read. The added external validation interface requires independent review; no waiver or qualification was claimed.

Only these repository files were edited by this agent:

- `ci/project/p06_counter_diagnostics_replay.py`
- `ci/project/p06_counter_public_replay.py`
- New `ci/project/test_p06_counter_inventory_replay.py`

The existing checked/public replay tests, the source-inventory helper and its independently owned tests, all producer/native code, evidence originals, workflow files and acceptance metadata were not edited. Reviewer 37 was notified before reader edits and received the final reader hashes. Agent 41 received the final hashes before running its public-focused tests.

## Implemented interface and preserved checks

Both `replay_archive(...)` functions now accept the keyword arguments `source_inventory=None` and `source_inventory_sha256=None`. Both command lines accept `--source-inventory` and `--source-inventory-sha256`. These are all-or-none, using explicit `None` checks; an empty or invalid supplied value is not treated as omission. A partial pair fails before archive access.

Any supplied manifest is loaded through `p06_counter_source_inventory.load_source_inventory` with its independently supplied SHA-256, the caller's expected source revision, and the exact checked/public producer contract. Loading occurs after the trusted reader source snapshot and before report interpretation. The helper therefore participates in the existing before/after reader-source closure across manifest loading and archive validation. An explicit load, parse, digest, schema, revision or contract error propagates; there is no fallback to the original inventory.

For a validated external manifest, `DiagnosticPacket.source` calls `validate_archive_sources` on the entire `source_before.files` list. Every path, SHA-256 and byte count must equal the manifest's complete ordered descriptors. The helper also retains every original mandatory source name, including uncompiled headers and original helper bodies, and bounds additions to its reviewed roots. The existing `SOURCE_REQUIRED` coverage remains in place.

When no manifest is selected, the original reader behavior and name pins remain unchanged:

| Producer | Original count | Original names SHA-256 |
| --- | ---: | --- |
| `simx-checked-counters-native-v2` | 270 | `d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108` |
| `simx-counter-public-native-v1` | 676 | `f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da` |

Both routes retain the previous raw retained-member hash/length validation, complete archive-member closure, source-before/after checks, clean checkout/revision/tree/submodule metadata checks, frozen profile identity, configuration expansion/copy checks, original compiler-log parsing, build/object/source summaries, command bindings, observations and nonacceptance invariants. Producer paths and manifest source descriptors remain inert data.

The helper `ci/project/p06_counter_source_inventory.py` was added to `_reader_sources`, which is already included in public replay's closure. `baseline_packet_io.py` remains in that closure. Both are identified in the result and checked again before success. The separately loaded archive parser remains pinned to its existing reviewed hash.

Successful results now contain `source_inventory_expectation`:

| Field | Original inventory | Explicit external manifest |
| --- | --- | --- |
| `source` | `original-inventory` | `external-manifest` |
| `manifest_path` | `null` | Exact selected path text, without resolving producer paths |
| `manifest_sha256` | `null` | Caller-supplied manifest byte digest |
| `source_files` | Original source count | Exactly matched complete source count |
| `source_names_sha256` | Original name pin | Digest of the complete matched names |
| `trust_boundary` | Reader pins names; retained bodies establish archive consistency | Caller pins complete expected descriptors; labels do not prove Git/GitHub provenance, binary contents or execution |

The existing top-level `source_inventory_sha256` continues to describe the complete name list. It is not relabelled as the external manifest byte digest. The public reader's obsolete claim that every later inventory requires changing its code was replaced with the explicit original/default and external/opt-in behavior.

Every success and CLI failure keeps all qualification, readiness, warm execution, acceptance, phase/performance acceptance and retained-code execution flags false. `native_execution` stays `not_run`.

## Focused verification

Final command, from the source root:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -m unittest test_p06_counter_inventory_replay test_p06_counter_diagnostics_replay -v
```

Result: **66 test methods passed, 0 failures, 0 errors, 0 skips**, in 23.666 seconds. This comprises **23 new inventory integration methods** and **43 existing checked replay methods**. Full discovery was not run.

The focused suite covers:

- The unchanged original checked ZIP passing without a manifest, with its exact 270-name pin and existing 17-command/7-cell/45-TU-per-variant result.
- The same original passing with a fully matched externally pinned manifest and an explicit path/digest/count/trust receipt.
- A synthetic later revision with an additional legitimate helper body and updated source/log/ZIP hashes failing without an external manifest and with the wrong complete manifest, then passing only with the matching externally pinned complete manifest. This is a consistency fixture; the added helper deliberately raises if executed.
- The original public packet's source-only manifest validation and an added-helper source-only comparison, with the original failed outcome preserved. Full public replay rejects `producer outcome` with or without a matching manifest.
- Both missing option-pair directions, wrong and mistyped digest, wrong revision, wrong producer contract, missing original uncompiled header/helper, omission from both manifest and packet, descriptor hash/size mismatch, malformed/missing/symlink manifest and no fallback.
- Raw retained source-body corruption, a rehashed missing compiler command and changed source-before/after metadata still failing after valid manifest checks.
- Both helper identities appearing in both reader closures, and simulated helper/`baseline_packet_io` byte drift during manifest loading rejecting success.
- Both CLI argument parsers, partial-pair failures before archive access, output report receipt/nonacceptance fields, and a guarded complete checked replay with manifest loading. The guard permits only the selected ZIP, selected manifest, current trusted-reader files and their directory traversal; it prohibits unrelated paths, writes, filesystem discovery, subprocess/native execution and archive extraction. Only the existing pinned current archive parser may be executed.

The first development-only run exercised 23 new methods and reported one assertion-message mismatch: the raw-byte corruption correctly rejected with `retained descriptor hash or size differs`, while the new test expected a different phrase. Only the expected error phrase was corrected. The final 66-method run above passed; no implementation fallback or validation weakening was introduced.

Two actual CLI processes were also invoked, using the current trusted scripts and explicit digest-pinned manifests:

| Script and original | Expected / observed exit | Result |
| --- | ---: | --- |
| Checked reader, `run-45026112992-attempt1.zip` | 0 / 0 | Consistency pass, 270 manifest sources, all false claims and `native_execution=not_run` |
| Public reader, failed `run-45029135146-attempt1.zip` | 1 / 1 | `producer outcome: value differs`, 676 manifest sources, all false claims and `native_execution=not_run` |

Exact command arrays, manifest/result digests and exit codes are in `/workspace/scratch/98908dfa3444/w07-replay-inventory-cli-checks.json`. These manifests were generated from already digest-checked original report descriptors solely to test the caller-supplied input wiring. They are not separately authenticated Git manifests or source-tree proofs.

The checked original ZIP's SHA-256 is `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f`, source revision `407ab9fea5e4f793a2a5088f566a87f3e631aa84`. The failed public original ZIP's SHA-256 is `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5`, source revision `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`. These original identities were verified before fixture loading.

Syntax parsing and a direct trailing-whitespace/final-newline check passed for the changed files and referenced helper/test identities. `git diff --check` also returned zero, but these untracked files are not inspected by that command alone; the direct check is the substantive whitespace evidence.

## Content identities

| File | Before SHA-256 | Final SHA-256 |
| --- | --- | --- |
| Checked replay reader | `6284fda2985533e327bddcfa02c2341b8f7c17b1ba123d0a66b3d263187e5b75` | `4d959363229859bd1ac5f4ede4f09937b8418e50f85a1c2eab3f131956532f0b` |
| Public replay reader | `6a89c103f7e2bc79b0f51af44754bf378f87ac1ffc847dafe0edc67a5066c18b` | `6489dff8b39bda3d18df97fb72092fd2014d86d8c0129bcd56a13f08acd942a0` |
| New inventory integration tests | New file | `c710288b344930cb3f0a9ca6b8092c87f4ae71fbc0952cdf712d4627892290c9` |
| Source-inventory helper, unchanged | `8961331993ceb112f80a83314ee7a6a3020163a89ca1b8781139c103e98f6862` | Same |

Detailed bytes/lines/method counts are retained in `/workspace/scratch/98908dfa3444/w07-replay-inventory-integration-checks.json`. The final focused log is `/workspace/scratch/98908dfa3444/w07-replay-inventory-integration.log`.

## Separate independent review performed

At root's request, this agent independently reviewed agent 41's bounded changes to `ci/project/test_p06_counter_public_replay.py`, without editing that file. This is separate from author verification of this agent's own reader integration. The review found no F2/F3 defect in agent 41's changed hunks, confirmed that the genuine-original intake requirement was unchanged, and independently rejected 116 raw record corruptions while exercising the actual six mutation method bodies and three no-op controls: 9 methods, 103 subtests, no failures/errors/skips. The reviewed test-file SHA-256 is `6d9c4c541a0e68acd021a3d2bf3ffb989ed4300b8339314e80551947498df6e0`.

The separate receipt is `/workspace/scratch/98908dfa3444/w07-public-replay-test-delta-review.md`, with `.py`, `.log` and `.json` supporting records. It does not independently approve the reader integration authored here.

## Limits and next action

No native build or execution, full test discovery, archived-code execution, commit or push was performed. No source-inventory helper or producer edit was made. No successful public archive or native outcome was fabricated. The corrected genuine public retry and its complete positive-original tests remain a separately owned intake/execution task.

An externally pinned manifest can describe internally consistent synthetic or forged data. It supplies expected source descriptors, not independent Git/GitHub provenance, absent object/binary authentication, a complete counter-lifetime theorem, warm readiness, hardware evidence or phase/performance acceptance. Before/after observations are not a defense against malicious concurrent writers.

Next bounded action: independent wave-8 review of these exact reader/test hashes, followed by root's chosen genuine public intake and focused replay checks. The new CLI option pair supports later complete inventories without weakening the frozen no-manifest route or original mandatory coverage.
