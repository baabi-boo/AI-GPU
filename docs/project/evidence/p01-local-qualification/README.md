# P01 supplemental local qualification evidence

This packet records completed local AFU/RTL execution, tooling checks, corrections,
and independent reviews. **All eight local cases passed at `7e4ac585`; both fresh
unit cases passed at `143c69fe`.** P01-A03 remains blocked on qualified vendor
`hw_emu`, and P02–P11 remain `not_started`. This evidence does not qualify vendor
runtime/platform behavior, physical FPGA operation, host/device cache coherence,
or silicon behavior.

See the [reproduction guide](../../p01-local-qualification.md) and
[implementation handoff](../../p01-local-qualification-handoff.md) for commands,
configuration, unchanged numerical thresholds, limitations and the next bounded
vendor action.

## Results and source identities

| Execution | Actual tested local revision | Result |
| --- | --- | --- |
| First native attempt | `9532327e6006e0b6b09bae761745bc0d36a79b1e` | Failed: advertised stencil `-b` option was rejected before device access; later cases were not run. Preserved in full. |
| Corrected tooling suite | `7e4ac5851f1f71d292ed1802c3f92456d96faf8d` | 1,260 tests, zero failures/errors/skips; 293.241 seconds. |
| Corrected eight-case local run | `7e4ac5851f1f71d292ed1802c3f92456d96faf8d` | All eight cases and all 32 monitored commands passed, with complete cleanup and final identity checks. |
| Fresh CP/LLC and AXI unit follow-up | `143c69fe284bc2a1628721cf8a4237ac82d2547d` | Both selected units and all five commands passed using the strengthened CP oracle. No full suite or eight-case rerun at this revision. |
| Isolated CP mutation proof | `7e4ac585` plus retained proposed harness variants | Three deliberately injected defects escaped the original harness and failed the strengthened harness. All nine executions met their expected outcomes; expected failure exits remain failures in the raw records. |

The eight-case selection comprises demo, cold and warm reopen, 64-cubed AXI
store-order stencil, CP/LLC unit, AXI arbiter unit, and native TFR FP16/BF16 GEMMs.
The stencil observed 122 reordered responses and retained the original six-ULP
bound. Both 64×64×64 GEMMs reported zero mismatches under the inherited strict
relative-error threshold. The local STD floating-point/TFR arithmetic claim does
not imply an entirely DPI-free AFU: integer multiply/divide remain DPI-assisted.

The [identity map](identity-map.json) maps all three actual local commits to
GitHub commits with identical source trees. Different commit metadata and parent
identities produce different commit IDs. Original local commit object bytes are
included in the archive. Timestamped preparation audits are historical records;
branch delivery and hosted CI must be checked on the containing GitHub commit.

## Files and integrity

| File | Purpose |
| --- | --- |
| [packet.tar.gz](packet.tar.gz) | Deterministic archive: 566 text members, 7,254,083 uncompressed bytes; 1,244,701 compressed bytes. |
| [manifest.json](manifest.json) | Exact raw/public file mapping, declared path substitutions, sizes, hashes and explicit omissions. |
| [index.json](index.json) | Distinguishes attempts, follow-up, diagnostics, expected mutation failures and review scopes. |
| [identity-map.json](identity-map.json) | Exact tested-source/GitHub tree mappings and scope of the identity audits. |
| [agent-ledger.json](agent-ledger.json) | Exactly 60 completed assignments in ten waves of six, with unique task names and raw note hashes. Notes are under `agent-notes/` in the archive. |
| [SHA256SUMS](SHA256SUMS) | Checksums of the eight distributed files other than this checksum inventory itself. |
| [export_local_packets.py](export_local_packets.py) | Reviewed original native-attempt publication/integrity helper. |
| [export_final_packets.py](export_final_packets.py) | Reviewed complete-packet wrapper; requires the adjacent original helper. |

Archive SHA-256:
`555b9daaa54630d74c4793c4d79dc79c5c390d8eb6fdbe064040b8dfad95b825`.
The verifier's member-bundle SHA-256 is
`ac3c805a3b1ad19913c59d4cb16ff32dd0f48d8cd3ff8ca870c671c4baa00411`;
this is a separate digest domain from the compressed archive bytes.

From the repository root:

```sh
cd docs/project/evidence/p01-local-qualification
sha256sum --check SHA256SUMS
python3 -B export_final_packets.py verify packet.tar.gz
```

With the retained original execution workspace available, additionally run:

```sh
python3 -B export_final_packets.py verify packet.tar.gz --raw-workspace /absolute/path/to/original/workspace
```

That optional raw-workspace check reproduces the declared transformation and
compares every exported byte. The public-only check verifies distributed
integrity and recorded linkage. Neither check reruns workloads or authenticates
original execution: the manifest is unsigned. Embedded report hashes identify
raw bytes; the manifest's public hashes identify distributed bytes. Local path
substitutions and the logical `$AGENT_TREE` token are explicitly declared.

The archive retains failed attempts and the metadata-only first mutation setup
failure, source snapshots, logs, launch records, original commit bytes and all
60 finalized agent notes. The separate 8-cubed stencil diagnostic is not a
substitute for the completed frozen 64-cubed case. Binary/model artifacts retain
identities but their bytes are not distributed in this text packet; 91 omitted
CP proof members are individually recorded. Historical notes keep their original
time context and are not relabelled as final publication or hosted CI evidence.

## Resource limits and preserved gates

The completed native run used two build workers, at most 3,978,248,192 bytes of
sampled process RSS, and sequential fixed commands with a 1,800-second per-command
limit. Its policy retained a 15-GiB free-disk reserve, a 6-GiB sampled process-RSS
ceiling, a 16-MiB per-command log ceiling and a 512-MiB packet ceiling. These are
polled monitoring limits, not kernel-enforced quotas. No new toolchain download
or waveform collection was needed. The final resource audit recorded about
45.45 GiB free and approximately 1.60 GiB allocated across the three build roots.

All 36 acceptance criteria, prior accepted evidence, toolchain pins, submodule
identities, goldens and numerical thresholds remain unchanged. P00 is complete;
P01-A01 and P01-A02 retain their accepted historical evidence. Passing local
checks does not change `vendor_execution_performed: false`,
`qualifies_P01_A03: false` or `phase_complete: false`.
