# Native public counter diagnostic hooks

Owned files only:

- `tests/unittest/checked_counters/public_hooks.h`
- `tests/unittest/checked_counters/public_hooks.cpp`

No production code, flags, types, model update, or runtime logic was changed. No commit or push was performed.

## Implementation

The header has standard-library types only. `observation()` records cumulative actual constructor/destructor, run, read, write, typed overflow/underflow/negative-operand and unexpected-error counts. `model_state()` reads the actual model's platform ticks/reset generation/idle state, running state, pending reads, core cycles/instructions, architectural exit code and all 40 backing components. `selector_info()` freezes the exact 33-selector metadata from the common diagnostic accessor. `seed_component()` and `clear_components()` reject a non-idle, running or outstanding-read model. The caller still owns the separate obligation to finish public queues/collect AsyncRun and exclude any other submitter; a model snapshot does not prove that ownership.

All five wrappers call the unchanged real Processor methods. Typed `PerfCounterError` observations are rethrown to the unchanged production AsyncRun boundary. No synthetic counter error or fake Processor/RAM implementation exists. A mutex guards hook state and spans each real intercepted run/read/write, preventing diagnostic state access from racing those entry points; this is diagnostic serialization and is not a new public runtime concurrency guarantee.

Read traces retain up to 4,096 actual calls, including source address/tag, status/value, clock/reset identity and MPM class before/after, with a typed-overflow marker. The 16-entry destruction trace captures the live model immediately before the real destructor and separately records its completion and post-finalization platform state. `SimPlatform::cleanup()` resets the platform clock to zero: compare terminal observations to `Destruction.before`, not to `ticks_after`. The post-finalization clock reset is not evidence of a counter update or a monotonic-clock claim. `model_state()` after disposal returns live=false without dereferencing model storage.

## Required backend link interception

The unchanged backend object must be linked into the diagnostic backend shared library with `--wrap` for each of these symbol spellings:

```
_ZN6vortex9ProcessorC1Ev
_ZN6vortex9ProcessorD1Ev
_ZN6vortex9Processor11run_checkedEv
_ZN6vortex9Processor8dcr_readEjjPj
_ZN6vortex9Processor9dcr_writeEjj
```

The hooks object belongs in that backend library; do not copy it into the model library or application, and do not apply wrapping only to the final executable after the backend was already linked. The actual native application must assert the wrapper entry counts to establish runtime interception. Final source/link binding is the runner's responsibility.

## Completed bounded validation

Retained raw commands and compiler/nm output: `/workspace/scratch/98908dfa3444/w03-public-hooks-validation.log`.

- Fresh out-of-tree configure: RV64, p02-tfr, PERF=1, checked counters, host `/usr/bin/g++`, no toolchain download.
- The final hooks source passed `g++ <unchanged model flags> -fsyntax-only public_hooks.cpp` and a host object compile. Only dependency side-effect flags were removed for these probes.
- A separate translation unit using normal public `Processor` calls emitted the exact five target undefined symbols. Compiler unwind support symbols were retained and excluded from the Processor-specific comparison.
- The final hooks object emitted exactly the five corresponding `__real_` references and five exported global `__wrap_` definitions. GCC's local `.cold` clones were retained and excluded from the exported-definition comparison.
- A minimal translation unit including only `public_hooks.h` passed C++17 `-Wall -Wextra -Werror -pedantic` syntax validation.
- `git diff --check` passed for both owned files.

No native model/backend library was linked, no public runtime scenario was executed, and no qualification claim follows from these syntax/object checks. The native resource reserve remains unchanged.

Final SHA-256 identities:

| Path | SHA-256 |
| --- | --- |
| `tests/unittest/checked_counters/public_hooks.h` | `cb85ffb6df7151a3b9d747cfe243e464a3f16c4bd1063718b28af0800e86e95a` |
| `tests/unittest/checked_counters/public_hooks.cpp` | `c67ee622d159941d6c0ba3e759847cbe2fc463dcff9f9a989fd8dbf702ef434f` |
