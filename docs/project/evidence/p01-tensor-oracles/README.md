# P01 supplemental tensor-oracle evidence

**The nine-variant matrix passed all 62 monitored commands at local source
`ca8686d668ed9f2ff733ce7e3c12dd458b9776d8`. All 1,272 tooling tests passed at
that same clean source, with zero failures, errors or skips, in 336.269 seconds.**
These are supplemental unit and host results. P01-A03 remains blocked on
qualified vendor XRT `hw_emu`, and P02–P11 remain `not_started`.

Use the [reproduction guide](../../p01-tensor-oracles.md) for setup, exact
configuration selections, comparison policies, resource limits and commands.
The existing accepted P01-A01/A02 reports and all phase gates are unchanged.

## Evidence files

- [Compressed packet](packet.tar.gz) and [member/hash index](index.json): commands,
  logs, failed attempts, source objects, scripts and scoped agent reports.
- [Native matrix](native-matrix.json), [numeric summary](numeric-summary.json),
  [full tooling suite](tooling-suite.json) and [host follow-up](host-followup.json):
  convenience copies of the corresponding published archive members.
- [Source map](source-map.json), [agent ledger](agents.md) and
  [machine-readable ledger](agents.json): provenance and actual work assignments.

The index identifies both raw and published bytes; see the integrity explanation
below before comparing report hashes with transformed log files.

## Observed coverage

| Execution scope | Fresh builds | Executed harness cases |
| --- | ---: | --- |
| Native TFR WMMA | 3 | 7,001 random, 140 independent exact fixture executions, 6 inherited modeled directed executions |
| Native TFR FEDP | 3 | 1,700,001 floating-point and modular integer cases |
| DPI WMMA compatibility | 1 | 3,000 random and 40 independent exact fixture executions |
| DPI FEDP compatibility | 2 | 9,000 floating-point and modular integer cases |
| Actual-binary CLI checks | — | 58 + 37 = 95 checks; generic FEDP checks repeat in the disabled-format profile |

The total is **1,719,188 harness case executions**, of which **1,707,148 use
native TFR** and **12,040 execute DPI backends**. The total includes **404,001
integer cases**. It counts vector/case executions, not individual output lanes,
distinct input vectors or independent mathematical proofs. All 38 numerical
invocations requested zero ULP; integer cases use exact modulo-2^32 equality.
The floating-point comparator accepts both NaNs regardless of payload/sign and
treats signed zeros as equal. Both harness defaults remain one ULP, while exact
fixtures always use zero ULP.

The native floating FEDP matrix covers TF32, FP16, BF16, FP8/BF8, MXFP8/MXBF8,
MXFP4 and NVFP4; integer runs cover signed/unsigned 8- and 4-bit inputs. WMMA
covers four and eight threads. DPI floating FEDP is deliberately N=1 because the
inherited N>1 RTL grouping and serial discrete reference associate sums
differently. No N>1 DPI floating result, native 64-lane result, INT32 hardware,
full AFU, vendor platform, physical FPGA or silicon qualification is claimed.
DPI floating-point paths call C arithmetic; the selected DPI integer paths use
behavioral RTL integer products and accumulation. The packet's `dpi_c_arithmetic`
field labels the backend family, not every integer operation.

Random native TFR floating-point checks share the windowed `TfrFedp` model. The separately
counted FP16/BF16 exact fixtures have independent expected values. Host C++ and
Python rational decoders check 6,988 output lanes over seven shapes; this is
host fixture coverage, not a native execution of every shape.

## Source identities and review

The [source map](source-map.json) connects original local commit objects to
GitHub objects with exactly identical trees. Commit metadata and parent identities
can differ; the results belong to the local revisions actually tested.

| Role | Original local commit | Corresponding GitHub object |
| --- | --- | --- |
| Initial implementation | `f4169a74edb17c28364c2c6e7fb92a928c468f77` | [364218f4](https://github.com/baabi-boo/AI-GPU/commit/364218f44093b394aca28c0cf737c72d6e3f2de2) |
| Format guards; first frozen matrix | `20ea50d98d41684451c99df3b6f4eb43396f0c17` | [ee8d154b](https://github.com/baabi-boo/AI-GPU/commit/ee8d154b41f7c9ab7f1822edc6faddc20f41aba1) |
| Successful matrix and full suite | `ca8686d668ed9f2ff733ce7e3c12dd458b9776d8` | [9058c156](https://github.com/baabi-boo/AI-GPU/commit/9058c156c0b4c984455bbb25888304bfe4397ad2) |
| Host diagnostic follow-up | `a25ee6663e37d5fe28e7a6fd40b3857083ddeecc` | [c592d98e](https://github.com/baabi-boo/AI-GPU/commit/c592d98e052b62f99d62690f1031fbb5e43c8213) |

At `a25ee666`, the only code change after the matrix is replacement decoding of
malformed UTF-8 in the bounded host-test helper. It preserves the original
nonzero exit diagnostic instead of masking it with a decode exception. All 12
tensor host groups and an actual malformed-output negative control pass there;
all 16 recorded native source/configuration files remain unchanged. The full
1,272-test suite and nine-build matrix retain their `ca8686d` attribution.

The change is **R2**, because the unit Makefiles change. All nine configurations
were freshly generated. Independent reviews cover every changed code hunk,
backend/feature matrices, generated C++/RTL bindings, output counters, exact
fixture independence, modular arithmetic, replay and bounded failure handling.
The user's instruction authorizes delivery to `master`; agent reviews are scoped
engineering evidence, not invented human approvals or phase waivers.

The [agent ledger](agents.md) and [machine-readable ledger](agents.json) record
**60 completed, distinct agent assignments across ten logical waves**, with
no unspawned or unfinished slots. Six assignments form each logical wave, with
at most three subagents running concurrently under the environment's limit.

## Retained failures and corrections

- Initial automatic OS selection rejected Debian. The explicit `ubuntu/focal`
  selection identifies the pinned tool bundle; the actual host remained Debian
  13.6 with GCC/G++ 14.2 and Verilator 5.050.
- The first frozen matrix at `20ea50d` stopped at command 15: the TF32-enabled
  eight-thread WMMA build failed GCC's array-bounds warning in a format-name
  diagnostic. Its 14 preceding passes are preserved. Later variants and CLI
  checks were not reached. The correction replaces the indexed diagnostic with
  a switch, preserving warnings and behavior. The identical matrix then passed
  from fresh build trees at `ca8686d`.
- The full suite passed at `20ea50d` in 335.863 seconds and was rerun at
  `ca8686d` in 336.269 seconds. Neither result is relabelled as a later revision.
- Independent negative controls retain the unsafe original FP32 comparisons,
  integer overflow, selection/replay errors, disabled-format sparse-zero false
  passes and malformed-output diagnostic failure. Some are extracted host or
  preliminary-binary probes; their reports state their exact scope. The A22/A27
  integer checks retain summary receipts rather than complete standalone
  mutation/vector generators or command transcripts, so they supply receipt-level
  evidence alongside the committed, reproducible integer host tests.

## Resources, integrity and delivery

Only the pinned Verilator component and pinned SoftFloat submodule were
provisioned. Native builds used two workers, a 15 GiB free-disk reserve, a 6 GiB
sampled process-group RSS budget and a 16 MiB per-command log limit. Highest
sampled matrix RSS was **1,322,639,360 bytes (about 1.23 GiB)**. Free disk at
completion was **45,010,890,752 bytes (about 41.9 GiB)**. These are sampled
observations, not hard quotas or performance measurements.

The sealed packet has **243 members**, **334,429 compressed bytes**, and SHA-256
`482a4093bc8606cf587a662aebaaa3f26d4c313b12225dc9c7c56e3bd403524d`.
An [independent final verification](seal-verification.json) checks every published
member and its current raw source, all 99 raw log bindings, four original Git
commit objects, and the retained replay proof files. Its results are a separate
post-seal record so the archive has no self-hash dependency.

The packet index records both raw captured hashes and hashes of published
members. Workspace prefixes are replaced in published text; original report
log hashes continue to identify the raw logs. Verify published bytes against
the index, not against raw-log hashes. The transformation and original-to-
published mapping are retained without claiming independent authentication of
raw bytes after redaction. Original Git commit objects retain their exact bytes.
Native binaries, generated object trees and tool archives are excluded.

New verification helpers and records in this continuation follow the repository's
[Apache-2.0 license](../../../../LICENSE). The archive includes that license;
inherited Vortex source snapshots retain their original copyright/license
notices. Frozen helper/probe records keep their original bytes rather than being
retroactively rewritten to add headers. No vendor tool binaries are distributed.

The source map's prepared-object status is a sealing-time snapshot, not proof
that a branch moved. Check the containing commit on
[master](https://github.com/baabi-boo/AI-GPU/tree/master) and its
[Actions runs](https://github.com/baabi-boo/AI-GPU/actions) for delivery and
revision-specific hosted CI. A check of an earlier head does not certify a later
one. Historical gate reports are not changed by this supplemental packet.
