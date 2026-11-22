# SPDX-License-Identifier: Apache-2.0
"""Bind public counter diagnostics to their exact native build records."""

from collections import Counter
import hashlib
from pathlib import Path, PurePosixPath
import re

from baseline_packet_contract import _stamp_defines, _stamp_words
from compiler_records import _compiler_arguments, _records, _syntax
import p06_checked_execute as checked
import p06_compiler_records as records


ROOT = "sim/simx/checked-public/"
KINDS = ("runtime", "backend", "main")
STAMPS = tuple(ROOT + kind + "_config.stamp" for kind in KINDS)
ARTIFACTS = tuple(ROOT + name for name in (
    "libchecked-simx.so", "libvortex-simx.so", "libvortex.so", "checked_public_test"))
WRAPS = (
    "_ZN6vortex9ProcessorC1Ev", "_ZN6vortex9ProcessorD1Ev",
    "_ZN6vortex9Processor11run_checkedEv", "_ZN6vortex9Processor8dcr_readEjjPj",
    "_ZN6vortex9Processor9dcr_writeEjj",
)
RUNTIME_SOURCES = ("sw/runtime/stub/vortex.cpp", *(
    "sw/runtime/common/" + name + ".cpp" for name in (
        "graphics", "result", "device", "buffer", "queue", "event", "module",
        "runtime_helpers", "perf", "legacy_runtime", "legacy_utils", "utils", "vm")))
BACKEND_SOURCES = ("sw/runtime/simx/vortex.cpp", "sw/runtime/common/utils.cpp",
                   "sim/common/cmd_processor.cpp")
HOOKS = "tests/unittest/checked_counters/public_hooks.cpp"
MAIN = "tests/unittest/checked_counters/public_main.cpp"
HEADERS = ("tests/unittest/checked_counters/public.mk",
           "tests/unittest/checked_counters/public_hooks.h",
           "tests/unittest/checked_counters/counter_access.h",
           "tests/regression/ai_bench_common/counters.h",
           "sw/runtime/common/vortex2_internal.h", "sw/runtime/include/vortex.h")

# The configured p02-tfr records include repeated expanded/profile definitions.
# Pin every role's ordered original tokens so unknown defines fail closed.
MACRO_INVENTORY = {
    "model": (36, "5244c57d60f6f8fe57fb6fcd495a9fa87920ff7de06f416368401fd90fad26ab"),
    "runtime": (304, "ce7408aa49ea29ac56693e72bc6d7fb563806fce53fe3dc72a4686e09f592551"),
    "backend": (306, "b8d552301b2a98a5b220a7b78f204bb8a40790f51c7a0b179c264aaf50fce0fe"),
    "main": (304, "ce7408aa49ea29ac56693e72bc6d7fb563806fce53fe3dc72a4686e09f592551"),
}
require = checked.require


def _path(value, label):
    path = checked._absolute_record_path(value, label)
    require(re.fullmatch(r"/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", str(path)),
            label + " is not a safe normalized absolute path")
    return path


def _macro_inventory(words, kind, label):
    macros = [word for word in words if word.startswith("-D")]
    count, digest = MACRO_INVENTORY[kind]
    require(len(macros) == count
            and hashlib.sha256(("\n".join(macros) + "\n").encode()).hexdigest() == digest,
            label + " changes the complete ordered macro inventory")


def _stamp(text, kind, source, build):
    label = kind + " public compiler stamp"
    require(type(text) is str and len(text.encode("utf-8")) <= records.MAX_RECORD_BYTES
            and len(_records(text, label)) == 1, label + " must contain one bounded record")
    _syntax(text, label)
    words = _stamp_words(text, label)
    _compiler_arguments(words, label)
    _macro_inventory(words, kind, label)
    defines = _stamp_defines(text, label)
    require(defines.get(checked.GUARD) == "1" and defines.get("NDEBUG") == "1",
            label + " lacks checked release selection")
    records._configuration({name: value for name, value in defines.items() if name != checked.GUARD},
                           label, performance=False, raw=True, expanded=True)
    common = ["-std=c++17", "-Wall", "-Wextra", "-Wfatal-errors", "-Werror"]
    if kind == "backend":
        includes = [source / "sw/runtime/include", build / "sw/runtime/common", build / "sw", build / "hw",
                    source / "sim/simx", source / "sim/common", source / "sw/common",
                    source / "sw/runtime/common"]
        options = common + ["-fPIC"] + ["-I" + str(path) for path in includes]
    else:
        includes = [source / "sw/runtime/include", source / "sw/kernel/include", build / "sw", build / "hw",
                    source / "sw/common", source / "sw/runtime/common"]
        options = common + ["-I" + str(path) for path in includes] + ["-fPIC"]
    options += ["-O2", "-MMD", "-MP", "-MF", str(build / STAMPS[KINDS.index(kind)])]
    require([word for word in words if not word.startswith("-D")] == options,
            label + " changes compiler options, includes or dependency target")
    return words


def _identities(value, expected, label):
    require(type(value) is list and len(value) == len(expected), label + " has an incomplete object inventory")
    paths = []
    for item in value:
        require(type(item) is dict and set(item) == {"path", "resolved_path", "sha256", "size_bytes"},
                label + " has malformed identity fields")
        require(type(item["path"]) is str and type(item["resolved_path"]) is str,
                label + " has a nontext object path")
        path = _path(item["path"], label + " object path")
        require(item["resolved_path"] == str(path), label + " resolves an object through an alias")
        require(type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                and type(item["size_bytes"]) is int and item["size_bytes"] > 0,
                label + " has invalid object digest or size")
        paths.append(str(path))
    require(Counter(paths) == Counter(map(str, expected)), label + " changes the exact object inventory")
    return [dict(item) for item in value]


def _model_records(value, source, build, compiler):
    require(type(value) is dict and set(value) == {
        "compiled_sources", "object_identities", "included_production_sources", "generated_production_sources",
        "compiler", "translation_units", "link_count"}, "prior model records have unexpected fields")
    require(type(value["translation_units"]) is int and value["translation_units"] == 45
            and type(value["link_count"]) is int and value["link_count"] == 1
            and value["compiler"] == compiler, "prior model compiler or build counts differ")
    sources = sorted(str(build / checked.GENERATED_TCU if name == checked.TCU_FOOTER else source / name)
                     for name in checked.MODEL_SOURCES)
    require(value["compiled_sources"] == sources
            and value["included_production_sources"] == checked.INCLUDED_SOURCES
            and value["generated_production_sources"] == {str(build / checked.GENERATED_TCU): {
                "production_source": checked.TCU_ORIGINAL, "access_footer": checked.TCU_FOOTER,
                "separator_hex": "0a"}}, "prior model source provenance differs")
    expected = [checked.expected_object(name, build) for name in checked.MODEL_SOURCES]
    identities = _identities(value["object_identities"], expected, "prior model")
    omitted = str(checked.expected_object(checked.DIAGNOSTIC_ROOT + "main.cpp", build))
    return [item for item in identities if item["path"] != omitted]


def _new_inputs(source, build):
    inputs = {}
    for name in RUNTIME_SOURCES:
        suffix = PurePosixPath(name[len("sw/runtime/"):]).with_suffix(".o")
        inputs[build / ROOT / "obj/runtime" / suffix] = (source / name, "runtime")
    for name in BACKEND_SOURCES:
        inputs[build / ROOT / "obj/backend" / PurePosixPath(name).with_suffix(".o").name] = (source / name, "backend")
    inputs[build / "sim/simx/obj/tests/checked_counters/public_hooks.o"] = (source / HOOKS, "model")
    inputs[build / ROOT / "obj/public_main.o"] = (source / MAIN, "main")
    return inputs


def _logical_records(text):
    require(type(text) is str and len(text.encode("utf-8")) <= records.MAX_RECORD_BYTES,
            "public build log is not bounded text")
    _records(text, "public build log")
    return _records(text.replace("\\\n", " "), "public logical build log")


def parse_build_records(text, model_stamp_words, stamps, *, source, build, compiler, source_files, model_records):
    """Check retained paths and records as data without reading producer files."""
    source, build = _path(source, "source root"), _path(build, "build root")
    compiler = str(_path(compiler, "compiler path"))
    require(source != build and not source.is_relative_to(build) and not build.is_relative_to(source),
            "source and build roots overlap")
    require(type(model_stamp_words) is list and all(type(word) is str for word in model_stamp_words),
            "model stamp words must be a text-token list")
    model_words = checked.compile_flags(" ".join(model_stamp_words), checked=True, source=source, build=build)
    require(model_words == model_stamp_words, "model stamp words are not canonical")
    _macro_inventory(model_words, "model", "public model stamp")
    require(type(stamps) is dict and set(stamps) == set(KINDS), "public compiler stamp inventory differs")
    words = {kind: _stamp(stamps[kind], kind, source, build) for kind in KINDS}
    flags = {kind: checked.dependency_flags(words[kind], build / STAMPS[KINDS.index(kind)]) for kind in KINDS}
    flags["model"] = checked.dependency_flags(model_words, build / checked.STAMP)
    reused = _model_records(model_records, source, build, compiler)
    expected = _new_inputs(source, build)
    require(type(source_files) in (set, frozenset, list, tuple)
            and all(type(name) is str for name in source_files), "source inventory is not a collection of paths")
    required_sources = set(checked.MODEL_SOURCES) | set(checked.WRAPPER_SOURCES.values()) | set(HEADERS)
    required_sources.update((HOOKS, MAIN, *RUNTIME_SOURCES, *BACKEND_SOURCES))
    require(required_sources <= set(source_files), "source snapshot omits public or native implementation inputs")
    compiled, links = {}, {}
    for line in _logical_records(text):
        tokens = _stamp_words(line, "public build command")
        if not tokens or tokens[0] != compiler:
            require(not any(word.endswith((".o", ".cpp", ".so", ".a")) for word in tokens),
                    "public build contains an unrecognized source, object or library command")
            continue
        require("\\" not in line, "public command contains unsupported escape syntax")
        _syntax(line.replace("-Wl,-rpath,'$ORIGIN'", ""), "public build command")
        arguments = tokens[1:]
        require(len(arguments) >= 2 and arguments.count("-o") == 1 and arguments[-2] == "-o",
                "public build output is ambiguous")
        target = _path(arguments[-1], "public output")
        body = arguments[:-2]
        if "-c" in body:
            require(len(body) >= 2 and body.count("-c") == 1 and body[-2] == "-c",
                    "public compile source is ambiguous")
            original = _path(body[-1], "public source")
            require(target in expected and target not in compiled, "public compile target is foreign or repeated")
            expected_source, kind = expected[target]
            require(original == expected_source, "public source does not match its exact object mapping")
            require(checked.dependency_flags(body[:-2], target.with_suffix(".d")) == flags[kind],
                    "public translation-unit flags differ from its independent stamp")
            compiled[target] = {"source": str(original), "object": str(target), "kind": kind}
        else:
            require(target in {build / name for name in ARTIFACTS} and target not in links,
                    "public link output is foreign or repeated")
            links[target] = body
    require(set(compiled) == set(expected) and len(links) == 4,
            "public build lacks exactly 19 new compiles and four links")
    third_party = source / "third_party"
    dependencies = [str(third_party / "softfloat/build/Linux-x86_64-GCC/softfloat.a"),
        "-Wl,-rpath," + str(third_party / "ramulator"), "-L" + str(third_party / "ramulator"), "-lramulator",
        "-Wl,-rpath," + str(third_party / "ramulator_ext"), "-L" + str(third_party / "ramulator_ext"),
        "-Wl,--push-state,--no-as-needed", "-lramulator-vortex", "-Wl,--pop-state"]
    model, backend, runtime, app = (build / name for name in ARTIFACTS)
    prefix = list(model_words)
    prefix[prefix.index("-MF") + 1] = str(model)
    tail = ["-shared", *dependencies, "-Wl,-soname,libchecked-simx.so"]
    model_link = links[model]
    require(model_link[:len(prefix)] == prefix and model_link[-len(tail):] == tail
            and Counter(model_link[len(prefix):-len(tail)]) == Counter(item["path"] for item in reused),
            "public model link changes checked flags, the 44 reused objects or dependencies")
    objects = lambda kind: [str(path) for path, (_, group) in expected.items() if group == kind]
    require(links[runtime] == [*objects("runtime"), "-shared", "-pthread", "-ldl",
                              "-Wl,-soname,libvortex.so", "-Wl,-rpath,$ORIGIN"],
            "public runtime link differs from its 14 real objects and fixed libraries")
    require(links[backend] == [*objects("backend"), *objects("model"), "-shared", "-pthread",
                              "-Wl,-rpath,$ORIGIN", *("-Wl,--wrap=" + name for name in WRAPS),
                              "-L" + str(build / ROOT), "-lchecked-simx"],
            "public backend link changes its real inputs, hook placement or required wraps")
    require(links[app] == [*objects("main"), "-L" + str(build / ROOT), "-lvortex", "-lvortex-simx",
                          "-pthread", "-Wl,-rpath,$ORIGIN", "-Wl,-rpath-link," + str(build / ROOT)],
            "public executable link differs from its isolated runtime binding")
    return {"compiler": compiler, "translation_units": 19, "link_count": 4,
            "compiled_sources": sorted(item["source"] for item in compiled.values()),
            "compile_records": [compiled[path] for path in sorted(compiled)],
            "object_paths": list(map(str, compiled)), "reused_model_object_identities": reused,
            "links": [{"target": str(path), "arguments": links[path]} for path in (model, backend, runtime, app)],
            "wrapped_processor_symbols": list(WRAPS),
            "compiler_stamps": {kind: {"sha256": hashlib.sha256(stamps[kind].encode()).hexdigest(),
                                      "macro_tokens": MACRO_INVENTORY[kind][0],
                                      "macro_inventory_sha256": MACRO_INVENTORY[kind][1]}
                                for kind in KINDS}}


def validate_build(text, model_stamp_words, stamps, *, source, build, compiler, source_files, model_records):
    """Add actual object hashing to the pure build-record contract."""
    parsed = parse_build_records(text, model_stamp_words, stamps, source=source, build=build,
                                 compiler=compiler, source_files=source_files, model_records=model_records)
    for item in parsed["reused_model_object_identities"]:
        require(checked.native.file_identity(item["path"]) == item, "reused model object changed after its build")
    paths = parsed.pop("object_paths")
    require(all(Path(path).resolve(strict=True) == Path(path) for path in paths),
            "public object resolves through an alias")
    parsed["object_identities"] = [checked.native.file_identity(path) for path in paths]
    return parsed
