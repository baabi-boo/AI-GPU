# SPDX-License-Identifier: Apache-2.0
"""Generate host-only preflight records from the configured production Makefiles."""

import os
from pathlib import Path
import re
import shlex
import shutil
import sys

from p02_matrix_records import DISABLED
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
APP = "tests/regression/ai_counter_preflight"
ROLES = ((0, 0, "runtime"), (1, 0, "backend_cpp"), (2, 0, "kernel"), (2, 1, "host"))


def hardware_macros(text):
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?", line)
        if match and (match[1].startswith("VX_CFG_") or match[1] in ("PERF_ENABLE", "SIMX_CHECKED_COUNTERS")):
            if match[1] in result:
                raise AssertionError("Host preprocessor repeated a hardware macro")
            result[match[1]] = match[2] or "1"
    return result


def generate(directory):
    directory = Path(directory)
    compiler = shutil.which("g++") or shutil.which("c++")
    make = shutil.which("make")
    if not compiler or not make:
        raise AssertionError("Managed build-record tests require Make and a host C++ preprocessor")
    marker = directory / "forbidden-compiler-used"
    guard = directory / "compiler-guard"
    guard.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$P06_PREFLIGHT_COMPILER_SENTINEL"\nexit 97\n')
    guard.chmod(0o700)
    env = {
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
        "LANG": "C", "LC_ALL": "C", "TMPDIR": str(directory),
        "PYTHONDONTWRITEBYTECODE": "1", "MAKEFLAGS": "-j1", "THREADS": "1",
        "CCACHE_DISABLE": "1", "OBJCACHE": "", "ORIGIN": "must-not-expand",
        "P06_PREFLIGHT_COMPILER_SENTINEL": str(marker),
    }
    guard_options = [name + "=" + str(guard) for name in ("CC", "CXX", "VX_CC", "VX_CXX")]
    command_count = 0

    def run(argv, cwd, environment=None):
        nonlocal command_count
        command_count += 1
        return run_host_command(list(map(str, argv)), cwd=cwd, env=environment or env,
                                timeout=90, max_output_bytes=2 * 1024**2)

    files = {path.relative_to(ROOT).as_posix()
             for name in ("sim", "sw", "tests/regression")
             for path in (ROOT / name).rglob("*") if path.is_file()}
    generated = {}
    for fmt in ("fp16", "bf16"):
        build = directory / fmt
        build.mkdir()
        run([ROOT / "configure", "--xlen=64", "--profile=p02-tfr", "--osversion=ubuntu/focal",
             "--tooldir=" + str(directory / "unused-tools")], build)
        current = dict(env, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1 -DSIMX_CHECKED_COUNTERS=1",
                       PERF="1")
        runtime = build / "sw/runtime"
        for relative, target in (("sw/runtime/simx", "simx_rt_config.stamp"),
                                 ("sim/simx", "simx_config.stamp")):
            run([make, "--no-print-directory", "-s", "-j1", "-C", relative,
                 *guard_options, "DESTDIR=" + str(runtime), runtime / target], build, current)
        run([make, "--no-print-directory", "-s", "-j1", "--old-file=.depend", "-C", APP,
             *guard_options, "config.stamp"], build, current)
        backend_makefile = build / APP / "backend.mk"
        run([make, "--no-print-directory", "-s", "-j1", "-f", backend_makefile,
             *guard_options, "DESTDIR=" + str(runtime), runtime / "preflight_backend_link.stamp"],
            build / "sw/runtime/simx", current)
        stamps = ((runtime / "simx_rt_config.stamp").read_text(),
                  (runtime / "simx_config.stamp").read_text(),
                  (build / APP / "config.stamp").read_text())
        backend_linker = (runtime / "preflight_backend_link.stamp").read_text()
        dry_run = run([make, "--no-print-directory", "-n", "-j1", "THREADS=1", "-f", backend_makefile,
                       *guard_options, "DESTDIR=" + str(runtime), runtime / "libvortex-simx.so"],
                      build / "sw/runtime/simx", current)
        commands = "\n".join(line for line in dry_run.splitlines() if line.startswith(str(guard) + " ")) + "\n"
        if marker.exists():
            raise AssertionError("Generating records invoked a native compiler")

        expanded_flags = run([sys.executable, ROOT / "ci/gen_config.py",
            "--config=" + str(ROOT / "VX_config.toml"), "--profile=p02-tfr", "--xlen=64",
            "--format=cflags", f"--cflags=-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1 -DVX_CFG_XLEN=64"], build)
        expanded = run([compiler, "-E", "-dM", "-x", "c++", *shlex.split(expanded_flags),
            *("-D" + name + "_DISABLE" for name in DISABLED),
            "-include", build / "sw/VX_config.h", "/dev/null"], build)
        base = run([compiler, "-E", "-dM", "-x", "c++", "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
                    "-include", build / "sw/VX_config.h", "/dev/null"], build)
        expected = {role: dict(hardware_macros(expanded), SIMX_CHECKED_COUNTERS="1") for _, _, role in ROLES}
        expected["backend_cpp"] = dict(hardware_macros(base), PERF_ENABLE="1", SIMX_CHECKED_COUNTERS="1",
                                       **{name + "_DISABLE": "1" for name in DISABLED})
        probe = build / "managed-record-probe.cpp"
        probe.write_text("#include <VX_config.h>\n")
        directories = {"runtime": build / "sw/runtime/simx", "backend_cpp": build / "sim/simx",
                       "kernel": build / APP, "host": build / APP}
        headers = {}
        for outer, inner, role in ROLES:
            words = shlex.split(stamps[outer].splitlines()[inner])
            relevant = [word for word in words if word.startswith(("-D", "-I"))]
            headers[role] = run([compiler, "-E", "-dM", "-x", "c++", *relevant, probe],
                                directories[role])
        generated[fmt] = {
            "stamps": stamps, "backend_linker": backend_linker, "text": commands,
            "source": ROOT, "build": build, "compiler": str(guard), "make": make,
            "fmt": fmt, "source_files": files, "headers": headers, "expected_headers": expected,
        }
    return {"formats": generated, "command_count": command_count, "guard_marker": marker}
