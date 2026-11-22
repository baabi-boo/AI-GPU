# P06 host MPM transport evidence

**The strict eight-cell native matrix and both numeric parent-sensitivity checks
pass review at `18c8880`.** The immutable governance suite passes 2,910 tests.
All eight Beacon and eight generic Yosys measurements completed. The measured
alternative comparison selects the direct decoder and closes its specific F2;
raw RV64 area failures remain failures. Broader repository CI is still running
at this checkpoint. No overall CI-green, publication, phase acceptance or
historical warm qualification is claimed.

Start with the [audit](../../p06-mpm-transport-audit.md),
[frozen contract](../../../designs/host_mpm_transport_v1.md),
[handoff](../../p06-mpm-transport-handoff.md) and
[next qualification plan](../../p06-mpm-qualification-plan.md).
The repair restores both unsigned 32-bit host DCR halves on RV64 while preserving
the API, architectural CSR behavior and registered response schedule.

## 1. Strict native matrix and parent sensitivity

The [native index](hosted/attempt3-native.json), [raw ZIP](hosted/attempt3-native.zip)
and [independent review](reviews/native-review.md) retain
[run 44983573225](https://github.com/baabi-boo/AI-GPU/actions/runs/44983573225),
native job `137089144698`, artifact `14738787973`, attempt 1.

| Source identity | Exact value |
|---|---|
| Candidate head | `18c888058ac851b802350c99770ed9ac2d27b582` |
| Actual PR merge checkout | `6e6426a0bf761baab11e932a4c86b49a5de81217` |
| Shared complete tree | `d6dd742a905e0f3e76c7374cc678ba87e5c2a19e` |
| Unrepaired production reference | `4df7186edbca82b21b2b8cba9b3b192248b99209` |

Each configuration uses a freshly configured build tree, empty profile and
extra `CONFIGS`, TCU disabled, and separate build/run commands. PERF off is
unset/empty; PERF on is `1`.

| Configuration | RTL reads | RTL assertions | Linked SimX checks | Result |
|---|---:|---:|---:|---|
| RV32, PERF off | 188 | 3,610 | 3,781 | Both pass |
| RV32, PERF on | 340 | 6,346 | 5,251 | Both pass |
| RV64, PERF off | 188 | 3,610 | 3,781 | Both pass |
| RV64, PERF on | 340 | 6,346 | 5,251 | Both pass |
| **Total** | **1,056** | **19,912** | **18,064** | **Eight passes** |

RTL instantiates production `VX_dcr_data` and `VX_csr_mpm`, checks 44-bit halves,
seven ignored requests per variant and two-edge responses. SimX traverses the
actual Processor/Cluster/Socket/Core/CsrUnit route. Each of five SimX builds,
including the parent, compiles and links 41 production objects plus the harness.
The additive make fragment preserves the original SimX Makefile's P02 pin.

Both pinned-parent targets build successfully and then exit **1** under the
unchanged harness. RTL reports tag `00220001`, expected `00000001`, actual
`00000000`. Every one of the **714 SimX failures among 5,251 checks** is
independently reconciled: 357 missing high replies, 238 truncated low-first
reconstructions and 119 truncated high-first reconstructions. No compiler,
timeout or unrelated assertion supplies this sensitivity evidence.

The review verifies 125 safe archive members, CRCs, 34 structured logs,
configuration/compiler records, original source hashes and identical parent test
overlays. Recorded source/tool/configuration and binary identities stay stable.
Executable bytes are not archived, so offline review cannot rehash or rerun
those binaries. The packet keeps `qualified=false`, `acceptance_claimed=false`
and an unestablished absolute no-wrap bound.

## 2. Paired circuit evidence and cost review

The [circuit index](hosted/attempt3-circuits.json), [raw ZIP](hosted/attempt3-circuits.zip)
and [independent review](reviews/circuit-review.md) bind the same candidate/tree
to job `137089144444`, artifact `14738343862`. All eight Beacon measurements
precede all eight generic Yosys confirmations. The review checks 263 archive
members, 46 structured logs, 204 retained artifacts and original candidate/
reference sources with identical wrapper/catalog overlays.

Numbers below are unrepaired parent → repaired candidate.

| Variant | Beacon LUT | Beacon depth | Yosys cells | Yosys FF | Yosys path |
|---|---:|---:|---:|---:|---:|
| RV32, PERF off | 93 → 93 | 4 → 4 | 397 → 397 | 168 → 168 | 7 → 7 |
| RV32, PERF on | 1,439 → 1,439 | 8 → 8 | 997 → 997 | 360 → 360 | 10 → 10 |
| RV64, PERF off | 72 → 93 | 4 → 4 | 320 → 397 | 144 → 168 | 7 → 7 |
| RV64, PERF on | 1,022 → 1,439 | 8 → 8 | 770 → 997 | 288 → 360 | 10 → 10 |

Raw build verdicts are `NO-BASELINE`; RV64 comparisons exit 3 for area:
**+21 LUT (+29.2%)** off and **+417 LUT (+40.8%)** on. The aggregate
`gate_outcome=fail` remains. Beacon FF counts stay 193/369; optimized Yosys
retains precisely 24/72 formerly discarded high-counter bits. These are wrapper
input registers becoming observable, not added production pipeline stages.
The flows count different abstractions and are not interchangeable.

The original review attributes the cost to `58c71d3` and records a missing-
alternative-comparison F2. The subsequent [independent comparison](reviews/alternative-review.md)
closes that specific finding while preserving the original review unchanged.
Candidate `27a18d4` in [run 44985166238](https://github.com/baabi-boo/AI-GPU/actions/runs/44985166238)
passes the same native matrix and both parent checks; its
[native](hosted/attempt4-native.json) and [circuit](hosted/attempt4-circuits.json)
archives retain the complete experiment.

| Direct → shared decoder, both widths | PERF off | PERF on |
|---|---:|---:|
| Beacon LUT change | −2 | −68 |
| Yosys generic cell change | +9 | +21 |
| Yosys path | 7 → 8 | 10 → 10 |
| Beacon watch endpoints | 0 → 0 | 12 → 32 |

The shared candidate also worsens Beacon's modeled delay. **Retain the direct
`18c8880` implementation:** the LUT saving does not preserve all measured
resources/depths. [PR 5](https://github.com/baabi-boo/AI-GPU/pull/5) is closed
without adopting the experiment. This establishes the lowest-cost
depth-preserving tested candidate under the stated constraints, not global
optimality or an area-gate pass. No golden or threshold changes. Neither flow
establishes whole-GPU fit, placed timing, Liberty area, STA or physical Fmax.

## 3. Host checks and integration

The [immutable governance receipt](host/governance-18c8880.json) and
[complete compressed log](host/governance-18c8880.log.gz) retain **2,910 tests,
1,516.847 seconds, exit 0** at `18c8880`. The focused MPM suite passes 73 tests;
these host adapter, runner, workflow and real-Git checks are not GPU executions.

```sh
python3 -B -m unittest discover -s ci/project -p 'test_p06_mpm*.py' -v
```

The [final hosted CI snapshot](hosted/final-ci-validation.json) records separately
scoped workflow results. Both hosted governance runs and all seven dedicated
workflows pass. The 92-job general PR workflow remains in progress; completed
transport/host checks do not imply that every repository CI job passed. Ordinary PR/push driver filters do
not select the new driverless catalog case; the dedicated workflow provides the
required native matrix. The [enforcement review](reviews/enforcement-review.md)
finds no F2/F3 in the hosted path. Its F1 follow-up is standalone interpreter
provenance: record `sys.executable` separately from PATH `python3` before future
standalone qualification use. Hosted execution already enforces equality.

The unchanged toolchain tag `v3.0.2` resolves to
`6cff3efdc1b721e4fec9165801ecd405be34dd11`. Budgets remain two build jobs,
`THREADS=1`, 4 GiB sampled RSS, 15 GiB free disk, 16 MiB per log and
120/1,800/180-second configure/build/run timeouts. Polled budgets are not hard
kernel quotas.

## 4. Retained development and failed attempts

| Record | Outcome retained |
|---|---|
| [Local RTL summary](host/rtl-matrix-summary.json) | Four candidate passes and the genuine old-RTL numeric failure; development provenance is narrower than strict hosted evidence. |
| [Initial configure](host/pilot-rv64-on/result.json) | Unsupported OS; no native execution. The later explicit Ubuntu bundle ran on an accurately identified Debian host. |
| [Local Beacon preparation](host/beacon-parent32/commands.json) | Blocked before execution by the 15 GiB reserve. |
| [First native attempt](hosted/attempt1-native.json) | Eight candidate passes; parent checkout exits 128 before parent build/run. |
| [Second native attempt](hosted/attempt2-native.json) | Eight candidate passes; same parent-staging failure. |
| [First circuit attempt](hosted/attempt1-circuits.json) | Missing `nanobind_backend`; zero measurements. |
| [Second circuit attempt](hosted/attempt2-circuits.json) | Import succeeds; parent checkout fails; zero measurements. |
| [Development governance](host/governance-development-attempt.json) | 2,873 tests, 104 failing subtests during source/helper edits; identity guards reject drift. This remains a failed run. |

`7396ded` pins the missing backend; `18c8880` uses detached reference worktrees.
Original ZIP bytes, raw errors and complete hashes remain in their indexes.

Stable directed counters do not qualify broader topology, enabled extensions,
moving/concurrent reads or absolute no-wrap bounds. Keep warm v1's unconditional
`P06-WARM-RV64-MPM-HIGH-HALF` block and historical pins. Future qualification
requires a reviewed binding and a fresh complete matched attempt. P06-A02/A03,
P01-A03, P05-A02/A03 and the inherited DSP finding remain separate. The
[agent ledger](agent-ledger.md) counts only completed worker receipts toward the
requested sixty-agent record. Original validation/experiment commits and their
evidence identities remain separate from the consolidated publication commit.
