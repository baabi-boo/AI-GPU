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

The requested program completed **60 distinct agent assignments across ten
logical waves, six assignments in every wave**. The
[final ledger](agent-execution.json) records all 60 completed reports and their
byte hashes, totaling 532,326 report bytes. The
[final ledger review](reviews/w10_a06.md) verified all 59 other completed reports
and delivered the completing 60th report; root then verified its hash and
finalized the ledger. Root integration, follow-up messages, repeated tests and
tool calls are not extra agents.

The initial six reviews independently examined the processor, managed witness,
strict reader, build/test route, CI/provenance boundary and choice of development
priority. Implementation and adversarial-test assignments followed. Later waves
reviewed the real original native processes, source and build identities,
ownership, version compatibility, qualification boundaries and publication
evidence. These reviews are separately scoped; an inert archive review does not
claim another native execution.

## Implemented result and repaired findings

The implementation is published at
[`b4127b19a004b5aebb8d52eab9ceda0da3ff4561`](https://github.com/baabi-boo/AI-GPU/commit/b4127b19a004b5aebb8d52eab9ceda0da3ff4561).
The [versioned contract](../../../designs/managed_counter_lifetime_v1.md)
and [evidence packet](README.md) describe the exact format and observations.
The default v1 route is unchanged. Lifetime mode is explicitly selected and
retains the complete original transcript before its separately identified
sidecar; the new reader validates that original prefix first.

The compiled sensitivity control gives a direct reason for the change. Both
parent and candidate hook variants compile. With a pending read at the next
run boundary, the parent enters the reset-bearing call and fails the exact
control assertion. The candidate rejects the boundary before that call and
passes. [The final-source receipt](host-controls/w04_a03-parent-control/report.json)
retains both outcomes. The native accessor probe separately demonstrates that
the getter observes an actual nonzero balance; its isolated always-zero control
compiles but fails the required missing-observation assertion.

Independent review found and repaired two issues before implementation
publication. The probe's bounded JSON wrapper could admit trailing extra
wrapper fields and then discard them when extracting its value. Exact wrapper
field validation and object/list suffix rejection tests now close that path.
The C++ fixture/getter formatting was also brought into the repository's
required brace style. The [probe review](reviews/w03_a06.md) and
[fixture review](reviews/w04_a03.md) retain the original findings and repairs.
Earlier failed development test attempts are retained in
[development history](development-history/manifest.json), separately from the
final successful test and native originals.

## Verification and its limits

The original hosted lifetime run is
[45130300651, attempt 1](https://github.com/baabi-boo/AI-GPU/actions/runs/45130300651),
at the implementation revision. Four FP16/BF16 by allocation-policy processes
complete 132 launches and 4,224 exact FP32 result words with zero mismatches.
Independent readers reconcile all 132 run/reset pairs and 2,680 zero-pending
observations, including terminal readout and actual destructor entry. The
separate probe's two architectural `gp` contexts each observe 23 positive
pending samples. Probe operations are excluded from the managed counts.

The exact 9,086,055-byte original ZIP, GitHub artifact metadata, original job
log and all-member inventory are [retained together](README.md#build-identity-and-retention).
The archive has 1,264 members. Reviews validate both format-specific backend
graphs and both complete application graphs using trusted current validators,
without executing retained programs. All 813 captured root-project source
inputs match the implementation's Git bytes and modes. The 193 captured
dependency headers correspond to the original captured hashes; that statement
does not establish their upstream origin or fresh compilation provenance.

The focused host population contains 120 distinct methods: 80 new and 40
existing. The 11-method formatted-fixture rerun and its 38 fresh controlled
processes repeat a subset of those methods. Full hosted governance
[45130300117](https://github.com/baabi-boo/AI-GPU/actions/runs/45130300117)
passes **3,813 tests in 2,498.078 seconds** at `b4127b19`; the
[original log](ci/b4127b19-full-governance-original.log) retains the complete
result. The current default native route also passes four processes / 132
launches / 4,224 words, and the historical replay workflow passes 203 tests
while preserving the failed original's exact rejection. These populations
overlap and are not added together as unique test methods or native launches.

Documentation and evidence added after the implementation are checked as such.
The native and full-governance results belong to `b4127b19`; unchanged source
projection does not assert that a later complete documentation tree was itself
executed. The packet reports generic CI separately from those completed jobs.

## Next development step after this increment

The next bounded task is
[fresh dependency provenance and complete live build admission](../../p06-dependency-provenance-handoff.md).
Current native builds still consume three reused dependency products. Their
stable hashes, captured headers and loaded paths are useful observations, but
do not prove the source and compiler invocations that produced those bytes.
The continuation must freeze the complete SoftFloat, Ramulator, yaml-cpp,
spdlog/fmt and argparse input closure, build in fresh isolated directories
under the existing budget, retain actual commands and archive-member/link
receipts, and join those products to the bytes actually loaded.

The complete application graph validator already exists in
`p06_managed_preflight_application_build.py`. Both format builds in the native
original passed it during inert review. The live producer currently admits the
final host command; the next implementation should integrate the existing
full-graph validation into live admission. It should not invent a replacement
contract or treat unchanged cached libraries as evidence of fresh compilation.

After that provenance work, independently reconcile the complete conditional
lifetime premises for all 33 selectors and 40 backing components. The new
pending-read observation is separate transient state; each run boundary
directly records two core cumulative fields. Those observations alone do not
close every component's source/binary-bound theorem or the absolute no-wrap
question. The full 24-process / 792-launch warm route stays blocked until the
reviewed qualification gate is satisfied. P06-A02/A03 and performance/phase
acceptance remain open.
