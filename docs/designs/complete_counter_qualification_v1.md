# Complete managed counter qualification v1

## Purpose and scope

This is a separately selected qualification route for the existing seed-free
managed counter preflight. It joins the reviewed source argument, original
directed diagnostics, fresh dependency compilation, complete application/model
builds and each actual process's lifetime observations. It preserves the
historical preflight, dependency and warm-v1 contracts.

The supported execution is RV64 timing SimX, the exact `p02-tfr` topology,
`PERF=1`, checked 64-bit counters, one simulation worker, one context and one
submitter. Both FP16 and BF16 run under both allocation policies. L2, L3, virtual
memory, WGMMA and CP-on-LLC routes remain disabled. This contract does not
qualify RTL's separate counter widths or physical hardware.

## Conditional lifetime argument

The fixed inventory has 33 available selectors backed by 40 cumulative
components: 26 single-component selectors and seven two-component aggregates.
The latter are six D-cache bank sums and the TCU two-buffer read sum. The twelve
unavailable L2/L3 selectors must not be queried. Pending memory reads are a
separate transient balance, not an additional cumulative component.

For nonnegative components whose reviewed production updates and permitted
resets preserve monotonicity, each aggregate at any earlier point is no larger
than its successfully checked terminal value:

`S_j(t) <= S_j(T) <= 2^64 - 1`.

All aggregates must be checked. Component checks alone do not bound a sum.
The source and actual process evidence must establish the no-update suffix
from the terminal vector through destruction. A guard failure at any point
invalidates the whole process, including an excluded prime or warm-up.

The ten source premises cover origin and updates, exact inventory, admitted
reset behavior, exclusive ownership, completed work and pending balance,
coherent full-width replies, terminal vector ordering, post-vector cleanup,
dependency finalization and failure containment. The reviewed manifests and
raw records supply these relationships. A Boolean assertion that a premise
passed is not evidence.

`memory_lt` keeps its existing run-loop accumulation meaning. No new integral
over every platform tick, elapsed host time or physical memory latency is
inferred from qualification.

## Frozen proof and prerequisites

The new proof freezes source identities separately from the future execution
revision. Its reviewed production projection is based on `5e88e2ec`; this
avoids a circular requirement that a file name its own future commit. The
three pending-read accessor files are explicitly reviewed against the earlier
lifetime projection. Seeded diagnostic source identities are retained as a
separate population and never admitted into the measurement build.

The original model/public diagnostic packet is revalidated through both trusted
inert readers, including its explicitly pinned public source inventory. Native
diagnostic controls retain their original source and execution identities.
They do not become a new native run when replayed. The dependency source
projection must match the fully verified fresh receipt and its selected graph;
a shared-library hash alone does not establish compilation origin.

Qualification inputs are bounded, exact-schema data with independently
selected identities. A rehashed altered document, missing component, duplicate
bank, changed source, wrong diagnostic original or unsupported configuration
must be rejected. Retained scripts, commands and binaries are never executable
input to a replay reader.

## Explicit admission and fresh execution

Only the new qualification entry point selects this contract. It requires the
lifetime and fresh-dependency modes. Missing or invalid qualification cannot
fall back to an earlier route.

Admission validates the proof and prerequisites before build or native
execution. The qualification digest and reconstructed admission are part of
the common build binding. Each process binding also contains the qualification
digest before hashing and before launch. The existing native
`--qualification-id` echo binds the original observations to that process;
no new C++ API or measurement interval is introduced.

Proof, source, tool, dependency and product stability are rechecked at the
applicable existing checkpoints and at finalization. The unchanged compiler,
generated-header, complete-link and loaded-library validators establish the
actual build route. Both policies use the identical guarded binary within
each format.

The fixed preflight contains four processes, 132 launches and 4,224 exact FP32
output words. Its 16 snapshots contain 528 available queries, 1,056 successful
half replies and 192 unavailable rows receiving no query. Cache-flush reads
are separately accounted. Counts alone do not establish the required ordering,
ownership, pending balance or disposal; the raw lifetime records must validate.

## Replay and claim boundaries

The new reader explicitly selects its new outer contract and shares strict
reconstruction with the dependency/lifetime reader. The old reader keeps its
original default contract. A reader must not select a permissive mode from
packet metadata, strip new fields or rewrite an original into another version.

Qualification is derived only after source/build/dependency reconstruction,
both numerical formats and policies, every process observation, final stability
and exact archive inventory all pass. Replay reports
`native_execution="not_run"` and `retained_code_executed=false`; actual execution
belongs to the separately identified original.

The nested historical observations retain all seven false qualification/warm/
acceptance fields. A new `counter_qualification_passed` result is scoped to the
fresh four-process preflight. It does not make a future process qualified,
constitute a 24-process warm experiment, establish a speedup or close P06-A02/A03.
The historical `unresolved_obligations` list is retained as part of the inner
preflight observation schema; it is not reinterpreted as the new outer result.
The separately derived outer result is the only complete counter-qualification
claim, and its scope is the recorded four processes. The historical warm-v1
high-half rejection and all original evidence remain unchanged. A later full warm route needs its own prelaunch bindings and complete
fresh observations under the unchanged workload and performance predicates.

## Review and validation

Independent review must cover the source projection, all ten premises, explicit
route selection, prelaunch binding and complete inert reconstruction. Tests
include internally rehashed inconsistent records, stale or swapped proof and
dependency identities, missing/duplicate components, partial snapshots, changed
inputs during execution, invalid cleanup and exact historical-route rejection.
Host fixtures remain synthetic tooling evidence. A fresh native original and
independent review are required before claiming this preflight's qualification.
