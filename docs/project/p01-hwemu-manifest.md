# P01 vendor `hw_emu` manifest contract

The [offline planner](../../ci/project/hwemu.py) reads a local JSON manifest,
checks its declared inputs, and describes one candidate integer smoke command.
It never runs that command. `planned` means **input consistency verified**;
vendor qualification, launch readiness and P01-A03 acceptance remain blocked.
Use the [hw_emu runbook](p01-hwemu-runbook.md) for the operating sequence and
[acceptance policy](acceptance.md) for the separate evidence obligation.

The implementation is authoritative:
[schema](../../ci/project/hwemu_contract.py),
[bounded input reader](../../ci/project/hwemu_io.py),
[source observer](../../ci/project/hwemu_source.py),
[generated-build checks](../../ci/project/hwemu_build.py), and
[planner](../../ci/project/hwemu_plan.py). This guide describes schema version 1.
There are no optional manifest fields or executable command fields.

## 1. Exact fields and frozen scope

Every object must contain exactly its specified keys. Unknown, missing or
duplicate JSON keys are rejected. JSON must be UTF-8 with an object at the top
level; malformed data, nonfinite numbers and excessive nesting are rejected.
Integer fields require JSON integers: `true`, `1.0` and `"1"` do not stand in
for `1`. Object-key order and whitespace do not matter to schema comparison,
but they change a file's byte identity. Array order matters.

| Top-level field | Required value or exact nested fields |
|---|---|
| `schema_version` | Integer `1` |
| `target` | String `"hw_emu"` |
| `source` | `root`, `revision`, `tree` |
| `build` | `root`, `tool_dir`, `xlen`, `profile`, `configs` |
| `vendor` | `vitis`, `vivado`, `xrt`; each contains exactly `root`, `release` |
| `platform` | Exactly `name` |
| `files` | The 11 roles in section 3; each contains `path`, `size_bytes`, `sha256` |
| `generated` | The 20 relative paths in section 4; each contains `size_bytes`, `sha256` |
| `budget` | The six integer fields in section 5 |

`source.revision` and `source.tree` are complete, lowercase, 40-character Git
hexadecimal identities for `HEAD` and `HEAD^{tree}`. A branch, abbreviated hash
or tag cannot replace them. `vendor.*.release` is an inert label of 1–80 ASCII
characters; `platform.name` allows 1–160. Both start with a letter or digit,
then permit letters, digits, `_`, `.`, `+` and `-`. Matching labels do not
authenticate a release or establish platform support. This contract does not
select a vendor release for the operator.

`build.xlen` is integer `64`, `build.profile` is the empty string, and
`build.configs` must equal this list in this order, without additions:

```json
[
  "-DVX_CFG_NUM_CLUSTERS=1",
  "-DVX_CFG_NUM_CORES=1",
  "-DVX_CFG_NUM_WARPS=4",
  "-DVX_CFG_NUM_THREADS=4",
  "-DVX_CFG_ISSUE_WIDTH=1",
  "-DVX_CFG_FPU_TYPE_STD"
]
```

The candidate uses the generated build's `./ci/blackbox.sh` with
`--driver=xrt --target=hw_emu --app=demo --args=-n1`. This integer integration
smoke does not qualify tensor numerics. The planner rejects `xrtsim` selectors
in the relevant compiler/linker stamps; the local vendor-free shim cannot
substitute for the vendor path.

## 2. Paths, source state and directory separation

All roots, file-role paths and the CLI's manifest path must be canonical
absolute POSIX paths. Use only ASCII letters, digits, `_`, `.`, `+`, `-` and
the `/` separator. No spaces, shell syntax, backslashes, control characters,
Unicode, repeated separators, trailing separator, `.` or `..` components are
accepted. `/` alone is not an input path. These declared paths are at most
4,096 characters; filesystem inspection also limits them to 128 components
and 255 characters per component.

Every declared file, generated input and source text read by the build checker
must be an existing regular file. Every ancestor must be a real directory,
with no symlink at any point, including the leaf. The reader uses
descriptor-based no-follow access and checks for replacement or mutation; it
does not silently resolve a link into an accepted path. This applies even to
a conventional vendor launcher or library symlink. Tracked source symlink
entries have the separate observation rule below; they do not relax the
declared-file contract. If an installation cannot meet the path contract,
retain the blocker and review the installation layout rather than editing a
vendor tree just to satisfy the planner.

Directory relationships are explicit:

- `build.root` cannot equal `source.root` or contain the source checkout.
  A build inside the source checkout must be a direct child whose name starts
  with `build`, such as `/work/source/build64-hwemu`; deeper nesting is rejected.
  A separate sibling build is also permitted.
- `build.tool_dir` identifies the native Vortex tool directory. It must be
  separate from both source and build: no equality or ancestor/descendant
  relationship with either. It is distinct from the three vendor-root labels.
- File-role paths must be mutually distinct, and none may equal a required
  generated path under `build.root`. The planner does not inventory a complete
  vendor installation, platform package or native tool directory.

The source must be the Git checkout root, at the declared revision and tree,
with no tracked changes or nonignored untracked inputs. The observer compares
the index's paths, modes and object IDs with `HEAD`, then hashes each tracked
regular file's raw bytes using Git's blob format and compares its executable
mode with the index. A tracked symlink is checked by hashing the link text
itself and checking its Git link mode; its target is never followed or
qualified. Ancestor symlinks cannot be used to reach a tracked member. Required
recursive submodules must be initialized at their recorded gitlink revisions,
with declarations matching the tree and the same clean-source checks applied
recursively. Missing, changed or conflicted modules block planning.

Before accepting source contents, the observer requires all **19 distinct
source paths consumed by the inspector** to be regular blobs in both `HEAD`
and the index, with Git mode `100644` or `100755`. This set is the deduplicated
union of the eight `SOURCE_INPUTS` in
[`baseline_inventory.py`](../../ci/project/baseline_inventory.py), the 13
source-side values of `COPIED_INPUTS` in
[`hwemu_build.py`](../../ci/project/hwemu_build.py), and
`sw/runtime/xrt/xsim.tcl`. An ignored or untracked on-disk copy, a staged-only
addition, a symlink or a gitlink cannot satisfy this requirement. The raw
worktree checks bind these files' bytes and modes to their recorded blobs.
This is the inspector's consumed input set; it does not cover every build
dependency.

Only fixed local Git metadata queries run: `config`, `rev-parse`, `ls-files`
and `ls-tree`. The observer does not use `git status`, a submodule helper or a
checkout/conversion command. It disables Git's filesystem monitor, untracked
cache, optional locks, replacement objects and lazy object fetches, and rejects
configured `filter.*.clean`/`filter.*.process`, partial-clone or promisor
settings. Checkout conversions are not applied to the raw-byte comparison.
Line-ending, encoding or other normalized checkouts whose bytes differ from
the recorded blobs cannot qualify. Hidden index entries, including
assume-unchanged and skip-worktree entries, and sparse index representations
are unsupported; a Git status display that looks clean is insufficient.

Nonignored untracked paths block the source check. Ignored untracked contents
are outside that cleanliness observation; passing it does not inventory or
qualify those contents. An ignored build directory does not excuse a modified
tracked source file, and any ignored file explicitly declared in the manifest
still undergoes its required identity and content checks. Source provenance is
observed before and after planning inspection and must remain consistent.
Keep manifests, receipts and capture-helper scripts outside the source checkout
unless their placement already meets its clean-state requirement. The source
observer's separate limits are listed in section 5.

## 3. File identities and roles

Each `files` entry has exactly this shape:

```json
{"path": "/absolute/retained/input", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"}
```

This illustration is deliberately invalid. Replace the size with the actual
positive integer byte count and the digest with the SHA-256 of the exact
retained bytes, represented as 64 lowercase hexadecimal characters. Neither
zero-filled hashes nor guessed sizes establish identity.

| Role | Required path binding and meaning |
|---|---|
| `vpp` | Exactly `vendor.vitis.root` + `/bin/v++` |
| `vivado` | Exactly `vendor.vivado.root` + `/bin/vivado` |
| `emconfigutil` | Exactly `vendor.vitis.root` + `/bin/emconfigutil` |
| `platforminfo` | Exactly `vendor.vitis.root` + `/bin/platforminfo` |
| `xrt_header` | A descendant file of `vendor.xrt.root` + `/include/` |
| `xrt_library` | Directly under `vendor.xrt.root` + `/lib/`, named `libxrt_coreutil.so` or that name followed by one or more numeric dot suffixes; no `lib64/` substitution |
| `platform` | Descriptor basename exactly `platform.name` + `.xpfm` |
| `xclbin` | Basename exactly `vortex_afu.xclbin` |
| `emconfig` | Basename exactly `emconfig.json`, in the same directory as `xclbin` |
| `build_receipt` | The retained declaration receipt described in section 6 |
| `xsim_hook` | Exactly `source.root` + `/sw/runtime/xrt/xsim.tcl` |

File identity checks do not execute tools, inspect executable behavior,
authenticate a vendor distribution, validate an `.xpfm` dependency closure,
decode an `.xclbin`, or establish artifact/platform compatibility. `emconfig`
is checked as a bounded, nonempty JSON object; its vendor-specific schema and
meaning remain unverified.

## 4. Generated inputs and content checks

`generated` requires exactly these 20 keys. Each value contains only
`size_bytes` and `sha256`; its absolute path is `build.root` + `/` + the key.

| Generated key | Additional content check |
|---|---|
| `.config.stamp` | Exact configure bindings described below |
| `config.mk` | Source `config.mk.in` after the required substitutions |
| `sw/VX_config.h` | Nonempty text, no NUL or external XLEN override |
| `sw/VX_types.h` | Same header screening |
| `hw/VX_config.vh` | Same header screening |
| `hw/VX_types.vh` | Same header screening |
| `ci/blackbox.sh` | Exact source text |
| `ci/gen_config.py` | Exact source text |
| `sw/kernel/Makefile` | Exact source text |
| `sw/runtime/stub/Makefile` | Exact source text |
| `sw/runtime/common.mk` | Exact source text |
| `sw/runtime/xrt/Makefile` | Exact source text |
| `sw/runtime/xrt/xrt.ini` | Source `.in` substitution and strict lean settings |
| `sw/runtime/xrt_config.stamp` | One compiler record with the frozen RV64 configuration |
| `tests/regression/demo/Makefile` | Exact source text |
| `tests/regression/demo/config.stamp` | Three records: kernel flags, host flags, linker flags |
| `tests/regression/common.mk` | Exact source text |
| `hw/syn/xilinx/xrt/Makefile` | Exact source text |
| `hw/syn/xilinx/common.mk` | Exact source text |
| `hw/syn/xilinx/platform.mk` | Exact source text |

The configure stamp must have exactly `XLEN`, `TOOLDIR`, `OSVERSION`, `PREFIX`,
`PROFILE`, `SOURCE_DIR`, `BUILDDIR`, `VORTEX_VERSION`, `TOOLCHAIN_REV`, `GEM5_REV`
and `FIRESIM_REV`, without duplicate fields. Values bind XLEN to `64`, OSVERSION
to `ubuntu/focal`, PROFILE to empty, PREFIX to `build.root` + `/install`, source,
build and tool paths to the manifest, and all four pins to the source `VERSION`.
Unresolved template substitutions are rejected.

Compiler stamps must establish the frozen flags plus `VX_CFG_XLEN=64` and
`VX_CFG_XLEN_64=1`, without conflicting XLEN or nonnative scalar/tensor
selectors. This check does not authenticate a compiler or prove that it ran.
The kernel record additionally requires exactly one effective direct
`-march=rv64imafd` and `-mabi=lp64d`. Missing, repeated, conflicting or consumed
options cannot qualify the target; preprocessor streams cannot establish driver
ISA/ABI selections. Free source operands and unsupported compiler transports
are rejected in that record. Shell operators (`;`, `&`, `|`, `<`, `>`) and
expansion syntax (dollar signs and backticks) are unsupported throughout
compiler records, including quoted or escaped literals.

The inspector does not evaluate glob expansion against a compilation directory.
Unquoted glob characters in unusual hand-written operands remain a tracked
[review follow-up](backlog.md); use retained producer records and independently
review the effective invocation before any separately supervised execution.
Host/runtime records do not require kernel ISA/ABI options.
The demo linker record must normalize to exactly two shell words, in order:
`-L` concatenated with `build.root` + `/sw/runtime` as one word, then `-lvortex`.
Quoting those same words is allowed; extra library paths, linker scripts,
plugins or other flags are rejected for this bounded smoke. This is the
planner's contract, not a change to the inherited Makefile's general options.
The INI requires exactly the Runtime, Emulation and Debug sections: console
runtime logging, debug mode off, the declared source `xsim.tcl` hook, profile
and timeline trace false, and data-transfer trace off. Defaults or extra
settings are rejected.

The four headers are hashed and screened, **not regenerated** by this planner.
Matching source copies, stamps and header identities do not prove which inputs
produced a binary, successful vendor compilation, or numerical correctness.

## 5. Integer and reader limits

Bounds are inclusive. A byte is an actual file byte, not a JSON character;
MiB means 1,048,576 bytes and GiB means 1,073,741,824 bytes.

| Field or reader limit | Supported range or cap |
|---|---|
| Every declared `size_bytes` | 1–536,870,912 bytes (512 MiB) |
| `files.build_receipt.size_bytes` | Further capped at 262,144 bytes (256 KiB) |
| Manifest JSON file | At most 262,144 bytes, read in a separate one-file budget |
| `budget.jobs` | 1–2 |
| `budget.timeout_seconds` | 1–7,200 |
| `budget.min_free_bytes` | 16,106,127,360–1,099,511,627,776 (15–1,024 GiB) |
| `budget.max_rss_bytes` | 1–6,442,450,944 (6 GiB) |
| `budget.max_log_bytes` | 1–16,777,216 (16 MiB) |
| `budget.max_input_bytes` | 1–536,870,912 (512 MiB) |
| Declared artifacts and build-checker input set | At most 64 distinct paths; shared `max_input_bytes` accounting |
| General text / JSON reads | At most 1 MiB / 256 KiB per read |
| Source observer tracked bytes | At most 512 MiB across the checkout and recursive submodules, including tracked link text |
| Source observer tracked entries | At most 32,768 files/links across observed worktrees; each index/tree listing also has a 32,768-entry cap |
| Source observer recursive submodules | At most 32 |
| Source observer identity text | At most 1 MiB per file, 8 MiB total and 64 distinct paths |
| Source observer Git probes | At most 1 MiB of output and 10 seconds per probe, within a 30-second observation deadline |

The sum of all 11 file-role sizes and all 20 generated sizes must fit
`max_input_bytes`. Actual inspection also charges source text read by the
build checker against the shared budget; allow space for those inputs.
Repeated reads of an unchanged path count once. The source `VERSION`, configure
stamp and XRT INI each have a 16 KiB text cap; the two compiler-stamp files each
have a 64 KiB cap. JSON parsing additionally bounds nesting to 64, structural
tokens to 250,000 and number-token length to 1,024 characters.

Each source observation has its own budgets, separate from the manifest reader
and the declared artifact/build-checker input set. Its identity-text budget
covers the fixed source inputs plus inspected `.git` files and recursive
`.gitmodules` declarations. The planner performs an initial and a final source
observation; these reads are not included in `checked_input_count` or
`checked_input_bytes`. An exceeded bound or incomplete observation blocks the
candidate rather than establishing clean source state.

The planner samples free disk for declared directories and requires the stated
reserve at the initial and final observations. Available host memory must be
known and at least `max_rss_bytes`; the effective cgroup limit remains unknown.
Jobs, timeout, RSS and log limits describe the candidate's budget. **They are
not enforced execution limits:** no process is launched and a separate bounded
supervisor is required before any future execution.

## 6. Receipt structure without a self-hash

The receipt is an independent retained JSON file. It has exactly these
top-level keys:

```text
schema_version, target, source, build, vendor, platform, files, generated
```

Its declarations must equal the manifest with two omissions: the top-level
`budget` object and the `files.build_receipt` entry. All other objects, paths,
sizes, hashes and ordered flags must match. There is no self-hash inside the
receipt, avoiding a recursive byte-identity requirement. The manifest alone
records the receipt's actual path, length and SHA-256. Receipt reformatting
therefore requires a new manifest identity even when the parsed declarations
remain equal. Extra approval, timestamp, execution-status or qualification
fields are rejected; preserve actual production logs as separate provenance.

The actual artifact producer should retain this declaration receipt with the
build's commands, exits, tool identities and logs when producing the artifacts.
Hash that retained receipt when authoring the manifest. Do not reconstruct a
matching receipt later and present it as proof that a build or workload ran.
This unsigned consistency format does not authenticate its author, establish
creation time, or prove production history. A matching receipt is an assertion
whose independent provenance still needs review.

## 7. Full structural example — deliberately invalid

Every `INVALID_PLACEHOLDER` must be replaced from actual retained observations.
The hash and size placeholders below fail schema validation; the example is
not a qualified release, usable platform, completed build or runnable plan.
The budget illustrates the permitted upper execution bounds and minimum disk
reserve, not a prediction of an installation's needs.

```json
{
  "schema_version": 1,
  "target": "hw_emu",
  "source": {
    "root": "/INVALID_PLACEHOLDER/source",
    "revision": "INVALID_PLACEHOLDER_REVISION",
    "tree": "INVALID_PLACEHOLDER_TREE"
  },
  "build": {
    "root": "/INVALID_PLACEHOLDER/build64",
    "tool_dir": "/INVALID_PLACEHOLDER/native-tools",
    "xlen": 64,
    "profile": "",
    "configs": [
      "-DVX_CFG_NUM_CLUSTERS=1",
      "-DVX_CFG_NUM_CORES=1",
      "-DVX_CFG_NUM_WARPS=4",
      "-DVX_CFG_NUM_THREADS=4",
      "-DVX_CFG_ISSUE_WIDTH=1",
      "-DVX_CFG_FPU_TYPE_STD"
    ]
  },
  "vendor": {
    "vitis": {"root": "/INVALID_PLACEHOLDER/vitis", "release": "INVALID_PLACEHOLDER"},
    "vivado": {"root": "/INVALID_PLACEHOLDER/vivado", "release": "INVALID_PLACEHOLDER"},
    "xrt": {"root": "/INVALID_PLACEHOLDER/xrt", "release": "INVALID_PLACEHOLDER"}
  },
  "platform": {"name": "INVALID_PLACEHOLDER"},
  "files": {
    "vpp": {"path": "/INVALID_PLACEHOLDER/vitis/bin/v++", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "vivado": {"path": "/INVALID_PLACEHOLDER/vivado/bin/vivado", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "emconfigutil": {"path": "/INVALID_PLACEHOLDER/vitis/bin/emconfigutil", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "platforminfo": {"path": "/INVALID_PLACEHOLDER/vitis/bin/platforminfo", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "xrt_header": {"path": "/INVALID_PLACEHOLDER/xrt/include/INVALID_PLACEHOLDER.h", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "xrt_library": {"path": "/INVALID_PLACEHOLDER/xrt/lib/libxrt_coreutil.so", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "platform": {"path": "/INVALID_PLACEHOLDER/platform/INVALID_PLACEHOLDER.xpfm", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "xclbin": {"path": "/INVALID_PLACEHOLDER/artifacts/vortex_afu.xclbin", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "emconfig": {"path": "/INVALID_PLACEHOLDER/artifacts/emconfig.json", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "build_receipt": {"path": "/INVALID_PLACEHOLDER/provenance/build-receipt.json", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "xsim_hook": {"path": "/INVALID_PLACEHOLDER/source/sw/runtime/xrt/xsim.tcl", "size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"}
  },
  "generated": {
    ".config.stamp": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "config.mk": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/VX_config.h": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/VX_types.h": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "hw/VX_config.vh": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "hw/VX_types.vh": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "ci/blackbox.sh": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "ci/gen_config.py": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/kernel/Makefile": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/runtime/stub/Makefile": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/runtime/common.mk": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/runtime/xrt/Makefile": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/runtime/xrt/xrt.ini": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "sw/runtime/xrt_config.stamp": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "tests/regression/demo/Makefile": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "tests/regression/demo/config.stamp": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "tests/regression/common.mk": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "hw/syn/xilinx/xrt/Makefile": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "hw/syn/xilinx/common.mk": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"},
    "hw/syn/xilinx/platform.mk": {"size_bytes": "INVALID_PLACEHOLDER_BYTES", "sha256": "INVALID_PLACEHOLDER_SHA256"}
  },
  "budget": {
    "jobs": 2,
    "timeout_seconds": 7200,
    "min_free_bytes": 16106127360,
    "max_rss_bytes": 6442450944,
    "max_log_bytes": 16777216,
    "max_input_bytes": 536870912
  }
}
```

## 8. Capture real identities with bounded streaming

This Python standard-library helper prints one identity without loading the
whole artifact or executing it. Save it outside the clean source checkout and
pass one actual canonical absolute path as its argument. It requires POSIX
no-follow facilities, opens ancestors without following links, limits reads to
512 MiB, and rejects a changed or replaced input during capture. For a
`generated` entry, retain only `size_bytes` and `sha256` from its output.

```python
import hashlib
import json
import os
import re
import stat
import sys


def identity(path):
    if (os.name != "posix" or not all(hasattr(os, flag) for flag in
            ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK"))
            or os.open not in os.supports_dir_fd
            or os.stat not in os.supports_dir_fd
            or os.stat not in os.supports_follow_symlinks):
        raise ValueError("no-follow access is unavailable")
    if (type(path) is not str or len(path) > 4096
            or re.fullmatch(r"/[A-Za-z0-9_./+\-]+", path) is None):
        raise ValueError("use a canonical absolute ASCII path")
    parts = path[1:].split("/")
    if len(parts) > 128 or any(p in ("", ".", "..") or len(p) > 255 for p in parts):
        raise ValueError("invalid path component")

    def inode(info):
        return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)

    def state(info):
        return (inode(info), info.st_mode, info.st_nlink, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptors, links = [], []
    try:
        parent = os.open("/", flags | os.O_DIRECTORY)
        descriptors.append(parent)
        for part in parts[:-1]:
            before = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ValueError("ancestor is not a real directory")
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent)
            descriptors.append(child)
            if inode(before) != inode(os.fstat(child)):
                raise ValueError("directory changed during capture")
            links.append((parent, part, child, inode(before)))
            parent = child
        before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= 512 * 1024**2:
            raise ValueError("input must be a nonempty bounded regular file")
        descriptor = os.open(parts[-1], flags, dir_fd=parent)
        descriptors.append(descriptor)
        initial = os.fstat(descriptor)
        if state(initial) != state(before):
            raise ValueError("input changed while opening")
        digest, size = hashlib.sha256(), 0
        while chunk := os.read(descriptor, min(65536, initial.st_size - size + 1)):
            size += len(chunk)
            if size > initial.st_size:
                raise ValueError("input grew during capture")
            digest.update(chunk)
        named = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if (size != initial.st_size or state(os.fstat(descriptor)) != state(initial)
                or state(named) != state(initial)):
            raise ValueError("input changed during capture")
        for parent_fd, name, child_fd, expected in links:
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if inode(named) != expected or inode(os.fstat(child_fd)) != expected:
                raise ValueError("directory changed during capture")
        return {"path": path, "size_bytes": size, "sha256": digest.hexdigest()}
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


if __name__ == "__main__":
    print(json.dumps(identity(sys.argv[1]), indent=2))
```

A captured digest observes bytes at that time. It cannot prevent a later
writer or prove that a tool produced an artifact; the planner independently
rechecks its inputs. Keep the producer's receipt and production logs intact.
Never use [synthetic fixtures](../../ci/project/hwemu_fixture.py), test-created
stamps, mock releases or fabricated artifact files as accepted vendor or GPU
execution evidence. Such fixtures exercise only the inspection tooling, even
when a test obtains a `planned` report.

## 9. Invoke and interpret the CLI

Run from the instrumentation source root, substituting the actual manifest
path. The command reads inputs and prints a report; it writes no output files
and has no `run` command.

```sh
python3 ci/project/hwemu.py plan /absolute/retained/hwemu-manifest.json --json
```

| Exit status | Meaning |
|---|---|
| `0` | `plan` returned `outcome: "planned"`, with a candidate and `input_consistency_verified: true` |
| `1` | Inputs, provenance or resources are blocked; no candidate is exposed. `inventory` always reports blocked and exits 1 because it cannot qualify a candidate |
| `2` | CLI argument error, such as an unknown command or missing manifest argument |

Even at exit 0, `execution_performed`, `phase_complete`, `launch_ready` and
`vendor_qualification_verified` are false; `vendor_qualification` is
`"unverified"`, and `acceptance_outcome` for `P01-A03` is `"blocked"`.
The report's candidate has `inherit_environment: false` and
`supervision_required: true`. Review its explicit environment and remaining
limitations; a hash check does not supply missing site-specific vendor setup,
license entitlement, library dependencies or a qualified platform.

Local Git/source and resource observations occur, but no vendor binary, setup
script, license server, network request, build or workload is invoked. Do not
pipe candidate JSON into a shell or turn an exit-0 plan into a passing execution
record. Follow the [runbook](p01-hwemu-runbook.md) to resolve prerequisites and
retain separately reviewed DMA, launch, completion and reference evidence.
