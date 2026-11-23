# SPDX-License-Identifier: Apache-2.0
"""Review a caller-pinned dependency original without executing retained content."""

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat

from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
import p06_dependency_binary as binary
import p06_dependency_contract as contract
import p06_dependency_graph as graph
import p06_dependency_record as recorder
from p06_dependency_sources import validate_manifest, CONTRACT_ID as SOURCE_CONTRACT_ID


SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
DESCRIPTOR_FIELDS = {"path", "sha256", "size_bytes"}
IDENTITY_FIELDS = {"path", "resolved_path", "sha256", "size_bytes"}
PAYLOAD_FIELDS = IDENTITY_FIELDS | {"payload"}
RECORD_FIELDS = {
    "schema_version", "contract_id", "id", "config_sha256", "recorder", "tool_name", "tool", "role",
    "cwd", "requested_arguments", "arguments", "output_path", "output_before", "output_absent_before",
    "output", "inputs_before", "inputs_after", "dependency_file", "dependency_prepass_file", "link_map",
    "children", "started_ns", "finished_ns", "state", "outcome", "reason", "failures", "process_started",
    "exit_code", "environment",
}
CHILD_FIELDS = {"stage", "argv", "started_ns", "finished_ns", "pid", "process_group",
                "process_started", "exit_code"}
COMMAND_FIELDS = {"id", "argv", "cwd", "environment", "timeout_seconds", "log", "process_started",
                  "outcome", "exit_code", "reason", "duration_seconds", "log_size_bytes",
                  "log_sha256", "peak_rss_bytes", "cleanup_complete", "limitations"}
REPORT_FIELDS = {
    "schema_version", "contract_id", "dependency_contract_sha256", "expected_revision", "state",
    "outcome", "reason", "failures", "paths", "preparation", "helper_sources", "environment", "budget",
    "source_manifest", "source_plan", "tools", "tool_config", "commands", "records", "compile_database",
    "cmake_configuration", "generated_inputs", "generated_sources", "products", "archives", "external_archives",
    "maps", "staged_files", "retained_files", "stability_checks", "source_checkout_before", "source_checkout_after",
    "fresh_dependency_build_passed", *contract.FALSE_CLAIMS,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, names, label):
    require(type(value) is dict and set(value) == set(names), label + " fields differ")


def absolute(value, cwd=None):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_./+-]+", value), "unsafe producer path")
    path = PurePosixPath(value)
    if not path.is_absolute():
        require(cwd is not None, "producer path must be absolute")
        path = PurePosixPath(cwd) / path
    parts = []
    for part in path.parts[1:]:
        if part == "..":
            require(parts, "producer path escapes its root")
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/" + "/".join(parts)


def relative(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_./+()\-]+", value)
            and not value.startswith("/") and all(part not in ("", ".", "..") for part in value.split("/")),
            "unsafe retained path")
    return value


def decode(data):
    require(type(data) is bytes and len(data) <= contract.MAX_RECEIPT_BYTES, "JSON exceeds its byte bound")

    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite JSON constant: " + value)

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("invalid bounded JSON") from error


def identity(value, *, payload=False):
    fields(value, PAYLOAD_FIELDS if payload else IDENTITY_FIELDS, "file identity")
    require(absolute(value["path"]) == value["path"]
            and absolute(value["resolved_path"]) == value["resolved_path"], "noncanonical file identity")
    require(type(value["sha256"]) is str and SHA256.fullmatch(value["sha256"]), "invalid file digest")
    require(type(value["size_bytes"]) is int and 0 <= value["size_bytes"] <= contract.MAX_FILE_BYTES,
            "file exceeds its byte bound")
    if payload:
        require(value["payload"] == value["sha256"] + ".bin", "content-addressed payload name differs")
    return value


def descriptor(value, read_bytes):
    fields(value, DESCRIPTOR_FIELDS, "retained descriptor")
    name = relative(value["path"])
    require(type(value["sha256"]) is str and SHA256.fullmatch(value["sha256"])
            and type(value["size_bytes"]) is int and 0 <= value["size_bytes"] <= contract.MAX_FILE_BYTES,
            "invalid retained descriptor")
    data = read_bytes(name)
    require(type(data) is bytes and len(data) == value["size_bytes"]
            and hashlib.sha256(data).hexdigest() == value["sha256"], "retained bytes differ: " + name)
    return data


def payload(value, read_bytes):
    identity(value, payload=True)
    return descriptor({"path": "payloads/" + value["payload"], "sha256": value["sha256"],
                       "size_bytes": value["size_bytes"]}, read_bytes)


def _arguments(value):
    require(type(value) is list and 0 < len(value) <= recorder.MAX_ARGUMENTS
            and all(type(word) is str and word and "\x00" not in word and "\n" not in word
                    and "\r" not in word for word in value), "invalid command argument list")
    require(sum(len(word.encode()) for word in value) <= recorder.MAX_ARGUMENT_BYTES,
            "command argument bytes exceed their bound")
    return value


def _launcher(document, tool, role, *, compiler_launcher=False):
    words = [document["tools"]["python3"]["path"], document["paths"]["source"]
             + "/ci/project/p06_dependency_record.py", "--config",
             document["paths"]["output"] + "/tool-config.json", "--config-sha256",
             document["tool_config"]["sha256"], "--tool", tool, "--role", role]
    if compiler_launcher:
        words.append("--compiler-launcher")
    return [*words, "--"]


def _one_option(arguments, option):
    require(arguments.count(option) == 1, "command needs exactly one " + option)
    index = arguments.index(option)
    require(index + 1 < len(arguments), "command option lacks its operand")
    return arguments[index + 1]


def _normal_compile(arguments, cwd):
    words = recorder.without_dependency_flags(arguments)
    result = []
    previous = None
    for word in words:
        if previous in ("-o", "-I", "-isystem", "-iquote"):
            result.append(absolute(word, cwd))
        elif word.startswith("-I") and len(word) > 2:
            result.append("-I" + absolute(word[2:], cwd))
        elif not word.startswith("-") and word.endswith((".c", ".cpp")):
            result.append(absolute(word, cwd))
        else:
            result.append(word)
        previous = word
    return result


def _validate_record(record, config, config_sha256, read_bytes, expected_recorder):
    fields(record, RECORD_FIELDS, "tool execution receipt")
    require(type(record["schema_version"]) is int and record["schema_version"] == 1
            and record["contract_id"] == recorder.CONTRACT_ID, "tool receipt version differs")
    require(record["config_sha256"] == config_sha256 and record["recorder"] == expected_recorder,
            "tool receipt configuration or trusted recorder identity differs")
    role, tool = record["role"], record["tool_name"]
    require(role in recorder.ROLES and tool in recorder.TOOLS
            and ((role in ("compile", "link") and tool in ("gcc", "g++"))
                 or (role == "archive" and tool == "ar") or (role == "index" and tool == "ranlib")),
            "tool receipt role differs")
    require(record["tool"] == config["tools"][tool], "tool receipt selected a different executable")
    identity(record["tool"])
    cwd, output = absolute(record["cwd"]), absolute(record["output_path"])
    owned = tuple(PurePosixPath(config["roots"][name]) for name in ("sources", "build"))
    require(cwd == record["cwd"] and output == record["output_path"]
            and any(PurePosixPath(cwd).is_relative_to(root) for root in owned)
            and any(PurePosixPath(output).is_relative_to(root) for root in owned), "tool receipt escaped owned roots")
    require(record["id"] == contract.digest({"role": role, "output": output}), "tool receipt identity differs")
    require(record["state"] == "finished" and record["outcome"] == "pass" and record["reason"] is None
            and record["failures"] == [] and record["process_started"] is True
            and type(record["exit_code"]) is int and record["exit_code"] == 0, "tool receipt is not a successful execution")
    require(type(record["started_ns"]) is int and type(record["finished_ns"]) is int
            and 0 < record["started_ns"] <= record["finished_ns"], "tool receipt timing differs")
    require(type(record["environment"]) is dict and set(record["environment"]) ==
            {"PATH", "CCACHE_DISABLE", "OBJCACHE", *recorder.INJECTION_ENVIRONMENT}
            and record["environment"]["CCACHE_DISABLE"] == "1"
            and record["environment"]["OBJCACHE"] == ""
            and all(record["environment"][name] is None for name in recorder.INJECTION_ENVIRONMENT),
            "tool receipt used an uncontrolled input environment")
    requested = _arguments(record["requested_arguments"])
    actual = _arguments(record["arguments"])
    require(record["output"] is not None and record["output"]["path"] == output
            and record["output"]["resolved_path"] == output, "tool output path differs")
    payload(record["output"], read_bytes)
    require(record["output"]["size_bytes"] > 0, "tool output is empty")
    if role == "index":
        require(record["output_absent_before"] is False and record["output_before"] is not None
                and record["output_before"]["path"] == output, "index lacks its prior archive identity")
        payload(record["output_before"], read_bytes)
    else:
        require(record["output_absent_before"] is True and record["output_before"] is None,
                "tool output was not freshly produced")
    for key in ("inputs_before", "inputs_after"):
        require(type(record[key]) is list and 0 < len(record[key]) <= recorder.MAX_INPUTS,
                "tool input inventory is empty or oversized")
        require(len({item.get("path") for item in record[key] if type(item) is dict}) == len(record[key]),
                "tool input inventory contains duplicates")
        for item in record[key]:
            payload(item, read_bytes)
    if role != "index":
        require(record["inputs_before"] == record["inputs_after"], "tool inputs changed during execution")
    else:
        require(record["inputs_before"] == [record["output_before"]]
                and record["inputs_after"] == [record["output"]], "archive indexing join differs")
    stages = ["dependencies", "tool"] if role == "compile" else ["tool"]
    require(type(record["children"]) is list and len(record["children"]) == len(stages),
            "tool execution lacks its actual child inventory")
    previous = record["started_ns"]
    for child, stage in zip(record["children"], stages):
        fields(child, CHILD_FIELDS, "tool child")
        require(child["stage"] == stage and child["process_started"] is True
                and type(child["exit_code"]) is int and child["exit_code"] == 0
                and type(child["pid"]) is int and child["pid"] > 0
                and type(child["process_group"]) is int and child["process_group"] > 0
                and type(child["started_ns"]) is int and type(child["finished_ns"]) is int
                and previous <= child["started_ns"] <= child["finished_ns"] <= record["finished_ns"],
                "tool child was not observed successfully in order")
        _arguments(child["argv"])
        require(child["argv"][0] == config["tools"][tool]["path"], "child executed a different tool")
        previous = child["finished_ns"]
    require(record["children"][-1]["argv"] == [config["tools"][tool]["path"], *actual],
            "actual tool argv differs from the receipt")
    require(len({child["process_group"] for child in record["children"]}) == 1,
            "tool children changed their observed supervisor process group")
    if role == "compile":
        require(record["dependency_file"] is not None and record["dependency_prepass_file"] is not None
                and record["link_map"] is None, "compile dependency observations are absent")
        dep, before = record["dependency_file"], record["dependency_prepass_file"]
        require(before["path"] == output + ".p06-before.d", "prepass output path differs")
        require(actual == [*recorder.without_dependency_flags(requested), "-MD", "-MF", dep["path"], "-MT", output],
                "actual compilation changed its observed recipe")
        require(record["children"][0]["argv"] == [config["tools"][tool]["path"],
                *recorder._prepass(requested, before["path"], output)], "dependency prepass command differs")
        for item in (dep, before):
            selected = recorder.dependency_paths(payload(item, read_bytes), target=Path(output), cwd=Path(cwd))
            require(list(map(str, selected)) == [item["path"] for item in record["inputs_before"]],
                    "included-input closure differs from actual compiler dependency observations")
        require(absolute(_one_option(requested, "-o"), cwd) == output and requested.count("-c") == 1,
                "compile command output differs")
    else:
        require(actual == requested and record["dependency_file"] is None and record["dependency_prepass_file"] is None,
                "noncompile command changed or invents dependency observations")
        if role == "link":
            require(record["link_map"] is not None and "-shared" in actual and "-c" not in actual
                    and absolute(_one_option(actual, "-o"), cwd) == output, "shared link recipe differs")
            payload(record["link_map"], read_bytes)
            map_flags = [word for word in actual if word.startswith(("-Wl,-Map,", "-Wl,-Map="))]
            require(len(map_flags) == 1 and absolute(map_flags[0][9:], cwd) == record["link_map"]["path"],
                    "link map is not the actual link output")
        else:
            require(record["link_map"] is None, "archive operation invents a linker map")
            if role == "index":
                require(len(requested) == 1 and absolute(requested[0], cwd) == output,
                        "archive indexing command differs")
    return record


class PacketReader:
    """Open only bounded regular files below a caller-selected packet root."""

    def __init__(self, root):
        self.root = Path(root).absolute()
        require(self.root.resolve(strict=True) == self.root
                and all(not path.is_symlink() for path in (self.root, *self.root.parents)),
                "packet root must be canonical without symlinks")

    def __call__(self, name):
        parts = relative(name).split("/")
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor_fd = None
        try:
            for part in parts[:-1]:
                next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            before = os.fstat(descriptor_fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and before.st_size <= contract.MAX_FILE_BYTES, "packet payload is not a bounded regular file")
            chunks, total = [], 0
            while True:
                chunk = os.read(descriptor_fd, min(1024 * 1024, contract.MAX_FILE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                require(total <= contract.MAX_FILE_BYTES, "packet payload exceeds its bound")
            after = os.fstat(descriptor_fd)
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    and total == before.st_size, "packet payload changed while read")
            return b"".join(chunks)
        finally:
            if descriptor_fd is not None:
                os.close(descriptor_fd)
            os.close(directory)


def _verify_compile_inputs(document, record, source_files):
    source_root = PurePosixPath(document["paths"]["sources"])
    project_roots = [PurePosixPath(document["paths"][name]) for name in ("source", "workspace")]
    for item in record["inputs_before"]:
        path, resolved = (PurePosixPath(item[name]) for name in ("path", "resolved_path"))
        if path.is_relative_to(source_root):
            name = path.relative_to(source_root).as_posix()
            require(name in source_files and item["resolved_path"] == item["path"]
                    and item["sha256"] == source_files[name]["sha256"]
                    and item["size_bytes"] == source_files[name]["size_bytes"],
                    "included dependency source differs from the source lock")
        else:
            require(not any(candidate.is_relative_to(root)
                            for candidate in (path, resolved) for root in project_roots),
                    "compiler input contains an unreviewed project file")


def _verify_link_map(document, link, expected_inputs, archives, required_archives, required_loads, read_bytes):
    checked = binary.validate_link_map(payload(link["link_map"], read_bytes).decode("utf-8"),
        cwd=link["cwd"], archives=archives, required_archives=required_archives, required_loads=required_loads)
    loaded = Counter(checked["loads"])
    require(all(loaded[item["path"]] == 1 for item in expected_inputs),
            "link map omits or repeats an observed direct input")
    external = {row["original_path"] for row in document["external_archives"]}
    require(external <= set(archives), "compiler support archive lacks its admitted member inventory")
    project_roots = [PurePosixPath(document["paths"][name]) for name in ("source", "workspace")]
    owned_loads = [name for name in checked["loads"] if name not in external
                   and any(PurePosixPath(name).is_relative_to(root) for root in project_roots)]
    require(sorted(owned_loads) == sorted(item["path"] for item in expected_inputs),
            "link map contains an unplanned source/workspace input")
    return checked


def _verify_compile_graph(document, records, config, read_bytes):
    manifest = validate_manifest(document["source_manifest"])
    source_files = {}
    for source in manifest["sources"]:
        for item in source["files"]:
            name = source["name"] + "/" + item["path"]
            data = descriptor({"path": "sources/" + name, "sha256": item["sha256"],
                               "size_bytes": item["size_bytes"]}, read_bytes)
            require(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == item["oid"],
                    "retained dependency source differs from its locked Git blob")
            source_files[name] = item
    source_body = lambda component, name: read_bytes("sources/" + component + "/" + name)
    plan = graph.source_plan(manifest, source_body)
    require(document["source_plan"] == plan, "declared source plan differs from the immutable recipes")
    roots = config["roots"]
    selected = {str(PurePosixPath(roots["sources"]) / row["source"]): row for row in plan}
    compiles = {}
    output_to_record = {}
    database = decode(descriptor(document["compile_database"], read_bytes))
    require(type(database) is list and len(database) == 97, "CMake compile database population differs")
    database_by_source = {}
    for row in database:
        fields(row, {"directory", "command", "file"}, "CMake compile database row")
        cwd, source = absolute(row["directory"]), absolute(row["file"], row["directory"])
        require(source not in database_by_source and type(row["command"]) is str,
                "CMake compile database duplicates a source")
        words = shlex.split(row["command"], posix=True)
        _arguments(words)
        require(words[0] == config["tools"]["g++"]["path"], "CMake plan selected a different compiler")
        database_by_source[source] = (cwd, words[1:])
    cmake_sources = {source for source, row in selected.items()
                     if row["component"] in ("ramulator", "yaml-cpp", "spdlog")}
    main = str(PurePosixPath(roots["sources"]) / "ramulator/src/main.cpp")
    require(set(database_by_source) == cmake_sources | {main}, "CMake plan contains an unreviewed source")
    for record in records:
        if record["role"] != "compile":
            continue
        requested, cwd = record["requested_arguments"], record["cwd"]
        sources = [absolute(word, cwd) for word in requested
                   if not word.startswith("-") and word.endswith((".c", ".cpp"))]
        require(len(sources) == 1 and sources[0] in selected and sources[0] not in compiles,
                "compile inventory changes or repeats a selected translation unit")
        source, row = sources[0], selected[sources[0]]
        owner, relative_name = row["source"].split("/", 1)
        expected_source = source_files[row["source"]]
        observed_source = next((item for item in record["inputs_before"] if item["path"] == source), None)
        require(observed_source is not None and observed_source["sha256"] == expected_source["sha256"]
                and observed_source["size_bytes"] == expected_source["size_bytes"],
                "compiler source does not match its locked input")
        _verify_compile_inputs(document, record, source_files)
        normalized = _normal_compile(requested, cwd)
        if row["component"] == "softfloat":
            directory = str(PurePosixPath(roots["sources"]) / "softfloat/build/Linux-x86_64-GCC")
            expected = ["-c", "-Werror-implicit-function-declaration", "-DSOFTFLOAT_FAST_INT64",
                        *contract.SOFTFLOAT_OPTIONS, "-I" + directory,
                        "-I" + str(PurePosixPath(roots["sources"]) / "softfloat/source/RISCV"),
                        "-I" + str(PurePosixPath(roots["sources"]) / "softfloat/source/include"),
                        "-O2", "-o", record["output_path"], source]
            require(record["tool_name"] == "gcc" and cwd == directory and normalized == expected
                    and record["output_path"] == directory + "/" + row["archive_member"],
                    "SoftFloat specialization, options or object recipe differs")
        elif row["component"] == "extension":
            expected = ["-std=c++20", "-O3", "-DNDEBUG", "-fPIC"]
            for directory in ("ramulator/src", "spdlog/include", "yaml-cpp/include"):
                expected.extend(("-isystem", str(PurePosixPath(roots["sources"]) / directory)))
            expected.extend(("-c", source, "-o", record["output_path"]))
            require(record["tool_name"] == "g++" and normalized == expected, "extension compiler recipe differs")
        else:
            expected_cwd, planned = database_by_source[source]
            require(record["tool_name"] == "g++" and cwd == expected_cwd
                    and normalized == _normal_compile(planned, expected_cwd),
                    "observed CMake compilation differs from its selected generated plan")
        require(record["output_path"] not in output_to_record, "compile output is repeated")
        compiles[source] = record
        output_to_record[record["output_path"]] = record
    require(set(compiles) == set(selected), "fresh dependency compilation population is incomplete")
    return plan, compiles, output_to_record


def _verify_outer_commands(document, config, read_bytes):
    rows = document["commands"]
    require(type(rows) is list and 5 <= len(rows) <= 7, "outer build command population differs")
    identifiers = [row.get("id") for row in rows if type(row) is dict]
    require(len(identifiers) == len(rows) and len(set(identifiers)) == len(rows)
            and identifiers[:5] == ["softfloat", "ramulator-configure", "ramulator-build",
                                    "extension-compile", "extension-link"], "outer command order differs")
    require(set(identifiers[5:]) <= {"locate-libgcc-a", "locate-libgcc_eh-a"}, "unexpected build subprocess")
    for row in rows:
        fields(row, COMMAND_FIELDS, "outer build command")
        require(row.get("process_started") is True and row.get("outcome") == "pass"
                and type(row.get("exit_code")) is int and row["exit_code"] == 0
                and row.get("reason") is None and row.get("cleanup_complete") is True,
                "outer command did not execute successfully")
        require(type(row["duration_seconds"]) in (int, float) and math.isfinite(row["duration_seconds"])
                and row["duration_seconds"] >= 0 and type(row["peak_rss_bytes"]) is int
                and 0 <= row["peak_rss_bytes"] <= contract.BUDGET["max_rss_bytes"]
                and row["limitations"] == list(PROCESS_LIMITATIONS), "outer command resource observation differs")
        require(row.get("environment") == document["environment"], "outer command environment differs")
        timeout = 120 if row["id"] == "ramulator-configure" else 30 if row["id"].startswith("locate-") else 1800
        require(type(row.get("timeout_seconds")) is int and row["timeout_seconds"] == timeout,
                "outer command timeout differs")
        require(row.get("log") == "logs/" + row["id"] + ".log"
                and type(row.get("log_size_bytes")) is int and 0 <= row["log_size_bytes"] <= contract.BUDGET["max_log_bytes"],
                "outer command log identity differs")
        descriptor({"path": row["log"], "sha256": row["log_sha256"], "size_bytes": row["log_size_bytes"]}, read_bytes)
        _arguments(row["argv"])
        require(absolute(row["cwd"]) == row["cwd"], "outer command cwd differs")
    source_root, build_root = document["paths"]["sources"], document["paths"]["build"]
    compile_words = [*_launcher(document, "gcc", "compile"), "-c", "-Werror-implicit-function-declaration",
                     "-DSOFTFLOAT_FAST_INT64", *contract.SOFTFLOAT_OPTIONS, "-I.", "-I../../source/RISCV",
                     "-I../../source/include", "-O2", "-o"]
    expected_softfloat = [document["tools"]["make"]["path"], "--no-print-directory", "-j2",
        "--output-sync=target", "SPECIALIZE_TYPE=RISCV", "SOFTFLOAT_OPTS=" + " ".join(contract.SOFTFLOAT_OPTIONS),
        "COMPILE_C=" + shlex.join(compile_words) + " $@",
        "MAKELIB=" + shlex.join([*_launcher(document, "ar", "archive"), "crs"]) + " $@", "softfloat.a"]
    require(rows[0]["argv"] == expected_softfloat
            and rows[0]["cwd"] == source_root + "/softfloat/build/Linux-x86_64-GCC",
            "SoftFloat outer recipe or worker bound differs")
    extension = build_root + "/extension"
    expected_compile = [*_launcher(document, "g++", "compile"), "-std=c++20", "-O3", "-DNDEBUG", "-fPIC"]
    for directory in ("ramulator/src", "spdlog/include", "yaml-cpp/include"):
        expected_compile.extend(("-isystem", source_root + "/" + directory))
    expected_compile.extend(("-c", source_root + "/ramulator/src/dram/impl/GDDR6.cpp", "-o", extension + "/gddr6.o"))
    expected_link = [*_launcher(document, "g++", "link"), "-shared", extension + "/gddr6.o",
        "-L" + source_root + "/ramulator", "-lramulator", "-Wl,-Map," + build_root + "/extension.map",
        "-o", extension + "/libramulator-vortex.so"]
    require(rows[3]["argv"] == expected_compile and rows[4]["argv"] == expected_link
            and rows[3]["cwd"] == rows[4]["cwd"] == extension, "extension outer recipe differs")
    configure = rows[1]
    options = document["cmake_configuration"]
    extra = {"CMAKE_CXX_COMPILER", "CMAKE_MAKE_PROGRAM", "CMAKE_AR", "CMAKE_RANLIB", "CMAKE_CXX_COMPILER_LAUNCHER",
             "CMAKE_CXX_LINKER_LAUNCHER", "CMAKE_SHARED_LINKER_FLAGS", "FETCHCONTENT_SOURCE_DIR_SPDLOG",
             "FETCHCONTENT_SOURCE_DIR_ARGPARSE", "FETCHCONTENT_SOURCE_DIR_YAML-CPP"}
    fields(options, set(graph.CMAKE_OPTIONS) | extra, "CMake configuration")
    require(all(options[name] == value for name, value in graph.CMAKE_OPTIONS.items()),
            "CMake source/configuration selection changed")
    require(options["CMAKE_CXX_COMPILER"] == document["tools"]["g++"]["path"]
            and options["CMAKE_MAKE_PROGRAM"] == document["tools"]["make"]["path"]
            and options["CMAKE_SHARED_LINKER_FLAGS"] == "-Wl,-Map," + build_root + "/ramulator.map",
            "CMake compiler or map selection differs")
    for key, role in (("CMAKE_CXX_COMPILER_LAUNCHER", "compile"), ("CMAKE_CXX_LINKER_LAUNCHER", "link")):
        require(options[key] == ";".join(_launcher(document, "g++", role, compiler_launcher=True)),
                "CMake recorder launcher differs")
    for name, role in (("ar", "archive"), ("ranlib", "index")):
        path = "launchers/" + name + ".sh"
        require(options["CMAKE_" + name.upper()] == document["paths"]["output"] + "/" + path,
                "CMake archive tool wrapper differs")
        expected = "#!/bin/sh\nexec " + shlex.join(_launcher(document, name, role)) + ' "$@"\n'
        require(read_bytes(path) == expected.encode("utf-8"), "retained archive wrapper differs")
    for key, name in (("YAML-CPP", "yaml-cpp"), ("SPDLOG", "spdlog"), ("ARGPARSE", "argparse")):
        require(options["FETCHCONTENT_SOURCE_DIR_" + key] == source_root + "/" + name,
                "CMake selected different fetched source inputs")
    expected_configure = [document["tools"]["cmake"]["path"], "-S", source_root + "/ramulator",
                          "-B", build_root + "/ramulator", "-G", "Unix Makefiles",
                          *("-D" + name + "=" + value for name, value in sorted(options.items()))]
    require(configure["argv"] == expected_configure and configure["cwd"] == build_root,
            "CMake configure invocation differs from the reviewed graph")
    expected_build = [document["tools"]["cmake"]["path"], "--build", build_root + "/ramulator",
                      "--target", "ramulator", "--parallel", "2", "--verbose"]
    require(rows[2]["argv"] == expected_build and rows[2]["cwd"] == build_root,
            "Ramulator build changes the target or nested job bound")
    expected_environment = {
        "PATH": ":".join(dict.fromkeys((str(PurePosixPath(document["tools"]["python3"]["path"]).parent),
                                        "/usr/bin", "/bin"))),
        "HOME": build_root + "/home", "TMPDIR": build_root + "/tmp",
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "CCACHE_DISABLE": "1", "OBJCACHE": "", "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1",
    }
    require(document["environment"] == expected_environment and type(expected_environment["PATH"]) is str,
            "build environment changes dependency input selection or worker bounds")
    require(config["roots"]["receipts"] == document["paths"]["output"] + "/records"
            and config["roots"]["payloads"] == document["paths"]["output"] + "/payloads",
            "recorder output roots differ")
    return {row["id"]: row for row in rows}


def _verify_generated_build(document, records, read_bytes):
    """Reconcile generated plans with the fixed configuration and actual children."""
    rows = document["generated_inputs"]
    require(type(rows) is list and 0 < len(rows) <= 10000, "generated CMake input inventory differs")
    names = []
    for row in rows:
        descriptor(row, read_bytes)
        require(row["path"].startswith("build-inputs/"), "generated CMake input escaped its retained root")
        names.append(row["path"])
    require(names == sorted(set(names)) and document["compile_database"] in rows,
            "generated CMake inventory is duplicated, unordered or omits its compile database")
    require(document["compile_database"]["path"] == "build-inputs/compile_commands.json",
            "CMake compile database location differs")
    available = set(names)

    def generated(name):
        name = "build-inputs/" + relative(name)
        require(name in available, "generated CMake input is absent: " + name)
        return read_bytes(name).decode("utf-8", errors="strict")

    cache = {}
    for line in generated("CMakeCache.txt").splitlines():
        if not line or line.startswith(("//", "#")):
            continue
        match = re.fullmatch(r"([^:=]+):([A-Z]+)=(.*)", line)
        require(match is not None and match[1] not in cache, "CMake cache has malformed or duplicate entries")
        cache[match[1]] = match[3]
    for name, value in document["cmake_configuration"].items():
        require(cache.get(name) == value, "generated CMake cache changes configured input: " + name)
    fixed = {"CMAKE_GENERATOR": "Unix Makefiles", "CMAKE_HOME_DIRECTORY": document["paths"]["sources"] + "/ramulator",
             "CMAKE_MAKE_PROGRAM": document["tools"]["make"]["path"], "CMAKE_CXX_FLAGS": "",
             "CMAKE_CXX_FLAGS_RELEASE": "-O3 -DNDEBUG", "CMAKE_SHARED_LINKER_FLAGS_RELEASE": "",
             "CMAKE_STATIC_LINKER_FLAGS": "", "CMAKE_STATIC_LINKER_FLAGS_RELEASE": ""}
    require(all(cache.get(name) == value for name, value in fixed.items()),
            "generated CMake cache changes the selected build environment")
    binary_root = PurePosixPath(document["paths"]["build"]) / "ramulator"
    source_root = document["paths"]["sources"]
    for row in records:
        if row["role"] != "compile" or not PurePosixPath(row["output_path"]).is_relative_to(binary_root):
            continue
        output = PurePosixPath(row["output_path"]).relative_to(binary_root)
        require(output.parts.count("CMakeFiles") == 1, "CMake object target is ambiguous")
        position = output.parts.index("CMakeFiles")
        require(position + 2 < len(output.parts) and output.parts[position + 1].endswith(".dir"),
                "CMake object lacks its selected target")
        target = PurePosixPath(*output.parts[:position + 2])
        definitions = {}
        for line in generated(str(target / "flags.make")).splitlines():
            match = re.fullmatch(r"(CXX_DEFINES|CXX_INCLUDES|CXX_FLAGS) = (.*)", line)
            if match is not None:
                require(match[1] not in definitions, "CMake flags are duplicated")
                definitions[match[1]] = shlex.split(match[2], posix=True)
        fields(definitions, {"CXX_DEFINES", "CXX_INCLUDES", "CXX_FLAGS"}, "generated CMake compiler flags")
        source = [word for word in row["requested_arguments"] if word.endswith(".cpp")]
        require(len(source) == 1, "CMake compiler source is ambiguous")
        expected = [*definitions["CXX_DEFINES"], *definitions["CXX_INCLUDES"], *definitions["CXX_FLAGS"],
                    "-o", row["output_path"], "-c", source[0]]
        require(_normal_compile(expected, row["cwd"]) == _normal_compile(row["requested_arguments"], row["cwd"]),
                "observed CMake compiler differs from its generated target flags")

    generated_commands = []
    for name in names:
        if not name.endswith("/link.txt"):
            continue
        path = PurePosixPath(name.removeprefix("build-inputs/"))
        require(path.parts.count("CMakeFiles") == 1, "generated link target is ambiguous")
        position = path.parts.index("CMakeFiles")
        cwd = str(binary_root.joinpath(*path.parts[:position]))
        for line in read_bytes(name).decode("utf-8", errors="strict").splitlines():
            if line.strip():
                generated_commands.append((cwd, shlex.split(line, posix=True)))
    for row in records:
        if row["role"] == "compile" or row["output_path"].startswith(source_root + "/softfloat/"):
            continue
        if row["output_path"].startswith(document["paths"]["build"] + "/extension/"):
            continue
        prefix = (_launcher(document, "g++", "link", compiler_launcher=True)
                  + [document["tools"]["g++"]["path"]] if row["role"] == "link"
                  else [document["paths"]["output"] + "/launchers/" + row["tool_name"] + ".sh"])
        expected = (row["cwd"], [*prefix, *row["requested_arguments"]])
        require(generated_commands.count(expected) == 1,
                "observed archive/index/link differs from its generated CMake target recipe")


def _verify_source_stability(document, records):
    """Rebuild every generated source-root identity from observed tool outputs."""
    root = PurePosixPath(document["paths"]["sources"])
    generated = {}
    for row in sorted(records, key=lambda item: item["finished_ns"]):
        for field in ("output", "dependency_file", "dependency_prepass_file", "link_map"):
            item = row[field]
            if item is not None and PurePosixPath(item["path"]).is_relative_to(root):
                name = str(PurePosixPath(item["path"]).relative_to(root))
                generated[name] = {"path": name, "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    expected = [generated[name] for name in sorted(generated)]
    require(document["generated_sources"] == expected, "generated dependency source-root inventory differs")
    commands = [row["id"] for row in document["commands"]]
    labels = ["sources-frozen", *(label + command for command in commands for label in ("before-", "after-")),
              "staged-and-verified", "final"]
    rows = document["stability_checks"]
    require(type(rows) is list and [row.get("label") for row in rows if type(row) is dict] == labels,
            "dependency stability boundary population or order differs")
    manifest = document["source_manifest"]
    current = []
    for row in rows:
        fields(row, {"label", "sources", "staged_sha256"}, "dependency stability check")
        if row["label"] == "after-softfloat":
            current = [item for item in expected if item["path"].startswith("softfloat/")]
        if row["label"] == "after-ramulator-build":
            current = expected
        summary = {"contract_id": SOURCE_CONTRACT_ID, "manifest_sha256": contract.digest(manifest),
                   "source_files": manifest["total_files"], "source_bytes": manifest["total_size_bytes"],
                   "generated_files": len(current), "generated_bytes": sum(item["size_bytes"] for item in current),
                   "generated_sha256": contract.digest(current)}
        staged = document["staged_files"] if row["label"] in ("staged-and-verified", "final") else []
        require(row["sources"] == summary and row["staged_sha256"] == contract.digest(staged),
                "dependency stability summary differs from the observed source/output inventory")


def verify_document(document, read_bytes, *, expected_revision):
    """Verify parsed original metadata and retained bytes through an inert reader."""
    require(type(expected_revision) is str and REVISION.fullmatch(expected_revision), "expected source revision is required")
    fields(document, REPORT_FIELDS, "dependency build report")
    require(document.get("contract_id") == contract.CONTRACT_ID
            and type(document.get("schema_version")) is int and document["schema_version"] == 1
            and document.get("dependency_contract_sha256") == contract.contract_hash()
            and document.get("expected_revision") == expected_revision, "dependency receipt identity differs")
    require(document.get("state") == "finished" and document.get("outcome") == "pass"
            and document.get("reason") is None and document.get("failures") == []
            and document.get("fresh_dependency_build_passed") is True,
            "dependency receipt is not a complete successful build")
    require(all(document.get(name) is False for name in contract.FALSE_CLAIMS), "dependency receipt claims qualification")
    require(document.get("budget") == contract.BUDGET, "dependency build budget differs")
    fields(document["paths"], {"source", "workspace", "sources", "build", "output"}, "build paths")
    for value in document["paths"].values():
        require(absolute(value) == value, "build path is not canonical")
    for name in ("sources", "build", "output"):
        require(PurePosixPath(document["paths"][name]).is_relative_to(PurePosixPath(document["paths"]["workspace"]))
                and document["paths"][name] != document["paths"]["workspace"], "owned dependency path escaped the workspace")
    source, workspace = (PurePosixPath(document["paths"][name]) for name in ("source", "workspace"))
    require(not source.is_relative_to(workspace) and not workspace.is_relative_to(source),
            "measurement source overlaps its dependency workspace")
    require(document["paths"]["sources"] == str(workspace / "dependency-sources")
            and document["paths"]["build"] == str(workspace / "dependency-build"),
            "owned dependency source/build root differs")
    owned = [PurePosixPath(document["paths"][name]) for name in ("sources", "build", "output")]
    require(all(not left.is_relative_to(right) and not right.is_relative_to(left)
                for index, left in enumerate(owned) for right in owned[index + 1:]),
            "dependency source/build/evidence roots overlap")
    retained = document.get("retained_files")
    require(type(retained) is list and 0 < len(retained) <= 20000, "retained file inventory is invalid")
    require(len({item.get("path") for item in retained if type(item) is dict}) == len(retained),
            "retained file inventory has duplicates")
    for item in retained:
        fields(item, DESCRIPTOR_FIELDS, "retained inventory item")
        require(type(item["size_bytes"]) is int and 0 <= item["size_bytes"] <= contract.MAX_FILE_BYTES,
                "invalid retained inventory size")
    require(sum(item["size_bytes"] for item in retained) <= contract.MAX_PACKET_BYTES,
            "dependency packet exceeds its total bound")
    require([item["path"] for item in retained] == sorted(item["path"] for item in retained),
            "retained inventory ordering differs")
    for item in retained:
        descriptor(item, read_bytes)
    inventory = {row["path"]: row for row in retained}
    original_reader = read_bytes

    def read_bytes(name):
        require(name in inventory, "referenced payload is outside the retained inventory: " + str(name))
        return descriptor(inventory[name], original_reader)

    require(document["tool_config"]["path"] == "tool-config.json", "tool configuration location differs")
    config_data = descriptor(document["tool_config"], read_bytes)
    config = decode(config_data)
    fields(config, {"schema_version", "contract_id", "contract_sha256", "roots", "tools"}, "tool recorder configuration")
    require(type(config["schema_version"]) is int and config["schema_version"] == 1
            and config["contract_id"] == recorder.CONTRACT_ID and config["contract_sha256"] == contract.contract_hash(),
            "tool recorder configuration identity differs")
    fields(config["roots"], recorder.ROOT_NAMES, "recorder roots")
    fields(config["tools"], recorder.TOOLS, "recorder tools")
    fields(document["tools"], {*recorder.TOOLS, "cmake", "make", "python3"}, "build tools")
    for item in document["tools"].values():
        identity(item)
    for name, value in config["roots"].items():
        require(absolute(value) == value, "recorder root is not canonical")
    for name in recorder.TOOLS:
        identity(config["tools"][name])
        require(document["tools"][name] == config["tools"][name], "build and recorder tools differ")
    require(config["roots"]["sources"] == document["paths"]["sources"]
            and config["roots"]["build"] == document["paths"]["build"], "recorder and build roots differ")
    config_sha256 = hashlib.sha256(config_data).hexdigest()
    commands = _verify_outer_commands(document, config, read_bytes)
    preparation = decode(descriptor(document["preparation"], read_bytes))
    require(preparation.get("contract_id") == "p06-dependency-preparation-v1"
            and preparation.get("outcome") == "pass" and preparation.get("reason") is None
            and preparation.get("dependency_cache_used") is False
            and preparation.get("expected_revision") == expected_revision
            and preparation.get("dependency_contract_sha256") == contract.contract_hash(),
            "build lacks matching fresh dependency preparation")
    before = decode(descriptor(document["source_checkout_before"], read_bytes))
    after = decode(descriptor(document["source_checkout_after"], read_bytes))
    require(before == after and before.get("revision") == expected_revision
            and before.get("dirty") is False and before.get("blockers") == [],
            "measurement checkout identity changed or was not clean")
    helpers = document["helper_sources"]
    require(type(helpers) is list and helpers, "helper source inventory is absent")
    helper_names = []
    for helper in helpers:
        fields(helper, DESCRIPTOR_FIELDS, "helper source")
        require(relative(helper["path"]).startswith("ci/project/") and helper["path"].endswith(".py"),
                "helper source path differs")
        descriptor(dict(helper, path="helpers/" + helper["path"]), read_bytes)
        helper_names.append(helper["path"])
    require(helper_names == sorted(set(helper_names)), "helper source inventory is duplicated or unordered")
    helper = next((row for row in helpers if row["path"] == "ci/project/p06_dependency_record.py"), None)
    require(helper is not None, "trusted recorder source was not frozen")
    helper_body = descriptor({"path": "helpers/" + helper["path"], "sha256": helper["sha256"],
                              "size_bytes": helper["size_bytes"]}, read_bytes)
    recorder_path = str(PurePosixPath(document["paths"]["source"]) / helper["path"])
    expected_recorder = {"path": recorder_path, "resolved_path": recorder_path,
                         "sha256": hashlib.sha256(helper_body).hexdigest(), "size_bytes": len(helper_body)}
    require(type(document["records"]) is list and 0 < len(document["records"]) <= contract.MAX_RECORDS,
            "tool record inventory is empty or oversized")
    records = [_validate_record(decode(descriptor(row, read_bytes)), config, config_sha256,
                                read_bytes, expected_recorder) for row in document["records"]]
    require([row["path"] for row in document["records"]] == sorted(row["path"] for row in document["records"])
            and all(row["environment"]["PATH"] == document["environment"]["PATH"] for row in records),
            "tool receipt ordering or selected PATH differs")
    require(len({row["id"] for row in records}) == len(records), "tool record identity is duplicated")
    require(Counter(row["role"] for row in records) == {"compile": 406, "archive": 3, "index": 2, "link": 2},
            "tool execution graph is incomplete or contains extra operations")
    require(all(row["path"] == "records/" + record["id"] + ".json"
                for row, record in zip(document["records"], records)), "tool receipt filename identity differs")
    plan, compiles, outputs = _verify_compile_graph(document, records, config, read_bytes)
    _verify_generated_build(document, records, read_bytes)
    archive_results, archive_by_path = {}, {}
    require(type(document["archives"]) is list and len(document["archives"]) == 3,
            "dependency archive population differs")
    for row in document["archives"]:
        fields(row, {"name", "original_path", "descriptor", "members"}, "archive record")
        name, path = row["name"], absolute(row["original_path"])
        require(name in ("softfloat", "yaml-cpp", "spdlog") and name not in archive_results,
                "dependency archive name differs")
        expected_path = (config["roots"]["sources"] + "/softfloat/build/Linux-x86_64-GCC/softfloat.a"
                         if name == "softfloat" else config["roots"]["build"] + "/ramulator/_deps/"
                         + name + "-build/lib" + name + ".a")
        require(path == row["original_path"] == expected_path, "dependency archive output location differs")
        sources = [item for item in plan if item["component"] == name]
        expected_members = []
        expected_objects = []
        for item in sources:
            compile_record = compiles[str(PurePosixPath(config["roots"]["sources"]) / item["source"])]
            expected_members.append({"name": item["archive_member"],
                                     "sha256": compile_record["output"]["sha256"],
                                     "size_bytes": compile_record["output"]["size_bytes"]})
            expected_objects.append(compile_record)
        actual = binary.validate_archive(descriptor(row["descriptor"], read_bytes), expected_members)
        require(row["members"] == actual["members"], "declared archive members differ")
        creates = [record for record in records if record["role"] == "archive" and record["output_path"] == path]
        require(len(creates) == 1, "archive lacks its fresh creator")
        create = creates[0]
        expected_operation = "crs" if name == "softfloat" else "qc"
        args = create["requested_arguments"]
        require(args[0] == expected_operation and absolute(args[1], create["cwd"]) == path
                and [absolute(word, create["cwd"]) for word in args[2:]]
                    == [record["output_path"] for record in expected_objects], "archive creation object order differs")
        require(create["inputs_before"] == [record["output"] for record in expected_objects]
                and all(record["finished_ns"] <= create["started_ns"] for record in expected_objects),
                "archive does not consume its completed compiler outputs")
        binary.validate_archive(payload(create["output"], read_bytes), expected_members)
        indexes = [record for record in records if record["role"] == "index" and record["output_path"] == path]
        if name == "softfloat":
            require(not indexes, "SoftFloat archive has an unexpected indexing operation")
            final = create
        else:
            require(len(indexes) == 1 and indexes[0]["output_before"] == create["output"]
                    and create["finished_ns"] <= indexes[0]["started_ns"], "archive indexing prerequisite differs")
            final = indexes[0]
        require((row["descriptor"]["sha256"], row["descriptor"]["size_bytes"])
                == (final["output"]["sha256"], final["output"]["size_bytes"]), "retained archive differs from its producer")
        archive_results[name] = {"path": path, "members": actual["members"], "output": final["output"],
                                 "finished_ns": final["finished_ns"]}
        archive_by_path[path] = actual["members"]
    require(type(document["external_archives"]) is list and len(document["external_archives"]) <= 2,
            "external archive inventory exceeds its selected scope")
    require(len({row.get("name") for row in document["external_archives"] if type(row) is dict})
            == len(document["external_archives"]), "external archive names are duplicated")
    for external in document["external_archives"]:
        fields(external, {"name", "original_path", "descriptor", "members", "tool_resolution_command_id"},
               "external archive")
        name, path = external["name"], absolute(external["original_path"])
        require(name in ("libgcc.a", "libgcc_eh.a") and path not in archive_by_path,
                "external archive selection differs")
        row = commands.get(external["tool_resolution_command_id"])
        require(row is not None and row["argv"] == [document["tools"]["g++"]["path"], "-print-file-name=" + name],
                "external archive lacks its observed tool resolution")
        resolved = read_bytes(row["log"]).decode("utf-8").strip()
        require(absolute(resolved) == path, "external archive differs from the compiler-selected path")
        parsed = binary.parse_archive(descriptor(external["descriptor"], read_bytes))
        require(parsed["members"] == external["members"], "external archive members differ")
        archive_by_path[path] = parsed["members"]
    require(set(commands) - {"softfloat", "ramulator-configure", "ramulator-build", "extension-compile", "extension-link"}
            == {row["tool_resolution_command_id"] for row in document["external_archives"]},
            "compiler support resolution inventory differs from its selected archives")
    require(set(document["products"]) == set(contract.PRODUCTS), "selected product population differs")
    for product in document["products"].values():
        fields(product, {"original_path", "staged_path", "sha256", "size_bytes", "payload"}, "selected product")
        require(product["payload"] == "payloads/" + product["sha256"] + ".bin", "selected product payload name differs")
        descriptor({"path": product["payload"], "sha256": product["sha256"], "size_bytes": product["size_bytes"]}, read_bytes)
    links = [row for row in records if row["role"] == "link"]
    link_results = {}
    for name in ("ramulator", "extension"):
        product = document["products"][name]
        expected_path = (config["roots"]["sources"] + "/ramulator/libramulator.so" if name == "ramulator"
                         else config["roots"]["build"] + "/extension/libramulator-vortex.so")
        require(product["original_path"] == expected_path, "shared dependency output location differs")
        selected_links = [row for row in links if row["output_path"] == product["original_path"]]
        require(len(selected_links) == 1, "selected shared product lacks its successful linker")
        link = selected_links[0]
        require((product["sha256"], product["size_bytes"], product["payload"])
                == (link["output"]["sha256"], link["output"]["size_bytes"], "payloads/" + link["output"]["payload"]),
                "shared product differs from its observed link")
        if name == "ramulator":
            required = [archive_results[key]["path"] for key in ("yaml-cpp", "spdlog")]
            expected_inputs = [record["output"] for source, record in compiles.items()
                               if next(row for row in plan if str(PurePosixPath(config["roots"]["sources"]) / row["source"]) == source)["component"] == "ramulator"]
            expected_inputs += [archive_results[key]["output"] for key in ("yaml-cpp", "spdlog")]
            completed = [record["finished_ns"] for record in compiles.values()
                         if record["output"] in expected_inputs]
            completed += [archive_results[key]["finished_ns"] for key in ("yaml-cpp", "spdlog")]
            loads = []
        else:
            required = []
            extension = next(row for row in plan if row["component"] == "extension")
            expected_inputs = [compiles[str(PurePosixPath(config["roots"]["sources"]) / extension["source"])]["output"],
                               link_results["ramulator"]["output"]]
            completed = [compiles[str(PurePosixPath(config["roots"]["sources"]) / extension["source"])]["finished_ns"],
                         link_results["ramulator"]["finished_ns"]]
            loads = [document["products"]["ramulator"]["original_path"]]
        require(Counter(contract.digest(row) for row in link["inputs_before"])
                == Counter(contract.digest(row) for row in expected_inputs), "link consumes different dependency objects or archives")
        require(all(finished <= link["started_ns"] for finished in completed),
                "dependency link precedes a completed prerequisite")
        require(link["link_map"]["path"] == config["roots"]["build"] + "/" + name + ".map",
                "dependency link map location differs")
        map_result = _verify_link_map(document, link, expected_inputs, archive_by_path, required, loads, read_bytes)
        maps = [row for row in document["maps"] if row.get("name") == name]
        require(len(maps) == 1 and set(maps[0]) == {"name", "cwd", "descriptor", "verification"}
                and maps[0]["cwd"] == link["cwd"] and maps[0]["verification"] == map_result
                and descriptor(maps[0]["descriptor"], read_bytes) == payload(link["link_map"], read_bytes),
                "declared linker map differs from its observed link")
        link_results[name] = {"output": link["output"], "map": map_result, "record_id": link["id"],
                              "finished_ns": link["finished_ns"]}
    require(type(document["maps"]) is list and len(document["maps"]) == 2,
            "dependency linker map population differs")
    softfloat = document["products"]["softfloat"]
    require(softfloat["original_path"] == archive_results["softfloat"]["path"]
            and all(softfloat[key] == archive_results["softfloat"]["output"][key]
                    for key in ("sha256", "size_bytes"))
            and softfloat["payload"] == "payloads/" + archive_results["softfloat"]["output"]["payload"],
            "staged SoftFloat product differs from its archive")
    expected_staged = []
    for source in document["source_manifest"]["sources"]:
        if source["name"] in ("yaml-cpp", "spdlog", "argparse"):
            prefix = PurePosixPath(document["paths"]["source"]) / contract.PINS[source["name"]]["path"]
            expected_staged.extend({"path": str(prefix / item["path"]), "sha256": item["sha256"],
                                    "size_bytes": item["size_bytes"]} for item in source["files"])
    for name, product in document["products"].items():
        require(product["staged_path"] == str(PurePosixPath(document["paths"]["source"]) / contract.PRODUCTS[name]),
                "selected product was staged at a different measurement path")
        expected_staged.append({"path": product["staged_path"], "sha256": product["sha256"], "size_bytes": product["size_bytes"]})
    require(document["staged_files"] == sorted(expected_staged, key=lambda item: item["path"]),
            "staged source/product inventory differs from the complete locked selection")
    _verify_source_stability(document, records)
    return {"contract_id": contract.CONTRACT_ID, "dependency_contract_sha256": contract.contract_hash(),
            "expected_revision": expected_revision, "source_manifest_sha256": contract.digest(document["source_manifest"]),
            "translation_units": dict(contract.TRANSLATION_UNITS), "tool_execution_records": len(records),
            "archives": archive_results, "links": link_results, "products": document["products"],
            "fresh_dependency_build_passed": True, **dict.fromkeys(contract.FALSE_CLAIMS, False)}


def load_receipt(path, expected_sha256, expected_revision):
    path = Path(path).absolute()
    require(type(expected_sha256) is str and SHA256.fullmatch(expected_sha256), "caller-pinned receipt digest is required")
    reader = PacketReader(path.parent)
    data = reader(path.name)
    require(hashlib.sha256(data).hexdigest() == expected_sha256, "dependency receipt digest differs from the caller pin")
    document = decode(data)
    result = verify_document(document, reader, expected_revision=expected_revision)
    expected_files = {row["path"] for row in document["retained_files"]} | {path.name}
    actual_files = set()
    for directory, directories, files in os.walk(reader.root, followlinks=False):
        for name in directories:
            require(not Path(directory, name).is_symlink(), "packet inventory traverses a symlink")
        for name in files:
            item = Path(directory, name)
            require(not item.is_symlink(), "packet inventory contains a symlink")
            actual_files.add(item.relative_to(reader.root).as_posix())
            require(len(actual_files) <= 20001, "packet inventory exceeds its file bound")
    require(actual_files == expected_files, "packet contains omitted or unlisted retained files")
    require(reader(path.name) == data, "dependency receipt changed during review")
    result["receipt_sha256"] = expected_sha256
    return document, result
