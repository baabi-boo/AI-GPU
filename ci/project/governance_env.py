#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare and check a fresh, offline interpreter environment for governance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig


ROOT = Path(__file__).resolve().parents[2]
HOST_TOOLS = ("python", "python3", "cmake", "gcc", "g++", "ar", "ranlib",
              "make", "git", "tclsh", "readelf")
MAX_OUTPUT_BYTES = 1024 * 1024
PYTHON_PROBE = """import importlib.util, json, platform, site, sys, sysconfig
print(json.dumps({
    'executable': sys.executable, 'base_executable': sys._base_executable,
    'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
    'version': sys.version, 'version_info': list(sys.version_info[:3]),
    'implementation': sys.implementation.name, 'platform': sys.platform,
    'machine': platform.machine(), 'byteorder': sys.byteorder,
    'libc': list(platform.libc_ver()),
    'gil_enabled': not bool(sysconfig.get_config_var('Py_GIL_DISABLED')),
    'user_site_enabled': site.ENABLE_USER_SITE,
    'pip_present': importlib.util.find_spec('pip') is not None,
}))
"""
CXX_PROBE = """#include <iostream>
#include <limits>
#include <optional>
#include <thread>
#include <utility>
extern "C" int governance_value(void);
int main(int argc, char**) {
    if (argc > 1) {
        volatile int maximum = std::numeric_limits<int>::max();
        return maximum + 1;
    }
    auto [left, right] = std::pair{40, 2};
    std::optional<int> value;
    std::thread worker([&] { value = left + right; });
    worker.join();
    if (value != governance_value()) return 2;
    std::cout << "cxx17-ubsan-ok\\n";
    return 0;
}
"""
CMAKE_PROBE = """cmake_minimum_required(VERSION 3.14)
project(governance_probe LANGUAGES C CXX)
find_package(Threads REQUIRED)
add_library(probe_value STATIC value.c)
add_executable(probe main.cpp)
target_compile_features(probe PRIVATE cxx_std_17)
target_compile_options(probe PRIVATE -fsanitize=undefined -fno-sanitize-recover=undefined)
target_link_options(probe PRIVATE -fsanitize=undefined -fno-sanitize-recover=undefined)
target_link_libraries(probe PRIVATE probe_value Threads::Threads)
"""


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def identity(path):
    path = Path(os.path.abspath(path))
    target = path.resolve(strict=True)
    information = target.stat()
    require(stat.S_ISREG(information.st_mode) and os.access(path, os.X_OK),
            "tool is not a regular executable: " + str(path))
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    before = tuple(getattr(information, name) for name in fields)
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        require(tuple(getattr(os.fstat(stream.fileno()), name) for name in fields) == before,
                "tool changed while reading: " + str(path))
    require(path.resolve(strict=True) == target
            and tuple(getattr(target.stat(), name) for name in fields) == before,
            "tool changed while reading: " + str(path))
    return {"path": str(path), "resolved_path": str(target),
            "sha256": digest.hexdigest(), "size_bytes": information.st_size}


def native_cmake(requested):
    requested_identity = identity(requested)
    target = Path(requested_identity["resolved_path"])
    with target.open("rb") as stream:
        native = stream.read(4) == b"\x7fELF"
    selection = {"requested": requested_identity, "resolution": "native"}
    if not native:
        try:
            distribution = importlib.metadata.distribution("cmake")
        except importlib.metadata.PackageNotFoundError as error:
            raise ValueError("CMake is a launcher; pass --cmake the native executable") from error
        files = distribution.files or ()
        launchers = [distribution.locate_file(item).resolve()
                     for item in files if str(item).endswith("/bin/cmake")]
        require(target in launchers and any(
            item.group == "console_scripts" and item.name == "cmake"
            and item.value == "cmake:cmake" for item in distribution.entry_points),
            "selected CMake launcher is not bound to the installed cmake package; "
            "pass --cmake the native executable")
        candidates = [distribution.locate_file(item).resolve()
                      for item in files if str(item) == "cmake/data/bin/cmake"]
        require(len(candidates) == 1, "cmake package does not identify one native executable")
        target = candidates[0]
        selection.update(resolution="python-package", package_version=distribution.version)
    selection["native"] = identity(target)
    with target.open("rb") as stream:
        require(stream.read(4) == b"\x7fELF", "selected native CMake is not an ELF executable")
    return target, selection


def clean_environment(interpreter, workspace):
    # Dependency fixtures deliberately use this restricted lookup order.
    entries = (str(Path(interpreter).parent), "/usr/bin", "/bin")
    return {"PATH": os.pathsep.join(dict.fromkeys(entries)),
            "HOME": str(workspace / "home"), "TMPDIR": str(workspace / "tmp"),
            "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}


def fresh_output(raw):
    require(os.path.isabs(raw) and re.fullmatch(r"/[A-Za-z0-9_./+()\-]+", raw),
            "output directory must be an absolute safe literal path")
    require(not any(part in (".", "..") for part in raw.split("/")),
            "output directory must not contain dot traversal")
    output = Path(raw)
    require(output.resolve() == output and all(not item.is_symlink()
            for item in (output, *output.parents)), "output path must not traverse a symlink")
    require(not output.is_relative_to(ROOT) and not ROOT.is_relative_to(output),
            "output directory must be outside the source checkout")
    require(output.parent.is_dir(), "output parent directory must already exist")
    require(not os.path.lexists(output), "output directory must be fresh")
    output.mkdir(mode=0o700)
    return output


def command(report, name, argv, environment, cwd, *, input_text=None, check=True, timeout=30):
    row = {"name": name, "argv": [str(item) for item in argv], "cwd": str(cwd),
           "environment": environment, "returncode": None, "timed_out": False}
    report["commands"].append(row)
    with subprocess.Popen(row["argv"], cwd=cwd, env=environment,
                          stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(
                input_text.encode("utf-8") if input_text is not None else None, timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            row["timed_out"] = True
        row.update(returncode=process.returncode,
                   stdout=stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
                   stderr=stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"))
    require(not row["timed_out"], name + " was interrupted or exceeded its time bound")
    require(len(stdout) <= MAX_OUTPUT_BYTES and len(stderr) <= MAX_OUTPUT_BYTES,
            name + " exceeded its output bound")
    require(not check or row["returncode"] == 0,
            name + " failed with exit " + str(row["returncode"]) + ": " + row["stderr"].strip())
    return row


def write_report(output, report):
    temporary = output / "environment.json.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    temporary.replace(output / "environment.json")


def platform_checks():
    require(sys.platform == "linux" and sys.implementation.name == "cpython"
            and sys.version_info[:2] == (3, 12)
            and not sysconfig.get_config_var("Py_GIL_DISABLED"),
            "governance requires GIL-enabled Linux CPython 3.12")
    require(platform.machine().lower() in ("x86_64", "amd64")
            and sys.byteorder == "little" and platform.libc_ver()[0] == "glibc",
            "complete governance requires a little-endian x86-64 glibc host")
    require(hasattr(os, "mkfifo") and hasattr(os, "O_NOFOLLOW")
            and Path("/proc/self/stat").is_file() and Path("/dev/full").exists(),
            "governance requires POSIX FIFO/no-follow, Linux /proc, and /dev/full")


def native_probes(report, output, environment):
    source, build = output / "probe-source", output / "probe-build"
    source.mkdir()
    (source / "value.c").write_text("int governance_value(void) { return 42; }\n")
    (source / "main.cpp").write_text(CXX_PROBE)
    (source / "CMakeLists.txt").write_text(CMAKE_PROBE)
    tools = report["tools"]
    preprocessor = command(report, "c-preprocessor", [tools["gcc"]["path"], "-E", "-dM",
        "-x", "c", "-DGOVERNANCE_ENV_PROBE=37", "-"], environment, output, input_text="")
    require("#define GOVERNANCE_ENV_PROBE 37" in preprocessor["stdout"].splitlines(),
            "C preprocessor did not preserve the probe definition")
    command(report, "elf32-link", [tools["gcc"]["path"], "-shared", "-fPIC", "-m32",
        "-nostdlib", source / "value.c", "-o", output / "probe32.so"], environment, output)
    require((output / "probe32.so").read_bytes()[:6] == b"\x7fELF\x01\x01",
            "compiler/linker did not produce the required little-endian ELF32 object")
    command(report, "elf32-readelf", [tools["readelf"]["path"], "-h", output / "probe32.so"],
            environment, output)
    command(report, "cmake-configure", [tools["cmake"]["path"], "-S", source, "-B", build,
        "-G", "Unix Makefiles", "-DCMAKE_C_COMPILER=" + tools["gcc"]["path"],
        "-DCMAKE_CXX_COMPILER=" + tools["g++"]["path"], "-DCMAKE_AR=" + tools["ar"]["path"],
        "-DCMAKE_RANLIB=" + tools["ranlib"]["path"],
        "-DCMAKE_MAKE_PROGRAM=" + tools["make"]["path"]], environment, output, timeout=60)
    command(report, "cmake-build", [tools["cmake"]["path"], "--build", build, "--parallel", "2"],
            environment, output, timeout=60)
    successful = command(report, "cxx17-ubsan-run", [build / "probe"], environment, output)
    require(successful["stdout"] == "cxx17-ubsan-ok\n" and not successful["stderr"],
            "C++17/thread/UBSan probe produced an unexpected result")
    rejected = command(report, "ubsan-rejection", [build / "probe", "overflow"],
                       environment, output, check=False)
    require(rejected["returncode"] > 0
            and "runtime error: signed integer overflow" in rejected["stderr"],
            "UBSan did not reject the intentional signed overflow")
    os.mkfifo(output / "probe.fifo", 0o600)
    require(stat.S_ISFIFO((output / "probe.fifo").stat().st_mode), "FIFO creation failed")
    (output / "probe-link").symlink_to(source / "value.c")
    try:
        descriptor = os.open(output / "probe-link", os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        require(error.errno == errno.ELOOP, "O_NOFOLLOW failed unexpectedly")
    else:
        os.close(descriptor)
        raise ValueError("O_NOFOLLOW followed the probe symlink")
    report["probes"] = {"c_preprocessor": True, "elf32_link": True, "cmake_build": True,
                        "cxx17_threads": True, "ubsan_runtime": True,
                        "ubsan_rejects_overflow": True, "fifo": True, "nofollow": True}


def prepare_environment(output_dir, cmake):
    output = fresh_output(output_dir)
    interpreter = output / "venv/bin/python"
    report = {"schema_version": 1, "status": "preparing", "source_root": str(ROOT),
              "output_dir": str(output), "interpreter": str(interpreter),
              "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
              "environment": clean_environment(interpreter, output), "tools": {},
              "probes": {}, "commands": [], "error": None}
    write_report(output, report)
    try:
        platform_checks()
        report["bootstrap_python"] = identity(sys.executable)
        native, report["cmake_selection"] = native_cmake(cmake)
        for name in ("home", "tmp"):
            (output / name).mkdir(mode=0o700)
        bootstrap = clean_environment(sys.executable, output)
        command(report, "create-venv", [sys.executable, "-I", "-m", "venv", "--without-pip",
                                      output / "venv"], bootstrap, output)
        (interpreter.parent / "cmake").symlink_to(native)
        environment = report["environment"]
        python = command(report, "venv-python", [interpreter, "-c", PYTHON_PROBE],
                         environment, output)
        report["python"] = information = json.loads(python["stdout"])
        require(information["executable"] == str(interpreter)
                and information["prefix"] == str(output / "venv")
                and information["prefix"] != information["base_prefix"]
                and information["version_info"] == list(sys.version_info[:3])
                and information["implementation"] == "cpython" and information["gil_enabled"]
                and not information["user_site_enabled"] and not information["pip_present"],
                "created interpreter is not an isolated, matching CPython 3.12 venv without pip")
        for name in HOST_TOOLS:
            selected = shutil.which(name, path=environment["PATH"])
            require(selected is not None, "required governance tool is absent from clean PATH: " + name)
            tool = report["tools"][name] = identity(selected)
            version = command(report, "version-" + name,
                [selected] if name == "tclsh" else [selected, "--version"], environment, output,
                input_text="puts [info patchlevel]\n" if name == "tclsh" else None)
            tool["version"] = (version["stdout"] + version["stderr"]).strip()
            require(tool["version"], "tool returned an empty version: " + name)
        require(report["tools"]["python"]["path"] == str(interpreter)
                and report["tools"]["python3"]["resolved_path"]
                == report["tools"]["python"]["resolved_path"],
                "clean PATH does not select the venv Python aliases")
        cmake_tool = report["tools"]["cmake"]
        require(cmake_tool["resolved_path"] == str(native), "clean PATH did not select native CMake")
        version_match = re.match(r"cmake version (\d+)\.(\d+)\.(\d+)(?:$|\s|[-.])", cmake_tool["version"])
        require(version_match is not None, "CMake returned an unrecognized version")
        cmake_version = tuple(map(int, version_match.groups()))
        require((3, 21, 0) <= cmake_version < (3, 26, 0),
                "governance requires CMake 3.21 through 3.25 for linker launchers and recorded command grammar")
        native_probes(report, output, environment)
        identities = [report["bootstrap_python"], *report["tools"].values(),
                      report["cmake_selection"]["requested"], report["cmake_selection"]["native"]]
        for before in identities:
            require(identity(before["path"]) == {key: before[key] for key in
                    ("path", "resolved_path", "sha256", "size_bytes")},
                    "selected tool changed during preparation: " + before["path"])
        report["status"] = "ready"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_report(output, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="fresh absolute directory outside the checkout")
    parser.add_argument("--cmake", required=True, help="existing CMake executable; native binary preferred")
    args = parser.parse_args(argv)
    try:
        report = prepare_environment(args.output_dir, args.cmake)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("governance environment failed: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps({"interpreter": report["interpreter"],
                      "environment_receipt": str(Path(args.output_dir) / "environment.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
