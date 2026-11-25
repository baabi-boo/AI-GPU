# Agent 19 — canonical test population and preserved coverage

## Result and exact scope

**All 5,114 base IDs remain, in their original relative order. Current discovery
contains 5,159 distinct IDs: exactly 45 intended additions in 11 new modules.**
There are no removed IDs, duplicate IDs, loader errors, imported `TestCase`
fixture bindings, active skip flags, or expected-failure flags in this collection.

This is a read-only source/population audit at **2026-11-25 12:06:50–12:06:54
UTC**, against base and current HEAD
`622662ad9cece6da4e3375be7e977dbe04cde862`, with the concurrent working edits.
Agent 16 confirmed its eight-test finalization module was frozen before
collection. All **489 `ci/project/**/*.py` source hashes remained identical**
before and after discovery. No repository source, test, Git object or publication
was changed by this audit; only external `notes/agent-19*` artifacts were written.

Read the task brief, repository AGENTS instructions, current governance and
acceptance context, the strict runbook, and relevant author/reviewer records.
The exact base ZIP's `run/discovered.json` has 5,114 unique IDs and validates
against its recorded ordered-ID SHA-256. Its source revision matches HEAD.

## Method and retained evidence

From the repository source root:

```sh
PYTHONDONTWRITEBYTECODE=1 \
TMPDIR=/tmp/ai-gpu-ae456f837c05/tmp \
PATH=/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin:/usr/bin:/bin \
/tmp/ai-gpu-ae456f837c05/governance-bootstrap/environment/venv/bin/python3 \
/tmp/ai-gpu-ae456f837c05/notes/agent-19-collect.py
```

Exit **0**, approximately four seconds. The script uses ordinary
`unittest.TestLoader().discover("ci/project", pattern="test_*.py")` and unchanged
`governance_run.collect_test_ids`; it never calls a test runner, test body or
fixture setup. It also inspects loaded class bindings, effective skip/failure
flags and added AST markers. A separate static AST check confirms all **37
existing control test method bodies are unchanged**.

`agent-19-test-delta.json` is the compact counts/added/removed-ID result.
`agent-19-population.json` retains metadata, source identities, raw-file checks,
platform checks and observed Git status. `agent-19-discovered.json` retains the
complete ordered collection; `agent-19-source-hashes.json` covers every reviewed
governance Python file. `agent-19-static-checks.json` records the existing-method
comparison and evidence hashes. These records cover this snapshot only.

| New module, under `ci/project/` | IDs | Intended operational regression |
| --- | ---: | --- |
| `test_p06_control_closeout_review.py` | 4 | Preserve primary errors, invalidate failed receipt close, protect archive replacements |
| `test_p06_control_finalization.py` | 8 | Outer close failures, first-error preservation, bounded identity-checked recovery |
| `test_p06_control_operational_failures.py` | 6 | Transfer/storage failures and receipt finalization |
| `test_p06_encrypt_operational_failures.py` | 6 | Path replacement and interrupted publication/cleanup |
| `test_p06_encrypt_publication_review.py` | 1 | Retain last ciphertext after first-link path drift |
| `test_p06_hosted_operational_failures.py` | 6 | Trustworthy failed-supervisor dispositions and writer state |
| `test_p06_input_operational_failures.py` | 3 | Prelaunch failure and retained failed-transfer evidence |
| `test_p06_operational_cancellation.py` | 4 | Real SIGTERM between stages and during a bounded inert child |
| `test_p06_pack_operational_failures.py` | 4 | Output-directory identity and incomplete-byte retention |
| `test_p06_prelaunch_review.py` | 2 | Unstarted stages and unobserved-child evidence rejection |
| `test_p06_warm_supervision_failures.py` | 1 | Prelaunch checkpoint failure records an unstarted stage |

The new classes derive directly from `unittest.TestCase`; reusable test fixtures
are accessed through module objects or non-TestCase helper imports. Exact
module counts and all added identities match these additions, with no discovery
leakage of existing fixture classes.

## New platform guard: explicit qualification

There **is one new `skipUnless` class decorator** at
`test_p06_operational_cancellation.py:168`, covering the four new signal tests:
`os.name == "posix" and Path("/proc/self/stat").exists()`. No new
`expectedFailure`, `skipTest` call or skip-attribute assignment was found.

The guard condition is **true** here, and all four collected tests have no active
skip flag. The unchanged `governance_env.platform_checks()` passes on the prepared
Linux x86-64, GIL-enabled CPython 3.12.14 interpreter; that checker explicitly
requires Linux and `/proc/self/stat`, alongside POSIX FIFO/no-follow support.
The unchanged strict runner rejects actual skips and expected failures. This
guard limits new tests on unsupported platforms and removes no prior coverage.
Collection does not execute setup or test bodies, so this audit cannot establish
the absence of runtime skips.

## Native, performance and golden preservation

Compared **raw materialized bytes and executable/symlink modes of all 7,700 base
tracked files** with their base Git objects, independently of `git diff` and
index assume-unchanged flags: **7,693 match exactly**, with no missing/unreadable
files. The only seven differences are the six assigned
`p06_qualified_warm_{control,encrypt,hosted,inputs,pack,run}.py` modules and the
three-line `Response.close()` fixture addition in
`test_p06_qualified_warm_control.py`. The existing test bodies are intact.

All **1,418 `tests/` files, 882 `hw/` files, 200 `sim/` files, 141 runtime/kernel
files, 25 `ci/baselines/` goldens and 42 `ci/testcases/` entries** match exactly.
Other tracked native/performance governance tests, performance gates, proofs,
accepted evidence, acceptance records and configuration files also match the
base. No untracked native/performance source was present in the recorded status.
The five submodule interiors were not inspected; their base Gitlink identities
are retained without claiming dependency closure.

## Key SHA-256 identities

| Record or source | SHA-256 |
| --- | --- |
| Base ZIP | `928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156` |
| Base manifest file | `db8665fccccf134902c1739d8c5eb55d8f2021cd9d394c43e39f0f615d2836cd` |
| Base ordered IDs | `a33e6215dd12a601aefe3161615083699a8e9fef0ef22a9faaef0331939a71cd` |
| Current ordered IDs | `840f317f52248972001068281ffcf7a4f69e4deafdef4ffa602d872be55adc29` |
| Stable 489-file source snapshot | `877e71829a215b97433ece466f08ebcabcc16c215bec6979fdde36a5b8400561` |
| `governance_run.py` | `5fcb877775e5e35fd859686e875d0597d534326c679ff68b29f2151203d0bfdc` |
| `governance_env.py` | `af4538a894a96abaf4848b19126ba0b55f8b5d1c3404f7bda3c24f8ac3d9dbe1` |
| Final control production | `edb6c8e65191087da0278d5235d31cc4080d3b4e6f9f30c2147d3f5de4fa4ccc` |
| Final eight-test control module | `7020fea4b05a002f8d6353aed429d66e4162f9e2d4f202a0ca401edfb2c6e06c` |
| Signal test module | `9e04008693a5410a1ede7e6d88ccb86800ed7514a56852fdfffa2fb90877fc6b` |
| `agent-19-population.json` | `f9ff6c04ae1164d2ab2a98b1cbd8e16addad587dc5db875ff47ac058c5d9733a` |
| `agent-19-discovered.json` | `767bd695738b249361957cd8ca80131f049e84c3a9c14dec7af54e74f1ba1cff` |
| `agent-19-source-hashes.json` | `c6ad69e3523d7a24269f578039773deece7ce34f81fb92997d6a6e489d55cf23` |

## Limits and next action

No test bodies, full strict governance invocation, native experiment,
performance evaluation or network operation ran. This establishes collection
preservation and source scope only, not test success, native qualification,
maintainer approval or phase acceptance. Root should freeze the final combined
source and obtain its complete unchanged strict governance invocation; any later
test change requires a fresh population record. The qualified warm experiment
and P06-A02/A03 remain outside this audit.
