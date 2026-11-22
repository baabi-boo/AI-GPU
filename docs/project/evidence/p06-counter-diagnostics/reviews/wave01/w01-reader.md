# Wave 1 diagnostic reader audit

Audited clean `master` at `7455e008c1e001d3329e74fd55ffcd942592ec5f`. Read-only source audit; no native execution or qualification is claimed.

## Smallest useful implementation

Add a separately named **native counter diagnostic retained-data verifier**, for example `p06_counter_diagnostics_replay.py`, with its own contract ID. It should establish consistency of the new all-33 transport/public-failure evidence and attached terminal proof. Its successful result must still emit `native_execution="not_run"`, `qualified=false`, `ready_for_warm=false`, `performance_acceptance=false`, and `phase_acceptance=false`. The current five-cell prerequisite, warm-v1 analyzer/replay, cold acceptance and original archives remain historical and unchanged.

Do not turn this bounded reader into warm readiness merely by accepting a reviewer string or a `terminal=true` flag. A separate future pre-execution qualification binding must join reviewed premises to the actual seed-free measurement binaries and all 24 fresh processes. The existing `qualification_id` is only an execution-binding digest (`p06-mpm-qualification-plan.md:377–402`).

## Reuse and concrete hazards

- `p06_replay._archive_api()` loads the trusted, digest-pinned bounded `ArchiveReader` from the current repository. It never extracts members, accepts an externally supplied original ZIP digest, rejects unsafe/duplicate/special members and bounds sizes, counts and JSON structure. Reuse this reader rather than create another extraction path.
- `p06_replay._same`, `_fields`, `_integer`, `_timestamp` provide recursive exact-type checks. Use those semantics so `true` cannot substitute for integer `1`, duplicate JSON fields cannot disappear, and extra fields cannot hide unsupported claims.
- Reuse the trusted compiler token/syntax functions and `p06_compiler_records` configuration validation. Do **not** import or execute retained Python files, shell commands, binaries or archive-provided modules.
- **Do not call `p06_checked_execute.validate_build()` directly during replay.** It ends by hashing each original recorded object path with `native.file_identity()` (`153–202`); its path resolution also consults the current host. Separate pure compile/link parsing from live hashing, or write a narrow pure parser using `PurePosixPath`. Recorded absolute paths are labels, never local files to open.
- The checked runner's `source_snapshot()` retains `sim`, `sw/common`, `third_party/ramulator_ext` and its critical list. A new public diagnostic must additionally retain the actual `sw/runtime/common`, SimX backend and relevant AI caller/runtime files. Current retention is insufficient for a public-runtime lifetime claim.
- Native object/binary/tool/dependency payloads are currently recorded identities, not retained replay payloads. The reader can check internal identity consistency and before/after equality; it must not claim to independently rehash absent binary bytes or authenticate execution/origin.

## Strict packet contract

| Layer | Minimum check |
|---|---|
| External identity | Require explicit ZIP SHA-256, source revision and expected contract; verify archive bytes before parsing and again at close. Exact schema/contract IDs reject old 19-selector packets even if relabeled flags are added. |
| Execution scope | RV64 `p02-tfr`, timing mode, one simulation worker, PERF and TCU enabled, exact generated topology/feature exclusions including VM and CP-on-LLC off. Validate effective macros and original flags, not the profile name alone. |
| Source binding | Clean original revision/tree, initialized pinned submodules, complete required body inventory, original/final equality, and retained source digests; include wrappers and all actual runtime/compiler/helper bodies. Preserve the actual local versus published revision distinction. |
| Build binding | Parse every actual compile and one complete link per binary. Require exact object-to-source coverage; validate wrapper-to-included-production-source mapping; allow `-fno-access-control` only on an explicit diagnostic wrapper allowlist. Reject omitted/duplicate production implementation objects, mixed ordinary/checked TUs, unknown flags, and unrecorded libraries. |
| Tool binding | Before/after identities for compiler, linker, make, dependencies, PATH `python3` and actual executing interpreter. Enforce the hosted route's interpreter equality and exact executable used in each invocation. |
| Native results | Parse original logs afresh. Require the fixed ordered cell inventory, process started, exit zero, completed cleanup and bounded resource observations. A failed build, timeout, unrelated crash or self-reported pass cannot substitute for the required typed guard failure. Recompute counts and compare them with report summaries. |
| Selector transport | Exact 33 descriptor tuples and backing-source mapping, all ten frozen vectors, both orders of low/high reads, complete reconstruction and reset/carry evidence. Twelve unavailable rows must remain unqueried; zero-valued available TCU rows do not substitute for seeded transport. |
| Public failures | Distinguish real-model updater, real two-bank CSR aggregate and controlled/mock cells. Require exact error type/reason, protected source values, unchanged public destination on failure, persistent waits/query/launch rejection after queue error consumption, observed destruction and fresh-context success. |
| Terminal proof | Bind a separate reviewed proof artifact to exact source-body/dependency hashes and all 33 selector premises: zero origins, monotonic checked components, permitted resets, final successful aggregate read, exclusive owner, retired queues/CP work, zero pending balance, no post-observation ticks/updates and final disposal. Validate native observations against this fixed inventory; source proof remains a reviewer obligation. |
| Packet closure | Every consumed retained descriptor matches bytes; all required members exist; reject unexpected diagnostic-prefix members and trailing commands/results. Check fixed budgets and before/after stability. Original failures remain separate records. |

The proof attachment should list each premise and source path/digest plus review identity and scope. A parser can enforce completeness and identity, but cannot prove a mathematical argument or reviewer independence from arbitrary untrusted JSON. Independent source review must remain explicit in delivery evidence.

## Focused rejection tests

1. A complete synthetic packet passes only retained-data consistency and never gains warm/phase qualification; run with the original producer paths nonexistent to prove replay is inert.
2. Wrong external digest/revision/contract, truncated archive, unsafe path, duplicate member/key, boolean-as-integer, NaN, extra fields and unsupported schema fail.
3. Missing/duplicate selector or vector, wrong class/CSR/core, stale high half, zero-only TCU coverage, available row marked disabled, and queried unavailable row fail even after all affected hashes are recomputed.
4. Omitted real model TU, duplicated wrapper/base TU, `-fno-access-control` on ordinary/measurement code, checked macro missing or repeated, unknown linker object/library, source drift and mismatched executing interpreter fail after rehashing.
5. A mock public failure relabeled native, unrelated nonzero exit, timeout, absent typed failure, overwritten destination, revived context, unjoined work or missing fresh-context success fails.
6. Missing terminal row, leftover queue/reference/pending read, late aggregate overflow, absent finalizer proof or mismatched dependency/proof hash fails. A reviewer string alone never changes readiness.
7. Preserve old warm-v1 unconditional rejection with both favorable and unfavorable statistics. Do not add any acceptance adapter from old low-half evidence.

## Recommendation to root

Implement and review native all-33/public diagnostic producers first. If time permits this turn, add the narrow diagnostic replay above; otherwise retain an independently reviewed original packet and leave the new reader as the exact next bounded action. A prematurely permissive qualification reader would be worse than a clearly scoped verified diagnostic step.
