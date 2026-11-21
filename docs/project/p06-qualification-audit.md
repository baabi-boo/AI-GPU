# P06 baseline qualification and analysis audit

## Selected development step

This continuation starts from `84b6ca0ca75fba248ba330642bbf8764db3d459c` on
`baabi-boo/AI-GPU`'s `master` branch. The six latest workflows at that source
passed, including the two-format P06 Native Baseline run `44901052221`, attempt
1. The previous implementation had frozen and executed the experiment, but
P06-A01 still lacked independent original-artifact review and a complete analysis.

The next bounded step is to qualify that baseline, repair concrete validation
defects, and provide a reusable full-matrix analyzer. P04 supplies the entry
dependency; the independent P05 framework track does not block P06. No native
kernel, runtime, simulator or RTL optimization is included in this step.

The original FP16 and BF16 ZIP files are retained without modification in the
[qualification packet](evidence/p06-baseline/README.md). The original failed
governance attempt at `fd7129a` remains documented in the
[preceding development audit](p06-benchmark-audit.md); its successful native run
is not reassigned to the corrected source.

## Findings and disposition

| Finding | Evidence and action |
|---|---|
| Hosted success was not yet independently qualified | Replay both externally digest-pinned originals and reconcile their source, compiler, numerical, cleanup and counter records. Keep execution at its original source identity. |
| Individual timing bounds admitted impossible serial totals | Two synthetic probes passed the original reader: 7.1 seconds of serial lifecycle work within a 4-second process, and 9,000 ns of serial waits within a 3,500 ns advance. Add aggregate containment checks while preserving all existing checks. |
| The complete two-format experiment had no reusable analysis command | Add `ci/project/p06_analyze.py` to replay both originals, reject incompatible packets, and derive full-matrix summaries and diagnostics from checked individual samples. |
| Process supervision affects host duration | A synthetic subprocess reproduced an approximately 100 ms EOF/exit-observation delay in `baseline_process.py`. Preserve every original duration; explicitly exclude fine-grained host speedup interpretations. |
| Retained dependency paths are not all submodule source | Independently match Ramulator's separate spdlog and yaml-cpp FetchContent headers to their resolved Git commits rather than attributing them to Ramulator's gitlink. |
| Native overlapping operations need separate qualification | `ManagedMatmul::submit` can create multiple queues while launch setup is not serialized across queues. The frozen model serializes and closes each operation. Any future reuse or concurrency experiment must resolve this scope gap first. |

## What the original measurements establish

The frozen suite contains eight workloads: three matrix shapes and the fixed
batch-16 model in FP16 and BF16. Each workload retains one warm-up and five
measured fresh-process invocations. Independent raw-record reconciliation finds
48 processes, 72 native launches, 4,608 exact native output-word comparisons,
768 bridge-word comparisons and 768 final assembled-output comparisons. Of the
total, 40 processes and 60 launches are measured.

All 45 counter rows are identical across the six invocations of each workload:
33 are available and 12 remain explicitly unavailable. Both formats have the
same modeled counts for each corresponding workload:

| Workload | Useful FLOPs per invocation | Active core cycles | Retired macroinstructions |
|---|---:|---:|---:|
| Matmul `(8,4,8)` | 512 | 5,952 | 509 |
| Matmul `(8,4,16)` | 1,024 | 6,339 | 559 |
| Matmul `(16,8,16)` | 4,096 | 6,405 | 2,208 |
| Batch-16 `16 -> 8 -> 4` model | 5,120 | 18,189 | 3,226 |

These are whole-context SimX timing-model counts. They are not per-kernel
latencies or physical FPGA measurements. The model count includes three
launches. One multiply and one add count as two FLOPs. The largest matrix has
eight times the useful arithmetic of the smallest with about 7.6% more active
cycles. This supports investigating amortization of small workloads; it does
not identify a single causal bottleneck or establish a successful optimization.

The process supervisor can add an observation delay after output EOF. In a
controlled host-only reproduction, a child with a 5 ms tail took approximately
114-116 ms with the default monitoring interval, versus approximately 20-26 ms
under a shorter interval or direct execution. Original packets do not retain an
exact process-exit timestamp, so the original durations cannot be corrected by
subtracting a guessed 100 ms. Native modeled counters are retained separately.

## Source and numerical review boundaries

Each packet retains 979 source bodies: 786 main-repository files, 50 Ramulator
files, seven SoftFloat headers, 99 spdlog headers and 37 yaml-cpp headers.
Independent review matched all bodies to Git content and all five top-level
submodule identities to the source revision. Three unrelated nested CVFPU
gitlinks were not fetched; no retained body falls under them. FetchContent tags
were resolved during review, so historical tag immutability is not asserted.

The timing correction passes all twelve original model samples without changing
their measurements or summaries. Successful model creation, accumulated
advances and accumulated closes are disjoint. Successful native stage submit,
wait, comparison and close scopes, and the host bridge/assembly scopes, are also
serial inside advance. Native event profiles overlap host waits and are never
added to those aggregates. The existing 1,000 ns process-receipt rounding
allowance is unchanged.

The analyzer validates retained data using trusted local code. It does not
execute archived binaries or scripts, authenticate GitHub origin by itself,
grant acceptance automatically, or provide a new GPU execution. Independent
GitHub observations and source-to-Git checks remain separate evidence.

## Next bounded experiment and remaining gates

Use the accepted cold baseline to freeze one small-workload amortization
experiment before changing native code. Specify the candidate workload/layout,
ownership rule, reference and candidate revisions, identical numerical inputs,
all repetitions, and rejection conditions. A resident-workspace experiment must
retain this cold baseline and define a separate warm-context boundary. Resolve
the native multiple-live-operation scope before relying on concurrent queues.

P06-A02 still requires matched before/after correctness, native RTL and
applicable parity/performance evidence. P06-A03 still requires a reviewed target
budget and synthesis/resource/timing reports. P06 remains `in_progress`.
The inherited 267 -> 283 DSP area finding and P01-A03 vendor XRT `hw_emu`
blocker remain unresolved. Physical FPGA speed, power, energy and silicon remain
unmeasured. No gate, numerical tolerance, golden data, toolchain pin or resource
budget is relaxed by this continuation.
