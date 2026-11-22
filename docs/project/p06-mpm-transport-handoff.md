# Host counter transport handoff

The RV64 host MPM transport repair restores the high 32-bit reply used by
`vx_device_mpm_query`. At `18c888058ac851b802350c99770ed9ac2d27b582`, all eight
strict native cells pass and both pinned-parent targets fail the expected numeric
assertions after successful builds. The immutable governance suite passes 2,910
tests. Paired circuit and alternative reviews select the direct decoder at
`18c8880`; the specific missing-comparison finding is closed. Broader repository
CI remains in progress at this checkpoint; overall CI success is not asserted.
Use the [evidence index](evidence/p06-mpm-transport/README.md) for subsequent
results, the [audit](p06-mpm-transport-audit.md) for the development decision,
and [host MPM transport v1](../designs/host_mpm_transport_v1.md) for the frozen
behavior and evaluation requirements.

## Repair and preserved interfaces

The public API assembles a `uint64_t` from two unsigned 32-bit DCR replies on
both RV32 and RV64. Its addresses, tag fields, error handling, read order and
per-core summation are unchanged. In SimX, the RV64 host adapter reads the full
low-address counter and selects bits `[31:0]` or `[63:32]`; RV32 retains its
existing low/high CSR route. The temporary MPM class is restored after supported
reads. The host-only RTL decoder supplies both halves independently of XLEN:
its 44-bit counters produce a zero-extended 12-bit high reply.

Architectural device CSR behavior remains unchanged. RV64 low addresses return
the full implemented value, and supported high aliases remain zero. The repair
adds no pipeline stage, atomic snapshot, rollover retry, concurrent-caller
guarantee or absolute no-wrap proof. Counters must remain stable across the
serialized reads. SimX retains its 64-bit counters; RTL remains 44-bit.

The original `sim/simx/Makefile` stays byte-identical to the historical P02-A02
acceptance pin. The additive
[`mpm_transport.mk`](../../sim/simx/mpm_transport.mk) includes that Makefile and
links the directed test with the actual processor model. `configure` copies the
fragment into generated build trees. Existing production targets are preserved.

## Reviewed execution and circuit comparison

The [native packet](evidence/p06-mpm-transport/hosted/attempt3-native.json) and
[independent review](evidence/p06-mpm-transport/reviews/native-review.md) bind
run [44983573225](https://github.com/baabi-boo/AI-GPU/actions/runs/44983573225)
to actual PR merge checkout `6e6426a0bf761baab11e932a4c86b49a5de81217`, tree
`d6dd742a905e0f3e76c7374cc678ba87e5c2a19e`, identical to candidate `18c8880`.

| XLEN | PERF | RTL reads / assertions | Linked SimX checks |
|---|---|---:|---:|
| 32 | Off | 188 / 3,610 | 3,781 |
| 32 | On | 340 / 6,346 | 5,251 |
| 64 | Off | 188 / 3,610 | 3,781 |
| 64 | On | 340 / 6,346 | 5,251 |

All eight cells passed. The RTL leaf exercises actual `VX_dcr_data` and
`VX_csr_mpm`; SimX traverses the processor/cluster/socket/core/CSR route, with
41 model objects plus the harness. This establishes stable seeded-counter
behavior with TCU disabled, not full-AFU, public-runtime end-to-end, broader
topology, enabled-extension or physical-hardware coverage.

Both old-production targets compile and exit 1 on the same harness. RTL reports
tag `00220001`, expected high `00000001`, actual `00000000`; all 714 SimX
failures among 5,251 checks match missing high words or their truncated
reconstructions. The first two hosted attempts' separate Git-staging failures
remain in the evidence index; they did not establish parent sensitivity.
Detached worktrees now preserve the pinned production source and identical
test overlays.

The [circuit review](evidence/p06-mpm-transport/reviews/circuit-review.md)
verifies eight Beacon runs before eight generic Yosys runs. RV32 is unchanged.
RV64 adds 21/417 estimated LUTs and 24/72 optimized wrapper FF bits with PERF
off/on; measured depth stays unchanged. Raw `NO-BASELINE` and area failures
remain. The [alternative review](evidence/p06-mpm-transport/reviews/alternative-review.md)
closes the concrete comparison: shared decoding saves 2/68 estimated LUTs but
adds 9/21 generic cells, increases the PERF-off path 7 → 8 and PERF-on watch
endpoints 12 → 32. Keep the direct decoder; the experimental PR is closed without
adopting its code. This is the depth-preserving tested choice, not a global
optimum or passing area gate. Generic cells/paths establish neither physical
area, STA nor Fmax.

The [immutable integration log](evidence/p06-mpm-transport/host/governance-18c8880.json)
records 2,910 passing tests at `18c8880`, exit 0. Refer to the
[CI snapshot](evidence/p06-mpm-transport/hosted/final-ci-validation.json) for separately
scoped hosted results and pending checks.

## Reproduce with fresh, bounded trees

Prepare pinned tools and required dependency libraries first. From a clean,
tracked source checkout, use absolute literal paths without symlinks; work and
output directories must be fresh, separate and outside source/tools, under
existing parents:

```sh
python3 ci/project/p06_mpm_execute.py \
  --source-dir "$PWD" --tools-dir /absolute/pinned/tools \
  --work-dir /absolute/new/mpm-work --output /absolute/new/mpm-packet \
  --xlen both --engines both
```

The runner freshly configures each XLEN/PERF variant, builds and executes each
binary separately, and retains commands, logs and identities. Budgets are two
build jobs, `THREADS=1`, 4 GiB polled process-group RSS, a 15 GiB disk reserve,
16 MiB logs, and configure/build/run timeouts of 120/1,800/180 seconds.
These are monitored budgets, not hard quotas. `--development` is explicitly
nonqualifying; a selected subset cannot establish the full matrix. The
[enforcement review](evidence/p06-mpm-transport/reviews/enforcement-review.md)
records an F1 standalone provenance gap: native tool identities hash PATH
`python3` but not `sys.executable` separately. Hosted execution checks equality;
record the executing interpreter before future standalone qualification use.

For an individual SimX diagnostic, re-run `configure` into a fresh variant tree
with explicit `--xlen=32` or `--xlen=64`, `--profile=` and the pinned `--tooldir`.
Inside its generated `sim/simx` directory, the build/run selection is:

```sh
make --no-print-directory -f mpm_transport.mk -j2 THREADS=1 \
  CONFIGS= PROFILE= PERF= "$PWD/mpm_transport_test"
./mpm_transport_test
```

`PERF=` means off; use `PERF=1` in a separate fresh tree for on. `PERF=0` still
enables Makefile `ifdef` branches. Direct commands do not provide the runner's
environment isolation, resource monitoring or retained provenance.

Before invoking `p06_mpm_parent.py` or `p06_mpm_synthesis.py`, fetch pinned
reference `4df7186edbca82b21b2b8cba9b3b192248b99209`. Both accept the same four
path arguments as above and require their own fresh work/output directories.
The parent check accepts only genuine native high-half failures. The synthesis
runner keeps completed measurements separate from gate acceptance.

## Next bounded development action

The transport native, cost-comparison and local host obligations are complete;
final broader CI and publication identities remain separately tracked. Follow
the [qualification plan](p06-mpm-qualification-plan.md): implement and independently
review a versioned layer binding repaired source, configuration and binaries and rejecting
old or mismatched packets. Then obtain a fresh complete matched warm attempt:
24 processes, 792 launches and 25,344 exact output words under unchanged rules.
Historical low words cannot recover missing high bits.

Preserve the unconditional `P06-WARM-RV64-MPM-HIGH-HALF` v1 block,
`qualified=false`, `absolute_no_wrap_bound="not_established"`, original cold
execution pins and all historical acceptance scopes. This repair does not close
P06-A02/A03, P01-A03, P05-A02/A03 or the inherited DSP-area finding.
