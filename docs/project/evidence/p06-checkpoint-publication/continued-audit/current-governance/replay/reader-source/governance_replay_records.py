#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reconcile recorded governance identities without inspecting recorded host paths."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import PurePosixPath
import re


SCOPE = "project-governance-unittest-only"
TOOLS = ("python", "python3", "cmake", "gcc", "g++", "ar", "ranlib",
         "make", "git", "tclsh", "readelf")
PROBES = {"c_preprocessor", "elf32_link", "cmake_build", "cxx17_threads",
          "ubsan_runtime", "ubsan_rejects_overflow", "fifo", "nofollow"}
MAX_ENVIRONMENT_BYTES = 1024**2
MAX_RECORD_BYTES = 32 * 1024**2
MAX_LOG_BYTES = 128 * 1024**2
MAX_TOOL_BYTES = 512 * 1024**2
MAX_SOURCE_BYTES = 1024**3
MAX_SOURCE_FILES = 32_768
MAX_GIT_BYTES = 4 * 1024**2
MAX_GITLINKS = 32
_PYTHON_PROBE = """import importlib.util, json, platform, site, sys, sysconfig
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


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields),
             label + " has missing or unexpected fields")
    return value


def _string(value, label, *, maximum=MAX_RECORD_BYTES, empty=False):
    _require(type(value) is str and (empty or bool(value)), label + " must be text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError(label + " is not valid UTF-8 text") from error
    _require(size <= maximum, label + " exceeds its text limit")
    return value


def _integer(value, label, *, minimum=0, maximum=MAX_RECORD_BYTES):
    _require(type(value) is int and minimum <= value <= maximum,
             label + " must be an integer in range")
    return value


def _digest(value, label, length=64):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value),
             label + " must be a lowercase hexadecimal digest")
    return value


def _path(value, label):
    _string(value, label, maximum=4096)
    path = PurePosixPath(value)
    _require(path.is_absolute() and str(path) == value and not value.startswith("//")
             and ".." not in path.parts
             and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value),
             label + " must be an exact absolute POSIX path")
    return path


def _relative(value, label):
    _string(value, label, maximum=4096)
    parts = value.split("/")
    _require(not value.startswith("/") and "\\" not in value and ":" not in value
             and len(parts) <= 128
             and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
             and all(part.lower() not in ("", ".", "..", ".git")
                     and len(part.encode("utf-8")) <= 255 for part in parts),
             label + " is an unsafe source-relative path")
    return value


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("record contains a non-JSON value") from error


def _same(left, right, label):
    _require(_canonical(left) == _canonical(right), label + " does not match")


def _parse_json(raw, label):
    def pairs(values):
        result = {}
        for key, value in values:
            _require(key not in result, label + " has a duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(label + " contains a nonfinite JSON number: " + value)

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(label + " is not strict JSON: " + str(error)) from error


def _timestamp(value, label):
    _string(value, label, maximum=64)
    _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00", value),
             label + " must be a producer UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(label + " is an invalid timestamp") from error
    _require(parsed.utcoffset() == timedelta(0), label + " is not UTC")
    return parsed


def _outside(path, source, label):
    _require(not path.is_relative_to(source) and not source.is_relative_to(path),
             label + " must be outside the recorded source checkout")


def _identity(value, label, *, prepared=False, version=False):
    path_key = "path" if prepared else "requested_path"
    fields = {path_key, "resolved_path", "sha256", "size_bytes"}
    if version:
        fields.add("version")
    _object(value, fields, label)
    _path(value[path_key], label + "." + path_key)
    _path(value["resolved_path"], label + ".resolved_path")
    _digest(value["sha256"], label + ".sha256")
    _integer(value["size_bytes"], label + ".size_bytes", maximum=MAX_TOOL_BYTES)
    if version:
        _string(value["version"], label + ".version", maximum=2 * MAX_ENVIRONMENT_BYTES)
    return {"requested_path": value[path_key], "resolved_path": value["resolved_path"],
            "sha256": value["sha256"], "size_bytes": value["size_bytes"]}


def _payload(identity):
    return {key: identity[key] for key in ("resolved_path", "sha256", "size_bytes")}


def _source(value, root, revision):
    _object(value, {"root", "head", "tree", "clean", "status_porcelain", "submodules",
                    "gitlinks", "tracked_count", "tracked_sha256", "index_sha256",
                    "worktree_sha256", "tracked_bytes", "mismatch_count", "mismatches", "git"},
            "source identity")
    _require(value["root"] == str(root) and value["head"] == revision,
             "source root or revision does not match the selected run")
    _digest(value["tree"], "source tree", len(revision))
    _require(value["clean"] is True and value["status_porcelain"] == "",
             "source is not recorded clean")
    _integer(value["tracked_count"], "source tracked count", minimum=1, maximum=MAX_SOURCE_FILES)
    _integer(value["tracked_bytes"], "source tracked bytes", maximum=MAX_SOURCE_BYTES)
    _integer(value["mismatch_count"], "source mismatch count", maximum=0)
    _same(value["mismatches"], [], "source mismatches")
    for key in ("tracked_sha256", "index_sha256", "worktree_sha256"):
        _digest(value[key], "source " + key)
    _require(value["tracked_sha256"] == value["index_sha256"] == value["worktree_sha256"],
             "recorded HEAD, index and worktree inventories disagree")
    _identity(value["git"], "source Git")
    submodules = _string(value["submodules"], "submodule status", maximum=MAX_GIT_BYTES, empty=True)
    _require(not submodules or submodules.endswith("\n"), "submodule status lacks its final newline")
    observations = {}
    for line in submodules.splitlines():
        match = re.fullmatch(r"([- ])([0-9a-f]{40}|[0-9a-f]{64}) ([^\s()]+)(?: \([^\r\n]*\))?", line)
        _require(match is not None and len(observations) < MAX_GITLINKS,
                 "submodule status is malformed, dirty or oversized")
        status, oid, name = match.groups()
        _relative(name, "submodule path")
        _require(name not in observations, "duplicate submodule status")
        observations[name] = {"path": name, "oid": oid, "status": status}
    links = value["gitlinks"]
    _require(type(links) is list and len(links) <= MAX_GITLINKS, "invalid gitlink list")
    names = []
    for link in links:
        _object(link, {"path", "oid", "status", "pinned_oid"}, "gitlink")
        name = _relative(link["path"], "gitlink path")
        _digest(link["pinned_oid"], "gitlink pin", len(revision))
        _require(name in observations and link == {**observations[name], "pinned_oid": link["pinned_oid"]}
                 and link["oid"] == link["pinned_oid"], "gitlink disagrees with clean submodule status")
        names.append(name)
    _require(names == sorted(set(names)), "gitlinks are not uniquely sorted")
    _require(len(links) <= value["tracked_count"], "gitlinks exceed tracked source count")
    for name in observations.keys() - set(names):
        _require(any(name.startswith(link["path"] + "/") and link["status"] == " " for link in links),
                 "recursive submodule status has no initialized tracked parent")


def _clean_environment(interpreter, output):
    path = ":".join(dict.fromkeys((str(PurePosixPath(interpreter).parent), "/usr/bin", "/bin")))
    return {"PATH": path, "HOME": str(output / "home"), "TMPDIR": str(output / "tmp"),
            "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}


def _python(value, interpreter, output):
    _object(value, {"executable", "base_executable", "prefix", "base_prefix", "version",
                    "version_info", "implementation", "platform", "machine", "byteorder",
                    "libc", "gil_enabled", "user_site_enabled", "pip_present"}, "Python probe")
    _path(value["base_executable"], "Python base executable")
    _path(value["base_prefix"], "Python base prefix")
    _require(value["executable"] == interpreter and value["prefix"] == str(output / "venv")
             and value["prefix"] != value["base_prefix"], "Python probe is not the prepared venv")
    version = _string(value["version"], "Python version", maximum=4096)
    info = value["version_info"]
    _require(type(info) is list and len(info) == 3, "invalid Python version tuple")
    for number in info:
        _integer(number, "Python version component", maximum=9999)
    match = re.match(r"(\d+)\.(\d+)\.(\d+)(?:\D|$)", version)
    _require(info[:2] == [3, 12] and match is not None and list(map(int, match.groups())) == info,
             "governance requires a consistent Python 3.12 version")
    _require(value["implementation"] == "cpython" and value["platform"] == "linux"
             and type(value["machine"]) is str and value["machine"].lower() in ("x86_64", "amd64")
             and value["byteorder"] == "little", "Python probe is not Linux x86-64 CPython")
    libc = value["libc"]
    _require(type(libc) is list and len(libc) == 2 and libc[0] == "glibc", "Python probe is not glibc")
    _string(libc[1], "glibc version", maximum=4096, empty=True)
    _require(value["gil_enabled"] is True and value["user_site_enabled"] is False
             and value["pip_present"] is False, "Python probe is not isolated and GIL-enabled")


def _commands(report, output, tools, bootstrap):
    interpreter = report["interpreter"]
    source, build = str(output / "probe-source"), str(output / "probe-build")
    paths = {name: identity["requested_path"] for name, identity in tools.items()}
    expected = [
        ("create-venv", [bootstrap["requested_path"], "-I", "-m", "venv", "--without-pip", str(output / "venv")]),
        ("venv-python", [interpreter, "-c", _PYTHON_PROBE]),
        *(("version-" + name, [paths[name]] + ([] if name == "tclsh" else ["--version"])) for name in TOOLS),
        ("c-preprocessor", [paths["gcc"], "-E", "-dM", "-x", "c", "-DGOVERNANCE_ENV_PROBE=37", "-"]),
        ("elf32-link", [paths["gcc"], "-shared", "-fPIC", "-m32", "-nostdlib", source + "/value.c", "-o", str(output / "probe32.so")]),
        ("elf32-readelf", [paths["readelf"], "-h", str(output / "probe32.so")]),
        ("cmake-configure", [paths["cmake"], "-S", source, "-B", build, "-G", "Unix Makefiles",
                             "-DCMAKE_C_COMPILER=" + paths["gcc"], "-DCMAKE_CXX_COMPILER=" + paths["g++"],
                             "-DCMAKE_AR=" + paths["ar"], "-DCMAKE_RANLIB=" + paths["ranlib"],
                             "-DCMAKE_MAKE_PROGRAM=" + paths["make"]]),
        ("cmake-build", [paths["cmake"], "--build", build, "--parallel", "2"]),
        ("cxx17-ubsan-run", [build + "/probe"]),
        ("ubsan-rejection", [build + "/probe", "overflow"]),
    ]
    commands = report["commands"]
    _require(type(commands) is list and len(commands) == len(expected), "preparation command inventory is incomplete")
    rows = {}
    for row, (name, argv) in zip(commands, expected):
        _object(row, {"name", "argv", "cwd", "environment", "returncode", "timed_out", "stdout", "stderr"},
                "preparation command")
        _require(row["name"] == name and type(row["argv"]) is list and row["argv"] == argv,
                 "preparation command order or argv differs: " + name)
        _require(row["cwd"] == str(output), "preparation command cwd differs: " + name)
        env = (_clean_environment(bootstrap["requested_path"], output) if name == "create-venv"
               else report["environment"])
        _same(row["environment"], env, "preparation command environment: " + name)
        _require(row["timed_out"] is False, "preparation command timed out: " + name)
        _integer(row["returncode"], "preparation returncode", minimum=1 if name == "ubsan-rejection" else 0,
                 maximum=255 if name == "ubsan-rejection" else 0)
        for key in ("stdout", "stderr"):
            # Replacement decoding can expand each original byte to three UTF-8 bytes.
            _string(row[key], "preparation command " + key, maximum=3 * MAX_ENVIRONMENT_BYTES, empty=True)
        rows[name] = row
    _same(_parse_json(rows["venv-python"]["stdout"], "Python probe stdout"), report["python"], "Python probe stdout")
    for name in TOOLS:
        row = rows["version-" + name]
        _require(report["tools"][name]["version"] == (row["stdout"] + row["stderr"]).strip(),
                 "recorded tool version disagrees with its command output: " + name)
    _require("#define GOVERNANCE_ENV_PROBE 37" in rows["c-preprocessor"]["stdout"].splitlines(),
             "preprocessor probe lacks its definition")
    elf = rows["elf32-readelf"]["stdout"]
    _require(re.search(r"Class:\s+ELF32(?:\s|$)", elf)
             and re.search(r"Data:[^\n]*little endian", elf), "readelf output contradicts the ELF32 little-endian probe")
    _require(rows["cxx17-ubsan-run"]["stdout"] == "cxx17-ubsan-ok\n"
             and rows["cxx17-ubsan-run"]["stderr"] == "", "C++17/thread/UBSan probe output differs")
    _require("runtime error: signed integer overflow" in rows["ubsan-rejection"]["stderr"],
             "UBSan rejection lacks the required diagnostic")


def _environment(report, source_root):
    _object(report, {"schema_version", "status", "source_root", "output_dir", "interpreter",
                     "started_at", "finished_at", "environment", "tools", "probes", "commands",
                     "error", "bootstrap_python", "cmake_selection", "python"}, "environment preparation")
    _integer(report["schema_version"], "environment schema", minimum=1, maximum=1)
    _require(report["status"] == "ready" and report["error"] is None, "environment preparation did not finish ready")
    _require(report["source_root"] == str(source_root), "environment source root differs")
    output = _path(report["output_dir"], "environment output")
    _require(re.fullmatch(r"/[A-Za-z0-9_./+()\-]+", str(output)), "environment output is not a safe literal path")
    _outside(output, source_root, "environment output")
    interpreter = str(output / "venv/bin/python3")
    _require(report["interpreter"] == interpreter, "environment selects an unexpected interpreter")
    _same(report["environment"], _clean_environment(interpreter, output), "prepared environment")
    _object(report["probes"], PROBES, "preparation probes")
    _require(all(value is True for value in report["probes"].values()), "preparation has an unsuccessful probe")
    _object(report["tools"], TOOLS, "prepared tools")
    tools = {name: _identity(report["tools"][name], "prepared " + name, prepared=True, version=True) for name in TOOLS}
    for name, identity in tools.items():
        selected = PurePosixPath(identity["requested_path"])
        _require(selected.name == name and str(selected.parent) in (str(output / "venv/bin"), "/usr/bin", "/bin"),
                 "prepared tool is outside the restricted PATH: " + name)
    _require(tools["python3"]["requested_path"] == interpreter
             and tools["python"]["requested_path"] == str(output / "venv/bin/python"), "Python aliases are not private venv paths")
    _same(_payload(tools["python"]), _payload(tools["python3"]), "Python alias identities")
    bootstrap = _identity(report["bootstrap_python"], "bootstrap Python", prepared=True)
    selection = report["cmake_selection"]
    _require(type(selection) is dict and selection.get("resolution") in ("native", "python-package"),
             "invalid CMake resolution")
    fields = {"requested", "native", "resolution"}
    if selection["resolution"] == "python-package":
        fields.add("package_version")
        _string(selection.get("package_version"), "CMake package version", maximum=4096)
    _object(selection, fields, "CMake selection")
    cmake = {name: _identity(selection[name], "selected CMake " + name, prepared=True) for name in ("requested", "native")}
    _require(cmake["native"]["requested_path"] == cmake["native"]["resolved_path"]
             and tools["cmake"]["requested_path"] == str(output / "venv/bin/cmake"), "native CMake path or alias differs")
    _same(_payload(cmake["native"]), _payload(tools["cmake"]), "native CMake identity")
    if selection["resolution"] == "native":
        _same(_payload(cmake["requested"]), _payload(cmake["native"]), "requested native CMake identity")
    else:
        _require(cmake["requested"]["resolved_path"] != cmake["native"]["resolved_path"],
                 "CMake launcher and native executable share one path")
    version = re.match(r"cmake version (\d+)\.(\d+)\.(\d+)(?:$|\s|[-.])", report["tools"]["cmake"]["version"])
    _require(version is not None and (3, 21, 0) <= tuple(map(int, version.groups())) < (3, 26, 0),
             "CMake version is outside governance's 3.21 through 3.25 range")
    _python(report["python"], interpreter, output)
    for name in ("python", "python3"):
        _require(report["tools"][name]["version"] == "Python " + report["python"]["version"].split()[0],
                 "Python alias version differs from the interpreter probe")
    by_resolved, by_requested = {}, {}
    for identity in [bootstrap, *tools.values(), *cmake.values()]:
        resolved = identity["resolved_path"]
        if resolved in by_resolved:
            _same(_payload(identity), by_resolved[resolved], "shared resolved tool identity")
        by_resolved[resolved] = _payload(identity)
        requested = identity["requested_path"]
        if requested in by_requested:
            _same(_payload(identity), by_requested[requested], "shared requested tool identity")
        by_requested[requested] = _payload(identity)
    for path in by_requested.keys() & by_resolved.keys():
        _same(by_requested[path], by_resolved[path], "requested/resolved tool identity")
    _commands(report, output, tools, bootstrap)
    return output, tools, cmake


def validate_records(started: dict, summary: dict, environment: dict, *, revision: str,
                     environment_bytes: bytes) -> dict:
    """Validate receipt consistency only; provenance and actual source inventories are external."""
    _require(type(revision) is str and len(revision) in (40, 64), "selected revision must be a full Git object ID")
    _digest(revision, "selected revision", len(revision))
    _require(type(environment_bytes) is bytes and 0 < len(environment_bytes) <= MAX_ENVIRONMENT_BYTES,
             "preparation receipt bytes are missing or oversized")
    _same(_parse_json(environment_bytes, "preparation receipt"), environment, "preparation receipt raw JSON")
    base_fields = {"schema_version", "scope", "status", "started_at", "governance_passed",
                   "execution_completed", "source_root", "discovery", "command",
                   "source_before", "interpreter_before", "environment_before"}
    _object(started, base_fields, "started receipt")
    _object(summary, base_fields | {"errors", "execution", "source_after", "interpreter_after",
                                  "environment_after", "source_stable", "interpreter_stable",
                                  "environment_stable", "finished_at", "log", "event_bytes"}, "summary receipt")
    for record, label in ((started, "started"), (summary, "summary")):
        _integer(record["schema_version"], label + " schema", minimum=1, maximum=1)
        _require(record["scope"] == SCOPE, label + " scope differs")
        _same(record["discovery"], {"start_directory": "ci/project", "pattern": "test_*.py"}, label + " discovery")
    _require(started["status"] == "started" and started["governance_passed"] is False
             and started["execution_completed"] is False, "started receipt has a completion claim")
    _require(summary["status"] == "completed" and summary["governance_passed"] is True
             and summary["execution_completed"] is True, "summary is not a completed governance pass")
    _same(summary["errors"], [], "summary errors")
    _require(type(summary["execution"]) is dict and summary["execution"].get("strict_success") is True
             and summary["execution"].get("execution_completed") is True,
             "execution is not recorded strictly successful")
    for name in ("source_root", "started_at", "command", "source_before", "interpreter_before", "environment_before"):
        _same(started[name], summary[name], "started/summary " + name)
    for name in ("source", "interpreter", "environment"):
        _require(summary[name + "_stable"] is True, name + " is not recorded stable")
        _same(summary[name + "_before"], summary[name + "_after"], name + " before/after identity")
    source_root = _path(started["source_root"], "source root")
    output, tools, cmake = _environment(environment, source_root)
    prep_start = _timestamp(environment["started_at"], "preparation start")
    prep_finish = _timestamp(environment["finished_at"], "preparation finish")
    run_start = _timestamp(started["started_at"], "run start")
    run_finish = _timestamp(summary["finished_at"], "run finish")
    _require(prep_start <= prep_finish <= run_start <= run_finish, "recorded preparation/run timestamps are inconsistent")
    command = started["command"]
    _require(type(command) is list and len(command) == 6, "strict runner command is incomplete")
    run_output = _path(command[3], "run output")
    _outside(run_output, source_root, "run output")
    _require(command == [environment["interpreter"], str(source_root / "ci/project/governance_run.py"),
                         "--output-dir", str(run_output), "--environment-receipt", str(output / "environment.json")],
             "strict runner command does not join the source and preparation paths")
    prepared_files = [output / "environment.json"]
    for identity in [*tools.values(), *cmake.values()]:
        prepared_files.extend(PurePosixPath(identity[key]) for key in ("requested_path", "resolved_path"))
    # These remain live inputs; disposable preparation probes need not remain on disk.
    _require(all(not path.is_relative_to(run_output) and not run_output.is_relative_to(path)
                 for path in prepared_files), "run output overlaps a prepared input")
    _source(summary["source_before"], source_root, revision)
    _same(summary["source_before"]["git"], tools["git"], "source/prepared Git identity")
    interpreter = summary["interpreter_before"]
    _object(interpreter, {"executable", "version", "implementation", "platform", "prefix", "base_prefix", "path"},
            "interpreter identity")
    _identity(interpreter["executable"], "executing interpreter")
    _same(interpreter["executable"], tools["python3"], "executing/prepared Python identity")
    expected_interpreter = {"executable": tools["python3"], "implementation": "CPython",
                            "path": environment["environment"]["PATH"],
                            **{key: environment["python"][key] for key in ("version", "platform", "prefix", "base_prefix")}}
    _same(interpreter, expected_interpreter, "interpreter/probe identity")
    receipt_sha256 = hashlib.sha256(environment_bytes).hexdigest()
    expected_environment = {"receipt_path": str(output / "environment.json"),
                            "receipt_sha256": receipt_sha256, "receipt_size_bytes": len(environment_bytes),
                            "tools": tools, "cmake_selection": cmake}
    _same(summary["environment_before"], expected_environment, "observed/prepared environment identity")
    _object(summary["log"], {"bytes", "truncated"}, "log receipt")
    _require(summary["log"]["truncated"] is False, "internal log was truncated")
    log_bytes = _integer(summary["log"]["bytes"], "internal log bytes", maximum=MAX_LOG_BYTES)
    event_bytes = _integer(summary["event_bytes"], "event bytes", minimum=1, maximum=MAX_RECORD_BYTES)
    return {"schema_version": 1, "scope": "project-governance-record-reconciliation-only",
            "revision": revision, "source_tree": summary["source_before"]["tree"],
            "source_tracked_count": summary["source_before"]["tracked_count"],
            "source_tracked_sha256": summary["source_before"]["tracked_sha256"],
            "source_tracked_bytes": summary["source_before"]["tracked_bytes"],
            "interpreter_sha256": tools["python3"]["sha256"],
            "environment_sha256": receipt_sha256, "environment_size_bytes": len(environment_bytes),
            "started_at": started["started_at"], "finished_at": summary["finished_at"],
            "log_bytes": log_bytes, "event_bytes": event_bytes, "retained_code_executed": False}
