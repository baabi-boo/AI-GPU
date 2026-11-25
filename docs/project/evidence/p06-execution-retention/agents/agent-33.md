# Agent 33 — final operational source closure

## Disposition and scope

**No F2/F3 finding in the assigned closure scope.** Read-only audit of the six changed operational helpers against current run/hosted inventories, source export, and native replay. Base HEAD: `622662ad9cece6da4e3375be7e977dbe04cde862`. Read BRIEF, AGENTS, agent-15 review/JSON, automation contract, current status, and applicable review policy. No repository edits, native work, commit, or publication.

## Actual observations

AST traversal of explicit local imports, including each entry module, found:

| Entry helper | Local modules | Retaining inventory | Missing |
| --- | ---: | --- | ---: |
| inputs | 78 | run / hosted | 0 |
| run | 84 | run / hosted | 0 |
| hosted | 87 | hosted | 0 |
| control | 39 | hosted | 0 |
| pack | 85 | hosted | 0 |
| encrypt | 1 | hosted | 0 |

Real `selected_sources()` reads returned **106 files / 2,769,944 bytes** for run and **113 files / 2,933,758 bytes** for hosted, with stable rereads and sorted unique paths. These fit unchanged 256-file, 4-MiB/file, 32-MiB-total bounds. The hosted byte total supersedes agent 15's earlier snapshot. Actual loaded local module paths matched the checkout.

The three new `xrt_signals` imports are covered by run's explicit `ci/project/xrt_signals.py` entry and hosted's union with run. The unchanged helper is 730 bytes and imports only stdlib modules. Copy routines rehash destination bytes; run/hosted recheck source and retained inventories. Success packaging requires the exact run population and matching retained descriptors. No missing helper or inconsistent retained path was found.

Native source snapshots union loaded helpers, route files, and admission inputs; native replay requires their recorded populations and hashes. Qualified replay's own **100-file / 2,707,752-byte** trusted reader inventory remained stable. Nine fixed dynamic-module targets plus the pinned archive reader and configuration renderer are selected; their inspected paths agree. The wrapper launches native stages in separate interpreters. Its new cancellation helper does not extend native replay's fixed runner set.

The frozen proof still describes **69 measurement sources / 1,303,138 bytes**; every current descriptor matches. Measurement digest is `21ba69d11a9bdb91eab4abee75589710cd3dcc092895ec251350f4f4ce215d8b`. The six changed helpers and signal helper are outside that measurement set; proof bytes match HEAD.

An initial reviewer assertion incorrectly applied historical generic-preflight export pins to current qualified-route helpers. Its 33-helper digest differs from those historical pins but matches HEAD exactly; the qualified route uses the separate source/required-helper checks above. The diagnostic and correction are recorded in JSON; no contract or pin was changed.

## Source identities

All paths below are under `ci/project/`.

| File | SHA-256 |
| --- | --- |
| `p06_qualified_warm_control.py` | `a303c3dc56076bbb203376521534e465c5d97b997c9ae1b93e6375e98d298fcd` |
| `p06_qualified_warm_encrypt.py` | `70b5cc6e52d112b75d7009b3fe4b431ef56d17fea2a78e2a537538333b694053` |
| `p06_qualified_warm_hosted.py` | `01bee3115ba5b2ff0abb2583d76b165718a08216e3064faeb28324655d27b3ff` |
| `p06_qualified_warm_inputs.py` | `f4077dc42117f4e2e121c18e9be72ac6de1a480450245db19cb8ce951f4860bb` |
| `p06_qualified_warm_pack.py` | `e4cff314b8a2a0dbb277baef1bc5b3eb78b10a90f777a4d3b60ff74b682dac0e` |
| `p06_qualified_warm_run.py` | `8455ff73d618e41714c0737fc3ac25ee3d8afbb538fb95b42779d9b3740dfcd3` |
| `xrt_signals.py` | `a9531608094a233e5336a35e9fa7ebd028aaa3fc6dd7d3ed0f6f4d3f83a94fb8` |

## Evidence, limits, next action

Prepared CPython 3.12.14, `PYTHONDONTWRITEBYTECODE=1`, task-specific TMPDIR. Executed only read-only AST, trusted-import, bounded identity, and Git-object reads; the corrected identity audit exited 0. Existing test suites were not repeated. Source-copy and packaging rejection paths were inspected statically. No actual packet replay or native execution is claimed. Standalone helper APIs do not independently create the run/hosted envelope; this is selected local closure, not complete system provenance.

`agent-33-source-audit.json` retains full inventories, closure lists, checks, and hashes; SHA-256: `17ba5dff73b14f3d2b86d4b91a67e628b8041b6d7678d1376bb38c1ee272abba`.

Root should preserve these identities in final evidence and complete final-source governance/publication checks. No production fix is requested.
