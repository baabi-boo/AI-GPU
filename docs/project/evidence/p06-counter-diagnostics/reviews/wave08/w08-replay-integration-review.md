# W08 independent R3 replay inventory integration review

## Verdict

**No F2/F3 finding. High confidence.** The exact reader and integration-test
identities below are suitable for the proposed replay-code/evidence checkpoint
within the reviewed retained-data consistency scope. This is independent
advisory R3 review by agent 44 (`/root/w08_replay_integration_review`), who did
not author or edit the repository changes. It is not a maintainer approval,
waiver, native execution, qualification, warm-readiness decision, or phase or
performance acceptance. The source-inventory helper has its own independent
agent-43 review; this report checks its integration into both readers.

No finding severity is assigned to a nonexistent defect. The conclusions below
have high confidence from static inspection of the complete reader/integration
test files and executed positive and rejection checks. No F1 defect was found.

The review read `AGENTS.md`, `docs/review/code-review-policy.md`, the current
project/roadmap/backlog/acceptance context, and the author-40 handoff. Repository
HEAD was `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`. The reviewed replay files
were untracked at review time, so these content identities, not HEAD alone,
identify the changes. They were rechecked after the test run.

| Reviewed file | SHA-256 |
| --- | --- |
| `ci/project/p06_counter_diagnostics_replay.py` | `4d959363229859bd1ac5f4ede4f09937b8418e50f85a1c2eab3f131956532f0b` |
| `ci/project/p06_counter_public_replay.py` | `6489dff8b39bda3d18df97fb72092fd2014d86d8c0129bcd56a13f08acd942a0` |
| `ci/project/test_p06_counter_inventory_replay.py` | `c710288b344930cb3f0a9ca6b8092c87f4ae71fbc0952cdf712d4627892290c9` |
| Integrated helper, separately owned | `8961331993ceb112f80a83314ee7a6a3020163a89ca1b8781139c103e98f6862` |

## Actual execution and source bindings

The final command, run from the source root with bytecode writes disabled, was:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -B /workspace/scratch/98908dfa3444/w08-replay-integration-review.py
```

Output was retained in `w08-replay-integration-review.log`. The final command
exited **0**. This was bounded host-side replay and Python test execution; no
native diagnostic was rerun.

| Executed suite | Methods | Subtests | Failures / errors / skips | Duration |
| --- | ---: | ---: | --- | ---: |
| Existing inventory integration regressions | 23 | 47 | 0 / 0 / 0 | 3.966 s |
| Independent genuine-public integration review | 14 | 63 | 0 / 0 / 0 | 20.695 s |
| Total | **37** | **110** | **0 / 0 / 0** | **24.661 s** |

The independent harness has one full positive public case that executes both
reader routes and several other complete successful public runs for CLI,
output, closure, and filesystem guards. Its negative cases do not fabricate a
successful native producer outcome.

| Original ZIP | SHA-256 | Source revision | Review treatment |
| --- | --- | --- | --- |
| `run-45026112992-attempt1.zip` | `c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f` | `407ab9fea5e4f793a2a5088f566a87f3e631aa84` | Original all-33 checked packet; existing integration suite passed legacy and exact external paths |
| `run-45031746149-attempt1.zip` | `05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276` | `e5f152464dda5e488d6d1a030c1fcdc49b5a9701` | Genuine corrected public packet; independently passed complete legacy and exact external paths |
| `run-45029135146-attempt1.zip` | `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5` | `81ed6871634fefbf5c78fb27cf10dce913bd4d9c` | Original public failure; both paths rejected `producer outcome` |

The successful-original intake receipt was checked to contain exactly its
three intended fields, matching the e5 original filename, digest, and source
revision. Each original ZIP byte digest was verified before report loading.

### Separate immutable Git comparison

The public manifest used for interface testing was first constructed by copying
the genuine report's complete `source_before.files` descriptors. That act alone
is only a synthetic expected-input wiring check and supplies no independent
authentication.

Separately, the reviewer used read-only `git cat-file --batch` requests of the
form `e5f152464dda5e488d6d1a030c1fcdc49b5a9701:PATH` for **all 676 paths**.
For each response, the reviewer required a Git blob, recomputed its SHA-256 and
byte length, and compared its bytes directly with the retained archive body.
**All 676 descriptor and retained-body comparisons matched; no mismatch or
missing blob occurred.** The immutable source tree is
`74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`. The complete name digest is
`f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da`.
The per-file Git blob IDs, hashes, lengths and paths are retained in
`w08-replay-integration-public-git.json`.

This separate local Git comparison establishes the claimed source-byte mapping
at that immutable commit. It does not independently authenticate remote GitHub
origin, absent binary or object payloads, or native execution.

## Verified integration behavior

### Exact opt-in and no invalid fallback

Both API signatures and both CLI parsers accept the same optional manifest
path/digest pair. The pair check explicitly uses `None`, so omission is distinct
from empty or invalid supplied values. Missing either half rejected before
archive access in both APIs and both CLI paths. Wrong manifest byte digests,
mistyped or malformed digests, wrong revisions, wrong producer contracts,
missing files, symlinks, empty files, malformed JSON and duplicate JSON fields
all rejected. There is no catch-and-continue or fallback from a selected invalid
manifest to the legacy inventory route.

The exact descriptor comparison receives the entire report source list, not
only compiled translation units or a selected subset. Public tests rejected
changed descriptor hash and size, and rejected a complete failed-public source
manifest whose revision label was altered to e5. Thus equal names and a matching
revision label cannot replace exact expected descriptors. Both an uncompiled
header and an original helper body remained mandatory, even when removed from
both the public packet and selected manifest.

The legacy name pins remain unchanged:

| Producer route | Count | Source-name SHA-256 |
| --- | ---: | --- |
| Checked native v2 | 270 | `d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108` |
| Public native v1 | 676 | `f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da` |

The existing integration suite also verifies an explicitly labeled synthetic
checked packet with an added inert helper: it rejects the legacy and wrong
manifest paths, and passes only the complete matching manifest. Its added
source body raises if executed; the execution guard did not trigger.

### Trusted reader closure and bounded filesystem access

A recursive AST inspection of repository-local imports found exactly **25
checked reader source files** and **28 public reader source files**. Each
reported `_reader_sources()` inventory exactly covered its transitive local
Python import set, with no missing or duplicate entries. In particular, the new
source-inventory helper and `baseline_packet_io.py` are covered by both readers.
The existing archive parser remains separately pinned to its reviewed digest.

For every one of the 28 public-reader closure files, the reviewer simulated a
changed byte observation immediately after manifest loading. **All 28 complete
public replay attempts rejected trusted reader source stability.** These checks
changed no actual repository file. The authored suite separately checks the
checked route for helper and packet-I/O drift.

A public manifest was atomically replaced with identical bytes while its file
descriptor was being read. The read rejected the changed named-file identity;
matching bytes alone did not hide the replacement. This is a concrete bounded
swap check, not a claim to defeat a malicious concurrent writer generally.

A complete successful externally pinned public replay also ran inside explicit
filesystem and execution guards. The guard allowed only the selected archive,
selected manifest, current trusted reader sources, their directory traversal,
and execution of the current pinned archive parser. It prohibited unrelated
path access, discovery, writes, subprocesses/native execution, archive
extraction, native build/source-snapshot routines, and execution of retained
code. The run passed and actually opened both explicitly selected data files.

### Existing validation, exact integers and output behavior

Manifest matching did not replace retained source-body hashing: changing an
uncompiled public header body without changing its descriptor rejected.
The existing integration suite also confirms that missing compiler-log commands
and source-before/after disagreement still reject with a valid manifest.

Complete genuine public replay via both routes produced:

- 676 retained source files, 14 commands, 6 cells including 5 public scenarios;
- 45 model translation units, 19 public translation units and 44 reused model
  objects;
- the same exact recomputed public observations, including integer seeds
  `18446744073709551615` and `18446744073709551613`;
- successful JSON round trips with no change to integer values or types;
- identical results after removing only `source_inventory_expectation`.

The new expectation receipt accurately identifies `original-inventory` or
`external-manifest`, the selected manifest path and supplied byte digest, the
matched source count, and the name digest. It explicitly states that caller
expectations and matching revision labels do not independently prove Git/GitHub
provenance, binary contents or execution. The preexisting top-level
`source_inventory_sha256` still means the source-name digest, distinct from the
manifest byte digest.

The public CLI was exercised both in-process and as an actual current Python
process. The complete external path returned exit 0 and a nonqualifying result.
Partial-pair failures returned exit 1 with explicit reasons and false claims.
`--output` wrote the full manifest receipt and false claims; trying the same
existing output path returned failure and preserved its bytes.

For successful results and handled CLI failures, `native_execution` remained
`not_run`; qualification, readiness, warm execution, acceptance, phase and
performance acceptance, full warm coverage, and retained-code execution flags
remained false.

## Review-harness correction

The initial reviewer run used an incorrect new assertion expecting 36 reused
model objects. The genuine packet and existing public completeness contract
require 44. Only that assertion in the outside-repository review harness was
corrected to 44. No repository implementation, source fixture, existing test,
producer record, or archived evidence was changed. The initial log and JSON
receipt remain available under `w08-replay-integration-review-initial.*`.
The final complete rerun passed all 37 methods and 110 subtests.

## Scope limits

This review did not perform a native build or diagnostic execution, full test
discovery, a fresh remote-source-origin audit, archived-code execution, a
repository edit, commit or push. The parent-reported 43 checked replay methods
and 40 public replay methods are not represented as independently rerun here;
this report counts only its own 23 existing integration and 14 additional
methods. Earlier base-reader reviews and agent 43's helper review remain
separate evidence.

The replay interface establishes retained-data consistency. Even a digest-pinned
manifest may express deliberately fabricated expectations. The external digest
is an explicit caller trust input, and this integration does not promote it to
proof of execution or qualification. Before/after checks remain limited against
malicious concurrent mutation, as disclosed by the implementation.

## Retained artifacts

All paths below are under `/workspace/scratch/98908dfa3444/`.

| Artifact | SHA-256 |
| --- | --- |
| `w08-replay-integration-review.py` | `25cd2c2028ff4194b631f5a96660ebf8bb0e5c71dcd2e080acb8b119ccb3fa56` |
| `w08-replay-integration-review.log` | `38c0fa19cbfd84c7ea6f30cb618249801cae23e4814e46e335eb6908777fd4f9` |
| `w08-replay-integration-review.json` | `a4df8b1cb9a5730224806ce8279b157dcd5e2c45fb032d4ca835677c59afb647` |
| `w08-replay-integration-public-inventory.json` | `030470cc34dfc7fd39394fbc0ab7f9a235e5eead199399af3c868a335869f448` |
| `w08-replay-integration-public-git.json` | `6a405f439d69db076d39728fa205afe8757815b1500e5d2219523945396ae8d7` |
| `w08-replay-integration-public-legacy-result.json` | `382d3317d16cb87e5531c33922e10f3c0db112eeefc4ea77113ad8c076a1f4c3` |
| `w08-replay-integration-public-external-result.json` | `d6eaf694f19093785ca4b5e245066160db4a6e9dc94117d9125890822580b337` |

The saved manifest is an exact-byte copy of the test's selected temporary
manifest; its digest matches the external result receipt. The temporary path
recorded by that result is the actual path supplied during the test, and is
intentionally not rewritten afterward. The machine receipt additionally retains
all 25/28 reader source descriptors, per-suite counts, command, precise limits,
and the initial-run artifact hashes.
