# P06 execution and retention continuation

This packet records the 2026-11-25 continuation from
`622662ad9cece6da4e3375be7e977dbe04cde862`. The
[audit](../../p06-execution-retention-audit.md) explains the development decision,
reproduced failures, fixes and remaining native action. The
[operator guide](../../p06-hosted-warm-guide.md) gives the execution and private
retention procedure.

Scope: orchestration, failure accounting and private evidence retention. The
frozen qualified warm experiment remains unstarted. This packet establishes no
native execution, performance acceptance or phase closure.

## Collaboration and independent review

The [completed-assignment ledger](agent-ledger.md) and
[machine-readable ledger](agent-ledger.json) record **all 60 completed assignments**.
Every worker started with a separate fresh context; three workers could run
concurrently. Root coordinated file ownership, integration and publication.
Reports retain the exact source identities they reviewed. A later change does
not retroactively extend an earlier review or successful check.
The [packet inventory](files.json) records the size and SHA-256 of every other
file in this packet. The [final release review](agents/agent-60.md) covers the
publication procedure and its remaining exact-revision CI obligations.

| Implementation boundary | Implementation and reproduction | Independent review |
| --- | --- | --- |
| Hosted failed-native disposition | [01](agents/agent-01.md) | [07](agents/agent-07.md), [34](agents/agent-34.md) |
| Supervisor and input launch checkpoints | [02](agents/agent-02.md), [04](agents/agent-04.md) | [08](agents/agent-08.md) |
| Packaging directory identity and recovery | [03](agents/agent-03.md) | [09](agents/agent-09.md) |
| Encryption path identity and last-copy retention | [05](agents/agent-05.md) | [11](agents/agent-11.md), [24](agents/agent-24.md) |
| Control transport, storage and receipt finalization | [06](agents/agent-06.md), [13](agents/agent-13.md), [16](agents/agent-16.md) | [12](agents/agent-12.md), [21](agents/agent-21.md) |
| Scoped operational SIGTERM handling | [10](agents/agent-10.md) | [15](agents/agent-15.md), [33](agents/agent-33.md) |
| Consumed directory descriptor ownership | [21](agents/agent-21.md), [23](agents/agent-23.md) | [21](agents/agent-21.md) reviewed the root control fix; [27](agents/agent-27.md) reviewed the sibling fixes |
| Packaging output acquisition lifetime | [28](agents/agent-28.md) | [27](agents/agent-27.md) preserves the failure; [30](agents/agent-30.md) reviews the repair |
| Final packaging output-close exception precedence | [47](agents/agent-47.md) reproduces the F2; [48](agents/agent-48.md) repairs it | [49](agents/agent-49.md) verifies the correction with the unchanged six-case probe and seven passing test methods |

Failed reproductions remain in the packet, including the control-closeout
failures, the packaging setup leak and the final output-close masking failure.
Agent 47 reviewed all 65 production-diff hunks at the historical 22-file snapshot;
Agent 49's independent review resolves the final-close F2 on the corrected
packaging source. Their later repairs and successful independent checks are
distinct evidence. No waiver or native acceptance is implied by a completed
review.

Nine original logs and patches contain trailing whitespace, including blank
context lines required by unified diffs. They are stored as deterministic gzip
files without changing their original bytes. The
[lossless storage map](raw-log-storage.json) maps each original logical filename
to its `.gz` companion and records both original and stored sizes and hashes.
References in the historical reports to those uncompressed names refer to the
bytes obtained by gzip decompression; every round trip was checked byte-for-byte.

## Publication source

The [publication source snapshot](validation/publication-source-freeze.json)
binds **23 files** after the final output-close correction. Its SHA-256 is
`6c90e8e2c097b1d8db3534835d4f8ae94c4f6dc2c20b1c59283342c0b1c2dbf8`.
The corrected packaging helper is
`585341fd1a7734f06468d8ca25ad8d9f4dc2a08dc861111e98c94e3cf4028134`;
the new final-cleanup regression module is
`fe8a7835b51d132f286f5f3e453d873ac52408b7b0ab59f5c5eebd58de3484af`.
The [historical 22-file snapshot](validation/operational-source-freeze.json)
remains byte-for-byte unchanged at SHA-256
`714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb`.
The later snapshot changes only the packaging helper and adds its new regression
module; it does not extend earlier validation to those new bytes.

## Validation scope

| Evidence | What actually ran | Limit |
| --- | --- | --- |
| [Focused invocation on the publication source](agents/agent-50.md), [exact command/IDs/events/hashes](agents/agent-50.json), [complete log](agents/agent-50-tests.log) | One invocation: 26 modules, 328 distinct test methods passed in 73.452944 seconds; zero failures/errors/skips, exit 0 and stable source snapshots | Focused development check at the 23-file publication source; not complete strict qualification |
| [Canonical collection on the publication source](agents/agent-51.md), [comparison](agents/agent-51-population.json), [ordered IDs](agents/agent-51-discovered.json) | 5,167 unique IDs; all 5,114 base and 5,164 prior candidate IDs retained in original relative order; 53 additions across 15 modules against base, including 3 since the prior collection; no duplicates, loader errors or active skip flags | Collection only; no test bodies or fixtures executed |
| [Independent final evidence reconciliation](agents/agent-53.md), [checks and identities](agents/agent-53.json) | Reconciles 328 method IDs, 984 ordered parent events, the 5,167-ID population and final source bindings; all recorded checks pass | Read-only evidence review; the reported aggregate of 645 successful subtests and their individual labels/outcomes cannot be independently reconstructed |
| [Earlier focused invocation](agents/agent-42.md), [exact command/IDs/events/hashes](agents/agent-42.json), [complete log](agents/agent-42-tests.log) | One invocation: 25 modules, 325 tests passed in 67.066 seconds; zero failures/errors/skips and stable source | Historical 22-file source before the final output-close correction; not combined with the 328-method invocation |
| [Earlier canonical collection](agents/agent-44.md), [comparison](agents/agent-44-population.json), [ordered IDs](agents/agent-44-discovered.json) | 5,164 unique IDs; all 5,114 base IDs preserved in relative order; 50 additions across 14 modules; no loader failure or active skips | Historical 22-file source before the final output-close correction; collection only, no test bodies executed |
| [Audited-base reconciliation](validation/base-governance-reviewed.json), [independent second review](agents/agent-32.md) | Original strict packet: 5,114 ordered canonical tests, 37,449 successful subtests, 52,791 events, zero failures/errors/skips, 3,122.11397 seconds | Exact base `622662ad` only |
| [Earlier development summary](validation/combined-operational-tests.json), [log](validation/combined-operational-tests.log) | 318 focused tests passed in 25.867 seconds | Earlier source identities only; exact invocation/test selection was not retained; later descriptor corrections have separate checks |
| [Real partial retention round trip](agents/agent-14.md) | Pinned real age v1.3.2; packaging, encryption, decryption, inert inspection and restoration; 1,950-byte ZIP restored byte-for-byte | Synthetic partial evidence, recorded source hashes, no native experiment |
| [Earlier partial round trip](agents/agent-41.md), [command and identity records](agents/agent-41.json) | Nine real invocations succeed; 8 files, 3 directories and 8,690 selected bytes preserved through packaging, encryption, decryption, strict inspection and restoration | Synthetic evidence at the historical 22-file source before the final output-close correction; all 22 frozen files and 89 imported source hashes stayed unchanged during that run; no native execution |
| [Real ciphertext controls](agents/agent-25.md) | Valid archive succeeds; wrong identity, truncation, payload mutation and appended ciphertext fail; a valid envelope around malformed plaintext fails strict inspection | Cryptographic and structural boundaries only; no producer authentication |
| [Direct CLI checks](agents/agent-26.md) | 39 selected actual entry-point checks: 11 help and 28 denials | Instrumented local checks; one additional interference case explicitly excluded |
| [Frozen measurement review](agents/agent-22.md), [source closure](agents/agent-33.md) | All 69 measurement identities and operational helper closures checked | No measured code or performance predicate changed |
| [Resource review](agents/agent-20.md) | Unchanged admission and visible capacity boundaries checked | Local native admission is not established |

The real-age pipeline in Agent 41 succeeded on its recorded source. The final
packaging cleanup changed afterward; that round trip does not validate the
23-file publication source. Agent 50's 645 successful subtests remain a reported
aggregate: the retained 984 events describe only start/success/stop transitions
for the parent test methods. Agent 53 independently reconciles those method
events and source records without claiming a per-subtest reconstruction or
continuous source immutability between observations.

Focused runs and their union do not replace the required complete strict
invocation. The exact published changed revision requires its own actual Actions
result, clean/stable source, checked/stable tools, complete ordered test
accounting and retained original receipts before native dispatch. Follow the
[governance runbook](../../governance-runbook.md). No earlier base pass qualifies
later edits.

## Retained original and reproducibility

The original public governance artifact is retained unchanged as
[base-governance/original.zip](base-governance/original.zip): **1,320,535 bytes**, SHA-256
`928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156`.
It comes from [run 45583904526](https://github.com/baabi-boo/AI-GPU/actions/runs/45583904526),
[job 139100502944](https://github.com/baabi-boo/AI-GPU/actions/runs/45583904526/job/139100502944),
artifact `15011343157`. This is the public governance packet, separate from the
private historical native control original.

From this packet directory, its retained consistency can be checked without
extracting files or executing retained code:

```bash
python3 -B agents/agent-32-reconcile.py base-governance/original.zip \
  --expected-revision 622662ad9cece6da4e3375be7e977dbe04cde862 \
  --expected-sha256 928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156
```

The reviewer uses external revision/hash pins and the observed successful v1
schema. It checks consistency and retained bindings; it does not independently
authenticate a provider or establish a later native execution.

The [publication snapshot](validation/publication-source-freeze.json),
[historical operational snapshot](validation/operational-source-freeze.json),
[measurement identities](validation/measurement-sources-before.json),
[frozen inputs](validation/frozen-inputs-before.json) and
[checked CMake package review](validation/cmake-wheel-reviewed.json) retain their
own scope. Historical scratch paths in reports identify actual invocations;
publicly retained companions are in `agents/` and `validation/`. Disposable
private identities, private control archives and synthetic decrypted trees are
not part of this public packet.

## Next native action

Verify/configure exact private control delivery and the owner's public age
recipient, verify the selected published revision's strict result, and obtain a
runner that satisfies unchanged admission. Execute one complete frozen attempt,
retain successful and unsuccessful originals privately, confirm encrypted
delivery, privately decrypt and validate, restore, and independently replay a
complete original before applying the frozen performance predicates.

P06-A02/A03, vendor XRT, physical FPGA and resource acceptance obligations remain
separate. No fixture, receipt repair, packaging result or governance success
closes those gates.
