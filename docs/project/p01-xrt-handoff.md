# P01 vendor XRT integration handoff

## Scope and starting point

This continuation implements the next incomplete P01-T05 execution path from
`91b82fe300f94ab0a70dd0e0e4a69a0e23b16101`. The current user instruction authorizes
implementation, testing, commit and push to `baabi-boo/AI-GPU` on `master`, with
60 distinct agent assignments across ten logical waves.

P01-A01/A02 remain accepted. P01-A03 remains blocked on an unavailable qualified
vendor environment/platform. P01 is incomplete and P02 has not started.
This handoff will be finalized with exact candidate identity, verification,
independent review and publication observations before delivery.

## Implemented path

Read the [integration guide](p01-xrt-integration.md). The new source provides
strict manifest and build-receipt validation, read-only prerequisite inventory,
fresh generated host/kernel builds, explicit vendor `hw_emu` execution and
bounded command/checkpoint retention. The inherited XRT pre-simulation Tcl path
is corrected and covered through actual out-of-tree configuration generation.
No vendor installation, FPGA-image synthesis or hardware qualification was
performed during this tooling implementation.

## Current verification

The original suite passed 591 tests before changes. New independent tests cover
manifest binding, safe reads, effective configuration, runner state transitions,
resource/environment boundaries and actual generated-build inspection. Final
counts and exact candidate revision remain to be recorded.

The live prerequisite probe reports absent `v++`, `vivado`, `emconfigutil`,
`platforminfo` and `xsim`, with the three vendor roots unset. No vendor command
was launched. Fixture tests use inert local files and do not qualify an
accelerator or satisfy P01-A03.

## Next bounded action

Prepare one compatible, independently reviewed vendor release/platform and a
matching `hw_emu` image/configuration/build receipt. Fill the manifest with
observed identities, run `plan`, then execute and independently review the
bounded smoke through the [guide](p01-xrt-integration.md). Keep P01-A03 blocked
until that real execution and review exist.
