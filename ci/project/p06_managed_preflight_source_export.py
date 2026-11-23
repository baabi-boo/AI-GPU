#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Derive managed-preflight source expectations from explicitly selected Git objects.

This tool never reads an execution archive or checks out/imports retained code.
It follows the reviewed producer discovery recipe; changed discovery helpers
require a new review. Source membership does not prove compilation or execution.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import subprocess
import sys
import time

import p06_managed_preflight_sources as inventory


CONTRACT_ID = "p06-managed-counter-preflight-source-export-v1"
MAX_BLOB_BYTES = 16 * 1024**2
MAX_TREE_BYTES = 8 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**2
MAX_TREE_ENTRIES = 50000
MAX_GIT_COMMANDS = 25000
COMMAND_TIMEOUT = 30
SOURCE_ROOTS = ("sw/common", "sw/kernel", "sw/runtime", "sim/common", "sim/simx",
                "sim/rtlsim", "hw/rtl", "hw/dpi", "tests/regression/sgemm_tcu")
SOURCE_SUFFIXES = frozenset((".c", ".cc", ".cpp", ".h", ".hpp", ".S", ".s", ".sv",
                             ".v", ".vh", ".vi", ".mk", ".in", ".ld", ".sh", ".py",
                             ".toml", ".inc"))
HEADER_SUFFIXES = frozenset((".h", ".hpp", ".inc", ".tpp"))
DISCOVERY_HELPER_SHA256 = frozenset((
    "24f1eb40dac4469c64379d6afcd0a8271518218e3ca10f445c4335ebc5f0502c",
    "3d58674992289643ac35aee2ec0c4ecd69969a24a8d3ab36029807703aa064c2",
))
DEPENDENCIES = {
    "ramulator": ("third_party/ramulator", "https://github.com/CMU-SAFARI/ramulator2.git"),
    "softfloat": ("third_party/softfloat", "https://github.com/ucb-bar/berkeley-softfloat-3.git"),
}
FETCH_INPUTS = {
    "spdlog": ("https://github.com/gabime/spdlog.git", "v1.11.0"),
    "yaml-cpp": ("https://github.com/jbeder/yaml-cpp.git", "yaml-cpp-0.7.0"),
}
FALSE_CLAIMS = ("qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
                "acceptance_claimed", "phase_acceptance", "performance_acceptance")
LIMITATIONS = [
    "The explicitly supplied full commits select expected Git content; remote origin is not authenticated.",
    "The reviewed discovery recipe is fixed; changed producer/helper bytes require an independently reviewed update.",
    "CMake tag text is checked, but caller-supplied full commits select FetchContent bytes; remote tag resolution is not authenticated.",
    "Only selected source/header inputs are inventoried; this is not a complete dependency compilation closure.",
    "Git object membership and source hashes do not prove source-to-binary compilation, loaded bytes or native execution.",
    "Local repositories are caller-selected inputs; hashes do not defend against malicious concurrent object-store mutation.",
]


class ExportError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ExportError(message)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _revision(value):
    require(type(value) is str and inventory.REVISION.fullmatch(value),
            "an explicit lowercase full Git commit is required")
    return value


def _path(value):
    try:
        return inventory._source_path(value)
    except ValueError as error:
        raise ExportError(str(error)) from error


def _bounded_command(argv, environment, limit, *, timeout=COMMAND_TIMEOUT):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=environment)
    started = time.monotonic()
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = timeout - (time.monotonic() - started)
                require(remaining > 0, "Git object command exceeded its time bound")
                for key, _ in selector.select(min(remaining, 0.25)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = streams[key.data]
                    require(len(target) + len(chunk) <= (limit if key.data == "stdout" else 65536),
                            "Git object command exceeded its output bound")
                    target.extend(chunk)
            process.wait(timeout=max(0.001, timeout - (time.monotonic() - started)))
        require(process.returncode == 0, "Git object command failed: " +
                bytes(streams["stderr"]).decode("utf-8", errors="replace")[:1000])
        return bytes(streams["stdout"])
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ExportError("Git object command failed or timed out") from error
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


class GitObjects:
    """Read only bounded SHA-1 Git objects; ignore checkout bytes and replacements."""

    def __init__(self, path, revision, *, budget=None):
        path = Path(path)
        require(path.is_absolute() and path.is_dir() and path.resolve(strict=True) == path
                and not any(part.is_symlink() for part in (path, *path.parents)),
                "Git repository must be an explicit canonical directory without symlinks")
        self.path, self.revision = path, _revision(revision)
        self.commands = self.bytes_read = 0
        self.budget = {"commands": 0, "bytes": 0} if budget is None else budget
        git = shutil.which("git", path=os.defpath)
        require(git is not None, "Git is unavailable on the system command path")
        self.git = str(Path(git).resolve(strict=True))
        self.environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
        require(self.run(["rev-parse", "--show-object-format"], 32) == b"sha1\n",
                "only SHA-1 Git object repositories are supported")
        require(self.run(["rev-parse", "--verify", revision + "^{commit}"], 64) == (revision + "\n").encode(),
                "selected revision does not identify the exact commit")
        self.tree_id = self.run(["rev-parse", revision + "^{tree}"], 64).decode().strip()
        _revision(self.tree_id)
        self.entries = self._tree()
        self.cache = {}

    def run(self, arguments, limit):
        self.commands += 1
        self.budget["commands"] += 1
        require(self.budget["commands"] <= MAX_GIT_COMMANDS, "Git command budget exceeded")
        return _bounded_command([self.git, "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "protocol.allow=never",
            "-C", str(self.path), *arguments], self.environment, limit)

    def _tree(self):
        raw = self.run(["ls-tree", "-r", "-z", "--full-tree", self.revision], MAX_TREE_BYTES)
        require(raw.endswith(b"\0") and 0 < raw.count(b"\0") <= MAX_TREE_ENTRIES,
                "Git tree is empty, malformed or exceeds its entry bound")
        entries = {}
        for item in raw[:-1].split(b"\0"):
            try:
                metadata, name = item.decode("ascii").split("\t", 1)
                mode, kind, oid = metadata.split(" ")
            except (UnicodeError, ValueError) as error:
                raise ExportError("Git tree entry is not canonical ASCII") from error
            require(0 < len(name) <= inventory.MAX_PATH_BYTES and len(name.split("/")) <= 64
                    and not any(ord(char) < 32 or ord(char) == 127 for char in name)
                    and not name.startswith("/") and "\\" not in name
                    and all(part not in ("", ".", "..", ".git") for part in name.split("/")),
                    "Git tree path is unsafe or exceeds its bound")
            _revision(oid)
            require(name not in entries, "Git tree contains a duplicate path")
            require((kind == "blob" and mode in ("100644", "100755", "120000"))
                    or (kind == "commit" and mode == "160000"), "unsupported Git tree entry")
            entries[name] = {"mode": mode, "kind": kind, "oid": oid}
        return entries

    def blob(self, name):
        _path(name)
        entry = self.entries.get(name)
        require(entry is not None and entry["kind"] == "blob" and entry["mode"] in ("100644", "100755"),
                "selected source is missing or is not a regular Git blob: " + name)
        if name not in self.cache:
            raw_size = self.run(["cat-file", "-s", entry["oid"]], 32)
            require(re.fullmatch(rb"(?:0|[1-9][0-9]*)\n", raw_size), "Git object size is invalid")
            size = int(raw_size)
            require(size <= MAX_BLOB_BYTES and self.budget["bytes"] + size <= MAX_TOTAL_BYTES,
                    "selected source exceeds its Git byte budget")
            body = self.run(["cat-file", "blob", entry["oid"]], max(size, 1))
            require(len(body) == size, "Git blob size changed")
            require(hashlib.sha1(b"blob " + str(size).encode() + b"\0" + body).hexdigest() == entry["oid"],
                    "Git blob bytes differ from their object identity")
            self.bytes_read += size
            self.budget["bytes"] += size
            self.cache[name] = body
        return self.cache[name]


def _under(name, roots):
    return any(name.startswith(root + "/") for root in roots)


def _source_names(source):
    required = inventory.required_source_names()
    helpers = [{"path": name, "sha256": hashlib.sha256(source.blob(name)).hexdigest(),
                "size_bytes": len(source.blob(name))}
               for name in required if name.startswith("ci/project/") and name.endswith(".py")]
    helper_sha = hashlib.sha256(json_bytes(helpers)).hexdigest()
    require(helper_sha in DISCOVERY_HELPER_SHA256,
            "producer discovery/helper bytes differ from the reviewed recipe")
    names = set(required)
    for name in source.entries:
        path = PurePosixPath(name)
        if (_under(name, SOURCE_ROOTS) and (path.name == "Makefile" or path.suffix in SOURCE_SUFFIXES)) \
                or (path.parent == PurePosixPath("tests/runtime") and path.suffix == ".cpp"):
            names.add(name)
    return sorted(names), helper_sha


def _gitlink(source, name):
    path, url = DEPENDENCIES[name]
    entry = source.entries.get(path)
    require(entry is not None and entry["mode"] == "160000" and entry["kind"] == "commit",
            "required dependency gitlink is missing: " + name)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(source.blob(".gitmodules").decode("utf-8"))
        section = parser['submodule "' + path + '"']
        require(section["path"] == path and section["url"] == url,
                "dependency declaration differs from its reviewed repository: " + name)
    except (configparser.Error, KeyError, UnicodeError) as error:
        raise ExportError("invalid dependency declaration: " + name) from error
    return entry["oid"]


def _fetch_declarations(ramulator):
    body = ramulator.blob("CMakeLists.txt").decode("utf-8")
    for name, (url, tag) in FETCH_INPUTS.items():
        blocks = re.findall(r"(?im)^\s*FetchContent_Declare\(\s*" + re.escape(name) + r"\s+([^()]*)\)", body)
        require(len(blocks) == 1 and blocks[0].split() == ["GIT_REPOSITORY", url, "GIT_TAG", tag,
                "SOURCE_DIR", "${CMAKE_SOURCE_DIR}/ext/" + name],
                "Ramulator FetchContent declaration differs: " + name)


def export_inventory(*, source_repository, source_revision, ramulator_repository,
                     softfloat_repository, spdlog_repository, spdlog_revision,
                     yaml_cpp_repository, yaml_cpp_revision):
    """Return a manifest and derivation receipt; no archive or checkout is consulted."""
    source = GitObjects(source_repository, source_revision)
    repos = {"source": source,
        "ramulator": GitObjects(ramulator_repository, _gitlink(source, "ramulator"), budget=source.budget),
        "softfloat": GitObjects(softfloat_repository, _gitlink(source, "softfloat"), budget=source.budget),
        "spdlog": GitObjects(spdlog_repository, spdlog_revision, budget=source.budget),
        "yaml-cpp": GitObjects(yaml_cpp_repository, yaml_cpp_revision, budget=source.budget)}
    _fetch_declarations(repos["ramulator"])
    names, helper_sha = _source_names(source)
    selections = [(name, "source", name) for name in names]
    for key, roots, prefix in (
        ("ramulator", ("src",), "third_party/ramulator/"),
        ("softfloat", ("source/include", "source/RISCV"), "third_party/softfloat/"),
        ("spdlog", ("include",), "third_party/ramulator/ext/spdlog/"),
        ("yaml-cpp", ("include",), "third_party/ramulator/ext/yaml-cpp/"),
    ):
        selected = [name for name in repos[key].entries
                    if _under(name, roots) and PurePosixPath(name).suffix in HEADER_SUFFIXES]
        require(selected, "dependency header inventory is empty: " + key)
        selections.extend((prefix + name, key, name) for name in selected)
    require(len(selections) <= inventory.MAX_SOURCES and len({row[0] for row in selections}) == len(selections),
            "source inventory is too large or contains duplicate output paths")
    rows, provenance = [], []
    for name, key, repository_path in sorted(selections):
        body = repos[key].blob(repository_path)
        entry = repos[key].entries[repository_path]
        descriptor = {"path": _path(name), "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        rows.append(descriptor)
        provenance.append(dict(descriptor, repository=key, repository_path=repository_path,
                               git_blob=entry["oid"], git_mode=entry["mode"]))
    require(sum(repo.bytes_read for repo in repos.values()) <= MAX_TOTAL_BYTES,
            "combined source repositories exceed the Git byte budget")
    manifest = inventory.validate_source_inventory({"schema_version": 1, "contract_id": inventory.CONTRACT_ID,
        "producer_contract_id": inventory.PRODUCER_CONTRACT_ID, "source_revision": source_revision,
        "sources": rows}, expected_revision=source_revision)
    manifest_bytes = json_bytes(manifest)
    require(len(manifest_bytes) <= inventory.MAX_MANIFEST_BYTES, "source manifest exceeds its byte bound")
    repositories = {}
    for name, repo in repos.items():
        record = {"commit": repo.revision, "tree": repo.tree_id}
        if name == "source":
            record["selection"] = "caller-supplied-full-producer-commit"
        elif name in DEPENDENCIES:
            record.update(selection="producer-gitlink", producer_path=DEPENDENCIES[name][0], url=DEPENDENCIES[name][1])
        else:
            record.update(selection="caller-supplied-full-FetchContent-commit", url=FETCH_INPUTS[name][0],
                          declared_tag=FETCH_INPUTS[name][1])
        repositories[name] = record
    receipt = {"schema_version": 1, "contract_id": CONTRACT_ID, "source_revision": source_revision,
        "source_files": len(rows), "source_names_sha256": hashlib.sha256(
            "".join(row["path"] + "\n" for row in rows).encode()).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "discovery_helper_sha256": helper_sha, "repositories": repositories, "sources": provenance,
        "git_commands": sum(repo.commands for repo in repos.values()),
        "git_bytes_read": sum(repo.bytes_read for repo in repos.values()),
        "native_execution": "not_run", "retained_code_executed": False,
        "dependency_compilation_provenance_verified": False, **dict.fromkeys(FALSE_CLAIMS, False),
        "limitations": LIMITATIONS}
    require(len(json_bytes(receipt)) <= 16 * 1024**2, "source derivation receipt exceeds its byte bound")
    return manifest, receipt


def write_outputs(outputs):
    """Create all caller-selected files exclusively before writing any contents."""
    paths, opened = [], []
    try:
        for path, value in outputs:
            path = Path(path).absolute()
            require(path.parent.resolve(strict=True) == path.parent
                    and not any(parent.is_symlink() for parent in path.parents),
                    "output parent must be canonical without symlinks")
            require(path not in paths, "output paths must be distinct")
            paths.append(path)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            opened.append((path, fd, os.fstat(fd), value))
        for _, fd, _, value in opened:
            with os.fdopen(os.dup(fd), "wb") as stream:
                stream.write(json_bytes(value))
                stream.flush()
                os.fsync(stream.fileno())
    except (OSError, ValueError):
        for path, _, original, _ in opened:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino):
                    path.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        for _, fd, _, _ in opened:
            os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-repository", "ramulator-repository", "softfloat-repository", "spdlog-repository",
                 "yaml-cpp-repository"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-revision", "spdlog-revision", "yaml-cpp-revision"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    if (args.output is None) != (args.receipt is None):
        parser.error("--output and --receipt must be supplied together")
    try:
        values = vars(args).copy()
        values.pop("output")
        values.pop("receipt")
        manifest, receipt = export_inventory(**values)
        if args.output is not None:
            write_outputs(((args.output, manifest), (args.receipt, receipt)))
            print(json.dumps({"outcome": "pass", "source_files": receipt["source_files"],
                              "manifest_sha256": receipt["manifest_sha256"], "native_execution": "not_run"}))
        else:
            print(json_bytes({"manifest": manifest, "derivation": receipt}).decode(), end="")
        return 0
    except (ExportError, inventory.SourceInventoryError, OSError, UnicodeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "native_execution": "not_run",
                          **dict.fromkeys(FALSE_CLAIMS, False)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
