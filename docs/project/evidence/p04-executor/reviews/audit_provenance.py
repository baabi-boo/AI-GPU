#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independently inspect retained P04 source/build identity, without executing it.

This standard-library audit imports no production validator. It checks the
canonical flag syntax emitted by the frozen Makefiles, not every possible
compiler command. Unarchived executable/tool bytes cannot be rehashed offline.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys


PROFILE_SHA = "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
LIMIT = 16 * 1024 * 1024
VALUES = {
    "VX_CFG_XLEN": "64", "VX_CFG_XLEN_64": "1", "VX_CFG_NUM_CLUSTERS": "1",
    "VX_CFG_NUM_CORES": "1", "VX_CFG_NUM_WARPS": "4", "VX_CFG_NUM_THREADS": "4",
    "VX_CFG_ISSUE_WIDTH": "1", "VX_CFG_NUM_ALU_BLOCKS": "1",
    "VX_CFG_NUM_LSU_BLOCKS": "1", "VX_CFG_NUM_FPU_BLOCKS": "1",
    "VX_CFG_TCU_PE_RATIO": "1", "VX_CFG_TCU_LATENCY": "4", "VX_CFG_TCU_USE_DSP": "0",
}
DISABLED = ["VX_CFG_TCU_" + name for name in (
    "TF32", "FP8", "FP4", "INT8", "INT4", "MX", "MXFP4", "NVFP4",
    "SPARSE", "DSM", "WGMMA")] + ["VX_CFG_EXT_LDST_MATRIX"]
ENABLED = ["VX_CFG_EXT_TCU", "VX_CFG_TCU_FP16", "VX_CFG_LMEM"]
DEPENDENCIES = {
    "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
    "third_party/ramulator/libramulator.so",
    "third_party/ramulator_ext/libramulator-vortex.so",
}
TOOLS = {"make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl",
         "clang", "clang++", "llvm-objcopy", "llvm-objdump", "riscv-gcc", "riscv-gcc-ar",
         "riscv-objdump", "riscv-objcopy", "libc64/lib/libc.a", "libc64/lib/libm.a",
         "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"}
SOURCE_ROOTS = ("sw/common/", "sw/kernel/", "sw/runtime/", "sim/common/", "sim/simx/",
                "sim/rtlsim/", "hw/rtl/", "hw/dpi/", "tests/regression/sgemm_tcu/")
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp", ".S", ".s", ".sv", ".v", ".vh",
                   ".vi", ".mk", ".in", ".ld", ".sh", ".py", ".toml", ".inc"}
GENERATED = {".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "hw/VX_config.vh", "hw/VX_types.vh", "sim/rtlsim/verilator.vlt"}
ESSENTIAL = {
    "sw/runtime/ai/runtime.cpp", "sw/runtime/ai/runtime.h",
    "sw/runtime/ai/mlp_runtime.cpp", "sw/runtime/ai/mlp_runtime.h",
    "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_host.h",
    "sw/runtime/common/queue.cpp", "sw/runtime/common/event.cpp",
    "sw/kernel/ai/matmul.cpp", "tests/regression/ai_mlp/Makefile",
    "tests/regression/ai_mlp/main.cpp", "tests/regression/ai_mlp/records.h",
    "tests/regression/ai_mlp/p04_fixtures.h", "ci/project/p04_execute.py",
    "ci/project/p04_execution_records.py", "ci/project/p04_fixture_adapter.py",
    "ci/project/fixtures/p04_tiny_mlp_v1.json", "profiles/p02-tfr.json",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(data):
    def constant(value):
        raise ValueError("nonfinite JSON: " + value)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def relative(name):
    require(type(name) is str and name and "\\" not in name
            and not name.startswith("/") and all(part not in ("", ".", "..") for part in name.split("/")),
            "noncanonical packet path")
    return PurePosixPath(name)


def read(root, name):
    path = root.joinpath(*relative(name).parts)
    require(path.resolve() == path and path.is_file(), "missing or symlinked packet file: " + name)
    require(path.stat().st_size <= LIMIT, "oversized packet file: " + name)
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT, "packet file grew beyond bound")
    return data


def identity(item):
    relative(item["path"])
    require(type(item["size_bytes"]) is int and 0 <= item["size_bytes"] <= 2**64 - 1,
            "invalid artifact byte count")
    require(type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
            "invalid artifact digest")


def inventory(items):
    require(type(items) is list and len(items) <= 20000, "invalid inventory")
    result = {}
    for item in items:
        identity(item)
        require(item["path"] not in result, "duplicate inventory path")
        result[item["path"]] = item
    return result


def checked(root, item):
    identity(item)
    data = read(root, item["path"])
    require((digest(data), len(data)) == (item["sha256"], item["size_bytes"]),
            "retained identity mismatch: " + item["path"])
    return data


def configuration(defines, *, fmt=None, selectors=True, raw=True):
    for key, value in VALUES.items():
        require(defines.get(key) == value, "configuration differs: " + key)
    require(not any(key.startswith("VX_CFG_XLEN_") and key != "VX_CFG_XLEN_64" for key in defines),
            "conflicting XLEN selector")
    for prefix, native in (("VX_CFG_TCU_TYPE", "TFR"), ("VX_CFG_FPU_TYPE", "STD")):
        if raw:
            require(defines.get(prefix) == native, "missing native arithmetic enum")
        if selectors:
            require(defines.get(prefix + "_" + native) == "1", "missing native arithmetic selector")
        require(not any(key.startswith(prefix + "_") and key != prefix + "_" + native
                        for key in defines), "alternative/DPI arithmetic selector")
    for prefix in ENABLED:
        require(defines.get(prefix + "_ENABLE") == "1" and prefix + "_DISABLE" not in defines
                and defines.get(prefix + "_ENABLED", "1") == "1", "required feature disabled")
    for prefix in DISABLED:
        require(prefix + "_ENABLE" not in defines and defines.get(prefix + "_ENABLED", "0") == "0",
                "excluded feature enabled")
        if raw:
            require(defines.get(prefix + "_DISABLE") == "1", "excluded feature lacks disable")
    require(not any(key.startswith(("VX_CFG_TCU_FEDP2K", "WGMMA_", "DBG_TRACE_"))
                    or key in {"DEBUG", "PERF_ENABLE", "VCD_OUTPUT", "SAIF_OUTPUT", "XRTSIM", "__FAST_MATH__"}
                    for key in defines), "unsupported arithmetic/tracing override")
    require(defines.get("__FINITE_MATH_ONLY__", "0") == "0", "finite-only arithmetic")
    if fmt is not None:
        require(all(defines.get(k) == v for k, v in
                    (("ITYPE", fmt), ("OTYPE", "fp32"), ("KUNROLL", "1"), ("NDEBUG", "1"))),
                "kernel/application arithmetic differs")


def include_flags(role, source, build, backend):
    """Frozen Makefile search roots, in their original lookup order.

    These are the CONFIGS-independent lists in sw/runtime/{simx,rtlsim}/Makefile,
    sim/{simx,rtlsim}/Makefile, tests/regression/common.mk and ai_mlp/Makefile.
    Arbitrary absolute paths are not evidence of bound header inputs.
    """
    require(backend in ("simx", "rtlsim"), "unknown compiler backend")
    for path in (source, build):
        require(type(path) is str and re.fullmatch(r"/[A-Za-z0-9_./+-]+", path)
                and all(part not in ("", ".", "..") for part in path.split("/")[1:]),
                "noncanonical source/build root")
    require(source != build and not source.startswith(build + "/")
            and not build.startswith(source + "/"), "source/build roots overlap")
    dependencies = [source + "/third_party/" + name for name in
                    ("softfloat/source/include", "ramulator/ext/spdlog/include",
                     "ramulator/ext/yaml-cpp/include", "ramulator/src")]
    if role == "runtime":
        roots = [source + "/sw/runtime/include"]
        if backend == "simx":
            roots += ["../common"]
        roots += [build + "/sw", build + "/hw", source + "/sim/" + backend,
                  source + "/sim/common", source + "/sw/common", source + "/sw/runtime/common"]
    elif role == "backend_cpp" and backend == "simx":
        roots = [source + "/sim/simx" + suffix for suffix in
                 ("", "/dxa", "/tex", "/om", "/raster", "/rtu", "/kmu", "/mem", "/dtm")]
        roots += [source + "/sw/common", source + "/sim/common", build + "/sw",
                  build + "/hw", source + "/third_party", *dependencies, source + "/sim/simx/tcu"]
    elif role == "backend_cpp":
        roots = [build + "/sw", build + "/hw", source + "/sim/common",
                 source + "/sw/common", *dependencies]
    elif role == "verilator":
        require(backend == "rtlsim", "Verilator role in non-RTL variant")
        roots = [build + "/sw", build + "/hw", source + "/sim/rtlsim",
                 source + "/hw/rtl", source + "/hw/dpi"]
        roots += [source + "/hw/rtl/" + name for name in
                  ("libs", "interfaces", "core", "mem", "vm", "cache", "fpu", "tcu", "tcu/tfr")]
    elif role == "kernel":
        roots = [source + "/sw/kernel/include", build + "/sw", build + "/hw", source + "/sw/common"]
    elif role == "host":
        roots = [source + "/sw/runtime/ai", source + "/sw/runtime/include",
                 source + "/sw/kernel/include", build + "/sw", build + "/hw", source + "/sw/common"]
    else:
        raise ValueError("unknown compiler role")
    return ["-I" + path for path in roots]


def compiler_record(line, role, fmt, reported, source, jobs, *, backend, build, selectors=True):
    require(not re.search(r"[;&|<>$`*?\[\]{}()~\r\x00]", line), "noncanonical stamp syntax")
    words = shlex.split(line)
    require(selectors == (backend != "rtlsim" or role != "backend_cpp"),
            "arithmetic selector requirement differs from compiler role")
    includes = include_flags(role, source, build, backend)
    require([word for word in words if word.startswith("-I")] == includes,
            "compiler include roots/order differs from frozen Makefiles")
    require(not any(word.startswith(("-Wp,", "-U", "@", "-Xpreprocessor", "--define", "--undefine"))
                    or word in {"-D", "-Ofast", "-ffast-math", "-ffinite-math-only", "-CFLAGS"}
                    for word in words), "opaque or noncanonical arithmetic flag transport")
    rtl_options = {"--language": "1800-2012", "--replication-limit": "65536",
                   "--x-initial": "unique", "--x-assign": "unique", "--cc": "rtlsim_shim",
                   "--top-module": "rtlsim_shim", "-j": str(jobs)}
    packages = {source + "/hw/rtl/" + name for name in
                ("VX_gpu_pkg.sv", "fpu/VX_fpu_pkg.sv", "tcu/VX_tcu_pkg.sv", "VX_trace_pkg.sv")}
    standalone = {"-Wall", "-Wextra", "-Werror", "-Wfatal-errors", "-Wpedantic", "-pedantic",
                  "-fPIC", "-fdata-sections", "-ffunction-sections", "-fno-exceptions", "-fno-rtti",
                  "-fno-tree-loop-distribute-patterns", "-nostartfiles", "-nostdlib", "-pthread"}
    pending = iter(words)
    for word in pending:
        if word.startswith("-D") or word in includes or word in standalone or re.fullmatch(
                r"-O[0-3sg]|-std=c\+\+17|-Wno-[A-Za-z0-9_-]+", word):
            continue
        if role == "kernel" and word in {"-march=rv64imafd", "-mabi=lp64d", "-mcmodel=medany"}:
            continue
        if role == "backend_cpp" and backend == "simx":
            if word in {"-MMD", "-MP"}:
                continue
            if word == "-MF":
                require(next(pending, None) == build + "/sw/runtime/simx_config.stamp",
                        "noncanonical SimX dependency target")
                continue
        if role == "verilator":
            if word in rtl_options:
                require(next(pending, None) == rtl_options[word], "noncanonical processor RTL option")
                continue
            if word == "-MAKEFLAGS":
                require(next(pending, None) in ("OPT_FAST=-O2", "OPT_GLOBAL=-O2"), "opaque nested make flags")
                continue
            if word in packages | {"--exe", "--assert", "verilator.vlt"}:
                continue
        raise ValueError("unrecognized canonical compiler argument: " + word)
    flags = [word for word in words if word.startswith("-D")]
    defines = {}
    for flag in flags:
        name, equal, value = flag[2:].partition("=")
        value = value if equal else "1"
        require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name), "invalid macro name")
        require(name not in defines or defines[name] == value, "conflicting macro values")
        defines[name] = value
    configuration(defines, fmt=fmt, selectors=selectors)
    # The RTL C++ shim need not select arithmetic: the Verilator record does.
    expected_config = {k: v for k, v in defines.items()
                       if k.startswith("VX_CFG_") or k in ("ITYPE", "OTYPE", "KUNROLL")}
    require(reported == {"role": role, "sha256": digest(line.encode()),
                         "macro_flags": flags, "configuration": expected_config},
            "reported compiler record differs from retained stamp")
    if role == "kernel":
        require(words.count("-march=rv64imafd") == words.count("-mabi=lp64d") == 1,
                "kernel ISA/ABI differs")
    if role == "verilator":
        for key, value in (("--language", "1800-2012"), ("--top-module", "rtlsim_shim"),
                           ("--cc", "rtlsim_shim"), ("-j", str(jobs))):
            require(words.count(key) == 1 and words[words.index(key) + 1] == value,
                    "processor RTL compilation differs")
        for name in ("VX_gpu_pkg.sv", "fpu/VX_fpu_pkg.sv", "tcu/VX_tcu_pkg.sv", "VX_trace_pkg.sv"):
            require(words.count(source + "/hw/rtl/" + name) == 1, "missing native RTL package")


class GitSource:
    def __init__(self, root):
        self.root, self.blobs = root, {}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE, timeout=30)

    def blob(self, revision, path):
        key = revision, path
        if key not in self.blobs:
            data = self.git("show", revision + ":" + path)
            require(len(data) <= LIMIT, "Git source blob exceeds audit bound")
            self.blobs[key] = data
        return self.blobs[key]


def audit_packet(packet, git):
    root = packet.resolve()
    if root.name == "report.json":
        root = root.parent
    report_bytes = read(root, "report.json")
    report = decode(report_bytes)
    require(report["contract_id"] == "p04-managed-model-execution-v1"
            and type(report["schema_version"]) is int and report["schema_version"] == 1,
            "not a P04 execution packet")
    require(report["state"] == "finished" and report["outcome"] == "pass" and report["reason"] is None
            and report["development"] is False and report["acceptance_claimed"] is False
            and report["phase_complete"] is False and report["source_stable"] is True,
            "unfinished, failed, development or self-accepted packet")
    before = decode(checked(root, report["source_before"]))
    after = decode(checked(root, report["source_after"]))
    require(before == after, "source snapshots changed")
    checkout = before["checkout"]
    require(checkout["dirty"] is False and checkout["outcome"] == "pass"
            and not checkout["blockers"] and not checkout["changed_paths"] and not checkout["untracked_paths"],
            "source was not clean")
    revision = checkout["revision"]
    require(re.fullmatch(r"[0-9a-f]{40}", revision), "invalid source revision")
    require(git.git("rev-parse", revision + "^{tree}").decode().strip() == checkout["tree"],
            "recorded tree differs from Git commit")
    submodules = {}
    for entry in checkout["submodules"]["entries"]:
        require(entry["status"] == "initialized", "uninitialized/mismatched recursive source")
        require(entry["path"] not in submodules, "duplicate recursive source identity")
        submodules[entry["path"]] = entry["revision"]
    require(not checkout["submodules"]["errors"], "recursive source identity errors")
    tracked, gitlinks = {}, {}
    for entry in git.git("ls-tree", "-r", "-z", revision).split(b"\0"):
        if entry:
            metadata, name = entry.split(b"\t", 1)
            mode, kind, object_id = metadata.decode().split()
            (gitlinks if kind == "commit" else tracked)[name.decode()] = object_id
    require(all(submodules.get(path) == sha for path, sha in gitlinks.items()),
            "top-level submodule pin differs from committed gitlink")
    files = inventory(before["files"])
    require(ESSENTIAL <= files.keys(), "source inventory omits a model/observer input")
    expected_sources = {name for name in tracked if name.startswith(SOURCE_ROOTS)
                        and (Path(name).suffix in SOURCE_SUFFIXES or Path(name).name == "Makefile")}
    require(expected_sources <= files.keys(), "source inventory omits committed runtime/processor inputs")
    verified_source, external_source = 0, 0
    for name, item in files.items():
        if name in tracked:
            data = git.blob(revision, name)
            require((digest(data), len(data)) == (item["sha256"], item["size_bytes"]),
                    "source snapshot differs from Git object: " + name)
            verified_source += 1
        else:
            require(any(name.startswith(path + "/") for path in gitlinks),
                    "source inventory contains an input outside the commit/submodules")
            external_source += 1
    retained = inventory(report["retained_sources"])
    retained_names = set()
    for name, item in retained.items():
        require(name.startswith("artifacts/source/"), "unexpected retained-source prefix")
        original = name[len("artifacts/source/"):]
        data = checked(root, item)
        require(data == git.blob(revision, original), "retained source differs from exact commit: " + original)
        if original in files:
            require((digest(data), len(data)) == (files[original]["sha256"], files[original]["size_bytes"]),
                    "retained source differs from execution snapshot")
        retained_names.add(original)
    require(ESSENTIAL <= retained_names, "essential source bodies were not retained")
    for helper in report["loaded_helpers"]:
        identity(helper)
        require(helper == files[helper["path"]], "loaded helper differs from snapshot")
    require(digest(git.blob(revision, "profiles/p02-tfr.json")) == PROFILE_SHA, "frozen profile changed")
    require(digest(git.blob(revision, "ci/project/fixtures/p04_tiny_mlp_v1.json")) == report["fixture_sha256"],
            "fixture differs from exact source")
    checked(root, report["fixture_snapshot"])
    tools_before = decode(checked(root, report["tools_before"]))
    require(tools_before == decode(checked(root, report["tools_after"])), "recorded tools changed")
    expected_tools = TOOLS | ({"verilator", "verilator_bin"}
                             if any(v["backend"] == "rtlsim" for v in report["variants"]) else set())
    require(set(tools_before) == expected_tools, "required tool/runtime archive inventory differs")
    for item in tools_before.values():
        require(type(item["size_bytes"]) is int and item["size_bytes"] > 0
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "invalid identified tool")
    deps = inventory(report["dependencies_before"])
    require(set(deps) == DEPENDENCIES, "required dependency identities differ")
    commands = {}
    for command in report["commands"]:
        require(command["id"] not in commands, "duplicate command")
        require(command["outcome"] == "pass" and type(command["exit_code"]) is int
                and command["exit_code"] == 0 and command["cleanup_complete"] is True,
                "command did not pass and drain")
        checked(root, {"path": command["log"], "sha256": command["log_sha256"],
                       "size_bytes": command["log_size_bytes"]})
        commands[command["id"]] = command
    variants = []
    for variant in report["variants"]:
        backend, fmt = variant["backend"], variant["format"]
        require(backend in ("simx", "rtlsim") and fmt in ("fp16", "bf16")
                and variant["id"] == backend + "-" + fmt and variant["outcome"] == "pass",
                "invalid variant")
        binding = decode(checked(root, variant["binding"]))
        require(digest(canonical(binding)) == variant["qualification_id"], "qualification digest differs")
        require(binding["source"] == checkout and binding["backend"] == backend and binding["format"] == fmt
                and binding["profile_sha256"] == PROFILE_SHA
                and binding["fixture_sha256"] == report["fixture_sha256"]
                and binding["model_id"] == "p04-tiny-mlp-v1"
                and binding["dependencies"] == report["dependencies_before"]
                and binding["compiler_records"] == variant["compiler_records"]
                and binding["artifacts"] == variant["artifacts_before"] == variant["artifacts_after"],
                "variant binding does not match observed inputs")
        artifacts = inventory(binding["artifacts"])
        app = "tests/regression/ai_mlp"
        expected = GENERATED | {app + "/" + n for n in ("Makefile", "config.stamp", "ai_mlp", "kernel.elf", "kernel.vxbin")}
        expected |= {"sw/kernel/libvortex2.a", "sw/runtime/libvortex.so",
                     "sw/runtime/libvortex-" + backend + ".so", "sw/runtime/lib" + backend + ".so",
                     "sw/runtime/" + backend + "_rt_config.stamp", "sw/runtime/" + backend + "_config.stamp"}
        require(set(artifacts) == expected, "native artifact inventory differs")
        prefix = "artifacts/" + variant["id"] + "/"
        for name, item in artifacts.items():
            if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or Path(name).name == "Makefile":
                checked(root, dict(item, path=prefix + name))
        runtime = read(root, prefix + "sw/runtime/" + backend + "_rt_config.stamp").decode().splitlines()
        native = read(root, prefix + "sw/runtime/" + backend + "_config.stamp").decode().splitlines()
        application = read(root, prefix + app + "/config.stamp").decode().splitlines()
        require(len(runtime) == 1 and len(native) == (2 if backend == "rtlsim" else 1)
                and len(application) == 3, "incorrect independent compiler-role inventory")
        roles = ["runtime"] + (["verilator", "backend_cpp"] if backend == "rtlsim" else ["backend_cpp"]) + ["kernel", "host"]
        require(len(variant["compiler_records"]) == len(roles), "compiler-role count differs")
        build = report["paths"]["work"] + "/" + variant["id"]
        require(shlex.split(application[2]) == ["-L" + build + "/sw/runtime", "-lvortex"], "linker uses another runtime")
        for line, role, recorded in zip(runtime + native + application[:2], roles, variant["compiler_records"]):
            compiler_record(line, role, fmt, recorded, report["paths"]["source"], report["budget"]["jobs"],
                            selectors=not (backend == "rtlsim" and role == "backend_cpp"),
                            backend=backend, build=build)
        for suffix, field in (("-header", "header_macros"), ("-effective-header", "backend_header_macros")):
            text = read(root, commands[variant["id"] + suffix]["log"]).decode()
            macros = {}
            for line in text.splitlines():
                match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?", line)
                if match:
                    require(match[1] not in macros, "duplicate effective macro")
                    macros[match[1]] = match[2] or "1"
            configuration(macros, raw=False)
            require({k: v for k, v in macros.items() if k.startswith("VX_CFG_")} == variant[field],
                    "effective-header summary differs from raw compiler observation")
        variants.append((backend, fmt))
    preparation_checked = False
    if (root.parent / "preparation.json").exists():
        preparation = decode(read(root.parent, "preparation.json"))
        require(preparation["outcome"] == "pass" and preparation["expected_revision"] == revision
                and preparation["source"] == checkout and preparation["tool_identities"] == tools_before
                and preparation["dependency_identities"] == report["dependencies_before"],
                "hosted preparation differs from execution inputs")
        quarantine = preparation.get("cache_quarantine")
        if quarantine is not None:
            require(quarantine["state"] in ("not_needed", "relocated")
                    and not quarantine["status_after"]
                    and quarantine["revision_before"] == quarantine["revision_after"]
                    == quarantine["expected_revision"] == submodules["third_party/cocogfx"],
                    "unused-cache quarantine did not retain a clean pinned submodule")
            for item in quarantine["files"]:
                identity(item)
                require(item["moved"] is True and item["sha256"] == item["after_sha256"]
                        and item["size_bytes"] == item["after_size_bytes"]
                        and item["path"].startswith("third_party/cocogfx/"),
                        "quarantined cache product was not preserved")
        preparation_checked = True
    return {"packet": str(root), "report_sha256": digest(report_bytes), "revision": revision,
            "tree": checkout["tree"], "fixture_sha256": report["fixture_sha256"],
            "profile_sha256": PROFILE_SHA, "variants": variants, "commands_verified": len(commands),
            "source_inventory_entries": len(files), "git_source_bodies_verified": verified_source,
            "external_submodule_file_identities_recorded": external_source,
            "retained_source_bodies_verified": len(retained_names), "preparation_checked": preparation_checked,
            "dependencies": report["dependencies_before"], "tool_names": sorted(tools_before)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", action="append", type=Path, required=True)
    parser.add_argument("--source-dir", "--git-repo", dest="source", type=Path, required=True)
    parser.add_argument("--selected-scope", "--allow-partial", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"schema_version": 1, "audit": "independent-p04-source-provenance-v1",
              "outcome": "fail", "acceptance_claimed": False, "packets": []}
    try:
        git = GitSource(args.source.resolve())
        result["packets"] = [audit_packet(path, git) for path in args.packet]
        items = result["packets"]
        require(len({(x["revision"], x["tree"], x["fixture_sha256"], x["profile_sha256"])
                     for x in items}) == 1, "mixed source/profile/fixture matrix")
        require(all(x["dependencies"] == items[0]["dependencies"] for x in items), "mixed dependency bytes")
        variants = [tuple(v) for item in items for v in item["variants"]]
        require(len(variants) == len(set(variants)), "duplicate variant packets")
        required = {(b, f) for b in ("simx", "rtlsim") for f in ("fp16", "bf16")}
        require(set(variants) <= required and variants, "unknown or empty variant inventory")
        require(args.selected_scope or set(variants) == required, "full four-variant provenance is missing")
        result.update(outcome="pass", full_matrix=set(variants) == required)
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as error:
        result["reason"] = str(error)
    result["limitations"] = [
        "This is retained provenance consistency, not an independent native rerun or phase acceptance.",
        "Main-repository source bodies are compared with Git blobs; external submodule body hashes are recorded, not rehydrated by this offline audit.",
        "Tool/native executable bytes and dependency binaries are not archived here and cannot be independently rehashed offline.",
        "Source pins, compiler flags and byte bindings identify trusted execution inputs; they do not authenticate arbitrary hardware.",
        "Native processor RTL TFR/STD arithmetic retains integer DPI plumbing; full AFU, vendor emulation and physical hardware are outside scope.",
    ]
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x") as stream:
            stream.write(text)
    print(text, end="")
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
