# P05 original-artifact replay evidence

This packet separates **recorded installed PyTorch execution** from the
**inert review of its original artifacts**. The selected primary execution is
`c6fb039e706e812b6b3f4d2a5db1828076fe50df`,
[Installed PyTorch run 45349805332, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45349805332).
FP16 and BF16 ran separately using **PyTorch 2.15.0+cpu, CPython 3.12.14,
little-endian Linux x86_64 with the GIL and main interpreter, and RV64 SimX**.
Both hosted format jobs and both complete retained replays passed. The separate
[P05-A02 execution decision](acceptance-torch.json) and
[P05-A03 compatibility decision](acceptance-compatibility.json) accept this
bounded matrix after independent review, completing P05 alongside retained A01.
The reader itself never grants acceptance.

The historical execution at
`c0b44ce64665fe11895f869eea8c38c9b820d6f7`,
[run 45244780331, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45244780331),
is separate corroboration. Its two original archives also passed retained
review. Do not combine c0 and c6 into a single tested source revision.

## Entry points

| Record | Purpose |
|---|---|
| [Primary c6 intake](fresh-seam-intake.json) | Provider run/job results, original artifact identities and independent size/digest matches |
| [Historical c0 intake](intake.json) | Separately selected original identities and provider observation for the earlier revision |
| [Original retention](original-retention.json) | Exact unchanged archive identities preserved outside Git; owner access is distinct from public availability |
| [P05-A02 decision](acceptance-torch.json) and [P05-A03 decision](acceptance-compatibility.json) | Separate source-scoped simulation and compatibility acceptance |
| [Validation summary](validation-summary.json) | Exact reader identities, source-bound outcomes, failures, skips and limitations |
| [Review ledger](reviews/ledger.json) | Actual distinct agents, fresh contexts, assigned scopes and retained reports |
| [Compatibility matrix](../../p05-torch-compatibility.md) | Exact tested environment, operator/layout matrix and unsupported contexts |
| [Replay handoff](../../p05-torch-replay-handoff.md) | Safe public CLI, independently supplied pins and result interpretation |
| [Replay contract](../../../designs/torch_archive_replay_v1.md) | Retained-data semantics, trust boundary and no-execution requirements |
| [Operator contract](../../../designs/torch_custom_ops_v1.md) | Eager schemas, actual native dispatch, storage, ownership and recovery |
| [Development audit](../../p05-torch-replay-audit.md) | Implementation history, independent findings and publication scope |
| [Acceptance policy](../../acceptance.md) and [canonical roadmap](../../roadmap.json) | Required decision procedure and authoritative phase state |

## Independently selected originals

The recorded filenames are useful labels, not trust inputs. The CLI accepts a
caller-selected absolute canonical path with any filename; SHA-256, exact
execution revision and format are independently supplied. All four downloads
matched their corresponding provider-recorded size and digest.

| Role / format | Original filename | Bytes | SHA-256 |
|---|---|---:|---|
| Primary c6 / FP16 | `p05-torch-fp16-c6fb039e-original.zip` | 21,444,979 | `d9e9a713ef716882086b6c8176d1d27c4c98acae77110c58f84bdb69a00c4aaa` |
| Primary c6 / BF16 | `p05-torch-bf16-c6fb039e-original.zip` | 21,445,834 | `85498037f9a8b06bbb44357208f236ad325dc686934059bc472348c4524a74b3` |
| Historical c0 / FP16 | `p05-torch-fp16-c0b44ce6-original.zip` | 21,439,407 | `8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c` |
| Historical c0 / BF16 | `p05-torch-bf16-c0b44ce6-original.zip` | 21,439,104 | `787fd1b41a27da8c100277613c581ba734920fd45b13e0707ba0f9ea2e866330` |

Preserve the original ZIP bytes. All four originals were saved unchanged as
durable owner-accessible artifacts outside Git, as recorded in
[original-retention.json](original-retention.json). The repository contains
their immutable pins and review receipts, not the ZIP payloads. Public provider
retention and availability remain separate; a future public reviewer may need
the owner to supply an original if GitHub retention has expired. A later download
must match the independently selected original. A matching hash identifies
bytes and does not authenticate an arbitrary producer.

## Recorded population and review scope

Each original has 663 retained members. The complete replay checks all member
bytes and reconciles native raw outputs, frozen fixtures, actual model
intermediates, Python/framework operand and result bytes, native dispatch,
explicit close, restored resources, package/source joins and exact copied
packets. These are data checks on recorded work.

| Population | Per original / format | Both formats at one execution revision |
|---|---:|---:|
| Framework operator calls | 16 | 32 |
| Framework-route native launches | 36 | 72 |
| Native comparison launches | 36 | 72 |
| Plain-Python launches | 36 | 72 |
| Distinct recorded launches | **108** | **216** |
| Framework event/profile pairs | 180 | 360 |
| Additional launches from packet copies | **0** | **0** |

The 16 framework calls comprise six standalone matmuls and ten fixed-model
calls. The three matmul signatures and five fixed-model families each run with
both output poisons. Each fixed model uses three native launches, with ReLU,
format conversion and row assembly retained as declared host work. The c0 and
c6 rows above represent different execution populations.

Independent supplementary review a33 reconciled **45 unique scripted host
definitions plus nine compiled host scenarios in each original**. Raw logs,
reported outcomes, child command/results and source/artifact identities agree;
the scripted results have zero failures, errors or skips. Those definitions
repeat across both formats and both revisions. They are not 180 unique tests,
36 unique scenarios or extra native accelerator execution. The older
[43-test development receipt](../p05-torch/development/integrated-torch-host.json)
remains historical.

Some host capture arrays and intermediate failure/ownership channels were not
retained. The supplementary review establishes the enumerated source and
outcome joins, while the public reader checks bounded envelopes and retained
bytes. **Complete host semantic reconstruction is not established**;
`host_fault_semantics_revalidated=false` and
`supplementary.host_test_results_revalidated=false` remain correct. Scripted
or compiled host fixture arithmetic is not native numerical evidence.

Independent source review a49 matched retained first-party bytes at **82 unique
paths** to the selected Git revision, plus **731 receipt-only paths**, for an
813-path first-party union per original. The 731 paths are not archived
historical filesystem bytes. Another 193 submodule source paths lack the same
byte comparison. Receipt occurrences and copied files do not add unique source
paths or launches. Third-party wheel/payload bytes, interpreter/tool/seed bytes
and some generated metadata are absent; their recorded identities and
inventories support consistency, not fresh byte-level requalification or
reproducible compilation.

## Reader identity and accepted evidence

The complete reader was published at
`d8abc24d2fd5dab5ceddbae3627e3d3eb9750358`. That is a reader checkpoint, not the
original execution revision. Subsequent reviewed parser repairs and any new
validation must retain their own exact source identities. The `reader_sources`
manifest in each replay output identifies the files that actually supplied that
result; a later checkout must not relabel an earlier output as its own test.
The unchanged shared archive reader remains separately hash-pinned by the
replay implementation.

The independent a33 host, a49 source and a53 frozen-criteria reviews support the
bounded evidence assessment. The [review ledger](reviews/ledger.json)
retains actual agent identities, source-scoped reports and dispositions.
[Validation-summary.json](validation-summary.json) binds original/replay/source
identities and exact verification outcomes, including later independently
reviewed parser fixes. Earlier reports retain the status and source snapshots
they observed; pending language in a historical review is not a current phase
decision. Overlapping suites and repeated probes are not added as unique coverage.

Every successful replay still reports `native_execution="not_run"`,
`retained_code_executed=false`, `acceptance_claimed=false` and
`phase_acceptance=false`. No archive member is imported, executed or extracted,
and no recorded producer path is opened. An Installed PyTorch workflow pass is
specific to that run; it does not imply a general CI or governance pass for a
different checkpoint. P01-A03, P06-A02/A03, the P06 15 GiB resource guard,
processor RTL, vendor emulation, physical FPGA, silicon and physical performance
remain outside this packet's result.
