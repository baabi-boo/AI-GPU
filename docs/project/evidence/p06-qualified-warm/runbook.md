# Fresh qualified warm experiment and complete inert replay

This procedure operates the [qualified warm-workspace v1 contract](../../../designs/qualified_warm_workspace_v1.md). It composes three explicit stages from one reviewed checkout:

1. `p06_dependency_local_prepare.py` prepares the pinned local inputs.
2. `p06_dependency_build.py` compiles fresh dependency products and retains their provenance.
3. `p06_qualified_warm_execute.py run` admits the separately pinned caller extension and original prerequisites before building and launching the full 24-process matrix.

These instructions are a procedure, not a completed execution claim. The original route review is scoped to `c0b44ce64665fe11895f869eea8c38c9b820d6f7`; select and record the exact reviewed published execution revision independently. The [governance audit](../../governance-readiness-audit.md) verifies a full strict pass at `e8e73347ba598c9cd0ceed353148163721b7603d`: [run 45422819749](https://github.com/baabi-boo/AI-GPU/actions/runs/45422819749), 4,812 canonical tests, 36,821 subtests, zero failures/errors/skips and stable source/interpreter/environment. That pass qualifies only its exact revision. The automation is implemented with source-scoped focused validation in the [tooling evidence packet](../p06-hosted-warm-automation/README.md); verify its published revision's own full strict result from the exact Actions run.

For the manual hosted route, use the [hosted operator guide](../../p06-hosted-warm-guide.md) and [automation contract](../../../designs/qualified_warm_automation_v1.md). The next operational action is private control URL/public recipient configuration, verification of the exact published revision's full strict Actions result, and one complete admitted attempt. The workflow accepts no revision input, selects trusted `master` at its provider SHA and requires a successful full governance run for that exact SHA. The steps below retain the existing direct local composition and independent replay commands.

The exact control original has been recovered unchanged: **47,632,218 bytes**, SHA-256 `d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`. Retained Micron verification sources under Ramulator carry proprietary/confidential notices. This original and fresh full dependency packets are not cleared for public redistribution. Keep raw prerequisite archives, source copies, native reports, partial attempts and logs private. Public Actions upload is restricted to encrypted retention and its minimal encryption summary.

Preserve exact source, inputs, logs and outcome for each attempt. A complete native original and independent replay establish the recorded 24-process experiment's validity. The frozen performance predicates may be satisfied or not satisfied. Neither outcome establishes performance acceptance, P06-A02/A03, vendor integration or physical hardware qualification.

The historical four-process route and blocked historical warm-v1 route remain separate. Explicitly select the new producer and reader below; do not alter an old packet or rely on its self-reported metadata to choose a reader. The original qualification proof and both original prerequisite ZIPs retain their original identities and scope. Historical prerequisite projection and the current one-file caller extension are validated separately.

The historical `p06_dependency_local_execute.py` is a separate five-stage contract. Do not use it to select this new route or rewrite one of its originals into this format. Its workspace-creation rule and original-archive layout differ from the direct stages below. The earlier pending-read and alternate-library controls remain independently pinned historical prerequisites; this procedure does not count them as new executions.

## 1. Select and freeze inputs

Use one new, dedicated source checkout at an exact reviewed **published 40-character commit** containing the qualified warm implementation. Start with a clean checkout and all **eight recursive submodules** initialized at their recorded gitlinks. All three stages must execute scripts from that same checkout and use the same revision. Dependency building legitimately stages products and fetched sources into it; do not reuse that populated checkout for another fresh attempt.

Use canonical absolute paths without spaces, traversal or symlink ancestors. The source checkout, execution workspace, toolchain archive root and dependency repository root must be pairwise disjoint. The review directory and final ZIP must be outside the source and execution workspace. The workspace must already exist for these direct preparation/build entry points, but all stage destinations must be fresh.

| Variable | Required selection |
| --- | --- |
| `P06_PYTHON` | Absolute executable named `python3`, reviewed Linux CPython **3.12.14** |
| `P06_SOURCE_REVISION` | Exact reviewed execution commit, 40 lowercase hexadecimal characters |
| `P06_SOURCE` | New dedicated checkout of that commit, including all eight recursive submodules |
| `P06_WORKSPACE` | New owned directory under an existing parent; create it once below |
| `P06_ARCHIVE_ROOT` | Exact locked toolchain archive parts in their original lock-relative paths |
| `P06_DEPENDENCY_REPOSITORIES` | Existing pinned Git repositories for `yaml-cpp`, `spdlog` and `argparse` |
| `P06_HOST_BIN` | Reviewed host-tool alias directory |
| `P06_DIAGNOSTIC_ARCHIVE` | Complete original diagnostic ZIP selected by the frozen proof |
| `P06_CONTROL_ARCHIVE` | Complete original local attempt-04 ZIP selected by the frozen proof |
| `P06_REVIEW_DIRECTORY` | New or empty existing owned directory for external invocation logs and review results |

The [earlier local input guide](../p06-dependency-provenance/local-execution/runbook.md#1-prepare-exact-separate-inputs) specifies the unchanged five dependency commits/trees, fifteen toolchain archive parts, complete host compiler installation and acquisition evidence. Preparation verifies the **15 parts / 606,992,434 compressed bytes**, source Git objects, native tools and all selected host tools. The new route does not substitute a moving tag, restored dependency cache, copied source tree or downloaded replacement. Verilator is outside this SimX-only selection.

The earlier reviewed host setup observed GCC **12.2.0** with matching compiler support, C++ headers and shared runtime. That observed version is not a frozen GCC minor-version constraint. The new Ubuntu 24.04 hosted route selects GCC/G++ 12 and must retain its actual exact package, compiler, support-file and shared-runtime identities. CPython **3.12.14** and CMake **3.22.6** remain fixed for the native route. An executable alone is not the complete host toolchain. The selected `python3` found through the sanitized path must have the executing interpreter's identity.

The immutable source and prerequisite pins are:

| Input | SHA-256 |
| --- | --- |
| Current `ci/project/p06_qualified_warm_proof.json` (passed to the new CLI) | `172721c671ddaa79541dde9c37c154b5ab5a99b8abb0caabf2e07036dd429efb` |
| `ci/project/p06_counter_qualification_proof.json` | `d12718e9b182a3c93eab346901b380031516d556dd823017a63831d4a0304b4e` |
| Frozen `ci/project/p06_warm_contract.json` | `893d85401b1d5f7757d82cb7c743a89b36264fe19c7d08c239b7f216b7a8cbbd` |
| Original diagnostic ZIP | `6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb` |
| Original local attempt-04 control ZIP | `d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f` |

The original proof also pins the diagnostic public source inventory retained in the checkout. The current proof extends exactly one of the 69 measurement sources, the native caller, while preserving the other 68 source identities and all ten premises. Any further measurement-source change needs a newly reviewed pin and a fresh attempt. Keep both prerequisite ZIPs unchanged and available separately to the execution and replay callers. The live admission rejects aliases and multiply linked inputs. Do not repack an original merely to move it to another path.

Run the examples in a dedicated Bash script with the variables populated. The guards below deliberately supply no execution revision or machine-specific path:

```bash
set -euo pipefail
: "${P06_PYTHON:?Set the reviewed absolute CPython 3.12.14 python3 executable}"
: "${P06_SOURCE_REVISION:?Set the exact reviewed published execution commit}"
: "${P06_SOURCE:?Set the new dedicated source checkout}"
: "${P06_WORKSPACE:?Set the new owned workspace path}"
: "${P06_ARCHIVE_ROOT:?Set the pinned archive root}"
: "${P06_DEPENDENCY_REPOSITORIES:?Set the pinned dependency repository root}"
: "${P06_HOST_BIN:?Set the reviewed host-tool alias directory}"
: "${P06_DIAGNOSTIC_ARCHIVE:?Set the original diagnostic ZIP path}"
: "${P06_CONTROL_ARCHIVE:?Set the original attempt-04 ZIP path}"
: "${P06_REVIEW_DIRECTORY:?Set the external review directory}"
[[ "$P06_SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]]
[[ "$P06_PYTHON" == /*/python3 ]]
P06_OBSERVED_REVISION="$(git -C "$P06_SOURCE" rev-parse HEAD)"
test "$P06_OBSERVED_REVISION" = "$P06_SOURCE_REVISION"
git -C "$P06_SOURCE" status --short
git -C "$P06_SOURCE" submodule status --recursive
"$P06_PYTHON" --version
```

Check that status is clean and that each of `cocogfx`, `cvfpu`, `common_cells`, `fpu_div_sqrt_mvp`, `flexfloat`, `hardfloat`, `ramulator` and `softfloat` is initialized at its recorded commit. If populating a new checkout, use `git submodule update --init --recursive`, never `--remote`. The producers perform stronger full source/index-state checks; these displayed checks do not replace them.

## Read-only readiness screen

Before creating a native workspace or beginning preparation, collect the advisory
screen from the same trusted checkout selected by `P06_SOURCE`. The
[observer](../../../../ci/project/p06_qualified_warm_readiness.py) requires all
**eight flags** below: seven explicit paths and the exact expected revision.
`--source-dir` must identify the checkout containing that executing script.
`--workspace-dir` may name an absent planned directory whose parent exists; the
screen does not create it. Keep the external review directory outside all input
roots, and select fresh output filenames.

The screen reads pinned proofs and source identities, checks raw original and
locked-part identities, inspects local dependency Git objects, observes host
aliases, runs bounded host-version/Git probes, and reports capacity. It performs
no download, archive extraction, dependency build or native execution. Missing
or inadmissible inputs become explicit observations; it does not acquire or
repair them.

The preceding variable guards still apply. Run this as a separate observation
before the mutating stages. The output writes below only retain the screen's
report and invocation records in the external review directory.

```bash
test -d "$P06_REVIEW_DIRECTORY"
(
  set -o noclobber
  date -u +%Y-%m-%dT%H:%M:%SZ > "$P06_REVIEW_DIRECTORY/readiness.started.txt"
  if PYTHONDONTWRITEBYTECODE=1 "$P06_PYTHON" -B \
    "$P06_SOURCE/ci/project/p06_qualified_warm_readiness.py" \
    --source-dir "$P06_SOURCE" \
    --workspace-dir "$P06_WORKSPACE" \
    --archive-root "$P06_ARCHIVE_ROOT" \
    --dependency-repositories "$P06_DEPENDENCY_REPOSITORIES" \
    --host-bin "$P06_HOST_BIN" \
    --diagnostic-archive "$P06_DIAGNOSTIC_ARCHIVE" \
    --control-archive "$P06_CONTROL_ARCHIVE" \
    --expected-revision "$P06_SOURCE_REVISION" \
    > "$P06_REVIEW_DIRECTORY/readiness.json" \
    2> "$P06_REVIEW_DIRECTORY/readiness.stderr.log"; then
    P06_READINESS_STATUS=0
  else
    P06_READINESS_STATUS=$?
  fi
  printf '%s\n' "$P06_READINESS_STATUS" > "$P06_REVIEW_DIRECTORY/readiness.exit-code.txt"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$P06_REVIEW_DIRECTORY/readiness.finished.txt"
  exit "$P06_READINESS_STATUS"
)
```

The nonzero result is preserved and stops a surrounding `set -e` script. Inspect
the retained JSON and stderr before continuing work. Do not replace the return
code or delete failed observations to create an apparent successful screen.

| Result | Interpretation |
| --- | --- |
| Check `observed` | The bounded observation met that row's selected requirement. |
| Check `blocked` | A requirement failed or its input could not be admitted. |
| Check `not_checked` | Another unavailable prerequisite prevented this check. |
| Check `unknown` | This observer cannot establish the requirement. |
| Exit `1` | At least one blocked, unknown or unchecked row remains. |
| Exit `2` | Invalid invocation, reporting failure or unexpected observer error; argument/output failures may leave no JSON. |
| Exit `0` | The generic no-blocker branch; it does not authorize native work. The current implementation cannot reach it while its unconditional cgroup-unknown row remains. |

`resources.cgroup_capacity` deliberately remains `unknown`: host
`MemAvailable` does not establish effective process allocation or hidden ancestor
limits. The current real report therefore cannot be all clear. Disk snapshots
reserve no space, shared filesystems provide no independent extra capacity, and
the 15 GiB reserve is not an upper bound for extraction/build/log growth. Confirm
adequate effective allocation independently and satisfy the existing production
resource guards before native preparation.

The advisory JSON is not a preparation receipt or an admission input. It leaves
`native_execution="not_run"`, `counter_qualification_passed=false`,
`qualified_warm_passed=false` and every historical acceptance field false. It
cannot establish governance completion, authenticated artifact delivery, archive
member safety, full historical replay, complete compiler support/runtime files,
installed native tool validity or native execution. Source observations are
bounded and non-atomic; all later stages must revalidate their own inputs. Keep
both raw prerequisite ZIPs and every frozen native limit unchanged.

## 2. Inspect resources and prepare the supervisor environment

Keep the existing limits: **two build jobs**, **one simulation worker**, **15 GiB free-disk reserve**, **4 GiB available memory** and **4 GiB sampled child process-group RSS**. Native configure/build/process timeouts are **120 / 1,800 / 180 seconds**, with **16 MiB per recorded child command log**. Toolchain extraction retains its own unchanged limits. The selected source and workspace filesystems must actually satisfy the checks; a roomy `/workspace` does not imply that `/tmp` has the same capacity.

These are polled budgets, not hard cgroup or filesystem quotas. Sampling can miss peaks or double-count shared pages, and bounded termination/receipt writing can finish after a deadline. The direct three-stage composition does not claim the historical outer executor's 90-minute supervision or its descendant accounting. Record any additional supervisor's own limits and actual behavior separately. The retained [attempt-01 supervisor](native/attempt-01-supervisor.py.txt) records its historical 90-minute bound, old revision and scratch paths; preserve it as evidence and do not execute it unchanged. The new [parameterized wrapper](../../../../ci/project/p06_qualified_warm_run.py) supplies the separately documented 90-minute polled outer budget for the current route. Use that wrapper through the [hosted guide](../../p06-hosted-warm-guide.md), or the direct composition below. The wrapper creates its own absent workspace, so do not precreate that workspace using the direct recipe. The additional visible-cgroup observer records exposed bounds only; unknown hierarchy visibility never authorizes native execution.

If the resource guard fails, stop, preserve the attempt and select an adequately provisioned new owned workspace/checkpoint. Do not lower reserves, widen timeouts, disable recording, prune an original or silently reuse partially built products to obtain a pass.

```bash
test ! -e "$P06_WORKSPACE"
test ! -L "$P06_WORKSPACE"
test -d "$P06_REVIEW_DIRECTORY"
df -h -- "$P06_SOURCE" "$P06_ARCHIVE_ROOT" "$P06_DEPENDENCY_REPOSITORIES" "$P06_REVIEW_DIRECTORY"
free -h
mkdir -m 700 -- "$P06_WORKSPACE"
mkdir -m 700 -- "$P06_WORKSPACE/local-home" "$P06_WORKSPACE/local-tmp"
P06_PYTHON_DIRECTORY="${P06_PYTHON%/*}"
P06_ENV=(/usr/bin/env -i
  "PATH=$P06_HOST_BIN:$P06_PYTHON_DIRECTORY:/usr/bin:/bin"
  "HOME=$P06_WORKSPACE/local-home" "TMPDIR=$P06_WORKSPACE/local-tmp"
  LANG=C LC_ALL=C TZ=UTC PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
  CCACHE_DISABLE=1 OBJCACHE= MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 THREADS=1)
P06_PROOF_SHA256=172721c671ddaa79541dde9c37c154b5ab5a99b8abb0caabf2e07036dd429efb
P06_DIAGNOSTIC_SHA256=6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb
P06_CONTROL_SHA256=d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f
cd "$P06_SOURCE"
```

`P06_ENV` supplies only the child invocation's environment; it does not replace the caller shell's home or path. The dependency and native producers then select and retain their own sanitized command environments and out-of-tree build directories. Do not export arbitrary compiler flags or library paths into them.

A small external invocation recorder preserves the exact command, start/end UTC times, exit status and combined output without overwriting earlier logs. Its receipt is local supervision data, not a new accepted outer-envelope contract:

```bash
p06_run_stage() {
  local P06_STAGE="$1"
  shift
  local P06_LOG_BASE="$P06_REVIEW_DIRECTORY/$P06_STAGE"
  local P06_STAGE_STATUS
  test ! -e "$P06_LOG_BASE.command.txt"
  test ! -e "$P06_LOG_BASE.stdout.log"
  test ! -e "$P06_LOG_BASE.started.txt"
  test ! -e "$P06_LOG_BASE.finished.txt"
  test ! -e "$P06_LOG_BASE.exit-code.txt"
  (
    set -o noclobber
    printf '%q ' "${P06_ENV[@]}" "$@" > "$P06_LOG_BASE.command.txt"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$P06_LOG_BASE.started.txt"
    if "${P06_ENV[@]}" "$@" > "$P06_LOG_BASE.stdout.log" 2>&1; then
      P06_STAGE_STATUS=0
    else
      P06_STAGE_STATUS=$?
    fi
    printf '%s\n' "$P06_STAGE_STATUS" > "$P06_LOG_BASE.exit-code.txt"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$P06_LOG_BASE.finished.txt"
    exit "$P06_STAGE_STATUS"
  )
}
```

With `set -e`, a failed stage stops the script. Inspect its original report and log. Preserve successful earlier subpackets with the failed attempt; their success does not qualify the whole attempt. Do not manually repair or resume source staging in that attempt.

## 3. Run the three fresh stages

### Preparation

The owned workspace now exists; `tools/`, the preparation receipt, dependency build/source destinations, native work tree and stage evidence outputs must still be absent. The preparation checks source cleanliness, exact gitlinks, absent fetched inputs/products, resources, local Git objects and locked archive bytes.

```bash
p06_run_stage preparation "$P06_PYTHON" -B \
  "$P06_SOURCE/ci/project/p06_dependency_local_prepare.py" \
  --source-dir "$P06_SOURCE" \
  --workspace-dir "$P06_WORKSPACE" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --archive-root "$P06_ARCHIVE_ROOT" \
  --dependency-repositories "$P06_DEPENDENCY_REPOSITORIES" \
  --host-bin "$P06_HOST_BIN"
```

Require exit 0 and `outcome="pass"` in `evidence/dependency-preparation.json`. It records local preparation and `native_execution="not_run"`.

### Fresh dependency build

```bash
p06_run_stage dependency-build "$P06_PYTHON" -B \
  "$P06_SOURCE/ci/project/p06_dependency_build.py" \
  --source-dir "$P06_SOURCE" \
  --workspace-dir "$P06_WORKSPACE" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --preparation "$P06_WORKSPACE/evidence/dependency-preparation.json" \
  --output-dir "$P06_WORKSPACE/evidence/dependency-build" \
  --host-bin "$P06_HOST_BIN"
```

Require the completed report's successful fresh-build flag. This stage retains preparation inside its own packet as `preparation.json`; the top-level preparation receipt remains outside the two-root qualification ZIP.

Compute the next stage's dependency pin from this completed original's **raw report bytes**, and retain it externally. This initial check does not replace the qualified executor's complete dependency admission:

```bash
P06_DEPENDENCY_RECEIPT_SHA256="$("$P06_PYTHON" -I -B - \
  "$P06_WORKSPACE/evidence/dependency-build/report.json" "$P06_SOURCE_REVISION" <<'PY'
import hashlib, json, pathlib, sys
body = pathlib.Path(sys.argv[1]).read_bytes()
report = json.loads(body)
assert report['state'] == 'finished' and report['outcome'] == 'pass'
assert report['reason'] is None and report['failures'] == []
assert report['expected_revision'] == sys.argv[2]
assert report['fresh_dependency_build_passed'] is True
print(hashlib.sha256(body).hexdigest())
PY
)"
(set -o noclobber; printf '%s\n' "$P06_DEPENDENCY_RECEIPT_SHA256" > "$P06_REVIEW_DIRECTORY/dependency-receipt.sha256")
```

### Explicit qualified warm native run

```bash
p06_run_stage qualified-warm "$P06_PYTHON" -B \
  "$P06_SOURCE/ci/project/p06_qualified_warm_execute.py" run \
  --source-dir "$P06_SOURCE" \
  --expected-revision "$P06_SOURCE_REVISION" \
  --tools-dir "$P06_WORKSPACE/tools" \
  --work-dir "$P06_WORKSPACE/work" \
  --output-dir "$P06_WORKSPACE/evidence/qualified-warm" \
  --host-bin "$P06_HOST_BIN" \
  --dependency-receipt "$P06_WORKSPACE/evidence/dependency-build/report.json" \
  --dependency-receipt-sha256 "$P06_DEPENDENCY_RECEIPT_SHA256" \
  --counter-qualification "$P06_SOURCE/ci/project/p06_qualified_warm_proof.json" \
  --counter-qualification-sha256 "$P06_PROOF_SHA256" \
  --diagnostic-archive "$P06_DIAGNOSTIC_ARCHIVE" \
  --diagnostic-archive-sha256 "$P06_DIAGNOSTIC_SHA256" \
  --control-archive "$P06_CONTROL_ARCHIVE" \
  --control-archive-sha256 "$P06_CONTROL_SHA256" \
  --jobs 2 --timeout-seconds 1800 --run-timeout-seconds 180
```

The entry point explicitly requires lifetime, dependency, counter qualification and qualified warm selection. It validates the current source extension and replays both historical prerequisite packets against the unchanged original proof before any recorded build/native command. Proof, reconstructed admission and the full frozen sampling plan enter both format build bindings and every process binding. Each process receives its bound digest before launch; both policies share one immutable build per format.

The exact order is FP16, then BF16; pair zero is warm-up and pairs one through five are measured. Policy order alternates, starting with reference `per_operation` before candidate `reusable_single_tile` at pair zero. Each fresh process performs one excluded prime and 32 timed serial operations. All nine completed totals must match:

| Observation | Complete attempt |
| --- | ---: |
| Processes | 24 |
| Launches | 792 |
| Exact FP32 words checked | 25,344 |
| Counter snapshots | 96 |
| Available counter queries | 3,168 |
| Successful half replies | 6,336 |
| Cache-flush reads | 792 |
| DCR reads | 7,128 |
| Unavailable rows without queries | 1,152 |

These totals do not replace per-process numerical, source/build/load, counter, lifetime, destruction or final stability checks. Retain every prime and warm-up observation; the measured population is 20 processes, 640 operations and 20,480 checked output words.

Wait until `qualified-warm/report.json` has `state="finished"`; require successful outcome, `counter_qualification_passed=true`, `qualified_warm_passed=true`, exact complete counts and no failures before describing native qualification as passed. The last flag means this attempt completed its required qualified population; it does not say the performance hypothesis passed. The seven historical fields remain false: `qualified`, `ready_for_warm`, `warm_execution`, `full_warm_coverage`, `acceptance_claimed`, `phase_acceptance` and `performance_acceptance`. The new counter scope is `recorded-complete-24-process-warm-attempt-only`. Historical pending-read and alternate-library controls are not counted as additional new processes.

Stop and preserve the whole attempt on an admission, build, process, resource, stability or interruption failure. Do not resume it, replace a sample, omit an outlier or rerun until a favorable performance result appears. A later corrected source or environment requires its own separately identified fresh attempt, with earlier failures retained.

## 4. Preserve the exact two-root original

The [packaging helper](../../../../ci/project/p06_qualified_warm_pack.py) offers
separate `success` and `partial` modes after evidence writers finish. Its
complete original preserves exactly the same two roots described below;
acquisition/supervision records stay in a separate envelope. Its `PRIVATE`
outputs, including partial bytes and packaging-failure records, must be retained
privately. Use the [hosted encryption procedure](../../p06-hosted-warm-guide.md)
before public artifact upload. Closeout attempts can fail: unknown launch or
unresolved cleanup blocks packaging and encryption, and only successfully
uploaded validated ciphertext and its sanitized summary establish durable
hosted delivery. Inspect invocation/hosted-closeout status and failure receipts
as well as any success-shaped packaging receipt; interruption can leave that
receipt and verified final ZIPs after a failed invocation. Packaging and
encryption do not establish replay, native validity or performance acceptance.
Encryption uses a separate bounded retention-space check so a small failure
packet can survive a native 15 GiB reserve failure when tools/configuration are
available; native and acquisition resource guards remain unchanged. The
[failure matrix](../../p06-hosted-warm-guide.md#failure-and-delivery-matrix)
records setup, encryption and cancellation limits.

Wait until both stage reports are finished and no producer is writing either tree. Preserve every failed attempt as well. If an early failure never produced both subpackets, retain its available files separately with the failure; do not fabricate the missing subtree or a complete original.

A qualified warm ZIP has exactly these two regular-file root populations:

- `dependency-build/`
- `qualified-warm/`

Do not ZIP the whole `evidence/` directory. Top-level preparation, invocation logs, identities and independent review results stay outside this archive. Keep every regular member beneath the selected roots, including applicable hidden `.retention.lock` files and opaque diagnostic side outputs. Do not exclude unfavorable records, add a generated manifest inside the packet, combine attempts or rewrite JSON.

The following data-only recipe checks the finished reports, rejects links/special files, preserves all regular members, compares every compressed member with its original and rehashes the source trees after packaging. A failed but finished pair can be preserved by the same recipe; packaging does not make it pass.

```bash
: "${P06_ORIGINAL_ZIP:?Set a new absolute ZIP path outside source and workspace}"
export P06_SOURCE P06_WORKSPACE P06_ORIGINAL_ZIP
"$P06_PYTHON" -I -B - <<'PY'
import hashlib, json, os, pathlib, stat, zipfile
source = pathlib.Path(os.environ['P06_SOURCE'])
workspace = pathlib.Path(os.environ['P06_WORKSPACE'])
root = workspace / 'evidence'
target = pathlib.Path(os.environ['P06_ORIGINAL_ZIP'])
roots = ('dependency-build', 'qualified-warm')
assert root.is_absolute() and root.resolve(strict=True) == root
assert not any(p.is_symlink() for p in (root, *root.parents))
assert target.is_absolute() and target.parent.resolve(strict=True) == target.parent
assert not any(p.is_symlink() for p in target.parents)
assert not target.is_relative_to(workspace) and not target.is_relative_to(source)
assert not os.path.lexists(target)
sidecar = target.with_suffix('.identity.json')
assert not os.path.lexists(sidecar)
for name in roots:
    directory = root / name
    assert directory.is_dir() and not directory.is_symlink()
    assert json.loads((directory / 'report.json').read_bytes())['state'] == 'finished'

def inventory():
    rows = {}
    for name in roots:
        for path in sorted((root / name).rglob('*')):
            before = path.lstat()
            assert not stat.S_ISLNK(before.st_mode)
            if stat.S_ISDIR(before.st_mode):
                continue
            assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = path.lstat()
            assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                    before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)
            rows[path.relative_to(root).as_posix()] = (before.st_size, digest)
    return dict(sorted(rows.items()))

before = inventory()
with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name in before:
        archive.write(root / name, arcname=name)
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert archive.namelist() == list(before)
    for name, (size, digest) in before.items():
        assert archive.getinfo(name).file_size == size
        with archive.open(name) as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest
assert inventory() == before
with target.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
identity = {'filename': target.name, 'size_bytes': target.stat().st_size,
            'sha256': digest, 'member_count': len(before), 'roots': list(roots),
            'all_members_rehashed_against_original': True,
            'original_rehashed_after_packaging': True, 'zip_crc_verified': True,
            'retained_code_executed': False}
with sidecar.open('x', encoding='utf-8') as stream:
    json.dump(identity, stream, indent=2)
    stream.write('\n')
print(json.dumps(identity, sort_keys=True))
PY
```

Pin the actual ZIP bytes. Compression changes can produce a different ZIP identity for identical member contents. Keep the selected original unchanged after its identity is recorded. This packet does not contain the whole host installation, original toolchain archives or operating system; keep their separate acquisition/provenance evidence when making claims about them.

## 5. Independent intake and complete inert replay

Select external expectations from the reviewed execution/intake record, not from an untrusted candidate's self-reported digests. Record source and reader revisions, exact raw SHA-256 values, sizes, paths and original provenance outside the packet. Stop on any mismatch; do not replace an expected digest solely to obtain a passing replay.

| Variable | Independently selected identity |
| --- | --- |
| `P06_ZIP_SHA256` | Exact two-root original ZIP bytes |
| `P06_SOURCE_REVISION` | Actual original execution commit |
| `P06_DEPENDENCY_RECEIPT_SHA256` | Raw `dependency-build/report.json` bytes |
| `P06_NATIVE_REPORT_SHA256` | Raw `qualified-warm/report.json` bytes |
| `P06_NATIVE_SOURCE_BEFORE_SHA256` | Raw `qualified-warm/snapshots/source-before.json` bytes |
| `P06_READER_SOURCE` | Trusted reviewed reader checkout, never code extracted from the candidate |
| `P06_REPLAY_OUTPUT` | New JSON path in an existing external directory |

`--source-manifest-sha256` names the native snapshot's raw bytes, not the semantic dependency-source manifest digest, a source plan, Git tree or proof digest. Every SHA-256 expectation is 64 lowercase hexadecimal characters. The current extended proof, diagnostic and control pins remain the three independently selected CLI identities above; the original proof and frozen warm manifest remain pinned trusted inputs. This procedure deliberately supplies no native report, source-manifest, dependency-receipt or ZIP hash before actual execution and intake.

```bash
: "${P06_READER_SOURCE:?Set the trusted reader checkout}"
: "${P06_REPLAY_OUTPUT:?Set a new external replay JSON path}"
: "${P06_ZIP_SHA256:?Set the independently recorded ZIP digest}"
: "${P06_DEPENDENCY_RECEIPT_SHA256:?Set the independently recorded dependency receipt digest}"
: "${P06_NATIVE_REPORT_SHA256:?Set the independently recorded native report digest}"
: "${P06_NATIVE_SOURCE_BEFORE_SHA256:?Set the independently recorded native snapshot digest}"
git -C "$P06_READER_SOURCE" rev-parse HEAD
git -C "$P06_READER_SOURCE" status --short
p06_run_stage independent-replay "$P06_PYTHON" -B \
  "$P06_READER_SOURCE/ci/project/p06_qualified_warm_replay.py" \
  --archive "$P06_ORIGINAL_ZIP" \
  --sha256 "$P06_ZIP_SHA256" \
  --source-revision "$P06_SOURCE_REVISION" \
  --dependency-receipt-sha256 "$P06_DEPENDENCY_RECEIPT_SHA256" \
  --native-report-sha256 "$P06_NATIVE_REPORT_SHA256" \
  --source-manifest-sha256 "$P06_NATIVE_SOURCE_BEFORE_SHA256" \
  --counter-qualification-sha256 "$P06_PROOF_SHA256" \
  --diagnostic-archive "$P06_DIAGNOSTIC_ARCHIVE" \
  --diagnostic-archive-sha256 "$P06_DIAGNOSTIC_SHA256" \
  --control-archive "$P06_CONTROL_ARCHIVE" \
  --control-archive-sha256 "$P06_CONTROL_SHA256" \
  --output "$P06_REPLAY_OUTPUT"
```

The packaging recipe uses no prefix. If a separately selected original uses one common literal prefix, record that choice during intake and pass `--prefix PREFIX` explicitly; do not search the archive for a favorable candidate. Output is created exclusively. Use a new output/log path for each independent review.

A passing replay reconstructs the complete dependency receipt, both format builds, all **57 native command receipts**, all **24 raw process transcripts**, proof/source/dependency relationships, both full historical prerequisite replays, stability and exact member inventories. Only then does it derive `counter_qualification_passed=true` and `qualified_warm_passed=true` and call the arithmetic reducer. Its contract is `p06-qualified-warm-replay-v1` and scope is `complete-qualified-warm-retained-consistency`. Replay itself reports `native_execution="not_run"`, `retained_code_executed=false`, `execution_origin="local"` and `origin_authenticated=false`. Consistent retained records do not authenticate an untrusted producer or independently establish Git membership.

Only the explicitly selected `qualified-warm/report.json` uses the new bounded decoder: **64 MiB**, **750,000 value nodes**, depth **64**. Duplicate keys, nonfinite values and excessive numeric tokens reject. Individual retained records and historical routes retain their existing parser bounds. Do not truncate a report, widen those bounds or use another route to admit a rejected candidate.

Retain the reviewer's source/helper identities and independently inspect the original native observations. Do not execute scripts or binaries extracted from the candidate. The raw report, source snapshot and complete original ZIP must match their independently recorded input pins before a result is accepted for review.

## 6. Interpret the fixed predicates and publish the handoff

Inspect `analysis.hypothesis_evaluation` in the complete replay result. `satisfied` means both formats satisfied all frozen experimental predicates; `not_satisfied` is a valid complete experiment whose optimization hypothesis failed. The public replay exits successfully for either valid outcome. A nonzero replay exit means the command did not deliver a usable reported result. Inspect its reason: a consistency or qualification rejection differs from an output I/O failure after otherwise valid replay. Neither a failed command nor an incomplete output establishes an experimental result. Never use exit zero or `qualified_warm_passed=true` as a substitute for the hypothesis field.

For **each format independently**, use the five measured batch means per policy, each computed from exactly 32 primary timed intervals. The candidate median must be at most **95%** of the reference median; **every measured candidate pair** must be no slower in instrumented host time and have no increase in qualified modeled cycles. Both FP16 and BF16 must meet all predicates. The reducer uses exact integer/rational comparisons. All 24 prime operations and the four warm-up processes remain retained but excluded from the decision. Do not pool individual intervals into a different sample population, remove outliers, change the threshold, subtract observer overhead or correct for supervisor delay.

Report the result as instrumented host time and qualified modeled cumulative batch observations. It is not physical GPU latency, energy, power or hardware qualification. `performance_acceptance`, `phase_acceptance` and `acceptance_claimed` remain false even when the experiment's hypothesis is satisfied. Historical warm-v1 rejection and all seven historical false fields remain intact; P06-A02/A03 and vendor integration require their separate obligations.

Before updating status/backlog, retain the exact native revision and configuration, original ZIP and all external identities, supervision and failed-attempt records, independent complete replay, numerical/lifetime/build reviews, source-scoped test results and limitations. State one next bounded action supported by the observed result. Neither this runbook nor a successful synthetic tooling test establishes a fresh native experiment.
