# SPDX-License-Identifier: Apache-2.0
"""Replay the complete original application build log without running a shell."""

from collections import Counter
import hashlib
from pathlib import PurePosixPath
import re

from baseline_packet_contract import _stamp_words
from compiler_records import _records
import p06_compiler_records as timed
import p06_managed_preflight_build as build_records
import p06_warm_compiler_records as warm
from p02_matrix_records import require


CONTRACT_ID = "p06-managed-preflight-application-replay-v1"
MAX_LOG_BYTES = 1024 * 1024
RECIPE_SHA256 = {
    "config.mk.in": "28fa1d7ad7076018ebb22a720df7cf3c792a5989a71834418f0ccb86a67551d1",
    "tests/regression/common.mk": "4164a783137b2f6e594ff3795f5911233227c3e4bfcb0319095cd6e78acf9b56",
    "tests/regression/ai_counter_preflight/Makefile": "1fefa29e176fff3ce05f1a606aebabc434f83fbaba6704afc14b9728c50f4bd2",
    "sw/kernel/Makefile": "b1c359421ca2b1b8c31b9dc98893fac772daa239e236e9d1c9225a1eb431238c",
    "sw/runtime/common.mk": "2af4343c0738db4a665c96e24f90f78912302b20597dda74d9592afb6676736e",
    "sw/runtime/stub/Makefile": "e6aae339e07e2a3086cc0334c9353001521f774afdc9e921acf1e126b115b941",
    "sw/kernel/scripts/kernel_startup.sh": "8e408e07bf5e177da7e466cb14f1d386c487a2e390f7fcebd20b5d157e683221",
    "sw/kernel/scripts/vxbin.py": "6c76ef0c505c68e02a68a3660021d20f6c8b8cc18b9a4c0b1a544611673875ed",
}
KERNEL_SOURCES = (
    "vx_start.S", "vx_syscalls.c", "vx_print.S", "tinyprintf.c", "vx_print.c",
    "vx_spawn.c", "vx_serial.S",
)
STUB_SOURCES = (
    "sw/runtime/stub/vortex.cpp",
    *("sw/runtime/common/" + name + ".cpp" for name in (
        "graphics", "result", "device", "buffer", "queue", "event", "module",
        "runtime_helpers", "perf", "legacy_runtime", "legacy_utils", "utils", "vm")),
)
STARTUP_FLAGS = "-DNEED_GP -DNEED_TLS -DNEED_INITFINI"


def _line(text):
    # Preserve quotes and shell punctuation: shlex would erase whether $ORIGIN
    # was quoted or a command substitution was literal text.
    return re.sub(r"[ \t]+", " ", text).strip(" ")


def _tool_paths(tools, tools_root):
    require(type(tools) is dict, "application replay needs selected tool identities")
    root = PurePosixPath(build_records._path(str(tools_root), "tool root"))
    expected = {
        "clang++": "llvm-vortex/bin/clang++",
        "llvm-objcopy": "llvm-vortex/bin/llvm-objcopy",
        "llvm-objdump": "llvm-vortex/bin/llvm-objdump",
        "riscv-gcc": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",
        "riscv-gcc-ar": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc-ar",
        "riscv-objdump": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-objdump",
        "libc64/lib/libc.a": "libc64/lib/libc.a",
        "libc64/lib/libm.a": "libc64/lib/libm.a",
        "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a":
            "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a",
    }
    selected = {}
    for name in (*expected, "g++", "make"):
        require(name in tools and type(tools[name]) is dict and "path" in tools[name],
                "application replay lacks selected tool " + name)
        selected[name] = str(build_records._path(tools[name]["path"], "selected application tool"))
        if name in expected:
            require(selected[name] == str(root / expected[name]),
                    "selected application tool differs from the retained recipe: " + name)
    return selected, root


def _flags(stamp, compiler_records, *, source, build, fmt):
    lines = build_records._lines(stamp, "application replay stamp")
    require(len(lines) == 3, "application replay needs kernel/host/linker stamps")
    require(type(compiler_records) is list and len(compiler_records) == 4,
            "application replay needs four independently checked compiler roles")
    require(all(type(row) is dict for row in compiler_records)
            and [row.get("role") for row in compiler_records] == list(build_records.ROLES),
            "application replay compiler roles differ")
    records = {row["role"]: row for row in compiler_records}
    for role, text in zip(("kernel", "host"), lines[:2]):
        require(records[role].get("original_record") == text,
                "application replay stamp differs from independent " + role + " record")
        projected, _ = build_records._project_record(text, role, source)
        timed._record(projected, "application replay " + role, fmt, role=role, source=source, build=build)
        warm._configuration(projected, role=role, fmt=fmt)
    kernel, host, linker = (_stamp_words(line, "application replay flags") for line in lines)
    require(linker == build_records.host_link_flags(build), "application replay host linker changed")
    require(kernel.count("-DVX_PROFILE=p02-tfr") == kernel.count("-DVX_CFG_XLEN=64") == 1,
            "application replay configuration boundaries are ambiguous")
    start, end = kernel.index("-DVX_PROFILE=p02-tfr"), kernel.index("-DVX_CFG_XLEN=64")
    require(start < end, "application replay configuration order changed")
    configs, expanded = kernel[start:end], kernel[end:]
    require(all(flag.startswith("-D") for flag in (*configs, *expanded)),
            "application replay configuration contains a non-definition")
    require(configs[-4:] == ["-DITYPE=" + fmt, "-DOTYPE=fp32", "-DKUNROLL=1", build_records.GUARD_FLAG],
            "application replay format or checked-counter selectors changed")
    return kernel, host, linker, configs, expanded


def _graph(*, source, build, root, selected, kernel, host, linker, configs, expanded):
    commands = {}

    def add(identifier, kind, parents, *parts):
        commands[identifier] = {"kind": kind, "parents": tuple(parents),
                                "text": _line(" ".join(map(str, parts)))}

    host_prefix = [selected["g++"], *host]
    host_sources = [source / name for name in build_records.APP_SOURCES]
    add("host-dependencies", "host_dependency", (), *host_prefix, "-MM", *host_sources, "> .depend;")
    add("stub-make", "recursive_make", ("host-dependencies",),
        'CONFIGS="' + " ".join(configs) + '"', "PERF=1", selected["make"], "-C",
        build / "sw/runtime/stub", "DESTDIR=" + str(build / "sw/runtime"))
    add("kernel-make", "recursive_make", ("host-dependencies",), selected["make"], "-C", build / "sw/kernel")
    library_prefix = [selected["riscv-gcc"], "-march=rv64imafd -mabi=lp64d -O3 -mcmodel=medany",
        "-fno-exceptions -fdata-sections -ffunction-sections -D__VORTEX__",
        "-Wall -Wextra -Wfatal-errors -Werror", "-I" + str(source / "sw/kernel/include"),
        "-I" + str(build / "sw"), "-I" + str(build / "hw"), *expanded]
    for tag, suffix, library in (("ordinary", ".o", "libvortex"), ("kmu", ".2.o", "libvortex2")):
        objects = []
        compiles = []
        for name in KERNEL_SOURCES:
            identifier = tag + ":" + name
            compiles.append(identifier)
            objects.append(name + suffix)
            extra = [STARTUP_FLAGS] if name.endswith(".S") else []
            if tag == "kmu":
                extra.append("-DKMU_ENABLE")
            add(identifier, "riscv_compile", ("kernel-make",), *library_prefix, *extra,
                "-c", source / "sw/kernel/src" / name, "-o", name + suffix)
        add(tag + "-archive", "kernel_archive", compiles, selected["riscv-gcc-ar"], "rcs",
            library + ".a", *objects)
        add(tag + "-dump", "archive_dump", (tag + "-archive",), selected["riscv-objdump"],
            "-D", library + ".a", ">", library + ".dump")
    riscv = root / "riscv64-gnu-toolchain"
    clang = [selected["clang++"], "--target=riscv64-unknown-elf", "--sysroot=" + str(riscv / "riscv64-unknown-elf"),
        "--gcc-toolchain=" + str(riscv), "-Xclang -target-feature -Xclang +xvortex",
        "-Xclang -target-feature -Xclang +zicond -mllvm -disable-loop-idiom-all",
        "-Wno-unused-command-line-argument", *kernel]
    startup = source / "sw/kernel/src/vx_start.S"
    kernel_link = ["vx_start.o matmul.o", "-Wl,-Bstatic,--gc-sections,-T," + str(
        source / "sw/kernel/scripts/link64.ld") + ",--defsym=STARTUP_ADDR=0x180000000",
        build / "sw/kernel/libvortex2.a", "-L" + str(root / "libc64/lib"), "-lm -lc",
        selected["libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"]]
    add("matmul-compile", "kernel_clang", ("ordinary-dump", "kmu-dump"), *clang, "-c",
        source / "sw/kernel/ai/matmul.cpp")
    add("startup-compile", "kernel_clang", ("matmul-compile",), *clang, STARTUP_FLAGS,
        "-DKMU_ENABLE -c", startup, "-o vx_start.o")
    add("startup-link", "kernel_clang", ("startup-compile",), *clang, *kernel_link, "-o vx_start.o.elf")
    add("startup-recompile", "kernel_clang", ("startup-link",), *clang,
        "$(" + str(source / "sw/kernel/scripts/kernel_startup.sh"), selected["llvm-objdump"],
        "vx_start.o.elf)", "-DKMU_ENABLE -c", startup, "-o vx_start.o && rm -f vx_start.o.elf")
    add("kernel-link", "kernel_clang", ("startup-recompile",), *clang, *kernel_link, "-o kernel.elf")
    add("vxbin", "kernel_conversion", ("kernel-link",), "OBJCOPY=" + selected["llvm-objcopy"],
        source / "sw/kernel/scripts/vxbin.py", "kernel.elf kernel.vxbin")
    add("kernel-dump", "kernel_dump", ("kernel-link",), selected["llvm-objdump"], "-D kernel.elf > kernel.dump")
    add("stub-link", "stub_compile_link", ("stub-make",), selected["g++"], *expanded,
        "-std=c++17 -Wall -Wextra -Wfatal-errors -Werror", "-I" + str(source / "sw/runtime/include"),
        "-I" + str(source / "sw/kernel/include"), "-I" + str(build / "sw"), "-I" + str(build / "hw"),
        "-I" + str(source / "sw/common"), "-I" + str(source / "sw/runtime/common"), "-fPIC", *configs,
        "-O2 -DNDEBUG", *(source / name for name in STUB_SOURCES),
        "-shared -pthread -ldl -Wl,-soname,libvortex.so -Wl,-rpath,'$ORIGIN'", "-o", build / "sw/runtime/libvortex.so")
    add("host-link", "host_compile_link", ("stub-link",), *host_prefix, *host_sources,
        build / "sw/runtime/libvortex.so", *linker, "-o ai_counter_preflight")
    return commands


def validate_application_build(text, stamp, *, source, build, tools_root, tools, fmt,
                               compiler_records, source_body):
    """Validate the frozen recipe graph; retained paths and commands stay inert."""
    require(type(fmt) is str and fmt in ("fp16", "bf16"), "unsupported application replay format")
    require(type(text) is str and len(text.encode("utf-8")) <= MAX_LOG_BYTES,
            "application build log is not bounded text")
    source, build = build_records._roots(str(source), str(build))
    selected, root = _tool_paths(tools, tools_root)
    # The reconstruction is intentionally limited to these reviewed recipes.
    # A different recipe needs an explicitly reviewed grammar, never execution.
    for name, digest in RECIPE_SHA256.items():
        body = source_body(name)
        require(type(body) is bytes and hashlib.sha256(body).hexdigest() == digest,
                "unsupported retained application recipe: " + name)
    kernel, host, linker, configs, expanded = _flags(stamp, compiler_records,
        source=source, build=build, fmt=fmt)
    graph = _graph(source=source, build=build, root=root, selected=selected,
        kernel=kernel, host=host, linker=linker, configs=configs, expanded=expanded)
    by_text = {row["text"]: name for name, row in graph.items()}
    require(len(by_text) == len(graph) == 30, "application recipe graph is ambiguous")
    lines = [_line(line) for line in _records(text, "application build log")]
    require(len(lines) == len(graph), "application build log has missing or extra command records")
    seen, order = set(), []
    for number, line in enumerate(lines, 1):
        require(line in by_text, "application build log has an unsupported or altered command at record " + str(number))
        name = by_text[line]
        require(name not in seen, "application build log repeats command " + name)
        require(set(graph[name]["parents"]) <= seen, "application build command precedes its prerequisites: " + name)
        seen.add(name)
        order.append(name)
    require(seen == set(graph), "application build command inventory differs")
    return {"contract_id": CONTRACT_ID, "format": fmt, "command_count": len(lines),
        "command_counts": dict(sorted(Counter(row["kind"] for row in graph.values()).items())),
        "command_order": order, "recipe_sha256": dict(RECIPE_SHA256),
        "normalized_commands_sha256": hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()}
