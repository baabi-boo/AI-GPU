# Managed tiny-model execution records v1

This contract defines the P04 executor's native application records. Successful
records are execution observations only when a trusted runner binds their source,
fixture, compiler configuration and actual module/backend/application binaries.
A hand-written record or host mock cannot establish native execution.

## Application interface and record framing

`tests/regression/ai_mlp/ai_mlp` accepts `--case ID`, `--iterations 1|2`,
`--module PATH`, `--qualification-id SHA256`, `--backend simx|rtlsim` and
`--source-revision COMMIT`. The selected fixture format must match the compiled
native input format. The fixture digest comes from the validated generated
header, not an unchecked command-line value. Unknown, missing, duplicate and
malformed arguments fail before a launch.

Each successful model repetition emits one line beginning `P04_RESULT ` followed
by a JSON object. Only a fully successful process prints one final `PASSED!`.
Failures preserve diagnostic output and exit nonzero; no successful completion
marker follows a numerical, runtime, cleanup or profiling failure. Iteration
zero uses poison `7fc0dead`; iteration one uses `deadbeef` for all three outputs.

Top-level fields are exactly `schema_version` (1), `model_id`, `fixture_id`,
`fixture_sha256`, `source_revision`, `backend`, `iteration`, `qualification_id`,
`clock` (`std::chrono::steady_clock`), `timing_scope`
(`host_runtime_observations`) and `trace`. The identity values must agree with
the trusted invocation and the frozen fixture. Iterations are ordered from zero.

## Trace serialization

The trace mirrors every public field of `MlpTrace` in
[`mlp_runtime.h`](../../sw/runtime/ai/mlp_runtime.h). Its `native` array contains
exactly three `MlpNativeStage` records in graph order. Each native stage embeds
all public `MatmulTrace` fields as `dispatch`. Struct member names are JSON keys.
No host pointer address or unused fixed-array suffix is serialized.

| C++ value | JSON representation |
|---|---|
| `DType` | `fp16` or `bf16` string |
| `MlpStatus` | `mlp_status_string` string |
| `BridgeStatus`, `Status`, `vx_result_t` | Integer enum/result value |
| `ExecutionResult` | Object with `validation`, `primary`, `cleanup`, `complete` |
| `MlpResult` | Object with `status`, `execution`, `terminal` |
| Fixed word arrays | Arrays of eight-digit lowercase hexadecimal strings |
| Stage `a_bytes` / `b_bytes` | Lowercase byte-hex strings, exactly `a_size` / `b_size` bytes |
| Stage `output_words` | Exactly `output_count` word strings |
| `bridge_bytes` | Exactly 256 bytes as lowercase byte-hex |
| `argument_bytes` | Exactly 56 bytes as lowercase byte-hex |
| Event/profile result arrays | Exactly five integers or booleans, as appropriate |
| `event_profiles` | Five objects with `queued_ns`, `submit_ns`, `start_ns`, `end_ns` |
| Other counters and timestamps | Nonnegative integers; JSON booleans are not integers |

The successful trace has actual, observed and compared intermediate/output
flags, closed operation and owner flags, successful separate execution and
cleanup results, and valid equal before/after memory counters. It retains actual
H, bridge and Y values even though the verifier independently compares them.
The first native record covers rows [0,16); the output records cover [0,8) and
[8,16). Their sequences are 0, 1 and 2, with the three fixed operation IDs.

## Independent consumer obligations

The consumer rejects missing or unknown fields, duplicate JSON keys, nonfinite
numbers, coercible types, reordered/missing/extra records, failure text and
ambiguous success markers. Logs and records are bounded before parsing.

For every successful repetition it independently checks:

1. Exact actual hidden, bridge, output-block and assembled output words against
   the unchanged fixture. Checked counts are 128, 64, 32+32 and 64 respectively,
   with zero mismatches. The hidden comparison occurs before bridge work.
2. Recorded hidden A/B bytes equal X/W1; output A bytes equal the corresponding
   actual bridge slice; both output B buffers equal W2. Assembled words equal
   the two actual output blocks in their declared order.
3. Three actual launches, nine writes and three reads; per-stage tensor sizes,
   poison, format, shape and qualification binding match. The 56-byte wire
   arguments are independently reconstructed from shape, dtype and nonoverlapping,
   aligned, representable actual allocation addresses.
4. Every created event completed successfully and supplied an observed successful
   profiling query. Timestamp order is queued ≤ submit ≤ start ≤ end. Equal
   timestamps and zero-duration intervals are allowed; absent observations are
   not synthesized from default zeros.
5. Submission, completion, operation cleanup, model completion and owner cleanup
   are distinct observations. An incomplete result, cleanup error or unrestored
   resource baseline cannot pass.

## Timing and transfer accounting

All timestamps and elapsed durations use host `steady_clock` nanoseconds. Queue
wait is submit minus queued, preparation is start minus submit, and command
service is end minus start. Launch start follows argument staging and KMU/DCR
programming. Transfer start precedes the enqueue mutex, so its service interval
includes mutex wait. These are host runtime observations, not physical DMA,
device cycles, accelerator-only latency, throughput or speedup.

Host create, submission, waiting, comparisons, ReLU/conversion, assembly and
cleanup are separately recorded. Host wait intervals overlap event profiles and
must not be added to those profiles. The three submissions carry 1,920 explicit
tensor-buffer H2D bytes (including poisons) and 768 D2H bytes per model run.
Argument/control, module/setup traffic and physical transaction counts are
excluded. The two output-block copies perform 256 bytes of explicit host assembly.

The complete planned matrix is four backend/format variants, five cases each,
two repetitions: 20 case/backend pairs, 40 model runs and 120 launches. Partial
variant packets identify their narrower inventory and cannot imply full-matrix
completion. Independent review and separate acceptance remain necessary.
