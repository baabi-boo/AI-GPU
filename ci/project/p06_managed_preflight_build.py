# SPDX-License-Identifier: Apache-2.0
"""Check the original seed-free managed-preflight build records as inert data."""

from collections import Counter
import hashlib
from pathlib import Path, PurePosixPath
import re

from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
from compiler_records import _compiler_arguments, _records, _syntax
from p02_matrix_records import require
import p06_compiler_records as timed
import p06_warm_compiler_records as warm


CONTRACT_ID = "p06-managed-counter-preflight-build-v1"
APP = "tests/regression/ai_counter_preflight"
GUARD = "SIMX_CHECKED_COUNTERS"
GUARD_FLAG = "-D" + GUARD + "=1"
# These options consume the next token in the compiler grammar admitted below.
# The checked-counter definition must be a driver argument, never their operand:
# removing an operand during projection would change the remaining command.
_OPERAND_OPTIONS = frozenset((
    "-D", "-U", "--define-macro", "--undefine-macro", "-Xpreprocessor",
    "-I", "-isystem", "-isystem-after", "-iquote", "-idirafter", "-iprefix",
    "-iwithprefix", "-iwithprefixbefore", "-isysroot", "-imultilib", "-imultiarch",
    "-MF", "-MT", "-MQ", "--include-directory", "--include-directory-after",
    "--include-prefix", "--include-with-prefix", "--include-with-prefix-after",
    "--include-with-prefix-before", "--sysroot",
))
ROLES = warm.ROLES
BACKEND_LINK_STAMP = "sw/runtime/preflight_backend_link.stamp"
WRAPPED_PROCESSOR_SYMBOLS = (
    "_ZN6vortex9ProcessorC1Ev", "_ZN6vortex9ProcessorD1Ev",
    "_ZN6vortex9Processor11run_checkedEv", "_ZN6vortex9Processor8dcr_readEjjPj",
    "_ZN6vortex9Processor9dcr_writeEjj",
)
HOST_WRAP_FLAGS = (*warm.WRAP_FLAGS, "-Wl,--wrap=vx_device_mpm_query")
MODEL_SOURCES = (
    "sw/common/util.cpp", "sim/common/mem.cpp", "sw/common/softfloat_ext.cpp",
    "sw/common/rvfloats.cpp", "sim/common/dram_sim.cpp", "sim/common/cmd_processor.cpp",
    "sim/common/elf_loader.cpp", "sim/common/host_monitor.cpp", "sim/common/cout_drainer.cpp",
    *("sim/simx/" + name + ".cpp" for name in (
        "processor", "cluster", "socket", "core", "scheduler", "cta_dispatcher",
        "barrier_unit", "gbar_unit", "kmu/kmu", "decode", "decompressor", "scoreboard",
        "sequencer", "opc_unit", "dispatcher", "alu_unit", "fpu_unit", "lsu_unit",
        "sfu_unit", "wctl_unit", "csr_unit", "mem/cache", "mem/cache_cluster",
        "mem/memory", "mem/local_mem", "mem/mem_coalescer", "mem/local_mem_switch",
        "mem/lsu_mem_adapter", "dtm/debug_module", "dtm/jtag_dtm", "dtm/remote_bitbang",
        "operands", "tcu/tcu_unit", "tcu/tcu_tbuf")),
)
BACKEND_SOURCES = (
    "sw/runtime/simx/vortex.cpp", "sw/runtime/common/utils.cpp",
    "sim/common/cmd_processor.cpp", APP + "/hooks.cpp",
)
APP_SOURCES = (
    APP + "/main.cpp", "tests/regression/ai_warm_workspace/observer.cpp",
    "sw/runtime/ai/contract.cpp", "sw/runtime/ai/runtime.cpp",
)
REQUIRED_SOURCE_FILES = (*MODEL_SOURCES, *BACKEND_SOURCES, *APP_SOURCES,
    APP + "/hooks.h", APP + "/backend.mk", APP + "/Makefile",
    "tests/regression/ai_warm_workspace/main.cpp",
    "tests/regression/ai_warm_workspace/observer.h", "sim/simx/types.h",
    "sim/common/perf_counter.h", "sim/simx/Makefile", "sw/runtime/simx/Makefile")


def _path(value, label):
    require(isinstance(value, (str, Path)), label + " must be a path")
    text = str(value)
    require(re.fullmatch(r"/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", text) is not None,
            label + " must be a safe absolute path")
    path = Path(text)
    require(str(path) == text and not {".", ".."} & set(path.parts),
            label + " must be lexically canonical")
    return path


def _roots(source, build):
    source, build = _path(source, "source root"), _path(build, "build root")
    require(source != build and not source.is_relative_to(build)
            and not build.is_relative_to(source), "source and build roots overlap")
    return source, build


def _lines(text, label):
    require(type(text) is str and len(text.encode("utf-8")) <= timed.MAX_RECORD_BYTES,
            label + " is not bounded text")
    return _records(text, label)


def _project_record(text, role, source):
    label = "managed preflight " + role + " stamp"
    require(len(_lines(text, label)) == 1, label + " must contain one original record")
    _syntax(text, label)
    words = _stamp_words(text, label)
    _compiler_arguments(words, label, kernel=role == "kernel")
    flags = _stamp_flags(text, label)
    require(not any(flag.startswith("-U") for flag in flags), label + " contains undefinitions")
    selected = [flag for flag in flags if flag[2:].partition("=")[0] == GUARD]
    require(selected == [GUARD_FLAG] and words.count(GUARD_FLAG) == 1,
            label + " requires exactly one direct checked-counter definition")
    guard_index = words.index(GUARD_FLAG)
    require(guard_index == 0 or words[guard_index - 1] not in _OPERAND_OPTIONS,
            label + " checked-counter definition is an option operand")
    require(_stamp_defines(text, label).get(GUARD) == "1", label + " disables checked counters")
    projected = list(words)
    projected.remove(GUARD_FLAG)
    removed = [GUARD_FLAG]
    if role == "host":
        extra = "-I" + str(source / "sw/runtime/common")
        require(projected.count(extra) == 1, label + " requires its exact runtime inspection include")
        index = projected.index(extra)
        require(index > 0 and projected[index - 1] == "-I" + str(source / "sw/runtime/ai"),
                label + " changes the host include search order")
        projected.pop(index)
        removed.append(extra)
    return " ".join(projected), removed


def host_link_flags(build):
    build = _path(build, "build root")
    return [*HOST_WRAP_FLAGS, "-L" + str(build / "sw/runtime"), "-lvortex", "-lvortex-simx"]


def backend_link_flags(build):
    build = _path(build, "build root")
    return ["-shared", "-pthread", "-Wl,-rpath,$ORIGIN", "-L" + str(build / "sw/runtime"),
            "-lsimx", *("-Wl,--wrap=" + name for name in WRAPPED_PROCESSOR_SYMBOLS)]


def validate_backend_linker(text, *, build):
    label = "managed preflight backend linker stamp"
    require(len(_lines(text, label)) == 1, label + " must contain one original record")
    _syntax(text.replace("-Wl,-rpath,'$ORIGIN'", ""), label)
    words = _stamp_words(text, label)
    require(words == backend_link_flags(build), label + " changes the exact production library/wrapper link")
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "arguments": words,
            "wrapped_processor_symbols": list(WRAPPED_PROCESSOR_SYMBOLS)}


def validate_records(runtime, backend, application, *, driver="simx", fmt, source, build, jobs):
    """Admit only the guard and fixed observer additions before historical checks."""
    require(driver == "simx" and type(driver) is str, "managed preflight requires SimX")
    require(type(fmt) is str and fmt in ("fp16", "bf16"), "unsupported managed preflight format")
    require(type(jobs) is int and jobs in (1, 2), "unsupported managed preflight build budget")
    source, build = _roots(source, build)
    records = (_lines(runtime, "managed runtime stamp"), _lines(backend, "managed model stamp"),
               _lines(application, "managed application stamp"))
    require(tuple(map(len, records)) == (1, 1, 3), "managed preflight compiler record inventory differs")
    originals = [records[0][0], records[1][0], *records[2][:2]]
    projections = [_project_record(text, role, source) for text, role in zip(originals, ROLES)]
    _syntax(records[2][2], "managed preflight host linker")
    require(_stamp_words(records[2][2], "managed preflight host linker") == host_link_flags(build),
            "managed preflight host link changes its five observers or exact runtime libraries")
    historical_link = " ".join([*warm.WRAP_FLAGS, "-L" + str(build / "sw/runtime"), "-lvortex"])
    verified = warm.validate_records(projections[0][0], projections[1][0],
        "\n".join([projections[2][0], projections[3][0], historical_link]),
        driver=driver, fmt=fmt, source=source, build=build, jobs=jobs)
    for row, original, (projected, removed) in zip(verified, originals, projections):
        row.update(sha256=hashlib.sha256(original.encode()).hexdigest(), original_record=original,
            projection_sha256=hashlib.sha256(projected.encode()).hexdigest(), projection_removed=removed,
            macro_flags=_stamp_flags(original, "original managed preflight record"))
        row["configuration"][GUARD] = "1"
        if row["role"] == "host":
            row["include_paths"].insert(1, str(source / "sw/runtime/common"))
    return verified


def validate_effective_header(text, expected, *, driver="simx", role):
    require(driver == "simx" and role in ROLES, "unsupported managed effective-header role")
    lines = _lines(text, "managed preflight effective header")
    selected = [line for line in lines if re.match(r"#define " + GUARD + r"(?:\s|\(|$)", line)]
    require(selected == ["#define " + GUARD + " 1"], "effective header lacks the exact checked-counter definition")
    require(type(expected) is dict and expected.get(GUARD) == "1",
            "expected effective header lacks checked-counter selection")
    projected = "\n".join(line for line in lines if line != selected[0])
    historical = {name: value for name, value in expected.items() if name != GUARD}
    result = warm.validate_effective_header(projected, historical, driver=driver, role=role)
    return dict(result, **{GUARD: "1"})


def expected_object(relative, build):
    root = _path(build, "build root") / "sw/runtime/obj"
    require(relative in MODEL_SOURCES, "source is not in the seed-free production model inventory")
    for prefix, destination in (("sw/common/", "common"), ("sim/common/", "sim_common"), ("sim/simx/", "")):
        if relative.startswith(prefix):
            return root / destination / PurePosixPath(relative[len(prefix):]).with_suffix(".o")
    raise ValueError("source has no production object mapping")


def _dependency_flags(words, expected):
    require(words.count("-MF") == 1, "model compile has an ambiguous dependency path")
    index = words.index("-MF")
    require(index + 1 < len(words) and words[index + 1] == str(expected),
            "model compile changes its exact dependency path")
    return words[:index] + words[index + 2:]


def _model_libraries(source):
    third_party = source / "third_party"
    return [str(third_party / "softfloat/build/Linux-x86_64-GCC/softfloat.a"),
        "-Wl,-rpath," + str(third_party / "ramulator"), "-L" + str(third_party / "ramulator"), "-lramulator",
        "-Wl,-rpath," + str(third_party / "ramulator_ext"), "-L" + str(third_party / "ramulator_ext"),
        "-Wl,--push-state,--no-as-needed", "-lramulator-vortex", "-Wl,--pop-state"]


def validate_build_commands(text, runtime, backend, backend_linker, *, source, build,
                            compiler, make, fmt, source_files):
    """Bind a fresh 43-TU model and wrapped backend without reading producer paths."""
    source, build = _roots(source, build)
    compiler, make = str(_path(compiler, "compiler path")), str(_path(make, "make path"))
    require(type(fmt) is str and fmt in ("fp16", "bf16"), "unsupported build format")
    require(type(source_files) in (list, tuple, set, frozenset)
            and all(type(name) is str for name in source_files)
            and set(REQUIRED_SOURCE_FILES) <= set(source_files), "build source inventory is incomplete")
    for original, role in ((runtime, "runtime"), (backend, "backend_cpp")):
        projected, _ = _project_record(original, role, source)
        timed._record(projected, "managed " + role + " stamp", fmt,
                      role=role, source=source, build=build)
        warm._configuration(projected, role=role, fmt=fmt)
    model_words = _stamp_words(backend, "original managed model stamp")
    runtime_words = _stamp_words(runtime, "original managed runtime stamp")
    link_record = validate_backend_linker(backend_linker, build=build)
    directory = build / "sw/runtime"
    model_binary, backend_binary = directory / "libsimx.so", directory / "libvortex-simx.so"
    expected_flags = _dependency_flags(model_words, directory / "simx_config.stamp")
    expected_inputs = {source / name: expected_object(name, build) for name in MODEL_SOURCES}
    require(len(expected_inputs) == 43, "production model inventory is not the reviewed 43-source route")
    compiled, links = {}, {}
    for line in _lines(text, "managed preflight build log"):
        words = _stamp_words(line, "managed preflight build command")
        if not words:
            continue
        if words[0] != compiler:
            if words == ["DESTDIR=" + str(directory), make, "-C", str(build / "sim/simx"), str(model_binary)]:
                continue
            require(not any(word.endswith((".o", ".cpp", ".a", ".so")) for word in words),
                    "managed build log contains an unrecognized source/object/library command")
            continue
        arguments = words[1:]
        require(arguments.count("-o") == 1 and len(arguments) >= 2 and arguments[-2] == "-o",
                "managed build output is ambiguous")
        target = _path(arguments[-1], "managed build output")
        body = arguments[:-2]
        if "-c" in body:
            _syntax(line, "managed model compile command")
            require(body.count("-c") == 1 and len(body) >= 2 and body[-2] == "-c",
                    "managed model compile source is ambiguous")
            original = _path(body[-1], "managed model compile source")
            require(original in expected_inputs and target == expected_inputs[original]
                    and target not in compiled, "model compile changes or repeats the production source/object map")
            require(_dependency_flags(body[:-2], target.with_suffix(".d")) == expected_flags,
                    "model translation-unit flags differ from its original stamp")
            compiled[target] = str(original)
        elif target == model_binary:
            _syntax(line, "managed model link command")
            require(target not in links, "managed model link is repeated")
            prefix = list(model_words)
            prefix[prefix.index("-MF") + 1] = str(model_binary)
            tail = ["-shared", *_model_libraries(source)]
            require(body[:len(prefix)] == prefix and body[-len(tail):] == tail
                    and Counter(body[len(prefix):-len(tail)]) == Counter(map(str, expected_inputs.values())),
                    "model link changes production objects or exact dependencies")
            links[target] = body
        elif target == backend_binary:
            _syntax(line.replace("-Wl,-rpath,'$ORIGIN'", ""), "managed backend link command")
            require(target not in links, "managed backend link is repeated")
            require(body == [*runtime_words, *(str(source / name) for name in BACKEND_SOURCES),
                             *link_record["arguments"]],
                    "backend compile/link changes production inputs, read-only hooks, flags or wrappers")
            links[target] = body
        else:
            raise ValueError("managed build contains an unexpected compile/link target")
    require(set(compiled) == set(expected_inputs.values()) and set(links) == {model_binary, backend_binary},
            "managed build lacks the exact fresh model and backend compile/link inventory")
    return {"contract_id": CONTRACT_ID, "compiler": compiler, "model_translation_units": 43,
        "backend_translation_units": len(BACKEND_SOURCES), "link_count": 2,
        "compiled_sources": sorted(compiled.values()), "object_paths": sorted(map(str, compiled)),
        "backend_sources": [str(source / name) for name in BACKEND_SOURCES],
        "links": [{"target": str(path), "arguments": links[path]} for path in (model_binary, backend_binary)],
        "backend_linker": link_record, "diagnostic_object_substitutions": False,
        "dependency_compilation_provenance_verified": False, "qualified": False}
