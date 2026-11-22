# Independent public counter-fault review

Reviewer: `/root/w07_a01_public_fault_review`. The root coordinator retained
this summary of the independent read-only review. No edits, builds, tests or
publication were performed by the reviewer. The author separately reported
five passing methods and ten RAM/LLC cells.

**Verdict: land the two additive controlled host public-error-transport tests.
No F2/F3 defect found.** R3 review depth was used for this enforcement evidence.
The production/runtime dependencies were reviewed at
`53f4ad08c469a1cc73fa604249b302f9416055e0`.

## Findings

The new tests compile the actual SimX backend, command processor, common
runtime, device, queue, event and public MPM implementation. Processor and RAM
are explicitly controlled substitutes. Generated shim insertion requires one
exact existing source site; the original fixture/test/control files remain
unchanged.

Faults perform real PerfCounter arithmetic: counter-to-counter overflow,
zero decrement and signed-negative addition. The trigger verifies the exact
typed reason/diagnostic and unchanged protected/source operands, then rethrows
the original error. Exactly one trigger and one valid typed witness are
required, so an unrelated injected exception cannot substitute for the guard.

Asynchronous cases cover pending execution, repeated/higher/multiple event
waits, a suppressed dependent command, queue-error reporting and consumption,
continued backend rejection, a second queue, explicit cleanup and a fresh
successful context. Checked-entry counts match controlled launches; no legacy
entry may run. Synchronization uses the retained condition-variable gate and
completed public observations, not sleeps. No captured-state lifetime defect
was found.

The synchronous query case first proves a healthy MPM read. Overflow at the
controlled Processor DCR hook must return VX_ERR_INVALID_VALUE, leave the
64-bit caller sentinel unchanged and occur exactly once. Repeated queries and
later writes/launches remain rejected without processor reentry, including
after queue-error consumption. Cleanup and a fresh context must succeed.
This directed failure is at the first failing DCR read; it is not exhaustive
low/high-half failure coverage.

The query aggregate is a controlled local PerfCounter addition, not a real
Cache/TCU/native backing-source reduction. `native_model=0` correctly preserves
that distinction. Actual public native counter injection remains open.

O2/NDEBUG, warnings as errors and UBSan are used. Source, generated shim/config
and binary identities are checked before/after the declared boundaries. Bad
commands, cleanup, diagnostics, exceptions or process exits fail the tests.
These checks are host evidence, not a retained native toolchain packet or
all-33 lifetime/coherence qualification.

## Reviewed identities

| File | SHA-256 |
|---|---|
| `ci/project/test_p06_checked_public.py` | `d9e830d10f416ea62e9db1f4cfdf5b061aff696641957fd3bfa99aea21bdc8b4` |
| `ci/project/fixtures/checked_counter_public.cpp` | `392092f25404acfd275fddb28121598c01a8266b3e22a6d4e75e8ea275b474b1` |
| Existing public test | `5258035e883eaed32214472c11f2d0015865108a7c892f1e4b993836a4589a7c` |
| Existing public fixture | `68c18324ce4786940f5c06eb46d8388fd5e7f1fa96f6d2826e249209d7d56174` |
| Existing control header | `1d23cbdbbb873385edd51857ee8bad91448bcdad7b351f72a5a5c5da3d40ead8` |
| `sim/common/perf_counter.h` | `8635c832c9fc4ad60cf3bf21665a5bc22a6d3500b1f5c012dd056fb4c6907417` |
| `sw/runtime/common/async_run.h` | `a9f63b2a896c5e512f7c592c758618ea88b774c9dac4bca29e847e2e3719a24e` |
| `sw/runtime/simx/vortex.cpp` | `0d890c95fecb67da26d23ea4a0af10ac328dddf110cd2575baff3aa5d4c905cb` |
