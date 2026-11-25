# Agent 26 — direct qualified-warm CLI entry/error audit

## Result and ownership

**No actionable F2/F3 finding; no repository edits.** Exercised the real Python script entry points in a concurrent dirty working tree based on `622662ad9cece6da4e3375be7e977dbe04cde862`. Per-command source hashes bind this evidence; it is not clean-commit qualification.

The selected **39 direct subprocess checks passed**: 11 help calls and 28 parser/prerequisite denials. Exit counts were **11 × 0, 25 × 1, 3 × 2**. Every selected case completed within **0.895665 seconds** under a 12-second process-group timeout. The three exit-2 cases are the normal missing-argument diagnostics from inputs, run, and pack. All other negative cases returned their documented failure JSON. No selected case attempted a child subprocess or socket operation; no unexpected traceback, false admission claim, or false successful output artifact appeared.

Owned outputs only: `/tmp/ai-gpu-ae456f837c05/cli-agent26/`, `notes/agent-26.md`, `notes/agent-26.json`, and `notes/agent-26-supplement.json`. Production, proofs, goldens, native code, resource budgets, and acceptance records were not edited.

## Actual coverage

| Entry point | Denied condition and observed retained scope |
| --- | --- |
| control | Missing URL and malformed synthetic URL: exit 1, fixed sanitized reason, blocked `control-intake.json`, original verification false, no archive/network activity. |
| inputs | Invalid revision: exit 1, finished blocked acquisition receipt, expected revision null, commands empty, native not run, acquisition false. |
| run | Existing workspace: exit 1 before launch/finalization, no created artifacts; false orchestration/acceptance claims. |
| hosted preflight | Absent provider context: exit 1, minimal sanitized stage failure; no output tree. |
| hosted run | Existing attempt directory: exit 1 before orchestration; no output tree mutation or child work. |
| pack success and partial | Missing evidence: exit 1, private packaging-failure receipt only; no success receipt or ZIP. |
| encrypt | Valid public fixture recipient with missing age executable, plus invalid recipient: exit 1, sanitized failure summary, no public/private output directories. |
| restore inspect and restore | Missing archive and malformed synthetic tar with its real digest: exit 1, fixed retention rejection, all execution/acceptance fields false, no restored output. |

Also exercised root `--help`/missing arguments for all seven scripts, subcommand help/missing arguments for hosted preflight/run and restore inspect/restore, and unknown-argument canaries for control/hosted/encrypt/restore. Public failure stdout/stderr contained neither the synthetic canary nor task output paths. Acquisition/execution/packaging local CLI argument diagnostics retain their local scope.

## Instrumentation and explicit limitation

`strace` could not run because `PTRACE_TRACEME` returned EPERM. Those initial launcher attempts **never executed the CLIs**, are excluded from the result, and remain under `cli-agent26/strace-unavailable/`.

The completed runs used a task-local CPython 3.12.14 virtualenv, the same underlying interpreter binary, and a `sitecustomize` audit hook. The hook recorded each actual script startup and denied process/socket/ctypes events outside the selected no-child scope. It did not replace, import-call, or mock `main`; each command executed `python3 -B ABSOLUTE_SCRIPT ARGUMENTS` as a real subprocess with a minimal constructed environment. No credentials or real private inputs were inherited.

A **40th observation**, `run-invalid-revision`, is retained and excluded from the selected verdict: admission correctly returned blocked/native-not-run, but the existing `finally` block at `p06_qualified_warm_run.py` attempts its read-only isolated source observer even when revision validation fails. The hook denied that attempted subprocess and the CLI recorded a final-source failure. No native stage started, and no false pass resulted. This is an instrumentation limitation, not a demonstrated production defect. The existing-workspace case supplies an uninterfered run-denial check. No full hosted orchestration, native attempt, download, real encryption, complete replay, or full governance suite was run.

## Reproducibility

`notes/agent-26.json` contains every exact argv/shell command, minimal environment, source manifests before/after, real exit code, timeout result, report scope, stdout/stderr/audit SHA-256, artifact inventory, and each assertion. Raw bytes are in `cli-agent26/logs/`; synthetic case outputs are in `cli-agent26/cases/`. The original and supplemental harnesses plus the audit hook are retained with hashes. Source sets stayed stable within every selected invocation.

Primary launch:

```text
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp/ai-gpu-ae456f837c05/cli-agent26/tmp /tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 -B /tmp/ai-gpu-ae456f837c05/cli-agent26/audit.py
```

The original primary bytes are retained as `cli-agent26/audit-initial.py`; the current harness adds the one selected early-denial supplement. The supplemental launch used `CLI_AGENT26_CASE_FILTER=run-existing-workspace` with the same command. Fresh case directories are required; do not rerun over retained outputs.

### Tested CLI SHA-256

| CLI suffix | SHA-256 |
| --- | --- |
| `control` | `a303c3dc56076bbb203376521534e465c5d97b997c9ae1b93e6375e98d298fcd` |
| `inputs` | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `run` | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `hosted` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `pack` | `73ef372dbf76256304c2db73bddddfdae15a492695f5ae39ada68f1aa72c3f3a` |
| `encrypt` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `restore` | `21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d` |

Transitive local source/workflow/proof hashes and reviewed-document hashes are in the JSON.

## Next action

No CLI packaging/import/argument wiring repair is indicated by these checks. Root should finish the independent source reviews and final exact-revision governance/publication work. Actual warm admission still needs its unchanged private inputs, provider context, observed capacity, and separate native evidence.
