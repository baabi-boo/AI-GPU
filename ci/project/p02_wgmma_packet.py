#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify a complete original WGMMA runner packet without executing its code.

Exit zero means retained evidence is consistent, including a faithfully recorded
parity or witness failure. It never grants P02-A03 acceptance. Development and
subset packets remain development/subset evidence. Interrupted/incomplete runs
and relocated or normalized publication packets are outside this entry point.

An independently obtained --report-sha256 anchors the report. Without it this
checks internal consistency, not authenticity. Omitted binary/source bodies are
not reconstructed, executed, or fetched from the original source/build paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from baseline_inventory import SOURCE_INPUTS, _digest, hash_artifacts
from baseline_packet_io import (PacketReader, _json_float, _json_integer,
                                _reject_constant, _relative_path, _unique_keys)
import p02_wgmma_matrix as matrix
from p02_wgmma_records import require, validate_header_macros, validate_records, verify_output
from p02_wgmma_witness import verify_witness


ROOT = matrix.ROOT
MIB = 1024 ** 2
MAX_JSON_BYTES = 32 * MIB
MAX_MEMBER_BYTES = 64 * MIB
MAX_FILES = 16384
HELPERS = tuple("ci/project/" + name + ".py" for name in (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract", "baseline_packet_io",
    "baseline_process", "compiler_records", "p02_matrix", "p02_matrix_records",
    "p02_wgmma_dependencies", "p02_wgmma_fixture_oracle", "p02_wgmma_matrix",
    "p02_wgmma_records", "preflight"))
WITNESS_PARSER = "ci/project/p02_wgmma_witness.py"
# The shared checkout inventory includes blackbox.sh, which this runner does not invoke.
CHECKOUT_ONLY_INPUTS = ("ci/blackbox.sh",)
# The v1 runner retains these direct consumer inputs unconditionally. Declare
# the minimum here: matching packet snapshots cannot make a required file
# optional by omitting its entire identity and retained-body chain.
CONSUMER_INPUTS = (
    matrix.APP + "/Makefile", matrix.APP + "/fixtures.h", matrix.APP + "/main.cpp",
    "tests/regression/sgemm_tcu_wg/Makefile", "tests/regression/sgemm_tcu_wg/common.h",
    "tests/regression/sgemm_tcu_wg/kernel.cpp", "tests/regression/sgemm_tcu_wg/main.cpp",
    "tests/regression/sgemm_tcu_wg_sp/Makefile", "tests/regression/sgemm_tcu_wg_sp/common.h",
    "tests/regression/sgemm_tcu_wg_sp/kernel.cpp", "tests/regression/sgemm_tcu_wg_sp/main.cpp",
)
HEADER_ROOTS = tuple("third_party/ramulator/ext/" + name + "/include/"
                     for name in ("spdlog", "yaml-cpp"))


def same(actual, expected, label):
    """JSON equality which does not equate booleans, integers and floats."""
    require(json.dumps(actual, sort_keys=True, allow_nan=False) ==
            json.dumps(expected, sort_keys=True, allow_nan=False), label + " differs")


def parse_json(contents, label):
    require(len(contents) <= MAX_JSON_BYTES, label + " exceeds JSON byte limit")
    text = contents.decode("utf-8", errors="strict")
    depth = tokens = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            tokens += 1
        elif char in "[{":
            depth += 1
            tokens += 1
            require(depth <= 64, label + " exceeds JSON depth limit")
        elif char in "]}":
            depth -= 1
        elif char in ",:":
            tokens += 1
        require(tokens <= 2000000, label + " exceeds JSON structure limit")
    return json.loads(text, object_pairs_hook=_unique_keys, parse_int=_json_integer,
                      parse_float=_json_float, parse_constant=_reject_constant)


def absolute(value):
    require(type(value) is str and value.startswith("/"), "original path must be absolute")
    _relative_path(value[1:])
    return Path(value)


def identity(value):
    require(type(value) is dict and set(value) == {"path", "sha256", "size_bytes"},
            "invalid file identity fields")
    _relative_path(value["path"])
    require(type(value["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
            "invalid SHA-256 identity")
    require(type(value["size_bytes"]) is int and 0 <= value["size_bytes"] <= 2 ** 40,
            "invalid file size")
    return value


def inventory(values, label):
    require(type(values) is list and len(values) <= MAX_FILES, label + " has invalid inventory")
    result = {}
    for value in values:
        row = identity(value)
        require(row["path"] not in result, label + " repeats a path")
        result[row["path"]] = row
    return result


class Reader(PacketReader):
    """Use the canonical no-follow reader with a matrix-sized file-count cap."""

    def __init__(self, root):
        super().__init__(root)
        self._max_files = MAX_FILES
        self._inodes = {}

    def _read(self, relative, limit, retain):
        contents = super()._read(relative, limit, retain)
        state = self._states[relative]
        require(state[2] == 1, "packet member has hard-link aliases: " + relative)
        previous = self._inodes.setdefault(state[0], relative)
        require(previous == relative, "packet members alias the same file")
        return contents

    def checked(self, row, *, contents=False, limit=MAX_MEMBER_BYTES):
        identity(row)
        if contents:
            data = self.read_bytes(row["path"], limit=limit)
            observed = {"path": row["path"], "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data)}
        else:
            observed = self.identity(row["path"], limit=limit)
        same(observed, row, "retained file " + row["path"])
        return data if contents else observed

    def json(self, row):
        return parse_json(self.checked(row, contents=True, limit=MAX_JSON_BYTES), row["path"])

    def text(self, row):
        return self.checked(row, contents=True, limit=matrix.BUDGET["max_log_bytes"]).decode("utf-8")


def bind_copies(reader, values, original, prefix, expected):
    copied = inventory(values, prefix)
    require(set(copied) == {prefix + name for name in expected}, prefix + " inventory differs")
    for name in expected:
        row = copied[prefix + name]
        require(name in original, prefix + " lacks original identity: " + name)
        same(dict(row, path=name), original[name], "copied/original identity " + name)
        reader.checked(row)
    return {name: copied[prefix + name] for name in expected}


def bind_checkout_inputs(values, files):
    inputs = inventory(values, "checkout inputs")
    same(sorted(inputs), sorted(SOURCE_INPUTS), "checkout input inventory")
    outside = []
    for path, row in inputs.items():
        if path in files:
            same(row, files[path], "checkout/source input " + path)
        else:
            require(path in CHECKOUT_ONLY_INPUTS,
                    "checkout input lacks execution source identity: " + path)
            outside.append(row)
    return sorted(outside, key=lambda row: row["path"])


def verify_source(reader, report, variants):
    before = reader.json(report["source_before"])
    require(type(before) is dict and set(before) == {"checkout", "files"}, "invalid source snapshot")
    checkout = before["checkout"]
    require(type(checkout) is dict and type(checkout["dirty"]) is bool, "invalid source checkout")
    for key in ("revision", "tree"):
        require(type(checkout[key]) is str and re.fullmatch(r"[0-9a-f]{40}", checkout[key]),
                "invalid source " + key)
    for key in ("changed_paths", "untracked_paths"):
        require(type(checkout[key]) is list and len(checkout[key]) == len(set(checkout[key])),
                "invalid source changed paths")
        for path in checkout[key]:
            _relative_path(path)
    same(checkout["dirty"], bool(checkout["changed_paths"] or checkout["untracked_paths"]), "source dirty state")
    matrix._source_ok(before, report["development"])
    same(report["source_revision"], checkout["revision"], "source revision")
    same(report["source_dirty"], checkout["dirty"], "source dirty observation")
    snapshots = {"source_before": "source-before", "source_after": "source-after"}
    for variant in variants:
        for suffix in ("before", "built", "after"):
            label = variant["id"] + "-" + suffix
            snapshots["source_" + label] = "source-" + label
    recorded = {key for key, value in report.items() if key.startswith("source_") and type(value) is dict}
    same(sorted(recorded), sorted(snapshots), "source stability snapshot inventory")
    for key, name in snapshots.items():
        same(report[key]["path"], "snapshots/" + name + ".json", "source snapshot path")
        same(reader.json(report[key]), before, "source stability " + key)
    files = inventory(before["files"], "source files")
    checkout_only = bind_checkout_inputs(checkout["inputs"], files)
    helpers = inventory(report["loaded_helpers"], "loaded helpers")
    same(sorted(helpers), sorted(HELPERS), "loaded helper closure")
    saved = set(HELPERS + (matrix.MANIFEST, WITNESS_PARSER) + matrix.CORPUS + matrix.COPIED
                + matrix.CONFIG_INPUTS + CONSUMER_INPUTS)
    for path in files:
        if str(Path(path).parent) in (matrix.APP, "tests/regression/sgemm_tcu_wg", "tests/regression/sgemm_tcu_wg_sp"):
            if Path(path).suffix in matrix.SOURCE_SUFFIXES or Path(path).name == "Makefile":
                saved.add(path)
    if report["witness_requested"]:
        saved.add("sim/rtlsim/p02_wgmma_scoreboard_monitor.sv")
        same(report["witness_parser"], files.get(WITNESS_PARSER), "witness parser identity")
    for path, row in helpers.items():
        same(row, files.get(path), "loaded helper source " + path)
    retained = bind_copies(reader, report["source_snapshots"], files, "artifacts/source/", saved)
    return files, retained, checkout_only


def verify_tools(reader, report, backends):
    for key in ("tools_before", "tools_after"):
        same(report[key]["path"], "snapshots/" + key.replace("_", "-") + ".json", "tool snapshot path")
    tools = reader.json(report["tools_before"])
    same(reader.json(report["tools_after"]), tools, "tool stability")
    names = {"make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl", "clang", "clang++",
             "llvm-objcopy", "llvm-objdump", "riscv-gcc", "riscv-gcc-ar", "riscv-objdump", "riscv-objcopy",
             "libc64/lib/libc.a", "libc64/lib/libm.a", "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"}
    if "rtlsim" in backends:
        names |= {"verilator", "verilator_bin"}
    require(type(tools) is dict and set(tools) == names, "tool inventory differs")
    for row in tools.values():
        require(type(row) is dict and set(row) == {"path", "resolved_path", "sha256", "size_bytes"},
                "invalid tool identity")
        absolute(row["path"])
        absolute(row["resolved_path"])
        identity({"path": "tool", "sha256": row["sha256"], "size_bytes": row["size_bytes"]})
    dependencies = inventory(report["dependencies_before"], "dependencies")
    same(sorted(dependencies), sorted(matrix.DEPENDENCIES), "dependency inventory")
    same(report["dependencies_after"], report["dependencies_before"], "dependency stability")
    headers = inventory(report["dependency_headers_before"], "dependency headers")
    require(all(any(path.startswith(prefix) for prefix in HEADER_ROOTS) for path in headers)
            and all(any(path.startswith(prefix) for path in headers) for prefix in HEADER_ROOTS),
            "dependency header inventory is incomplete")
    same(list(headers), sorted(headers), "dependency header ordering")
    same(report["dependency_headers_after"], report["dependency_headers_before"], "dependency header stability")
    return tools


def retained_name(path):
    return path.endswith((".stamp", ".mk", ".h", ".vh", ".vlt", ".elf", ".vxbin", ".dat", ".d")) or Path(path).name in ("Makefile", "p02_wgmma")


def verify_build(reader, report, variant, sources, source_files, commands):
    original = inventory(variant["artifacts_before"], variant["id"] + " artifacts")
    same(variant["artifacts_after"], variant["artifacts_before"], "build artifact stability")
    generated = inventory(variant["generated_before"], "generated inputs")
    same(sorted(generated), sorted(matrix.GENERATED + matrix.COPIED), "generated input inventory")
    driver = variant["backend"]
    required = set(matrix.GENERATED + matrix.COPIED) | {
        "sw/runtime/" + driver + "_rt_config.stamp", "sw/runtime/" + driver + "_config.stamp",
        matrix.APP + "/config.stamp", matrix.APP + "/p02_wgmma", matrix.APP + "/kernel.elf",
        matrix.APP + "/kernel.vxbin", "sw/kernel/libvortex2.a", "sw/runtime/libvortex.so",
        "sw/runtime/libvortex-" + driver + ".so", "sw/runtime/lib" + driver + ".so"}
    require(required <= original.keys(), "build inventory lacks required artifacts")
    for path, row in generated.items():
        same(row, original[path], "generated input stability " + path)
    for path in matrix.COPIED:
        same(original[path], source_files[path], "copied build input " + path)
    retained = bind_copies(reader, variant["retained_artifacts"], original,
                          "artifacts/" + variant["id"] + "/", {name for name in original if retained_name(name)})
    source, build = absolute(report["paths"]["source"]), absolute(variant["build_dir"])
    same(str(build), str(absolute(report["paths"]["work"]) / variant["id"]), "build directory")
    text = reader.text(retained["config.mk"])
    for key, value in (("XLEN", "64"), ("PROFILE", ""), ("VORTEX_HOME", str(source)),
                       ("TOOLDIR", report["paths"]["tools"]), ("OSVERSION", "ubuntu/focal")):
        same(re.findall(r"^" + key + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", text, re.MULTILINE), [value], "generated " + key)
    tokens = reader.text(retained[".config.stamp"]).strip().split()
    require(all("=" in token for token in tokens), "malformed configure stamp")
    fields = dict(token.split("=", 1) for token in tokens)
    require(len(fields) == len(tokens), "configure stamp repeats settings")
    for key, value in (("XLEN", "64"), ("PROFILE", ""), ("SOURCE_DIR", str(source)),
                       ("BUILDDIR", str(build)), ("TOOLDIR", report["paths"]["tools"])):
        same(fields.get(key), value, "configure stamp " + key)
    same(reader.text(retained["sim/rtlsim/verilator.vlt"]),
         reader.text(sources["sim/rtlsim/verilator.vlt.in"]).replace("@VORTEX_HOME@", str(source)), "Verilator input")
    stamps = [reader.text(retained[path]) for path in ("sw/runtime/" + driver + "_rt_config.stamp",
              "sw/runtime/" + driver + "_config.stamp", matrix.APP + "/config.stamp")]
    observed = validate_records(*stamps, driver=driver, variant=variant["configuration"], source=source,
                                build=build, jobs=report["budget"]["jobs"], witness=variant["witness"])
    same(variant["compiler_records"], observed, "compiler records")
    effective = commands[variant["id"] + "-effective-header"]
    same(variant["effective_backend_configuration"], validate_header_macros(
        reader.text(log_identity(effective)), variant["configuration"]), "effective configuration")
    disassembly = commands[variant["id"] + "-kernel-disassembly"]
    same(variant["kernel_disassembly"], log_identity(disassembly), "disassembly identity")
    require(variant["kernel_disassembly"]["size_bytes"] > 0, "empty kernel disassembly")
    if driver == "rtlsim":
        native = "sw/runtime/librtlsim.so.obj_dir/Vrtlsim_shim"
        for suffix in ("__verFiles.dat", "_classes.mk", "__Syms.h"):
            require(native + suffix in retained and retained[native + suffix]["size_bytes"] > 0,
                    "native hierarchy metadata is incomplete")
    return sorted(path for path in original if path not in retained and Path(path).suffix in (".a", ".so"))


def log_identity(command):
    return {"path": command["log"], "sha256": command["log_sha256"], "size_bytes": command["log_size_bytes"]}


def verify_invocations(report, variant, commands, tools, base_environment):
    """Bind each named successful command to the runner's original arguments."""
    source = absolute(report["paths"]["source"])
    build = absolute(variant["build_dir"])
    app = build / matrix.APP
    jobs = str(report["budget"]["jobs"])
    make = [tools["make"]["path"], "--no-print-directory", "-j" + jobs,
            "THREADS=" + jobs, "VERILATOR_PATH=" + report["paths"]["verilator"]]
    current = dict(base_environment, CONFIGS=" ".join(variant["configs"]), VORTEX_PROFILING="11")
    expected = {
        "configure": ([str(source / "configure"), "--xlen=64", "--profile=", "--osversion=ubuntu/focal",
                       "--tooldir=" + report["paths"]["tools"]], build, base_environment),
        "runtime": (make + ["runtime-" + variant["backend"]], app, current),
        "application-build": (make + ["all"], app, current),
        "effective-header": ([tools["g++"]["path"], "-E", "-dM", "-x", "c++",
            *variant["compiler_records"][1]["macro_flags"], "-include", str(build / "sw/VX_config.h"), "/dev/null"], build, base_environment),
        "kernel-disassembly": ([tools["llvm-objdump"]["path"], "-D", str(app / "kernel.elf")], app, base_environment),
    }
    for language, name in (("cpp", "VX_config.h"), ("verilog", "VX_config.vh")):
        expected[language + "-header-reproduce"] = ([tools["python3"]["path"], str(source / "ci/gen_config.py"),
            "--config=" + str(source / "VX_config.toml"), "--profile=", "--format=" + language,
            "--output=" + str(build / "p02-header-check" / name)], build, dict(base_environment, XLEN="64"))
    for case in variant["cases"]:
        expected[case["id"]] = (make + ["--silent", "run-" + variant["backend"],
            "OPTS=--case=" + case["id"] + " --iterations=2"], app, current)
    for suffix, (argv, cwd, environment) in expected.items():
        cmd = commands[variant["id"] + "-" + suffix]
        same(cmd["argv"], argv, "command arguments " + cmd["id"])
        same(cmd["cwd"], str(cwd), "command directory " + cmd["id"])
        same(cmd["environment"], environment, "command environment " + cmd["id"])


def verify_packet(packet, *, report_sha256=None, require_witness=False):
    """Return independent observations; raise ValueError on unsafe/inconsistent evidence."""
    with Reader(packet) as reader:
        raw = reader.read_bytes("report.json", limit=MAX_JSON_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if report_sha256 is not None:
            require(type(report_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", report_sha256), "invalid report digest")
            same(digest, report_sha256, "external report digest")
        report = parse_json(raw, "report.json")
        require(type(report) is dict, "report must be an object")
        for key, value in {"schema_version": 1, "contract_id": matrix.CONTRACT_ID, "state": "finished",
                "iterations": 2, "acceptance_claimed": False, "qualifies_P02_A03": False,
                "phase_complete": False, "source_frozen_before_execution": True, "source_stable": True}.items():
            same(report[key], value, key)
        for key in ("development", "full_matrix_requested", "witness_requested", "source_dirty"):
            require(type(report[key]) is bool, key + " must be boolean")
        require(type(require_witness) is bool, "require_witness must be boolean")
        require(not require_witness or report["witness_requested"], "requested witness evidence is absent")
        same(str(absolute(report["paths"]["output"])), str(Path(packet).absolute()), "original output path")
        for key in ("source", "work", "tools", "verilator"):
            absolute(report["paths"][key])
        require(type(report["budget"]["jobs"]) is int and report["budget"]["jobs"] in (1, 2), "invalid job budget")
        for key, value in matrix.BUDGET.items():
            same(report["budget"][key], value, "resource budget " + key)
        manifest, fixtures = matrix.load_inputs(ROOT)
        variants = report["variants"]
        require(type(variants) is list and 0 < len(variants) <= 12, "invalid variant inventory")
        expected_variants = {driver + "-" + item["id"]: (driver, item)
                             for driver in matrix.BACKENDS for item in manifest["variants"]}
        ids = [item["id"] for item in variants]
        require(len(ids) == len(set(ids)) and set(ids) <= expected_variants.keys(), "duplicate or unknown variant")
        same(ids, [name for name in expected_variants if name in ids], "variant order")
        full = set(ids) == expected_variants.keys() and all(
            [case["id"] for case in item["cases"]] == expected_variants[item["id"]][1]["cases"] for item in variants)
        same(report["full_matrix_requested"], full, "full matrix inventory")
        require(report["development"] or full, "formal packet has an incomplete matrix")
        for item in variants:
            driver, spec = expected_variants[item["id"]]
            for key, value in {"backend": driver, "configuration_id": spec["id"], "configuration": spec,
                               "profile": "", "witness": report["witness_requested"] and driver == "rtlsim" and spec["sparse"]}.items():
                same(item[key], value, "variant " + key)
            same(item["configs"], manifest["configs"] + spec["configs"] +
                 ([manifest["witness"]["flag"]] if item["witness"] else []), "variant flags")
            names = [case["id"] for case in item["cases"]]
            require(names and len(names) == len(set(names)) and set(names) <= set(spec["cases"]), "invalid case inventory")
            same(names, [name for name in spec["cases"] if name in names], "case order")
        source_files, sources, checkout_only = verify_source(reader, report, variants)
        same(report["manifest"], source_files[matrix.MANIFEST], "manifest identity")
        same(report["manifest"]["sha256"], matrix.MANIFEST_SHA256, "frozen manifest")
        same(reader.json(sources[matrix.MANIFEST]), manifest, "retained manifest")
        same(report["corpus"], manifest["fixture_inputs"], "fixture identities")
        for row in manifest["fixture_inputs"]:
            same(source_files[row["path"]], row, "frozen fixture input")
        same(reader.checked(sources[matrix.CORPUS[0]], contents=True).hex(),
             (json.dumps(matrix.oracle.fixture_document(), indent=2) + "\n").encode().hex(), "reproduced fixture corpus")
        same(reader.checked(sources[matrix.CORPUS[1]], contents=True).hex(),
             matrix.oracle.header_bytes(matrix.oracle.fixture_document()).hex(), "reproduced fixture header")
        selected_ids = sorted({case["id"] for item in variants for case in item["cases"]})
        same(report["case_ids"], selected_ids, "selected fixture IDs")
        same(report["fixture_snapshot"]["path"], "snapshots/selected-fixtures.json", "selected fixture path")
        same(reader.json(report["fixture_snapshot"]), [fixtures[name] for name in selected_ids], "selected fixtures")
        backends = {item["backend"] for item in variants}
        tools = verify_tools(reader, report, backends)
        version_tools = ["g++", "make", "clang", "riscv-gcc"] + (["verilator"] if "rtlsim" in backends else [])
        expected_commands = ["version-" + name.replace("+", "p") for name in version_tools]
        for item in variants:
            expected_commands += [item["id"] + "-" + suffix for suffix in (
                "configure", "cpp-header-reproduce", "verilog-header-reproduce", "runtime", "application-build",
                "effective-header", "kernel-disassembly", *[case["id"] for case in item["cases"]])]
        require(type(report["commands"]) is list, "invalid command inventory")
        same([cmd["id"] for cmd in report["commands"]], expected_commands, "command inventory")
        commands = {cmd["id"]: cmd for cmd in report["commands"]}
        for cmd in commands.values():
            for key, value in {"process_started": True, "cleanup_complete": True, "exit_code": 0, "outcome": "pass"}.items():
                same(cmd[key], value, "command " + key)
            same(cmd["log"], "logs/" + cmd["id"] + ".log", "command log path")
            require(type(cmd["timeout_seconds"]) is int and 0 < cmd["timeout_seconds"] <= 1800, "invalid command timeout")
            require(type(cmd["argv"]) is list and cmd["argv"] and all(type(arg) is str for arg in cmd["argv"]), "invalid argv")
            absolute(cmd["cwd"])
            reader.checked(log_identity(cmd), limit=matrix.BUDGET["max_log_bytes"])
        for name in version_tools:
            same(commands["version-" + name.replace("+", "p")]["argv"], [tools[name]["path"], "--version"], "version command")
        base_environment = commands[expected_commands[0]]["environment"]
        environment_keys = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TZ", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE",
                            "CCACHE_DISABLE", "OBJCACHE", "MAKEFLAGS", "THREADS", "CMAKE_BUILD_PARALLEL_LEVEL"}
        require(type(base_environment) is dict and set(base_environment) == environment_keys
                and all(type(value) is str for value in base_environment.values()), "invalid clean command environment")
        for key, value in matrix.clean_environment({"work": absolute(report["paths"]["work"]), "host_bin": None}, report["budget"]["jobs"]).items():
            if key != "PATH":
                same(base_environment[key], value, "clean environment " + key)
        require(0 < len(base_environment["PATH"]) <= 4096, "invalid command PATH")
        for component in base_environment["PATH"].split(":"):
            absolute(component)
        for name in version_tools:
            cmd = commands["version-" + name.replace("+", "p")]
            same(cmd["cwd"], report["paths"]["work"], "version command directory")
            same(cmd["environment"], base_environment, "version command environment")
        unavailable, derived = {}, []
        witnessed = 0
        for item in variants:
            unavailable[item["id"]] = verify_build(reader, report, item, sources, source_files, commands)
            verify_invocations(report, item, commands, tools, base_environment)
            checked_cases = []
            for case in item["cases"]:
                command_id = item["id"] + "-" + case["id"]
                same(case["command_id"], command_id, "case command binding")
                command = commands[command_id]
                require(command["argv"][-2:] == ["run-" + item["backend"], "OPTS=--case=" + case["id"] + " --iterations=2"]
                        and "--silent" in command["argv"], "case invocation differs")
                same(command["environment"]["CONFIGS"], " ".join(item["configs"]), "case configuration")
                same(command["environment"]["VORTEX_PROFILING"], "11", "case profiling")
                text = reader.text(log_identity(command))
                observations = verify_output(text, fixtures[case["id"]], item["configuration"], witness=item["witness"])
                same(case["observations"], observations, "case arithmetic observations")
                same(case["arithmetic_outcome"], "pass", "case arithmetic outcome")
                witness_outcome = "not_run"
                if item["witness"]:
                    witnessed += 1
                    try:
                        witness = verify_witness(text, require_wait=True)
                    except ValueError as error:
                        witness_outcome = "fail"
                        require("witness" not in case, "failed witness has successful observations")
                        same(case["witness_reason"], str(error), "witness failure reason")
                    else:
                        witness_outcome = "pass"
                        same(case["witness"], witness, "witness observations")
                        require("witness_reason" not in case, "passing witness has failure reason")
                else:
                    require("witness" not in case and "witness_reason" not in case, "unrequested witness observations")
                same(case["witness_outcome"], witness_outcome, "case witness outcome")
                same(case["outcome"], "fail" if witness_outcome == "fail" else "pass", "case outcome")
                checked_cases.append(dict(case, observations=observations))
            same(item["outcome"], "pass" if all(case["outcome"] == "pass" for case in checked_cases) else "fail", "variant outcome")
            derived.append(dict(item, cases=checked_cases))
        count = sum(len(item["cases"]) for item in derived)
        same(report["full_matrix_counts"], manifest["expected_counts"], "frozen full matrix counts")
        for key, expected in {"expected_case_executions": count, "completed_case_executions": count,
                "verified_case_executions": count, "expected_launches": 2 * count, "verified_launches": 2 * count,
                "expected_checked_output_words": 1024 * count, "checked_output_words": 1024 * count,
                "expected_witness_case_executions": witnessed}.items():
            same(report[key], expected, key)
        require(not report["witness_requested"] or witnessed > 0, "requested witness inventory is absent")
        require(not full or not report["witness_requested"] or witnessed == 2, "full matrix requires two witness cases")
        paired = matrix.paired_comparisons(derived)
        same(report["paired_performance"], paired, "paired performance")
        witness_outcome = ("fail" if any(case["witness_outcome"] == "fail" for item in derived for case in item["cases"])
                           else "pass") if report["witness_requested"] else "not_run"
        outcomes = {"arithmetic_outcome": "pass", "witness_outcome": witness_outcome, "parity_outcome": paired["outcome"]}
        for key, value in outcomes.items():
            same(report[key], value, key)
        failures = []
        if paired["outcome"] == "fail":
            failures.append("paired retired-instruction or cycle parity differs")
        if witness_outcome == "fail":
            failures.append("metadata witness ordering or observed wait coverage failed")
        same(report["outcome"], "fail" if failures else "pass", "overall outcome")
        same(report["reason"], "; ".join(failures) + "; arithmetic outcome retained separately" if failures else None, "overall reason")
        require(not full or len(commands) == 113 and len(paired["pairs"]) == 12, "full matrix command/pair inventory differs")
        reader.recheck()
        ready = full and not report["development"] and not report["source_dirty"] and witness_outcome == paired["outcome"] == "pass"
        return {"schema_version": 1, "contract_id": matrix.CONTRACT_ID, "packet_valid": True,
                "report_sha256": digest, "trust_anchor": "external_report_sha256" if report_sha256 else "self_consistency_only",
                "full_matrix": full, "development": report["development"], "recorded_outcome": report["outcome"], **outcomes,
                "qualification_status": "independent_review_required" if ready else "not_established",
                "counts": {"backend_variants": len(derived), "case_executions": count, "launches": 2 * count,
                           "checked_output_words": 1024 * count, "commands": len(commands), "performance_pairs": len(paired["pairs"]),
                           "witness_case_executions": witnessed},
                "unavailable_binary_bodies": unavailable, "verified_file_count": len(reader.inventory()),
                "checkout_inputs_outside_execution_inventory": checkout_only,
                "verifier_sources": hash_artifacts(ROOT, sorted(set(HELPERS + (WITNESS_PARSER,)))) + [
                    {"path": "ci/project/p02_wgmma_packet.py", "sha256": _digest(Path(__file__))[0],
                     "size_bytes": Path(__file__).stat().st_size}],
                "acceptance_claimed": False, "qualifies_P02_A03": False, "phase_complete": False,
                "limitations": ["Hashes establish consistency, not independent authenticity without an external trust anchor.",
                    "Only retained bodies are checked; original tools, dependencies, omitted binaries and source bodies are identity-only evidence.",
                    "Only the unused ci/blackbox.sh may lack an execution-source identity; its checkout identity is recorded without requiring or verifying its body.",
                    "Generated native metadata presence is checked; native hierarchy semantics and disassembly require independent review.",
                    "No GPU execution, binary replay, publication normalization, or automatic acceptance is performed."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("packet", type=Path, help="original runner output directory containing report.json")
    parser.add_argument("--report-sha256", help="independently obtained digest of the original report.json")
    parser.add_argument("--require-witness", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify_packet(args.packet, report_sha256=args.report_sha256, require_witness=args.require_witness)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, RecursionError, OverflowError) as error:
        result = {"packet_valid": False, "reason": str(error), "acceptance_claimed": False,
                  "qualifies_P02_A03": False, "phase_complete": False}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["packet_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
