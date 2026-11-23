# P06 fresh dependency provenance evidence

## Scope and current state

This packet records the next bounded P06-T01 step selected by the
[development audit](development-audit.md): build the three selected SimX
dependency products from immutable source and bind their actual compilation,
archive/link steps and bytes to the managed native lifetime population. The
[v1 design](../../../designs/dependency_provenance_v1.md) and
[handoff](../../p06-dependency-provenance-handoff.md) define completion.

The implemented route records the source-to-compile/archive/link chain, checks
the exact selected products and model link inputs, and binds the receipt to
live managed admission. The live route also invokes the existing complete
30-command application validator, including the 14-source runtime stub.
The [published foundation](validation/foundation-publication.json) is commit
`5527cb062e10dfff3266022d138dd7cdf63f5e5c`; later reader and failure-retention work
has its own source identities and focused review in the
[validation index](validation-index.md). A foundation result does not establish
validation of later bytes.

Complete dependency, native and combined-control readers are now implemented.
**The next bounded action is to collect one complete fresh dependency and
managed-lifetime original, replay its untouched bytes with external intake
pins, and independently review that original and its separate controls.**
A successful complete original, complete inert original replay and independent
original review remain unobserved in this continuation's recorded evidence.
Host fixtures and source auditing do not establish native execution or phase
acceptance. The [control-coverage audit](control-coverage.md) preserves the
remaining whole-original semantic mutation obligation.
The [reset/recovery record](recovery/environment-reset.md) distinguishes earlier
development results from fresh validation of restored files.

## Reader and evidence index

The [intake and replay guide](replay-guide.md) defines the external ZIP,
execution-revision, report and source-snapshot expectations, exact CLI flags,
literal member prefixes, and fresh result paths. Each reader treats retained
source, commands and binaries as inert data; it does not run the original.

| Reader | Reviewed scope |
| --- | --- |
| [Dependency reader](../../../../ci/project/p06_dependency_replay.py) | Complete selected dependency source, tool, build-record and product consistency. |
| [Native reader](../../../../ci/project/p06_dependency_native_replay.py) | Dependency reconstruction plus hosted identity, managed builds, raw four-process lifetime evidence and loaded-product joins. Separate controls remain outside this scope. |
| [Combined control reader](../../../../ci/project/p06_dependency_control_replay.py) | Native/dependency reconstruction plus the separate pending/always-zero and substituted-library controls, with one bounded archive owner. |

The [native/control integration review](agents/w07_a06.md) records source trust,
input closure and population boundaries. The [validation index](validation-index.md)
distinguishes actual tiny host builds and child processes, synthetic semantic
fixtures, pinned-source/configure observations, and tests against different
source checkpoints. Its overlapping test runs are not an additive unique-test
total. The [checkpoint-failure review](agents/w08_a01.md) retains the reproduced
failure and subsequent 67-test pass for the probe/substitution correction.

At the last attributed observation, **2026-11-23 10:07:16 UTC**, the
[fresh hosted run](https://github.com/baabi-boo/AI-GPU/actions/runs/45146777986)
was queued with no executed steps, logs or conclusion; see the
[workflow/probe review](agents/w07_a04.md). That observation does not identify
the queue's cause or promise an execution result. Recheck the provider at
intake. The [separate host diagnostic](host-diagnostic/README.md) has a prepared
attempt and distinct evidence contract. Its eventual lower-scope result cannot
substitute for formal preparation, the native population or loader evidence.

## Immutable source audit

The [source-input audit](source-inputs/README.md) retains the complete manifest,
406-unit source plan and repeated exact Git-object verification. All 1,294 files
contain 10,938,128 bytes. The graph has 309 SoftFloat, 60 Ramulator, 29 yaml-cpp, 7 spdlog and 1 extension
translation units. Argparse is configured without a selected compiled object.
These observations do not establish the separately required 413 tool executions.

## Work and acceptance boundary

The [execution ledger](agent-execution.json) records spawned, completed and
handed-off assignments across the requested ten waves of six. Recovery and
validation follow-ups by the same authors do not inflate the sixty-agent count.
Each report under [agents](agents/) names its scope and distinguishes inspected
code, synthetic controls and observed execution.

The managed population remains four FP16/BF16 × policy processes, 132 launches and
4,224 exact FP32 words. Pending-accessor, always-zero and alternate-library controls
remain outside that population. All seven fields remain false: `qualified`,
`ready_for_warm`, `warm_execution`, `full_warm_coverage`, `acceptance_claimed`,
`phase_acceptance`, and `performance_acceptance`. P06 and P06-T01 remain
`in_progress`. Complete 40-component lifetime qualification, no-wrap bounds, warm
performance, P06-A02/A03, vendor integration and physical hardware remain separate
obligations. Historical originals retain their existing meaning.
