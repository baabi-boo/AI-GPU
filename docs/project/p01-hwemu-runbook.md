# P01 vendor hardware-emulation preparation

This runbook advances **P01-T05 preparation**. P01-A01 and P01-A02 retain their
accepted execution evidence. P01-A03 remains blocked until a qualified vendor
environment produces independently reviewed DMA, launch and completion evidence.
The commands here inspect prerequisites and prepare a candidate; they do not run
an accelerator or close the phase.

Read [current status](status.md), the [P01 phase](phases/p01-baseline.md), the
[developer resource policy](developer-guide.md) and [AGENTS.md](../../AGENTS.md)
first. The exact manifest and receipt format is in the
[manifest guide](p01-hwemu-manifest.md).

## 1. Inspect the available environment

From the source root:

```sh
python3 ci/project/hwemu.py inventory --root . --json
```

The inventory reports the source revision/tree, clean, dirty or unknown state,
submodule readiness, vendor executable presence, vendor-root environment-variable
presence, free disk and Linux `MemAvailable`. It does not print those variables' values,
license-server addresses, source filenames or installation paths. It invokes
fixed local Git metadata queries and compares raw tracked bytes and Git modes
with the index and `HEAD`. It does not use `git status`, execute Git conversion
filters or run a vendor binary, setup script, license probe, download, build
or workload.

The source observer requires ordinary, fully present index entries and exact
tracked bytes. All 19 source paths consumed by the inspector must also be
recorded as regular blobs in both `HEAD` and the index; ignored or untracked
copies and staged-only additions do not qualify. This membership check covers
the inspector's inputs, not every build dependency. Each Git query strips
inherited `GIT_*` values and sets `GIT_CONFIG_NOSYSTEM=1` plus
`GIT_CONFIG_GLOBAL=os.devnull` (`/dev/null` on POSIX). System and
default HOME/XDG global configuration are excluded; repository configuration,
enabled worktree configuration, explicit includes and matching conditional
includes remain checked. Clean/process filters and partial-clone/promisor
settings in those local/include scopes are unsupported, even when an include
points to an otherwise excluded machine/user file. Assume-unchanged/skip-worktree
entries and sparse index entries are also unsupported. Checkout normalization
that changes blob bytes can therefore block an otherwise apparently clean
checkout. Ignored untracked contents are outside this cleanliness check; explicitly declared
files still need their own checks. See the [source contract](p01-hwemu-manifest.md#2-paths-source-state-and-directory-separation)
for tracked symlinks and recursive submodules.

Inventory returns **exit 1 and `outcome: blocked`**, including when every named
tool is on `PATH`. Tool presence cannot establish a qualified release, platform,
license entitlement or matching artifacts. A blocked inventory is a prerequisite
list, not an instruction to install the full toolchain.

The continuation environment had no `v++`, `vivado`, `platforminfo`,
`emconfigutil`, or XRT inventory utility on `PATH`. Its source checkout also had
uninitialized submodules. These are observations of this environment; another
machine must be inspected independently.

## 2. Establish an actual vendor build

Use an authorized environment with a supported Vitis/Vivado/XRT combination and
platform package. Record the actual releases, installation identities, platform
dependencies, entitlement where required, and available resources. No particular
release or FPGA platform is qualified by this runbook.

Prepare an exact clean source checkout and initialize its pinned submodules.
Keep native tools separate from source and build directories. Run `configure`
from a dedicated RV64 build directory after any source/configuration change.
This bounded contract uses an empty profile, the `ubuntu/focal` native-tool
bundle setting and the default build-local install prefix. The `OSVERSION`
setting identifies that native-tool bundle; it does not certify a vendor host OS.

The existing [XRT build rules](../../hw/syn/xilinx/xrt/Makefile) produce
`vortex_afu.xclbin` and `emconfig.json`. Select **`TARGET=hw_emu` explicitly**,
fix the actual platform descriptor, and propagate the frozen integer-smoke
configuration to both hardware and software. Limit the outer build and nested
vendor work with explicit `JOBS` and `MAX_JOBS`; an outer Make worker count alone
is insufficient. Review any platform-derived memory settings and native tool
dependencies separately.

This planner checks an **already prepared** artifact set. The generated build
must include the XRT runtime and demo compiler stamps; `configure` alone cannot
produce those records. Retain the producer's actual commands, successful or
failed results, tool/platform identities, generated files and artifact hashes.
Create the build receipt from that retained producer record. Reconstructing a
receipt from arbitrary existing files cannot establish how they were built.

Do not download or launch vendor tools while entitlement, compatibility, platform,
resource requirements or artifact provenance remain unresolved. Preserve failures
and the existing [blocked acceptance record](evidence/p01-xrt-blocked.json).

## 3. Freeze and check the input manifest

The [manifest guide](p01-hwemu-manifest.md) describes all required fields and
identities. It binds a declared source revision/tree, generated build, vendor
roots/releases, platform descriptor, matching emulation artifact names, source
Tcl hook, build receipt and resource budget. Use actual observations; its example
contains deliberately invalid placeholders.

Use canonical absolute paths to regular files for all manifest declarations.
Whitespace, shell/Make syntax, dot segments and symlink traversal are rejected.
If an installation exposes a
versioned library through a symlink, declare a supported real file path; this
does not verify that the future dynamic loader will choose that same file.
Dependency loading remains part of vendor qualification.

```sh
python3 ci/project/hwemu.py plan /absolute/retained/hwemu-manifest.json --json
```

The planner checks file bytes with shared size/count limits, validates the
receipt against the manifest, compares copied build files with source, checks
native RV64 compiler records, rejects the vendor-free shim, checks the lean XRT
configuration, and observes source and resource state at both boundaries. It
rechecks retained inputs before returning a candidate. It never executes text
from the manifest or calls the generated runner. The CLI prints its report
without writing output files.

The [shared compiler-record contract](p01-compiler-records.md) requires one
runtime record and three ordered demo records: kernel, host and linker. Only
LF separates records; spaces, tabs and blank lines are allowed. CRLF, bare CR,
other controls and Unicode whitespace separators are rejected. Each compilation
record independently establishes the frozen configuration and both RV64 macro
selectors; include/dependency operands cannot supply definitions.

The demo kernel record must contain exactly one effective direct
`-march=rv64imafd` and `-mabi=lp64d`. RV64 macros alone do not establish a kernel
compiler target. Required options hidden in another option's operand or a
preprocessor stream cannot satisfy this check. Host/runtime records cannot
select these kernel ISA/ABI flags. All compiler roles reject response files,
Verilator/Make transports, unsupported options and free source operands.

Shell operators, dollar signs, backticks, glob characters (`*`, `?`, `[` and
`]`), braces, parentheses and tilde are excluded from record text even when
quoted or escaped. The inspector does not expand patterns. Ordinary quoting,
split definitions and supported preprocessor forwarding remain valid. The
linker record must select exactly `-L<build.root>/sw/runtime -lvortex`.
These checks resolve the former compiler-glob ambiguity; successful planning
still grants no launch readiness or vendor qualification.

| Result | Exit | Meaning |
|---|---|---|
| `outcome: planned` | `0` | The declared input set passed the implemented consistency checks; a candidate is described |
| `outcome: blocked` | `1` | A prerequisite, identity, contract or resource observation is missing or inconsistent; no candidate is emitted |
| Invalid CLI arguments | `2` | The command was not accepted; use `--help` |

Even a planned result retains `launch_ready: false`,
`vendor_qualification_verified: false`, `execution_performed: false`,
`phase_complete: false` and P01-A03 `acceptance_outcome: blocked`. Hash agreement
does not authenticate a vendor release, producer statement, platform package,
generated numerical behavior or execution. Generated headers are identity-pinned
and screened for external XLEN overrides; they are not regenerated by this
offline tool. Emulation JSON is checked for bounded parseability, without
certifying the vendor-specific schema.

## 4. Review the fixed candidate and budget

The candidate describes these arguments, from the dedicated generated build:

```text
./ci/blackbox.sh --driver=xrt --target=hw_emu --app=demo --args=-n1
```

The explicit target matters: the inherited runner defaults to `xrtsim` and
resets an inherited `TARGET` variable. The candidate sets the frozen one-core,
one-cluster, four-warp, four-thread, issue-width-one STD configuration, declared
vendor/platform/artifact paths and bounded worker settings. It supplies a
controlled environment and requests no ambient environment inheritance. This
environment is a candidate, not a validated site-specific setup; native tools,
vendor library resolution and entitlement still require review.

| Control | Supported declaration |
|---|---|
| Compile workers | One or two; `MAKEFLAGS`, `JOBS`, `MAX_JOBS` and `THREADS` agree |
| Free-disk reserve | At least 15 GiB, checked on every inspected resource root |
| Sampled process-group RSS budget | Positive integer, at most 6 GiB |
| Command timeout | Positive integer, at most 7,200 seconds |
| Retained command log | Positive byte limit, at most 16 MiB |
| Declared artifacts and build-checker inputs | At most 512 MiB across at most 64 files; includes source text inspected for copy consistency |
| Manifest / receipt JSON | At most 256 KiB each |
| Separate source observation | At most 512 MiB of tracked bytes, 32,768 files/links and 32 recursive submodules per observation |

The source observer also has separate identity-text, Git-output and time limits;
the [reader limits](p01-hwemu-manifest.md#5-integer-and-reader-limits) specify
them. Source observations run at both inspection boundaries and do not count
toward the report's declared-input totals. Incomplete or oversized source
observations block a candidate.

The planner **does not enforce execution budgets**. It runs no child workload.
Before any real execution, use a separately reviewed supervisor such as the
existing [bounded process runner](../../ci/project/baseline_process.py), retain
its complete result and account for generated output beyond console logs. Its
limits are sampled budgets, not hard filesystem quotas or a guarantee about
descendants that leave the process group. `MemAvailable` does not establish the
effective container memory limit. A later file change also invalidates the
earlier input observation; stop writers and recheck immediately before use.

The demo is an integer integration smoke. Even successful execution would not
extend the separate accepted floating-point/tensor numerical matrix or qualify
physical FPGA performance.

## 5. Keep tracing an explicit debugging choice

The generated XRT INI now points to the actual source hook at
`sw/runtime/xrt/xsim.tcl`. Its default `debug_mode=off` and disabled legacy
profiling/transfer-trace settings avoid automatic waveform/profiling capture.
Runtime console logging remains enabled.

For an intentional debugging run, budget a separate generated build and output
directory. Select `debug_mode=batch` or `gui` in that build's INI, set
`VORTEX_XRT_WAVEFORM=1`, and satisfy the selected vendor release's debug-build
requirements. The environment variable alone does not override `debug_mode=off`.
Reconfiguring replaces the generated INI with the source default. A debug variant
does not satisfy this planner's lean default contract.

AMD documents the waveform modes and debug-link requirement in the
[Vitis 2025.1 XRT INI reference](https://docs.amd.com/r/2025.1-English/ug1702-vitis-accelerated-reference/xrt.ini-File).
The inherited false/off profiling options are described by the
[XRT 2021.1 reference](https://xilinx.github.io/XRT/2021.1/html/xrt_ini.html).
Some legacy options are deprecated or ignored in later releases; disabled
settings are not a claim that all possible modern instrumentation is controlled.

## Validation and handoff

The source-root test suite uses synthetic vendor files and actual temporary
configuration/Git observations. Synthetic xclbins, releases and receipts are
test fixtures, never acceptance evidence. Tcl tests report an explicit skip if
the interpreter is unavailable; a skip does not verify hook execution.

The Git-scope regressions use owned system/user configurations and real Git to
check isolation while retaining rejection of repository/worktree and included
unsafe settings. Their local pass does not establish hosted CI recovery; the
[handoff](p01-hwemu-handoff.md#publication-record) preserves the original hosted
failure and records later observations separately.

```sh
python3 -m unittest discover -s ci/project -p 'test_hwemu*.py'
python3 -m unittest discover -s ci/project -p 'test_xrt_configuration.py'
python3 ci/project/check_project.py
python3 ci/project/check_baseline_packets.py
```

Before publication, run the full governance discovery required by
[AGENTS.md](../../AGENTS.md), obtain independent review, and record the exact
tested source/tree, commands, failures, omissions and delivery state. Follow the
[handoff template](handoff.example.md); preserve the accepted native and
clean-build packets without altering their claims.

**Next bounded action:** the FPGA-platform owner supplies a qualified vendor
release/platform and actual matching build packet, then the verification owner
reviews the candidate, executes the bounded DMA/launch/completion smoke and
retains its logs and reference result. Keep P01-A03 blocked until that execution
and independent acceptance review are complete. **P02 now proceeds from accepted
P01-A01/A02 evidence** under [ADR-004](decisions.md#adr-004--staged-native-development-entry-with-vendor-integration-retained);
P07 still requires full P01 completion for its own acceptance.
