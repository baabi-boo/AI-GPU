# Complete governance invocation runbook

Use this procedure to obtain one uninterrupted execution of the complete project
governance population. Commands are instructions, not evidence that a run passed.
The [workflow](../../.github/workflows/project-governance.yml),
[environment preparer](../../ci/project/governance_env.py) and
[strict runner](../../ci/project/governance_run.py) define the executable contract.
Run from a clean, published source checkout, without a GPU build tree.

## Why the invocation environment matters

Legacy hosted runs could report `OK (skipped=23)` while leaving **36 canonical
test bodies unexecuted**: 21 method skips plus two class-setup skip events that
suppressed another 15 bodies. Ambient preflight found CMake, but dependency
fixtures deliberately search only the interpreter directory, `/usr/bin` and
`/bin`. CMake outside that restricted PATH was invisible. Keep that production
sanitization; expose a checked native executable through the prepared interpreter
directory instead.

The executing interpreter must use the private `venv/bin/python3` alias. Existing
dependency and replay contracts bind the selected `python3` path to the executing
interpreter; another alias for the same binary is a different launch identity.
Preparation checks both private alias paths and their common resolved binary,
then probes and records the exact `python3` interpreter used for the suite.

The [historical audit](p06-qualified-warm-audit.md) and
[coverage reconciliation](evidence/p06-qualified-warm/validation/coverage/final-reconciliation.json)
preserve the separate result: 4,491 hosted passing IDs plus 59 supplemental IDs,
less 23 overlaps, covered all 4,527 IDs at that historical revision. That union
crosses two environments and does not establish one complete invocation without
skips. Use each new run's discovered manifest for its population; counts change
with source revisions. Ordinary unittest success, selected-module reruns and a
union of partial runs cannot satisfy the strict invocation requirement.

## Host and tool prerequisites

Governance requires GIL-enabled Linux CPython **3.12.x**, a little-endian x86-64
glibc host, working `venv` support, and `gcc`, `g++`, `ar`, `ranlib`, `make`, `git`,
`tclsh` and `readelf` in the restricted PATH. Preparation checks the Python
aliases, native CMake, C preprocessing, ELF32 linking, C++17/threads, UBSan,
POSIX FIFO/no-follow support, `/proc` and `/dev/full`. It builds small host
prerequisite probes. The bootstrap interpreter and system tools are trusted
inputs; a preflight inventory alone does not establish readiness.

The preparer accepts CMake **3.21 through 3.25** because the retained dependency
command grammar requires pre-3.26 behavior and linker-launcher support. CI pins
**3.22.6**. A pip-installed `bin/cmake` may be a Python launcher that fails under
the isolated environment; select the package's native `cmake/data/bin/cmake`.

Inspect capacity under the [resource policy](developer-guide.md) before starting
a long run. The separate [qualified warm route](evidence/p06-qualified-warm/runbook.md)
requires its exact **CPython 3.12.14** and unchanged source, tools, artifacts,
capacity and admission checks. Governance readiness or success grants no native
admission and changes no simulation, RTL, FPGA, performance or phase acceptance
requirement; see the [acceptance policy](acceptance.md).

## Prepare a fresh invocation

Set `GOVERNANCE_SOURCE` to the absolute clean source root, `GOVERNANCE_REVISION`
to its published full commit ID, and `GOVERNANCE_ROOT` to a **new absolute path
outside the checkout** whose parent already exists. Use literal paths without
spaces, dot traversal or symlink components. Keep all commands below in one Bash
session. The root, `environment` and `run` directories must be fresh; only the
root and log directory are created manually. Preserve earlier attempts. Use a
complete checkout with no pre-existing local Python bytecode; disabling new
bytecode writes does not remove existing caches.

```bash
set -euo pipefail
: "${GOVERNANCE_SOURCE:?Set an absolute clean source checkout path}"
: "${GOVERNANCE_REVISION:?Set the published full commit ID}"
: "${GOVERNANCE_ROOT:?Set a fresh absolute external output path}"
cd "$GOVERNANCE_SOURCE"
test "$(pwd -P)" = "$GOVERNANCE_SOURCE"
test "$(git rev-parse HEAD)" = "$GOVERNANCE_REVISION"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
mkdir "$GOVERNANCE_ROOT"
mkdir "$GOVERNANCE_ROOT/logs"
export PYTHONDONTWRITEBYTECODE=1
git rev-parse HEAD > "$GOVERNANCE_ROOT/logs/source-revision.txt"
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version; print(sys.version)'
python3 ci/project/preflight.py --tier governance
python3 ci/project/check_project.py
python3 ci/project/check_baseline_packets.py
```

Install the pinned **Linux x86-64 wheel** before offline environment preparation.
This uses bootstrap pip, with no dependency resolution or source build, and
records installation and actual native-version output. The log parent above
must exist before any `tee` pipeline.

```bash
cat > "$GOVERNANCE_ROOT/logs/cmake-requirements.txt" <<'REQUIREMENTS'
cmake==3.22.6 --hash=sha256:a2357c510e37db7df156c31ab43857b4583e3a2ece8220747e8a007aea50aa45
REQUIREMENTS
python3 -m pip --isolated --disable-pip-version-check install \
  --index-url https://pypi.org/simple --no-cache-dir --no-deps --no-compile \
  --only-binary=:all: --require-hashes \
  --target "$GOVERNANCE_ROOT/cmake-package" \
  --requirement "$GOVERNANCE_ROOT/logs/cmake-requirements.txt" \
  2>&1 | tee "$GOVERNANCE_ROOT/logs/cmake-install.log"
governance_cmake="$GOVERNANCE_ROOT/cmake-package/cmake/data/bin/cmake"
test -x "$governance_cmake"
"$governance_cmake" --version 2>&1 | tee "$GOVERNANCE_ROOT/logs/cmake-version.log"
test "$(head -n 1 "$GOVERNANCE_ROOT/logs/cmake-version.log")" = 'cmake version 3.22.6'
python3 ci/project/governance_env.py \
  --output-dir "$GOVERNANCE_ROOT/environment" \
  --cmake "$governance_cmake" \
  2>&1 | tee "$GOVERNANCE_ROOT/logs/environment.log"
```

Preparation performs no downloads. It creates a private venv without pip,
private `home` and `tmp` directories, the native CMake alias and
`environment/environment.json`. Continue only after preparation exits zero with
`status: ready`. Its receipt records probes, versions, requested/resolved paths
and tool hashes; it does not establish suite execution.

## Run the entire suite once

Invoke the prepared Python directly with the exact clean environment. Activating
a venv or prepending ambient PATH is insufficient. Do not omit private `HOME` or
`TMPDIR`, add Python/compiler/loader overrides, or drop pipeline failure handling.

```bash
/usr/bin/env -i \
  PATH="$GOVERNANCE_ROOT/environment/venv/bin:/usr/bin:/bin" \
  HOME="$GOVERNANCE_ROOT/environment/home" \
  TMPDIR="$GOVERNANCE_ROOT/environment/tmp" \
  LANG=C LC_ALL=C TZ=UTC PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 \
  CCACHE_DISABLE=1 OBJCACHE= MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 THREADS=1 \
  "$GOVERNANCE_ROOT/environment/venv/bin/python3" ci/project/governance_run.py \
  --output-dir "$GOVERNANCE_ROOT/run" \
  --environment-receipt "$GOVERNANCE_ROOT/environment/environment.json" \
  2>&1 | tee "$GOVERNANCE_ROOT/logs/governance.log"
```

The runner discovers `ci/project/test_*.py` from the source root and executes that
same ordered suite once. It offers no filtering, partition, retry or resume
option. `--environment-receipt` is required: the runner validates the preparation
receipt and checked tool identities before and after execution and retains the
receipt argument in its launch record. There is no receipt-free qualifying CLI
mode; a missing, empty or invalid receipt cannot produce a qualifying success.
Every discovered ID must have exactly one start, successful outcome and
stop; starts must follow the discovered order. Fixture and subtest events are
accounted separately. Skips, expected failures, unexpected successes, errors, failures,
import errors, empty/duplicate discovery and missing/unexpected/duplicate IDs
all prevent a pass. Standard unittest cleanup releases completed test objects.

## Read and retain the evidence

| Relative output | Meaning |
| --- | --- |
| `environment/environment.json` | Preparation readiness and checked interpreter/tool/probe identities. |
| `run/started.json` | Launch intent and available before-execution source, interpreter and environment identities. It is never completion evidence. |
| `run/discovered.json` | Ordered canonical test IDs, count and SHA-256; written before execution. |
| `run/events.jsonl` | Flushed, sequenced start/outcome/stop events plus fixture and subtest outcomes. |
| `run/unittest.log` | Python stdout/stderr **text-stream** log, capped at 128 MiB. |
| `run/summary.json` | Final completion, strict accounting, source/tool stability, errors, duration and `governance_passed`. |
| `logs/governance.log` | Outer combined stdout/stderr from `tee`, including OS-descriptor and inherited child-process diagnostics. |

The internal log does not capture or bound all descriptor/child output; preserve
the outer log too. Internal truncation prevents a pass. A missing final receipt,
`status: incomplete`, interrupted process or unfinished event population is
**incomplete**, even if earlier tests passed. `status: completed` means execution
finished; **failure** is still the result when `governance_passed` is false.
Only exit zero and `governance_passed: true`, backed by the complete manifest,
events, clean/stable source and checked/stable tools, establish **pass** for this
one invocation. A printed unittest `OK` is insufficient. Preserve failed and
incomplete packets; restart from a fresh output root after resolving the cause.

The source binding compares raw HEAD/index inventories with materialized file
bytes and modes before and after execution; a clean `git status` alone is
insufficient. `source_before`/`source_after` retain HEAD/tree and tracked, index
and worktree digests. Sparse omissions, assume-unchanged/skip-worktree flags,
unbound loaded local Python or its existing bytecode caches cannot qualify. The
runner also rejects executable filter and deferred-object retrieval settings;
raw hashing invokes no clean/smudge filters. Recorded gitlinks/submodule state
allow uninitialized submodules and keep their governance scope; they do not
establish the native route's complete submodule closure.

CI keeps one hosted job with a **90-minute** total budget, including preparation,
validators, the suite and artifact upload. The retained historical suite took
3,555.657 seconds, leaving only 44.343 seconds in the former 60-minute budget.
This extra time changes no population or acceptance predicate. Concurrency still
cancels superseded runs for the same event/ref, so allow a validation candidate
to finish uninterrupted.

The workflow makes a best-effort attempt to upload `logs`, the environment
receipt and the whole `run` directory when the upload step can execute, with
source SHA, provider run ID and attempt in the artifact name, for 30 days. A job
timeout or runner loss can prevent upload. Confirm that the packet exists,
retain provider step logs and verify the uploaded packet against that exact
revision and attempt. The package and venv are not uploaded; their recorded
identities support the governance-only result.

## Independently replay an original

Use the [governance artifact replay guide](governance-artifact-replay.md) for the
bounded original ZIP reader. It joins the retained manifest, events, receipts
and logs to an explicit clean checkout at the exact recorded revision. Its
isolated discovery imports that trusted source to enumerate canonical test IDs;
it runs no test bodies and executes no archive content. Supply an independently
selected archive digest. Provider identity remains separate from offline record
consistency.

The qualified warm hosted preflight additionally retrieves the exact artifact
for its selected successful run and attempt, verifies its provider digest,
requires this replay, and reobserves provider/source stability. Expired, absent,
partial or substituted originals block that route. A replay of an earlier
revision does not qualify changed source or grant native/phase acceptance.
