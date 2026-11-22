# Wave 4 / agent 4 — native fixture and build source audit

Recorded: 2026-11-22T08:50:53.113415+00:00
Base revision: `42809ff0c1b81384d7c9b079e4ef786be8407600`
Checkout: `/workspace/scratch/ea983fdea786/AI-GPU`
Disposition: **BLOCK — one confirmed simulator cleanup defect makes the native unit's final fresh-context check unable to finish.**

This is an independent source review plus a host-only probe of the actual simulation framework. The native `Processor` unit and the generated public-runtime regression were **not compiled, linked or executed**. The candidate contains uncommitted changes and new files, so the SHA-256 identities below, rather than HEAD alone, bind this review. No project source was edited, no download/native build was attempted, and no commit or publication was performed.

## Blocking finding: abandoned channel reservations survive device destruction

**Location and trigger.** `tests/unittest/simx_completion/main.cpp` runs two normal contexts, a legacy bounded-RAM fault, a checked asynchronous bounded-RAM fault, and then another normal context in the same process. The fault launches instruction fetch at address 4096 against `RAM(4096, 4096)`. In `sim/simx/mem/memory.cpp`, `Memory::Impl::tick()` obtains the memory request with `peek()`, performs `ram_->read(...)` at line 120, and only removes the request with `mem_xbar_->ReqOut.at(i).pop()` at line 156. `RAM::get()` throws `OutOfRange` when `address >= capacity_`, before that pop.

**Ownership/accounting defect.** `sim/common/simobject.h` keeps `SimChannelBase::inflight_count()` as a process-global static atomic. Sending to a terminal channel increments it in `reserve()` (line 847); the only decrement is `queue_pop()` (line 905). `SimPlatform::cleanup()` clears its object and event containers, and `SimChannelBase::~SimChannelBase()` only unregisters the channel. Neither abandonment/destruction nor `initialize()` or `reset()` retires the reservation belonging to the faulted request. Full destruction of a failed Processor therefore leaves a stale global count. This is an existing simulation-framework leak exposed by the new unit, not a new defect in the hand-encoded program.

**Consequence inferred for the native unit.** `ProcessorImpl::run()` stops only when the cores have stopped and `SimPlatform::idle()` is true. `idle()` requires the global count to be zero. The unit's final `check_normal(7)` cannot meet that condition after the bounded-RAM faults. The hosted runner would be expected to time out the `unit-run` cell instead of reaching the required success inventory. This native outcome is a source-derived prediction; it was not observed by running the native Processor.

**Confirmed with real framework code.** The host-only probe `abandoned_channel.cpp` includes the actual, unmodified `sim/common/simobject.h`. A real `SimObject` receives a real channel packet and throws before `pop()`. The probe uses the same destruction ordering as `ProcessorImpl`: `finalize()` first, followed by release of the owning shared pointer. It then calls `initialize()`, constructs a new object, resets the platform and successfully consumes the new packet. No replacement simulator framework or mocked count is used. Its observed output is:

```text
after_exception inflight=1 idle=0 queued=1
after_full_destruction inflight=1 idle=0
fresh_context_after_consumption inflight=1 idle=0 queued=0
```

The probe compiled and exited zero; zero means that the targeted defect was reproduced, not that completion behavior passed. It does not instantiate a native Processor, use RAM, execute RISC-V instructions, or test public runtime integration.

**Minimal repair recommendation.** Repair abandoned reservation accounting at the framework ownership boundary, with independent tests for queued and scheduled-but-undelivered packets. Preserve the native unit and the fresh-context obligation. Clearing the global counter in the test or deleting the last normal context would conceal the defect. A production repair must account for destruction order and ensure a terminal reservation is retired exactly once; a broad reset of shared accounting without establishing ownership is not an adequate substitute. Recheck both successful context recreation and exception destruction after the repair. This report does not authorize additional architectural scope or claim the fix is already reviewed.

## Other scoped source findings

No additional definite compile/link/configuration defect was established in the inspected native fixture and build path. The following are source-derived checks, not executed native evidence:

- **Instruction encoding / x3.** `(immediate << 20) | 0x193` encodes `addi x3, x0, immediate`; 7 and `0xfff` give the intended 7 and sign-extended -1 witnesses. `0x0000700b` and `0x0000000b` match `wsync` and `tmc x0` in `vx_start.S` and the real decoder. The two warp-control operations do not declare a destination register. The legacy exit accessor reads warp 0 / lane 0 / x3. `wsync` precedes warp termination, matching the real startup exit sequence.
- **Launch descriptor / bounded RAM.** The unit programs the required startup, entry, argument, dimensional and block-size DCRs. The KMU retains those fields over launch reset, initializes local-memory size to zero, and dispatches one CTA to the sole configured core. Address 256 is inside the bounded page; address 4096 is the first out-of-range byte and is aligned to the configured memory block size. Disabling ACL does not disable the independent capacity check. The checked entry directly calls `impl_->run()`, while the legacy entry retains its catch/log/-1 behavior.
- **Kernel entry and arguments.** `KERNEL_LIB := vortex2` selects KMU startup. The `__kernel` declaration is the established annotation/retention convention. `vxbin.py` maps `__vx_kentry_kernel_main` to public name `main`; the runtime distinguishes the image startup address from the selected kernel entry address. `Queue::enqueue_launch` copies the 16-byte argument blob at enqueue, stages it to device scratch, and programs its pointer through the KMU argument DCRs. The zero-initialized unused dimensions are normalized by `ndim=1` handling.
- **Global pointer witness.** The volatile initialized global forces a retained global-data load. The established two-pass startup build detects data sections and enables `NEED_GP`; startup loads `gp` from the linker-defined global pointer. The kernel captures gp, and the caller specifically requires its low 32-bit word to be nonzero while checking the global value, XOR result, sequence and reserved field. Actual compiler output and gp value remain unverified.
- **Six serial public launches and cleanup.** Two distinct `run_context()` calls each perform three serial launches. Each iteration waits for poison upload, launch and read; repeats a completed launch event wait; checks output; and releases both read and launch events. Explicit close finishes the queue and releases output, kernel, module, queue and device before the next context is created. The readback storage lives in the context; launch arguments are copied by the runtime. Native cleanup success and process-wide state recreation have not been demonstrated.
- **Build routing.** The additive `completion.mk` includes the accepted SimX Makefile, links the ordinary model `OBJS` with the directed unit object, omits `main.o`, and adds `-pthread`. `configure` copies `*.mk` and new test Makefiles into a fresh tree. The runner's absolute unit target matches the fragment's default `DESTDIR`; the runtime and application builds use the generated test directory, followed by direct execution with `VORTEX_DRIVER=simx` and the runtime library directory on `LD_LIBRARY_PATH`. The generated command graph, target compiler, native link and dependency availability were not executed in this audit.
- **Configuration scope.** The runner fixes RV64, `p02-tfr`, `PERF=1`, two build jobs and one host thread, and separately validates model/runtime/kernel/host compiler records and effective headers. The profile selects one core, four warps and four threads; default `SIMX_MT=0` selects one model worker. This review does not qualify another profile, threaded model, RV32, RTL runtime or native public fault path.

## Executed command and resource evidence

Only the newly targeted framework concern was executed; existing positive suites were not repeated. Compiler: `/usr/bin/g++`, Debian 14.2.0-19. Compilation used `-std=c++17 -Wall -Wextra -Wfatal-errors -Werror -O2 -DNDEBUG`, the actual `sim/common` and `sw/common` include directories, and `-pthread`. The exact argument arrays, environment, working directories, exits and log hashes are retained in `/workspace/scratch/ea983fdea786/w04-a04-native-probe/commands.json`. Compilation and execution each had a 30-second subprocess timeout.

The observed free space on the workspace filesystem was 2,469,609,472 bytes, below the native runner's unchanged 15 GiB minimum. No budget was reduced, no native process was launched, and no native pass is claimed. The native runner and its output parser were inspected but not invoked.

The review covers the named fixture/build mechanism and concrete cleanup blocker. It is not a full production runtime review, acceptance decision, parent-sensitivity run, counter qualification, performance claim, RTL or physical-device result. It does not establish faulted-context reuse; it establishes that destruction must retire old ownership before a new context can become idle.

## Retained probe identities

| Artifact (under `/workspace/scratch/ea983fdea786/w04-a04-native-probe`) | SHA-256 |
|---|---|
| `abandoned_channel.cpp` | `3ea55b849a140f82c08c27bca813661ad06fdf92757d7d370f5cddbf42727adc` |
| `commands.json` | `e33368abacdd4193c89da10c25cb1a50817ee8db6c0db8766e4c1d542fa7c272` |
| `compile.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `run.log` | `d766532781950dac9b70eb0c49020d3af54e62cf3d0ed4750e536901f67f6211` |
| `review-inputs.json` | `02ab95c54122360f4e09675895cc7cb973c0a55257e507c6818cd301eaae8eb0` |

## Exact source identities

| Input | SHA-256 |
|---|---|
| `AGENTS.md` | `cf282720e32b644553893bee801d4beb2c39f521a3454193a8b7e91aaa06f8a7` |
| `docs/designs/simulator_completion_v1.md` | `03825e18a97be8f6031b7cee4ec727578f05d7b96f3894b183967e12c3d3ff15` |
| `ci/project/p06_simulator_execute.py` | `373ed9ba9141db73e740c87ec812872bb1dc2131b29819a7f001eda7e59e5641` |
| `.github/workflows/p06-simulator-completion.yml` | `233521df10f3b3c90035a533849a17e783a5977a705023609ef73d07ca21b65c` |
| `ci/project/p02_matrix.py` | `e65eca7ac42705f175c296165d9579389d7db8a2deb7542d6eded8337bc83c17` |
| `ci/project/p06_compiler_records.py` | `f441c12f4c9e4b9ef10eca13f8b5291fc41ffb86f1f42e42dfd320056dedd6da` |
| `ci/project/test_p06_simulator_execute.py` | `c648b3a3c784be7bfd55a34eb4dbc1de6105fe86144e64e8f732a676ed2ef1e8` |
| `ci/project/test_p06_simulator_build.py` | `d7a0e6babb72c4d8174f568bcea41a7b16be26efb5b96969d27bbf3041acb5b1` |
| `configure` | `645cdad95c31a959a36c795c37b2b7e4c0202f19c53093aa9067cda3ef23a0be` |
| `config.mk.in` | `28fa1d7ad7076018ebb22a720df7cf3c792a5989a71834418f0ccb86a67551d1` |
| `profiles/p02-tfr.json` | `79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102` |
| `sim/simx/completion.mk` | `371f1cc7ad00e00094cb80e03074e114bf38134c59e03a617f34ec9fe209f235` |
| `sim/simx/Makefile` | `c719966647f32fef5421dd798a89d3eeddccd692e7c61046e5744b7a8e722403` |
| `sim/common.mk` | `086294bb98d1f5ac2324ffbf5fc66a377bc2f63d2b73f321f6351c9a7e2ecf0b` |
| `sim/simx/processor.cpp` | `569cf629d1e25ec9a295b20bfadfabbe21cd0989127f2b825fceee99a8062b78` |
| `sim/simx/processor.h` | `588db10c3997e91dd471771cd12bb0329dacbc3902248b84353beebd19bc0438` |
| `sim/simx/core.cpp` | `f95003971a6052962b761b1ee8e815ead42f6a60fccf8157fa94c3ded3e44f31` |
| `sim/simx/core.h` | `58a3b2b7d2b90283d603b9b0b17401fa179ff93d6e76639b3bbeb1563afc6961` |
| `sim/simx/decode.cpp` | `1ef0b3c2bd461a579ad4f1f23464721d1b4686ec0ff73d5a5569167335bfc884` |
| `sim/simx/operands.cpp` | `f1de7870bf82f35427537017d6fe1fcb74fb0d1a909dde6a3af113bc56e63944` |
| `sim/simx/wctl_unit.cpp` | `450f2e683dd4e6c182264b948dfdae27e4493d6b86e577ee5c29dff236263206` |
| `sim/simx/kmu/kmu.cpp` | `b01fc64bd4e2ea59224872aabce3b1233315ad07f8f7341fe617b40fe3fc4421` |
| `sim/simx/kmu/kmu.h` | `e620b0a8e550f9b62203a7b5ae22c26d7bf982f5421a0791793182da6f317660` |
| `sim/simx/scheduler.cpp` | `d62b9fab40133011a7293e994e0d57514212ed5f636e836ffb9fd468fbfa2056` |
| `sim/simx/cta_dispatcher.cpp` | `7ab0772317c2ae7c2221d77811e517f17f9dcad48deddf580118d654912c82ee` |
| `sim/simx/types.h` | `2cdd672188cdcbf03558bc9bd2058c9715466c35eacece5078f692f46d809809` |
| `sim/simx/mem/memory.cpp` | `4d73809cd63a0c768115c5de0205989f6f941446895de1831587002fc94ed474` |
| `sim/common/simobject.h` | `e5ca3afcc9b856a74d97d83c285dcfc97e40050391a7f26b9f72b1d298345df6` |
| `sim/common/mem.cpp` | `2dc21e7ccb04e773b091f209652107bac673edbc6d6640cfca0418ad89a73cba` |
| `sim/common/mem.h` | `c6fb3dc152b641edac6d1d373f7b7425d038a902b3ef2899d39f5aab00baf152` |
| `sw/common/util.h` | `22df04c6d7242b40fc63f1701643d5eed8601f64893104567580bab80360a884` |
| `sw/runtime/simx/Makefile` | `a904a327b54481567d5efd205da7cba3fed0f7ecb6410ab641753d789c8ee975` |
| `sw/kernel/src/vx_start.S` | `177dc612239e463ed27631a746473015116cc4e81d707b0f9d7dfe35281b9109` |
| `sw/kernel/scripts/kernel_startup.sh` | `8e408e07bf5e177da7e466cb14f1d386c487a2e390f7fcebd20b5d157e683221` |
| `sw/kernel/scripts/link64.ld` | `e8f02c64c8666a4df40d35d51ac50e2c62f02d29618323c13890e9a50e36b0e5` |
| `sw/kernel/scripts/vxbin.py` | `6c76ef0c505c68e02a68a3660021d20f6c8b8cc18b9a4c0b1a544611673875ed` |
| `sw/kernel/include/vx_spawn2.h` | `7865a242249cdc66d2843780ff9208b1e0970124001ea9927529acb18a5ac2ab` |
| `sw/kernel/Makefile` | `b1c359421ca2b1b8c31b9dc98893fac772daa239e236e9d1c9225a1eb431238c` |
| `sw/runtime/common/module.cpp` | `5d2efe2ba92801d3dbb1e836b077e7d966bc9a6b2beb8d29c50f89ce4ee67f06` |
| `sw/runtime/common/queue.cpp` | `1d785262d128de3ffbf1feb32cc2b32f6457a6644df6ef9a04d4e8b4d45c962e` |
| `sw/runtime/include/vortex2.h` | `9738cdf35a7344d6a974b4d78f7b02d3c1e7ce87cfe68ef668b03c8eb1832614` |
| `tests/regression/common.mk` | `4164a783137b2f6e594ff3795f5911233227c3e4bfcb0319095cd6e78acf9b56` |
| `tests/unittest/simx_completion/main.cpp` | `343f68f1cf90ea5e81ae9d97d8428df9e5db246fb35ac29af163c5b099b1727e` |
| `tests/regression/simx_completion/main.cpp` | `07687cbb532f3f6901d928da5de181fa76d8c0efc8796bfd578d0c485008b468` |
| `tests/regression/simx_completion/kernel.cpp` | `15f6df7b29f9211b4fdf8ac589265241c177e8059e9a2bebcb479bc3baef8cc6` |
| `tests/regression/simx_completion/common.h` | `ab20e7e7dff9ede29b045f9a38405ee0eab8f366517cc51f9fb1a836b521b926` |
| `tests/regression/simx_completion/Makefile` | `a2f83c95a4b976ea179a5e6f850799f5795646042cff4e2df9afcc1ca4ecbad7` |

The complete observed Git status and source file sizes are retained in `review-inputs.json`. Hashes identify the source state at report creation; concurrent edits after that point need their own review.
