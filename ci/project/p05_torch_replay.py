#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check retained P05 framework observations without running archive payloads."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
import p04_model_contract as model_contract
import p05_execution_records as python_records
import p05_installed_check
import p05_torch_records as torch_records
import p05_replay_installation as installation_replay
import p05_replay_native as native_replay
import p06_replay

verify_installations = installation_replay.verify_installations
verify_native = native_replay.verify_native
_archive_api = p06_replay._archive_api


ROOT = Path(__file__).resolve().parents[2]
REVISION = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CONTRACT_ID = "p05-retained-torch-consistency-v1"
MIB = 1024 ** 2
BUDGET = {"min_free_bytes": 15 * 1024**3, "max_rss_bytes": 4 * 1024**3,
          "max_log_bytes": 16 * MIB, "framework_file_bytes": 2 * 1024**3,
          "framework_total_bytes": 3 * 1024**3, "framework_files": 50000}
TORCH_SOURCE_FILES = (
    "ci/project/p05_torch_execute.py", "ci/project/p05_torch_records.py",
    "ci/project/p05_torch_installed_check.py", "ci/project/p05_torch_contract.json",
    "ci/project/p05_torch_requirements.lock",
)
PYTHON_SOURCE_FILES = (
    "ci/project/p05_execute.py", "ci/project/p05_execution_records.py",
    "ci/project/p05_installed_check.py", "ci/project/p05_bundle.py", "python/README.md", "LICENSE",
)
TORCH_HELPERS = tuple(sorted((*native_replay.PYTHON_HELPERS,
                              "ci/project/p05_torch_execute.py", "ci/project/p05_torch_records.py")))
RETAINED_SOURCES = tuple(sorted(set(TORCH_HELPERS + TORCH_SOURCE_FILES + PYTHON_SOURCE_FILES
                                  + installation_replay.SOURCE_PATHS)))
CHECKOUT_INPUTS = ("VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml",
                   "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh")
SUBMODULE_PATHS = (
    "third_party/cocogfx", "third_party/cvfpu", "third_party/cvfpu/src/common_cells",
    "third_party/cvfpu/src/fpu_div_sqrt_mvp", "third_party/cvfpu/tb/flexfloat",
    "third_party/hardfloat", "third_party/ramulator", "third_party/softfloat",
)
# Only these local modules supply the reader. Unrelated modules imported by a
# test runner must neither enlarge its identity nor hide a missing dependency.
READER_MODULES = tuple(sorted((*p06_replay.REPLAY_MODULES, "p06_replay", "p05_execution_records",
                              "p05_installed_check", "p05_torch_records", "p05_replay_native",
                              "p05_replay_installation")))
READER_DATA = tuple(sorted(set(model_contract.ARTIFACT_PATHS) | {
    model_contract.MANIFEST_PATH, p06_replay.ARCHIVE_READER_PATH,
    "ci/project/p05_execute.py", "ci/project/p05_torch_execute.py",
    *("ci/project/fixtures/" + name for name in native_replay.FIXTURES),
}))
REPORT_FIELDS = frozenset("""
acceptance_claimed backend budget bundle_artifacts bundle_manifest bundle_validation
commands comparison contract contract_id development execution_counts finished_at
format framework_after framework_before framework_entry_points framework_wheel_payload
installed_after installed_before installed_helpers installed_request installed_wheel
iterations limitations loaded_helpers observations outcome paths phase_complete
provisioning_interpreter python_input python_input_after python_report python_revalidation
reason requirements resources_after resources_before retained_sources schema_version
source_after source_before source_stable started_at state venv_configuration
venv_interpreter venv_seed wheelhouse wheelhouse_after
""".split())
COMMAND_FIELDS = frozenset("""
argv cleanup_complete cwd duration_seconds environment exit_code id limitations log
log_sha256 log_size_bytes outcome peak_rss_bytes process_started reason timeout_seconds
""".split())
COMMAND_IDS = (
    "framework-create-venv", "framework-install-locked-wheels",
    "framework-install-bound-wheel", "framework-environment-before",
    "installed-framework-matrix", "framework-environment-after",
)
REPORT_LIMITATIONS = (
    "One SimX format is executed; both separate format packets are needed for the declared framework matrix.",
    "Only the frozen eager CPU tensor custom operators, Python patch, CPU framework version and wheel closure are qualified.",
    "The copied P04/P05 packets add no executions. This stage adds exactly 36 native launches through 16 framework operator calls.",
    "Framework payload files are independently matched to locked wheels and streamed before/after; large third-party binaries are identified, not replay-archived.",
    "Original P04/P05 paths and their installations must remain present for live revalidation; relocated offline review is a separate operation.",
    "SimX results are simulated evidence, not RTL, vendor hw_emu, physical FPGA, silicon or physical performance evidence.",
    "No phase acceptance, general framework backend, autograd, training, arbitrary models, CUDA inputs or zero-copy claim is made.",
    "Source and artifact identities retain the existing trusted-builder/non-adversarial-filesystem boundary.",
    *PROCESS_LIMITATIONS,
)
HOST_SCENARIOS = (
    "matmul_shapes", "fixed_models", "transient_timeout", "matmul_deadline", "model_deadline",
    "partial_submit", "async_failure", "cleanup_failure", "model_mismatch",
)
SUPPLEMENTARY_FILES = tuple(sorted({
    "execution.log", "framework-provision.log", "job.json", "native-execution.log",
    "p05_torch_contract.json", "p05_torch_requirements.lock", "preparation.json", "preparation.log",
    "python-provision.json", "python-provision.log", "torch-execution.log", "torch-host.json",
    "torch-host.log", "torch-native-host.log", "workflow.yml", "torch-native-host/report.json",
    "torch-native-host/test.snapshot.py", "torch-native-host/runtime/build.log",
    "torch-native-host/runtime/build_commands.json", "torch-native-host/runtime/bundle/kernel.vxbin",
    "torch-native-host/runtime/bundle/manifest.json",
    *("torch-native-host/runtime/bundle/lib/" + name for name in (
        "libramulator-vortex.so", "libramulator.so", "libsimx.so", "libvortex-simx.so", "libvortex.so")),
    *("torch-native-host/runtime/generated/" + name for name in (
        "dummy.cpp", "fake.exports", "p05_build_config.h")),
    *("torch-native-host/runtime/python/vortex_ai/" + name for name in (
        "__init__.py", "_api.py", "_bundle.py", "_native.cpython-312-x86_64-linux-gnu.so",
        "launch.py", "torch_ops.py")),
    *("torch-native-host/children/" + scenario + "/" + name for scenario in HOST_SCENARIOS
      for name in ("command.json", "launcher.py", "stderr.log", "stdout.log")),
}))
LIMITATIONS = (
    "Replay checks retained consistency; it does not authenticate an arbitrary producer or execute a GPU.",
    "The selected archive digest and execution revision must come from independently retained intake evidence.",
    "Recorded runner paths are lexical data; archived code, binaries and wheels are never executed or extracted.",
    "Third-party wheel and installed payload bytes, interpreter/seed bytes and venv configuration contents are not fully retained.",
    "Their recorded identities and inventories can be reconciled, but missing bytes cannot be freshly hashed by replay.",
    "One format is not the complete two-format qualification; copied packets add no executions.",
    "Host fault-test reports remain host evidence. This reader does not grant framework, performance or phase acceptance.",
    "Supplementary preparation and host fault packets have bounded envelope and byte-identity checks only; their fault, build and preparation semantics are not revalidated.",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected, label):
    require(torch_records.canonical(actual) == torch_records.canonical(expected), label + " differs")


def _fields(value, expected, label):
    require(type(value) is dict and set(value) == set(expected), "invalid " + label + " fields")


def _integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, "invalid " + label)


def _absolute(value):
    require(type(value) is str and value.startswith("/") and value != "/"
            and len(value.encode("utf-8")) <= 4096 and "\\" not in value
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value),
            "invalid recorded absolute path")
    path = PurePosixPath(value)
    require(str(path) == value and len(path.parts) <= 64
            and all(p not in ("", ".", "..") for p in value[1:].split("/")),
            "noncanonical recorded absolute path")
    return path


def _timestamp(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", value),
            "invalid UTC execution timestamp")
    return datetime.fromisoformat(value)


def _inventory(rows, api, label, *, expected=None, ordered=True):
    require(type(rows) is list and 0 < len(rows) <= 20000, "invalid " + label + " inventory")
    result = {}
    for row in rows:
        api.descriptor(row)
        require(row["path"] not in result, "duplicate " + label + " path")
        result[row["path"]] = row
    if ordered:
        same(list(result), sorted(result), label + " order")
    if expected is not None:
        same(list(result), list(expected), label + " membership")
    return result


def _trusted_bytes(path):
    require(path.is_absolute() and path.resolve(strict=True) == path
            and not any(part.is_symlink() for part in (path, *path.parents)),
            "trusted reader input is not canonical")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 2 * MIB,
                "trusted reader input is not a bounded regular file")
        body = stream.read(2 * MIB + 1)
        require(len(body) == info.st_size, "trusted reader input changed while reading")
        return body


def _reader_sources():
    paths = {ROOT / name for name in READER_DATA}
    for name in (*READER_MODULES, __name__):
        module = sys.modules.get(name)
        require(module is not None and type(getattr(module, "__file__", None)) is str,
                "missing trusted reader helper: " + name)
        expected = ROOT / "ci/project" / ("p05_torch_replay.py" if name == __name__ else name + ".py")
        require(Path(module.__file__).absolute() == expected,
                "reader helper loaded outside the trusted source: " + name)
        paths.add(expected)
    rows = []
    for path in sorted(paths):
        body = _trusted_bytes(path)
        rows.append({"path": path.relative_to(ROOT).as_posix(),
                     "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
    return rows


# Detect changes after import as well as during replay, including fixture and
# AST-only probe inputs. Historical producer sources have a separate identity.
READER_SOURCES = _reader_sources()


def _source(view, report, api, revision):
    before = view.document(report["source_before"], "snapshots/source-before.json")
    after = view.document(report["source_after"], "snapshots/source-after.json")
    same(after, before, "source before/after")
    _fields(before, ("checkout", "files"), "source snapshot")
    checkout = before["checkout"]
    _fields(checkout, ("revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                       "pins", "blockers", "inputs", "outcome"), "source checkout")
    for key, expected in (("revision", revision), ("dirty", False), ("outcome", "pass"),
                          ("blockers", []), ("changed_paths", []), ("untracked_paths", [])):
        same(checkout[key], expected, "source checkout " + key)
    require(type(checkout["tree"]) is str and REVISION.fullmatch(checkout["tree"]), "invalid source tree")
    submodules = checkout["submodules"]
    _fields(submodules, ("declared_count", "entries", "errors"), "submodule inventory")
    same(submodules["declared_count"], 5, "declared submodule count")
    same(submodules["errors"], [], "source submodule errors")
    modules = submodules["entries"]
    require(type(modules) is list and len(modules) == len(SUBMODULE_PATHS), "incomplete submodule inventory")
    names = []
    for row in modules:
        _fields(row, ("path", "revision", "status"), "source submodule")
        require(row["status"] == "initialized"
                and type(row["revision"]) is str and REVISION.fullmatch(row["revision"]),
                "uninitialized or invalid retained submodule")
        api.relative_name(row["path"])
        names.append(row["path"])
    same(names, list(SUBMODULE_PATHS), "source submodule membership")
    _fields(checkout["pins"], ("FIRESIM_REV", "GEM5_REV", "TOOLCHAIN_REV", "VORTEX_VERSION"), "source version pins")
    require(all(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value)
                for value in checkout["pins"].values()), "invalid source version pin")
    indexed = _inventory(before["files"], api, "source files")
    inputs = _inventory(checkout["inputs"], api, "checkout inputs", expected=CHECKOUT_INPUTS, ordered=False)
    for name, row in inputs.items():
        # blackbox.sh was observed by checkout preflight but was not retained in
        # the runner's larger source inventory. Do not invent unavailable bytes.
        if name != "ci/blackbox.sh":
            same(indexed.get(name), row, "checkout input source identity")
    sources = _inventory(report["retained_sources"], api, "retained sources",
                         expected=("artifacts/source/" + name for name in RETAINED_SOURCES))
    same(list(sources), [name for name in view.files() if name.startswith("artifacts/source/")],
         "retained source member closure")
    for path, row in sources.items():
        name = path.removeprefix("artifacts/source/")
        same({**row, "path": name}, indexed.get(name), "retained source snapshot identity")
        view.verified(row)
    helpers = _inventory(report["loaded_helpers"], api, "loaded helpers", expected=TORCH_HELPERS)
    for name, row in helpers.items():
        same(row, indexed.get(name), "loaded-helper source identity")
        same(sources.get("artifacts/source/" + name), dict(row, path="artifacts/source/" + name),
             "loaded-helper retained identity")
    return before


def _probe_source():
    tree = ast.parse(_trusted_bytes(ROOT / "ci/project/p05_torch_execute.py").decode("utf-8"))
    values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "FRAMEWORK_PROBE"
                      for target in node.targets)
              and isinstance(node.value, ast.Constant) and type(node.value.value) is str]
    require(len(values) == 1, "trusted framework probe source is ambiguous")
    return values[0]


def _commands(view, report, request, api):
    paths = report["paths"]
    require(type(paths) is dict and set(paths) == {
        "source", "output", "python_output", "python_work", "wheelhouse", "work"}, "invalid execution paths")
    paths = {key: _absolute(value) for key, value in paths.items()}
    roots = tuple(paths.values())
    require(not any(left.is_relative_to(right) or right.is_relative_to(left)
                    for index, left in enumerate(roots) for right in roots[index + 1:]),
            "recorded framework execution roots overlap")
    work, output = paths["work"], paths["output"]
    check = work / "installed-check"
    interpreter = str(work / "venv/bin/python")
    same(request["base_request"]["expected_prefix"], str(work / "venv"), "framework venv request")
    same(request["base_request"]["binding"]["bundle_root"], str(output / "artifacts/bundle"), "framework bundle request")
    commands = report["commands"]
    require(type(commands) is list and len(commands) == len(COMMAND_IDS)
            and all(type(row) is dict for row in commands)
            and [row.get("id") for row in commands] == list(COMMAND_IDS),
            "framework command inventory/order differs")
    same([name for name in view.files() if name.startswith("logs/")],
         sorted("logs/" + name + ".log" for name in COMMAND_IDS), "framework command log closure")
    environment_probe = _probe_source()
    provisioning = _absolute(report["provisioning_interpreter"]["path"])
    environment = {
        "CCACHE_DISABLE": "1", "CMAKE_BUILD_PARALLEL_LEVEL": "1", "LANG": "C", "LC_ALL": "C",
        "MAKEFLAGS": "-j1", "MAX_JOBS": "1", "MKL_NUM_THREADS": "1", "OBJCACHE": "",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "PATH": str(provisioning.parent) + ":/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1", "THREADS": "1", "TMPDIR": str(work / "tmp"), "TZ": "UTC",
    }
    framework = view.document(report["framework_before"], "snapshots/framework-before.json", integers_only=True)
    require(type(framework) is dict and type(framework.get("distributions")) is dict
            and len(framework["distributions"]) == 13, "invalid environment distribution closure")
    versions = {}
    for name, row in framework["distributions"].items():
        require(type(name) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                and type(row) is dict and type(row.get("version")) is str
                and 0 < len(row["version"]) <= 128, "invalid environment distribution version")
        versions[name] = row["version"]
    require(versions.get("torch") == torch_records.TORCH_VERSION and versions.get("vortex_ai") == "0.1.0",
            "invalid environment framework identity")
    raw = {}
    for row in commands:
        require(type(row) is dict and set(row) == COMMAND_FIELDS, "invalid framework command fields")
        name = row["id"]
        for key, expected in (("outcome", "pass"), ("exit_code", 0), ("reason", None),
                              ("process_started", True), ("cleanup_complete", True),
                              ("cwd", str(check if name == "installed-framework-matrix" else work)),
                              ("limitations", list(PROCESS_LIMITATIONS))):
            same(row[key], expected, "command " + name + " " + key)
        timeout = 4860 if name == "installed-framework-matrix" else 600
        _integer(row["timeout_seconds"], timeout, timeout, "command timeout")
        duration = row["duration_seconds"]
        require(type(duration) in (int, float) and math.isfinite(duration) and 0 <= duration <= timeout + 10,
                "invalid completed command duration")
        _integer(row["peak_rss_bytes"], 0, 4 * 1024**3, "command sampled RSS")
        _integer(row["log_size_bytes"], 0, 16 * 1024**2, "command log length")
        same(row["log"], "logs/" + name + ".log", "command log path")
        body = view.verified({"path": row["log"], "sha256": row["log_sha256"],
                              "size_bytes": row["log_size_bytes"]}, limit=16 * 1024**2)
        raw[name] = body.decode("utf-8", errors="strict")
        argv = row["argv"]
        require(type(argv) is list and 0 < len(argv) <= 128
                and all(type(x) is str and x and len(x.encode("utf-8")) <= 65536 and "\x00" not in x for x in argv),
                "invalid command arguments")
        same(row["environment"], environment, "command environment")
        if name == "framework-create-venv":
            expected = [report["provisioning_interpreter"]["path"], "-I", "-B", "-m", "venv", "--copies", str(work / "venv")]
        elif name == "framework-install-locked-wheels":
            expected = [interpreter, "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index",
                        "--find-links", str(paths["wheelhouse"]), "--only-binary=:all:", "--require-hashes",
                        "--no-deps", "--no-compile", "--no-cache-dir", "--disable-pip-version-check", "-r",
                        str(output / report["requirements"]["path"])]
        elif name == "framework-install-bound-wheel":
            expected = [interpreter, "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
                        "--no-compile", "--no-cache-dir", "--disable-pip-version-check",
                        str(output / report["installed_wheel"]["path"])]
        elif name == "installed-framework-matrix":
            expected = [interpreter, "-I", "-B", "-m", "vortex_ai.launch", "--bundle",
                        str(output / "artifacts/bundle"), "--", str(check / "p05_torch_installed_check.py"),
                        "--request", str(check / "request.json"), "--output", str(check / "observations.json"),
                        "--contract", str(check / "p05_torch_contract.json")]
        else:
            expected = [interpreter, "-I", "-B", "-c", environment_probe, str(work / "venv"),
                        torch_records.canonical(versions).decode("utf-8")]
        same(argv, expected, "command " + name + " arguments")
    return raw


def _report(view, api, revision, fmt):
    report = view.json("report.json")
    require(type(report) is dict and set(report) == REPORT_FIELDS, "invalid framework report fields")
    for key, expected in (("schema_version", 1), ("contract_id", "p05-installed-torch-execution-v1"),
                          ("backend", "simx"), ("format", fmt), ("state", "finished"), ("outcome", "pass"),
                          ("reason", None), ("development", False), ("source_stable", True),
                          ("acceptance_claimed", False), ("phase_complete", False), ("iterations", 2)):
        same(report[key], expected, "framework report " + key)
    same(report["budget"], BUDGET, "framework resource budget")
    same(report["limitations"], list(REPORT_LIMITATIONS), "framework report limitations")
    started, finished = (_timestamp(report[key]) for key in ("started_at", "finished_at"))
    require(started <= finished, "framework timestamps are reversed")
    source = _source(view, report, api, revision)
    for key in ("resources_before", "resources_after"):
        resources = report[key]
        require(type(resources) is dict and set(resources) == {"available_memory_bytes", "free_disk_bytes"}
                and type(resources["free_disk_bytes"]) is dict
                and set(resources["free_disk_bytes"]) == {"source", "output", "work"}, "missing resource observations")
        if resources["available_memory_bytes"] is not None:
            _integer(resources["available_memory_bytes"], 0, 2**64 - 1, "available memory")
        for size in resources["free_disk_bytes"].values():
            _integer(size, 0, 2**64 - 1, "free disk reserve")
    resources = report["resources_before"]
    require(type(resources["available_memory_bytes"]) is int
            and resources["available_memory_bytes"] >= BUDGET["max_rss_bytes"]
            and all(size >= BUDGET["min_free_bytes"] for size in resources["free_disk_bytes"].values()),
            "initial framework resources were below the frozen budget")
    request = view.document(report["installed_request"], "snapshots/installed-request.json", integers_only=True)
    torch_records.validate_request_data(request)
    observations = view.document(report["observations"], "artifacts/installed-observations.json", integers_only=True)
    commands = _commands(view, report, request, api)
    require(sum(row["duration_seconds"] for row in report["commands"]) <= (finished - started).total_seconds() + 2,
            "framework commands exceed the recorded execution interval")
    return report, request, observations, commands, source


def _source_and_python(outer, report, source, native, python, api, revision, fmt):
    """Join separately validated sources and reconcile the copied Python packet."""
    same(source["checkout"], native["python_source"]["checkout"], "Python/framework checkout identity")
    python_files = _inventory(native["python_source"]["files"], api, "Python source files")
    torch_files = _inventory(source["files"], api, "framework source files")
    expected = {**python_files, **{name: torch_files[name] for name in TORCH_SOURCE_FILES}}
    same(source["files"], [expected[name] for name in sorted(expected)], "Python/framework source projection")
    tr, pr = outer.subview("torch"), native["python_report"]
    for row in pr["retained_sources"]:
        same(tr.identity(row["path"]), row, "Python/framework retained source bytes")
    same(report["python_input"], {
        "kind": "completed_top_level_p05_packet", "directory": pr["paths"]["output"],
        "work": pr["paths"]["work"], "retained_prefix": "python",
        # The producer sorted pathlib paths by components; ZIP member order is
        # lexical text. Preserve the recorded order while deriving every row.
        "files": sorted(outer.subview("python").inventory(), key=lambda row: PurePosixPath(row["path"])),
    }, "framework Python input identity")
    same(tr.document(report["python_input_after"], "snapshots/python-input-after.json"),
         report["python_input"]["files"], "framework Python input stability")
    same(tr.document(report["python_report"], "python/report.json"), pr, "framework Python report")
    same(report["bundle_validation"], {
        "kind": "in_process", "function": "p05_bundle.create_bundle", "source": pr["paths"]["source"],
        "build": pr["paths"]["native_build"], "native_output": pr["paths"]["native_output"],
        "destination": str(_absolute(report["paths"]["output"]) / "artifacts/bundle"),
        "format": fmt, "state": "passed",
    }, "framework bundle validation receipt")
    wheel = report["python_revalidation"].get("wheel") if type(report["python_revalidation"]) is dict else None
    api.descriptor(wheel)
    require(wheel in pr["packages"], "revalidated wheel is not a Python package artifact")
    same(report["python_revalidation"], {
        "outcome": "pass", "comparison": python, "source_revision": revision,
        "native_qualification_id": pr["native_qualification_id"],
        "matmul_qualification_id": pr["matmul_qualification_id"],
        "bundle_sha256": report["bundle_manifest"]["sha256"], "wheel": wheel,
        "completed_native_and_python_launches": native["counts"]["total_launches"] + python["counts"]["total_launches"],
        "copied_packet_additional_launches": 0,
    }, "framework Python revalidation summary")


def _packet_members(outer, report, native, api):
    """Require the full original inventory; descriptors cannot hide extra files."""
    python = outer.subview("python")
    pr = native["python_report"]
    py_names = {"report.json"}
    for key in ("bundle_manifest", "observations", "source_before", "source_after", "tools_before", "tools_after",
                "selection", "matmul_binding", "wheel_inventory", "package_source_stage",
                "extracted_sdist_before_build", "installed_before", "installed_after", "installed_request",
                "package_tools_before", "package_tools_after", "native_report"):
        api.descriptor(pr[key])
        py_names.add(pr[key]["path"])
    py_names.update(row["log"] for row in pr["commands"])
    py_names.update(row["path"] for row in pr["retained_sources"])
    py_names.update(row["path"] for row in pr["packages"])
    for prefix, rows in (
        ("native", pr["native_input"]["files"]),
        ("artifacts/native-matmul", pr["retained_native_matmul"]),
        ("artifacts/native-model", pr["retained_native_model"]),
        ("artifacts/bundle", pr["bundle_artifacts"]),
        ("artifacts/installed", python.document(pr["installed_before"], "snapshots/installed-before.json")),
    ):
        py_names.update(prefix + "/" + row["path"] for row in rows)
    py_names.update("artifacts/sdist-pin/" + name for name in (
        "manifest.json", "source_inventory.json", "p05_build_config.h"))
    same(list(python.files()), sorted(py_names), "complete Python member inventory")
    torch = outer.subview("torch")
    torch_names = {"report.json", report["installed_wheel"]["path"], "artifacts/installed-observations.json"}
    for key in ("framework_after", "framework_before", "framework_wheel_payload", "installed_after",
                "installed_before", "installed_helpers", "installed_request", "python_input_after",
                "source_after", "source_before", "venv_seed", "wheelhouse_after"):
        api.descriptor(report[key])
        same(report[key]["path"], "snapshots/" + key.replace("_", "-") + ".json", "framework snapshot path")
        torch_names.add(report[key]["path"])
    torch_names.update(row["log"] for row in report["commands"])
    torch_names.update(row["path"] for row in report["retained_sources"])
    torch_names.update("artifacts/bundle/" + row["path"] for row in report["bundle_artifacts"])
    torch_names.update("artifacts/checker/" + name for name in installation_replay.HELPERS)
    torch_names.update("python/" + name for name in py_names)
    same(list(torch.files()), sorted(torch_names), "complete framework member inventory")
    expected = set(SUPPLEMENTARY_FILES)
    expected.update("python/" + name for name in py_names)
    expected.update("torch/" + name for name in torch_names)
    # The native verifier independently derives this complete packet inventory.
    expected.update("native-model/" + name for name in outer.subview("native-model").files())
    same(list(outer.files()), sorted(expected), "complete outer archive member inventory")


def _hosted(outer, revision, fmt, api, report):
    job = outer.json("job.json")
    _fields(job, ("GITHUB_EVENT_NAME", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID", "GITHUB_SHA",
                  "P05_BACKEND", "P05_FORMAT", "acceptance_claimed", "native_execution",
                  "python_execution", "scope", "torch_execution", "workflow_sha256"), "provider job")
    for key, expected in (("GITHUB_SHA", revision), ("P05_BACKEND", "simx"), ("P05_FORMAT", fmt),
                          ("scope", "simx-installed-pytorch"), ("acceptance_claimed", False),
                          ("native_execution", "not_run"), ("python_execution", "not_run"),
                          ("torch_execution", "not_run")):
        same(job.get(key), expected, "hosted identity " + key)
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(type(job.get(key)) is str and re.fullmatch(r"[1-9][0-9]{0,19}", job[key]), "invalid provider run identity")
    require(job["GITHUB_EVENT_NAME"] in ("push", "pull_request", "workflow_dispatch"), "invalid provider event")
    body = outer.read("workflow.yml", limit=1024**2)
    require(body and type(job["workflow_sha256"]) is str and SHA256.fullmatch(job["workflow_sha256"]),
            "invalid retained workflow identity")
    same(hashlib.sha256(body).hexdigest(), job.get("workflow_sha256"), "retained workflow identity")
    provision = outer.json("python-provision.json")
    _fields(provision, ("build_requirements", "executable", "implementation", "platform", "python_version"),
            "Python provision")
    for key, expected in (("python_version", [3, 12, 14]), ("implementation", "CPython"), ("platform", "linux"),
                          ("build_requirements", {"packaging": "26.3", "setuptools": "84.2.1", "wheel": "0.48.0"})):
        same(provision.get(key), expected, "provisioned Python " + key)
    _absolute(provision["executable"])
    same(provision["executable"], report["provisioning_interpreter"]["path"], "provisioned interpreter path")
    return {"run_id": job["GITHUB_RUN_ID"], "run_attempt": job["GITHUB_RUN_ATTEMPT"],
            "event": job.get("GITHUB_EVENT_NAME"), "workflow_sha256": job["workflow_sha256"],
            "job_record_stage": "initial_pre_execution_identity", "origin_authenticated_by_replay": False}


def _supplementary(outer, report, source, native, api, revision, fmt):
    """Check bounded envelopes without claiming host fault/build semantics."""
    prep = outer.json("preparation.json")
    _fields(prep, ("acceptance_claimed", "backend", "budget", "cache_quarantine", "contract_id",
                   "dependency_identities", "expected_revision", "formats", "limitations", "native_execution",
                   "outcome", "preparation_sources", "reason", "resources", "schema_version", "source",
                   "third_party_cache_key", "tool_identities", "toolchain_cache_key", "toolchain_id", "tools_dir",
                   "tools_relocated"), "supplementary preparation report")
    for key, value in (("schema_version", 1), ("contract_id", "p04-hosted-preparation-v1"),
                       ("acceptance_claimed", False), ("native_execution", "not_run"), ("outcome", "pass"),
                       ("reason", None), ("backend", "simx"), ("formats", [fmt]),
                       ("expected_revision", revision), ("tools_relocated", True)):
        same(prep[key], value, "preparation envelope " + key)
    same(prep["source"], source["checkout"], "preparation source envelope")
    same(prep["tools_dir"], native["python_report"]["paths"]["tools"], "preparation tools root")
    same(outer.json("preparation.log"), {"outcome": "pass", "reason": None, "native_execution": "not_run"},
         "preparation envelope log")
    for name, path, acceptance in (
        ("native-execution.log", native["native_report"]["paths"]["output"], False),
        ("execution.log", native["python_report"]["paths"]["output"], True),
        ("torch-execution.log", report["paths"]["output"], True),
    ):
        expected = {"outcome": "pass", "reason": None, "report": str(_absolute(path) / "report.json")}
        if acceptance:
            expected["acceptance_claimed"] = False
        same(outer.json(name), expected, "execution envelope " + name)
    torch = outer.subview("torch")
    for name, key in (("p05_torch_contract.json", "contract"), ("p05_torch_requirements.lock", "requirements")):
        require(outer.read(name) == torch.verified(report[key]), "outer framework input copy differs: " + name)
    host = outer.json("torch-host.json")
    _fields(host, ("schema_version", "scope", "acceptance_claimed", "native_execution", "python_version",
                   "outcome", "source_files", "tests", "torch_version", "tests_run", "failures", "errors", "skips"),
            "supplementary host report")
    for key, value in (("schema_version", 1), ("scope", "host-only-real-pytorch-scripted-native-mock"),
                       ("acceptance_claimed", False), ("native_execution", "not_run"), ("outcome", "pass"),
                       ("python_version", "3.12.14"), ("torch_version", "2.15.0+cpu"), ("tests_run", 45),
                       ("failures", 0), ("errors", 0), ("skips", 0)):
        same(host[key], value, "host envelope " + key)
    require(type(host["tests"]) is list and len(host["tests"]) == 45
            and type(host["source_files"]) is list and len(host["source_files"]) == 4,
            "invalid supplementary host inventory envelope")
    fault = outer.json("torch-native-host/report.json")
    _fields(fault, ("acceptance_claimed", "backend_execution", "build", "child_timeout_seconds", "completed",
                    "format", "native_accelerator_execution", "outcome", "python_version", "results", "scenario_count",
                    "schema_version", "scope", "seconds", "test_sha256"), "supplementary host fault report")
    for key, value in (("schema_version", 1), ("scope", "host-only-real-pytorch-compiled-native-fault-runtime"),
                       ("acceptance_claimed", False), ("backend_execution", "not_run"),
                       ("native_accelerator_execution", "not_run"), ("outcome", "pass"), ("format", fmt),
                       ("child_timeout_seconds", 30), ("completed", 9), ("scenario_count", 9)):
        same(fault[key], value, "host fault envelope " + key)
    require(type(fault["results"]) is list and len(fault["results"]) == len(HOST_SCENARIOS),
            "invalid supplementary host fault inventory envelope")
    same(outer.identity("torch-native-host/test.snapshot.py")["sha256"], fault["test_sha256"],
         "host fault source snapshot identity")
    rows = [outer.identity(name, limit=16 * MIB) for name in SUPPLEMENTARY_FILES]
    require(sum(row["size_bytes"] for row in rows) <= 64 * MIB, "supplementary packets exceed their byte bound")
    return {"scope": "bounded-supplementary-envelopes-and-retained-bytes",
            "member_count": len(rows), "size_bytes": sum(row["size_bytes"] for row in rows),
            "host_fault_semantics_revalidated": False, "preparation_semantics_revalidated": False,
            "host_test_results_revalidated": False, "additional_native_launches_counted": 0,
            "retained_outcomes": {"preparation": prep["outcome"], "scripted_host": host["outcome"],
                                  "compiled_fault_host": fault["outcome"]}}


def replay_archive(path, sha256, *, expected_revision, expected_format):
    require(type(expected_revision) is str and REVISION.fullmatch(expected_revision), "exact execution revision required")
    require(expected_format in ("fp16", "bf16"), "expected format must be fp16 or bf16")
    require(type(sha256) is str and SHA256.fullmatch(sha256), "external original archive SHA-256 required")
    api = _archive_api()
    sources = _reader_sources()
    same(sources, READER_SOURCES, "trusted reader inputs since import")
    with api.ArchiveReader(Path(path), sha256) as archive:
        outer = archive.view()
        report, request, observations, commands, source = _report(outer.subview("torch"), api,
                                                               expected_revision, expected_format)
        hosted = _hosted(outer, expected_revision, expected_format, api, report)
        native = verify_native(outer, expected_revision=expected_revision, expected_format=expected_format)
        identities = verify_installations(outer, report, native,
                                          expected_revision=expected_revision, expected_format=expected_format)
        python = python_records.verify_retained_observations(
            native["python_observations"], native["python_request"],
            retained_identity=identities["python_identity"], native_matmuls=native["native_matmuls"],
            native_models=native["native_models"], model_cases=native["model_cases"], raw_log=native["python_raw_log"])
        framework = torch_records.verify_retained_observations(
            observations, request, retained_identity=identities["torch_identity"],
            adapter_bytes=identities["adapter_bytes"], native_matmuls=native["native_matmuls"],
            native_models=native["native_models"], model_cases=native["model_cases"],
            raw_log=commands["installed-framework-matrix"])
        same(python, native["python_report"]["comparison"], "plain Python comparison summary")
        same(framework, report["comparison"], "framework comparison summary")
        _source_and_python(outer, report, source, native, python, api, expected_revision, expected_format)
        _packet_members(outer, report, native, api)
        supplementary = _supplementary(outer, report, source, native, api, expected_revision, expected_format)
        total = (framework["counts"]["total_launches"] + native["counts"]["total_launches"]
                 + python["counts"]["total_launches"])
        counts = {"copied_packet_additional_launches": 0, "distinct_total_launches": total,
                  "framework_event_profile_pairs": framework["event_profile_pairs"],
                  "framework_launches": framework["counts"]["total_launches"],
                  "framework_operator_calls": framework["operator_calls"],
                  "native_comparison_launches": native["counts"]["total_launches"],
                  "plain_python_launches": python["counts"]["total_launches"]}
        same(counts, {"copied_packet_additional_launches": 0, "distinct_total_launches": 108,
                      "framework_event_profile_pairs": 180, "framework_launches": 36,
                      "framework_operator_calls": 16, "native_comparison_launches": 36,
                      "plain_python_launches": 36}, "derived one-format execution population")
        same(report["execution_counts"], counts, "framework execution counts")
        already_read = {row["path"] for row in archive.receipt()["read_files"]}
        for name in outer.files():
            if name not in already_read:
                outer.identity(name)
        receipt = archive.receipt()
        same([row["path"] for row in receipt["read_files"]], list(outer.files()), "complete archive byte coverage")
        result = {"schema_version": 1, "contract_id": CONTRACT_ID, "outcome": "pass",
                  "scope": "one-format-retained-installed-pytorch-consistency",
                  "execution_revision": expected_revision, "format": expected_format,
                  "provider_record": hosted, "native_execution": "not_run", "retained_code_executed": False,
                  "acceptance_claimed": False, "phase_acceptance": False, "counts": counts,
                  "host_fault_semantics_revalidated": False, "supplementary": supplementary,
                  "python_comparison": python, "framework_comparison": framework,
                  "installation": identities["summary"], "reader_sources": sources,
                  "archive_read": receipt, "limitations": list(LIMITATIONS)}
    same(_reader_sources(), sources, "trusted reader sources during replay")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path, help="absolute canonical original ZIP path (any filename)")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--format", required=True, choices=("fp16", "bf16"))
    args = parser.parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256,
                                expected_revision=args.expected_revision, expected_format=args.format)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, RuntimeError, OverflowError) as error:
        print(json.dumps({"schema_version": 1, "contract_id": CONTRACT_ID, "outcome": "fail",
                          "reason": str(error), "native_execution": "not_run", "retained_code_executed": False,
                          "acceptance_claimed": False, "phase_acceptance": False}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
