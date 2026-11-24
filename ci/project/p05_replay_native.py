# SPDX-License-Identifier: Apache-2.0
"""Reconstruct P05 native comparisons from retained data and trusted fixtures.

Only the reviewed local fixture adapters and inert P03/P04 parsers are used.
Producer paths remain lexical strings; retained source and binaries are never
imported, extracted, executed, or used as arithmetic reference implementations.
The caller owns the digest-pinned ArchiveReader and its final stability check.
"""

from __future__ import annotations

import ast
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
from p02_matrix_records import PROFILE_SHA256, require, validate_header_macros
from p02_wmma_fixtures import load_cases as load_matmul_cases
from p03_execution_records import qualification_id, validate_records, verify_output as verify_matmul
from p04_execution_records import verify_output as verify_model
from p04_fixture_adapter import load_cases as load_model_cases
from p05_execution_records import select_matmul_cases, select_model_cases


ROOT = Path(__file__).resolve().parents[2]
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
REVISION = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FIXTURES = {
    "p02_tfr_v1.json": "0d8b173af178875274a7bf29886a51838be8cdb54224d55353959a639a5ea6c3",
    "p02_layout_v1.json": "0543f9f4208de3ff4743fe1894d97ccf3b8cca4707e9a26acd1f3dde884725b2",
    "p02_wmma_numerical_v1.json": "4102d74024e92e9887d7324b9326c0d6ad1fff206b5fad33f45c530d5bd03a73",
    "p04_tiny_mlp_v1.json": "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03",
}
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "hw/VX_config.vh", "hw/VX_types.vh", "sim/rtlsim/verilator.vlt")
RUNTIME = ("sw/kernel/libvortex2.a", "sw/runtime/libvortex.so", "sw/runtime/libvortex-simx.so",
           "sw/runtime/libsimx.so", "sw/runtime/simx_rt_config.stamp", "sw/runtime/simx_config.stamp")
DEPENDENCIES = ("third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
                "third_party/ramulator/libramulator.so", "third_party/ramulator_ext/libramulator-vortex.so")
COMMAND_FIELDS = {"id", "argv", "cwd", "environment", "log", "timeout_seconds", "outcome",
                  "exit_code", "reason", "process_started", "duration_seconds", "log_sha256",
                  "log_size_bytes", "peak_rss_bytes", "cleanup_complete", "limitations"}
NATIVE_HELPERS = tuple(sorted("ci/project/" + name + ".py" for name in (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract", "baseline_packet_io",
    "baseline_process", "compiler_records", "p02_fixture_oracle", "p02_layout_fixture_oracle",
    "p02_matrix", "p02_matrix_records", "p02_wmma_fixtures", "p02_wmma_numerical_fixture_oracle",
    "p03_execute", "p03_execution_records", "p04_execute", "p04_execution_records",
    "p04_fixture_adapter", "p04_model_contract", "p04_reference", "preflight")))
PYTHON_HELPERS = tuple(sorted((*NATIVE_HELPERS, "ci/project/p05_bundle.py", "ci/project/p05_execute.py",
                               "ci/project/p05_execution_records.py", "python/vortex_ai/_bundle.py")))
# Freeze the retention contract of the historical c0b44ce6 producers, rather
# than letting a report choose which source bytes are mandatory. The native
# set is p02 TOOLING/CORPUS + p03/p04 SOURCE_FILES + loaded helpers and the nine
# runtime files present at that revision. The Python set is p05 SOURCE_FILES
# + loaded helpers + _bundle.SOURCE_PATHS. These are retained subsets only:
# the larger source snapshot still contains identities without source bytes.
NATIVE_RETAINED_SOURCES = tuple(sorted(set(NATIVE_HELPERS + (
    "ci/project/fixtures/p02_layout_v1.json", "ci/project/fixtures/p02_tfr_v1.json",
    "ci/project/fixtures/p02_wmma_numerical_v1.json", "ci/project/fixtures/p04_tiny_mlp_v1.json",
    "ci/project/p03_operator_manifest.json", "ci/project/p04_model_manifest.json",
    "docs/designs/mlp_execution_records_v1.md", "profiles/p02-tfr.json",
    "sim/common/cmd_processor.cpp", "sw/common/ai_matmul_args.h", "sw/common/ai_matmul_profile.h",
    "sw/kernel/ai/matmul.cpp", "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h",
    "sw/runtime/ai/runtime.cpp", "sw/runtime/ai/runtime.h", "sw/runtime/ai/mlp_runtime.cpp",
    "sw/runtime/ai/mlp_runtime.h", "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_host.h",
    "sw/runtime/common/queue.cpp", "sw/runtime/common/buffer.cpp", "sw/runtime/common/device.cpp",
    "sw/runtime/common/module.cpp", "sw/runtime/common/event.cpp", "sw/runtime/common/vortex2_internal.h",
    "sw/runtime/simx/vortex.cpp", "sw/runtime/rtlsim/vortex.cpp",
    "tests/regression/ai_matmul/Makefile", "tests/regression/ai_matmul/main.cpp",
    "tests/regression/ai_mlp/Makefile", "tests/regression/ai_mlp/main.cpp",
    "tests/regression/ai_mlp/records.h", "tests/regression/ai_mlp/p04_fixtures.h",
    "tests/regression/sgemm_tcu/p02_fixtures.h", "tests/runtime/Makefile",
    "tests/runtime/test_ai_lifecycle.cpp",
))))
PYTHON_RETAINED_SOURCES = tuple(sorted(set(PYTHON_HELPERS + (
    "ci/project/p05_installed_check.py", "python/README.md", "LICENSE",
    "pyproject.toml", "setup.py", "MANIFEST.in", "python/vortex_ai/__init__.py",
    "python/vortex_ai/_api.py", "python/vortex_ai/launch.py", "python/vortex_ai/torch_ops.py",
    "python/native/module.cpp", "python/native/runtime_loader.cpp", "python/native/runtime_loader.h",
    "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h", "sw/runtime/ai/runtime.cpp",
    "sw/runtime/ai/runtime.h", "sw/runtime/ai/mlp_runtime.cpp", "sw/runtime/ai/mlp_runtime.h",
    "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_host.h", "sw/runtime/include/vortex2.h",
    "sw/common/ai_matmul_args.h", "tests/regression/ai_mlp/p04_fixtures.h",
    "tests/regression/ai_mlp/records.h",
))))


def _same(actual, expected, label):
    # JSON canonical equality preserves bool/int and int/float distinctions.
    require(json.dumps(actual, sort_keys=True, separators=(",", ":"), allow_nan=False)
            == json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False),
            label + " differs")


def _fields(value, expected, label):
    require(type(value) is dict and set(value) == set(expected), label + ": invalid fields")


def _uint(value, maximum, label):
    require(type(value) is int and 0 <= value <= maximum, label + ": invalid integer")


def _path(value, *, absolute=False):
    require(type(value) is str and value and "\\" not in value
            and len(value.encode("utf-8")) <= 4096
            and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value),
            "invalid recorded path")
    path = PurePosixPath(value)
    require(str(path) == value and ".." not in path.parts and value not in (".", "/")
            and len(path.parts) <= 64 and path.is_absolute() is absolute and not value.startswith("//")
            and (absolute or not re.match(r"[A-Za-z]:", value)),
            "noncanonical recorded path")
    return path


def _descriptor(row):
    _fields(row, ("path", "sha256", "size_bytes"), "descriptor")
    _path(row["path"])
    require(type(row["sha256"]) is str and SHA256.fullmatch(row["sha256"]), "invalid SHA-256")
    _uint(row["size_bytes"], MAX_MEMBER_BYTES, "descriptor size")


def _inventory(rows, label, *, expected=None, sorted_paths=False):
    require(type(rows) is list and 0 < len(rows) <= 20000, label + ": invalid inventory")
    result = {}
    for row in rows:
        _descriptor(row)
        require(row["path"] not in result, label + ": duplicate inventory path")
        result[row["path"]] = row
    if expected is not None:
        _same(list(result), list(expected), label + " paths")
    if sorted_paths:
        _same(list(result), sorted(result), label + " order")
    return result


def _copies(left, right, label):
    """Require complete byte equality, including otherwise unused members."""
    _same(list(left.files()), list(right.files()), label + " members")
    for name in left.files():
        a = left.read(name, limit=MAX_MEMBER_BYTES)
        b = right.read(name, limit=MAX_MEMBER_BYTES)
        require(a == b, label + ": copied member bytes differ: " + name)


def _text(view, name):
    try:
        return view.read(name, limit=MAX_LOG_BYTES).decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("native retained log is not UTF-8: " + name) from error


def _finished(report, contract_id):
    require(type(report) is dict, "missing execution report")
    for name, expected in (("schema_version", 1), ("contract_id", contract_id), ("state", "finished"),
                           ("outcome", "pass"), ("reason", None), ("development", False),
                           ("acceptance_claimed", False), ("phase_complete", False), ("iterations", 2)):
        _same(report.get(name), expected, "report." + name)
    times = []
    for name in ("started_at", "finished_at"):
        value = report.get(name)
        require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", value),
                "invalid execution timestamp")
        times.append(datetime.fromisoformat(value))
    require(times[0] <= times[1], "execution timestamps are reversed")
    require(type(report.get("limitations")) is list and report["limitations"], "missing execution limitations")


def _source(view, report, revision):
    source = view.document(report["source_before"], "snapshots/source-before.json")
    _same(view.document(report["source_after"], "snapshots/source-after.json"), source,
          "source before/after")
    _same(report["source_stable"], True, "source stability")
    _fields(source, ("checkout", "files"), "source snapshot")
    checkout = source["checkout"]
    _fields(checkout, ("revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                       "pins", "blockers", "inputs", "outcome"), "source checkout")
    for key, expected in (("revision", revision), ("dirty", False), ("changed_paths", []),
                          ("untracked_paths", []), ("blockers", []), ("outcome", "pass")):
        _same(checkout[key], expected, "checkout." + key)
    require(type(checkout["tree"]) is str and REVISION.fullmatch(checkout["tree"]), "invalid source tree")
    modules = checkout["submodules"]
    _fields(modules, ("declared_count", "entries", "errors"), "submodules")
    _same(modules["errors"], [], "submodule errors")
    _uint(modules["declared_count"], 100, "submodule declarations")
    require(modules["declared_count"] > 0 and type(modules["entries"]) is list
            and len(modules["entries"]) >= modules["declared_count"], "incomplete submodule inventory")
    seen = set()
    for row in modules["entries"]:
        _fields(row, ("path", "revision", "status"), "submodule")
        _path(row["path"])
        require(row["path"] not in seen and row["status"] == "initialized"
                and type(row["revision"]) is str and REVISION.fullmatch(row["revision"]),
                "invalid source submodule")
        seen.add(row["path"])
    require(type(checkout["pins"]) is dict and checkout["pins"], "missing source version pins")
    inventory = _inventory(source["files"], "source files", sorted_paths=True)
    inputs = _inventory(checkout["inputs"], "checkout inputs", expected=(
        "VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml", "VX_types.toml",
        "ci/gen_config.py", "ci/blackbox.sh"))
    for name, row in inputs.items():
        # The original source snapshot does not include blackbox.sh in its
        # larger files inventory. Its before/after checkout receipt remains
        # an identity observation, not newly available source bytes.
        if name != "ci/blackbox.sh":
            _same(inventory.get(name), row, "checkout input " + name)
    native = report["contract_id"] == "p04-managed-model-execution-v1"
    expected_sources = NATIVE_RETAINED_SOURCES if native else PYTHON_RETAINED_SOURCES
    retained = _inventory(report["retained_sources"], "retained sources", sorted_paths=True,
                          expected=("artifacts/source/" + name for name in expected_sources))
    _same(list(retained), [name for name in view.files() if name.startswith("artifacts/source/")],
          "retained source membership")
    for name, row in retained.items():
        relative = name.removeprefix("artifacts/source/")
        _same(inventory.get(relative), dict(row, path=relative), "retained source identity " + relative)
        _same(view.identity(name), row, "retained source bytes " + relative)
    expected_helpers = NATIVE_HELPERS if native else PYTHON_HELPERS
    helpers = _inventory(report["loaded_helpers"], "loaded helpers", expected=expected_helpers, sorted_paths=True)
    for name, row in helpers.items():
        _same(retained.get("artifacts/source/" + name), dict(row, path="artifacts/source/" + name),
              "loaded helper identity " + name)
    return source


def _tools(view, report):
    tools = view.document(report["tools_before"], "snapshots/tools-before.json")
    _same(view.document(report["tools_after"], "snapshots/tools-after.json"), tools, "tools before/after")
    expected = {"make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl", "clang", "clang++",
                "llvm-objcopy", "llvm-objdump", "riscv-gcc", "riscv-gcc-ar", "riscv-objcopy", "riscv-objdump",
                "libc64/lib/libc.a", "libc64/lib/libm.a", "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"}
    _fields(tools, expected, "tool inventory")
    for row in tools.values():
        _fields(row, ("path", "resolved_path", "sha256", "size_bytes"), "tool identity")
        _path(row["path"], absolute=True)
        _path(row["resolved_path"], absolute=True)
        require(type(row["sha256"]) is str and SHA256.fullmatch(row["sha256"]), "invalid tool digest")
        _uint(row["size_bytes"], 1 << 40, "tool size")
        require(row["size_bytes"] > 0, "empty tool identity")
    return tools


def _budget(report, *, python=False):
    budget = report["budget"]
    expected = {"min_free_bytes", "max_rss_bytes", "max_log_bytes", "jobs"}
    _fields(budget, expected | ({"package_jobs"} if python else set()), "execution budget")
    for key, value in (("min_free_bytes", 15 * 1024**3), ("max_rss_bytes", 4 * 1024**3),
                       ("max_log_bytes", MAX_LOG_BYTES)):
        _same(budget[key], value, "execution budget " + key)
    require(type(budget["jobs"]) is int and budget["jobs"] in (1, 2), "invalid job count")
    if python:
        _same(budget["package_jobs"], 1, "package jobs")
    for key in ("resources_before", "resources_after"):
        resource = report[key]
        _fields(resource, ("available_memory_bytes", "free_disk_bytes"), key)
        _fields(resource["free_disk_bytes"], ("source", "tools", "work", "output"), key + " disk")
        for value in resource["free_disk_bytes"].values():
            _uint(value, 1 << 64, key + " disk bytes")
        if resource["available_memory_bytes"] is not None:
            _uint(resource["available_memory_bytes"], 1 << 64, key + " memory")
    before = report["resources_before"]
    require(type(before["available_memory_bytes"]) is int
            and before["available_memory_bytes"] >= budget["max_rss_bytes"]
            and all(value >= budget["min_free_bytes"] for value in before["free_disk_bytes"].values()),
            "initial resources were below the recorded budget")
    return budget


def _commands(view, report, ids):
    rows = report["commands"]
    require(type(rows) is list and len(rows) == len(ids), "command inventory length differs")
    _same([row.get("id") for row in rows], ids, "command membership/order")
    _same([name for name in view.files() if name.startswith("logs/")],
          sorted("logs/" + name + ".log" for name in ids), "command log membership")
    result = {}
    for row in rows:
        _fields(row, COMMAND_FIELDS, "command")
        name = row["id"]
        for key, expected in (("outcome", "pass"), ("exit_code", 0), ("reason", None),
                              ("process_started", True), ("cleanup_complete", True)):
            _same(row[key], expected, "command " + name + " " + key)
        require(type(row["argv"]) is list and 0 < len(row["argv"]) <= 128
                and all(type(arg) is str and "\x00" not in arg for arg in row["argv"]), "invalid argv")
        _path(row["argv"][0], absolute=True)
        _path(row["cwd"], absolute=True)
        require(type(row["environment"]) is dict and all(type(k) is str and type(v) is str
                and "\x00" not in k + v for k, v in row["environment"].items()), "invalid command environment")
        _uint(row["timeout_seconds"], 3600, "command timeout")
        require(row["timeout_seconds"] > 0, "missing command timeout")
        duration = row["duration_seconds"]
        require(type(duration) in (int, float) and math.isfinite(duration)
                and 0 <= duration <= row["timeout_seconds"] + 10, "command duration exceeds its bound")
        _uint(row["peak_rss_bytes"], report["budget"]["max_rss_bytes"], "command peak RSS")
        _same(row["limitations"], PROCESS_LIMITATIONS, "command monitor limitations")
        log = {"path": row["log"], "sha256": row["log_sha256"], "size_bytes": row["log_size_bytes"]}
        view.verified(log, "logs/" + name + ".log", limit=MAX_LOG_BYTES)
        result[name] = row
    return result


def _environment(paths, tools, jobs):
    entries = ([paths["host_bin"]] if paths["host_bin"] else [])
    entries += [str(PurePosixPath(tools["python3"]["path"]).parent), "/usr/bin", "/bin"]
    return {"PATH": ":".join(dict.fromkeys(entries)), "TMPDIR": paths["work"] + "/tmp",
            "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "CCACHE_DISABLE": "1", "OBJCACHE": "", "MAKEFLAGS": "-j" + str(jobs),
            "THREADS": str(jobs), "CMAKE_BUILD_PARALLEL_LEVEL": str(jobs)}


def _command_interval(report, commands):
    # _finished has validated UTC second-resolution endpoints; _commands has
    # validated finite, nonnegative durations. The producers run these commands
    # sequentially. Match the framework reader's bounded two-endpoint rounding
    # allowance; no per-command allowance can accumulate to hide an overrun.
    started, finished = (datetime.fromisoformat(report[key]) for key in ("started_at", "finished_at"))
    require(sum(row["duration_seconds"] for row in commands.values()) <= (finished - started).total_seconds() + 2,
            "commands exceed the recorded execution interval")


def _command(row, argv, cwd, environment, *, timeout=None, maximum=None):
    _same(row["argv"], [str(value) for value in argv], row["id"] + " argv")
    _same(row["cwd"], str(cwd), row["id"] + " cwd")
    _same(row["environment"], environment, row["id"] + " environment")
    if timeout is not None:
        _same(row["timeout_seconds"], timeout, row["id"] + " timeout")
    if maximum is not None:
        require(row["timeout_seconds"] <= maximum, row["id"] + " exceeds timeout maximum")


def _artifacts(app):
    return GENERATED + tuple(app + "/" + name for name in
                             ("Makefile", "config.stamp", PurePosixPath(app).name, "kernel.elf", "kernel.vxbin")) + RUNTIME


def _build_records(view, prefix, artifacts, *, source, build, jobs, fmt, app):
    def read(name):
        row = artifacts[name]
        return view.verified(dict(row, path=prefix + "/" + name), limit=MAX_LOG_BYTES).decode("utf-8")
    return validate_records(read("sw/runtime/simx_rt_config.stamp"), read("sw/runtime/simx_config.stamp"),
                            read(app + "/config.stamp"), driver="simx", fmt=fmt, source=source, build=build, jobs=jobs)


def _frozen_cases(view, fmt):
    for filename, digest in FIXTURES.items():
        name = "ci/project/fixtures/" + filename
        local = (ROOT / name).read_bytes()
        require(hashlib.sha256(local).hexdigest() == digest, "trusted frozen fixture bytes changed: " + filename)
        require(view.read("artifacts/source/" + name) == local, "retained frozen fixture differs: " + filename)
    require(hashlib.sha256(view.read("artifacts/source/profiles/p02-tfr.json")).hexdigest() == PROFILE_SHA256,
            "retained numerical profile differs")
    # ROOT is fixed by this reviewed module, never by an archive-supplied path.
    return (select_matmul_cases(load_matmul_cases(ROOT), fmt),
            select_model_cases(load_model_cases(ROOT), fmt))


def _native_commands(view, report, tools, compiler, binding_id, cases, revision, fmt):
    variant_id = "simx-" + fmt
    suffixes = ("configure", "header", "cpp-header-reproduce", "verilog-header-reproduce",
                "runtime", "application", "effective-header")
    ids = ["version-gpp", "version-clang", "version-make"]
    ids += [variant_id + "-" + suffix for suffix in suffixes]
    ids += [variant_id + "-" + case["id"] for case in cases]
    commands = _commands(view, report, ids)
    _command_interval(report, commands)
    paths, jobs = report["paths"], report["budget"]["jobs"]
    env = _environment(paths, tools, jobs)
    source, work = PurePosixPath(paths["source"]), PurePosixPath(paths["work"])
    build = work / variant_id
    app = build / "tests/regression/ai_mlp"
    for name in ("g++", "clang", "make"):
        _command(commands["version-" + name.replace("+", "p")], [tools[name]["path"], "--version"], work, env, timeout=30)
    _command(commands[variant_id + "-configure"], [source / "configure", "--xlen=64", "--profile=p02-tfr",
             "--osversion=ubuntu/focal", "--tooldir=" + paths["tools"]], build, env, timeout=120)
    header = [tools["g++"]["path"], "-E", "-dM", "-x", "c++"]
    tail = ["-include", build / "sw/VX_config.h", "/dev/null"]
    _command(commands[variant_id + "-header"], header + ["-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64"] + tail,
             build, env, timeout=30)
    for language, suffix in (("cpp", "h"), ("verilog", "vh")):
        _command(commands[variant_id + "-" + language + "-header-reproduce"],
                 [tools["python3"]["path"], source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                  "--profile=p02-tfr", "--format=" + language,
                  "--output=" + str(build / "p04-header-check" / ("VX_config." + suffix))],
                 build, dict(env, XLEN="64"), timeout=30)
    make = [tools["make"]["path"], "--no-print-directory", "-j" + str(jobs), "THREADS=" + str(jobs),
            "VERILATOR_PATH=" + paths["verilator"]]
    for suffix, target in (("runtime", "runtime-simx"), ("application", "all")):
        _command(commands[variant_id + "-" + suffix], make + [target], app,
                 dict(env, CONFIGS="-DITYPE=" + fmt + " -DOTYPE=fp32 -DKUNROLL=1"), maximum=1800)
    _command(commands[variant_id + "-effective-header"], header + compiler[1]["macro_flags"] + tail,
             build, env, timeout=30)
    for case in cases:
        _command(commands[variant_id + "-" + case["id"]], [app / "ai_mlp", "--case", case["id"],
                 "--iterations", "2", "--module", app / "kernel.vxbin", "--qualification-id", binding_id,
                 "--backend", "simx", "--source-revision", revision], app,
                 dict(env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(build / "sw/runtime")), maximum=180)
    return commands


def _package_probe():
    """Read the reviewed literal as data, without importing the producer."""
    tree = ast.parse((ROOT / "ci/project/p05_execute.py").read_text(encoding="utf-8"))
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "PACKAGE_PROBE" for target in node.targets)]
    require(len(values) == 1 and type(values[0]) is str, "trusted package probe literal is unavailable")
    return values[0]


def _python_commands(view, report, tools, compiler, binding_id, cases, request):
    ids = ["package-tools-before", "native-matmul-build", "native-matmul-effective-header"]
    ids += ["native-" + case["id"] for case in cases]
    ids += ["package-bound-sdist", "package-offline-wheel", "package-create-venv",
            "package-install-wheel", "installed-matrix", "package-tools-after"]
    commands = _commands(view, report, ids)
    _command_interval(report, commands)
    paths, jobs = report["paths"], report["budget"]["jobs"]
    env = _environment(paths, tools, jobs)
    package_env = dict(_environment(paths, tools, 1), CC=tools["gcc"]["path"], CXX=tools["g++"]["path"],
                       AR=tools["ar"]["path"], MAX_JOBS="1")
    work, output, build = (PurePosixPath(paths[key]) for key in ("work", "output", "native_build"))
    app = build / "tests/regression/ai_matmul"
    make = [tools["make"]["path"], "--no-print-directory", "-j" + str(jobs), "THREADS=" + str(jobs),
            "VERILATOR_PATH=" + paths["verilator"], "all"]
    _command(commands["native-matmul-build"], make, app,
             dict(env, CONFIGS="-DITYPE=" + report["format"] + " -DOTYPE=fp32 -DKUNROLL=1"), maximum=1800)
    _command(commands["native-matmul-effective-header"], [tools["g++"]["path"], "-E", "-dM", "-x", "c++",
             *compiler[1]["macro_flags"], "-include", build / "sw/VX_config.h", "/dev/null"], build, env, timeout=30)
    for case in cases:
        _command(commands["native-" + case["id"]], [app / "ai_matmul", "--case", case["id"], "--iterations", "2",
                 "--module", app / "kernel.vxbin", "--qualification-id", binding_id], app,
                 dict(env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(build / "sw/runtime")), maximum=180)
    python = [tools["python3"]["path"], "-I", "-B"]
    for when in ("before", "after"):
        _command(commands["package-tools-" + when], python + ["-c", _package_probe()], work, package_env, timeout=60)
    stage = work / "package-source"
    _command(commands["package-bound-sdist"], python + [stage / "setup.py", "egg_info", "sdist", "--dist-dir",
             output / "packages/sdist"], stage, dict(package_env, VORTEX_AI_BUNDLE=str(output / "artifacts/bundle")), maximum=1800)
    extracted = work / "extracted-sdist/vortex_ai-0.1.0"
    _command(commands["package-offline-wheel"], python + [extracted / "setup.py", "build", "--build-base",
             work / "package-build", "build_ext", "--parallel", "1", "bdist_wheel", "--dist-dir",
             output / "packages/wheel", "--bdist-dir", work / "wheel-stage"], extracted, package_env, maximum=1800)
    venv = work / "venv"
    _command(commands["package-create-venv"], python + ["-m", "venv", "--copies", venv], work, package_env, timeout=120)
    packages = _inventory(report["packages"], "Python package files")
    wheels = [name for name in packages if name.startswith("packages/wheel/") and name.endswith(".whl")]
    require(len(wheels) == 1, "missing or ambiguous bound wheel")
    _command(commands["package-install-wheel"], [venv / "bin/python", "-I", "-B", "-m", "pip", "--isolated",
             "install", "--no-index", "--no-deps", "--no-compile", "--disable-pip-version-check", output / wheels[0]],
             work, package_env, timeout=120)
    installed = work / "installed-check"
    _command(commands["installed-matrix"], [venv / "bin/python", "-I", "-B", "-m", "vortex_ai.launch", "--bundle",
             output / "artifacts/bundle", "--", installed / "p05_installed_check.py", "--request",
             installed / "request.json", "--output", installed / "observations.json"], installed, package_env, maximum=2940)
    _same(request["expected_prefix"], str(venv), "Python request prefix")
    _same(request["binding"]["bundle_root"], str(output / "artifacts/bundle"), "Python request bundle")
    return commands


def _results(native_view, python_view, native_report, python_report, matmuls, models,
             model_binding_id, matmul_binding_id, revision, fmt):
    variant = native_report["variants"][0]
    expected_models = [case["id"] for case in models]
    expected_matmuls = [case["id"] for case in matmuls]
    _same([row.get("id") for row in variant["cases"]], expected_models, "native model observation membership")
    _same([row.get("id") for row in python_report["native_matmuls"]], expected_matmuls,
          "native matmul observation membership")
    native_models, native_matmuls = {}, {}
    for case, saved in zip(models, variant["cases"]):
        _fields(saved, ("id", "outcome", "observations"), "native model case")
        _same(saved["outcome"], "pass", "native model outcome")
        rows = verify_model(_text(native_view, "logs/simx-" + fmt + "-" + case["id"] + ".log"), case, 2,
                            model_binding_id, backend="simx", source_revision=revision,
                            fixture_sha256=FIXTURES["p04_tiny_mlp_v1.json"])
        _same(saved["observations"], rows, "native model report/raw observations")
        native_models[case["id"]] = rows
    for case, saved in zip(matmuls, python_report["native_matmuls"]):
        _fields(saved, ("id", "observations"), "native matmul case")
        rows = verify_matmul(_text(python_view, "logs/native-" + case["id"] + ".log"), case, 2, matmul_binding_id)
        _same(saved["observations"], rows, "native matmul report/raw observations")
        native_matmuls[case["id"]] = rows
    observations = [row for rows in native_models.values() for row in rows]
    stages = [stage for row in observations for stage in row["trace"]["native"]]
    counts = {"matmul_runs": sum(map(len, native_matmuls.values())), "model_runs": len(observations),
              "matmul_launches": sum(row["dispatch"]["launches"] for rows in native_matmuls.values() for row in rows),
              "model_launches": sum(stage["dispatch"]["launches_enqueued"] for stage in stages)}
    counts["total_launches"] = counts["matmul_launches"] + counts["model_launches"]
    _same(counts, {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
                   "model_launches": 30, "total_launches": 36}, "native derived counts")
    comparison = {"hidden_words": sum(row["trace"]["native"][0]["checked_words"] for row in observations),
                  "bridge_words": sum(row["trace"]["bridge_checked_words"] for row in observations),
                  "output_block_words": sum(stage["checked_words"] for row in observations for stage in row["trace"]["native"][1:]),
                  "assembled_output_words": sum(row["trace"]["output_checked_words"] for row in observations)}
    for key, expected in (("completed_case_executions", len(models)), ("completed_model_runs", counts["model_runs"]),
                          ("completed_launches", counts["model_launches"]), ("comparison_counts", comparison),
                          ("tensor_h2d_bytes", sum(sum(stage["dispatch"][key] for key in
                              ("a_bytes", "b_bytes", "d_bytes")) for stage in stages)),
                          ("tensor_d2h_bytes", sum(stage["dispatch"]["d_bytes"] for stage in stages))):
        _same(native_report[key], expected, "native report " + key)
    _same(python_report["native_counts"], counts, "Python native counts")
    _same(python_report["completed_native_and_python_launches"], counts["total_launches"] * 2,
          "native/Python declared launch total")
    return native_matmuls, native_models, counts


def verify_native(outer_view, *, expected_revision, expected_format):
    """Validate native comparisons; return freshly parsed dictionaries, not summaries."""
    require(type(expected_revision) is str and REVISION.fullmatch(expected_revision), "invalid expected source revision")
    require(expected_format in ("fp16", "bf16"), "invalid expected format")
    native_view, python_view = outer_view.subview("native-model"), outer_view.subview("python")
    _copies(native_view, python_view.subview("native"), "native-model/Python native copies")
    _copies(python_view, outer_view.subview("torch/python"), "Python/framework Python copies")
    native, python = native_view.json("report.json"), python_view.json("report.json")
    _finished(native, "p04-managed-model-execution-v1")
    _finished(python, "p05-installed-python-execution-v1")
    _same(python["backend"], "simx", "Python backend")
    _same(python["format"], expected_format, "Python format")
    _same(native["full_matrix_requested"], False, "native selected matrix scope")
    _budget(native)
    _budget(python, python=True)
    _same(native["budget"]["jobs"], python["budget"]["jobs"], "native/Python job count")
    for report, extra in ((native, set()), (python, {"native_build", "native_output"})):
        _fields(report["paths"], {"source", "work", "output", "tools", "host_bin", "verilator"} | extra, "producer paths")
        for key, value in report["paths"].items():
            if key != "host_bin" or value is not None:
                _path(value, absolute=True)
    for key in ("source", "tools", "host_bin", "verilator"):
        _same(native["paths"][key], python["paths"][key], "native/Python path " + key)
    variant_id = "simx-" + expected_format
    build = str(PurePosixPath(native["paths"]["work"]) / variant_id)
    _same(python["paths"]["native_build"], build, "native build path")
    _same(python["paths"]["native_output"], native["paths"]["output"], "native packet path")
    native_source, python_source = (_source(view, report, expected_revision)
                                    for view, report in ((native_view, native), (python_view, python)))
    _same(native_source["checkout"], python_source["checkout"], "native/Python checkout")
    python_files = {row["path"]: row for row in python_source["files"]}
    for row in native_source["files"]:
        _same(python_files.get(row["path"]), row, "native/Python source identity " + row["path"])
    native_tools, python_tools = _tools(native_view, native), _tools(python_view, python)
    _same(native_tools, python_tools, "native/Python tool identity")
    _inventory(native["dependencies_before"], "native dependencies", expected=DEPENDENCIES)
    _same(python["dependencies_before"], native["dependencies_before"], "native/Python dependencies")
    matmuls, models = _frozen_cases(native_view, expected_format)
    _same(native_view.document(native["fixture_snapshot"], "snapshots/fixtures.json"), models, "native selected fixtures")
    _same(native["fixture_sha256"], FIXTURES["p04_tiny_mlp_v1.json"], "native fixture pin")
    _same(native["case_ids"], [case["id"] for case in models], "native case IDs")
    _same(python_view.document(python["selection"], "snapshots/selection.json"),
          {"matmuls": matmuls, "models": models}, "Python selected fixtures")
    _same(python["matmul_case_ids"], [case["id"] for case in matmuls], "Python matmul IDs")
    _same(python["model_case_ids"], [case["id"] for case in models], "Python model IDs")
    require(type(native["variants"]) is list and len(native["variants"]) == 1, "incorrect native variant count")
    variant = native["variants"][0]
    _fields(variant, ("id", "backend", "format", "outcome", "cases", "header_macros", "backend_header_macros",
                      "compiler_records", "qualification_id", "binding", "artifacts_before", "artifacts_after"), "native variant")
    for key, expected in (("id", variant_id), ("backend", "simx"), ("format", expected_format), ("outcome", "pass")):
        _same(variant[key], expected, "native variant " + key)
    native_artifacts = _inventory(variant["artifacts_before"], "native build artifacts", expected=_artifacts("tests/regression/ai_mlp"))
    matmul_artifacts = _inventory(python["matmul_artifacts_before"], "matmul build artifacts", expected=_artifacts("tests/regression/ai_matmul"))
    _same(variant["artifacts_after"], variant["artifacts_before"], "native build before/after")
    _same(python["native_artifacts"], variant["artifacts_before"], "Python native artifacts")
    _same(python["matmul_artifacts_after"], python["matmul_artifacts_before"], "matmul build before/after")
    for name in GENERATED + RUNTIME:
        _same(native_artifacts[name], matmul_artifacts[name], "shared native artifact " + name)
    for name, row in native_artifacts.items():
        retained_name = "artifacts/" + variant_id + "/" + name
        if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or PurePosixPath(name).name == "Makefile":
            _same(native_view.identity(retained_name), dict(row, path=retained_name), "native retained artifact " + name)
    for key, prefix in (("retained_native_matmul", "artifacts/native-matmul"),
                        ("retained_native_model", "artifacts/native-model")):
        rows = _inventory(python[key], key, sorted_paths=True)
        _same([prefix + "/" + name for name in rows], [name for name in python_view.files() if name.startswith(prefix + "/")],
              key + " members")
        for name, row in rows.items():
            _same(python_view.identity(prefix + "/" + name), dict(row, path=prefix + "/" + name), key + " bytes")
            expected = (native_artifacts["tests/regression/ai_mlp/ai_mlp"] if key == "retained_native_model"
                        else matmul_artifacts.get(name))
            require(expected is not None, "unknown retained native artifact")
            _same(dict(row, path=expected["path"]), expected, key + " bound identity")
    expected_retained = sorted(name for name in matmul_artifacts if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt"))
                               or PurePosixPath(name).name in ("Makefile", "ai_matmul", "kernel.elf", "kernel.vxbin"))
    _same([row["path"] for row in python["retained_native_matmul"]], expected_retained, "retained native matmul membership")
    _same([row["path"] for row in python["retained_native_model"]], ["ai_mlp"], "retained native model membership")
    common = {"source": native["paths"]["source"], "build": build, "jobs": native["budget"]["jobs"], "fmt": expected_format}
    model_compiler = _build_records(native_view, "artifacts/" + variant_id, native_artifacts, app="tests/regression/ai_mlp", **common)
    matmul_compiler = _build_records(python_view, "artifacts/native-matmul", matmul_artifacts, app="tests/regression/ai_matmul", **common)
    _same(model_compiler, variant["compiler_records"], "native compiler records")
    _same(matmul_compiler, python["matmul_compiler_records"], "matmul compiler records")
    _same(model_compiler[:2], matmul_compiler[:2], "shared runtime/backend compiler records")
    model_binding = {"source": native_source["checkout"], "backend": "simx", "format": expected_format,
                     "compiler_records": model_compiler, "artifacts": variant["artifacts_before"],
                     "dependencies": native["dependencies_before"], "profile_sha256": PROFILE_SHA256,
                     "fixture_sha256": FIXTURES["p04_tiny_mlp_v1.json"], "model_id": "p04-tiny-mlp-v1"}
    matmul_binding = {"source": python_source["checkout"], "backend": "simx", "format": expected_format,
                      "compiler_records": matmul_compiler, "artifacts": python["matmul_artifacts_before"],
                      "dependencies": python["dependencies_before"], "profile_sha256": PROFILE_SHA256}
    _same(native_view.document(variant["binding"], "snapshots/" + variant_id + "-binding.json"), model_binding, "model binding")
    _same(python_view.document(python["matmul_binding"], "snapshots/native-matmul-binding.json"), matmul_binding, "matmul binding")
    model_id, matmul_id = qualification_id(model_binding), qualification_id(matmul_binding)
    _same(variant["qualification_id"], model_id, "native qualification ID")
    _same(python["native_qualification_id"], model_id, "Python native qualification ID")
    _same(python["matmul_qualification_id"], matmul_id, "native matmul qualification ID")
    _same(python_view.document(python["native_report"], "native/report.json"), native, "Python retained native report")
    _fields(python["native_input"], ("kind", "directory", "build", "retained_prefix", "files"), "native input")
    _same(python["native_input"], {"kind": "completed_top_level_p04_packet", "directory": native["paths"]["output"],
          "build": build, "retained_prefix": "native", "files": native_view.inventory()}, "native input packet receipt")
    native_commands = _native_commands(native_view, native, native_tools, model_compiler, model_id, models,
                                       expected_revision, expected_format)
    native_members = {"report.json", "snapshots/source-before.json", "snapshots/source-after.json",
                      "snapshots/tools-before.json", "snapshots/tools-after.json", "snapshots/fixtures.json",
                      "snapshots/" + variant_id + "-binding.json"}
    native_members.update(row["path"] for row in native["retained_sources"])
    native_members.update("logs/" + name + ".log" for name in native_commands)
    native_members.update("artifacts/" + variant_id + "/" + name for name in native_artifacts
                          if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or PurePosixPath(name).name == "Makefile")
    _same(list(native_view.files()), sorted(native_members), "native packet complete member closure")
    for key, log in (("header_macros", "header"), ("backend_header_macros", "effective-header")):
        _same(variant[key], validate_header_macros(_text(native_view, "logs/" + variant_id + "-" + log + ".log")), key)
    request = python_view.document(python["installed_request"], "snapshots/installed-request.json", integers_only=True)
    _fields(request, ("schema_version", "contract_id", "binding", "matmul_cases", "model_cases", "iterations", "expected_prefix"), "Python request")
    for key, expected in (("schema_version", 1), ("contract_id", "p05-installed-request-v1"), ("iterations", 2),
                          ("matmul_cases", matmuls), ("model_cases", [case["id"] for case in models])):
        _same(request[key], expected, "Python request " + key)
    _fields(request["binding"], ("backend", "format", "bundle_root", "bundle_sha256", "source_sha256",
                                "qualification_id", "source_revision"), "Python request binding")
    for key, expected in (("backend", "simx"), ("format", expected_format), ("qualification_id", model_id),
                          ("source_revision", expected_revision)):
        _same(request["binding"][key], expected, "Python request binding " + key)
    for key in ("bundle_sha256", "source_sha256"):
        require(type(request["binding"][key]) is str and SHA256.fullmatch(request["binding"][key]), "invalid Python request digest")
    _python_commands(python_view, python, python_tools, matmul_compiler, matmul_id, matmuls, request)
    _same(python["matmul_backend_header_macros"], validate_header_macros(_text(python_view, "logs/native-matmul-effective-header.log")), "matmul backend macros")
    native_matmuls, native_models, counts = _results(native_view, python_view, native, python, matmuls, models,
                                                    model_id, matmul_id, expected_revision, expected_format)
    observations = python_view.document(python["observations"], "artifacts/installed-observations.json", integers_only=True)
    return {"native_matmuls": native_matmuls, "native_models": native_models, "model_cases": models,
            "python_report": python, "python_request": request, "python_observations": observations,
            "python_raw_log": _text(python_view, "logs/installed-matrix.log"), "counts": counts,
            "native_report": native, "model_binding": model_binding, "matmul_binding": matmul_binding,
            "native_source": native_source, "python_source": python_source}
