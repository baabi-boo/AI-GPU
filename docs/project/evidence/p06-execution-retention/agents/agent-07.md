# Agent 07 — independent hosted disposition review

## Scope and result

Independent reviewer; did not write the production change. Read `BRIEF.md`,
repository `AGENTS.md`, Agent 01's report, the relevant canonical project status,
roadmap, backlog and acceptance sections, the automation contract, and the
inherited review policy. Reviewed **both changed production hunks (15 added
lines)** of `ci/project/p06_qualified_warm_hosted.py` against HEAD
`622662ad9cece6da4e3375be7e977dbe04cde862`, and **all 126 lines** of the new
`ci/project/test_p06_hosted_operational_failures.py` (absent at HEAD). Read the
surrounding launch, writer, source-stability, closeout and success paths, the
existing hosted fixture/tests, and the underlying receipt-reader and supervisor
observation functions.

**No F2/F3 finding or required correction demonstrated.** No production or test
file changed by this reviewer. The added tests are targeted at the repaired
failure disposition and its trust boundaries; another repository test module
would duplicate existing checks, so none was added.

## Review conclusions

- The new reader uses the existing bounded, stable, single-link/no-follow file
  reader and duplicate-key/depth-limited JSON decoder. Missing, malformed,
  non-object, wrong-contract, wrong-revision, nonterminal or unsupported
  disposition values resolve to `unknown`.
- The closeout call is inside the existing failed/uncertain native-supervisor
  branch. It runs only after the selected operational source copies match and
  the existing outer/nested writer observations complete. Unknown launch,
  unresolved cleanup, missing required nested command records, and observed
  selected-source drift cannot borrow a finished receipt's `run`/`not_run`.
- Recovering disposition does not set `native_success`,
  `orchestration_passed`, `qualified_warm_passed`, or acceptance flags. Failed
  native execution still selects partial packaging and the final result remains
  failed even when encrypted retention succeeds. Resource limits, source
  admission, complete-population checks and upload authorization are unchanged.
- The existing report-based writer limitation remains explicit: this is not an
  operating-system proof of all descendant writers being absent and does not
  defend against malicious concurrent filesystem modification.

## Actual validation

All commands ran from `/tmp/ai-gpu-ae456f837c05/AI-GPU` using
`/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3`
(CPython 3.12.14), with `PYTHONDONTWRITEBYTECODE=1` and
`TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp`.

| Command/check | Actual result |
| --- | --- |
| `python3 -m unittest discover -s ci/project -p 'test_p06_hosted_operational_failures.py' -v` | 6 tests passed, 3.095 s; zero skips/errors/failures |
| `python3 -m unittest discover -s ci/project -p 'test_p06_qualified_warm_hosted.py' -v` | 34 tests passed, 4.118 s; zero skips/errors/failures |
| Independent inline receipt-reader matrix | 20 checks passed |
| Independent inline nested-child failure composition matrix | 10 cases passed |
| `git diff --check -- ci/project/p06_qualified_warm_hosted.py` | Passed |
| `git diff --no-index --check /dev/null ci/project/test_p06_hosted_operational_failures.py` | No whitespace diagnostics; exit 1 denotes the new-file difference |

The independent reader matrix used a new temporary report path and called
`observed_native_execution` directly. It covered absent, empty, truncated,
array, null, invalid-UTF-8, duplicate-key and excessive-depth JSON; wrong
contract/revision; running/null state; boolean, object, array, integer and unknown
string dispositions; and each accepted `not_run`/`run`/`unknown` value.

The independent composition matrix used only the existing
`HostedCompositionTests` fixture, not Agent 01's `_failed_supervisor` helper. It
injected a nonzero supervisor outcome with a finished matching supervisor
receipt, separately claiming `not_run` and `run`. Its started
`dependency-build` child had five variants: running state, missing commands,
unknown command launch, started command with false cleanup, and started command
with absent cleanup. Every case produced `native_execution=unknown`, failed
outcome, false orchestration/qualification/writer/packaging/encryption flags,
and no packaging or encryption invocation.

These are host fixture checks, not native execution, actual encryption, hosted
delivery, independent native replay, or full strict governance qualification.
No provider state was changed, no git commit was made, and no phase or acceptance
record was edited.

## Reviewed source identities

SHA-256 observations at review completion:

| Path | SHA-256 |
| --- | --- |
| `ci/project/p06_qualified_warm_hosted.py` | `eba46917d1cdc7dafea97c98ac92a41313f7ce86b62db40f66de36356651cda5` |
| `ci/project/test_p06_hosted_operational_failures.py` | `ad165dd0ec63cc7e0b6e547ba1b504f06f0ba3876e29aa6d75163ab442033eb9` |
| `ci/project/test_p06_qualified_warm_hosted.py` | `d14fef2b03981987b8d313cad56a3d0085c577a5a6c615832acd3422d6f5ea6f` |
| `ci/project/p06_qualified_warm_run.py` | `7108581a9317f4dc22741975173e8fd7dd6bfcbfacbd80ac35e30622320b9337` |
| `ci/project/baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `ci/project/baseline_packet_io.py` | `469583bc558ccb010af82259de38248d7a9a8283cd873a96726aa3c3e2aaa94c` |
| `docs/designs/qualified_warm_automation_v1.md` | `91f2c94cb03084dc412f2a1e2f0e99059ecb9679eeab86235775c1d06147ce76` |

## Remaining action

Root should consolidate this source-scoped independent review and obtain the
frozen published revision's full strict governance result. The fresh
24-process/792-launch/25,344-word experiment remains unstarted; its private
inputs, recipient and unchanged native/capacity admission remain required.
