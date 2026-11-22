# W04 A06 — independent simulator runner repair review

## Verdict and scope

**PASS for the repaired runner at source and host-verification scope. No open F2 or F3 defect was found in this review. An explicitly unqualified validation-branch checkpoint is supportable. Native qualification remains unearned; this is not a recommendation to label the change master-qualified.**

Reviewer: `/root/w04_a06_runner_independent`, wave 4 assignment 6 (overall assignment 24). This reviewer did not author or edit the runner, tests, build rules, or production implementation. The review was read-only except for this report, its supporting proof JSON, and an owned temporary configured tree that was removed after the bounded experiment.

Repository: `/workspace/scratch/ea983fdea786/AI-GPU`.
Base HEAD: `42809ff0c1b81384d7c9b079e4ef786be8407600`.
The completion changes are uncommitted working-tree inputs. The SHA-256 inventory below identifies the reviewed bytes; the base commit alone does not identify the candidate.

I read `AGENTS.md`, the project status/roadmap/backlog and acceptance context, `docs/review/code-review-policy.md`, and the new simulator completion contract. The main review covers `p06_simulator_execute.py`, both runner test modules, reused compiler validators and argument parsers, process/evidence handling, and the actual configured SimX/runtime/application build paths. Production completion behavior and the independent parent-sensitivity results remain separate review scopes.

## Finding disposition

| Item | Severity / confidence / evidence | Disposition |
|---|---|---|
| W03 non-macro compiler options could evade a macro-only probe, including `-Ofast` | Prior gate-integrity defect, F3; high confidence; static proof plus retained adversarial test evidence | **Closed by this repair.** Every role now requires the exact release option multiset, rejects unsupported options and repeats, and replays all accepted non-bookkeeping options. |
| W03 an unretained include directory could shadow the effective generated header | Prior gate-integrity defect, F3; high confidence; static proof plus retained adversarial test evidence | **Closed by this repair.** Each role requires its exact ordered include vector; replay preserves the original arguments and working directory. |
| Kernel driver selections outside the application stamp could differ from probe selections | Concrete configuration binding risk; high confidence; static proof and configure/Makefile expansion evidence | **Closed for the current build rules.** Entire generated `config.mk` must equal the retained template after the fixed substitutions, and the probe uses the same generated `VX_CXX` prefix. |
| Pinned RISC-V preprocessing and native build/run results are unavailable | Outstanding execution obligation, `not_run`; high confidence; missing execution evidence | **Remains open for qualification.** This is disclosed, blocks a native-qualified claim, and does not prevent an unqualified validation checkpoint. |

There is no new F1 finding from this bounded review. This advisory review does not grant a maintainer approval or waiver.

## Why the compiler-record repair is correct

### Five independent original records remain independent

The validator still reads the four original stamp files and enforces their line counts: one unit-model record, one runtime-model record, one runtime record, and the application's separate kernel, host, and linker lines. It does not concatenate records or let one role supply another role's configuration. The existing shared validator continues to check the runtime, kernel, host, and exact runtime linker binding. Each of the five compile roles then receives its own syntax, ISA/ABI, macro, raw configuration, release-selector, option, and include-order validation.

`compiler_flags` is the original shell-tokenized argument list. The per-record digest hashes the unchanged record text without its newline, while whole-file stamp hashes and retained copies bind whitespace, line order, and newlines. The report preserves those original inputs; the original stamps are not expanded or rewritten to establish coverage.

The compiler-record test checks all five role identities, each original line digest, the complete token list, compiler selection, probe suffix, working directory, and byte-for-byte stamp preservation. Its adversarial peer retains independent checks that a host record cannot borrow kernel configuration and that either model must carry its own `PERF_ENABLE` selector.

### Exact option and include expectations match the build rules

`_compiler_options` uses the accepted strict release option sets from `p06_compiler_records.py`, with only the documented completion-specific include and dependency destinations. It compares option multiplicities using `Counter`, so missing, repeated, changed, or extra non-macro options fail. Kernel `-O3`, host/runtime/model `-O2`, warnings, language mode, PIC, and fixed RV64 ISA/ABI flags match the actual Makefiles. A replacement by `-Ofast`, an additional preprocessing switch, a forwarded include switch, or an unrecognized driver option cannot silently survive this check.

The unit and runtime model records share the source SimX include order and differ in their exact dependency-stamp destination. The runtime uses its original `../common` include from the generated runtime directory. Kernel and host use the completion application's actual include lists; the completion host has no benchmark AI helper include. The final runner accepted all five independently retained, actually generated Makefile records in this review's pure parsing check.

The probe omits only `-MMD`, `-MP`, and the validated `-MF` plus its operand. These options generate dependency bookkeeping. In the stamp recipe, Make's automatic target variable produces the stamp path as the recorded `-MF` operand; replaying it would overwrite the original evidence. The exact expected dependency destination is checked before omission. All remaining original arguments keep their order, including macro transports, warning/optimization options, and includes. My supporting proof independently reconstructs this allowed omission and verifies equality to `probe_flags` for all five retained generated records.

### Tool, prefix, and working-directory selection are faithful

The build receives a newly constructed environment with no inherited `CXX`, `CXXFLAGS`, `CONFIGS`, `LLVM_PATH`, `RISCV_SYSROOT`, `CPATH`, or Make-option injection. The selected PATH resolves the same `g++` that the Makefiles use; an optional host-bin is shared by inventory, build and probe. Ccache is disabled. The kernel uses the inventoried `llvm-vortex/bin/clang++`, and its prefix includes the RISC-V target, selected sysroot and GCC toolchain, `+xvortex`, `+zicond`, the loop-idiom setting and the unused-command-line warning control from `tests/regression/common.mk`.

A current, independently configured tree passed all 20 generated-input identity checks. A Make-only query from the real generated application Makefile expanded `VX_CXX`. Its token list was **exactly equal** to the kernel probe's compiler plus fixed prefix. The same query reported the expected host `g++`. The query used `--old-file=.depend` to prevent dependency rebuilding; no compiler or simulator was invoked, and none of the runner's native artifacts existed in the temporary tree.

The generated configuration is now compared byte-for-byte against `config.mk.in` with the fixed configure substitutions and VERSION values, rather than relying only on XLEN/profile/path checks. This binds `LLVM_PATH`, `RISCV_TOOLCHAIN_PATH`, `RISCV_PREFIX`, `RISCV_SYSROOT` and the other compiler/search-path choices outside the application stamp. The new LLVM_PATH and RISCV_SYSROOT attacks are rejected immediately after configure. Copied Makefiles and fragments also remain byte-bound to source. Future changes to the template or driver prefix need a fresh review and compatible evidence; this verdict applies to the hashes below.

## Tests and retained evidence

The retained final receipt at `w04-a02/runner-tests-final.json` records:

```text
PYTHONPATH=ci/project python3 -m unittest -v \
  test_p06_simulator_execute test_p06_simulator_runner_failures
Ran 26 tests in 10.486s — OK
```

The receipt's recorded before/after hashes match the current checked files, including the final runner and both test modules. I reviewed that receipt and log; I did not rerun the suite or present its mock cells as native execution.

The failure fixture now uses retained Makefile samples and real profile resolution, with completion-specific changes, instead of the previously incomplete synthetic flag records. Its synthetic command seam is explicit. The ten attacks still cover `-Ofast` and unretained include shadowing independently in all five roles. The fast-math mutation now replaces `-O3` as well as `-O2` and asserts that mutation actually occurred, so the kernel attack is substantive. The existing resource, process receipt, source/tool/interpreter/dependency drift, generated-input, geometry, stamp/binary drift, raw-log tamper, retained-artifact tamper, and final disk-reserve assertions remain.

I compared the saved original failure test module with the current module using ASTs: all **15 original test method names** and all original assertion calls remain. The two changed test bodies add the configuration-path attacks and make the fast-math mutation cover the actual kernel flags. No original failure assertion was removed.

Evidence identities:

| Evidence | SHA-256 / scope |
|---|---|
| `w04-a02/runner-tests-final.json` | `ebbde9576f1270a605d15a93ccb17c33b5e8c68619c8515d9ba75c89ae5b9d15` — retained 26-test receipt |
| `w04-a02/runner-tests-final.log` | `e09e38bbb18cbca3ca96bf0537fea903e4c114de5723b2e7f106e0e9fab231b5` — retained host-only log |
| `w04-a01-runner-repair/generated-proof.json` | `aa5a4dc2459325ef1a3f68e257917f295ad0644e05acac0e46c3fd8dc1e664b9` — earlier runner hash `9326bbc…`; generated stamps and four host preprocessor probes, no kernel/native run |
| `w04-a01-runner-repair/config-template-proof.json` | `4fa6868cbd0c9e876c356c4ab4c3014cf0c1bcff69d396e4e0b52cff3ac0e7f0` — final runner hash, generated-template and path mutation checks |
| `w04-a06-runner-proof.json` | `604fdc1600458ef2d2349eec940eff831e9d2544ed9ebd72cf7d97d7e931cbb3` — this independent configure/Makefile-prefix expansion, final-validator parsing of five retained generated records, assertion preservation check; no compiler/native execution |

The earlier generated-stamp proof has an earlier runner hash and is not relabelled as a final-runner native result. The independent proof here explicitly applies the final option parser to those original generated records and verifies the current configuration and driver prefix separately.

## Evidence integrity and resource limits

The runner requires a clean formal source checkout, binds loaded helper bytes, retains source/generated inputs and original compiler stamps, hashes tool and executing-interpreter identities independently, and checks stability before/after both native cells. The bounded process receipt must show a started process, a passing outcome, zero exit status, complete cleanup, and an exact raw-log digest/length before output observations are accepted. Final source/tool/dependency/generated/binary/stamp checks and retained-file/log rechecks can invalidate an otherwise complete matrix.

Every external command uses the shared process monitor with the unchanged **15 GiB disk reserve**, **4 GiB sampled process-group RSS**, **16 MiB per-command output limit**, **two build jobs**, and **one simulator thread**. Stage timeouts remain 120 seconds for configure, 1,800 for each build, 180 for each native run, and 30 for probes. Resource or receipt failure cannot be rescued by successful-looking output. A final evidence or resource failure clears `full_matrix_completed`; `qualified` and `acceptance_claimed` remain false even for a passing runner matrix.

These are credible bounded evidence controls within the disclosed model: polling is not a hard quota, process-group escape is outside containment, hashes do not detect malicious transient replacement restored between checks, and tools/dependency hashes do not enumerate every compiler support/header/dynamic-library input. Binaries are identified, not archived. Those existing limits remain accurately stated.

## Remaining execution obligations

- Actual pinned RISC-V Clang preprocessing: **NOT RUN** by this review and explicitly not run in the earlier host-only proof.
- Native checked-run unit build/run and native public-runtime regression build/run: **NOT RUN** here. They require the hosted provisioned validation environment and a clean source snapshot. Local free disk was approximately 2.3 GiB, below the unchanged 15 GiB native reserve; no native run was attempted.
- A successful future native packet must establish the native checked-run and legacy-gp unit observations and the six public successful launches, with its own reviewed source/tool/build/log identities. The host fault fixtures, native success cell and parent sensitivity remain distinct evidence.
- No new P06 acceptance, no-wrap lifetime bound, warm speedup, native public-runtime injected failure, RTL datapath/AFU qualification, vendor `hw_emu`, physical FPGA, or silicon result follows from this report. The existing P06 and broader project blockers remain unchanged.

## Reviewed input hashes

| Repository-relative input | SHA-256 |
|---|---|
| `ci/project/p06_simulator_execute.py` | `373ed9ba9141db73e740c87ec812872bb1dc2131b29819a7f001eda7e59e5641` |
| `ci/project/test_p06_simulator_execute.py` | `c648b3a3c784be7bfd55a34eb4dbc1de6105fe86144e64e8f732a676ed2ef1e8` |
| `ci/project/test_p06_simulator_runner_failures.py` | `2e75f446898dbd24990ea02df7d8fc2ae7789bf7f0e608244f0100c9dfe56b66` |
| `ci/project/p06_compiler_records.py` | `f441c12f4c9e4b9ef10eca13f8b5291fc41ffb86f1f42e42dfd320056dedd6da` |
| `ci/project/compiler_records.py` | `7a7088deb078eaa58016fc09dacd0f2a3415aaeac18a6dec8c8304de22bf66b4` |
| `ci/project/baseline_packet_contract.py` | `0cbdbebbceac67440fa1baa9ac9951f9f705aed9476275955815d6cb867e58df` |
| `ci/project/p02_matrix.py` | `e65eca7ac42705f175c296165d9579389d7db8a2deb7542d6eded8337bc83c17` |
| `ci/project/baseline_process.py` | `54ae2d6756c47349f4cf33a91209addcff447de1618a35892e0ac3e344506daa` |
| `config.mk.in` | `28fa1d7ad7076018ebb22a720df7cf3c792a5989a71834418f0ccb86a67551d1` |
| `configure` | `645cdad95c31a959a36c795c37b2b7e4c0202f19c53093aa9067cda3ef23a0be` |
| `sim/common.mk` | `086294bb98d1f5ac2324ffbf5fc66a377bc2f63d2b73f321f6351c9a7e2ecf0b` |
| `sim/simx/Makefile` | `c719966647f32fef5421dd798a89d3eeddccd692e7c61046e5744b7a8e722403` |
| `sim/simx/completion.mk` | `371f1cc7ad00e00094cb80e03074e114bf38134c59e03a617f34ec9fe209f235` |
| `sw/runtime/common.mk` | `2af4343c0738db4a665c96e24f90f78912302b20597dda74d9592afb6676736e` |
| `sw/runtime/simx/Makefile` | `a904a327b54481567d5efd205da7cba3fed0f7ecb6410ab641753d789c8ee975` |
| `tests/regression/common.mk` | `4164a783137b2f6e594ff3795f5911233227c3e4bfcb0319095cd6e78acf9b56` |
| `tests/regression/simx_completion/Makefile` | `a2f83c95a4b976ea179a5e6f850799f5795646042cff4e2df9afcc1ca4ecbad7` |
| `docs/designs/simulator_completion_v1.md` | `03825e18a97be8f6031b7cee4ec727578f05d7b96f3894b183967e12c3d3ff15` |
| `AGENTS.md` | `cf282720e32b644553893bee801d4beb2c39f521a3454193a8b7e91aaa06f8a7` |
| `docs/review/code-review-policy.md` | `99426ced05c04c1b14422f4fdacabcce3c680600461c4887b14e5eabf8b0587d` |
