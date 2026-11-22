#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify original workspace correctness packets without executing retained code."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

from baseline_packet_contract import _stamp_flags
from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
from p02_matrix_records import DISABLED, PROFILE_SHA256, validate_header_macros
from p02_wmma_fixtures import load_cases, render_header
from p03_execution_records import qualification_id
import p06_replay as archive_helpers
from p06_replay import ReplayError, require, _fields, _integer, _number, _same, _timestamp
from p06_workspace_compiler_records import validate_records
from p06_workspace_execute import validate_effective_header
from p06_workspace_records import CONTRACT_ID, MANIFEST_PATH, load_contract, verify_output


ROOT = Path(__file__).resolve().parents[2]
BACKENDS = ("simx", "rtlsim")
FORMATS = ("fp16", "bf16")
POLICIES = ("per_operation", "reusable_single_tile")
APP = "tests/regression/ai_workspace"
HEADER_PROBE = "p06-workspace-header-check/include-probe.cpp"
KERNEL_SHA256 = "ad3b6107f0eef91ec676412bc795ab70cd1c9f31647b2cea854de6234fe71d3e"
GENERATED = archive_helpers.GENERATED
COPIED = archive_helpers.COPIED
SOURCE_INPUTS = archive_helpers.SOURCE_INPUTS
HOST_TOOLS = archive_helpers.HOST_TOOLS
TOOL_SUFFIXES = archive_helpers.TOOL_SUFFIXES
DEPENDENCIES = archive_helpers.DEPENDENCIES
REPORT_FIELDS = {
    "acceptance_claimed", "budget", "checked_words", "commands", "complete_matrix",
    "completed_launches", "completed_processes", "contract_id", "contract_sha256",
    "contract_snapshot", "corpus", "dependencies_after", "dependencies_before",
    "dependencies_stable", "expected_processes", "failures", "finished_at",
    "fixture_snapshot", "full_matrix_completed", "full_matrix_requested",
    "kernel_source_sha256", "limitations", "loaded_helpers", "outcome", "paths",
    "performance_acceptance", "phase_acceptance", "phase_complete", "processes",
    "profile_sha256", "raw_logs", "reason", "resources_after", "resources_before",
    "retained_files_stable", "retained_sources", "schema_version", "scope",
    "selected_counts", "selected_scope_completed", "source_after", "source_before",
    "source_stable", "stability_checks", "started_at", "state", "tools_after",
    "tools_before", "tools_stable", "variants",
}
RUNNER_HELPERS = tuple("ci/project/" + name + ".py" for name in (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract", "baseline_packet_io",
    "baseline_process", "compiler_records", "p02_fixture_oracle", "p02_layout_fixture_oracle",
    "p02_matrix", "p02_matrix_records", "p02_wmma_fixtures", "p02_wmma_numerical_fixture_oracle",
    "p03_execute", "p03_execution_records", "p06_compiler_records",
    "p06_workspace_compiler_records", "p06_workspace_execute", "p06_workspace_records", "preflight",
))
CORPUS = ("ci/project/fixtures/p02_layout_v1.json", "ci/project/fixtures/p02_tfr_v1.json",
          "ci/project/fixtures/p02_wmma_numerical_v1.json", "tests/regression/sgemm_tcu/p02_fixtures.h")
LIMITATIONS = [
    "This verifies retained data; native_execution is not_run and no performance or phase is accepted.",
    "Externally supplied ZIP digests and source revisions do not independently authenticate producer honesty.",
    "No archive member, retained helper, native binary, command or recorded absolute path is executed or opened as local source.",
    "Binaries and toolchains are retained as identities, not executable replay payloads.",
    "Processor rtlsim bypasses the AFU; neither it nor SimX is physical FPGA or silicon evidence.",
    "Buffer/device wrappers do not independently observe hidden queue/event/enqueue work inside rejected probes.",
    "Requested tensor bytes and simulator allocator readings do not establish physical memory reclamation.",
]


def _check_declared_submodules(body, inventory, api):
    require(type(body) is bytes and len(body) <= 256 * 1024,
            "retained submodule declarations exceed their byte bound")
    parser = configparser.RawConfigParser(strict=True, empty_lines_in_values=False)
    try:
        parser.read_string(body.decode("utf-8", errors="strict"))
    except (UnicodeError, configparser.Error) as error:
        raise ReplayError("invalid retained submodule declarations") from error
    require(not parser.defaults(), "retained submodule declarations contain defaults")
    roots = []
    for section in parser.sections():
        require(re.fullmatch(r'submodule "[^"\\\r\n]+"', section) is not None,
                "invalid retained submodule section")
        path = parser.get(section, "path", raw=True, fallback=None)
        api.relative_name(path)
        roots.append(path)
    require(0 < len(roots) <= 1000 and len(set(roots)) == len(roots),
            "retained submodule paths are missing or repeated")
    _same(inventory["declared_count"], len(roots), "declared root submodule count")
    names = {row["path"] for row in inventory["entries"]}
    require(set(roots) <= names, "declared root submodule is missing from the inventory")
    require(all(any(name == root or name.startswith(root + "/") for root in roots)
                for name in names), "submodule entry is outside the declared roots")


def _trusted_sources():
    rows = []
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name:
            continue
        path = Path(name).resolve()
        if path.suffix == ".py" and path.is_relative_to(ROOT / "ci/project"):
            data = path.read_bytes()
            rows.append({"path": path.relative_to(ROOT).as_posix(),
                         "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
    return sorted({row["path"]: row for row in rows}.values(), key=lambda row: row["path"])


def _artifacts(driver):
    return tuple(sorted(set((*GENERATED, *COPIED, HEADER_PROBE, "sw/kernel/libvortex2.a",
        *(APP + "/" + name for name in ("Makefile", "config.stamp", "ai_workspace", "kernel.elf", "kernel.vxbin")),
        "sw/runtime/libvortex.so", "sw/runtime/libvortex-" + driver + ".so",
        "sw/runtime/lib" + driver + ".so", "sw/runtime/" + driver + "_rt_config.stamp",
        "sw/runtime/" + driver + "_config.stamp"))))


class _Replay:
    def __init__(self, view, api, revision, driver, fmt):
        self.view, self.api = view, api
        self.revision, self.driver, self.fmt = revision, driver, fmt
        self.variant_id = driver + "-" + fmt
        self.report = view.json("report.json")
        self.contract = load_contract(ROOT)
        self.command_index = 0
        self.used_members = {"report.json"}
        inventory = {row["id"]: row for row in load_cases(ROOT)}
        self.cases = [inventory[fmt + "-" + row["fixture_suffix"]] for row in self.contract["sequence"]]
        self.plan = [{"id": self.variant_id + "-" + policy, "backend": driver, "format": fmt,
                      "policy": policy, "case_ids": [row["id"] for row in self.cases]}
                     for policy in POLICIES]

    def inventory(self, rows, label, *, expected=None, sorted_paths=False):
        require(type(rows) is list and 0 < len(rows) <= 20000, label + ": invalid inventory")
        result = {}
        for row in rows:
            self.api.descriptor(row)
            require(row["path"] not in result, label + ": repeated path")
            result[row["path"]] = row
        if expected is not None:
            _same(list(result), list(expected), label + " paths")
        if sorted_paths:
            _same(list(result), sorted(result), label + " path order")
        return result

    def verified(self, row, expected=None):
        body = self.view.verified(row, expected)
        self.used_members.add(row["path"])
        return body

    def document(self, key, name):
        return self.api.strict_json(self.verified(self.report[key], "snapshots/" + name + ".json"))

    def source_body(self, name):
        require(name in self.sources, "missing retained source: " + name)
        return self.verified(dict(self.sources[name], path="artifacts/source/" + name))

    def build_body(self, name, stage="frozen"):
        require(name in self.stages[stage], "missing retained build input: " + name)
        return self.verified(self.stages[stage][name])

    def budget(self):
        value = self.report["budget"]
        _fields(value, {"min_free_bytes", "max_rss_bytes", "max_log_bytes", "jobs",
                        "build_timeout_seconds", "run_timeout_seconds", "configure_timeout_seconds"}, "budget")
        for key, expected in (("min_free_bytes", 15 * 1024**3), ("max_rss_bytes", 4 * 1024**3),
                              ("max_log_bytes", 16 * 1024**2)):
            _same(value[key], expected, "budget." + key)
        _integer(value["jobs"], 1, 2, "build jobs")
        _integer(value["build_timeout_seconds"], 1, 1800, "build timeout")
        _integer(value["run_timeout_seconds"], 1, 180, "process timeout")
        _same(value["configure_timeout_seconds"], min(120, value["build_timeout_seconds"]), "configure timeout")
        self.limits = value
        for name in ("resources_before", "resources_after"):
            resource = self.report[name]
            _fields(resource, ("available_memory_bytes", "free_disk_bytes"), name)
            _fields(resource["free_disk_bytes"], ("source", "tools", "work", "output"), name + " roots")
            for free in resource["free_disk_bytes"].values():
                _integer(free, value["min_free_bytes"], (1 << 64) - 1, name + " disk reserve")
            if resource["available_memory_bytes"] is not None:
                _integer(resource["available_memory_bytes"], 0, (1 << 64) - 1, name + " available memory")
        before = self.report["resources_before"]["available_memory_bytes"]
        require(type(before) is int and before >= value["max_rss_bytes"], "initial memory is below the budget")

    def provenance(self):
        self.source = self.document("source_before", "source-before")
        self.tools = self.document("tools_before", "tools-before")
        self.dependencies = self.document("dependencies_before", "dependencies-before")
        for name, original in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
            _same(self.report[name + "_stable"], True, name + " stable")
            _same(self.document(name + "_after", name + "-after"), original, name + " original/final")
        _fields(self.source, ("checkout", "files"), "source snapshot")
        checkout = self.source["checkout"]
        _fields(checkout, ("revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                           "pins", "blockers", "inputs", "outcome"), "source checkout")
        for name, expected in (("revision", self.revision), ("dirty", False), ("changed_paths", []),
                               ("untracked_paths", []), ("blockers", []), ("outcome", "pass")):
            _same(checkout[name], expected, "checkout." + name)
        require(type(checkout["tree"]) is str and archive_helpers.REVISION.fullmatch(checkout["tree"]), "invalid source tree")
        submodules = checkout["submodules"]
        _fields(submodules, ("declared_count", "entries", "errors"), "submodule inventory")
        _same(submodules["errors"], [], "submodule errors")
        _integer(submodules["declared_count"], 1, 1000, "declared submodules")
        require(type(submodules["entries"]) is list
                and submodules["declared_count"] <= len(submodules["entries"]) <= 1000,
                "submodule inventory is incomplete or excessive")
        seen = set()
        for row in submodules["entries"]:
            _fields(row, ("path", "revision", "status"), "submodule")
            self.api.relative_name(row["path"])
            require(row["path"] not in seen and type(row["revision"]) is str
                    and archive_helpers.REVISION.fullmatch(row["revision"]), "invalid submodule identity")
            seen.add(row["path"])
            _same(row["status"], "initialized", "submodule state")
        self.sources = self.inventory(self.source["files"], "source files", sorted_paths=True)
        retained = [dict(row, path="artifacts/source/" + row["path"]) for row in self.source["files"]]
        _same(self.report["retained_sources"], retained, "retained source descriptors")
        for row in retained:
            self.verified(row)
        required = set(RUNNER_HELPERS) | set(SOURCE_INPUTS) | set(COPIED) | set(CORPUS) | {
            MANIFEST_PATH, ".github/workflows/p06-workspace.yml", "ci/project/p04_ci_prepare.py",
            "profiles/p02-tfr.json", "sw/kernel/ai/matmul.cpp", "sw/runtime/ai/runtime.cpp",
            "sw/runtime/ai/runtime.h", "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h",
            "sw/common/ai_matmul_args.h", "sw/common/ai_matmul_profile.h", "sw/runtime/include/vortex2.h",
            "sim/rtlsim/verilator.vlt.in", *(APP + "/" + name for name in ("main.cpp", "observer.cpp", "observer.h", "Makefile")),
        }
        require(required <= set(self.sources), "missing required source inventory")
        _check_declared_submodules(self.source_body(".gitmodules"), submodules, self.api)
        for row in self.inventory(checkout["inputs"], "checkout inputs", expected=SOURCE_INPUTS).values():
            _same(row, self.sources[row["path"]], "checkout input identity")
        for row in self.inventory(self.report["loaded_helpers"], "executing helpers", expected=RUNNER_HELPERS).values():
            _same(row, self.sources[row["path"]], "executing helper identity")
        version = {}
        for line in self.source_body("VERSION").decode("utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"(VORTEX_VERSION|TOOLCHAIN_REV|GEM5_REV|FIRESIM_REV)=([A-Za-z0-9][A-Za-z0-9._+-]*)", line)
            require(match is not None and match[1] not in version, "invalid retained version pin")
            version[match[1]] = match[2]
        _fields(version, ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV"), "version pins")
        _same(checkout["pins"], version, "checkout pins")
        manifest = self.source_body(MANIFEST_PATH)
        _same(self.api.strict_json(manifest, integers_only=True), self.contract, "retained contract")
        _same(self.report["contract_sha256"], hashlib.sha256(manifest).hexdigest(), "manifest identity")
        _same(self.document("contract_snapshot", "contract"), self.contract, "contract snapshot")
        _same(self.document("fixture_snapshot", "selected-fixtures"), self.cases, "selected independent fixtures")
        corpus = self.inventory(self.report["corpus"], "fixture corpus", expected=CORPUS)
        for name, row in corpus.items():
            _same(row, self.sources[name], "fixture descriptor")
            _same(self.source_body(name), (ROOT / name).read_bytes(), "trusted independent fixture bytes")
        _same(self.source_body(CORPUS[-1]), render_header(load_cases(ROOT)), "independent fixture header")
        for path, digest, field in (("profiles/p02-tfr.json", PROFILE_SHA256, "profile_sha256"),
                                    ("sw/kernel/ai/matmul.cpp", KERNEL_SHA256, "kernel_source_sha256")):
            _same(self.sources[path]["sha256"], digest, "frozen " + path)
            _same(self.report[field], digest, "reported " + path)
        self.inventory(self.dependencies, "dependencies", expected=DEPENDENCIES)

    def paths_and_tools(self):
        _fields(self.report["paths"], ("source", "tools", "work", "output", "host_bin", "verilator"), "paths")
        self.paths = {key: self.api.recorded_absolute(value) if value is not None else None
                      for key, value in self.report["paths"].items()}
        require(all(self.paths[key] is not None for key in ("source", "tools", "work", "output", "verilator")),
                "missing execution root")
        for key in ("work", "output"):
            path = self.paths[key]
            require(not any(path == other or path in other.parents or other in path.parents
                            for name, other in self.paths.items()
                            if name in ("source", "tools", "work", "output") and name != key), "execution roots overlap")
        self.build = self.paths["work"] / self.variant_id
        names = set(HOST_TOOLS) | set(TOOL_SUFFIXES)
        if self.driver == "rtlsim":
            names.update(("verilator", "verilator_bin"))
        _fields(self.tools, names, "tools")
        for key, row in self.tools.items():
            _fields(row, ("path", "resolved_path", "sha256", "size_bytes"), "tool " + key)
            self.api.recorded_absolute(row["path"])
            self.api.recorded_absolute(row["resolved_path"])
            require(type(row["sha256"]) is str and archive_helpers.SHA256.fullmatch(row["sha256"]), "invalid tool digest")
            _integer(row["size_bytes"], 1, (1 << 64) - 1, "tool bytes")
            if key in TOOL_SUFFIXES:
                _same(row["path"], str(self.paths["tools"] / TOOL_SUFFIXES[key]), "selected tool " + key)
            if key in ("verilator", "verilator_bin"):
                _same(row["path"], str(self.paths["verilator"] / "bin" / key), "selected Verilator tool")
        first = self.report["commands"][0]
        require(type(first) is dict and type(first.get("environment")) is dict, "invalid initial environment")
        env = first["environment"]
        expected = {"PATH": env.get("PATH"), "TMPDIR": str(self.paths["work"] / "tmp"),
                    "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "CCACHE_DISABLE": "1", "OBJCACHE": "", "MAKEFLAGS": "-j" + str(self.limits["jobs"]),
                    "THREADS": str(self.limits["jobs"]), "CMAKE_BUILD_PARALLEL_LEVEL": str(self.limits["jobs"])}
        _same(env, expected, "sanitized environment")
        require(type(env["PATH"]) is str, "invalid PATH")
        paths = env["PATH"].split(":")
        for path in paths:
            self.api.recorded_absolute(path)
        host = [str(self.paths["host_bin"])] if self.paths["host_bin"] else []
        interpreter = str(PurePosixPath(self.tools["python3"]["path"]).parent)
        _same(paths, list(dict.fromkeys([*host, interpreter, "/usr/bin", "/bin"])), "bounded PATH")
        for key in HOST_TOOLS:
            path = PurePosixPath(self.tools[key]["path"])
            require(path.name == key and str(path.parent) in paths, "host tool escaped bounded PATH")
        self.env = env

    def command(self, command_id, argv, cwd, environment, timeout, *, read=False):
        require(self.command_index < len(self.report["commands"]), "missing planned command")
        row = self.report["commands"][self.command_index]
        self.command_index += 1
        _fields(row, archive_helpers.COMMAND_FIELDS, "command " + command_id)
        for key, expected in (("id", command_id), ("argv", [str(arg) for arg in argv]), ("cwd", str(cwd)),
                              ("environment", environment), ("timeout_seconds", timeout), ("outcome", "pass"),
                              ("exit_code", 0), ("reason", None), ("process_started", True), ("cleanup_complete", True),
                              ("limitations", list(PROCESS_LIMITATIONS)), ("log", "logs/" + command_id + ".log")):
            _same(row[key], expected, "command " + command_id + "." + key)
        _number(row["duration_seconds"], 0, timeout + 10, "command duration")
        _integer(row["peak_rss_bytes"], 0, self.limits["max_rss_bytes"], "command peak RSS")
        _integer(row["log_size_bytes"], 0, self.limits["max_log_bytes"], "command log size")
        descriptor = {"path": row["log"], "sha256": row["log_sha256"], "size_bytes": row["log_size_bytes"]}
        body = self.verified(descriptor)
        self.log_rows.append(descriptor)
        return (body.decode("utf-8") if read else None), row

    def generated(self):
        row = self.variant
        self.frozen = self.inventory(row["artifacts_before"], "frozen artifacts", expected=_artifacts(self.driver))
        for value in self.frozen.values():
            _integer(value["size_bytes"], 1, self.api.MEMBER_BYTES, "frozen artifact bytes")
        _same(row["artifacts_after"], row["artifacts_before"], "artifact stability")
        for value in self.inventory(row["generated_identity"], "generated identity", expected=GENERATED + COPIED).values():
            _same(value, self.frozen[value["path"]], "generated file identity")
        stages = row["retained_builds"]
        require(type(stages) is list and len(stages) == 4, "missing retained build stages")
        names = [name for name in self.frozen if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt", ".py"))
                 or PurePosixPath(name).name == "Makefile" or name == HEADER_PROBE]
        self.stages = {}
        for stage, expected in zip(stages, ("configured", "runtime", "built", "frozen")):
            _fields(stage, ("stage", "files"), "retained stage")
            _same(stage["stage"], expected, "build stage order")
            prefix = "artifacts/" + self.variant_id + "/" + expected + "/"
            rows = self.inventory(stage["files"], "build " + expected, sorted_paths=True)
            values = {}
            for name, value in rows.items():
                require(name.startswith(prefix) and name[len(prefix):] in names, "unexpected retained build input")
                relative = name[len(prefix):]
                _same(dict(value, path=relative), self.frozen[relative], "retained build identity")
                self.verified(value)
                values[relative] = value
            require(set(GENERATED + COPIED) <= set(values), "build stage omits generated inputs")
            self.stages[expected] = values
        _same(list(self.stages["frozen"]), names, "final retained build inventory")
        _same(self.build_body(HEADER_PROBE), b"#include <VX_config.h>\n", "include probe")
        for name in (*COPIED, APP + "/Makefile"):
            _same(self.build_body(name), self.source_body(name), "copied source " + name)
        config = self.build_body("config.mk").decode("utf-8")
        for key, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("VORTEX_HOME", str(self.paths["source"])),
                              ("TOOLDIR", str(self.paths["tools"])), ("OSVERSION", "ubuntu/focal")):
            values = re.findall(r"^" + key + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", config, re.MULTILINE)
            _same(values, [expected], "generated config " + key)
        tokens = self.build_body(".config.stamp").decode("utf-8").strip().split()
        require(all("=" in token for token in tokens), "invalid configure stamp")
        stamp = dict(token.split("=", 1) for token in tokens)
        require(len(stamp) == len(tokens), "duplicate configure settings")
        for key, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("SOURCE_DIR", str(self.paths["source"])),
                              ("BUILDDIR", str(self.build)), ("TOOLDIR", str(self.paths["tools"]))):
            _same(stamp.get(key), expected, "configure stamp " + key)
        _same(self.build_body("sim/rtlsim/verilator.vlt").decode("utf-8"),
              self.source_body("sim/rtlsim/verilator.vlt.in").decode("utf-8").replace("@VORTEX_HOME@", str(self.paths["source"])),
              "generated Verilator configuration")

    def compiler_commands(self):
        source, build, env = self.paths["source"], self.build, self.env
        versions = ("g++", "clang", "make", "python3", "riscv-gcc") + (("verilator",) if self.driver == "rtlsim" else ())
        for name in versions:
            self.command("version-" + name.replace("+", "p"), [self.tools[name]["path"], "--version"], self.paths["work"], env, 30)
        self.command(self.variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                     "--osversion=ubuntu/focal", "--tooldir=" + str(self.paths["tools"])], build, env, self.limits["configure_timeout_seconds"])
        preprocessor = [self.tools["g++"]["path"], "-E", "-dM", "-x", "c++"]
        tail = ["-include", build / "sw/VX_config.h", "/dev/null"]
        text, _ = self.command(self.variant_id + "-header", [*preprocessor, "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", *tail],
                               build, env, 30, read=True)
        initial = validate_header_macros(text)
        _same(self.variant["header_macros"], initial, "initial header macros")
        for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
            self.command(self.variant_id + "-" + language + "-header-reproduce", [self.tools["python3"]["path"],
                         source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr",
                         "--format=" + language, "--output=" + str(build / PurePosixPath(HEADER_PROBE).parent / PurePosixPath(relative).name)],
                         build, dict(env, XLEN="64"), 30)
        config = "-DITYPE=" + self.fmt + " -DOTYPE=fp32 -DKUNROLL=1"
        text, _ = self.command(self.variant_id + "-expected-flags", [self.tools["python3"]["path"], source / "ci/gen_config.py",
                               "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr", "--xlen=64", "--format=cflags",
                               "--cflags=" + config + " -DVX_CFG_XLEN=64"], build, env, 30, read=True)
        flags = _stamp_flags(text, "retained generated flags")
        require(flags and all(flag.startswith("-D") for flag in flags), "invalid generated flags")
        text, _ = self.command(self.variant_id + "-expected-expanded-header", [*preprocessor, *flags,
                               *("-D" + name + "_DISABLE" for name in DISABLED), *tail], build, env, 30, read=True)
        expanded = validate_header_macros(text)
        backend = dict(initial, **{name + "_DISABLE": "1" for name in DISABLED})
        _same(self.variant["expected_expanded_header_macros"], expanded, "expanded configuration")
        _same(self.variant["expected_backend_header_macros"], backend, "backend configuration")
        make = [self.tools["make"]["path"], "--no-print-directory", "-j" + str(self.limits["jobs"]),
                "THREADS=" + str(self.limits["jobs"]), "VERILATOR_PATH=" + str(self.paths["verilator"])]
        app = build / APP
        current = dict(env, CONFIGS=config)
        self.command(self.variant_id + "-runtime", [*make, "runtime-" + self.driver], app, current, self.limits["build_timeout_seconds"])
        self.command(self.variant_id + "-application", [*make, "all"], app, current, self.limits["build_timeout_seconds"])
        self.compiler = validate_records(self.build_body("sw/runtime/" + self.driver + "_rt_config.stamp").decode("utf-8"),
            self.build_body("sw/runtime/" + self.driver + "_config.stamp").decode("utf-8"),
            self.build_body(APP + "/config.stamp").decode("utf-8"), driver=self.driver, fmt=self.fmt,
            source=Path(str(source)), build=Path(str(build)), jobs=self.limits["jobs"])
        _same(self.variant["compiler_records"], self.compiler, "independent original compiler records")
        self.effective = {}
        directories = {"runtime": build / "sw/runtime" / self.driver,
                       "backend_cpp": build / "sim" / self.driver, "verilator": build / "sim" / self.driver,
                       "kernel": app, "host": app}
        for record in self.compiler:
            role = record["role"]
            command_id = self.variant_id + "-" + role + "-header"
            text, _ = self.command(command_id, [*preprocessor, *record["macro_flags"],
                                   *("-I" + name for name in record["include_paths"]), build / HEADER_PROBE],
                                   directories[role], env, 30, read=True)
            expected = dict(backend if role in ("backend_cpp", "verilator") else expanded)
            if self.driver == "rtlsim" and role == "backend_cpp":
                expected.pop("VX_CFG_TCU_TYPE_TFR", None)
                expected.pop("VX_CFG_FPU_TYPE_STD", None)
            self.effective[role] = {"command_id": command_id, "macros":
                validate_effective_header(text, expected, driver=self.driver, role=role)}
        _same(self.variant["effective_headers"], self.effective, "effective compiler configuration")

    def processes(self):
        _same(self.report["expected_processes"], self.plan, "expected process plan")
        rows = self.report["processes"]
        require(type(rows) is list and len(rows) == 2, "missing or duplicate policy process")
        result = []
        for row, planned in zip(rows, self.plan):
            _fields(row, set(planned) | {"binding", "command_id", "log", "observation", "outcome", "qualification_id"}, "process")
            for key, expected in planned.items():
                _same(row[key], expected, "process." + key)
            _same(row["outcome"], "pass", "process outcome")
            process_id = planned["id"]
            binding = {"contract_id": CONTRACT_ID, "contract_sha256": self.report["contract_sha256"],
                "source": self.source, "backend": self.driver, "format": self.fmt, "policy": planned["policy"],
                "process_id": process_id, "sequence": self.contract["sequence"], "cases": self.cases,
                "corpus": self.report["corpus"], "profile_sha256": PROFILE_SHA256, "kernel_source_sha256": KERNEL_SHA256,
                "compiler_records": self.compiler, "effective_headers": self.effective,
                "generated_identity": self.variant["generated_identity"], "artifacts": self.variant["artifacts_before"],
                "tools": self.tools, "dependencies": self.dependencies}
            actual = self.api.strict_json(self.verified(row["binding"], "snapshots/" + process_id + "-binding.json"))
            _same(actual, binding, "reconstructed execution binding")
            binding_id = qualification_id(binding)
            _same(row["qualification_id"], binding_id, "qualification identity")
            _same(row["command_id"], process_id, "process command")
            _same(row["log"], "logs/" + process_id + ".log", "process log")
            app = self.build / APP
            text, _ = self.command(process_id, [app / "ai_workspace", "--policy", planned["policy"],
                                   "--module", app / "kernel.vxbin", "--qualification-id", binding_id], app,
                                   dict(self.env, VORTEX_DRIVER=self.driver, LD_LIBRARY_PATH=str(self.build / "sw/runtime")),
                                   self.limits["run_timeout_seconds"], read=True)
            observed = verify_output(text, cases=self.cases, fmt=self.fmt, policy=planned["policy"],
                                     binding_id=binding_id, contract=self.contract)
            _same(row["observation"], observed, "recomputed original output")
            result.append({"id": process_id, "policy": planned["policy"], "qualification_id": binding_id,
                           "launches": sum(op["dispatch"]["launches"] for op in observed["operations"]),
                           "checked_words": sum(op["checked"] for op in observed["operations"]),
                           "buffer_creates": observed["summary"]["counts"]["buffer_create_calls"],
                           "buffer_releases": observed["summary"]["counts"]["buffer_release_calls"]})
        _same(self.command_index, len(self.report["commands"]), "unexpected trailing command")
        _same(self.report["raw_logs"], self.log_rows, "original raw-log inventory")
        counts = {"processes": len(result), "launches": sum(row["launches"] for row in result),
                  "checked_words": sum(row["checked_words"] for row in result)}
        _same(counts, {"processes": 2, "launches": 8, "checked_words": 256}, "recomputed selected counts")
        _same(self.report["selected_counts"], counts, "reported selected counts")
        for key, value in (("completed_processes", counts["processes"]), ("completed_launches", counts["launches"]),
                           ("checked_words", counts["checked_words"])):
            _same(self.report[key], value, "completed " + key)
        labels = ["before-" + self.variant_id]
        for row in self.plan:
            labels.extend(("before-" + row["id"], "after-" + row["id"]))
        labels.append("after-" + self.variant_id)
        checks = self.report["stability_checks"]
        require(type(checks) is list and len(checks) == len(labels), "missing stability observations")
        previous = self.started
        for check, label in zip(checks, labels):
            _fields(check, ("at", "label", "source_sha256", "tools_sha256", "dependencies_sha256"), "stability observation")
            _same(check["label"], label, "stability order")
            at = _timestamp(check["at"])
            require(previous <= at <= self.finished, "stability timestamps are outside chronology")
            previous = at
            for name, observed in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
                _same(check[name + "_sha256"], qualification_id(observed), "stability identity " + name)
        return counts, result

    def hosted_identity(self):
        parent = str(PurePosixPath(self.view.prefix).parent) if self.view.prefix else ""
        outer = self.view.archive.view("" if parent == "." else parent)
        names = {"job.json", "workflow.yml", "python-provision.json"}
        present = names.intersection(outer.files())
        if not present:
            return None
        _same(present, names, "complete hosted identity")
        job = outer.json("job.json")
        _fields(job, ("GITHUB_SHA", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
                      "GITHUB_REPOSITORY", "GITHUB_REF", "P06_WORKSPACE_BACKEND", "P06_WORKSPACE_FORMAT",
                      "scope", "native_execution", "acceptance_claimed", "workflow_sha256"), "hosted job")
        for key, expected in (("GITHUB_SHA", self.revision), ("GITHUB_REPOSITORY", "baabi-boo/AI-GPU"),
                              ("GITHUB_JOB", "qualification"), ("P06_WORKSPACE_BACKEND", self.driver),
                              ("P06_WORKSPACE_FORMAT", self.fmt), ("scope", "native-serial-workspace-correctness"),
                              ("native_execution", "not_run"), ("acceptance_claimed", False)):
            _same(job[key], expected, "hosted " + key)
        require(job["GITHUB_EVENT_NAME"] in ("push", "pull_request", "workflow_dispatch"), "invalid hosted event")
        for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            require(type(job[key]) is str and re.fullmatch(r"[1-9][0-9]{0,20}", job[key]), "invalid hosted run identity")
        require(type(job["GITHUB_REF"]) is str
                and re.fullmatch(r"refs/((heads|tags)/[^\s]+|pull/[1-9][0-9]*/merge)", job["GITHUB_REF"]), "invalid hosted ref")
        if job["GITHUB_EVENT_NAME"] == "push":
            _same(job["GITHUB_REF"], "refs/heads/master", "hosted push branch")
        elif job["GITHUB_EVENT_NAME"] == "pull_request":
            require(re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", job["GITHUB_REF"]), "hosted PR ref differs")
        workflow = outer.read("workflow.yml", limit=256 * 1024)
        _same(workflow, self.source_body(".github/workflows/p06-workspace.yml"), "hosted workflow source")
        _same(job["workflow_sha256"], hashlib.sha256(workflow).hexdigest(), "hosted workflow hash")
        provision = outer.json("python-provision.json")
        _fields(provision, ("python_version", "implementation", "platform", "executable", "python3_on_path"), "Python provision")
        for key, expected in (("python_version", [3, 12, 14]), ("implementation", "CPython"), ("platform", "linux")):
            _same(provision[key], expected, "provisioned " + key)
        self.api.recorded_absolute(provision["executable"])
        _same(provision["python3_on_path"], self.tools["python3"]["path"], "provisioned interpreter")
        require(provision["executable"] in (self.tools["python3"]["path"], self.tools["python3"]["resolved_path"]),
                "Python provisioning differs from executed tool")
        return job

    def run(self):
        _fields(self.report, REPORT_FIELDS, "workspace report")
        for key, expected in (("schema_version", 1), ("contract_id", CONTRACT_ID), ("scope", "native-correctness-and-managed-ownership"),
                              ("state", "finished"), ("outcome", "pass"), ("reason", None), ("failures", []),
                              ("acceptance_claimed", False), ("performance_acceptance", False), ("phase_acceptance", False),
                              ("phase_complete", False), ("full_matrix_requested", False), ("full_matrix_completed", False),
                              ("selected_scope_completed", True), ("retained_files_stable", True),
                              ("complete_matrix", self.contract["complete_matrix"])):
            _same(self.report[key], expected, "report." + key)
        require(type(self.report["limitations"]) is list and self.report["limitations"]
                and all(type(value) is str and value for value in self.report["limitations"]), "missing execution limitations")
        self.started, self.finished = (_timestamp(self.report[key]) for key in ("started_at", "finished_at"))
        require(self.started <= self.finished, "execution timestamps are reversed")
        require(type(self.report["commands"]) is list and len(self.report["commands"]) == (21 if self.driver == "rtlsim" else 19),
                "unexpected command inventory")
        require(type(self.report["variants"]) is list and len(self.report["variants"]) == 1, "expected one selected variant")
        self.variant = self.report["variants"][0]
        _fields(self.variant, ("artifacts_after", "artifacts_before", "backend", "build_dir", "compiler_records", "effective_headers",
                              "expected_backend_header_macros", "expected_expanded_header_macros", "format", "generated_identity",
                              "header_macros", "id", "outcome", "process_ids", "retained_builds"), "variant")
        for key, expected in (("id", self.variant_id), ("backend", self.driver), ("format", self.fmt), ("outcome", "pass"),
                              ("process_ids", [row["id"] for row in self.plan])):
            _same(self.variant[key], expected, "variant." + key)
        self.budget()
        self.provenance()
        self.paths_and_tools()
        _same(self.variant["build_dir"], str(self.build), "variant build path")
        self.generated()
        self.log_rows = []
        self.compiler_commands()
        counts, processes = self.processes()
        hosted = self.hosted_identity()
        _same(set(self.view.files()), self.used_members, "complete workspace packet member inventory")
        return {"schema_version": 1, "scope": "p06-workspace-selected-variant-retained-data-replay", "outcome": "pass",
                "native_execution": "not_run", "acceptance_claimed": False, "performance_acceptance": False,
                "phase_acceptance": False, "phase_complete": False, "full_matrix_completed": False,
                "source_revision": self.revision, "source_tree": self.source["checkout"]["tree"],
                "source_snapshot_sha256": qualification_id(self.source), "backend": self.driver, "format": self.fmt,
                "report_identity": self.view.identity("report.json"), "commands_checked": self.command_index,
                "retained_source_files_checked": len(self.sources), "selected_counts": counts, "processes": processes,
                "tools": {key: {"sha256": value["sha256"], "size_bytes": value["size_bytes"]} for key, value in self.tools.items()},
                "dependencies": self.dependencies, "hosted_job_identity": hosted, "limitations": LIMITATIONS}


def replay_archive(path, sha256, *, expected_revision, expected_backend, expected_format, prefix="workspace"):
    """Recheck one selected variant against externally supplied original identities."""
    require(type(expected_revision) is str and archive_helpers.REVISION.fullmatch(expected_revision), "invalid external source revision")
    require(type(expected_backend) is str and expected_backend in BACKENDS, "invalid external backend")
    require(type(expected_format) is str and expected_format in FORMATS, "invalid external format")
    trusted = _trusted_sources()
    api = archive_helpers._archive_api()
    try:
        with api.ArchiveReader(path, sha256) as archive:
            result = _Replay(archive.view(prefix), api, expected_revision, expected_backend, expected_format).run()
            result["archive_read"] = archive.receipt()
            result["trusted_archive_reader"] = {"path": archive_helpers.ARCHIVE_READER_PATH,
                                                "sha256": archive_helpers.ARCHIVE_READER_SHA256}
            _same(_trusted_sources(), trusted, "executing replay source stability")
            result["trusted_replay_sources"] = trusted
            return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError) as error:
        raise ReplayError("malformed retained workspace packet: " + str(error)) from error


def replay_matrix(archives, *, expected_revision):
    """Require all four distinct variants from one compatible execution checkpoint."""
    require(type(archives) is list and len(archives) == 4, "workspace matrix requires exactly four archives")
    selections = {}
    for row in archives:
        _fields(row, ("path", "sha256", "backend", "format"), "archive selection")
        require(type(row["backend"]) is str and type(row["format"]) is str, "invalid archive selection type")
        key = (row["backend"], row["format"])
        require(key not in selections, "duplicate workspace variant")
        selections[key] = row
    _same(set(selections), {(driver, fmt) for driver in BACKENDS for fmt in FORMATS}, "complete variant matrix")
    results = []
    for driver in BACKENDS:
        for fmt in FORMATS:
            row = selections[driver, fmt]
            results.append(replay_archive(row["path"], row["sha256"], expected_revision=expected_revision,
                                          expected_backend=driver, expected_format=fmt))
    first = results[0]
    for row in results[1:]:
        for key in ("source_revision", "source_tree", "source_snapshot_sha256", "dependencies"):
            _same(row[key], first[key], "matrix " + key)
        for name in set(first["tools"]) & set(row["tools"]):
            _same(row["tools"][name], first["tools"][name], "matrix tool " + name)
        a, b = first["hosted_job_identity"], row["hosted_job_identity"]
        require((a is None) == (b is None), "mixed hosted/non-hosted matrix")
        if a is not None:
            for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_EVENT_NAME", "GITHUB_REF",
                        "GITHUB_REPOSITORY", "GITHUB_JOB", "workflow_sha256"):
                _same(b[key], a[key], "matrix hosted " + key)
    counts = {key: sum(row["selected_counts"][key] for row in results) for key in ("processes", "launches", "checked_words")}
    _same(counts, {"processes": 8, "launches": 32, "checked_words": 1024}, "complete verified matrix counts")
    return {"schema_version": 1, "scope": "p06-workspace-complete-matrix-retained-data-replay", "outcome": "pass",
            "native_execution": "not_run", "acceptance_claimed": False, "performance_acceptance": False,
            "phase_acceptance": False, "phase_complete": False, "full_matrix_completed": True,
            "source_revision": expected_revision, "source_tree": first["source_tree"], "counts": counts,
            "variants": results, "limitations": LIMITATIONS}


def _selection(value):
    parts = value.split(":", 3)
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("use BACKEND:FORMAT:SHA256:ABSOLUTE_PATH")
    driver, fmt, digest, path = parts
    if driver not in BACKENDS or fmt not in FORMATS or not archive_helpers.SHA256.fullmatch(digest) or not path.startswith("/"):
        raise argparse.ArgumentTypeError("invalid backend, format, SHA-256 or absolute archive path")
    return {"backend": driver, "format": fmt, "sha256": digest, "path": Path(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=_selection, action="append", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = replay_matrix(args.archive, expected_revision=args.source_revision)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "counts": result["counts"], "native_execution": "not_run",
                              "acceptance_claimed": False, "report": str(args.output)}))
        else:
            print(body, end="")
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "native_execution": "not_run", "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
