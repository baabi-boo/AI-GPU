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
| Implementation publication identity | Recorded after the reviewed tree is published and read back |
| Current release state | Locally validated implementation; publication verification pending |
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
intermediate run passed 787 tests. After the final compiler-record correction,
the complete source-root suite passed **788 tests with zero skips in 85.925
seconds** (86.209 seconds including its wrapper), using Python 3.12.14 and Git
2.52.0. These are host tooling/governance results, not GPU execution results.

All local commands below ran from the source root. For the standalone CLI,
`$FIXTURE` is a path alias for the owned temporary fixture directory; its
`manifest.json` was passed as an absolute path. The directory was removed after
the two observations, and its private machine path is not published.

| Command / observation | Outcome and exit code | Exact scope |
|---|---|---|
| `python3 -B ci/project/preflight.py --tier governance` | Pass, `0` | Vendor tools absent and submodules uninitialized are named, optional governance prerequisites |
| `python3 -B ci/project/check_project.py` | Pass, `0` | Structure, links and metadata only |
| `python3 -B ci/project/check_baseline_packets.py` | Pass, `0` | Both retained packets; public consistency only |
| `python3 -B -m unittest discover -s ci/project -p 'test_*.py'` | Pass, `0` | 788 tests, zero skips, after the final code correction |
| `python3 -B -m unittest discover -s ci/project -p 'test_xrt_configuration.py' -v` | Pass, `0` | Four tests, zero skips; real fresh out-of-tree configure and Tcl hook checks |
| `python3 -B ci/project/hwemu.py plan "$FIXTURE/manifest.json" --json`, complete synthetic inputs | `planned`, `0` | Actual resource observations; all qualification/execution/phase flags remain false |
| Same CLI invocation after same-size corruption of the synthetic xclbin | `blocked`, `1` | No candidate; file-identity mismatch detected |
| `git diff --check` | Pass, `0` at review checkpoints | Repeated for publication |
| Vendor build, full `hw_emu`, physical FPGA, synthesis and GPU workloads | `not_run`, no exit code | Qualified tools/platform absent; no RTL/SimX timing change is included |

The following digests identify the retained coordination observations. These
local logs are not packaged as public vendor-execution evidence. Hosted CI
observations are recorded separately below as they become available.

| Local observation log | SHA-256 |
|---|---|
| `integrated-preflight.log` | `02ed4cac8e91c00397f47eb4c6718f9baa8887554c8921eea5809495a01f3ec0` |
| `integrated-project-check.log` | `d505e20764bb8ca9754d5a40ae3dede73831b96c6b6d0020065e6a3b87960993` |
| `integrated-baseline-packets.log` | `fe35ed00868a1b653caa23c1fdade37cce4ad8691b9a9cd08a222e82afae28be` |
| `final-unittest.log` | `500c59a589ac5eed311a3fc3c689599f1a47c629efb522f7af8375c16d810738` |
| `change-impact.xrt-test.log` | `d181f86801beaf8c5fca15b41c8922de4490dc5ea497f53ae153c47c6141d16a` |
| `w07e-complete.json` | `0d68c4688f0305336e258ed32dd2d765b0afd536886f6574b94bee995265442a` |
| `w07e-same-size-xclbin-corruption.json` | `c243bfdb4222bbd3f622a2e52fefb13142fa6f70035bd839b09039e5e8057f70` |

The final local suite recorded identical before/after hashes for all 65
`ci/project/*.py` files and both changed XRT files. Its content-set digest is
`aef71e5fa9e21fa99f13b64741608dfc46d777f7c9e3d89d0596b310e7c3f3f4`:
SHA-256 of compact sorted-key JSON mapping source-relative paths to their
SHA-256 content hashes. The final test-log SHA-256 is
`500c59a589ac5eed311a3fc3c689599f1a47c629efb522f7af8375c16d810738`.
The exact published implementation commit/tree and hosted CI observations belong
in the publication record below; the starting HEAD alone does not identify the
modified tree tested locally.

The standalone fixture check observed about 50.63 GiB of free disk and 7.57 GiB
of host `MemAvailable`, retaining the production 15-GiB disk reserve and 6-GiB
RSS budget. Its inputs and index metadata did not change during either CLI call;
no vendor/setup execution marker appeared. The fixture was removed afterward.
Host memory observations do not establish an effective container/cgroup limit.

## Independent review and disposition

The base revision's classifier and policy classify this scope as **R2**, because
of the two XRT software-stack files. The 33-file review snapshot has nine R0,
22 R1 and two R2 files, with no R3 contract detector. The sole emitted evidence
obligation is testing the changed INI from a newly configured build tree; the
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

All F2/F3 findings in the final implementation/test review are closed; none is
waived. The F1 follow-up for unquoted glob characters in unusual hand-written
compiler operands is recorded in the [backlog](backlog.md). The inspector does
not expand globs against a compilation directory. Actual producer records and
review of the effective invocation remain required before any separately
supervised execution; a plan never grants launch readiness. Some isolated test
children may create small ignored Python caches; this is not a CLI output or a
change to retained source/evidence.

## Resources and preservation

The shallow checkout occupies about 339 MiB, with approximately 50.63 GiB free
on the workspace filesystem at the preservation audit. No vendor/GPU toolchain
was downloaded. Disposable fixtures use tiny synthetic artifacts. The distinct
`/tmp` filesystem has less than the 15-GiB execution reserve; a real resource
check correctly blocked a candidate placed there. Tests that mock resource
observations label those observations explicitly without lowering production
limits.

The preservation review recomputed 3,173 baseline blobs. Only the seven intended
tracked files differ. It also verified 161 retained artifact SHA-256 references
without a mismatch. Accepted evidence, existing execution ledgers, phase
roadmap/dependencies, golden data, pins and shared baseline/preflight/verifier
code are unchanged. All new delivery files are UTF-8 text; no vendor packages,
binaries, logs or disposable fixtures are part of the change.

The protected illustration remains byte-identical and embedded in the README:
`docs/assets/img/vortex_framework_stack.svg`, SHA-256
`db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`.

## Publication record

Publication, remote commit/tree readback, final completed-agent accounting and
hosted CI observations are recorded here after they occur. Local validation is
complete for the implementation identities above; no remote CI result is
claimed at this checkpoint.

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
