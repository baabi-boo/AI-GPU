#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Observe selected dependency tool children and retain their inert inputs/outputs."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True

from baseline_packet_io import load_json_bytes
import p06_dependency_contract as contract


CONTRACT_ID = "p06-dependency-tool-recorder-v1"
MAX_ARGUMENT_BYTES = 256 * 1024
MAX_ARGUMENTS = 4096
MAX_DEPFILE_BYTES = 4 * 1024**2
MAX_INPUTS = 4096
TOOLS = ("gcc", "g++", "ar", "ranlib")
ROLES = ("compile", "link", "archive", "index")
ROOT_NAMES = ("sources", "build", "receipts", "payloads")
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".C", ".S", ".s")
INJECTION_ENVIRONMENT = (
    "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH",
    "LIBRARY_PATH", "COMPILER_PATH", "GCC_EXEC_PREFIX", "LD_PRELOAD", "LD_AUDIT",
    "DEPENDENCIES_OUTPUT", "SUNPRO_DEPENDENCIES",
)
PATH_PATTERN = re.compile(r"/[A-Za-z0-9_.+/-]+")


class RecorderError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RecorderError(message)


def _absolute(value, cwd=None):
    require(isinstance(value, (str, Path)), "path must be text")
    text = str(value)
    require(text and not any(char in text for char in "\x00\n\r"), "invalid path text")
    candidate = Path(text)
    if not candidate.is_absolute():
        require(cwd is not None, "path must be absolute")
        candidate = Path(cwd) / candidate
    candidate = Path(os.path.abspath(candidate))
    require(PATH_PATTERN.fullmatch(str(candidate)) is not None,
            "path contains unsupported characters")
    return candidate


def _no_links(path):
    require(not any(item.is_symlink() for item in (path, *path.parents)),
            "owned path must not traverse a symlink")
    return path


def _regular_bytes(path, maximum=contract.MAX_FILE_BYTES):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum,
                "file is not regular or exceeds its byte bound: " + str(path))
        chunks, size = [], 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= maximum, "file exceeds its byte bound: " + str(path))
        after = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(all(getattr(before, key) == getattr(after, key) == getattr(current, key)
                    for key in fields) and size == before.st_size,
                "file changed while being observed: " + str(path))
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def file_identity(path):
    invoked = _absolute(path)
    resolved = invoked.resolve(strict=True)
    body = _regular_bytes(resolved)
    return {"path": str(invoked), "resolved_path": str(resolved),
            "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def _json_file(path):
    return load_json_bytes(_regular_bytes(path, contract.MAX_RECEIPT_BYTES), str(path))


def _load_config(path, expected_sha256):
    path = _no_links(_absolute(path))
    require(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256),
            "config requires an explicit SHA-256")
    raw = _regular_bytes(path, contract.MAX_RECEIPT_BYTES)
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, "recorder config digest mismatch")
    data = load_json_bytes(raw, "recorder config")
    require(type(data) is dict and set(data) == {
        "schema_version", "contract_id", "contract_sha256", "roots", "tools"},
        "recorder config fields differ")
    require(type(data["schema_version"]) is int and data["schema_version"] == 1
            and data["contract_id"] == CONTRACT_ID
            and data["contract_sha256"] == contract.contract_hash(),
            "recorder config contract differs")
    require(type(data["roots"]) is dict and set(data["roots"]) == set(ROOT_NAMES),
            "recorder root inventory differs")
    roots = {name: _no_links(_absolute(value)) for name, value in data["roots"].items()}
    require(all(root.is_dir() for root in roots.values()), "recorder roots must exist")
    require(all(not left.is_relative_to(right) and not right.is_relative_to(left)
                for i, left in enumerate(roots.values())
                for right in list(roots.values())[i + 1:]), "recorder roots overlap")
    require(type(data["tools"]) is dict and set(data["tools"]) == set(TOOLS),
            "recorder tool inventory differs")
    for name, selected in data["tools"].items():
        require(type(selected) is dict and set(selected) == {
            "path", "resolved_path", "sha256", "size_bytes"}, "tool identity fields differ")
        require(type(selected["size_bytes"]) is int and selected["size_bytes"] > 0
                and type(selected["sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", selected["sha256"]),
                "invalid selected tool identity")
        require(file_identity(selected["path"]) == selected,
                "selected tool identity differs: " + name)
        require(os.access(selected["path"], os.X_OK), "selected tool is not executable")
    return path, raw, data, roots


def _arguments(arguments):
    require(type(arguments) is list and 0 < len(arguments) <= MAX_ARGUMENTS,
            "tool arguments are absent or exceed their count bound")
    require(all(type(item) is str and item and not any(char in item for char in "\x00\n\r")
                for item in arguments), "invalid tool argument")
    require(sum(len(item.encode()) + 1 for item in arguments) <= MAX_ARGUMENT_BYTES,
            "tool arguments exceed their byte bound")
    forbidden = ("-fplugin", "-specs", "--specs", "-wrapper", "-fprofile", "-B", "--sysroot")
    require(not any(item.startswith("@") or item.startswith(forbidden)
                    or item in ("-include", "-imacros", "-Xpreprocessor", "-Xassembler")
                    for item in arguments), "unsupported tool input expansion")
    return list(arguments)


def _option(arguments, name):
    indices = [index for index, value in enumerate(arguments) if value == name]
    require(len(indices) <= 1, "repeated tool option: " + name)
    if not indices:
        return None
    index = indices[0]
    require(index + 1 < len(arguments), "tool option lacks its operand: " + name)
    return arguments[index + 1]


def _owned(path, roots):
    require(any(path.is_relative_to(roots[name]) for name in ("sources", "build")),
            "output lies outside owned source/build roots")
    _no_links(path)
    require(path.parent.is_dir(), "output parent does not exist")
    return path


def _map_path(arguments, cwd):
    maps = []
    for argument in arguments:
        if argument.startswith("-Wl,"):
            words = argument[4:].split(",")
            for index, word in enumerate(words):
                if word == "-Map":
                    require(index + 1 < len(words), "link map lacks its path")
                    maps.append(_absolute(words[index + 1], cwd))
                elif word.startswith("-Map="):
                    maps.append(_absolute(word[5:], cwd))
    require(len(maps) <= 1, "link has repeated map outputs")
    return maps[0] if maps else None


def _direct_inputs(arguments, cwd, role):
    if role == "archive":
        return [_absolute(value, cwd) for value in arguments[2:]]
    if role == "index":
        return [_absolute(arguments[-1], cwd)]
    excluded = set()
    for index, word in enumerate(arguments):
        if word in ("-o", "-MF", "-MT", "-MQ", "-I", "-isystem", "-iquote", "-L", "-D", "-U"):
            require(index + 1 < len(arguments), "option lacks an operand")
            excluded.add(index + 1)
    inputs = [_absolute(word, cwd) for index, word in enumerate(arguments)
              if index not in excluded and not word.startswith("-")
              and word.endswith((*SOURCE_SUFFIXES, ".o", ".a", ".so"))]
    if role == "link":
        searches, libraries = [], []
        for index, word in enumerate(arguments):
            if word == "-L":
                searches.append(_absolute(arguments[index + 1], cwd))
            elif word.startswith("-L"):
                searches.append(_absolute(word[2:], cwd))
            elif word.startswith("-l") and len(word) > 2:
                libraries.append(word[2:])
        for name in libraries:
            require(re.fullmatch(r"[A-Za-z0-9_.+-]+", name), "unsupported library selection")
            selected = next((directory / ("lib" + name + suffix)
                for directory in searches for suffix in (".so", ".a")
                if (directory / ("lib" + name + suffix)).is_file()), None)
            if selected is not None:
                inputs.append(selected)
    require(len(inputs) == len(set(inputs)), "repeated direct input")
    return inputs


def invocation(tool, role, arguments, cwd, roots):
    require(tool in TOOLS and role in ROLES, "unsupported recorder tool or role")
    require((tool in ("gcc", "g++") and role in ("compile", "link"))
            or (tool == "ar" and role == "archive") or (tool == "ranlib" and role == "index"),
            "selected tool does not match its role")
    arguments = _arguments(arguments)
    depfile = before_depfile = link_map = None
    if role in ("compile", "link"):
        name = _option(arguments, "-o")
        require(name is not None, "compiler needs one explicit output")
        output = _owned(_absolute(name, cwd), roots)
        inputs = _direct_inputs(arguments, cwd, role)
        if role == "compile":
            require(arguments.count("-c") == 1 and len(inputs) == 1
                    and str(inputs[0]).endswith(SOURCE_SUFFIXES) and output.suffix == ".o",
                    "compile must select exactly one source/object pair")
            require(any(inputs[0].is_relative_to(roots[name]) for name in ("sources", "build")),
                    "compile source lies outside owned roots")
            depfile = _owned(_absolute(_option(arguments, "-MF") or str(output) + ".d", cwd), roots)
            before_depfile = _owned(Path(str(output) + ".p06-before.d"), roots)
        else:
            require("-c" not in arguments and "-shared" in arguments and output.suffix == ".so"
                    and inputs and all(path.suffix in (".o", ".a", ".so") for path in inputs),
                    "link must select owned shared-library inputs")
            link_map = _map_path(arguments, cwd)
            require(link_map is not None, "link requires its explicit linker map")
            _owned(link_map, roots)
    elif role == "archive":
        require(len(arguments) >= 3 and arguments[0] in ("crs", "rcs", "qc", "qcs"),
                "archive requires a supported ordinary creation operation")
        output = _owned(_absolute(arguments[1], cwd), roots)
        require(output.suffix == ".a", "archive output suffix differs")
        inputs = _direct_inputs(arguments, cwd, role)
        require(inputs and all(path.suffix == ".o" for path in inputs), "archive inputs must be objects")
    else:
        require(len(arguments) == 1 or (len(arguments) == 2 and arguments[0] == "-D"),
                "unsupported archive indexing arguments")
        output = _owned(_absolute(arguments[-1], cwd), roots)
        require(output.suffix == ".a", "index output must be an archive")
        inputs = [output]
    require(len(inputs) <= MAX_INPUTS, "direct input count exceeds its bound")
    for path in inputs:
        if any(path.is_relative_to(roots[name]) for name in ("sources", "build")):
            _no_links(path)
    return {"output": output, "inputs": inputs, "depfile": depfile,
            "before_depfile": before_depfile, "link_map": link_map}


def dependency_paths(contents, *, target, cwd):
    require(type(contents) is bytes and len(contents) <= MAX_DEPFILE_BYTES,
            "dependency file exceeds its bound")
    text = contents.decode("utf-8", "strict").replace("\\\r\n", " ").replace("\\\n", " ")
    require("\\" not in text and "$" not in text and "#" not in text
            and "\r" not in text, "unsupported dependency-file escaping")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    require(lines and all(line.count(":") == 1 for line in lines), "malformed dependency file")
    first_target, names = lines[0].split(":", 1)
    require(_absolute(first_target.strip(), cwd) == target, "dependency target differs from its object")
    names = names.split()
    require(0 < len(names) <= MAX_INPUTS,
            "dependency input inventory is empty or oversized")
    selected = list(dict.fromkeys(_absolute(name, cwd) for name in names))
    for line in lines[1:]:
        header, empty = line.split(":", 1)
        require(not empty.strip() and _absolute(header.strip(), cwd) in selected,
                "unsupported dependency phony target")
    return selected


def without_dependency_flags(arguments):
    result, index = [], 0
    while index < len(arguments):
        word = arguments[index]
        if word in ("-MF", "-MT", "-MQ"):
            require(index + 1 < len(arguments), "dependency/output option lacks its operand")
            index += 2
        elif word in ("-MD", "-MMD", "-MP"):
            index += 1
        else:
            result.append(word)
            index += 1
    return result


def _prepass(arguments, before_depfile, output):
    selected = without_dependency_flags(arguments)
    result, index = [], 0
    while index < len(selected):
        word = selected[index]
        if word == "-o":
            require(index + 1 < len(selected), "output option lacks its operand")
            index += 2
        elif word == "-c":
            index += 1
        else:
            result.append(word)
            index += 1
    return [*result, "-M", "-MF", str(before_depfile), "-MT", str(output)]


def _write_record(path, record, *, exclusive=False):
    raw = contract.json_bytes(record) + b"\n"
    require(len(raw) <= contract.MAX_RECEIPT_BYTES, "execution receipt exceeds its byte bound")
    destination = path if exclusive else path.with_name(path.name + ".tmp." + str(os.getpid()))
    with destination.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if not exclusive:
        os.replace(destination, path)


def _claim_record(path, record, roots):
    descriptor = os.open(roots["receipts"] / ".records.lock",
                         os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), "receipt lock is not regular")
        require(len(list(roots["receipts"].glob("*.json"))) < contract.MAX_RECORDS,
                "execution receipt count exceeds its bound")
        _write_record(path, record, exclusive=True)
    finally:
        os.close(descriptor)


def _retain(path, roots, *, maximum=contract.MAX_FILE_BYTES):
    invoked = _absolute(path)
    if any(invoked.is_relative_to(roots[name]) for name in ("sources", "build")):
        _no_links(invoked)
    resolved = invoked.resolve(strict=True)
    body = _regular_bytes(resolved, maximum)
    digest = hashlib.sha256(body).hexdigest()
    target = roots["payloads"] / (digest + ".bin")
    lock_path = roots["payloads"] / ".retention.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), "retention lock is not regular")
        if target.exists():
            require(_regular_bytes(target) == body, "retained payload changed")
        else:
            total = sum(item.stat().st_size for item in roots["payloads"].glob("*.bin"))
            require(total + len(body) <= contract.MAX_PACKET_BYTES, "retained payload budget exceeded")
            with target.open("xb") as stream:
                stream.write(body)
    finally:
        os.close(descriptor)
    return {"path": str(invoked), "resolved_path": str(resolved), "sha256": digest,
            "size_bytes": len(body), "payload": target.name}


def run(config_path, expected_sha256, tool, role, arguments, *, compiler_launcher=False, cwd=None):
    config_path, config_bytes, config, roots = _load_config(config_path, expected_sha256)
    cwd = _no_links(_absolute(cwd if cwd is not None else Path.cwd()))
    require(cwd.is_dir() and any(cwd.is_relative_to(roots[name]) for name in ("sources", "build")),
            "tool cwd must be inside an owned source/build root")
    require(type(compiler_launcher) is bool, "compiler-launcher selection must be boolean")
    require(tool in TOOLS and role in ROLES, "unsupported recorder tool or role")
    original = list(arguments)
    if compiler_launcher:
        require(tool in ("gcc", "g++") and original
                and original[0] == config["tools"][tool]["path"],
                "CMake launcher selected an unexpected compiler")
        original = original[1:]
    plan = invocation(tool, role, original, cwd, roots)
    output = plan["output"]
    identifier = contract.digest({"role": role, "output": str(output)})
    record_path = roots["receipts"] / (identifier + ".json")
    record = {"schema_version": 1, "contract_id": CONTRACT_ID, "id": identifier,
        "config_sha256": expected_sha256, "recorder": file_identity(__file__),
        "tool_name": tool, "tool": config["tools"][tool], "role": role,
        "cwd": str(cwd), "requested_arguments": original, "arguments": None,
        "output_path": str(output), "output_absent_before": None, "output_before": None, "output": None,
        "inputs_before": [], "inputs_after": [], "dependency_file": None,
        "dependency_prepass_file": None, "link_map": None, "children": [],
        "started_ns": time.monotonic_ns(), "finished_ns": None, "state": "started",
        "outcome": "fail", "reason": None, "failures": [], "process_started": False,
        "exit_code": None, "environment": {name: os.environ.get(name) for name in (
            "PATH", "CCACHE_DISABLE", "OBJCACHE", *INJECTION_ENVIRONMENT)}}
    _claim_record(record_path, record, roots)

    def fail(error, stage):
        reason = str(error) or "interrupted"
        record["failures"].append({"stage": stage, "reason": reason})
        if record["reason"] is None:
            record["reason"] = reason
        record["outcome"] = "fail"

    def observe(paths):
        return [_retain(path, roots) for path in paths]

    def child(arguments, stage):
        argv = [config["tools"][tool]["path"], *arguments]
        row = {"stage": stage, "argv": argv, "started_ns": time.monotonic_ns(),
               "finished_ns": None, "pid": None, "process_group": None,
               "process_started": False, "exit_code": None}
        record["children"].append(row)
        process = None
        try:
            _write_record(record_path, record)
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL)
            row.update(pid=process.pid, process_started=True)
            if stage == "tool":
                record["process_started"] = True
            _write_record(record_path, record)
            row["process_group"] = os.getpgid(process.pid)
            require(row["process_group"] == os.getpgrp(), "tool child escaped its supervisor process group")
            _write_record(record_path, record)
            row["exit_code"] = process.wait()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
            fail(error, stage + ("-interruption" if isinstance(error, KeyboardInterrupt) else "-supervision"))
            if process is not None:
                for label, signal in (("terminate", process.terminate), ("kill", process.kill)):
                    try:
                        signal()
                    except (OSError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as cleanup_error:
                        fail(cleanup_error, stage + "-" + label)
                    try:
                        row["exit_code"] = process.wait(timeout=2)
                        break
                    except (OSError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as cleanup_error:
                        fail(cleanup_error, stage + "-" + label + "-wait")
            raise
        finally:
            row["finished_ns"] = time.monotonic_ns()
            record["exit_code"] = row["exit_code"]
            _write_record(record_path, record)
        require(row["exit_code"] == 0, stage + " child failed with exit code " + str(row["exit_code"]))

    try:
        require(not any(name in os.environ for name in INJECTION_ENVIRONMENT),
                "unsupported compiler input environment")
        record["output_absent_before"] = not os.path.lexists(output)
        if not record["output_absent_before"]:
            record["output_before"] = _retain(output, roots)
        for path in (output, plan["depfile"], plan["before_depfile"], plan["link_map"]):
            if path is not None and not (role == "index" and path == output):
                require(not os.path.lexists(path), "pre-existing tool output: " + str(path))
        inputs = plan["inputs"]
        if role == "compile":
            source_before = observe(inputs)
            child(_prepass(original, plan["before_depfile"], output), "dependencies")
            require(observe(inputs) == source_before, "compile source changed during dependency observation")
            record["dependency_prepass_file"] = _retain(plan["before_depfile"], roots, maximum=MAX_DEPFILE_BYTES)
            before_bytes = _regular_bytes(plan["before_depfile"], MAX_DEPFILE_BYTES)
            inputs = dependency_paths(before_bytes, target=output, cwd=cwd)
            require(plan["inputs"][0] in inputs, "dependency closure omits its source")
            record["inputs_before"] = observe(inputs)
            actual = [*without_dependency_flags(original), "-MD", "-MF", str(plan["depfile"]), "-MT", str(output)]
        else:
            record["inputs_before"] = observe(inputs)
            actual = original
        record["arguments"] = actual
        require(file_identity(config["tools"][tool]["path"]) == config["tools"][tool],
                "selected tool changed before invocation")
        child(actual, "tool")
        require(output.is_file() and output.stat().st_size > 0, "successful child lacks a nonempty output")
        record["output"] = _retain(output, roots)
        if role == "compile":
            record["dependency_file"] = _retain(plan["depfile"], roots, maximum=MAX_DEPFILE_BYTES)
            after_paths = dependency_paths(_regular_bytes(plan["depfile"], MAX_DEPFILE_BYTES),
                                           target=output, cwd=cwd)
            require(after_paths == inputs, "included-input set changed during compilation")
        if role == "link":
            record["link_map"] = _retain(plan["link_map"], roots, maximum=contract.MAX_FILE_BYTES)
        record["inputs_after"] = observe(inputs)
        if role != "index":
            require(record["inputs_after"] == record["inputs_before"], "tool input changed during invocation")
        require(file_identity(config["tools"][tool]["path"]) == config["tools"][tool],
                "selected tool changed during invocation")
        require(_regular_bytes(config_path, contract.MAX_RECEIPT_BYTES) == config_bytes,
                "recorder config changed during invocation")
        record["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        fail(error, "execution")
    finally:
        if record["output"] is None and record["output_absent_before"] and record["process_started"]:
            try:
                if output.is_file():
                    record["output"] = _retain(output, roots)
            except (OSError, ValueError, RuntimeError) as error:
                fail(error, "failed-output-retention")
        for label, operation in (
            ("final-tool", lambda: require(file_identity(config["tools"][tool]["path"]) == config["tools"][tool],
                "selected tool changed before finalization")),
            ("final-config", lambda: require(_regular_bytes(config_path, contract.MAX_RECEIPT_BYTES) == config_bytes,
                "recorder config changed before finalization")),
        ):
            try:
                operation()
            except (OSError, ValueError, RuntimeError) as error:
                fail(error, label)
        record.update(state="finished", finished_ns=time.monotonic_ns())
        _write_record(record_path, record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--tool", choices=TOOLS, required=True)
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--compiler-launcher", action="store_true")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    try:
        result = run(args.config, args.config_sha256, args.tool, args.role, arguments,
                     compiler_launcher=args.compiler_launcher)
        if result["outcome"] == "pass":
            return 0
        print("dependency recorder: " + str(result["reason"]), file=sys.stderr)
        code = result["exit_code"]
        return code if type(code) is int and 0 < code < 126 else 1
    except (OSError, ValueError, RuntimeError) as error:
        print("dependency recorder: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
