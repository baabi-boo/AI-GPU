# P01 hardware-emulation preparation handoff

## Scope and phase boundary

This continuation implements P01-T05 preparation and corrects the XRT
pre-simulation hook. It does not execute vendor `hw_emu`, qualify a platform,
accept P01-A03 or start P02. P01-A01 and P01-A02 retain their existing accepted
reports. The [roadmap](roadmap.json) remains authoritative.

| Identity | Value |
|---|---|
| Repository / target branch | `baabi-boo/AI-GPU`, `master` |
| Starting revision | `91b82fe300f94ab0a70dd0e0e4a69a0e23b16101` |
| Integration owner | Primary coding agent `/root` |
| Initial implementation publication | [`81e35e97d2fa410bbfbb970b53ccc179b0aa8d27`](https://github.com/baabi-boo/AI-GPU/commit/81e35e97d2fa410bbfbb970b53ccc179b0aa8d27), tree `dd72cfa527ad47a7cd967336528a7de1c00aa90b` |
| Git-configuration correction publication | Pending commit/tree and remote readback |
| Current release state | Initial implementation published; correction locally validated and independently reviewed; correction publication and hosted recovery pending |
| Vendor / physical execution | Not run; required tools and platform are absent |

The requested collaboration is recorded separately in the
[continuation ledger](p01-hwemu-agent-execution.json): ten logical waves, six
distinct assignments per wave, executed in bounded batches under the concurrent
worker limit. Only completed assignments are counted. Prior P00, native-baseline
and packet-verifier ledgers are historical and are not counted again. Agent
reviews are engineering evidence, not invented human approvals or acceptance
waivers. The user explicitly authorized implementation, commits and publication
to this repository's `master` branch; no force push is authorized or needed.

## Implementation

The [runbook](p01-hwemu-runbook.md) explains the workflow; the
[manifest guide](p01-hwemu-manifest.md) describes the exact input contract.

- `ci/project/hwemu.py` exposes read-only prerequisite inventory and input-set
  planning, with explicit blocked/usage exit statuses and no execution mode.
- The contract, bounded input reader, source inventory, generated-build checker
  and planner bind source/build/vendor/platform/artifact declarations and check
  stable bytes. Consistent inputs yield an unqualified structured candidate.
- Source observation uses bounded Git metadata and raw worktree identities,
  avoiding Git status and configured clean/process filter execution. Nineteen
  consumed source paths must be regular blobs in both HEAD and the index;
  staged equality, raw bytes/modes and recursive submodule checks bind them.
  Every Git query strips inherited `GIT_*` values and supplies fixed
  `GIT_CONFIG_NOSYSTEM=1` and `GIT_CONFIG_GLOBAL=os.devnull`. System and default
  HOME/XDG global configuration are excluded; repository/worktree configuration,
  explicit includes and matching conditional includes remain subject to the
  unsafe filter and partial-clone/promisor checks.
- The generated XRT INI points to the existing source Tcl hook. Waveform and
  inherited profiling capture are disabled by default; debugging is explicit.
- Synthetic test fixtures exercise malformed inputs, inconsistent compiler
  records, unsafe files, identity drift, resource failures and claim boundaries.
  These fixtures are not vendor execution or acceptance evidence.

Every planned candidate retains `launch_ready: false`,
`vendor_qualification_verified: false`, `execution_performed: false`,
`phase_complete: false` and P01-A03 `acceptance_outcome: blocked`. Declared limits
are not an execution supervisor. Matching hashes cannot authenticate a producer
statement, vendor release, library loading, platform compatibility or execution.

## Validation

The unmodified starting checkout passed the governance preflight, project
checker, both retained packet checks and all **591 existing tests**. An integrated
intermediate run passed 787 tests. The initial implementation's complete
source-root suite, after the compiler-record correction but before the later
Git-configuration correction, passed **788 tests with zero skips in 85.925
seconds** (86.209 seconds including its wrapper).

After the Git-configuration correction and its four new regressions, the complete
source-root suite passed **792 tests with zero skips in 87.878 seconds** (88.142
seconds including its wrapper), finishing at `2026-11-16T00:47:01.129238Z`.
Both local suite runs used Python 3.12.14 and Git 2.52.0. The corrected run tested
the uncommitted code changes above base commit
`81e35e97d2fa410bbfbb970b53ccc179b0aa8d27`; its content digest below identifies
those bytes independently of a later publication commit. These are host
tooling/governance results, not GPU execution results or hosted CI recovery.

All local commands below ran from the source root. For the standalone CLI,
`$FIXTURE` is a path alias for the owned temporary fixture directory; its
`manifest.json` was passed as an absolute path. The directory was removed after
the two observations, and its private machine path is not published.

| Command / observation | Outcome and exit code | Exact scope |
|---|---|---|
| `python3 -B ci/project/preflight.py --tier governance` | Pass, `0` | Vendor tools absent and submodules uninitialized are named, optional governance prerequisites |
| `python3 -B ci/project/check_project.py` | Pass, `0` | Structure, links and metadata only |
| `python3 -B ci/project/check_baseline_packets.py` | Pass, `0` | Both retained packets; public consistency only |
| Initial `python3 -B -m unittest discover -s ci/project -p 'test_*.py'` | Pass, `0` | 788 tests, zero skips; before the Git-configuration correction |
| Corrected `python3 -B -m unittest discover -s ci/project -p 'test_*.py'` | Pass, `0` | 792 tests, zero skips; includes the four Git-scope regressions |
| `python3 -B -m unittest discover -s ci/project -p 'test_xrt_configuration.py' -v` | Pass, `0` | Four tests, zero skips; real fresh out-of-tree configure and Tcl hook checks |
| `python3 -B ci/project/hwemu.py plan "$FIXTURE/manifest.json" --json`, complete synthetic inputs | `planned`, `0` | Actual resource observations; all qualification/execution/phase flags remain false |
| Same CLI invocation after same-size corruption of the synthetic xclbin | `blocked`, `1` | No candidate; file-identity mismatch detected |
| `git diff --check` | Pass, `0` at review checkpoints | Repeated for publication |
| Vendor build, full `hw_emu`, physical FPGA, synthesis and GPU workloads | `not_run`, no exit code | Qualified tools/platform absent; no RTL/SimX timing change is included |

The following digests identify the retained coordination observations. These
local logs are not packaged as public vendor-execution evidence. Hosted CI
observations are recorded separately below as they become available.

| Local observation artifact | SHA-256 |
|---|---|
| `integrated-preflight.log` | `02ed4cac8e91c00397f47eb4c6718f9baa8887554c8921eea5809495a01f3ec0` |
| `integrated-project-check.log` | `d505e20764bb8ca9754d5a40ae3dede73831b96c6b6d0020065e6a3b87960993` |
| `integrated-baseline-packets.log` | `fe35ed00868a1b653caa23c1fdade37cce4ad8691b9a9cd08a222e82afae28be` |
| `final-unittest.log` — initial 788-test run | `500c59a589ac5eed311a3fc3c689599f1a47c629efb522f7af8375c16d810738` |
| `final-unittest.metadata.json` — initial 67-file content set | `5b14bc6299a8f980c4a9a4d88b7c1a37b9cf350d8925af8e06ffb4fd98de18a8` |
| `corrected-unittest.log` — corrected 792-test run | `09c59ae669f0ea0e8101d85a3d7b19d811561f283bbf5f4bc5ac5926153411ec` |
| `corrected-unittest.metadata.json` — corrected 68-file content set | `215076dfb244af9e826548fe54f809cb7dd0528c5dfb40af0a982ffdef541051` |
| `change-impact.xrt-test.log` | `d181f86801beaf8c5fca15b41c8922de4490dc5ea497f53ae153c47c6141d16a` |
| `w07e-complete.json` | `0d68c4688f0305336e258ed32dd2d765b0afd536886f6574b94bee995265442a` |
| `w07e-same-size-xclbin-corruption.json` | `c243bfdb4222bbd3f622a2e52fefb13142fa6f70035bd839b09039e5e8057f70` |

The initial 788-test run recorded identical before/after hashes for all 65
`ci/project/*.py` files and both changed XRT files: 67 paths, content-set digest
`aef71e5fa9e21fa99f13b64741608dfc46d777f7c9e3d89d0596b310e7c3f3f4`.
The corrected 792-test run likewise recorded identical before/after hashes for
66 Python files and both XRT files: 68 paths, content-set digest
`aa8fdaa6bb8ef3dc0042e6406da744492ddbca706aac26db33f6ea200e106249`.
Each digest is SHA-256 of compact sorted-key JSON mapping source-relative paths
to their SHA-256 content hashes. Neither content set includes this evolving
handoff or other documentation/accounting changes. The publication record below
separates the initial published identities from the pending corrected publication
and its hosted observations.

The standalone fixture check observed about 50.63 GiB of free disk and 7.57 GiB
of host `MemAvailable`, retaining the production 15-GiB disk reserve and 6-GiB
RSS budget. Its inputs and index metadata did not change during either CLI call;
no vendor/setup execution marker appeared. The fixture was removed afterward.
Host memory observations do not establish an effective container/cgroup limit.

## Independent review and disposition

The base revision's classifier and policy classify this scope as **R2**, because
of the two XRT software-stack files. The initial 33-file review snapshot has
nine R0, 22 R1 and two R2 files, with no R3 contract detector. The sole emitted
evidence obligation is testing the changed INI from a newly configured build tree; the
four XRT tests satisfy that obligation. No RTL or SimX logic changes trigger
Beacon, synthesis or cycle-parity evidence. The final publication diff is checked
again with the base classifier.

Independent review covered every implementation and new-test hunk, with separate
documentation and preservation review. Findings drove corrections to:

- Source/tool path overlap, escaped shim macros and unbound linker inputs.
- Direct kernel ISA/ABI selections, option-operand parsing, shell operators and
  unbound environment-variable expansion in compiler records.
- Source filters that could execute during Git status, unsafe identity-file
  reads, hidden index flags and inherited Git environment state.
- Ignored/untracked consumed source files that could otherwise appear clean.

All F2/F3 findings in the initial implementation/test review are closed; none is
waived. The F1 follow-up for unquoted glob characters in unusual hand-written
compiler operands is recorded in the [backlog](backlog.md). The inspector does
not expand globs against a compilation directory. Actual producer records and
review of the effective invocation remain required before any separately
supervised execution; a plan never grants launch readiness. Some isolated test
children may create small ignored Python caches; this is not a CLI output or a
change to retained source/evidence.

### Git-configuration correction and independent review

The first hosted Governance failure led to a controlled reproduction of a
source-observer defect. The original observer removed every inherited `GIT_*`
value, including fixture isolation controls, then queried Git's default
configuration scopes before recording source revision/tree. Owned system or
HOME/XDG global clean/process-filter defaults therefore blocked an otherwise
clean fixture with unavailable source identity. The correction supplies fixed
system/global exclusion controls after stripping inherited values on every
query. Repository configuration, enabled worktree configuration and their
explicit or matching conditional includes remain visible. Unsafe settings in
those scopes still block observation, including a repository include of an
otherwise excluded machine configuration file.

Assignment 53 independently compared the original published module with the
correction using real Git and disposable owned configurations: **14 cases / 28
observations passed**, with no filter-canary execution or index-byte change.
The reviewer accepted the exact correction and finalized regression file below
with no unresolved findings, and independently reran the four new tests after
the fixture's conditional-include visibility assertion was finalized.

| Reviewed correction file | SHA-256 |
|---|---|
| `ci/project/hwemu_source.py` | `4a7afc60050937c8d6e4e752aba798d80cc4c1a6f9461d30591d2c655758445f` |
| `ci/project/test_hwemu_git_environment.py` | `eb2c35818cd581b537379a1ef4b20f904052a013b11484dbdd3a236b93497349` |

The controlled configuration-scope defect and its local correction are proven.
The original hosted log did **not** print the runner's actual system/global
configuration, so attribution of that exact hosted failure to those settings
remains a supported hypothesis. Local review and the corrected suite do not
establish hosted recovery; the original failed run remains preserved below.

## Resources and preservation

The shallow checkout occupies about 339 MiB, with approximately 50.63 GiB free
on the workspace filesystem at the preservation audit. No vendor/GPU toolchain
was downloaded. Disposable fixtures use tiny synthetic artifacts. The distinct
`/tmp` filesystem has less than the 15-GiB execution reserve; a real resource
check correctly blocked a candidate placed there. Tests that mock resource
observations label those observations explicitly without lowering production
limits.

The initial preservation review recomputed 3,173 baseline blobs. Only the seven
intended tracked files differed at that checkpoint. It also verified 161 retained
artifact SHA-256 references without a mismatch. Accepted evidence, prior
continuations' execution ledgers, phase roadmap/dependencies, golden data, pins
and shared baseline/preflight/verifier code are unchanged. All new delivery
files are UTF-8 text; no vendor packages, binaries, logs or disposable fixtures
are part of the change.

The protected illustration remains byte-identical and embedded in the README:
`docs/assets/img/vortex_framework_stack.svg`, SHA-256
`db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`.

## Publication record

### Initial implementation and retained hosted observations

The initial implementation was published to `baabi-boo/AI-GPU` `master` as
[`81e35e97d2fa410bbfbb970b53ccc179b0aa8d27`](https://github.com/baabi-boo/AI-GPU/commit/81e35e97d2fa410bbfbb970b53ccc179b0aa8d27),
tree `dd72cfa527ad47a7cd967336528a7de1c00aa90b`, with sole parent
`91b82fe300f94ab0a70dd0e0e4a69a0e23b16101`. Independent remote readback at
`2026-11-16T00:39:43Z` confirmed that branch head and the immutable commit/tree;
all 67 code paths matched the initial 788-test content set. That readback is a
point-in-time publication observation, not a hosted test result.

| Initial hosted observation for `81e35e97d2fa410bbfbb970b53ccc179b0aa8d27` | Retained outcome |
|---|---|
| [Project Governance run 43781442015](https://github.com/baabi-boo/AI-GPU/actions/runs/43781442015), attempt 1, [job 133019311021](https://github.com/baabi-boo/AI-GPU/actions/runs/43781442015/job/133019311021) | Completed **failure**, updated `2026-11-16T00:39:18Z`: 788 tests in 108.657 seconds, 164 failure records including subtests, no skips, exit 1 |
| [Main CI run 43781441841](https://github.com/baabi-boo/AI-GPU/actions/runs/43781441841), attempt 1 | Still **in progress** at `2026-11-16T00:42:21Z`: plan, change-impact and setup passed; builds for 32 and 64 were running; actual test matrix and final outcome were unverified |

The failed Governance job passed prerequisites, project/evidence validation and
baseline-packet consistency, then failed its tooling tests. Positive source
fixtures returned unavailable revision/tree/dirty, with downstream planning and
resource failures. Its retained decoded log has SHA-256
`fb08d40e1e7bd8b361814a685c64190a39f7dc63858934546716929a7b0d3151`.
The hosted log reports Git 2.56.1 and Python 3.12.3 but does not expose the
runner's filter configuration. These initial observations remain part of the
history even after later successful checks; neither run is recorded here as a
pass.

### Correction and final delivery — pending

The Git-configuration correction is independently reviewed and locally validated
at the exact content hashes above. Its publication commit/tree and remote
readback are **pending**. Subsequent hosted runs must be bound to that exact
published correction before recovery can be recorded. Final completed-agent
accounting and any later documentation/accounting publication are also
**pending** and must be filled only after they occur. This checkpoint does not
claim all 60 assignments completed or final delivery achieved.

## Next bounded action

The FPGA-platform owner supplies a qualified vendor release/platform and an
actual matching build packet. The verification owner reviews the candidate,
resolves the recorded compiler-glob follow-up before promoting an execution
contract, and uses a separately reviewed bounded supervisor to obtain the
required DMA/launch/completion smoke evidence. Limit execution to two workers,
at least 15 GiB free disk, at most 6 GiB RSS and 16 MiB of logs, with a reviewed
per-command timeout no greater than 7,200 seconds. Stop for any absent
prerequisite, identity mismatch, unexplained numerical error or budget breach.
Preserve all commands, failures,
reference checks, configuration and identities, then seek the independent
acceptance review required by [P01](phases/p01-baseline.md). Keep P01-A03 blocked
until those requirements are met; neither offline planning nor vendor-free
`xrtsim` closes it.
