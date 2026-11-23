# Native counter lifetime development audit

## Starting point and selected work

The audit starts at `6130a2f7424932a6f3b7377ef8ae4816da2b304f` on
`baabi-boo/AI-GPU` `master`. The current project handoff and source agree on
the next bounded development step: observe the real pending-read balance and
every reset-bearing managed run, then reconcile those observations through
terminal counter readout and actual processor destruction.

The existing four-process managed preflight demonstrates 132 launches and
4,224 checked result words in its historical native execution. Its four outer
snapshots do not establish the balance immediately before all intervening
resets. `ProcessorImpl::reset()` clears that balance, so a later zero cannot
prove the missing premise. The current v1 reader also permits bounded,
nondecreasing intermediate reset generations; an audit control collapsed the
31 intermediate generations while preserving the endpoints and remained
valid under v1. These are limits of that contract, not new failures of its
declared scope.

## Implementation boundaries

- Add a const value accessor through the owned `Processor` and
  `ProcessorImpl`; do not change simulated cycles, counter updates, resets,
  arithmetic or production completion behavior.
- Add an explicit opt-in, separately versioned lifetime record after the
  unchanged v1 transcript. The new reader validates the original prefix
  before applying the additional lifetime requirements. Historical v1
  archives retain their original version and result.
- Record all 33 real run boundary pairs, all 33 flushes, all 264 raw MPM
  half-read boundaries, four snapshots, construction and destruction.
- Check the pending balance before a real run can reset it. Require one
  reset per admitted run and coherent ordering within each reset generation.
- Preserve the void `run_checked()` contract. Legacy x3/`gp`, including `-1`,
  is an observed register value; exceptions and unsuccessful public
  completion/API results are separate failure evidence.
- Keep test-only fault mutation out of the measurement binary. Use separate
  compiled controls and a real-model accessor probe.

## Scope and resources

The existing 14 workflows returned for the starting `master` commit were
observed completed successfully during this audit. That observation does not
erase the separately retained historical RV64 area finding or qualify P06.

Local storage and available memory do not meet the native preflight's fixed
15 GiB disk reserve and 4 GiB memory requirement. Native execution therefore
uses the repository's hosted workflow route, with two build jobs and one
simulation worker. Local checks are bounded host/source tests.

This work does not establish fresh dependency compilation provenance, complete
counter qualification, a warm speedup, P05 framework acceptance, vendor XRT
hardware emulation or physical hardware results. The seven preflight
qualification/readiness/acceptance fields remain false. P06 and P06-T01 stay
`in_progress`; P06-A02/A03 remain open.

## Independent work and evidence

Ten waves of six distinct agent assignments are planned. Only completed work
will be counted in the final ledger. Review notes and exact validation results
will accompany the implementation; this initial audit makes no claim of new
native execution or completed implementation.
