# Qualified warm-workspace evidence

This packet records the explicitly selected route for the frozen 24-process
FP16/BF16 warm-workspace experiment. At the implementation checkpoint, the
route is implemented and independently reviewed, and all 89 focused tooling
tests pass. Fresh native execution, complete original replay and full governance
remain pending. This checkpoint makes no warm performance or phase claim.

## Contract and source boundaries

- [Development audit](../../p06-qualified-warm-audit.md)
- [Implemented route](../../../designs/qualified_warm_workspace_v1.md)
- [Frozen warm sampling and predicates](../../../designs/warm_workspace_benchmark_v1.md)
- [Preceding four-process original](../p06-counter-qualification/README.md)

The new proof's SHA-256 is
`172721c671ddaa79541dde9c37c154b5ab5a99b8abb0caabf2e07036dd429efb`.
Its projection changes only the explicit native caller among 69 measurement
sources. The original qualification proof remains
`d12718e9b182a3c93eab346901b380031516d556dd823017a63831d4a0304b4e`.
Historical original/prerequisite packets and the seven historical false fields
are preserved. No packet field selects the new trusted route implicitly.

## Current review and validation

The independent reports in `agents/` state actual work and limits. Wave three
covers the native extension (`w03_a01`), proof/admission (`w03_a02`), producer
(`w03_a03`), complete reader (`w03_a04`), unchanged statistics (`w03_a05`) and
actual historical archive compatibility (`w03_a06`). Wave four adds separately
recorded adversarial probes. Sixty actual assignments across ten waves are
planned; the final ledger will count completed assignments only.

The [focused execution receipt](validation/qualified-warm-focused.json) and
[complete log](validation/qualified-warm-focused.log) record 89 passing tests in
195.293 seconds on the documented dirty implementation tree. Current-source
identities are in the receipt. The [historical compatibility review](agents/w03_a06.md)
records a real public replay of the unchanged earlier ZIP and 29 passing
historical analyzer tests. Supplementary synthetic probes are not added to the
unique unittest count. The initial concurrent-edit historical test failure is
retained as `validation/historical-qualification-initial.log`.

## Required next evidence

One fresh attempt must retain all 24 processes, 792 launches and 25,344 exact
FP32 output words. Both formats must independently satisfy the unchanged 95%
median host-time rule and every measured pair's host-time and modeled-cycle
constraints. A valid complete experiment may reject that performance hypothesis.
No sample may be omitted or replaced to obtain a favorable result. P06-A02/A03,
the vendor integration gate and physical-device evidence remain separate.
