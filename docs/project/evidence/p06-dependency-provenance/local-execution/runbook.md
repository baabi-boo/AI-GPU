# Local fresh dependency execution and inert replay

This guide operates the [local v1 contract](../../../../designs/local_dependency_execution_v1.md).
Use the [evidence index](../README.md) and
[handoff](../../../p06-dependency-provenance-handoff.md) to select an original
and its review. Commands below are procedures, not claims that another run has
completed. Keep every failed attempt and its successful subpackets unchanged.

The local path records local preparation and execution. It does not invent a
GitHub run, job, artifact or cache-restoration identity. Full replay establishes
retained consistency and reports `native_execution="not_run"` and
`retained_code_executed=false`. Actual execution belongs to the separately
identified producer original.

## 1. Prepare exact, separate inputs

Select an exact reviewed **40-character Git commit**, not a moving branch or
tag. Use a new source checkout for each attempt: successful dependency building
stages products and fetched inputs into that checkout, so a previous execution
checkout is not a fresh input. The outer runner creates its workspace itself;
the workspace must not already exist, and its parent must exist.

Use canonical absolute paths without spaces, traversal or symlink ancestors.
The source checkout, workspace, archive root and dependency-repository root
must be pairwise disjoint. Keep a separate existing directory for shell logs,
archive output and review results. Do not place those files inside the source
checkout or the original `evidence/` directory.

Populate these variables with real paths and the selected revision before
using the examples:

| Variable | Required selection |
| --- | --- |
| `P06_PYTHON` | Absolute Linux CPython **3.12.14** executable, invoked as `python3` |
| `P06_SOURCE_REVISION` | Reviewed execution commit, exactly 40 lowercase hex characters |
| `P06_SOURCE` | New dedicated source-checkout path |
| `P06_WORKSPACE` | New, absent workspace path under an existing parent |
| `P06_ARCHIVE_ROOT` | Existing tree containing the exact locked toolchain parts |
| `P06_DEPENDENCY_REPOSITORIES` | Existing root with `yaml-cpp`, `spdlog` and `argparse` Git repositories |
| `P06_HOST_BIN` | Existing directory selecting the reviewed host-tool aliases |
| `P06_REVIEW_DIRECTORY` | Existing separate directory for logs, ZIPs and review outputs |

For a new checkout of the selected published commit:

```bash
: "${P06_PYTHON:?Set the reviewed CPython 3.12.14 python3 executable}"
: "${P06_SOURCE_REVISION:?Set the exact reviewed execution commit}"
: "${P06_SOURCE:?Set a new absolute source-checkout path}"
git clone --no-checkout https://github.com/baabi-boo/AI-GPU.git "$P06_SOURCE"
git -C "$P06_SOURCE" checkout --detach "$P06_SOURCE_REVISION"
git -C "$P06_SOURCE" submodule update --init --recursive
git -C "$P06_SOURCE" rev-parse HEAD
git -C "$P06_SOURCE" status --short
git -C "$P06_SOURCE" submodule status --recursive
"$P06_PYTHON" --version
```

Check each command's result before continuing. Do not use `submodule --remote`.
The reviewed source has five top-level gitlinks and **eight recursive entries**:
`cocogfx`, `cvfpu`, its `common_cells`, `fpu_div_sqrt_mvp` and `flexfloat`
children, `hardfloat`, `ramulator` and `softfloat`. Every entry must be initialized
at the superproject's recorded commit. Source provenance also rejects dirty,
untracked or hidden index-state changes; a clean-looking short status alone
does not replace the producer's full checks.

### Five pinned dependency trees

The authoritative pins and tree hashes are in
[`p06_dependency_contract.py`](../../../../../ci/project/p06_dependency_contract.py).
The preparation reads two trees from source-checkout gitlinks and three from
the supplied repository root:

| Dependency | Git commit | Repository used by local preparation |
| --- | --- | --- |
| SoftFloat | `b51ef8f3201669b2288104c28546fc72532a1ea4` | `$P06_SOURCE/third_party/softfloat` |
| Ramulator | `e62c84a6f0e06566ba6e182d308434b4532068a5` | `$P06_SOURCE/third_party/ramulator` |
| yaml-cpp | `0579ae3d976091d7d664aa9d2527e0d0cff25763` | `$P06_DEPENDENCY_REPOSITORIES/yaml-cpp` |
| spdlog | `ad0e89cbfb4d0c1ce4d097e134eb7be67baebb36` | `$P06_DEPENDENCY_REPOSITORIES/spdlog` |
| argparse | `997da9255618311d1fcb0135ce86022729d1f1cb` | `$P06_DEPENDENCY_REPOSITORIES/argparse` |

Acquire the latter repositories separately from the URLs in that contract and
retain their exact commit/tree/blob objects. Preparation verifies the actual
Git object bytes, not a copied source directory or repository-name assertion.
Its selected manifest contains 1,294 files / 10,938,128 bytes. It performs no
network acquisition. All three fetched destinations beneath
`third_party/ramulator/ext/` and all three dependency products must be absent
before preparation. It also rejects ignored build residue in the initialized
SoftFloat and Ramulator inputs.

### Locked native toolchain archives

Use the exact paths and identities in
[`p01_toolchain.lock.json`](../../../../../ci/project/p01_toolchain.lock.json),
from `vortexgpgpu/vortex-toolchain-prebuilt` commit
`e3db4bcdf819a17f618ad9fc2472f8f7dea3192b`, bundle `ubuntu/focal`.
The selected components are `riscv64-gnu-toolchain`, `llvm-vortex`, `libc64`
and `libcrt64`: **15 parts / 606,992,434 compressed bytes**. Preserve each
lock-relative path beneath `P06_ARCHIVE_ROOT`; do not concatenate or rename
the parts there. The provisioner streams the ordered parts itself. Verilator
is outside this SimX-only selection.

Do not substitute the current resolution of the historical `v3.0.2` tag.
Preparation checks each selected part's byte count, SHA-256 and Git blob ID,
rechecks while extracting into a fresh workspace tool directory, validates
archive links, and binds eleven selected native tools/libraries to their
archive members. It does not restore a hosted toolchain cache. The separately
budgeted extraction allows at most 4 GiB of regular-file contents, 1 GiB per
member, 50,000 members and 1,800 seconds, while preserving the disk reserve.

### Complete host compiler and build tools

The reviewed local environment used GCC **12.2.0**, Debian package version
`12.2.0-14+deb12u1`, and functional CMake **3.22.6**. The host directory selected
`gcc`, `g++` and `cmake` aliases; `ar`, `ranlib`, `make` and `python3` were
resolved through the sanitized path. Preparation requires all seven tools.
The selected `python3` must be the same executable identity as `P06_PYTHON`.
The child path consists of `P06_HOST_BIN`, the executing interpreter's directory,
`/usr/bin` and `/bin`; an unrelated activated environment is not inherited.

A compiler executable alone is insufficient. The complete reviewed extracted
GCC installation contains these seven matching packages:

| Package | Role |
| --- | --- |
| `cpp-12` | Compiler preprocessing support |
| `gcc-12` | C compiler and support executables |
| `g++-12` | C++ compiler and support executables |
| `gcc-12-base` | Matching base package |
| `libgcc-12-dev` | Compiler support development files |
| `libstdc++-12-dev` | C++ headers and development link |
| `libstdc++6` | Matching shared C++ runtime target |

[Attempt 01](attempt-01.md) omitted the matching runtime: its development
`libstdc++.so` link was dangling, and linking fell back to static archive
members that the provenance contract correctly rejects. The new host root
recorded in [attempt 02](attempt-02.md) supplied the matching runtime without
altering the previous installation or relaxing archive selection. The repaired
host receipt SHA-256 is
`1a205a1d080753490669664c61236a2102176aff1457529415809740ad70f4ce`.
The seven package identities were joined to the signed Debian index, with
three valid InRelease signatures; the retained compile/link/dlopen probe
checked actual shared-library selection.

The matching link-time file is `libstdc++.so.6.0.30`; normal process loading
still uses system runtime libraries. The receipt does not establish complete
host compiler, system-header, runtime or OS provenance. Preserve original
compiler flags and warnings. The local compatibility repair adds no warning
suppression; inherited dependency flags, including yaml-cpp's existing
`-Wno-long-long`, remain inherited flags.

## 2. Inspect resources and execute once

The unchanged inner limits are **two build jobs**, **one simulation worker**,
**15 GiB free-disk reserve**, **4 GiB available memory** and **4 GiB sampled
child process-group RSS**. Configure, build and native-process timeouts are
120, 1,800 and 180 seconds; each command log is bounded at 16 MiB. The enclosing
route has a 90-minute polled deadline. Allow headroom for archives, extracted
tools, retained maps and failed originals before starting.

These are polled budgets, not hard cgroup or filesystem quotas. The outer
monitor does not aggregate child-created process groups into one descendant
RSS ceiling. Sampled RSS may miss peaks and double-count shared pages; bounded
termination and receipt writing can finish after the deadline. Keep these
limitations with the result.

```bash
: "${P06_WORKSPACE:?Set a new absent workspace path}"
: "${P06_ARCHIVE_ROOT:?Set the verified archive root}"
: "${P06_DEPENDENCY_REPOSITORIES:?Set the pinned repository root}"
: "${P06_HOST_BIN:?Set the reviewed host-tool alias directory}"
: "${P06_REVIEW_DIRECTORY:?Set an existing separate review directory}"
test ! -e "$P06_WORKSPACE"
test ! -L "$P06_WORKSPACE"
df -h -- "$P06_SOURCE" "$P06_ARCHIVE_ROOT" "$P06_DEPENDENCY_REPOSITORIES"
free -h
cd "$P06_SOURCE"
"$P06_PYTHON" -B ci/project/p06_dependency_local_execute.py \
  --source-dir "$P06_SOURCE" \
  --workspace-dir "$P06_WORKSPACE" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --archive-root "$P06_ARCHIVE_ROOT" \
  --dependency-repositories "$P06_DEPENDENCY_REPOSITORIES" \
  --host-bin "$P06_HOST_BIN" \
  > "$P06_REVIEW_DIRECTORY/execution.stdout.log" 2>&1
P06_EXECUTION_STATUS=$?
printf '%s\n' "$P06_EXECUTION_STATUS"
```

Use a new review-log filename or directory for each attempt. Record the exact
command, source identity, start/end times and exit code outside the evidence
directory. Do not precreate the execution workspace. Do not invoke the
preparation separately before the enclosing runner or manually run build
recipes in the selected source checkout; the runner creates and configures
the out-of-tree native variants and controls the source-staging sequence.

The five stages run serially in separate interpreters:

| Stage | Required successful observation |
| --- | --- |
| `preparation` | Exact local source/archives/tools; explicit local receipt |
| `dependency-build` | 406 compilations, three archives, two indexes, two shared links; full receipt and staging checks |
| `native-lifetime` | FP16/BF16 × two allocation policies: four processes, 132 launches, 4,224 checked FP32 words |
| `pending-probe` | Separate native pending-read observation and expected rejection of its compiled always-zero control |
| `dependency-substitution` | Separate FP16 reusable process: 33 launches / 1,056 correct words, with original provenance rejected for the alternate dependency |

Only `native-lifetime` contributes to the four-process managed population.
Preserve the controls as separate populations. A failed stage stops the route;
successful earlier subpackets do not turn its enclosing envelope into a pass.
[Attempt 03](attempt-03.md), for example, passed dependency and native stages
but failed when the wrapper parsed the completed native report. Its controls
were unrun. The corrected route requires a fresh complete attempt.

The native report intake has an explicit **500,000 structural-token** ceiling;
the generic parser remains at **250,000**. The two control producers opt in only
through an exact dependency-receipt pin and still validate contract, revision,
population and claims. The 16 MiB managed-report byte bound, 64-level depth,
1,024-character numeric-token bound, duplicate-key rejection and finite-value
checks remain enforced. Do not change shared defaults or truncate a report to
make an attempt pass.

## 3. Preserve the complete original

Wait until `evidence/local-execution.json` has `state="finished"` and no
producer is writing the packet. Preserve failed attempts too. The complete
successful evidence root contains the original preparation, local envelope,
five stage logs, retained orchestrator source and all four dependency/native/
control subdirectories. Include hidden regular files such as
`payloads/.retention.lock`. Do not add review records or a generated manifest
inside the packet, omit unfavorable files, merge attempts or rewrite JSON.

For a newly created local ZIP, place **the contents of `evidence/` at its root**,
using regular-file members. The following data-only recipe rejects symlinks,
special files and multiply linked inputs, hashes all files before and after,
checks every archived member against its original, and writes the ZIP identity
outside the packet. This packages an original; it does not make a failed
envelope successful or authenticate the producer.

```bash
: "${P06_ORIGINAL_ZIP:?Set a new absolute ZIP path outside the workspace}"
export P06_WORKSPACE P06_ORIGINAL_ZIP
"$P06_PYTHON" -B - <<'PY'
import hashlib, json, os, pathlib, stat, zipfile

root = pathlib.Path(os.environ['P06_WORKSPACE']) / 'evidence'
target = pathlib.Path(os.environ['P06_ORIGINAL_ZIP'])
assert root.is_absolute() and root.resolve(strict=True) == root
assert not any(p.is_symlink() for p in (root, *root.parents))
assert target.is_absolute() and target.parent.resolve(strict=True) == target.parent
assert not any(p.is_symlink() for p in target.parents)
assert not target.is_relative_to(root.parent)
assert not os.path.lexists(target)
sidecar = target.with_suffix('.identity.json')
assert not os.path.lexists(sidecar)
assert json.loads((root / 'local-execution.json').read_bytes())['state'] == 'finished'

def inventory():
    rows = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        assert not stat.S_ISLNK(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            continue
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = path.lstat()
        assert (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        rows[path.relative_to(root).as_posix()] = (info.st_size, digest)
    return rows

before = inventory()
with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(before):
        archive.write(root / name, arcname=name)
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert archive.namelist() == sorted(before)
    for name, (size, digest) in before.items():
        info = archive.getinfo(name)
        assert info.file_size == size
        with archive.open(name) as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest
assert inventory() == before
with target.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
identity = {'filename': target.name, 'size_bytes': target.stat().st_size,
            'sha256': digest, 'member_count': len(before),
            'all_members_rehashed_against_original': True,
            'original_rehashed_after_packaging': True, 'zip_crc_verified': True,
            'retained_code_executed': False}
with sidecar.open('x', encoding='utf-8') as stream:
    json.dump(identity, stream, indent=2)
    stream.write('\n')
print(json.dumps(identity, sort_keys=True))
PY
```

Keep the resulting ZIP unchanged after its external identity is recorded.
Compression choices can produce different ZIP hashes for identical members;
the caller pins the **actual ZIP bytes**, not a predicted digest. This archive
contains retained evidence, not the complete host installation, original
toolchain archives or host disk. Retain separately reviewed archive/host
acquisition evidence for claims about those inputs.

## 4. Establish independent pins and run the full local reader

Record the exact original's provenance, filenames, sizes and raw SHA-256
identities in an intake record **outside the packet**. Independently select the
execution revision and expected reports; copying digest fields out of an
unreviewed candidate does not establish external expectations. Stop on a
mismatch. Never replace an expectation solely to make replay pass.

| Variable | Exact original bytes independently pinned |
| --- | --- |
| `P06_ZIP_SHA256` | Complete original ZIP |
| `P06_SOURCE_REVISION` | Original's executed Git commit |
| `P06_LOCAL_EXECUTION_SHA256` | `local-execution.json` |
| `P06_DEPENDENCY_RECEIPT_SHA256` | `dependency-build/report.json` |
| `P06_NATIVE_REPORT_SHA256` | `native-lifetime/report.json` |
| `P06_NATIVE_SOURCE_BEFORE_SHA256` | `native-lifetime/snapshots/source-before.json` |
| `P06_PROBE_REPORT_SHA256` | `pending-probe/report.json` |
| `P06_SUBSTITUTION_REPORT_SHA256` | `dependency-substitution/report.json` |

Every SHA-256 is 64 lowercase hexadecimal characters. In particular,
`--source-manifest-sha256` means the **native snapshot's raw bytes**, not the
semantic dependency-source manifest hash, source plan or Git tree hash.

Use a trusted, recorded reader checkout with the matching reviewed helper
implementation. Do not execute a reader copied out of the candidate archive.
Record its revision, tree and dirty state independently; it may be a later
documentation-only commit with identical relevant helper bytes. Set
`P06_READER_SOURCE` to that checkout and `P06_REPLAY_OUTPUT` to a new JSON file
in an existing directory outside the original workspace. The public reader
creates the output exclusively and preserves an existing file.

```bash
: "${P06_READER_SOURCE:?Set the trusted reader checkout}"
: "${P06_REPLAY_OUTPUT:?Set a new external replay JSON path}"
: "${P06_ZIP_SHA256:?Set the independently recorded ZIP digest}"
: "${P06_LOCAL_EXECUTION_SHA256:?Set the independently recorded envelope digest}"
: "${P06_DEPENDENCY_RECEIPT_SHA256:?Set the independently recorded dependency digest}"
: "${P06_NATIVE_REPORT_SHA256:?Set the independently recorded native report digest}"
: "${P06_NATIVE_SOURCE_BEFORE_SHA256:?Set the independently recorded native snapshot digest}"
: "${P06_PROBE_REPORT_SHA256:?Set the independently recorded pending-probe digest}"
: "${P06_SUBSTITUTION_REPORT_SHA256:?Set the independently recorded substitution digest}"
git -C "$P06_READER_SOURCE" rev-parse HEAD
git -C "$P06_READER_SOURCE" status --short
"$P06_PYTHON" -B "$P06_READER_SOURCE/ci/project/p06_dependency_local_replay.py" \
  "$P06_ORIGINAL_ZIP" \
  --sha256 "$P06_ZIP_SHA256" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --dependency-receipt-sha256 "$P06_DEPENDENCY_RECEIPT_SHA256" \
  --native-report-sha256 "$P06_NATIVE_REPORT_SHA256" \
  --source-manifest-sha256 "$P06_NATIVE_SOURCE_BEFORE_SHA256" \
  --probe-report-sha256 "$P06_PROBE_REPORT_SHA256" \
  --substitution-report-sha256 "$P06_SUBSTITUTION_REPORT_SHA256" \
  --local-execution-sha256 "$P06_LOCAL_EXECUTION_SHA256" \
  --output "$P06_REPLAY_OUTPUT"
P06_REPLAY_STATUS=$?
printf '%s\n' "$P06_REPLAY_STATUS"
```

The ZIP recipe above needs no prefix. If the independently selected original
instead has all evidence under a literal directory such as `evidence/`, add
`--prefix evidence`. Choose the prefix during intake; do not search for a
favorable report. Prefixes cannot contain traversal or leading/trailing slashes.

The full local reader reconstructs dependency, native lifetime and both control
semantics inside one bounded archive context, including its closing integrity
check. It checks the exact local member inventory, source/tool identities,
ordering, command/environment records, terminal outputs and external report
pins. A pass leaves all seven `qualified`, `ready_for_warm`, `warm_execution`,
`full_warm_coverage`, `acceptance_claimed`, `phase_acceptance` and
`performance_acceptance` fields false. Complete counter qualification,
absolute no-wrap reasoning, warm measurement, P06 acceptance and vendor
hardware integration retain their separate obligations.
