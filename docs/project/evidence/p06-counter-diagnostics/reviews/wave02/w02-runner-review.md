# Wave 2 independent runner review

Reviewer: `/root/w02_runner_review` (did not author either reviewed file).

Repository: `/workspace/scratch/98908dfa3444/AI-GPU`.
Base: `7455e008c1e001d3329e74fd55ffcd942592ec5f`; reviewed the uncommitted diff against that base.

## Verdict and findings

**No F1/F2/F3 finding in the two-file runner change. Land as a bounded diagnostic implementation; actual native results remain an open execution obligation and must not be reported as passed from these host tests.**

Treat this change as **R3** because it changes the externally consumed diagnostic schema and the build/output contract enforced by the runner. This independent review covers every changed hunk in `ci/project/p06_checked_execute.py` and `ci/project/test_p06_checked_execute.py`. The final committed-range classifier remains the integrating agent's obligation; a committed candidate was not available during this review.

Read `AGENTS.md`, repository `code-review` and `simx-review` skills, C++ and Verilog coding guidelines, bug-fix discipline, code-review policy, SimObject contract, SimX architecture, and the task's bounded diagnostic contract before assessing the change.

## Reviewed identities

| File | SHA-256 |
| --- | --- |
| `ci/project/p06_checked_execute.py` | `bcab9b048606a0d1d4ab8be3f91df9ebe5bce2a41375cd98b9dc2a279b5e2f99` |
| `ci/project/test_p06_checked_execute.py` | `181cf58c50b0ad5bfc7003ee48fc91e640d5c5a3a63fae3a22bbb7de77bbaae7` |
| `sim/simx/checked_counters.mk` (integration context) | `5080bbe88f3c6612258932953ada6d7ac983617bbba56806f37d3ab488b9ae99` |

## Contract review

- The exact 45-source inventory agrees with the current diagnostic Makefile: the four replaced production objects are omitted, five access objects are included, and the main diagnostic object is separate. Every compiled source has one exact object destination; substituted, duplicated, omitted, or foreign compile inputs and link objects fail validation. Link dependencies retain the pre-existing exact suffix.
- The three source-inclusion wrappers retain their literal nominated production include with the admitted preprocessing directives. The TCU compile input is explicitly the generated path, not an inaccurately reported original source path. Its retained bytes must equal production TCU bytes plus one LF byte plus the access footer. Original bodies, wrappers, helper header, and helper implementation are retained through the source snapshot and critical inventory.
- Every compile uses the validated common stamp except its exact dependency target. The existing release/configuration validator and exact option comparison reject `-fno-access-control`, unsafe flags, extra include roots, and unsupported topology changes. The diagnostic code does not weaken the protected lifecycle-hook assertion.
- `parse_build_records` handles producer paths as normalized absolute `PurePosixPath` labels and does not resolve or read them. `validate_build` adds live object identity checks. The pure parser still expects its caller to validate the stamp first and to authenticate the supplied retained source inventory; it is not by itself an archive-authentication service.
- Generated TCU bytes are retained, hashed after the build, checked before each native cell, and checked at completion. Source/tool/configuration/binary/object/retained-file/log drift checks remain active. These are before/after integrity observations, with the existing explicit exclusion of malicious concurrent filesystem writers.
- Boundary schema 2 matches the diagnostic harness's 33 selector names and order, 40 components, 400 component vectors, 14 split vectors, 33 reset selectors, 1,788 half reads, and 6,389 assertions. The 12 unavailable selectors remain outside the native query inventory. Exact top-level value types prevent bool/int and float/int acceptance.
- The original three negative modes keep their schema 1 scope. The two backing-source failures require schema 2, unchanged sources/output, actual DCR aggregation, sticky terminal containment, suppressed later work, join, and fresh-context success. They do not claim public-runtime qualification.
- `qualified`, `ready_for_warm`, `acceptance_claimed`, `full_warm_coverage`, and `warm_execution` remain false. The new narrow transport flag requires the full required cell set to pass. The 15 GiB disk reserve, 4 GiB memory requirement, two build jobs, one simulator worker, and bounded timeouts are unchanged.

## Verification observed by this reviewer

From the repository source root:

```text
python3 -m unittest discover -s ci/project -p 'test_p06_checked_execute.py' -v
Ran 35 tests in 35.800s
OK
```

Full output retained at `/workspace/scratch/98908dfa3444/w02-runner-review-tests.log`.

`git diff --check -- ci/project/p06_checked_execute.py ci/project/test_p06_checked_execute.py` passed.

I separately fed the access author's retained ordinary and checked **configured Make dry-run compiler/link records** and matching stamps through `compile_flags` followed by `parse_build_records`. Both produced exactly 45 translation units and one link, after their producer build directories had already been removed. Source bytes came from the current reviewed source construction, and the generated TCU bytes were supplied in memory as original + LF + footer. This verifies parser/build-rule agreement and offline path behavior; it does not establish compiled object or binary identity.

| Retained dry-run input | SHA-256 |
| --- | --- |
| `w02-access-ordinary-compiler-records.log` | `1639ed9e88dd0087726d145559c3878a3cf973da9af8175bd972d2fba1845048` |
| `w02-access-ordinary-stamp.txt` | `ba4ecb6c8b65f2eb88c7cf03c9d3ad5030a5e5dc09dbcbe6899866ca997f8ba7` |
| `w02-access-checked-compiler-records.log` | `0dc0c4e6da0454200d659ee4c0a039d0afba8ebdec61e3066537d04689bf0af2` |
| `w02-access-checked-stamp.txt` | `484ed118b978455a2c4b95dcd48026fbb27040b6e10be8a3d49d70c2b5188132` |

## Scope limits and open obligations

No native linked simulator build or execution was performed by this reviewer; local resources do not satisfy the existing reserve. Hosted native ordinary/checked execution, real backing-source overflow behavior, and clean final revision provenance remain for integration. Full access-pointer correctness and harness arithmetic are covered by their separate reviewers, not re-certified here. No public-runtime, warm-lifetime, RTL, hardware, numerical, performance, or phase-acceptance result follows from this review. No repository file was edited, no commit/push/reset/checkout was performed, and no gate or golden data was modified.
