# Agent 34 — contract conformance

## Disposition and scope

**No concrete contract incompatibility found. No normative contract revision or version bump is required.** Reviewed all six production diffs against `622662ad9cece6da4e3375be7e977dbe04cde862`, the continuation brief, execution/retention audit, current consumers, and prior source-scoped reviews. Production, contracts, proofs and tests were read-only. Owned outputs: this note and `agent-34.json`.

References below: **A** = `docs/designs/qualified_warm_automation_v1.md`; **R** = `docs/designs/qualified_warm_retention_review_v1.md`. Line references describe the unchanged contracts. Prior agents' executed results are supporting evidence, not tests rerun by this reviewer.

## Behavior-to-requirement mapping

| Changed behavior | Existing requirement and evidence/review |
| --- | --- |
| Acquisition checkpoint failure records `process_started=false`, completed cleanup and blocked command | A:72–81,105–108 require actual command outcomes and distinguish known prelaunch from unknown writers. The catch ends before `run_bounded`; earlier records/partial bytes remain. Independent Agent08 covers prelaunch and post-entry uncertainty; Agent04 reproduces failed transfers. |
| Supervisor checkpoint failure marks the stage unstarted; warm disposition becomes `not_run` | A:78–81,105–108. No child could execute before this checkpoint returns. Exceptions inside the executor still leave unknown launch observations. Agent08 independently verifies no fabricated warm report/log and retained completed-child bytes. |
| Failed hosted supervisor recovers finished native disposition | A:34–40,78–81 separate observed execution from successful orchestration. Recovery requires matching contract/revision, terminal receipt, stable selected sources and resolved writers. It never sets `native_success`; partial packaging and failed final outcome remain. Agent07 independently checks invalid receipts and ten unresolved-child cases. |
| Packaging binds the created output directory and anchors recovery | A:72,94–96,114–119 require exclusive private retention, byte verification and invocation/failure reconciliation. Repeated inode/mode checks reject observed replacement; recovery uses the held original directory, preserves unrelated replacements and retains failure evidence. Agent09 reviews replacement and withdrawal failures. |
| Encryption rechecks source/public/private directory ancestry | A:121–126,135–138,152–166 require validated encrypted publication and private failure retention. Checks precede age/publication, precede commit, and follow private cleanup. Existing commit ordering preserves the last ciphertext after a late failure. Agent11 independently checks displaced output with the private ciphertext link already absent. |
| Control finalization repairs only its owned receipt; close failures remain fatal | A:72–81,147–159 require truthful outcomes, preserved private originals and sanitized disclosure. Held-descriptor repair or checked inode/type/link/owner/mode reopening precedes truncation; archive and foreign replacements survive. Agent21's final lifecycle review covers the corrected recovery path. |
| Control write/readback errors use `storage_failed` | A:72–73,147–159 require actual outcomes without secret-bearing exception text. Existing allowlisted code replaces incorrect transport classification; readable partial identity remains retained. Agents06/13/21 document reproduction and final review. |
| HTTPS cleanup closes response and connection while preserving the active exception | A:72–73 require truthful failure/cleanup records. Both owned resources are attempted; cleanup cannot replace the primary storage/interruption failure. Agent21 reviews the final behavior after Agent12/13 follow-up. |
| Control/pack/encrypt traversal transfers ownership before parent close | A:72–73's cleanup obligation and private-output boundary. A consumed descriptor is not retried; the opened child is cleaned once, preserving unrelated reused descriptors and the original failure. Agent21 reviews control; Agent23 reproduces the sibling repairs. |
| Packaging setup covers acquired output before parent cleanup | Same ownership/cleanup obligation. A setup failure closes only the acquired output once and escapes before inventory. Agent30 independently validates both APIs and twelve lifetime cases. |
| Acquisition/run/hosted CLI SIGTERM handling and retained signal helper | A:72–81,128–138 require best-effort interrupted retention and source closure. Existing `KeyboardInterrupt` paths now cover between-command SIGTERM; monitor ownership and enclosing handlers remain intact. Agent15 independently verifies real-signal behavior and closure bounds. |

## Compatibility and limits

Static AST comparison found unchanged top-level assignments across the six helpers except run's addition of `xrt_signals.py` to operational `SOURCE_FILES`. Contract IDs, budgets and existing reason-code tables are unchanged. Encryption manifest construction, canonical JSON serialization, tar member generation/size calculation and ten-field public summary are structurally unchanged, matching R:38–127. Acquisition's explicit null launch intent uses the existing unknown-state meaning; it adds no successful-execution claim.

The unchanged hosted writer guard still rejects unknown outer/inner launches and unresolved cleanup. Upload still requires successful encryption invocation, validated summary/ciphertext/terminal records and workflow readiness; file existence cannot authorize it. Agent24 reviews that privacy boundary. R:15–36,199–208 still limits inspection/restoration to inert consistency: failed retained work remains failed, with no native/origin/acceptance promotion.

`agent-34.json` records exact current/base SHA-256 values, static comparisons and unchanged contract/reader/restore/workflow/proof identities. No tests, native execution, network actions, commits or publication were performed. Repeated observations provide neither hostile-writer exclusion nor crash atomicity. Final frozen-source strict governance remains required; this review grants no phase acceptance or native evidence.
