# Wave 8 public diagnostic design author handoff

## Scope and disposition

Completed the assigned documentation work only. Added `docs/designs/simx_counter_public_diagnostics_v1.md`; changed only the CP explanation and evidence-status portions of `docs/designs/simx_counter_lifetime_v1.md`. This is an author verification handoff for independent documentation review, not that independent review or an acceptance decision.

No production/test/reader code, source manifests, gates, phase status, backlog or native index was edited by this agent. No native build or execution, archive extraction, retained-code execution, commit or push was performed. Repo-backed documentation remains in the shared repository. The scratch files listed below are author verification inputs/receipts.

## Decisions recorded in the documents

- Kept native public packet `simx-counter-public-native-v1` / report schema 1, raw `COUNTER_PUBLIC_RESULT` schema 2, and public replay `simx-counter-public-replay-v1` / schema 1 separate. The all-33 model producer/replay contracts are identified separately.
- Bound native statements to original corrected producer `e5f152464dda5e488d6d1a030c1fcdc49b5a9701`, tree `74f5ce6e13d86d4f9a961c52aa9a04584a6ef0e8`, run 45031746149 / job 137236632765 / artifact 14758252829 and untouched ZIP SHA-256 `05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276`. The three-field pass file is a locator, not qualification.
- Preserved the earlier `81ed687` failure, its four blocked public modes and the distinction between an audit pass and native failure. Replaced the stale claim that corrected native intake is pending with the reviewed e5 result.
- Described actual Processor/RAM, all five GNU Processor wraps, exact scalar readback / gp=7 witness, sticky errors, no reentry and the separate real inverse-payload DMA/no-RAM-change check. The inverse payload has namespace-scope static storage lifetime.
- Recorded 45 initial model TUs, then 19 new public TUs, 44 reused model objects and four links with correct roles. Recorded 13 test process cases across the combined packet, all per-mode assertion counts, 10 constructions/disposals, seven terminal vectors, 462 successful half reads and one failed cache half read.
- Kept two unseeded normal contexts distinct from coherent/overflow seeds and all fresh independent controls. Explained exact terminal reference/queue ownership, CP-before-disable, unsupported head writeback, staged-low/committed-high raw tail, and the source-backed drain inference. Source proof still supplies the conditional no-later-update premise.
- Left 15 GiB reserve, 4 GiB memory/RSS, two jobs, one worker and CPython 3.12.14 native interpreter pin unchanged. Warm-v1 block, unestablished measurement no-wrap bound and all readiness/qualification/acceptance limits remain.
- Used current file paths and actual helper receipts for replay identity; no invented future reader commit or native result for a later documentation/reader checkpoint appears.

## Source and evidence verification

Read `AGENTS.md`, review policy, developer resource guide, current status/backlog/roadmap/acceptance, the all-selector design, lifetime source argument, actual producer/build/raw parser/replay implementations, public caller/hooks/makefile, workflow and production CP/runtime ownership code. Read `w07-native-public-audit.md` and both `w07-native-{corrected,failed}-receipt.json` files; confirmed their respective native outcomes are pass and fail despite both integrity audits passing.

Compared 16 implementation/workflow files byte-for-byte with immutable local Git blobs at e5: the four public C++/header/makefile inputs; three producer/build/raw-parser Python files; common device/perf/queue/refcount/async files; SimX backend and Processor; functional CP; and the native workflow. All matched. Later replay helpers are identified by their receipt bytes rather than attributed to the producer.

A direct comparison against `w08-lifetime-before.md` confirms the lifetime document's entire status/source/route/theorem/inventory portion before `Establishing the last valid observation`, and its entire finalizer/dependency argument, remain byte-identical. The only edited body paragraph before the evidence section is the permitted CP explanation. The final warm-caller obligations remain unchanged.

All 30 local links in the new public contract and all 46 in the lifetime document resolve. Both documents have LF endings, a final newline and no trailing whitespace. `git diff --check` passed; because these documents were initially untracked, explicit whitespace/link checks also covered their actual file bodies.

## CLI verification

Both actual `--help` outputs are retained. One useful initial probe failed closed with `archive path must be absolute and canonical without symlinks` when given a relative archive path; it created no passing receipt. The examples were corrected to derive an absolute source-root path with `pwd -P`. Output paths must be unused because the CLI uses exclusive creation.

The following real offline checks exited zero; no retained code was executed and no native commands were run:

| Check | Original producer | Result |
|---|---|---|
| All-33 original archive with external ZIP digest/revision | `407ab9fea5e4f793a2a5088f566a87f3e631aa84` | Seven cells, 17 commands, 270 retained source bodies, 25 current helper identities |
| Corrected public original with external ZIP digest/revision | `e5f152464dda5e488d6d1a030c1fcdc49b5a9701` | Six cells: one boundary control plus five public modes; 14 commands, 676 retained source bodies, 28 current helper identities |
| Corrected public original with paired external full source manifest and SHA-256 | Same e5 original | Six cells pass; `source_inventory_expectation.source=external-manifest` |

The optional manifest was generated independently of the archive from all 676 mandatory names and immutable e5 Git blob bytes using `git cat-file --batch`; it was never used to execute retained code. Its exact SHA-256 is `b5666ccb94fd71601d81539099817b8a156e41eec34ef31eb8c2fbd860b5a6df`. This exercises the documented optional CLI path; the author-generated manifest is not a separate native authenticity or dependency-provenance attestation.

The verified commands use the same interfaces/identities as the design examples, with unused output paths in this scratch directory. Every receipt keeps `native_execution=not_run`, `retained_code_executed=false`, `qualified=false`, `ready_for_warm=false` and all acceptance flags false. The public receipt rechecks 45 model TUs/one link and 19 public TUs/four links/44 reused objects. Original source-name inventories are 270 and 676; an external manifest cannot omit their required names. Missing half of the explicit manifest/digest pair is rejected by the documented shared reader check.

## Final file identities

| File relative to scratch root | Bytes | SHA-256 |
|---|---:|---|
| `AI-GPU/docs/designs/simx_counter_public_diagnostics_v1.md` | 20458 | `113eea8a116479dbbb678155988776928e8ccbe6fcac7546adaccd959d97b473` |
| `AI-GPU/docs/designs/simx_counter_lifetime_v1.md` | 24927 | `fd5518856d271622fa29e536ac264fb348a8a06931acd971f21360ff8101286a` |
| `w08-public-design-all33-replay.json` | 82526 | `7c5473b89ec5f501ed7e01b8f3448c8c487a8ab314287fdd94e14f21aac0c200` |
| `w08-public-design-public-replay.json` | 547313 | `2f862a8d317e33b9b0cde0b90ef2ee7eacf5e1d53acb3a43c2f39f55f096e658` |
| `w08-public-design-external-replay.json` | 547431 | `d5e9565c26d9876fec1937d2008280cbd4229ac4985374ce27a33d7ff2dc6428` |
| `w08-public-design-source-inventory.json` | 115698 | `b5666ccb94fd71601d81539099817b8a156e41eec34ef31eb8c2fbd860b5a6df` |
| `w08-public-design-all33-help.txt` | 1599 | `b6888c4f2099991599859069a498f665c025f281318bceb9d47cd411b676de87` |
| `w08-public-design-public-help.txt` | 1449 | `32bf33b4b714b82ffbd55f87dc5ffe7ba5b0853b5f58e1eb0481c390fb7aa389` |

## Remaining review boundary

Independent documentation review should check the native/replay/conditional-theorem distinctions and verify these exact document hashes. The replay receipts establish retained-data consistency only. Absent object/binary/library/tool payloads cannot be rehashed, cached dependency compilation origin remains unproven, and the complete warm caller is unqualified. This handoff makes no gate, readiness, warm performance, RTL, vendor or hardware claim.
