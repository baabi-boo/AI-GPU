# Independent evidence integrity review

**The retained packet identities, numeric results and evidence-level boundaries
reconcile. No new F2/F3 integrity or claim-scope finding was identified.**
Reviewer `/root/w10_a04` authored none of the repair, runners, earlier reviews
or execution archives. This is an offline evidence audit under AGENTS.md;
independent integration and final publication dispositions remain separate.

## Archive integrity and source identity

Independently verified all **eight hosted ZIP archives**, totaling **1,013
members**: whole-archive SHA-256 and byte size, member count and expanded size,
CRC, unique safe paths and regular-file types. Every one of the **237 declared
command logs** resolves inside its archive and matches its recorded hash and
size. Retained workflow bytes match their original Git head and job digest.
The [structured audit](evidence-review.json) records each checked archive.

GitHub's immutable commit endpoints independently confirmed all four PR merge
objects, their two parents and trees. Local original-head Git trees agree:

| Source attempt | PR head | Executed checkout | Tree |
|---|---|---|---|
| 1 | `58c71d34` | `d65d0869` | `4ffe04f2` |
| 2 | `7396ded8` | `00fdd88d` | `1e0a74cf` |
| 3, retained repair | `18c88805` | `6e6426a0` | `d6dd742a` |
| 4, alternative | `27a18d49` | `7a983db1` | `26211e4f` |

The structured audit retains full identifiers and endpoint URLs. Archive job
identities agree with the actual checkout and run, without relying on a PR's
later head. Critical production hashes match the named Git objects. Source and
tool observations are stable within each packet; successful parent packets also
preserve reference and generated identities. Their original production sources
match `4df7186edbca82b21b2b8cba9b3b192248b99209`.

Direct and alternative source inventories differ only in
`hw/rtl/core/VX_csr_mpm.sv`; tool identities agree. The main checkout retains
`18c8880` production, helper and workflow bytes. The alternate decoder has not
been adopted.

## Results and preserved failures

| Attempt | Native result | Circuit result |
|---|---|---|
| 1 | Eight candidate cells pass; parent checkout fails before tests | Dependency import fails; zero measurements |
| 2 | Eight candidate cells pass; parent checkout fails before tests | Parent checkout fails; zero measurements |
| 3 | Eight candidate cells pass; both parent tests detect the defect | Eight Beacon plus eight Yosys measurements complete; raw RV64 area failures remain |
| 4 | Alternative passes the same matrix and parent checks | Complete matched comparison; raw RV64 area failures remain |

Each complete native matrix has **1,056 RTL reads, 19,912 RTL assertions,
28 ignored requests and 18,064 SimX checks**. These totals apply per attempt;
repeat attempts are not additional configuration coverage. I independently
parsed the raw run banners, successful build/run exits and stable recorded
binary identities.

For both final native archives, the old RTL builds successfully and exits 1
at tag `00220001`, expected `00000001`, actual `00000000`. All **714** SimX
failures among **5,251** checks independently reconcile with the missing high
half: 357 high replies, 238 low-first reconstructions and 119 high-first
reconstructions. Each of the five SimX builds per archive compiles and links
**42 matching objects**, including 41 production objects and the harness.
These are actual linked-model results, distinct from the separate host-double
checks. Binaries themselves are not archived or rerun by this review.

## Circuit comparison and review continuity

Raw Beacon build reports and Yosys statistics/path logs reproduce both final
structured matrices. Each packet completes all eight Beacon measurements
before its eight Yosys confirmations. Repeated parent results agree.

Relative to the direct repair, the shared decoder saves **2/68 estimated
Beacon LUTs** with PERF off/on, but adds **9/21 generic Yosys cells**. Its
PERF-off topological path grows **7 → 8**; PERF-on watch endpoints grow
**12 → 32**. FF counts and Beacon maximum depths are unchanged. These findings
support the [alternative review's](alternative-review.md) recommendation to
retain the direct repair under the stated cross-flow constraints.

The [original circuit review](circuit-review.md) remains an immutable F2
checkpoint. The later comparison closes its specifically missing experiment;
it does not assert global optimality. Both circuit packets retain
`gate_outcome=fail`, every raw build retains `NO-BASELINE`, and RV64 area
comparisons retain exit 3. Measurement completion is not a cost-gate pass.

## Governance and claim limits

Both retained governance gzip/raw digests match their receipts. The earlier
2,873-test development attempt still records exit 1 and 104 failures. The
[immutable run](../host/governance-18c8880.json) contains exactly **2,910 test
entries**, the **1,516.847-second** `OK` footer and no failure/error/skip markers;
its deterministic gzip reproduces exactly. Actual exit zero is attributed to
`/root`'s session confirmation. Clean observations were mid-run and post-run;
pre-launch and interpreter/dependency binary provenance remain absent.

All execution records preserve unqualified/no-acceptance states. No historical
high bits, absolute no-wrap proof, atomic live-counter reads, full AFU,
physical timing or phase acceptance follows from these checks. The known
standalone interpreter-provenance F1 remains scoped in the
[enforcement review](enforcement-review.md). Broader CI and publication are
covered by the [integration review](integration-review.md) and final checks;
this audit makes no overall CI-pass claim.
