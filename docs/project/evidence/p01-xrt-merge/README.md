# P01 XRT merge tooling verification

This packet records the local combined tooling suite for implementation
`ae27591d1e4b7c9f2ec802c75fd6556b95a0483b`, tree
`9d2be910dd14ce4e6fabf2e30e4d84db98d835c7`.

**All 1075 source-root tooling tests passed, with zero failures, errors or skips**,
exit 0. The retained run reports 127.156 seconds in unittest and
127.569 seconds of measured wall time, from
`2026-11-16T01:05:12.345327+00:00` through
`2026-11-16T01:07:19.931192+00:00`. The integration owner recorded
a clean worktree before and after execution and no changes to 92 selected
source files; their retained hashes also match this exact immutable commit.
All four shared configuration/Tcl tests and all four new Git configuration
regressions report `ok` in this run.

The recorded command, from the repository source root, is:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

The result belongs to this exact tested commit/tree. Later evidence or delivery
documentation does not change that identity.

## Preserved integration history

| Integration | Exact commit | Ordered parents |
|---|---|---|
| Initial XRT/hwemu merge | `236770d6083ae88749e1830dd08eb72ee4327f97` | `42e36724a2f2a02766b26de8deb9b04b7557fa27`, `81e35e97d2fa410bbfbb970b53ccc179b0aa8d27` |
| Subsequent concurrent fix | `ae27591d1e4b7c9f2ec802c75fd6556b95a0483b` | `236770d6083ae88749e1830dd08eb72ee4327f97`, `e9e36c1cdccf975e330d9a9d2d67f3df9e50ba98` |

The seven XRT runner/helper modules remain byte-identical to `42e36724`.
The eight hwemu modules match the later concurrent `e9e36c1` revision. That
revision makes Git metadata probes ignore machine/global configuration while
retaining repository/worktree configuration and explicit includes for safety
inspection. It adds four real-Git configuration-scope regressions. The earlier
1071-test result predates this fix and does not verify it.

The shared `xrt.ini.in` and `xsim.tcl` remain byte-identical to `81e35e97`:
generated debug/profiling defaults are off, and waveform capture requires
explicit debug configuration plus exact `VORTEX_XRT_WAVEFORM=1`. The bounded
runner retains its separate no-hook, tracing-disabled smoke INI and direct
launch.

The shared configuration test file consolidates **1 + 4 parent tests into 4**,
with no lost assertions, as reviewed in assignment 50. The duplicate hook check
retains the exact existing tracked Tcl path and missing-script diagnostic; the
stronger assertion rejects every unexpanded `@` character. The remaining cases
retain lean INI defaults, non-opt-in Tcl inputs and exactly one recursive
waveform call for the exact opt-in. Fresh isolated RV64 configure remains part
of the tests; missing Tcl remains an explicit skip rather than a claimed pass.

## Retained evidence

- [Merge verification](merge-verification.json) records the actual primary and
  historical results, immutable identities, artifact hashes and boundaries.
- [Source comparison](merge-source-comparison.json) retains the immutable blob
  and SHA-256 identities behind the parent-preservation checks.
- [Primary raw suite log](p01-xrt-ae27591-tests.log) and
  [original execution metadata](p01-xrt-ae27591-tests.json) are copied byte-for-byte
  from the integration owner's captured run, without rerunning the suite.
- The [intermediate 1071-test log](history/236770d6/p01-xrt-merged-tests.log) and
  [metadata](history/236770d6/p01-xrt-merged-tests.json) retain the passing
  `236770d6` / `449e538d1066df343b501ab365fa521cb2cdc2fa` observation: zero
  skips, exit 0, 121.926 seconds in unittest and 122.255 recorded wall seconds.
  Its [58-path classification](history/236770d6/p01-xrt-merged-change-impact.json)
  and raw captures remain under the same historical directory.
- The [875-test packet](../p01-xrt-tooling/verification.json) remains a separate
  historical observation of `42e36724a2f2a02766b26de8deb9b04b7557fa27` and tree
  `c0f28a660c0a5c8b16d3f82adee06d104668d4e5`; this packet does not alter it.

## Immutable-base change impact

The base revision's classifier and policy classify
`91b82fe300f94ab0a70dd0e0e4a69a0e23b16101` through the primary tested commit as
**R2**, determinate, under policy version 3: **59 changed paths** comprise 11 R0,
46 R1 and 2 R2 paths. The R2 paths are the shared INI and Tcl files; no R3
contract detector fired. The configure-copied reminder applies to the INI.

[Raw classification](p01-xrt-ae27591-change-impact.json),
[explanation](p01-xrt-ae27591-change-impact.explain.txt),
[command log](p01-xrt-ae27591-change-impact.log),
[execution metadata](p01-xrt-ae27591-change-impact.commands.json) and
[immutable-base provenance](p01-xrt-ae27591-change-impact.provenance.json) retain
the actual results. Both commands exited 0; the base-file hashes were unchanged
after execution. Provenance identifies recoverable base Git blobs, while the
original commands retain historical scratch paths. Classification is advisory
and supplies no waiver, approval or replacement for review and test evidence.

## Boundaries and open work

`hwemu.py` inventory/plan and `xrt_baseline.py` retain separate strict
manifest/receipt/report schemas, build assumptions and budgets. A common
`schema_version: 1` does not make their inputs interchangeable. The XRT runner
constructs fixed commands from its own reviewed manifest and requires a fresh
build. It does not consume or promote a hwemu candidate. The read-only
planner's `launch_ready` remains false.

The hwemu **F1 compiler-glob follow-up remains open and unwaived** in the
[backlog](../../backlog.md). The Git configuration fix and the separate runner
do not resolve unquoted glob handling in manually written compiler-stamp
operands or establish vendor qualification. Actual producer records and
effective-invocation review remain required before promoting that candidate
to an execution contract.

This is source-level tooling evidence. It includes no vendor or GPU execution,
physical FPGA, performance or silicon measurement. P00 remains complete;
P01-A01/A02 retain their accepted historical evidence; P01-A03 and P01 remain
blocked, and P02 remains `not_started`. No 60-assignment completion, hosted CI
success, remote publication, maintainer approval or new phase acceptance is
claimed by this packet.
