# P05 original-artifact replay operator handoff

Use this handoff to review the original installed PyTorch evidence without the
producer's build tree, installation or native backend. **Replay runs trusted
local reader code only; it performs no native launch and grants no acceptance.**
The [evidence index](evidence/p05-torch-replay/README.md) holds the independent
original pins and counting rules, the
[compatibility matrix](p05-torch-compatibility.md) names the tested operators and
versions, and the [replay contract](../designs/torch_archive_replay_v1.md)
defines the retained-data boundary.

## Select the evidence and reader independently

The primary execution is
`c6fb039e706e812b6b3f4d2a5db1828076fe50df`, run 45349805332, attempt 1, using
PyTorch 2.15.0+cpu, CPython 3.12.14, little-endian Linux x86_64 with the GIL and
main interpreter, and RV64 SimX. Obtain both original ZIPs and compare their
provider metadata with the [c6 intake](evidence/p05-torch-replay/fresh-seam-intake.json).
Do not choose the expected digest or execution revision from inside the
candidate archive. Computing a candidate's hash and then treating that value as
an independent pin establishes no provenance.

Choose a separately reviewed source checkout containing the complete public
reader, [ci/project/p05_torch_replay.py](../../ci/project/p05_torch_replay.py),
and its local dependencies. The published complete-core checkpoint is
`d8abc24d2fd5dab5ceddbae3627e3d3eb9750358`; any later parser fixes require their
own reviewed source identities. **`--expected-revision` names the original
execution, not the reader checkout.** Preserve the reader revision, working-tree
state and the output's complete `reader_sources` manifest. A Git HEAD alone
does not identify uncommitted reader changes; retain those exact files when
applicable.

The trusted local Python used for replay is separate from the recorded
CPython 3.12.14 execution environment. No Torch installation, GPU build,
restored compiler/toolchain or original producer directory is needed for this
read-only review. Do not install or import an archived wheel, run an archived
checker, extract an archive member, or recreate/open any recorded producer
path. Select existing regular original files using absolute canonical paths
with no symlink in the file or parent path. Their filenames need not match the
intake labels.

## Replay the primary FP16 and BF16 originals

Replace the four absolute paths below. Select a reviewed repository checkout,
the two original ZIP files and a **new output directory outside the checkout
and original archives** whose parent already exists. Run from a shell with the
trusted local `python3` available. `mkdir` deliberately requires a new directory
so an existing review is not overwritten. The fixed digests and revision below
come from independent intake, not from the candidate files.

```bash
(
  set -euo pipefail
  umask 077
  cd "/absolute/path/to/reviewed/AI-GPU"
  P05_FP16_ORIGINAL="/absolute/path/to/p05-torch-fp16-c6fb039e-original.zip"
  P05_BF16_ORIGINAL="/absolute/path/to/p05-torch-bf16-c6fb039e-original.zip"
  P05_REPLAY_OUT="/absolute/path/to/new-p05-replay-review"
  mkdir -- "$P05_REPLAY_OUT"

  git rev-parse HEAD > "$P05_REPLAY_OUT/reader-revision.txt"
  git status --short > "$P05_REPLAY_OUT/reader-state-before.txt"
  python3 --version > "$P05_REPLAY_OUT/reader-python.txt" 2>&1

  PYTHONDONTWRITEBYTECODE=1 python3 -B ci/project/p05_torch_replay.py \
    --archive "$P05_FP16_ORIGINAL" \
    --sha256 d9e9a713ef716882086b6c8176d1d27c4c98acae77110c58f84bdb69a00c4aaa \
    --expected-revision c6fb039e706e812b6b3f4d2a5db1828076fe50df \
    --format fp16 \
    > "$P05_REPLAY_OUT/c6-fp16-replay.json" \
    2> "$P05_REPLAY_OUT/c6-fp16-replay.stderr"

  PYTHONDONTWRITEBYTECODE=1 python3 -B ci/project/p05_torch_replay.py \
    --archive "$P05_BF16_ORIGINAL" \
    --sha256 85498037f9a8b06bbb44357208f236ad325dc686934059bc472348c4524a74b3 \
    --expected-revision c6fb039e706e812b6b3f4d2a5db1828076fe50df \
    --format bf16 \
    > "$P05_REPLAY_OUT/c6-bf16-replay.json" \
    2> "$P05_REPLAY_OUT/c6-bf16-replay.stderr"

  git status --short > "$P05_REPLAY_OUT/reader-state-after.txt"
)
```

After reader initialization and successful argument parsing, each replay
invocation emits JSON on stdout and exits 0 only after all checks, including the
original's final stability/digest check and the reader-input stability check,
succeed. A replay validation rejection exits 1 and emits a failure record;
preserve that JSON and stderr. `--help` prints text and exits 0; argument-usage
errors print diagnostics to stderr and exit 2 without a JSON result. `set -e`
stops this example after a failed command, so the other format and final state
capture may not have run.
Record that distinction and investigate the reported failure without editing
original bytes or relaxing a check. Preserve actual command text, exit status,
outputs and reader identities in the review receipt.

For separate historical corroboration, repeat the procedure into another new
output directory. Use `--expected-revision c0b44ce64665fe11895f869eea8c38c9b820d6f7`
and the original paths and corresponding FP16/BF16 digests from the
[c0 intake](evidence/p05-torch-replay/intake.json).
Keep c0 outputs labelled as c0. Do not combine a c0 format with a c6 format to
claim one complete matrix, and do not substitute a reconstructed ZIP for a pinned
original.

## Interpret the complete result

Both primary format results must pass independently with the same c6 execution
revision. A one-format result does not establish the complete two-format matrix.
The expected fields for each of these originals are:

| Result field | Required/recorded value | Meaning |
|---|---|---|
| `outcome` | `"pass"` with CLI exit 0 | Complete retained-consistency checks returned successfully |
| `execution_revision`, `format` | Independently selected full revision and corresponding format | Identity of recorded execution |
| `archive_read.archive.sha256` | Corresponding independent intake digest | Identity of the original ZIP |
| `archive_read.data_files` and `archive_read.read_files` | 663 data members and 663 per-member receipts | Complete retained-byte coverage |
| `counts.framework_operator_calls` | 16 | Six standalone matmul and ten fixed-model calls recorded |
| `counts.framework_launches` | 36 | Recorded framework-route native launches |
| `counts.native_comparison_launches` | 36 | Separate recorded native comparison launches |
| `counts.plain_python_launches` | 36 | Separate recorded plain-Python launches |
| `counts.distinct_total_launches` | 108 | Sum of the three distinct recorded routes |
| `counts.framework_event_profile_pairs` | 180 | Five recorded event/profile pairs per framework launch |
| `counts.copied_packet_additional_launches` | 0 | Repeated packet bytes are not new execution |
| `native_execution`, `retained_code_executed` | `"not_run"`, `false` | The reader performed no native or retained-code execution |
| `acceptance_claimed`, `phase_acceptance` | `false`, `false` | A passing reader does not decide acceptance |
| `host_fault_semantics_revalidated` | `false` | Supplementary host evidence does not contain full assertion traces |
| `installation.third_party_bytes_rehashed`, `installation.interpreter_bytes_rehashed` | `false`, `false` | Absent third-party/interpreter bytes were not freshly checked |
| `reader_sources` | Complete path/hash/size manifest | Actual trusted inputs used by this replay |

Do not infer new launches from replay duration, archive reads, copied reports or
host scenarios. The c6 pair records 32 framework calls and 216 distinct launches;
replaying it any number of times adds zero native executions.

## Review limits and acceptance handoff

The independently reviewed host evidence contains **45 unique scripted host
definitions and nine compiled scenarios**, repeated in each original. Source,
raw-log, child-result and artifact joins were checked. Some intermediate
captures and failure/ownership channels are absent, so full host semantic
reconstruction remains unavailable and the public false flags stay unchanged.
Scripted/compiled fixture arithmetic does not supply native numerical proof.
Higher-level unqualified transforms, actual fork execution, training, arbitrary
models and CUDA binary compatibility remain outside the tested contract.

First-party bytes, bound wheel/bundle contents and retained raw results have a
different evidential scope from receipt-only source identities and missing
third-party wheels/payloads, interpreter/tool/seed bytes and generated metadata.
Matching a receipt to a selected Git object does not rehash absent producer
files. Replay establishes internal consistency within the trusted-builder
boundary, not arbitrary-producer authentication, reproducible compilation or
fresh qualification of missing bytes.

The [P05-A02 execution](evidence/p05-torch-replay/acceptance-torch.json) and
[P05-A03 compatibility](evidence/p05-torch-replay/acceptance-compatibility.json)
records now make the source-scoped decision under the
[acceptance policy](acceptance.md). The packet's
[validation summary](evidence/p05-torch-replay/validation-summary.json) and
[review ledger](evidence/p05-torch-replay/reviews/ledger.json) retain
exact identities, outcomes and independent dispositions. Use those identities
to select the final reviewed reader; the earlier d8 checkpoint precedes the
documented parser repairs. The [canonical roadmap](roadmap.json) remains
authoritative. The [original-retention receipt](evidence/p05-torch-replay/original-retention.json)
records durable owner access outside Git; public replay still requires obtaining
the unchanged ZIPs, and their availability is not implied by a digest. A successful Installed
PyTorch run does not imply that pending or cancelled general CI/governance ran
successfully. No P01-A03 or P06-A02/A03 decision follows, and the separate P06
experiment retains its 15 GiB resource guard. This is SimX evidence, without a
processor RTL, vendor `hw_emu`, physical FPGA, silicon or physical-performance
claim.
