# SPDX-License-Identifier: Apache-2.0
"""Derive the selected dependency source graph from locked inert build inputs."""

from collections import Counter
import hashlib
import re

import p06_dependency_contract as contract


RAMULATOR_TARGETS = (
    ("base", "ramulator-base", 6), ("test", "ramulator-test", 1),
    ("frontend", "ramulator-frontend", 10),
    ("translation", "ramulator-translation", 2),
    ("memory_system", "ramulator-memorysystem", 3),
    ("addr_mapper", "ramulator-addrmapper", 2),
    ("dram", "ramulator-dram", 11), ("dram_controller", "ramulator-controller", 25),
)
SPDLOG_SOURCES = ("spdlog", "stdout_sinks", "color_sinks", "file_sinks", "async",
                  "cfg", "bundled_fmtlib_format")
CMAKE_OPTIONS = {
    "CMAKE_BUILD_TYPE": "Release", "CMAKE_CXX_STANDARD": "20",
    "CMAKE_CXX_STANDARD_REQUIRED": "ON", "CMAKE_CXX_EXTENSIONS": "OFF",
    "CMAKE_POSITION_INDEPENDENT_CODE": "ON", "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
    "BUILD_SHARED_LIBS": "OFF", "BUILD_TESTING": "OFF",
    "YAML_BUILD_SHARED_LIBS": "OFF", "YAML_CPP_BUILD_CONTRIB": "OFF",
    "YAML_CPP_BUILD_TOOLS": "OFF", "YAML_CPP_BUILD_TESTS": "OFF", "YAML_CPP_INSTALL": "OFF",
    "SPDLOG_BUILD_ALL": "OFF", "SPDLOG_BUILD_SHARED": "OFF", "SPDLOG_BUILD_PIC": "ON",
    "SPDLOG_ENABLE_PCH": "OFF", "SPDLOG_BUILD_EXAMPLE": "OFF",
    "SPDLOG_BUILD_EXAMPLE_HO": "OFF", "SPDLOG_BUILD_TESTS": "OFF",
    "SPDLOG_BUILD_TESTS_HO": "OFF", "SPDLOG_BUILD_BENCH": "OFF", "SPDLOG_INSTALL": "OFF",
    "SPDLOG_USE_STD_FORMAT": "OFF", "SPDLOG_FMT_EXTERNAL": "OFF",
    "SPDLOG_FMT_EXTERNAL_HO": "OFF", "SPDLOG_NO_EXCEPTIONS": "OFF", "SPDLOG_NO_TLS": "OFF",
    "ARGPARSE_BUILD_TESTS": "OFF", "ARGPARSE_BUILD_SAMPLES": "OFF",
    "ARGPARSE_LONG_VERSION_ARG_ONLY": "OFF",
    "FETCHCONTENT_FULLY_DISCONNECTED": "ON", "FETCHCONTENT_UPDATES_DISCONNECTED": "ON",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _softfloat_objects(makefile, variable, count):
    sections = re.findall(r"(?m)^OBJS_" + variable + r" = ([\s\S]*?)(?=\n\n)", makefile)
    require(len(sections) == 1, "SoftFloat object declaration is ambiguous")
    # The pinned lists continue onto an empty line. Include the delimiter's
    # first newline so its terminal backslash is a continuation, not an object.
    words = (sections[0] + "\n").replace("\\\n", " ").split()
    require(len(words) == count and all(re.fullmatch(r"[A-Za-z0-9_]+\$\(OBJ\)", word)
                                       for word in words), "SoftFloat object declaration changed")
    return [word.removesuffix("$(OBJ)") for word in words]


def _ramulator_sources(text, target, count):
    sections = re.findall(r"target_sources\s*\(([^()]*)\)", text)
    require(len(sections) == 1, "Ramulator target source declaration is ambiguous")
    words = sections[0].split()
    require(words[:2] == [target, "PRIVATE"]
            and all(re.fullmatch(r"[A-Za-z0-9_/-]+\.(?:h|cpp)", word) for word in words[2:]),
            "Ramulator target source grammar changed")
    selected = [word for word in words[2:] if word.endswith(".cpp")]
    require(len(selected) == count, "Ramulator target source count changed")
    return selected


def source_plan(manifest, source_body):
    """Read source_body(component, relative_path) as bytes, without executing it."""
    from p06_dependency_sources import validate_manifest
    validate_manifest(manifest)
    files = {row["name"]: {item["path"]: item for item in row["files"]}
             for row in manifest["sources"]}

    def body(component, relative):
        expected = files[component].get(relative)
        require(expected is not None, "selected build source is absent: " + component + "/" + relative)
        data = source_body(component, relative)
        require(type(data) is bytes and len(data) == expected["size_bytes"]
                and hashlib.sha256(data).hexdigest() == expected["sha256"],
                "locked build source bytes differ: " + component + "/" + relative)
        return data

    plan = []

    def add(component, owner, relative, member=None):
        body(owner, relative)
        row = {"component": component, "source": owner + "/" + relative}
        if member is not None:
            row["archive_member"] = member
        plan.append(row)

    makefile = body("softfloat", "build/Linux-x86_64-GCC/Makefile").decode("utf-8")
    for variable, count, directory in (("PRIMITIVES", 31, "source"),
                                       ("SPECIALIZE", 20, "source/RISCV"),
                                       ("OTHERS", 258, "source")):
        for name in _softfloat_objects(makefile, variable, count):
            add("softfloat", "softfloat", directory + "/" + name + ".c", name + ".o")
    for directory, target, count in RAMULATOR_TARGETS:
        text = body("ramulator", "src/" + directory + "/CMakeLists.txt").decode("utf-8")
        for relative in _ramulator_sources(text, target, count):
            add("ramulator", "ramulator", "src/" + directory + "/" + relative)
    yaml_sources = sorted(name for name in files["yaml-cpp"]
                          if re.fullmatch(r"src/[A-Za-z0-9_-]+\.cpp", name))
    require(len(yaml_sources) == 29, "yaml-cpp selected glob differs from the locked graph")
    for relative in yaml_sources:
        add("yaml-cpp", "yaml-cpp", relative, relative.rsplit("/", 1)[-1] + ".o")
    for name in SPDLOG_SOURCES:
        add("spdlog", "spdlog", "src/" + name + ".cpp", name + ".cpp.o")
    add("extension", "ramulator", "src/dram/impl/GDDR6.cpp")
    require(Counter(row["component"] for row in plan) == contract.TRANSLATION_UNITS,
            "selected dependency translation-unit population differs")
    require(len({row["source"] for row in plan}) == len(plan),
            "selected dependency source is compiled more than once")
    return plan
