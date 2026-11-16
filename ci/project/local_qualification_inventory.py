# Licensed under the Apache License, Version 2.0.
"""Stable input and generated-recipe identities for local RTL qualification."""

import ast
import hashlib
import os
from pathlib import Path
import stat

from baseline import DEPENDENCIES
from baseline_host import collect_host
from baseline_inventory import _git, collect_build, collect_tools, hash_artifacts
from xrt_source import collect_source


HERE = Path(__file__).resolve().parent
MAX_FILE_BYTES = 1024 * 1024
MAX_HEADER_FILES = 512
MAX_HEADER_BYTES = 16 * 1024 * 1024
MAX_HELPERS = 64
MAX_HELPER_BYTES = 8 * 1024 * 1024
EXTENSION_INPUTS = (
    "third_party/Makefile",
    "third_party/ramulator/src/dram/impl/GDDR6.cpp",
)
EXTERNAL_HEADER_ROOTS = (
    "third_party/ramulator/ext/spdlog/include",
    "third_party/ramulator/ext/yaml-cpp/include",
)
COPIED_INPUTS = {
    "sim/xrtsim/Makefile": "sim/xrtsim/Makefile",
    "sim/xrtsim/verilator.vlt": "sim/xrtsim/verilator.vlt.in",
    "sw/runtime/xrt/Makefile": "sw/runtime/xrt/Makefile",
    "sw/runtime/xrt/xrt.ini": "sw/runtime/xrt/xrt.ini.in",
    "hw/unittest/common.mk": "hw/unittest/common.mk",
    "hw/unittest/verilator.vlt": "hw/unittest/verilator.vlt.in",
}
LIMITATIONS = (
    "Reused dependency binaries are hash-identified, not freshly rebuilt by this inventory.",
    "External dependency headers are identified by content; their hashes do not prove an upstream origin.",
    "Tool and host inventories do not cover every system header or dynamically loaded system library.",
    "Generated recipe equality does not establish successful compilation, native arithmetic selection or execution.",
)


def _finish(report):
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def _directory(value):
    requested = Path(os.path.abspath(value))
    resolved = requested.resolve(strict=True)
    if resolved != requested or not resolved.is_dir():
        raise ValueError("input root must be a directory without symlink traversal")
    return resolved


def _small_file(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("input must be a regular file, not a symlink")
    with path.open("rb") as stream:
        contents = stream.read(MAX_FILE_BYTES + 1)
    if len(contents) > MAX_FILE_BYTES:
        raise ValueError("input file exceeds its byte limit")
    return contents


def _header_files(root, relative_roots):
    names = []
    total = 0
    count = 0
    for relative in relative_roots:
        previous_count = len(names)
        directory = root / relative
        if directory.resolve(strict=True) != directory or not directory.is_dir():
            raise ValueError("header tree is missing or traverses a symlink")
        pending = [directory]
        while pending:
            current = pending.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    count += 1
                    if count > MAX_HEADER_FILES:
                        raise ValueError("header tree exceeds its entry limit")
                    if entry.is_symlink():
                        raise ValueError("header tree contains a symlink")
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                        if len(pending) + len(names) > MAX_HEADER_FILES:
                            raise ValueError("header tree exceeds its entry limit")
                    elif entry.is_file(follow_symlinks=False):
                        size = entry.stat(follow_symlinks=False).st_size
                        total += size
                        names.append(Path(entry.path).relative_to(root).as_posix())
                        if (size > MAX_FILE_BYTES or total > MAX_HEADER_BYTES
                                or len(names) > MAX_HEADER_FILES):
                            raise ValueError("header tree exceeds its file or byte limit")
                    else:
                        raise ValueError("header tree contains a nonregular input")
        if len(names) == previous_count:
            raise ValueError("declared header tree contains no files: " + relative)
    if not names:
        raise ValueError("header tree contains no files")
    identities = hash_artifacts(root, sorted(names))
    if sum(item["size_bytes"] for item in identities) != total:
        raise ValueError("header tree changed while being inventoried")
    return identities


def _gitlinks(source):
    entries = source.get("submodules", {}).get("entries", [])
    result = {entry["path"]: entry["revision"] for entry in entries
              if entry.get("status") == "initialized"}
    if not entries or len(result) != len(entries):
        raise ValueError("all recursive submodules must be initialized uniquely")
    return result


def _collect_dependencies(source, source_identity, dependency_source):
    report = {"reused": True, "source": collect_source(dependency_source),
              "gitlinks_match": False, "extension_inputs": [], "libraries": [],
              "external_headers": [], "blockers": []}
    report["blockers"].extend(report["source"]["blockers"])
    try:
        if _gitlinks(source_identity) != _gitlinks(report["source"]):
            raise ValueError("dependency supplier has different recursive submodule pins")
        report["gitlinks_match"] = True
        expected = hash_artifacts(source, list(EXTENSION_INPUTS))
        observed = hash_artifacts(dependency_source, list(EXTENSION_INPUTS))
        if observed != expected:
            raise ValueError("dependency extension build inputs differ from the selected source")
        for relative in EXTENSION_INPUTS:
            owner = dependency_source if relative == "third_party/Makefile" else dependency_source / "third_party/ramulator"
            tracked = relative if owner == dependency_source else "src/dram/impl/GDDR6.cpp"
            _git(owner, "ls-files", "--error-unmatch", "--", tracked)
        report["extension_inputs"] = observed
        report["libraries"] = hash_artifacts(dependency_source, list(DEPENDENCIES))
        report["external_headers"] = _header_files(dependency_source, EXTERNAL_HEADER_ROOTS)
    except (OSError, ValueError, RuntimeError, UnicodeError, KeyError) as error:
        report["blockers"].append("dependency reuse could not be verified: " + str(error))
    return _finish(report)


def collect_inputs(source, tool_dir, dependency_source, header_dir, environment):
    report = {"source": None, "tools": None, "host": None, "dependencies": None,
              "headers": [], "blockers": [], "limitations": list(LIMITATIONS)}
    try:
        source = _directory(source)
        tool_dir = _directory(tool_dir)
        dependency_source = _directory(dependency_source)
        header_dir = _directory(header_dir)
        if not isinstance(environment, dict):
            raise ValueError("effective environment must be a mapping")
        if (environment.get("THIRD_PARTY_DIR") != str(dependency_source / "third_party")
                or environment.get("CPLUS_INCLUDE_PATH") != str(header_dir)):
            raise ValueError("effective dependency and header paths differ from their inventoried roots")
        report["source"] = collect_source(source)
        report["tools"] = collect_tools(tool_dir, HERE / "p01_toolchain.lock.json")
        report["host"] = collect_host(environment)
        report["dependencies"] = _collect_dependencies(
            source, report["source"], dependency_source)
        for name in ("source", "tools", "host", "dependencies"):
            report["blockers"].extend(name + ": " + item for item in report[name]["blockers"])
        report["headers"] = _header_files(header_dir, (".",))
        if not any(item["path"] == "uuid/uuid.h" for item in report["headers"]):
            raise ValueError("UUID include tree does not contain uuid/uuid.h")
    except (OSError, ValueError, RuntimeError, UnicodeError, KeyError, TypeError) as error:
        report["blockers"].append("input inventory could not be completed: " + str(error))
    return _finish(report)


def collect_generated(build, source, cases):
    report = {"baseline": collect_build(build, source), "files": [], "source_files": [],
              "blockers": [], "limitations": [LIMITATIONS[-1]]}
    report["blockers"].extend(report["baseline"]["blockers"])
    try:
        build = _directory(build)
        source = _directory(source)
        copies = dict(COPIED_INPUTS)
        case_sources = set()
        for case in cases:
            if case["kind"] not in ("app", "unit"):
                raise ValueError("case contains an unsupported kind")
            prefix = "tests/regression" if case["kind"] == "app" else "hw/unittest"
            name = case["app"]
            if not isinstance(name, str) or not name or not all(
                    character.isascii() and (character.isalnum() or character == "_")
                    for character in name):
                raise ValueError("case contains an invalid build directory")
            relative = prefix + "/" + name + "/Makefile"
            copies[relative] = relative
            sources = case.get("sources", [])
            if not isinstance(sources, (list, tuple)) or any(
                    not isinstance(item, str) for item in sources):
                raise ValueError("case contains malformed source inputs")
            case_sources.update(sources)
        for destination, origin in copies.items():
            expected = _small_file(source / origin)
            if origin.endswith(".in"):
                expected = expected.replace(b"@VORTEX_HOME@", str(source).encode())
            if _small_file(build / destination) != expected:
                raise ValueError("generated recipe differs from source: " + destination)
        names = {item["path"] for item in report["baseline"]["generated"]}
        names.update(item["path"] for item in report["baseline"]["build_inputs"])
        names.update(copies)
        report["files"] = hash_artifacts(build, sorted(names))
        source_names = {item["path"] for item in report["baseline"]["source_inputs"]}
        source_names.update(item["path"] for item in report["baseline"]["source_build_inputs"])
        source_names.update(copies.values())
        source_names.update(case_sources)
        report["source_files"] = hash_artifacts(source, sorted(source_names))
    except (OSError, ValueError, RuntimeError, UnicodeError, KeyError, TypeError) as error:
        report["blockers"].append("generated local recipes could not be verified: " + str(error))
    return _finish(report)


def collect_helpers():
    pending = ["local_qualification.py", "local_qualification_cases.py",
               "local_qualification_inventory.py"]
    observed = {}
    total = 0
    while pending:
        name = pending.pop()
        if name in observed:
            continue
        contents = _small_file(HERE / name)
        total += len(contents)
        if len(observed) >= MAX_HELPERS or total > MAX_HELPER_BYTES:
            raise ValueError("local helper closure exceeds its file or byte limit")
        observed[name] = hashlib.sha256(contents).hexdigest()
        try:
            tree = ast.parse(contents, filename=name)
        except SyntaxError as error:
            raise ValueError("local helper has invalid Python syntax: " + name) from error
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise ValueError("relative local helper imports are unsupported")
                modules = [node.module] if node.module else []
            else:
                continue
            for module in modules:
                candidate = module.split(".", 1)[0] + ".py"
                if (HERE / candidate).exists() and candidate not in observed:
                    pending.append(candidate)
    identities = hash_artifacts(HERE, sorted(observed))
    if any(item["sha256"] != observed[item["path"]] for item in identities):
        raise ValueError("local helper changed while its imports were inspected")
    return identities + hash_artifacts(HERE, ["p01_toolchain.lock.json"])
