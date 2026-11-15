# Foundation setup — independent review record

This is a consolidated account of the repository-foundation review, not a GPU
test result or a maintainer approval. Its evidence level is **`source_present`**.
The [acceptance policy](../acceptance.md) and inherited
[review policy](../../review/code-review-policy.md) govern closure. A separate
machine-readable evidence report must identify any acceptance gates supported
by this narrative and retain its digest.

## Revision and decision boundary

| Checkpoint | Exact identity | Meaning |
|---|---|---|
| Inherited source baseline | `da55a516a48b49013724f697d3c12a48932b449f` | Upstream-derived source before the foundation setup |
| Frozen independent-review commit | `bda1e1441ff68082f6341a07d86b3561a803dc11` | Source reviewed by all six Wave 8 agents |
| Frozen review tree | `fc276dc850a4ed0cd64b61aabb50dc0ec33dd133` | Content tree corresponding to that review commit |
| Markdown-fix commit | `7c36e02d35ee4f709f4ca50d268bf43269e020e9` | Corrected validator and 34 independently authored regression tests |
| Markdown-fix tree | `8af4bf045fba36568e337fcdbcbacfd12e281b84` | Exact fix snapshot independently verified in a clean local clone; final review remains separate |
| Final independent-review commit | `d577267a8d7eb0b786faf47fe2aeb6acf0d66e56` | Integrated source, fixes and nine-wave evidence reviewed by all six Wave 10 agents |
| Final review tree | `11eae4b9118d9035e7cd4ed89cc5f93ebde4c460` | Exact source snapshot for the final reviews below; later delivery metadata is separately checked |
| Maintainer approval / default-branch delivery | Pending | Agent review cannot authorize the R3 change or establish a merge |

The base-identical change-impact classifier reported **R2** for CI-enforcement
paths. The coordinator applies **R3 conservatively** because this setup adds CI
enforcement. The inherited classifier and policy were not modified. R3 requires
an independent reviewer and a real maintainer decision recorded in the pull
request; neither this document nor the requested agent count supplies that
decision. No waiver was granted or inferred.

## Six independent Wave 8 reviews

Each reviewer inspected the frozen commit above in a separate assignment. The
checks below are the reviewers' reported observations; this consolidation does
not pretend that every reviewer ran every test. “No scoped findings” means no
actionable defect was reported within that assignment, not approval of all
future revisions or satisfaction of hardware gates.

| Reviewer | Scope | Observed checks and disposition |
|---|---|---|
| `/root/w08_a01` | Project validator, its core tests and adversarial tests | Re-ran the base-identical classifier, checked scoped whitespace and reproduced two full-validator failures with bounded in-memory inputs. **Requested changes:** REV-01 and REV-02. Did not rerun the unit suite. |
| `/root/w08_a02` | Read-only preflight, its tests and developer resource guidance | **42 preflight tests passed**; actual governance preflight passed; simulation prerequisites were correctly blocked with five uninitialized submodules. Checked image hash, scoped whitespace and clean tree. No scoped findings. |
| `/root/w08_a03` | GitHub workflow/forms, contribution and agent guidance, security, changelog, maintainer checklist and CI contract | Inspected workflow trust and form YAML; verified inherited workflows, functional source, goldens, pins and image preservation; checked generated-build CI exclusion of `ci/project`; cross-checked corrected blackbox guidance and retained changelog history. No scoped findings. |
| `/root/w08_a04` | Opt-in AI profile, profile tests, README, roadmap and architecture/software/hardware plans | **11 profile tests passed**; XLEN and merged-flag CLI checks passed. Verified all 13 dependency edges across 12 phases and 36 gates, plus protected source/image checks. No scoped findings. |
| `/root/w08_a05` | Canonical roadmap, requirements, phase guides, acceptance, verification, benchmarks, releases, risks, decisions, evidence policy and repository-contract tests | **18 repository-contract tests passed**; reviewed phase dependencies, gate/evidence boundaries, soak durations and external approval requirements. No scoped findings. |
| `/root/w08_a06` | Charter, baseline, backlog, status, handoff, execution ledger and project/technical indexes | Project validator and whitespace checks passed; verified image/embed, functional source, workflows, pins, licenses, changelog and technical-index preservation. Cross-checked current/next phase claims and the then-current ledger of **42 completed assignments in seven waves**. No scoped findings. |

None of these reviews ran GPU builds, GPU workloads, FPGA measurements or
silicon tests. Hosted Actions, GitHub issue rendering, publication readback and
repository-setting changes were not established by Wave 8. Preflight inspection
did not qualify installed tool identities, practical build budgets or physical
hardware. Reviewers who reported only scoped tests did not claim the full suite.

## Findings and required disposition

All three findings below have **high confidence** and **`static-proof`**
evidence. Their trigger conditions were exercised through the full project
validator, rather than inferred solely from a private helper.

| ID / severity | Concrete failure on the frozen revision | Required correction | Current disposition |
|---|---|---|---|
| REV-01 / F3 | Escaping a Markdown image marker could satisfy the protected visible-image gate even though the page displayed an ordinary link rather than the image. Escaped HTML markers required the same scrutiny. | Make image detection escape-aware and add paired real/escaped Markdown and HTML end-to-end tests. | Fixed; independently reproduced and accepted by `/root/w10_a01` at the final review revision. |
| REV-02 / F2 | An escaped literal reference such as `\[example][not-a-link]` was falsely rejected as an undefined live link. | Share escape-aware reference detection, preserving errors for genuinely active undefined references. | Fixed; independently reproduced and accepted by `/root/w10_a01` at the final review revision. |
| REV-03 / F3 | Replacing the original three-line image wrapper with four spaces followed by the image tag made a top-level Markdown code example, but the image-preservation gate still passed. | Exclude indented code from image/link semantics while retaining active paragraph, list, blockquote and raw-HTML contexts. | Fixed; independently reproduced and accepted by `/root/w10_a01` at the final review revision. |

REV-01 and REV-02 were reported by `/root/w08_a01`. The coordinator independently
reproduced REV-03 after the frozen review began. Indenting an image **inside**
the original active HTML `<p>` block is not equivalent to replacing that entire
wrapper with top-level indented code; positive controls preserve this distinction.

## Regression history and fix verification

Before the frozen Wave 8 review, integration corrected two earlier adversarial
cases: a valid balanced-parenthesis link destination was truncated, and an
escaped inline-link literal was incorrectly treated as live markup. The frozen
review commit also already contained restored upstream changelog history and
corrected native blackbox configuration guidance. These are earlier integration
fixes, not undisclosed changes after the six reviewers' source snapshot.

For the three Markdown findings, `/root/w09_a01` authored the validator
correction and `/root/w09_a02` independently authored
`ci/project/test_markdown_edges.py`. The new module contains **34 end-to-end test
methods**, covering escape parity, active versus literal references, top-level
and container-relative code, original raw-HTML embedding, and paired live-link
controls. It reuses the test-free fixture base without duplicating an inherited
concrete test suite.

The test author's **pre-fix run** retained the real failure signal:

- 34 methods executed; 21 methods fully passed and 13 methods failed.
- The failed methods comprised 33 assertion/subcase failures and zero errors.
- No failing case was skipped or weakened to produce a pass.

The fix author and coordinator reported **180 passing tests** on the corrected
working-tree code: the previous 146 tests plus the new 34. The coordinator also
observed passing validator, governance preflight, policy lint, catalog lint
(945 definitions across 28 categories), whitespace and protected-image checks.
The correction and tests were then committed at the Markdown-fix revision
above. These were integration observations, not a claim that the shared checkout
was wholly clean: this narrative was being drafted as an untracked file.
Independent clean-checkout verification of the fix snapshot is recorded below.
The final Wave 10 review is recorded separately below; passing tests alone do
not replace that review or the frozen-review history.

## Clean-checkout proof at the original review revision

`/root/w09_a03` made a separate local-only clone of the frozen review commit and
verified Python **3.12.14** with `-I -S -B`: isolated mode, no site packages,
ignored Python environment variables and bytecode generation disabled. All five
submodules remained uninitialized, and Git status was clean before and after.

The following commands exited **0** from that clone's source root:

```sh
python3 -I -S -B ci/project/preflight.py --tier governance
python3 -I -S -B ci/project/check_project.py
python3 -I -S -B -m unittest discover -s ci/project -p 'test_*.py'
python3 -I -S -B ci/gen_config.py --config VX_config.toml --profile ai-dev --profile-xlen
python3 -I -S -B ci/gen_config.py --config VX_config.toml --profile ai-dev --xlen 64 --merge-configs
python3 -I -S -B ci/gen_config.py --config VX_config.toml --profile ai-dev --xlen 64 --merge-configs --cflags='-DITYPE=fp16 -DOTYPE=fp32 -DWGMMA_NRC=16'
git diff --check
git status --short --untracked-files=all
```

The suite reported **146 tests passed**. XLEN was `64`; merged flags retained
the candidate native arithmetic choices and appended all three application
flags when requested. These commands were also prefixed with
`PYTHONDONTWRITEBYTECODE=1`; `-B` provided the effective bytecode control because
`-I` ignores that environment variable. This proves standard-library onboarding
for the original review revision only, **not** acceptance of the subsequent
34-test regression module or Markdown fix. No network fetch, dependency
installation, GPU build, simulation workload, synthesis or hardware access was
performed for this clean-checkout proof.

## Independent clean-checkout proof of the fix snapshot

`/root/w09_a06` independently cloned the exact Markdown-fix commit/tree above
from local source and used Python **3.12.14** with `-I -S -B`. The interpreter
reported isolated/no-site/no-user-site/ignore-environment/bytecode-disabled
flags, with standard-library-only paths. Git status was clean before and after;
no source edits or submodule initialization were performed.

| Command from the fix clone's source root | Result |
|---|---|
| `python3 -I -S -B -m unittest discover -s ci/project -p 'test_*.py'` | Exit 0; **180 tests passed**, including all 34 new Markdown methods |
| `python3 -I -S -B ci/project/check_project.py` | Exit 0; governance metadata validated |
| `python3 -I -S -B ci/project/preflight.py --tier governance` | Exit 0; tracked changes reported false |
| `python3 -I -S -B ci/gen_config.py --config VX_config.toml --profile ai-dev --profile-xlen` | Exit 0; `64` |
| `python3 -I -S -B ci/gen_config.py --config VX_config.toml --profile ai-dev --xlen 64 --merge-configs` | Exit 0; expected profile flags retained |
| Same merge command with `--cflags='-DITYPE=fp16 -DOTYPE=fp32 -DWGMMA_NRC=16'` | Exit 0; all three application flags retained |
| `python3 -I -S -B ci/project/preflight.py --tier simulation --json` | Exit 1; **blocked**, not a GPU pass: missing CMake, RISC-V compiler, LLVM Clang, Verilator and five uninitialized submodules |
| `git diff --check` and `git status --short --untracked-files=all` | Exit 0; no changes reported |

The protected illustration digest matched the baseline. This is independent
regression and onboarding evidence for the committed fix, not a hosted-CI run,
GPU execution or final code-review approval. The reviewer also identified a
pre-merge onboarding caveat: the default-branch clone instructions need an
explicit review-branch checkout note while the setup is not yet on `master`.
The coordinator added that note to both README and developer onboarding during
final integration. Reviewers `/root/w10_a02` and `/root/w10_a06` independently
confirmed the correction at the final review revision (ONB-01 resolved).

Separately, `/root/w09_a05` inspected the same fix snapshot's publication diff:
59 changed UTF-8 regular files, 526,537 raw payload bytes and no deletions.
Functional implementation, inherited workflows, goldens, licenses, tool pins,
image bytes, original README wrapper and inherited changelog body were retained
(the changelog's terminal newline was normalized). A bounded secret-like text
scan found no candidate credential material; this is not an exhaustive security
guarantee. That audit excluded this then-untracked narrative and did not rerun
unit tests, publish remotely or execute GPU work.

## Six independent final reviews

All six Wave 10 reviewers read the repository review skill and its required
rules, reviewed their assigned final-state hunks and reported no actionable
findings at `d577267a8d7eb0b786faf47fe2aeb6acf0d66e56`. Their advisory verdicts
were readiness for maintainer review, not permission to merge.

| Reviewer | Scope and observed checks |
|---|---|
| `/root/w10_a01` | Validator and its core/adversarial/Markdown tests: 34 targeted and all 180 tests passed; checker and independent full-project reproductions accepted REV-01/02/03 repairs and retained positive controls. Earlier tests were not weakened. |
| `/root/w10_a02` | Preflight and resource/onboarding contracts: 42 tests passed; actual governance screen passed; actual simulation screen correctly blocked. Verified bounded, non-mutating Git observations and ONB-01 correction. |
| `/root/w10_a03` | Roadmap, requirements, all phase guides and technical/acceptance plans: 18 contract tests and checker passed; independently counted 12 phases, 36 gates, 34 requirements, 17 risks and 13 matching dependency edges. |
| `/root/w10_a04` | Workflow/forms and contributor/security/maintainer process: five new YAML files passed installed PyYAML 6.0.3 duplicate-key/structure checks; 18 contract tests and checker passed; all five inherited workflows remained identical. |
| `/root/w10_a05` | Publication payload, provenance and opt-in profile: 60 regular UTF-8 changed files (545,208 raw replacement bytes), 2,765 protected entries and original image/wrapper/history verified; 11 profile tests and isolated configuration CLI checks passed. Bounded credential-pattern scan found no candidates. |
| `/root/w10_a06` | Handoff, navigation, status and evidence: a new exact local-only clone passed all 180 tests, checker, governance preflight, whitespace, image and clean-status checks under isolated Python 3.12.14. Historical tree identities, prior 54-task ledger and ONB-01 were verified. |

Every reviewer verified the frozen identity and clean shared checkout. The
base-identical classifier reported R2; the conservative R3 decision remained.
The final execution ledger records **60 distinct completed assignments across
10 waves of six**, scheduled with at most three subagents simultaneously. This
count is process provenance, not a measure of GPU correctness or human approval.

The Markdown checks remain a bounded standard-library subset, not a complete
GitHub/CommonMark renderer, HTML sanitizer or CSS visibility proof. Payload
scans are not exhaustive security certification. Static YAML checks are not
hosted Actions or GitHub issue rendering; `actionlint` was unavailable. Reviewers
who ran scoped suites did not claim a full-suite rerun. No final reviewer
executed GPU workloads, synthesis, physical hardware or remote publication.
Later delivery/evidence metadata is outside this frozen review and receives a
separate coordinator check and independent follow-up before publication.

## Remaining closure obligations

1. Check the final ledger and delivery/evidence metadata added after the frozen
   source review; retain its exact revision and independent disposition.
2. Attach compatible hash-checked evidence for the P00 gates actually supported
   by those observations. Preserve failures and not-runs in the record.
3. Publish only to the authorized repository and verify the remote branch/PR;
   obtain the required real maintainer approval before default-branch merge.
4. Keep P00 `in_progress` until all its obligations are met. P01–P11 remain
   separately gated; no result here qualifies the opt-in AI profile, a tiny
   model, native tensor numerical behavior, physical performance or silicon.

See [current status](../status.md) for the live handoff. This historical review
record must not be silently relabeled as review of a later source revision.
