# P01 compiler-record validation

The shared [compiler-record validator](../../ci/project/compiler_records.py)
checks the recorded configuration of the fixed RV64 vendor smoke. Both the
[read-only build inspector](../../ci/project/hwemu_build.py) and the
[XRT execution inventory](../../ci/project/xrt_inventory.py) use this contract.
Their manifest and receipt schemas remain separate; sharing this check does
not convert a preparation candidate into an execution input.

The validator addresses three concrete ambiguities. A pathname pattern such as
`-I*` can expand to a file named `-I`, causing the compiler to consume the next
apparent definition as an include path. A literal `-I -DNAME=value` has the same
operand-consumption issue. Combining flags from different compilation records
can also invent configuration coverage that no individual invocation supplied.
Inspection now preserves argument and record boundaries before crediting flags.

## Record layout

The [runtime recipe](../../sw/runtime/xrt/Makefile) and
[application recipe](../../tests/regression/common.mk) produce these records:

| Stamp, relative to the generated build | Nonempty records, in order |
|---|---|
| `sw/runtime/xrt_config.stamp` | Runtime host compiler flags |
| `tests/regression/demo/config.stamp` | Kernel compiler flags; application host compiler flags; application linker flags |

Only LF separates records. Spaces, tabs and blank lines are allowed; CRLF,
bare CR, other unsupported controls and Unicode whitespace separators are
rejected. The runtime requires one nonempty record and the application requires
exactly three. A missing, reordered or additional record cannot be replaced by
an aggregate list of flags. Callers read bounded UTF-8 text; malformed bytes
cannot establish a valid record.

## Configuration in every compilation record

The runtime, kernel and application host records must each establish these
effective definitions independently:

| Macro | Required value |
|---|---|
| `VX_CFG_NUM_CLUSTERS` | `1` |
| `VX_CFG_NUM_CORES` | `1` |
| `VX_CFG_NUM_WARPS` | `4` |
| `VX_CFG_NUM_THREADS` | `4` |
| `VX_CFG_ISSUE_WIDTH` | `1` |
| `VX_CFG_FPU_TYPE_STD` | `1` |
| `VX_CFG_XLEN` | `64` |
| `VX_CFG_XLEN_64` | `1` |

The generated recipes also emit resolved configuration definitions. The check
therefore permits additional supported definitions and repeated identical
definitions. Conflicting definitions, protected configuration undefinitions,
other XLEN selectors, vendor-free shim references and nonnative arithmetic
selectors are rejected. A bare `-DNAME` means `NAME=1`; an explicitly empty
value does not satisfy a required value of `1`.

Ordinary quoting, split definitions and supported preprocessor forwarding are
accepted. These are equivalent **fragments**, each supplying only the cluster
definition; a complete record still needs the remaining configuration:

```text
-DVX_CFG_NUM_CLUSTERS=1
-D VX_CFG_NUM_CLUSTERS=1
'-DVX_CFG_NUM_CLUSTERS=1'
-Wp,-D,VX_CFG_NUM_CLUSTERS=1
-Xpreprocessor -DVX_CFG_NUM_CLUSTERS=1
```

Include and dependency-output options consume their operands before macro
interpretation. For example, `-I -DVX_CFG_NUM_CLUSTERS=1` supplies an include
directory, so it cannot supply the required cluster definition. Forwarded
preprocessor arguments have their own operand stream and cannot consume or
establish driver architecture selections.

## Kernel architecture and linker binding

The kernel record must contain one direct `-march=rv64imafd` and one direct
`-mabi=lp64d`. Missing, repeated, conflicting, consumed or forwarded selections
are rejected. The host and runtime records do not accept these kernel
architecture selections. Merely recording RV64 macro definitions does not
establish the kernel ISA or ABI.

The application linker record must parse to exactly:

```text
-L<build>/sw/runtime -lvortex
```

Here `<build>` means the caller's concrete generated-build path. Additional
libraries, search directories, source operands or substituted runtime paths
fail this binding check.

## Deliberately restricted syntax

The validator interprets inert compiler flag records and never executes them,
expands patterns or consults matching filenames. The following raw characters
are rejected, including when quoted or escaped:

```text
; & | < > $ ` * ? [ ] { } ( ) ~
```

This conservative rule excludes otherwise literal filenames or macro values
containing those characters. Inline comment syntax is unsupported. Response
files, Verilator/Make flag transports such as `-CFLAGS` and `-MAKEFLAGS`, unknown
options and free source/object operands are also rejected in every compilation
role. The accepted option set is explicit in the validator. Extend it only
with an argument-semantics review and tests against the actual producer; do not
infer an unknown option's operand count.

## Execution and retained evidence

The XRT inventory retains each readable stamp's original-byte identity even
when its contents fail validation. Any blocker leaves `native_flags_verified`
false. The [runner](../../ci/project/xrt_baseline.py) checks the effective
records before launching the smoke. A failure preserves a failed report and
leaves the integration workload unrun. It checks again after the smoke and
compares the observations; altered or invalid records prevent success even
when the synthetic or real command's reference markers passed.

The runner snapshots `compiler_records.py` and its local dependencies:
`baseline_packet_contract.py`, `baseline_matrix.py` and `baseline_packet_io.py`.
Existing source and retained-copy identity checks cover these helpers. The
historical packet parser and previously accepted evidence keep their original
semantics and bytes.

These hashes provide source inventory and drift detection. They do not
authenticate stamp production, prove which inputs produced a binary, or attest
the interpreter, loaded code objects, standard library or bytecode caches.
Disabling Python bytecode writes does not disable reads from existing caches.
Independent review must retain those limits when assessing a vendor packet.

## Verification and remaining gate

The tests combine a real host-preprocessor oracle, fresh generated Make stamp
recipes, file-backed invalid inputs, runner launch boundaries and helper-copy
drift checks. The generated-stamp test suppresses the unrelated `.depend`
remake and fails any unexpected compiler invocation. Orchestration tests use
explicitly inert command fixtures. A skip for an unavailable compatible
preprocessor or Make/configure capability remains an unverified check.

Run the source-root tooling suite using:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py'
```

Exact tested revisions and outcomes belong in the current [status](status.md)
and continuation evidence. These checks supply no vendor-emulation or physical
hardware result. **P01-A03 remains blocked** until a qualified vendor
environment, platform and matching producer packet support an independently
reviewed DMA/launch/completion smoke through the
[XRT integration procedure](p01-xrt-integration.md). The
[roadmap](roadmap.json) and [acceptance policy](acceptance.md) remain authoritative.
