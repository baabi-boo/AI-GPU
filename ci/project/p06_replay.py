#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Recheck digest-pinned P06 archives as data without running retained code.

The caller supplies independently obtained archive and source identities. This
reader checks packet consistency; it cannot authenticate origin or prove that
an arbitrary producer executed a GPU. Synthetic packets remain synthetic.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

from baseline_packet_contract import _stamp_flags
from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
from p02_matrix_records import DISABLED, PROFILE_SHA256
from p03_execution_records import qualification_id
from p06_compiler_records import validate_header_macros, validate_records
from p06_contract import (CONTRACT_ID, FORMATS, MANIFEST_PATH, decode_contract,
                          load_analysis_contract, select_workloads)
from p06_records import summarize, verify_sample


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_READER_PATH = "docs/project/evidence/p05-torch/reviews/archive_reader.py"
ARCHIVE_READER_SHA256 = "4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3"
REVISION = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
APPS = {"matmul": "tests/regression/ai_bench_matmul", "mlp": "tests/regression/ai_bench_mlp"}
HEADER_PROBE = "p06-header-check/include-probe.cpp"
HEADER_PROBE_CONTENT = b"#include <VX_config.h>\n"
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "hw/VX_config.vh", "hw/VX_types.vh", "sim/rtlsim/verilator.vlt")
COPIED = ("ci/gen_config.py", "sw/kernel/Makefile", "sw/runtime/common.mk",
          "sw/runtime/stub/Makefile", "sw/runtime/simx/Makefile", "sw/runtime/rtlsim/Makefile",
          "sim/common.mk", "sim/simx/Makefile", "sim/rtlsim/Makefile",
          "tests/regression/common.mk", "tests/regression/sgemm_tcu/Makefile")
RUNTIME = ("sw/runtime/libvortex.so", "sw/runtime/libvortex-simx.so", "sw/runtime/libsimx.so",
           "sw/runtime/simx_rt_config.stamp", "sw/runtime/simx_config.stamp")
DEPENDENCIES = ("third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
                "third_party/ramulator/libramulator.so",
                "third_party/ramulator_ext/libramulator-vortex.so")
SOURCE_INPUTS = ("VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml",
                 "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh")
HOST_TOOLS = ("make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl")
REPLAY_MODULES = (
    "baseline_matrix", "baseline_packet_contract", "baseline_packet_io", "baseline_process", "compiler_records",
    "p02_fixture_oracle", "p02_layout_fixture_oracle", "p02_matrix_records", "p02_wmma_fixtures",
    "p02_wmma_numerical_fixture_oracle", "p03_execution_records", "p04_execution_records", "p04_fixture_adapter",
    "p04_model_contract", "p04_reference", "p06_compiler_records", "p06_contract", "p06_records",
)
RUNNER_HELPERS = tuple(sorted("ci/project/" + name + ".py" for name in (
    *REPLAY_MODULES, "baseline_inventory", "p02_matrix", "p03_execute", "p04_execute", "p06_execute", "preflight",
)))
TOOL_SUFFIXES = {
    **{name: "llvm-vortex/bin/" + name for name in ("clang", "clang++", "llvm-objcopy", "llvm-objdump")},
    **{"riscv-" + name: "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-" + name
       for name in ("gcc", "gcc-ar", "objdump", "objcopy")},
    **{name: name for name in ("libc64/lib/libc.a", "libc64/lib/libm.a",
                             "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a")},
}
COMMAND_FIELDS = {
    "id", "argv", "cwd", "environment", "log", "timeout_seconds", "outcome", "exit_code",
    "reason", "process_started", "duration_seconds", "log_sha256", "log_size_bytes",
    "peak_rss_bytes", "cleanup_complete", "limitations",
}
REPORT_FIELDS = {
    "schema_version", "contract_id", "started_at", "state", "outcome", "reason", "development",
    "acceptance_claimed", "phase_complete", "full_matrix_requested", "full_matrix_completed",
    "selected_scope_completed", "commands", "variants", "samples", "failures", "stability_checks",
    "limitations", "budget", "paths", "resources_before", "loaded_helpers", "source_before",
    "contract_snapshot", "contract_sha256", "workload_snapshot", "workload_ids", "formats",
    "expected_samples", "sampling", "boundaries", "contract_limitations", "tools_before",
    "dependencies_before", "retained_sources", "summary", "summary_snapshot", "source_after",
    "source_stable", "tools_after", "tools_stable", "dependencies_after", "dependencies_stable",
    "resources_after", "completed_samples", "finished_at",
}
LIMITATIONS = [
    "This is retained-data replay, not a new native execution or phase acceptance.",
    "Archive SHA-256 and source revision are supplied externally; replay does not authenticate GitHub origin.",
    "Consistent synthetic or forged producer records do not establish GPU execution.",
    "Retained binaries are identities, not executable replay payloads; no archive member is extracted or executed.",
    "Recorded absolute runner paths are interpreted syntactically and never opened on this host.",
    "One selected format does not establish the complete two-format experiment.",
    "Compiler observations are checked against the trusted runner's retained records; compilation is not rerun.",
]


class ReplayError(ValueError):
    """A retained baseline fails its source, execution, or measurement contract."""


def require(condition, message):
    if not condition:
        raise ReplayError(message)


def _same(actual, expected, label):
    require(type(actual) is type(expected), label + ": value type differs")
    if type(expected) is dict:
        _fields(actual, expected, label)
        for name, value in expected.items():
            _same(actual[name], value, label + "." + name)
    elif type(expected) is list:
        require(len(actual) == len(expected), label + ": inventory length differs")
        for index, value in enumerate(expected):
            _same(actual[index], value, label + "[" + str(index) + "]")
    else:
        require(actual == expected, label + ": value differs")


def _fields(value, names, label):
    require(type(value) is dict and set(value) == set(names), label + ": missing or unknown fields")


def _integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, label + ": integer is outside its bound")


def _number(value, minimum, maximum, label):
    require(type(value) in (int, float) and math.isfinite(value)
            and minimum <= value <= maximum, label + ": number is outside its bound")


def _timestamp(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", value),
            "invalid UTC observation timestamp")
    return datetime.fromisoformat(value)


def _archive_api():
    path = ROOT / ARCHIVE_READER_PATH
    require(hashlib.sha256(path.read_bytes()).hexdigest() == ARCHIVE_READER_SHA256,
            "trusted archive reader differs from its reviewed source pin")
    spec = importlib.util.spec_from_file_location("p06_trusted_archive_reader", path)
    require(spec is not None and spec.loader is not None, "trusted archive reader is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trusted_sources():
    rows = []
    for name in (*REPLAY_MODULES, __name__):
        module = sys.modules[name]
        path = Path(module.__file__).resolve()
        expected = ROOT / "ci/project" / ("p06_replay.py" if name == __name__ else name + ".py")
        require(path == expected, "replay helper did not load from the trusted repository")
        body = path.read_bytes()
        rows.append({"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(body).hexdigest(),
                     "size_bytes": len(body)})
    return sorted(rows, key=lambda row: row["path"])


TRUSTED_SOURCES = _trusted_sources()


def _artifacts():
    names = set(GENERATED + COPIED + RUNTIME + ("sw/kernel/libvortex2.a", HEADER_PROBE))
    for app in APPS.values():
        names.update(app + "/" + name for name in
                     ("Makefile", "config.stamp", PurePosixPath(app).name, "kernel.elf", "kernel.vxbin"))
    return sorted(names)


class _Replay:
    def __init__(self, view, api, revision, fmt):
        self.view, self.api, self.revision, self.fmt = view, api, revision, fmt
        self.report = view.json("report.json")
        # The current checkout supplies trusted readers and oracle inputs.
        # Historical execution-source pins are checked against retained bytes
        # in provenance(), independently of the current runtime implementation.
        self.contract = load_analysis_contract(ROOT)
        self.workloads = select_workloads(self.contract, [fmt])
        self.variant_id = "simx-" + fmt
        self.command_index = 0
        self.sources = {}

    def inventory(self, rows, label, *, expected=None, sorted_paths=False):
        require(type(rows) is list and 0 < len(rows) <= 20000, label + ": invalid inventory")
        names, result = [], {}
        for row in rows:
            self.api.descriptor(row)
            name = row["path"]
            require(name not in result, label + ": duplicate path")
            names.append(name)
            result[name] = row
        if expected is not None:
            _same(names, list(expected), label + " paths")
        if sorted_paths:
            _same(names, sorted(names), label + " order")
        return result

    def document(self, key, name):
        return self.view.document(self.report[key], "snapshots/" + name + ".json")

    def source_body(self, name):
        require(name in self.sources, "missing retained source input: " + name)
        row = dict(self.sources[name], path="artifacts/source/" + name)
        return self.view.verified(row)

    def build_body(self, name, stage="frozen"):
        require(name in self.stages[stage], "missing retained build input: " + name)
        return self.view.verified(self.stages[stage][name])

    def budget(self):
        budget = self.report["budget"]
        _fields(budget, {"min_free_bytes", "max_rss_bytes", "max_log_bytes", "jobs",
                         "build_timeout_seconds", "run_timeout_seconds", "configure_timeout_seconds"}, "budget")
        for name in ("min_free_bytes", "max_rss_bytes", "max_log_bytes"):
            _same(budget[name], self.contract["budget"][name], "budget." + name)
        _integer(budget["jobs"], 1, 2, "build jobs")
        _integer(budget["build_timeout_seconds"], 1, 1800, "build timeout")
        _integer(budget["run_timeout_seconds"], 1, 180, "sample timeout")
        _same(budget["configure_timeout_seconds"], 120, "configure timeout")
        self.limits = budget
        for label in ("resources_before", "resources_after"):
            resource = self.report[label]
            _fields(resource, ("available_memory_bytes", "free_disk_bytes"), label)
            _fields(resource["free_disk_bytes"], ("source", "tools", "work", "output"), label + " disk")
            for value in resource["free_disk_bytes"].values():
                _integer(value, 0, (1 << 64) - 1, label + " disk bytes")
            if resource["available_memory_bytes"] is not None:
                _integer(resource["available_memory_bytes"], 0, (1 << 64) - 1, label + " memory")
        before = self.report["resources_before"]
        require(all(value >= budget["min_free_bytes"] for value in before["free_disk_bytes"].values()),
                "initial disk reserve was below the frozen budget")
        require(type(before["available_memory_bytes"]) is int
                and before["available_memory_bytes"] >= budget["max_rss_bytes"],
                "initial available memory was below the frozen budget")

    def provenance(self):
        self.source = self.document("source_before", "source-before")
        self.tools = self.document("tools_before", "tools-before")
        self.dependencies = self.document("dependencies_before", "dependencies-before")
        for name, original in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
            _same(self.report[name + "_stable"], True, name + " stability claim")
            _same(self.document(name + "_after", name + "-after"), original, name + " before/after")
        _fields(self.source, ("checkout", "files"), "source snapshot")
        checkout = self.source["checkout"]
        _fields(checkout, ("revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                           "pins", "blockers", "inputs", "outcome"), "source checkout")
        for name, value in (("revision", self.revision), ("dirty", False), ("changed_paths", []),
                            ("untracked_paths", []), ("blockers", []), ("outcome", "pass")):
            _same(checkout[name], value, "source checkout." + name)
        require(type(checkout["tree"]) is str and REVISION.fullmatch(checkout["tree"]), "invalid source tree")
        require(type(checkout.get("submodules")) is dict and checkout["submodules"].get("errors") == [],
                "source submodule inventory is incomplete")
        entries = checkout["submodules"].get("entries")
        require(type(entries) is list and entries, "source submodules are not inventoried")
        seen = set()
        for entry in entries:
            _fields(entry, ("path", "revision", "status"), "submodule")
            _same(entry["status"], "initialized", "submodule status")
            self.api.relative_name(entry["path"])
            require(entry["path"] not in seen and type(entry["revision"]) is str
                    and REVISION.fullmatch(entry["revision"]), "invalid or duplicate submodule identity")
            seen.add(entry["path"])
        self.sources = self.inventory(self.source["files"], "source files", sorted_paths=True)
        expected_retained = [dict(row, path="artifacts/source/" + row["path"]) for row in self.source["files"]]
        _same(self.report["retained_sources"], expected_retained, "retained source inventory")
        for row in expected_retained:
            self.view.verified(row)
        for row in self.contract["source_inputs"]:
            require(row["path"] in self.sources and self.sources[row["path"]]["sha256"] == row["sha256"],
                    "frozen source pin differs: " + row["path"])
        inputs = self.inventory(checkout["inputs"], "checkout inputs", expected=SOURCE_INPUTS)
        for name, row in inputs.items():
            _same(row, self.sources.get(name), "checkout source identity " + name)
        version = {}
        for line in self.source_body("VERSION").decode("utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"(VORTEX_VERSION|TOOLCHAIN_REV|GEM5_REV|FIRESIM_REV)=([A-Za-z0-9][A-Za-z0-9._+-]*)", line)
            require(match is not None and match[1] not in version, "invalid retained version pin")
            version[match[1]] = match[2]
        _fields(version, ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV"), "version pins")
        _same(checkout["pins"], version, "source version pins")
        helpers = self.inventory(self.report["loaded_helpers"], "loaded helpers", expected=RUNNER_HELPERS)
        required_sources = set(RUNNER_HELPERS) | {
            "tests/regression/ai_bench_common/observer.cpp", "tests/regression/ai_bench_common/counters.h",
            ".github/workflows/p06-baseline.yml", "ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
            "ci/project/fixtures/p02_tfr_v1.json", "sw/runtime/include/vortex2.h",
        }
        require(required_sources <= set(self.sources), "retained source inventory omits required benchmark inputs")
        for name, row in helpers.items():
            require(name.startswith("ci/project/") and name.endswith(".py"), "invalid loaded helper path")
            _same(row, self.sources.get(name), "loaded helper identity " + name)
        manifest_body = self.source_body(MANIFEST_PATH)
        _same(decode_contract(manifest_body), self.contract, "retained frozen manifest")
        _same(self.report["contract_sha256"], hashlib.sha256(manifest_body).hexdigest(), "raw manifest identity")
        _same(self.document("contract_snapshot", "contract"), self.contract, "contract snapshot")
        _same(self.document("workload_snapshot", "workloads"), self.workloads, "workload snapshot")
        self.inventory(self.dependencies, "dependencies", expected=DEPENDENCIES)

    def paths_and_tools(self):
        paths = self.report["paths"]
        _fields(paths, ("source", "tools", "work", "output", "host_bin", "verilator"), "recorded paths")
        self.paths = {name: self.api.recorded_absolute(value) if value is not None else None
                      for name, value in paths.items()}
        require(all(self.paths[name] is not None for name in ("source", "tools", "work", "output", "verilator")),
                "missing execution root")
        for name in ("work", "output"):
            root = self.paths[name]
            require(not any(root == other or root in other.parents or other in root.parents
                            for key, other in self.paths.items()
                            if key in ("source", "tools", "work", "output") and key != name),
                    "recorded execution roots overlap")
        self.build = self.paths["work"] / self.variant_id
        _fields(self.tools, set(HOST_TOOLS) | set(TOOL_SUFFIXES), "tools")
        for name, row in self.tools.items():
            _fields(row, ("path", "resolved_path", "sha256", "size_bytes"), "tool " + name)
            self.api.recorded_absolute(row["path"])
            self.api.recorded_absolute(row["resolved_path"])
            require(type(row["sha256"]) is str and SHA256.fullmatch(row["sha256"]), "invalid tool digest")
            _integer(row["size_bytes"], 1, (1 << 64) - 1, "tool byte count")
            if name in TOOL_SUFFIXES:
                _same(row["path"], str(self.paths["tools"] / TOOL_SUFFIXES[name]), "tool selection " + name)
        first = self.report["commands"][0]
        require(type(first) is dict and type(first.get("environment")) is dict, "invalid first command environment")
        env = first["environment"]
        expected = {
            "PATH": env.get("PATH"), "TMPDIR": str(self.paths["work"] / "tmp"),
            "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "CCACHE_DISABLE": "1", "OBJCACHE": "", "MAKEFLAGS": "-j" + str(self.limits["jobs"]),
            "THREADS": str(self.limits["jobs"]), "CMAKE_BUILD_PARALLEL_LEVEL": str(self.limits["jobs"]),
        }
        _same(env, expected, "sanitized environment")
        require(type(env["PATH"]) is str, "invalid recorded PATH")
        entries = env["PATH"].split(":")
        require(entries and len(entries) == len(set(entries)), "duplicate or empty PATH component")
        for entry in entries:
            self.api.recorded_absolute(entry)
        host_bin = [str(self.paths["host_bin"])] if self.paths["host_bin"] else []
        interpreter = str(PurePosixPath(self.tools["python3"]["path"]).parent)
        expected_path = list(dict.fromkeys([*host_bin, interpreter, "/usr/bin", "/bin"]))
        _same(entries, expected_path, "bounded interpreter PATH")
        for name in HOST_TOOLS:
            path = PurePosixPath(self.tools[name]["path"])
            require(path.name == name and str(path.parent) in entries, "host tool is outside the selected PATH: " + name)
        self.env = env

    def command(self, command_id, argv, cwd, environment, timeout, *, read=False):
        commands = self.report["commands"]
        require(self.command_index < len(commands), "command inventory is truncated")
        row = commands[self.command_index]
        self.command_index += 1
        _fields(row, COMMAND_FIELDS, "command " + command_id)
        for name, value in (("id", command_id), ("argv", [str(item) for item in argv]), ("cwd", str(cwd)),
                            ("environment", environment), ("timeout_seconds", timeout), ("outcome", "pass"),
                            ("exit_code", 0), ("reason", None), ("process_started", True),
                            ("cleanup_complete", True), ("limitations", list(PROCESS_LIMITATIONS)),
                            ("log", "logs/" + command_id + ".log")):
            _same(row[name], value, "command " + command_id + "." + name)
        _number(row["duration_seconds"], 0, timeout + 10, "command duration")
        _integer(row["peak_rss_bytes"], 0, self.limits["max_rss_bytes"], "command peak RSS")
        _integer(row["log_size_bytes"], 0, self.limits["max_log_bytes"], "command log bytes")
        descriptor = {"path": row["log"], "sha256": row["log_sha256"], "size_bytes": row["log_size_bytes"]}
        self.api.descriptor(descriptor)
        _same(self.view.identity(row["log"], limit=self.limits["max_log_bytes"]), descriptor, "original command log")
        text = self.view.read(row["log"], limit=self.limits["max_log_bytes"]).decode("utf-8") if read else None
        return text, row

    def generated(self):
        variant = self.report["variants"][0]
        names = _artifacts()
        self.frozen = self.inventory(variant["artifacts_before"], "frozen artifacts", expected=names)
        for row in self.frozen.values():
            _integer(row["size_bytes"], 1, self.api.MEMBER_BYTES, "frozen artifact size")
        _same(variant["artifacts_after"], variant["artifacts_before"], "frozen artifact stability")
        self.inventory(variant["generated_identity"], "generated identity", expected=GENERATED + COPIED)
        for row in variant["generated_identity"]:
            _same(row, self.frozen[row["path"]], "generated artifact stayed stable")
        stages = variant["retained_builds"]
        require(type(stages) is list and len(stages) == 5, "missing retained build stage")
        self.stages = {}
        retained_names = [name for name in names if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt", ".py"))
                          or PurePosixPath(name).name == "Makefile" or name == HEADER_PROBE]
        for stage, expected_name in zip(stages, ("configured", "runtime", "built-matmul", "built-mlp", "frozen")):
            _fields(stage, ("stage", "files"), "build stage")
            _same(stage["stage"], expected_name, "build stage order")
            prefix = "artifacts/" + self.variant_id + "/" + expected_name + "/"
            rows = self.inventory(stage["files"], "retained stage " + expected_name, sorted_paths=True)
            values = {}
            for name, row in rows.items():
                require(name.startswith(prefix), "retained stage path differs")
                relative = name[len(prefix):]
                require(relative in retained_names, "unexpected retained generated input")
                _same(dict(row, path=relative), self.frozen[relative], "retained build identity")
                self.view.verified(row)
                values[relative] = row
            require(set(GENERATED + COPIED) <= set(values), "retained build stage omits generated inputs")
            self.stages[expected_name] = values
        _same(list(self.stages["frozen"]), retained_names, "frozen retained build inventory")
        _same(self.build_body(HEADER_PROBE), HEADER_PROBE_CONTENT, "ordinary header include probe")
        for name in (*COPIED, *(app + "/Makefile" for app in APPS.values())):
            _same(self.build_body(name), self.source_body(name), "generated copied source " + name)
        config = self.build_body("config.mk").decode("utf-8")
        for name, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("VORTEX_HOME", str(self.paths["source"])),
                               ("TOOLDIR", str(self.paths["tools"])), ("OSVERSION", "ubuntu/focal")):
            values = re.findall(r"^" + name + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", config, re.MULTILINE)
            _same(values, [expected], "generated config " + name)
        tokens = self.build_body(".config.stamp").decode("utf-8").strip().split()
        require(all("=" in token for token in tokens), "malformed configure stamp")
        stamp = dict(token.split("=", 1) for token in tokens)
        require(len(stamp) == len(tokens), "configure stamp repeats settings")
        for name, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("SOURCE_DIR", str(self.paths["source"])),
                               ("BUILDDIR", str(self.build)), ("TOOLDIR", str(self.paths["tools"]))):
            _same(stamp.get(name), expected, "configure stamp " + name)
        template = self.source_body("sim/rtlsim/verilator.vlt.in").decode("utf-8")
        _same(self.build_body("sim/rtlsim/verilator.vlt").decode("utf-8"),
              template.replace("@VORTEX_HOME@", str(self.paths["source"])), "generated Verilator configuration")
        for name in ("kernel.elf", "kernel.vxbin"):
            a, b = (self.frozen[app + "/" + name] for app in APPS.values())
            _same((a["sha256"], a["size_bytes"]), (b["sha256"], b["size_bytes"]), "shared kernel " + name)

    def compiler_commands(self):
        variant = self.report["variants"][0]
        source, build, tools, env = self.paths["source"], self.build, self.paths["tools"], self.env
        for name in ("g++", "clang", "make", "python3"):
            self.command("version-" + name.replace("+", "p"), [self.tools[name]["path"], "--version"],
                         self.paths["work"], env, 30)
        self.command(self.variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                     "--osversion=ubuntu/focal", "--tooldir=" + str(tools)], build, env, 120)
        preprocessor = [self.tools["g++"]["path"], "-E", "-dM", "-x", "c++"]
        header_tail = ["-include", build / "sw/VX_config.h", "/dev/null"]
        text, _ = self.command(self.variant_id + "-header",
                               [*preprocessor, "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", *header_tail],
                               build, env, 30, read=True)
        initial = validate_header_macros(text)
        _same(variant["header_macros"], initial, "original initial header macros")
        for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
            self.command(self.variant_id + "-" + language + "-header-reproduce", [self.tools["python3"]["path"],
                         source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                         "--profile=p02-tfr", "--format=" + language,
                         "--output=" + str(build / "p06-header-check" / PurePosixPath(relative).name)],
                         build, dict(env, XLEN="64"), 30)
        config_flags = "-DITYPE=" + self.fmt + " -DOTYPE=fp32 -DKUNROLL=1"
        text, _ = self.command(self.variant_id + "-expected-flags", [self.tools["python3"]["path"],
                               source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                               "--profile=p02-tfr", "--xlen=64", "--format=cflags",
                               "--cflags=" + config_flags + " -DVX_CFG_XLEN=64"], build, env, 30, read=True)
        flags = _stamp_flags(text, "retained independently generated flags")
        require(flags and all(flag.startswith("-D") for flag in flags), "invalid expected configuration flags")
        text, _ = self.command(self.variant_id + "-expected-expanded-header", [*preprocessor, *flags,
                               *("-D" + name + "_DISABLE" for name in DISABLED), *header_tail],
                               build, env, 30, read=True)
        expanded = validate_header_macros(text)
        backend = dict(initial, **{name + "_DISABLE": "1" for name in DISABLED})
        _same(variant["expected_expanded_header_macros"], expanded, "independently expanded configuration")
        _same(variant["expected_backend_header_macros"], backend, "independent backend configuration")
        make = [self.tools["make"]["path"], "--no-print-directory", "-j" + str(self.limits["jobs"]),
                "THREADS=" + str(self.limits["jobs"])]
        current = dict(env, CONFIGS=config_flags, PERF="1")
        self.command(self.variant_id + "-runtime", [*make, "runtime-simx"], build / APPS["matmul"],
                     current, self.limits["build_timeout_seconds"])
        for kind, app in APPS.items():
            self.command(self.variant_id + "-build-" + kind, [*make, "all"], build / app,
                         current, self.limits["build_timeout_seconds"])
        _fields(variant["applications"], APPS, "applications")
        for kind, app in APPS.items():
            stored = variant["applications"][kind]
            _fields(stored, ("path", "compiler_records", "effective_headers"), "application binding")
            _same(stored["path"], app, "application path")
            records = validate_records(self.build_body("sw/runtime/simx_rt_config.stamp").decode("utf-8"),
                                       self.build_body("sw/runtime/simx_config.stamp").decode("utf-8"),
                                       self.build_body(app + "/config.stamp").decode("utf-8"),
                                       fmt=self.fmt, source=Path(str(source)), build=Path(str(build)),
                                       jobs=self.limits["jobs"])
            _same(stored["compiler_records"], records, "original compiler records")
            _fields(stored["effective_headers"], ("runtime", "backend_cpp", "kernel", "host"), "effective headers")
            for record in records:
                role = record["role"]
                command_id = self.variant_id + "-" + kind + "-" + role + "-header"
                role_cwd = {"runtime": build / "sw/runtime/simx", "backend_cpp": build / "sim/simx",
                            "kernel": build / app, "host": build / app}[role]
                text, _ = self.command(command_id, [*preprocessor, *record["macro_flags"],
                                       *("-I" + path for path in record["include_paths"]), build / HEADER_PROBE],
                                       role_cwd, env, 30, read=True)
                macros = validate_header_macros(text, performance=role == "backend_cpp")
                _same({key: value for key, value in macros.items() if key.startswith("VX_CFG_")},
                      backend if role == "backend_cpp" else expanded, "complete effective " + role + " configuration")
                _same(stored["effective_headers"][role], {"command_id": command_id, "macros": macros},
                      "retained effective header")

    def binding(self):
        variant = self.report["variants"][0]
        binding = self.view.document(variant["binding"], "snapshots/" + self.variant_id + "-binding.json")
        expected = {
            "contract_id": CONTRACT_ID, "contract_sha256": self.report["contract_sha256"], "source": self.source,
            "backend": "simx", "format": self.fmt, "applications": variant["applications"],
            "generated_header_macros": variant["header_macros"],
            "expected_expanded_header_macros": variant["expected_expanded_header_macros"],
            "expected_backend_header_macros": variant["expected_backend_header_macros"],
            "artifacts": variant["artifacts_before"], "tools": self.tools, "dependencies": self.dependencies,
            "profile_sha256": PROFILE_SHA256, "sampling": self.contract["sampling"],
            "boundaries": self.contract["boundaries"], "counters": self.contract["counters"], "workloads": self.workloads,
        }
        _same(binding, expected, "complete original execution binding")
        self.binding_id = qualification_id(binding)
        _same(variant["qualification_id"], self.binding_id, "execution binding digest")

    def samples(self):
        plan = [{"sample_id": workload["id"] + "-" + phase + "-" + str(repetition),
                 "workload_id": workload["id"], "phase": phase, "repetition": repetition}
                for workload in self.workloads
                for phase, count in (("warmup", 1), ("measurement", 5)) for repetition in range(count)]
        _same(self.report["expected_samples"], plan, "canonical sample plan")
        _same(self.report["variants"][0]["sample_ids"], [row["sample_id"] for row in plan], "variant sample inventory")
        require(type(self.report["samples"]) is list and len(self.report["samples"]) == len(plan),
                "sample inventory is incomplete")
        replayed = []
        workload_map = {row["id"]: row for row in self.workloads}
        launch_env = dict(self.env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(self.build / "sw/runtime"))
        for stored, planned in zip(self.report["samples"], plan):
            workload = workload_map[planned["workload_id"]]
            app = self.build / APPS[workload["kind"]]
            command_id = "simx-" + planned["sample_id"]
            argv = [app / app.name, "--case", workload["case_id"], "--iterations", "1",
                    "--module", app / "kernel.vxbin", "--qualification-id", self.binding_id]
            if workload["kind"] == "mlp":
                argv += ["--backend", "simx", "--source-revision", self.revision]
            text, command = self.command(command_id, argv, app,
                                          dict(launch_env, P06_SAMPLE_ID=planned["sample_id"]),
                                          self.limits["run_timeout_seconds"], read=True)
            observation = verify_sample(text, workload, self.binding_id, sample_id=planned["sample_id"],
                                        source_revision=self.revision, fixture_sha256=workload["fixture_sha256"],
                                        contract=self.contract)
            sample = dict(planned, command_id=command_id, outcome="pass",
                          process_duration_seconds=command["duration_seconds"], observation=observation)
            _same(stored, sample, "original sample replay " + planned["sample_id"])
            replayed.append(sample)
        require(self.command_index == len(self.report["commands"]), "unexpected extra execution command")
        summary = summarize(replayed, self.contract, self.workloads)
        _same(self.report["summary"], summary, "recomputed measured-only summary")
        _same(self.document("summary_snapshot", "summary"), summary, "retained summary snapshot")
        _same(self.report["completed_samples"], len(plan), "completed sample count")
        labels = ["before-" + self.variant_id]
        for workload in self.workloads:
            labels += ["before-" + workload["id"], "after-" + workload["id"]]
        labels += ["after-" + self.variant_id]
        checks = self.report["stability_checks"]
        require(type(checks) is list and len(checks) == len(labels), "incomplete stability observations")
        for row, label in zip(checks, labels):
            _fields(row, ("label", "at", "source_sha256", "tools_sha256", "dependencies_sha256"), "stability observation")
            _same(row["label"], label, "stability chronology")
            require(self.started <= _timestamp(row["at"]) <= self.finished, "stability timestamp outside run")
            for name, value in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
                _same(row[name + "_sha256"], qualification_id(value), "stability identity")
        return summary

    def hosted_identity(self):
        parent = str(PurePosixPath(self.view.prefix).parent) if self.view.prefix else ""
        parent = "" if parent == "." else parent
        outer = self.view.archive.view(parent)
        present = {name for name in ("job.json", "workflow.yml", "python-provision.json") if name in outer.files()}
        if not present:
            return None
        require(present == {"job.json", "workflow.yml", "python-provision.json"}, "hosted identity packet is incomplete")
        job = outer.json("job.json")
        _fields(job, ("GITHUB_SHA", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
                      "GITHUB_REPOSITORY", "GITHUB_REF", "P06_BACKEND", "P06_FORMAT", "scope", "native_execution",
                      "acceptance_claimed", "workflow_sha256"), "hosted job identity")
        for name, expected in (("GITHUB_SHA", self.revision), ("GITHUB_REPOSITORY", "baabi-boo/AI-GPU"),
                               ("GITHUB_JOB", "baseline"), ("P06_BACKEND", "simx"), ("P06_FORMAT", self.fmt),
                               ("scope", "simx-native-baseline"), ("native_execution", "not_run"),
                               ("acceptance_claimed", False)):
            _same(job[name], expected, "hosted job " + name)
        require(job["GITHUB_EVENT_NAME"] in ("push", "pull_request", "workflow_dispatch"), "unexpected hosted event")
        for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            require(type(job[name]) is str and re.fullmatch(r"[1-9][0-9]{0,20}", job[name]), "invalid hosted run identity")
        require(type(job["GITHUB_REF"]) is str and re.fullmatch(r"refs/((heads|tags)/[^\s]+|pull/[1-9][0-9]*/merge)", job["GITHUB_REF"]),
                "invalid hosted ref")
        if job["GITHUB_EVENT_NAME"] == "push":
            _same(job["GITHUB_REF"], "refs/heads/master", "hosted push branch")
        elif job["GITHUB_EVENT_NAME"] == "pull_request":
            require(re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", job["GITHUB_REF"]), "hosted pull-request ref differs")
        workflow = outer.read("workflow.yml", limit=256 * 1024)
        _same(workflow, self.source_body(".github/workflows/p06-baseline.yml"), "hosted workflow source")
        _same(job["workflow_sha256"], hashlib.sha256(workflow).hexdigest(), "hosted workflow digest")
        provision = outer.json("python-provision.json")
        _fields(provision, ("python_version", "implementation", "platform", "executable", "python3_on_path"), "Python provisioning")
        for name, value in (("python_version", [3, 12, 14]), ("implementation", "CPython"), ("platform", "linux")):
            _same(provision[name], value, "hosted Python " + name)
        self.api.recorded_absolute(provision["executable"])
        _same(provision["python3_on_path"], self.tools["python3"]["path"], "provisioned interpreter selection")
        require(provision["executable"] in (self.tools["python3"]["path"], self.tools["python3"]["resolved_path"]),
                "provisioned interpreter differs from the execution identity")
        return job

    def run(self):
        _fields(self.report, REPORT_FIELDS, "execution report")
        for name, expected in (("schema_version", 1), ("contract_id", CONTRACT_ID), ("state", "finished"),
                               ("outcome", "pass"), ("reason", None), ("development", False),
                               ("acceptance_claimed", False), ("phase_complete", False),
                               ("full_matrix_requested", False), ("full_matrix_completed", False),
                               ("selected_scope_completed", True), ("failures", []), ("formats", [self.fmt]),
                               ("workload_ids", [row["id"] for row in self.workloads]),
                               ("sampling", self.contract["sampling"]), ("boundaries", self.contract["boundaries"]),
                               ("contract_limitations", self.contract["limitations"])):
            _same(self.report[name], expected, "report." + name)
        require(type(self.report["limitations"]) is list and self.report["limitations"]
                and all(type(value) is str and value for value in self.report["limitations"]), "missing execution limitations")
        self.started, self.finished = (_timestamp(self.report[name]) for name in ("started_at", "finished_at"))
        require(self.started <= self.finished, "execution timestamps are reversed")
        require(type(self.report["commands"]) is list and len(self.report["commands"]) == 45,
                "expected exactly 45 original commands for one selected format")
        require(type(self.report["variants"]) is list and len(self.report["variants"]) == 1, "unexpected variant inventory")
        variant = self.report["variants"][0]
        _fields(variant, ("id", "backend", "format", "outcome", "applications", "sample_ids", "generated_identity",
                          "retained_builds", "header_macros", "expected_expanded_header_macros",
                          "expected_backend_header_macros", "qualification_id", "binding",
                          "artifacts_before", "artifacts_after"), "variant")
        for name, expected in (("id", self.variant_id), ("backend", "simx"), ("format", self.fmt), ("outcome", "pass")):
            _same(variant[name], expected, "variant." + name)
        self.budget()
        self.provenance()
        self.paths_and_tools()
        self.generated()
        self.compiler_commands()
        self.binding()
        summary = self.samples()
        return {"schema_version": 1, "scope": "p06-selected-format-retained-data-replay", "outcome": "pass",
                "native_execution": "not_run", "acceptance_claimed": False, "phase_complete": False,
                "source_revision": self.revision, "format": self.fmt, "binding_id": self.binding_id,
                "report_identity": self.view.identity("report.json"), "commands_checked": self.command_index,
                "retained_source_files_checked": len(self.sources), "summary": summary,
                "hosted_job_identity": self.hosted_identity(), "limitations": LIMITATIONS}


def replay_archive(path, sha256, *, expected_revision, expected_format, prefix="baseline"):
    """Recheck one complete format using externally supplied original identities."""
    require(type(expected_revision) is str and REVISION.fullmatch(expected_revision), "invalid external source revision")
    require(type(expected_format) is str and expected_format in FORMATS, "invalid external format")
    _same(_trusted_sources(), TRUSTED_SOURCES, "executing replay source stability")
    api = _archive_api()
    try:
        with api.ArchiveReader(path, sha256) as archive:
            result = _Replay(archive.view(prefix), api, expected_revision, expected_format).run()
            result["archive_read"] = archive.receipt()
            result["trusted_archive_reader"] = {"path": ARCHIVE_READER_PATH, "sha256": ARCHIVE_READER_SHA256}
            _same(_trusted_sources(), TRUSTED_SOURCES, "replay source remained stable")
            result["trusted_replay_sources"] = TRUSTED_SOURCES
            return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError) as error:
        raise ReplayError("malformed retained packet: " + str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--format", choices=FORMATS, required=True)
    parser.add_argument("--prefix", default="baseline")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision,
                                expected_format=args.format, prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is not None:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "scope": result["scope"], "report": str(args.output),
                              "native_execution": "not_run", "acceptance_claimed": False}))
        else:
            print(body, end="")
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "native_execution": "not_run",
                          "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
