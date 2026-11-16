# P02 staged-entry handoff — native numerical development

P02-T01 is now complete; its [source-level P02-A01 record](evidence/p02-numerics/acceptance.json)
and actual checks are described in the [P02 numerical handoff](p02-numerics-handoff.md).
This document preserves the staged-entry decision and the work it originally
unlocked. P02-T02 whole-processor and WGMMA proof is the next work; consult
the current [status](status.md) for accepted scope and remaining gates.

**Decision:** [ADR-004](decisions.md#adr-004--staged-native-development-entry-with-vendor-integration-retained),
2026-11-16. This handoff records the entry decision for the unblocked workstream.
The canonical state and exact acceptance contract remain in
[roadmap.json](roadmap.json). The earlier P01 handoffs are historical execution
packets, not current sequencing instructions.

## Entry readiness

| Prerequisite | Evidence / state | Decision |
|---|---|---|
| P00 complete | [Setup acceptance](evidence/setup-accepted.json) | Complete |
| P01-A01 clean baseline | [Reviewed passing build](evidence/p01-build.json) | Accepted |
| P01-A02 native arithmetic | [Reviewed passing six-case matrix](evidence/p01-native.json) | Accepted |
| P01-A03 vendor `hw_emu` | [Preserved blocked record](evidence/p01-xrt-blocked.json) | **Blocked; not required for P02 entry** |

The `entry_acceptances` field on P02 requires the validator to resolve both
P01-A01 and A02 as valid passing evidence before any in-progress or completed
P02 status can be accepted. P02 additionally depends on P00 completion. P07
depends on P01/P04/P06 completion: **the vendor integration test has not been
removed, accepted, substituted or silently waived**. It must pass before P07
can close; physical FPGA measurements have their own separate acceptance.

## What work is now authorized by the roadmap

- P02 can specify and test native tensor arithmetic through SimX and processor
  RTL using pinned configurations and existing accepted P01 references.
- P03–P06 can follow their original completion dependencies as their preceding
  phases acquire genuine passing evidence. Their current states remain
  `not_started`; do not pre-mark gates or imply inherited coverage is sufficient.
- P01-T05 vendor qualification can continue independently with the existing
  XRT `hw_emu` preparation and execution tooling. P07 can be researched, but
  cannot close until P01 is complete and P07's own physical results pass.
- No paid cloud, tool download, physical board, license acquisition or broad
  synthesis job is authorized by a phase dependency change.

## Original first bounded deliverable: P02-T01

The following contract work is now implemented and reviewed. Its source-level
acceptance does not close P02-A02/A03; their remaining execution work is in the
[numerical handoff](p02-numerics-handoff.md#next-bounded-action).

1. Freeze exactly one first native FP16/BF16-input, FP32-accumulation tensor
   configuration, including XLEN, backend (`TFR`, not DPI), tile geometry,
   warp geometry and the compiled application/backend configuration identifiers.
   Read [P01 baseline](p01-baseline-runbook.md) and the
   [native matrix](../../ci/project/p01_baseline.json) first.
2. Write a versioned, reviewed numerical specification describing each
   supported mode's accumulation order, rounding, signed zero, NaNs/Infs,
   subnormals, overflow, underflow, exceptions, supported layouts and explicit
   unsupported-format response. **Investigate unknown behavior; do not invent
   an IEEE or vendor-parity guarantee.**
3. Attach independently derived deterministic fixtures, including signed-zero,
   tie, extreme, subnormal, cancellation and tile/layout edge cases. Review the
   existing [tensor oracle hardening](p01-tensor-oracles.md) before reusing it.
   Name every fixture's producer, expected output, version and hash.
4. Freeze existing accepted reference tolerances before evaluating P02-A02.
   Require separate SimX/native RTL results and native arithmetic binding;
   keep DPI and software shims separately labeled. Ensure any new format is
   explicitly unsupported until individually qualified.
5. Independently review the P02-A01 specification and fixture manifest, run
   focused contract tests with recorded commands/results and only then add a
   source-level P02-A01 passing report if the acceptance contract is met.

**Next handoff after P02-T01:** P02-T02 extends normal, edge, cancellation,
layout and unsupported-format execution checks; P02-A02 is not automatically
accepted by the older six-case P01 matrix. The same P02-T02 work package
addresses WGMMA synchronization, metadata, multi-warp and backpressure under
P02-A03.

## Verification and honesty boundaries

From the repo root, without a GPU toolchain:

```sh
python3 ci/project/check_project.py
python3 -m unittest discover -s ci/project -p 'test_check_project.py'
python3 -m unittest discover -s ci/project -p 'test_repository_contract.py'
```

These checks validate the **metadata and staged-entry enforcement**, not GPU
execution. Preserve prior evidence reports and blocked XRT prerequisite records;
do not rewrite their tested revisions or acceptance IDs. Current retained P01
native results describe their own historical execution revision and cannot be
relabelled as a P02 test. Record full commands, limits, artifact hashes and
actual independent review for every future execution packet.

## Decision-change verification (2026-11-16)

The decision change was developed on `master` from the previously published
`fd803750198eb9f6ec11071abfdad211d8858100` base. Observed local results:

| Check | Actual result | Scope |
|---|---|---|
| `python3 ci/project/check_project.py` | Pass | Project structure, evidence metadata and stage dependencies |
| `python3 -m unittest discover -s ci/project -p 'test_check_project.py' -q` | 55 passed | Positive and negative tests for blocked/missing evidence, cycles and P07 dependencies |
| `python3 -m unittest discover -s ci/project -p 'test_repository_contract.py' -q` | 18 passed | Requirement/phase traceability and 36 unchanged criteria |
| `python3 -m unittest discover -s ci/project -p 'test_*.py' -q` | 1,276 passed in 291.057 s | Full offline project-tooling suite, not GPU execution |
| `git diff --check` | Pass | No whitespace errors in the staged change |

An independent advisory agent reviewed the changed governance contract,
negative tests, documentation and preservation of P01-A03. It identified two
documentation inconsistencies; both were corrected before final validation.
Final review disposition: **no remaining findings**. This is not a claim of
human maintainer acceptance or of any completed P02/GPU/vendor execution.

No new build/download, expensive synthesis, vendor tool invocation or hardware
emulation was performed for this roadmap change. The earlier native execution
packets remain scoped to their original source revisions and workloads.
