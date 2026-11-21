#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit retained P05 source, native origin and clean installation without running it.

Only Git object reads and a SHA-256-pinned, independent P04 provenance auditor
are executed. Production P05 runners, validators, package code and native
binaries are never imported or run. Original absolute paths are recorded names;
all file verification uses the relocated packet and immutable Git objects.
"""

from __future__ import annotations

import argparse
import ast
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
import sys
import tarfile
import types
import zipfile


MIB = 1024 * 1024
JSON_LIMIT = 16 * MIB
FILE_LIMIT = 256 * MIB
TREE_LIMIT = 2 * 1024 * MIB
MAX_FILES = 20000
P04_AUDITOR = "docs/project/evidence/p04-executor/reviews/audit_provenance.py"
P04_AUDITOR_SHA256 = "32f18937591df8e91dd86d6693550748a4d3ed8f1cfd766733d20f0617fa4ab9"
PROFILE = "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
FIXTURE = "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03"
BINDING_SOURCES = tuple(sorted((
    "pyproject.toml", "setup.py", "MANIFEST.in", "python/vortex_ai/__init__.py",
    "python/vortex_ai/_api.py", "python/vortex_ai/_bundle.py", "python/vortex_ai/launch.py",
    "python/native/module.cpp", "python/native/runtime_loader.cpp", "python/native/runtime_loader.h",
    "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h", "sw/runtime/ai/runtime.cpp",
    "sw/runtime/ai/runtime.h", "sw/runtime/ai/mlp_runtime.cpp", "sw/runtime/ai/mlp_runtime.h",
    "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_host.h", "sw/runtime/include/vortex2.h",
    "sw/common/ai_matmul_args.h", "tests/regression/ai_mlp/p04_fixtures.h",
    "tests/regression/ai_mlp/records.h",
)))
P05_SOURCES = {"ci/project/p05_execute.py", "ci/project/p05_execution_records.py",
               "ci/project/p05_installed_check.py", "ci/project/p05_bundle.py", "LICENSE", "python/README.md"}
ROLES = {
    "ramulator": ("lib/libramulator.so", "third_party/ramulator/libramulator.so"),
    "ramulator_extension": ("lib/libramulator-vortex.so", "third_party/ramulator_ext/libramulator-vortex.so"),
    "runtime": ("lib/libvortex.so", "sw/runtime/libvortex.so"),
    "simulator": ("lib/libsimx.so", "sw/runtime/libsimx.so"),
    "backend": ("lib/libvortex-simx.so", "sw/runtime/libvortex-simx.so"),
    "module": ("kernel.vxbin", "tests/regression/ai_mlp/kernel.vxbin"),
}
MATMUL_FAMILIES = ("single-dense_boundaries", "numerical-cross_tile_rounding_positive", "multi-dense_boundaries")
MODEL_FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
DIST = "vortex_ai-0.1.0.dist-info/"
PACKAGE_VERSIONS = {"setuptools": "84.2.1", "wheel": "0.48.0", "packaging": "26.3"}
REPORT_FIELDS = set("""acceptance_claimed backend budget bundle_artifacts bundle_manifest bundle_validation commands
comparison completed_native_and_python_launches contract_id dependencies_before development extracted_sdist_before_build
finished_at format installed_after installed_before installed_request installed_script iterations limitations loaded_helpers
matmul_artifacts_after matmul_artifacts_before matmul_backend_header_macros matmul_binding matmul_case_ids
matmul_compiler_records matmul_qualification_id model_case_ids native_artifacts native_counts native_input native_matmuls
native_qualification_id native_report observations outcome package_source_stage package_tools_after package_tools_before
packages paths phase_complete reason resources_after resources_before retained_native_matmul retained_native_model
retained_sources schema_version selection source_after source_before source_stable started_at state tools_after tools_before
venv_interpreter wheel_inventory""".split())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value, newline=False):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + ("\n" if newline else "")).encode("utf-8")


def same(actual, expected, message):
    require(canonical(actual) == canonical(expected), message)


def decode(raw):
    require(type(raw) is bytes and len(raw) <= JSON_LIMIT, "JSON is absent or oversized")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    def number(token):
        value = float(token)
        require(math.isfinite(value), "nonfinite JSON number")
        return value
    def integer(token):
        require(len(token) <= 64, "oversized JSON integer")
        return int(token)
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_int=integer,
                      parse_float=number, parse_constant=number)


def relative(value):
    require(type(value) is str and value and len(value.encode()) <= 4096
            and "\\" not in value and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value),
            "unsafe relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value
            and all(part not in ("", ".", "..") for part in value.split("/")), "noncanonical relative path")
    return path


def absolute(value):
    require(type(value) is str and value.startswith("/") and value != "/", "expected absolute recorded path")
    relative(value[1:])
    return PurePosixPath(value)


def root_path(value, *, fresh=False):
    path = Path(str(absolute(str(value))))
    require(not any(part.is_symlink() for part in (path, *path.parents)), "root traverses a symlink")
    if fresh:
        require(not os.path.lexists(path) and path.parent.is_dir(), "output must be fresh under an existing directory")
    else:
        require(path.is_dir() and path.resolve(strict=True) == path, "root is not an existing canonical directory")
    return path


def read(root, name, limit=JSON_LIMIT):
    path = Path(root)
    for part in relative(name).parts:
        path /= part
        require(not path.is_symlink(), "retained path traverses a symlink: " + name)
    require(path.resolve(strict=True) == path, "retained path is not canonical: " + name)
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit, "nonregular or oversized retained file: " + name)
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(len(raw) <= limit and len(raw) == before.st_size
            and stamp(before) == stamp(after) == stamp(path.stat(follow_symlinks=False)),
            "retained file changed during read: " + name)
    return raw


def identity(name, raw, size_key="size_bytes"):
    return {"path": name, "sha256": sha(raw), size_key: len(raw)}


def inventory(rows, *, size_key="size_bytes", roles=False, absolute_paths=False, nonempty=True):
    require(type(rows) is list and (rows or not nonempty) and len(rows) <= MAX_FILES, "invalid file inventory")
    result = {}
    total = 0
    for row in rows:
        require(type(row) is dict and set(row) == {"path", "sha256", size_key} | ({"role"} if roles else set()),
                "invalid inventory fields")
        (absolute if absolute_paths else relative)(row["path"])
        require(type(row["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]), "invalid file hash")
        require(type(row[size_key]) is int and 0 <= row[size_key] <= FILE_LIMIT, "invalid file size")
        require(row["path"] not in result, "duplicate inventory path: " + row["path"])
        total += row[size_key]
        require(total <= TREE_LIMIT, "inventory exceeds byte budget")
        result[row["path"]] = row
    return result


def checked(root, row, *, expected=None, limit=FILE_LIMIT):
    inventory([row])
    if expected is not None:
        require(row["path"] == expected, "unexpected descriptor path: " + row["path"])
    raw = read(root, row["path"], limit)
    same(identity(row["path"], raw), row, "retained identity mismatch: " + row["path"])
    return raw


def snapshot(root, report, key, name=None):
    return decode(checked(root, report[key], expected="snapshots/" + (name or key.replace("_", "-")) + ".json", limit=JSON_LIMIT))


def tree(root):
    result, todo, count, size = {}, [Path(root)], 0, 0
    require(todo[0].is_dir() and not todo[0].is_symlink(), "missing retained tree")
    while todo:
        for path in sorted(todo.pop().iterdir()):
            count += 1
            require(count <= MAX_FILES, "retained tree has too many entries")
            mode = path.lstat().st_mode
            require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), "retained tree contains a link or special file")
            if stat.S_ISDIR(mode):
                todo.append(path)
            else:
                name = path.relative_to(root).as_posix()
                raw = read(root, name, FILE_LIMIT)
                size += len(raw)
                require(size <= TREE_LIMIT, "retained tree exceeds byte budget")
                result[name] = identity(name, raw)
    return dict(sorted(result.items()))


class Git:
    def __init__(self, root):
        self.root, self.cache = root, {}

    def git(self, *args):
        require(args and args[0] in ("cat-file", "ls-tree", "rev-parse"), "non-read-only Git request")
        result = subprocess.run(["/usr/bin/git", "--no-optional-locks", "-C", str(self.root), *args],
            env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
        require(len(result.stdout) <= 32 * MIB, "Git metadata output exceeds bound")
        return result.stdout

    def blob(self, revision, name):
        require(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision), "invalid Git revision")
        relative(name)
        key = revision, name
        if key not in self.cache:
            obj = revision + ":" + name
            size = int(self.git("cat-file", "-s", obj))
            require(0 <= size <= JSON_LIMIT and self.git("cat-file", "-t", obj).strip() == b"blob", "Git input is not a bounded blob")
            raw = self.git("cat-file", "blob", obj)
            require(len(raw) == size, "Git blob size differs")
            self.cache[key] = raw
        return self.cache[key]

    def entries(self, revision):
        require(re.fullmatch(r"[0-9a-f]{40}", revision), "invalid Git revision")
        require(self.git("cat-file", "-t", revision).strip() == b"commit", "source object is not an actual Git commit")
        result = {}
        for line in self.git("ls-tree", "-r", "-z", revision).split(b"\0"):
            if line:
                metadata, name = line.split(b"\t", 1)
                mode, kind, object_id = metadata.decode().split()
                name = name.decode("utf-8")
                relative(name)
                require(name not in result, "duplicate Git path")
                result[name] = (mode, kind, object_id)
        require(len(result) <= MAX_FILES, "Git tree exceeds file budget")
        return result


def load_p04(git, revision):
    raw = git.blob(revision, P04_AUDITOR)
    require(sha(raw) == P04_AUDITOR_SHA256, "independent P04 auditor differs from its reviewed hash pin")
    module = types.ModuleType("frozen_p04_provenance")
    exec(compile(raw, P04_AUDITOR + "@" + P04_AUDITOR_SHA256, "exec"), module.__dict__)
    module.read, module.decode = read, decode
    return module


def imported_helpers(git, revision, tracked):
    seen, pending = set(), ["ci/project/p05_execute.py"]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for node in ast.walk(ast.parse(git.blob(revision, name))):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for module in modules:
                path = "ci/project/" + (module or "").replace(".", "/") + ".py"
                if path in tracked and path not in seen:
                    pending.append(path)
    return seen | {"python/vortex_ai/_bundle.py"}


def source_check(root, report, git, native, p04):
    before = snapshot(root, report, "source_before")
    same(before, snapshot(root, report, "source_after"), "P05 before/after source inventories differ")
    checkout = before["checkout"]
    require(checkout["dirty"] is False and checkout["blockers"] == [] and checkout["changed_paths"] == []
            and checkout["untracked_paths"] == [], "recorded P05 checkout was not clean")
    revision = checkout["revision"]
    tracked = git.entries(revision)
    require(git.git("rev-parse", revision + "^{tree}").decode().strip() == checkout["tree"], "P05 tree differs from actual Git commit")
    native_source = snapshot(root / "native", native, "source_before")
    same(checkout, native_source["checkout"], "P05 and original native clean source differ")
    files = inventory(before["files"])
    helpers = inventory(report["loaded_helpers"])
    require(imported_helpers(git, revision, tracked) <= helpers.keys(), "loaded-helper inventory omits imported project code")
    expected = set(inventory(native_source["files"])) | P05_SOURCES | set(BINDING_SOURCES) | set(helpers)
    require(set(files) == expected, "P05 source inventory differs from native inputs plus exact package/helper closure")
    for name, row in inventory(native_source["files"]).items():
        same(files[name], row, "P05 source differs from native source: " + name)
    retained = inventory(report["retained_sources"])
    require(set(retained) == {"artifacts/source/" + name for name in P05_SOURCES | set(BINDING_SOURCES) | set(helpers)},
            "required retained P05 source bodies differ")
    same(tree(root / "artifacts/source"), {name.removeprefix("artifacts/source/"): {
        **row, "path": name.removeprefix("artifacts/source/")} for name, row in retained.items()},
        "retained source tree contains omitted or extra bodies")
    checked_count, external_count = 0, 0
    for name, row in files.items():
        if name in tracked:
            require(tracked[name][0] in ("100644", "100755") and tracked[name][1] == "blob", "source input is not a regular Git blob")
            same(identity(name, git.blob(revision, name)), row, "source identity differs from Git blob: " + name)
            checked_count += 1
        else:
            require(any(kind == "commit" and name.startswith(path + "/") for path, (_, kind, _) in tracked.items()),
                    "source input is outside recorded Git/submodule roots")
            external_count += 1
    for name, row in retained.items():
        original = name.removeprefix("artifacts/source/")
        require(checked(root, row) == git.blob(revision, original), "retained source body differs from Git: " + original)
    for name, row in helpers.items():
        same(row, files[name], "loaded helper differs from source snapshot")
    require(sha(git.blob(revision, "profiles/p02-tfr.json")) == PROFILE
            and sha(git.blob(revision, "ci/project/fixtures/p04_tiny_mlp_v1.json")) == FIXTURE, "frozen profile/fixture differs")
    return before, {"git_source_bodies_verified": checked_count, "submodule_file_identities_only": external_count,
                    "retained_source_bodies_verified": len(retained), "loaded_helpers": list(helpers.values())}


def commands(root, report):
    rows = report["commands"]
    require(type(rows) is list and 0 < len(rows) <= 64, "missing or excessive commands")
    result = {}
    for row in rows:
        name = row["id"]
        require(type(name) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name)
                and name not in result, "invalid or duplicate command")
        require(row["process_started"] is True and type(row["exit_code"]) is int and row["exit_code"] == 0
                and row["cleanup_complete"] is True and row["reason"] is None and row["outcome"] == "pass",
                "command did not actually start, exit successfully and drain: " + name)
        require(type(row["timeout_seconds"]) is int and 0 < row["timeout_seconds"] <= 16 * 1800 + 60
                and type(row["duration_seconds"]) in (int, float)
                and 0 < row["duration_seconds"] <= row["timeout_seconds"] + 10,
                "invalid command duration/timeout")
        require(type(row["peak_rss_bytes"]) is int and 0 <= row["peak_rss_bytes"] <= 4 * 1024**3,
                "command memory budget exceeded")
        require(type(row["argv"]) is list and row["argv"] and all(type(v) is str and v and "\0" not in v for v in row["argv"]),
                "invalid command argument inventory")
        absolute(row["cwd"])
        require(type(row["environment"]) is dict and all(type(k) is str and type(v) is str for k, v in row["environment"].items()),
                "invalid command environment")
        log = checked(root, {"path": row["log"], "sha256": row["log_sha256"], "size_bytes": row["log_size_bytes"]},
                      expected="logs/" + name + ".log", limit=JSON_LIMIT).decode("utf-8")
        allowed = set()
        if name == "installed-matrix":
            allowed = {"P05_MATMUL", "P05_MODEL"}
        elif name in ("package-tools-before", "package-tools-after"):
            allowed = {"P05_PACKAGE_TOOLS"}
        elif report.get("format") in ("fp16", "bf16") and name in {
                "native-" + report["format"] + "-" + family for family in MATMUL_FAMILIES}:
            allowed = {"P03_RESULT", "P03_REJECTIONS"}
        elif name in {"simx-" + variant["format"] + "-" + variant["format"] + "-" + family
                      for variant in report.get("variants", []) for family in MODEL_FAMILIES}:
            allowed = {"P04_RESULT"}
        for line in log.splitlines():
            candidate = re.search(r"\bP0[345]_[A-Za-z0-9_]+(?=\s|$)", line, re.I)
            if candidate:
                marker = candidate[0]
                require(marker in allowed and line.startswith(marker + " "),
                        "failure, malformed or misplaced runtime marker in " + name)
        result[name] = row
    return result


def base_environment(paths, jobs, observed_path, python):
    require(type(observed_path) is str, "missing clean PATH")
    entries = observed_path.split(":")
    require(entries and len(entries) == len(set(entries)), "duplicate or empty PATH entries")
    for entry in entries:
        absolute(entry)
    required = ([paths["host_bin"]] if paths.get("host_bin") else [])
    required += [str(PurePosixPath(python).parent), "/usr/bin", "/bin"]
    same(entries, list(dict.fromkeys(required)), "clean PATH differs from the recorded interpreter and source contract")
    return {"PATH": observed_path, "TMPDIR": paths["work"] + "/tmp", "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "MAKEFLAGS": "-j" + str(jobs), "THREADS": str(jobs), "CMAKE_BUILD_PARALLEL_LEVEL": str(jobs)}


def check_command(row, argv, cwd, environment):
    same(row["argv"], [str(value) for value in argv], "command arguments differ: " + row["id"])
    require(row["cwd"] == str(cwd), "command working directory differs: " + row["id"])
    same(row["environment"], environment, "command environment differs: " + row["id"])


def tools_check(root, report, native, p04):
    tools = snapshot(root, report, "tools_before")
    same(tools, snapshot(root, report, "tools_after"), "before/after tools differ")
    same(tools, snapshot(root / "native", native, "tools_before"), "native/P05 tools differ")
    require(set(tools) == p04.TOOLS, "required SimX tools differ")
    for row in tools.values():
        require(set(row) == {"path", "resolved_path", "sha256", "size_bytes"}, "unexpected tool identity fields")
        absolute(row["path"])
        absolute(row["resolved_path"])
        inventory([{key: row[key] for key in ("path", "sha256", "size_bytes")}], absolute_paths=True)
        require(row["size_bytes"] > 0, "empty tool identity")
    same(report["dependencies_before"], native["dependencies_before"], "P05/native dependencies differ")
    venv = report["venv_interpreter"]
    require(set(venv) == set(tools["python3"]), "invalid copied interpreter identity")
    require(venv["path"] == venv["resolved_path"] == report["paths"]["work"] + "/venv/bin/python", "venv interpreter was not a canonical copy")
    require((venv["sha256"], venv["size_bytes"]) == (tools["python3"]["sha256"], tools["python3"]["size_bytes"]),
            "copied interpreter differs from inventoried Python")
    return tools


def package_tools_check(root, report, rows, tools):
    before = snapshot(root, report, "package_tools_before")
    same(before, snapshot(root, report, "package_tools_after"), "package prerequisites changed")
    for label in ("package-tools-before", "package-tools-after"):
        raw = read(root, rows[label]["log"]).decode("utf-8")
        values = [decode(line[len("P05_PACKAGE_TOOLS "):].encode()) for line in raw.splitlines() if line.startswith("P05_PACKAGE_TOOLS ")]
        require(len(values) == 1, "missing or repeated raw package-tool inventory")
        same(values[0], before, "raw package-tool probe differs from snapshot")
    require(set(before) == {"python_version", "implementation", "executable", "distributions"}, "invalid package-tool fields")
    version = before["python_version"]
    require(type(version) is list and len(version) == 3 and all(type(n) is int and 0 <= n < 1000 for n in version)
            and version[:2] == [3, 12] and before["implementation"] == "CPython", "unsupported Python version")
    require(before["executable"] == tools["python3"]["path"] and set(before["distributions"]) == set(PACKAGE_VERSIONS),
            "package tools use a different interpreter or distribution inventory")
    for name, expected in PACKAGE_VERSIONS.items():
        distribution = before["distributions"][name]
        require(set(distribution) == {"version", "files"} and distribution["version"] == expected, "package prerequisite version differs")
        inventory(distribution["files"], absolute_paths=True)
    return before


def bundle_check(root, report, git, checkout, native_variant):
    raw = checked(root, report["bundle_manifest"], expected="artifacts/bundle/manifest.json", limit=4 * MIB)
    manifest = decode(raw)
    require(canonical(manifest, newline=True) == raw, "bundle manifest is not canonical")
    require(set(manifest) == {"schema_version", "contract_id", "backend", "format", "source_revision", "source_tree",
                             "binding_sources", "binding_source_sha256", "profile_sha256", "fixture_sha256",
                             "qualification_id", "native_binding", "artifacts"}, "bundle manifest fields differ")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and manifest["contract_id"] == "p05-python-bundle-v1" and manifest["backend"] == "simx"
            and manifest["format"] == report["format"] and manifest["source_revision"] == checkout["revision"]
            and manifest["source_tree"] == checkout["tree"] and manifest["profile_sha256"] == PROFILE
            and manifest["fixture_sha256"] == FIXTURE, "bundle scope/source differs")
    sources = inventory(manifest["binding_sources"], size_key="size")
    require(list(sources) == list(BINDING_SOURCES), "bundle does not have the exact ordered 22-source inventory")
    require(sha(canonical(manifest["binding_sources"], newline=True)) == manifest["binding_source_sha256"], "source inventory digest differs")
    for name, row in sources.items():
        same(identity(name, git.blob(checkout["revision"], name), "size"), row, "binding source differs from Git: " + name)
    binding = snapshot(root / "native", native_variant, "binding", "simx-" + report["format"] + "-binding")
    same(manifest["native_binding"], binding, "bundle native envelope differs from original retained P04 binding")
    require(sha(canonical(binding)) == manifest["qualification_id"] == report["native_qualification_id"]
            == native_variant["qualification_id"], "native qualification identity differs")
    original = {**inventory(binding["artifacts"]), **inventory(binding["dependencies"])}
    artifacts = inventory(manifest["artifacts"], size_key="size", roles=True)
    require(len(artifacts) == len(ROLES) and {row["role"] for row in artifacts.values()} == set(ROLES), "six bundle roles differ")
    expected = {"manifest.json": identity("manifest.json", raw)}
    for row in artifacts.values():
        name, origin = ROLES[row["role"]]
        require(row["path"] == name and (row["sha256"], row["size"]) == (original[origin]["sha256"], original[origin]["size_bytes"]),
                "bundle artifact does not match original native identity")
        expected[name] = {"path": name, "sha256": row["sha256"], "size_bytes": row["size"]}
    same(tree(root / "artifacts/bundle"), dict(sorted(expected.items())), "retained six-artifact bundle differs")
    same(inventory(report["bundle_artifacts"]), dict(sorted(expected.items())), "reported bundle inventory differs")
    validation = report["bundle_validation"]
    require(validation["kind"] == "in_process" and validation["function"] == "p05_bundle.create_bundle"
            and validation["state"] == "passed" and validation["format"] == report["format"], "bundle origin descriptor differs")
    paths = report["paths"]
    same({key: validation[key] for key in ("source", "build", "native_output", "destination")},
         {"source": paths["source"], "build": paths["native_build"], "native_output": paths["native_output"],
          "destination": paths["output"] + "/artifacts/bundle"}, "bundle producer paths differ")
    same(validation["producer_source"], identity("ci/project/p05_bundle.py", git.blob(checkout["revision"], "ci/project/p05_bundle.py")),
         "bundle producer source identity differs")
    return manifest, raw


def pin_header(manifest, digest):
    values = {"bundle_sha256": digest, "source_sha256": manifest["binding_source_sha256"],
              **{name: manifest[name] for name in ("backend", "format", "qualification_id", "source_revision")}}
    lines = ["// SPDX-License-Identifier: Apache-2.0", "// Generated from validated build inputs. Do not edit.",
             "#ifndef VORTEX_AI_P05_BUILD_CONFIG_H", "#define VORTEX_AI_P05_BUILD_CONFIG_H", "#include <array>",
             "#include <cstdint>", "namespace vortex_ai_python::build {", "struct Artifact {", "  const char* role;",
             "  const char* path;", "  const char* sha256;", "  std::uint64_t size;", "};"]
    lines += ["inline constexpr char " + key + "[] = " + json.dumps(value) + ";" for key, value in values.items()]
    lines += ["inline constexpr std::array<Artifact, 6> artifacts{{"]
    for row in sorted(manifest["artifacts"], key=lambda value: value["role"]):
        lines.append("  {" + ", ".join([json.dumps(row[key]) for key in ("role", "path", "sha256")] + [str(row["size"]) + "ULL"]) + "},")
    return "\n".join(lines + ["}};", "}  // namespace vortex_ai_python::build", "#endif", ""]).encode()


def archive(raw, kind):
    files, seen, total, top = {}, set(), 0, None
    if kind == "sdist":
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as stream:
            for index, item in enumerate(stream):
                require(index < 1024, "sdist exceeds member budget")
                name = item.name.rstrip("/") if item.isdir() else item.name
                path = relative(name)
                require(name not in seen and (item.isdir() or item.isfile()) and item.sparse is None, "duplicate or linked/special/sparse sdist member")
                seen.add(name)
                top = top or path.parts[0]
                require(path.parts[0] == top, "sdist has multiple roots")
                if item.isdir():
                    continue
                require(len(path.parts) > 1 and 0 <= item.size <= JSON_LIMIT, "invalid sdist file extent")
                total += item.size
                require(total <= 64 * MIB, "sdist expands beyond budget")
                with stream.extractfile(item) as member:
                    data = member.read(item.size + 1)
                require(len(data) == item.size, "sdist member size differs")
                files["/".join(path.parts[1:])] = data
        require(top == "vortex_ai-0.1.0", "sdist root differs")
    else:
        with zipfile.ZipFile(io.BytesIO(raw)) as stream:
            require(0 < len(stream.infolist()) <= 1024, "wheel exceeds member budget")
            for item in stream.infolist():
                name = str(relative(item.filename))
                mode = item.external_attr >> 16
                require(name not in seen and not item.is_dir() and not (item.flag_bits & 1)
                        and (not stat.S_IFMT(mode) or stat.S_ISREG(mode)), "duplicate/encrypted/linked wheel member")
                seen.add(name)
                require(0 <= item.file_size <= FILE_LIMIT, "wheel member is oversized")
                total += item.file_size
                require(total <= 512 * MIB, "wheel expands beyond budget")
                with stream.open(item) as member:
                    data = member.read(item.file_size + 1)
                require(len(data) == item.file_size, "wheel member size differs")
                files[name] = data
    require(files, "empty package archive")
    for name in files:
        require(not any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != "."), "archive file/directory collision")
    return files


def check_record(files):
    record = DIST + "RECORD"
    rows = list(csv.reader(io.StringIO(files[record].decode("utf-8"), newline="")))
    require(len(rows) == len(files) and all(len(row) == 3 for row in rows), "wheel/installed RECORD inventory differs")
    seen = set()
    for name, digest, length in rows:
        relative(name)
        require(name in files and name not in seen, "RECORD has an extra or duplicate member")
        seen.add(name)
        if name == record:
            require(digest == length == "", "RECORD hashes itself")
        else:
            expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).decode().rstrip("=")
            require(digest == expected and length == str(len(files[name])), "RECORD hash/size differs: " + name)


def package_check(root, report, manifest, manifest_raw, git):
    rows = inventory(report["packages"])
    sdists = [name for name in rows if name.startswith("packages/sdist/") and name.endswith(".tar.gz")]
    wheels = [name for name in rows if name.startswith("packages/wheel/") and name.endswith(".whl")]
    require(len(sdists) == len(wheels) == 1 and len(rows) == 2, "package archive inventory differs")
    same(tree(root / "packages"), {name.removeprefix("packages/"): {**row, "path": name.removeprefix("packages/")} for name, row in rows.items()},
         "package directory contains missing or extra archives")
    sdist = archive(checked(root, rows[sdists[0]]), "sdist")
    wheel = archive(checked(root, rows[wheels[0]]), "wheel")
    revision, digest = manifest["source_revision"], sha(manifest_raw)
    require(wheels[0] == "packages/wheel/vortex_ai-0.1.0-1" + digest + "-cp312-cp312-linux_x86_64.whl", "wheel tag lacks full pin or has unsupported ABI/platform")
    require(sdists[0] == "packages/sdist/vortex_ai-0.1.0.tar.gz", "sdist filename differs")
    sources = {name: git.blob(revision, name) for name in (*BINDING_SOURCES, "LICENSE", "python/README.md")}
    stage = inventory(snapshot(root, report, "package_source_stage"))
    same(stage, {name: identity(name, data) for name, data in sorted(sources.items())}, "clean package source stage differs from Git inputs")
    pins = {"manifest.json": manifest_raw, "source_inventory.json": canonical(manifest["binding_sources"], newline=True),
            "p05_build_config.h": pin_header(manifest, digest)}
    expected = set(sources) | {"python/p05_build/" + name for name in pins} | {"PKG-INFO"} | {
        "python/vortex_ai.egg-info/" + name for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "top_level.txt")}
    require(set(sdist) == expected, "sdist does not have the exact reviewed input/pin/metadata inventory")
    for name, data in sources.items():
        require(sdist[name] == data, "sdist source differs from Git input: " + name)
    for name, data in pins.items():
        require(sdist["python/p05_build/" + name] == data == read(root, "artifacts/sdist-pin/" + name), "sdist pin/header bytes differ: " + name)
    same(tree(root / "artifacts/sdist-pin"), {name: identity(name, raw) for name, raw in sorted(pins.items())}, "sdist pin directory has unexpected files")
    same(inventory(snapshot(root, report, "extracted_sdist_before_build")),
         {name: identity(name, data) for name, data in sorted(sdist.items())}, "extracted before-build inventory differs from archive")
    package_sources = {name.removeprefix("python/"): data for name, data in sources.items() if name.startswith("python/vortex_ai/")}
    extension = "vortex_ai/_native.cpython-312-x86_64-linux-gnu.so"
    metadata = {DIST + name for name in ("METADATA", "WHEEL", "RECORD", "top_level.txt", "licenses/LICENSE")}
    require(set(wheel) == set(package_sources) | {extension} | metadata, "wheel payload differs from bound package")
    for name, data in package_sources.items():
        require(wheel[name] == data, "wheel source differs from bound source: " + name)
    require(wheel[DIST + "licenses/LICENSE"] == sources["LICENSE"], "wheel license differs")
    metadata_headers = BytesParser().parsebytes(wheel[DIST + "METADATA"])
    for key, value in (("Name", "vortex-ai"), ("Version", "0.1.0"), ("Requires-Python", "<3.13,>=3.12"), ("License-Expression", "Apache-2.0")):
        require(metadata_headers.get_all(key) == [value], "package metadata differs: " + key)
    require(not metadata_headers.get_all("Requires-Dist"), "unexpected Python runtime dependency")
    wheel_headers = BytesParser().parsebytes(wheel[DIST + "WHEEL"])
    for key, value in (("Wheel-Version", "1.0"), ("Root-Is-Purelib", "false"), ("Tag", "cp312-cp312-linux_x86_64"), ("Build", "1" + digest)):
        require(wheel_headers.get_all(key) == [value], "wheel metadata differs: " + key)
    check_record(wheel)
    same(inventory(snapshot(root, report, "wheel_inventory")), {name: identity(name, data) for name, data in sorted(wheel.items())}, "wheel inventory differs from archive bytes")
    installed = inventory(snapshot(root, report, "installed_before"))
    same(installed, inventory(snapshot(root, report, "installed_after")), "installed package changed during workload")
    same(tree(root / "artifacts/installed"), installed, "retained installed tree differs from before/after inventories")
    require(set(installed) == set(wheel) | {DIST + name for name in ("INSTALLER", "REQUESTED", "direct_url.json")}, "installed distribution file membership differs")
    installed_bytes = {name: read(root / "artifacts/installed", name, FILE_LIMIT) for name in installed}
    for name, data in wheel.items():
        if name != DIST + "RECORD":
            require(installed_bytes[name] == data, "installed bytes differ from wheel: " + name)
    require(installed_bytes[DIST + "INSTALLER"] == b"pip\n" and installed_bytes[DIST + "REQUESTED"] == b"", "unexpected installer metadata")
    direct = decode(installed_bytes[DIST + "direct_url.json"])
    same(direct, {"archive_info": {"hash": "sha256=" + rows[wheels[0]]["sha256"], "hashes": {"sha256": rows[wheels[0]]["sha256"]}},
                  "url": "file://" + report["paths"]["output"] + "/" + wheels[0]}, "installed direct_url does not identify retained offline wheel")
    check_record(installed_bytes)
    require(digest.encode() + b"\0" in wheel[extension]
            and manifest["binding_source_sha256"].encode() + b"\0" in wheel[extension], "compiled extension lacks immutable package pins")
    return {"sdist": rows[sdists[0]], "wheel": rows[wheels[0]], "extension": identity(extension, wheel[extension]),
            "sdist_members": len(sdist), "wheel_members": len(wheel), "installed_members": len(installed),
            "pin_header_sha256": sha(pins["p05_build_config.h"])}, wheel[extension]


def elf(raw, machine, *, shared=False):
    require(len(raw) >= 64 and raw[:7] == b"\x7fELF\x02\x01\x01", "artifact is not little-endian ELF64")
    header = struct.unpack_from("<HHIQQQIHHHHHH", raw, 16)
    kind, observed_machine, version, _, phoff, _, _, ehsize, phsize, phnum, _, _, _ = header
    require(observed_machine == machine and version == 1 and ehsize == 64 and kind in ((3,) if shared else (2, 3)), "ELF machine/type differs")
    require(0 < phnum <= 1024 and phsize == 56 and phoff + phnum * phsize <= len(raw), "ELF program headers exceed file")
    segments = []
    for index in range(phnum):
        row = struct.unpack_from("<IIQQQQQQ", raw, phoff + index * phsize)
        require(row[2] + row[5] <= len(raw), "ELF segment exceeds file")
        segments.append(row)
    dynamic = [row for row in segments if row[0] == 2]
    require(len(dynamic) <= 1 and (dynamic or not shared), "ELF dynamic table differs")
    values = []
    if dynamic:
        segment = dynamic[0]
        require(segment[5] % 16 == 0 and segment[5] <= MIB, "ELF dynamic table extent differs")
        for offset in range(segment[2], segment[2] + segment[5], 16):
            key, value = struct.unpack_from("<qQ", raw, offset)
            if key == 0:
                break
            values.append((key, value))
        else:
            raise ValueError("unterminated ELF dynamic table")
    strings = {}
    if values:
        table = [value for key, value in values if key == 5]
        sizes = [value for key, value in values if key == 10]
        require(len(table) == len(sizes) == 1 and 0 < sizes[0] <= JSON_LIMIT, "ELF string table differs")
        mappings = [row for row in segments if row[0] == 1 and row[3] <= table[0] and table[0] + sizes[0] <= row[3] + row[5]]
        require(len(mappings) == 1, "ELF string table is not file-backed")
        start = mappings[0][2] + table[0] - mappings[0][3]
        data = raw[start:start + sizes[0]]
        for key, value in values:
            if key in (1, 14, 15, 29):
                require(value < len(data), "ELF string offset exceeds table")
                end = data.find(b"\0", value, min(len(data), value + 4097))
                require(end >= 0, "ELF dynamic string is unterminated")
                name = data[value:end].decode("utf-8")
                require(name and not any(ord(c) < 32 or ord(c) == 127 for c in name), "unsafe ELF dynamic string")
                strings.setdefault(key, []).append(name)
    require(len(strings.get(14, [])) <= 1 and len(strings.get(15, [])) <= 1 and len(strings.get(29, [])) <= 1,
            "duplicate ELF SONAME/search path")
    needed = strings.get(1, [])
    require(len(needed) == len(set(needed)) and all("/" not in name for name in needed), "nonrelocatable or repeated ELF dependency")
    return {"class": 64, "byte_order": "little", "machine": machine, "type": kind, "needed": needed,
            "soname": strings.get(14, []), "rpath": strings.get(15, []), "runpath": strings.get(29, [])}


def native_check(root, report, native, variant, p04, git, revision, command_rows):
    fmt, paths = report["format"], report["paths"]
    build, source = paths["native_build"], paths["source"]
    require(build == native["paths"]["work"] + "/simx-" + fmt and paths["native_output"] == native["paths"]["output"], "original native build/packet origin differs")
    for key in ("source", "tools", "host_bin", "verilator"):
        same(paths[key], native["paths"][key], "native/P05 recorded path differs: " + key)
    native_artifacts = inventory(variant["artifacts_before"])
    same(report["native_artifacts"], variant["artifacts_before"], "native origin inventory differs")
    matmul = inventory(report["matmul_artifacts_before"])
    same(report["matmul_artifacts_before"], report["matmul_artifacts_after"], "native matmul artifacts changed")
    expected = {name.replace("tests/regression/ai_mlp/", "tests/regression/ai_matmul/").removesuffix("/ai_mlp") +
                ("/ai_matmul" if name.endswith("/ai_mlp") else "") for name in native_artifacts}
    require(set(matmul) == expected, "native matmul artifact membership differs")
    for name in set(matmul) & set(native_artifacts):
        same(matmul[name], native_artifacts[name], "matmul/model shared artifact differs: " + name)
    retained_names = {name for name in matmul if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt"))
                      or PurePosixPath(name).name in ("Makefile", "ai_matmul", "kernel.elf", "kernel.vxbin")}
    retained = inventory(report["retained_native_matmul"])
    require(set(retained) == retained_names, "native matmul retained body inventory differs")
    same(tree(root / "artifacts/native-matmul"), retained, "retained matmul files differ")
    for name, row in retained.items():
        same(row, matmul[name], "retained matmul identity differs from original artifact")
    model_body = read(root, "artifacts/native-model/ai_mlp", FILE_LIMIT)
    same(inventory(report["retained_native_model"]), {"ai_mlp": identity("ai_mlp", model_body)}, "retained model inventory differs")
    same(tree(root / "artifacts/native-model"), inventory(report["retained_native_model"]), "retained model tree differs")
    same(identity("tests/regression/ai_mlp/ai_mlp", model_body), native_artifacts["tests/regression/ai_mlp/ai_mlp"], "model executable differs from native qualified binary")
    binding = snapshot(root, report, "matmul_binding", "native-matmul-binding")
    same(binding, {"source": variant_source(native, root), "backend": "simx", "format": fmt,
                   "compiler_records": report["matmul_compiler_records"], "artifacts": report["matmul_artifacts_before"],
                   "dependencies": report["dependencies_before"], "profile_sha256": PROFILE}, "native matmul binding differs")
    require(sha(canonical(binding)) == report["matmul_qualification_id"], "matmul qualification identity differs")
    prefix = "artifacts/native-matmul/"
    runtime = read(root, prefix + "sw/runtime/simx_rt_config.stamp").decode().splitlines()
    backend = read(root, prefix + "sw/runtime/simx_config.stamp").decode().splitlines()
    application = read(root, prefix + "tests/regression/ai_matmul/config.stamp").decode().splitlines()
    require(len(runtime) == len(backend) == 1 and len(application) == 3 and len(report["matmul_compiler_records"]) == 4, "matmul compiler role inventory differs")
    require(application[2].split() == ["-L" + build + "/sw/runtime", "-lvortex"], "matmul linker runtime differs")
    for line, role, record in zip(runtime + backend + application[:2], ("runtime", "backend_cpp", "kernel", "host"), report["matmul_compiler_records"]):
        p04.compiler_record(line, role, fmt, record, source, report["budget"]["jobs"], backend="simx", build=build)
    same(report["matmul_compiler_records"][:2], variant["compiler_records"][:2], "model/matmul runtime/backend compiler records differ")
    macros = {}
    for line in read(root, command_rows["native-matmul-effective-header"]["log"]).decode().splitlines():
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?", line)
        if match:
            require(match[1] not in macros, "duplicate matmul effective macro")
            macros[match[1]] = match[2] or "1"
    p04.configuration(macros, raw=False)
    same({key: value for key, value in macros.items() if key.startswith("VX_CFG_")}, report["matmul_backend_header_macros"], "matmul raw macro observation differs")
    versions = {}
    for line in git.blob(revision, "VERSION").decode().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            require(key not in versions and re.fullmatch(r"[A-Z][A-Z0-9_]*", key) and re.fullmatch(r"[A-Za-z0-9_.-]+", value), "unrecognized VERSION syntax")
            versions[key] = value
    fields = {"XLEN": "64", "TOOLDIR": paths["tools"], "OSVERSION": "ubuntu/focal", "PREFIX": build + "/install",
              "PROFILE": "p02-tfr", "SOURCE_DIR": source, "BUILDDIR": build, **versions}
    require(read(root, prefix + ".config.stamp") == (" ".join(key + "=" + value for key, value in fields.items()) + "\n").encode(), "generated configure stamp differs")
    substitutions = {**versions, "VORTEX_HOME": source, "XLEN": "64", "TOOLDIR": paths["tools"], "OSVERSION": "ubuntu/focal",
                     "INSTALLDIR": build + "/install", "BUILDDIR": build, "PROFILE": "p02-tfr"}
    for source_name, generated in (("config.mk.in", "config.mk"), ("sim/rtlsim/verilator.vlt.in", "sim/rtlsim/verilator.vlt")):
        expected_bytes = git.blob(revision, source_name)
        for key, value in substitutions.items():
            expected_bytes = expected_bytes.replace(("@" + key + "@").encode(), value.encode())
        require(read(root, prefix + generated) == expected_bytes, "generated configuration differs from source template: " + generated)
    require(read(root, prefix + "tests/regression/ai_matmul/Makefile") == git.blob(revision, "tests/regression/ai_matmul/Makefile"), "copied matmul Makefile differs")
    return versions


def variant_source(native, root):
    return snapshot(root / "native", native, "source_before")["checkout"]


def command_contract(root, report, native, variant, rows, native_rows, tools, git, revision, package):
    paths, fmt, jobs = report["paths"], report["format"], report["budget"]["jobs"]
    source, work, output, build = (paths[key] for key in ("source", "work", "output", "native_build"))
    expected = ["package-tools-before", "native-matmul-build", "native-matmul-effective-header"] + ["native-" + fmt + "-" + name for name in MATMUL_FAMILIES] + [
        "package-bound-sdist", "package-offline-wheel", "package-create-venv", "package-install-wheel", "installed-matrix", "package-tools-after"]
    require(list(rows) == expected, "P05 command sequence is missing, reordered or contains extra commands")
    env = base_environment(paths, jobs, rows["native-matmul-build"]["environment"]["PATH"], tools["python3"]["path"])
    package_env = dict(base_environment(paths, 1, env["PATH"], tools["python3"]["path"]), CC=tools["gcc"]["path"], CXX=tools["g++"]["path"], AR=tools["ar"]["path"], MAX_JOBS="1")
    probe = [node.value.value for node in ast.parse(git.blob(revision, "ci/project/p05_execute.py")).body
             if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PACKAGE_PROBE" for target in node.targets)
             and isinstance(node.value, ast.Constant) and type(node.value.value) is str]
    require(len(probe) == 1, "source package-tool probe is not an exact literal body")
    python, venv = tools["python3"]["path"], work + "/venv"
    for name in ("package-tools-before", "package-tools-after"):
        check_command(rows[name], [python, "-I", "-B", "-c", probe[0]], work, package_env)
    make = [tools["make"]["path"], "--no-print-directory", "-j" + str(jobs), "THREADS=" + str(jobs), "VERILATOR_PATH=" + paths["verilator"]]
    app = build + "/tests/regression/ai_matmul"
    check_command(rows["native-matmul-build"], make + ["all"], app, dict(env, CONFIGS="-DITYPE=" + fmt + " -DOTYPE=fp32 -DKUNROLL=1"))
    check_command(rows["native-matmul-effective-header"], [tools["g++"]["path"], "-E", "-dM", "-x", "c++", *report["matmul_compiler_records"][1]["macro_flags"], "-include", build + "/sw/VX_config.h", "/dev/null"], build, env)
    for family in MATMUL_FAMILIES:
        name = fmt + "-" + family
        check_command(rows["native-" + name], [app + "/ai_matmul", "--case", name, "--iterations", "2", "--module", app + "/kernel.vxbin", "--qualification-id", report["matmul_qualification_id"]], app, dict(env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=build + "/sw/runtime"))
    stage, extracted, bundle = work + "/package-source", work + "/extracted-sdist/vortex_ai-0.1.0", output + "/artifacts/bundle"
    check_command(rows["package-bound-sdist"], [python, "-I", "-B", stage + "/setup.py", "egg_info", "sdist", "--dist-dir", output + "/packages/sdist"], stage, dict(package_env, VORTEX_AI_BUNDLE=bundle))
    check_command(rows["package-offline-wheel"], [python, "-I", "-B", extracted + "/setup.py", "build", "--build-base", work + "/package-build", "build_ext", "--parallel", "1", "bdist_wheel", "--dist-dir", output + "/packages/wheel", "--bdist-dir", work + "/wheel-stage"], extracted, package_env)
    check_command(rows["package-create-venv"], [python, "-I", "-B", "-m", "venv", "--copies", venv], work, package_env)
    check_command(rows["package-install-wheel"], [venv + "/bin/python", "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", "--no-compile", "--disable-pip-version-check", output + "/" + package["wheel"]["path"]], work, package_env)
    installed = work + "/installed-check"
    check_command(rows["installed-matrix"], [venv + "/bin/python", "-I", "-B", "-m", "vortex_ai.launch", "--bundle", bundle, "--", installed + "/p05_installed_check.py", "--request", installed + "/request.json", "--output", installed + "/observations.json"], installed, package_env)
    native_env = base_environment(native["paths"], native["budget"]["jobs"], native_rows["simx-" + fmt + "-configure"]["environment"]["PATH"], tools["python3"]["path"])
    same(native_env["PATH"], env["PATH"], "native/P05 PATH differs")
    prefix = "simx-" + fmt + "-"
    expected_native = ["version-gpp", "version-clang", "version-make"] + [prefix + suffix for suffix in ("configure", "header", "cpp-header-reproduce", "verilog-header-reproduce", "runtime", "application", "effective-header")] + [prefix + fmt + "-" + family for family in MODEL_FAMILIES]
    require(list(native_rows) == expected_native, "original native command inventory/order differs")
    # These deadlines are literal runner contracts or one shared bounded CLI
    # parameter per build/run group. The 10-second duration allowance above is
    # conservative monitor/serialization slack, not extra execution authority.
    def timeout_group(mapping, names, expected=None):
        values = [mapping[name]["timeout_seconds"] for name in names]
        require(values and len(set(values)) == 1, "inconsistent shared command timeout")
        value = values[0]
        require(value == expected if expected is not None else 1 <= value <= 1800,
                "command timeout differs from the runner contract")
        return value
    timeout_group(rows, ["package-tools-before", "package-tools-after"], 60)
    timeout_group(rows, ["native-matmul-effective-header"], 30)
    timeout_group(rows, ["package-create-venv", "package-install-wheel"], 120)
    timeout_group(rows, ["native-matmul-build", "package-bound-sdist", "package-offline-wheel"])
    run_timeout = timeout_group(rows, ["native-" + fmt + "-" + name for name in MATMUL_FAMILIES])
    timeout_group(rows, ["installed-matrix"], 16 * run_timeout + 60)
    timeout_group(native_rows, ["version-gpp", "version-clang", "version-make"] + [prefix + name for name in (
        "header", "cpp-header-reproduce", "verilog-header-reproduce", "effective-header")], 30)
    timeout_group(native_rows, [prefix + "configure"], 120)
    timeout_group(native_rows, [prefix + "runtime", prefix + "application"])
    timeout_group(native_rows, [prefix + fmt + "-" + name for name in MODEL_FAMILIES])
    for label, tool in (("version-gpp", "g++"), ("version-clang", "clang"), ("version-make", "make")):
        check_command(native_rows[label], [tools[tool]["path"], "--version"], native["paths"]["work"], native_env)
    native_make = [tools["make"]["path"], "--no-print-directory", "-j" + str(native["budget"]["jobs"]), "THREADS=" + str(native["budget"]["jobs"]), "VERILATOR_PATH=" + paths["verilator"]]
    check_command(native_rows[prefix + "configure"], [source + "/configure", "--xlen=64", "--profile=p02-tfr", "--osversion=ubuntu/focal", "--tooldir=" + paths["tools"]], build, native_env)
    check_command(native_rows[prefix + "header"], [tools["g++"]["path"], "-E", "-dM", "-x", "c++", "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", "-include", build + "/sw/VX_config.h", "/dev/null"], build, native_env)
    for language, basename in (("cpp", "VX_config.h"), ("verilog", "VX_config.vh")):
        check_command(native_rows[prefix + language + "-header-reproduce"], [python, source + "/ci/gen_config.py", "--config=" + source + "/VX_config.toml", "--profile=p02-tfr", "--format=" + language, "--output=" + build + "/p04-header-check/" + basename], build, dict(native_env, XLEN="64"))
    native_app = build + "/tests/regression/ai_mlp"
    for suffix, target in (("runtime", "runtime-simx"), ("application", "all")):
        check_command(native_rows[prefix + suffix], native_make + [target], native_app, dict(native_env, CONFIGS="-DITYPE=" + fmt + " -DOTYPE=fp32 -DKUNROLL=1"))
    check_command(native_rows[prefix + "effective-header"], [tools["g++"]["path"], "-E", "-dM", "-x", "c++", *variant["compiler_records"][1]["macro_flags"], "-include", build + "/sw/VX_config.h", "/dev/null"], build, native_env)
    for family in MODEL_FAMILIES:
        name = fmt + "-" + family
        check_command(native_rows[prefix + name], [native_app + "/ai_mlp", "--case", name, "--iterations", "2", "--module", native_app + "/kernel.vxbin", "--qualification-id", variant["qualification_id"], "--backend", "simx", "--source-revision", revision], native_app, dict(native_env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=build + "/sw/runtime"))


def installed_check(root, report, manifest, manifest_raw, package_tools, git, revision):
    request = snapshot(root, report, "installed_request")
    selection = snapshot(root, report, "selection")
    paths, fmt = report["paths"], report["format"]
    require(set(selection) == {"matmuls", "models"}, "selection descriptor fields differ")
    require([row["id"] for row in selection["matmuls"]] == report["matmul_case_ids"] == [fmt + "-" + family for family in MATMUL_FAMILIES]
            and [row["id"] for row in selection["models"]] == report["model_case_ids"] == [fmt + "-" + family for family in MODEL_FAMILIES], "selected fixed workload membership differs")
    expected_binding = {"backend": "simx", "format": fmt, "bundle_root": paths["output"] + "/artifacts/bundle",
                        "bundle_sha256": sha(manifest_raw), "source_sha256": manifest["binding_source_sha256"],
                        "qualification_id": manifest["qualification_id"], "source_revision": revision}
    same(request, {"schema_version": 1, "contract_id": "p05-installed-request-v1", "binding": expected_binding,
                   "matmul_cases": selection["matmuls"], "model_cases": report["model_case_ids"], "iterations": 2,
                   "expected_prefix": paths["work"] + "/venv"}, "installed request does not identify bound external installation")
    same(report["installed_script"], identity("p05_installed_check.py", git.blob(revision, "ci/project/p05_installed_check.py")), "installed observation script differs from Git body")
    observations = decode(checked(root, report["observations"], expected="artifacts/installed-observations.json", limit=JSON_LIMIT))
    require(set(observations) == {"schema_version", "contract_id", "scope", "binding", "installation", "matmuls", "models", "counts", "outcome", "acceptance_claimed"}, "observed packet fields differ")
    require(type(observations["schema_version"]) is int and observations["schema_version"] == 1
            and observations["contract_id"] == "p05-installed-observations-v1" and observations["scope"] == "simx-installed-python"
            and observations["acceptance_claimed"] is False and observations["outcome"] == "pass", "unsupported installed scope")
    same(observations["binding"], expected_binding, "observed installed binding differs")
    installation = observations["installation"]
    require(set(installation) == {"python_version", "python_implementation", "executable", "prefix", "base_prefix", "package_file",
                                  "extension_file", "distribution_version", "build_info", "runtime_libraries"}, "installation fields differ")
    same(installation["python_version"], package_tools["python_version"], "installed interpreter version differs")
    require(installation["python_implementation"] == "CPython" and installation["distribution_version"] == "0.1.0", "installed package/Python version differs")
    venv = paths["work"] + "/venv"
    site = venv + "/lib/python3.12/site-packages/vortex_ai/"
    for key, expected in (("prefix", venv), ("executable", venv + "/bin/python"), ("package_file", site + "__init__.py"),
                          ("extension_file", site + "_native.cpython-312-x86_64-linux-gnu.so")):
        require(str(absolute(installation[key])) == expected, "observed external installation path differs: " + key)
    absolute(installation["base_prefix"])
    require(installation["base_prefix"] != venv, "installation did not use a venv")
    same(installation["build_info"], {"bundle_sha256": sha(manifest_raw), "source_sha256": manifest["binding_source_sha256"], "binding_api": 1}, "observed extension pins differ")
    same(installation["runtime_libraries"], [expected_binding["bundle_root"] + "/" + ROLES[role][0] for role in ROLES if role != "module"], "loaded project-library paths differ")
    raw = read(root, "logs/installed-matrix.log").decode("utf-8")
    require(not any(ord(c) < 32 and c not in "\t\r\n" or 127 <= ord(c) <= 159 for c in raw), "installed raw log contains control characters")
    sequence, observed = [], {"P05_MATMUL": [], "P05_MODEL": []}
    for line in raw.splitlines():
        if "p05_" in line.casefold():
            marker, sep, body = line.partition(" ")
            require(marker in observed and sep, "unexpected failure/malformed installed raw marker")
            sequence.append(marker)
            observed[marker].append(decode(body.encode()))
    require(sequence == ["P05_MATMUL"] * 6 + ["P05_MODEL"] * 10, "installed raw record membership/order differs")
    same(observed["P05_MATMUL"], observations["matmuls"], "retained matmul observations differ from original raw log")
    same(observed["P05_MODEL"], observations["models"], "retained model observations differ from original raw log")
    for row in observations["matmuls"]:
        for key in ("status", "close_status"):
            same(row[key], {"validation": "success", "primary": 0, "cleanup": 0, "complete": True}, "installed matmul completion/cleanup failed")
    return installation


def audit_packet(root, git):
    raw = read(root, "report.json")
    report = decode(raw)
    require(type(report) is dict and set(report) == REPORT_FIELDS, "P05 report fields are missing or claim an unknown scope")
    require(type(report["schema_version"]) is int and report["schema_version"] == 1
            and report["contract_id"] == "p05-installed-python-execution-v1", "not a P05 installed execution packet")
    require(report["backend"] == "simx" and report["format"] in ("fp16", "bf16") and type(report["iterations"]) is int
            and report["iterations"] == 2 and report["state"] == "finished" and report["outcome"] == "pass"
            and report["reason"] is None and report["development"] is False and report["acceptance_claimed"] is False
            and report["phase_complete"] is False and report["source_stable"] is True and not report.get("failure_reasons")
            and "resource_snapshot_error" not in report, "unfinished, failed, unstable or unsupported P05 scope")
    paths = report["paths"]
    require(set(paths) == {"source", "tools", "work", "output", "host_bin", "verilator", "native_build", "native_output"}, "input path inventory differs")
    for name, value in paths.items():
        if name != "host_bin" or value is not None:
            absolute(value)
    major = [paths[key] for key in ("source", "tools", "work", "output", "native_build", "native_output")]
    require(not any(left == right or left.startswith(right + "/") or right.startswith(left + "/")
                    for index, left in enumerate(major) for right in major[index + 1:]), "original clean source/build/output roots overlap")
    def resource_contract(value, package=False):
        budget = {"min_free_bytes": 15 * 1024**3, "max_rss_bytes": 4 * 1024**3,
                  "max_log_bytes": JSON_LIMIT, "jobs": value["budget"]["jobs"]}
        if package:
            budget["package_jobs"] = 1
        same(value["budget"], budget, "resource budget differs from the runner contract")
        require(type(budget["jobs"]) is int and budget["jobs"] in (1, 2), "invalid bounded job count")
        for label in ("resources_before", "resources_after"):
            resources = value[label]
            require(set(resources) == {"available_memory_bytes", "free_disk_bytes"}
                    and type(resources["available_memory_bytes"]) is int and resources["available_memory_bytes"] >= 0
                    and set(resources["free_disk_bytes"]) == {"source", "tools", "work", "output"}
                    and all(type(item) is int and item >= 0 for item in resources["free_disk_bytes"].values()),
                    "invalid recorded resource inventory")
        require(value["resources_before"]["available_memory_bytes"] >= 4 * 1024**3
                and min(value["resources_before"]["free_disk_bytes"].values()) >= 15 * 1024**3,
                "initial resource reserve was insufficient")
    resource_contract(report, package=True)
    source_before = snapshot(root, report, "source_before")
    revision = source_before["checkout"]["revision"]
    git.entries(revision)
    p04 = load_p04(git, revision)
    native_input = report["native_input"]
    require(set(native_input) == {"kind", "directory", "build", "retained_prefix", "files"}
            and native_input["kind"] == "completed_top_level_p04_packet" and native_input["retained_prefix"] == "native"
            and native_input["directory"] == paths["native_output"] and native_input["build"] == paths["native_build"], "original native packet origin differs")
    same(tree(root / "native"), inventory(native_input["files"]), "original native packet retained bytes/inventory differ")
    native_raw = checked(root, report["native_report"], expected="native/report.json", limit=JSON_LIMIT)
    native = decode(native_raw)
    resource_contract(native)
    require(type(native["variants"]) is list and len(native["variants"]) == 1
            and native["variants"][0]["id"] == "simx-" + report["format"], "native selected variant differs")
    variant = native["variants"][0]
    p04_result = p04.audit_packet(root / "native", git)
    before, source_evidence = source_check(root, report, git, native, p04)
    rows, native_rows = commands(root, report), commands(root / "native", native)
    tools = tools_check(root, report, native, p04)
    package_tools = package_tools_check(root, report, rows, tools)
    manifest, manifest_raw = bundle_check(root, report, git, before["checkout"], variant)
    version_pins = native_check(root, report, native, variant, p04, git, revision, rows)
    package, extension = package_check(root, report, manifest, manifest_raw, git)
    command_contract(root, report, native, variant, rows, native_rows, tools, git, revision, package)
    installation = installed_check(root, report, manifest, manifest_raw, package_tools, git, revision)
    version_observations = {}
    for label, tool, pattern in (("version-gpp", "g++", r"g\+\+ .* ([0-9]+\.[0-9]+(?:\.[0-9]+)?)$"),
                                 ("version-clang", "clang", r"clang version ([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b"),
                                 ("version-make", "make", r"GNU Make ([0-9]+\.[0-9]+(?:\.[0-9]+)?)$")):
        text = read(root / "native", native_rows[label]["log"]).decode("utf-8")
        first = text.splitlines()[0]
        match = re.search(pattern, first)
        require(match is not None, "unrecognized native tool version observation: " + tool)
        version_observations[tool] = {"version": match[1], "banner": first, "log_sha256": sha(text.encode())}
    elf_evidence = []
    for role, (name, _) in ROLES.items():
        if role != "module":
            data = read(root, "artifacts/bundle/" + name, FILE_LIMIT)
            elf_evidence.append({"role": role, **identity("artifacts/bundle/" + name, data), **elf(data, 62, shared=True)})
    for name, machine in (("artifacts/native-model/ai_mlp", 62), ("artifacts/native-matmul/tests/regression/ai_matmul/ai_matmul", 62),
                          ("artifacts/native-matmul/tests/regression/ai_matmul/kernel.elf", 243)):
        data = read(root, name, FILE_LIMIT)
        elf_evidence.append({**identity(name, data), **elf(data, machine)})
    elf_evidence.append({**package["extension"], **elf(extension, 62, shared=True)})
    library_names = {PurePosixPath(name).name for name, _ in ROLES.values()}
    external_dependencies = sorted({name for row in elf_evidence for name in row["needed"] if name not in library_names})
    known = {name: value for name, value in tree(root).items() if not name.startswith("native/")}
    return {"packet": str(root), "report_sha256": sha(raw), "format": report["format"], "backend": "simx",
            "revision": revision, "tree": before["checkout"]["tree"], "profile_sha256": PROFILE, "fixture_sha256": FIXTURE,
            "binding_source_sha256": manifest["binding_source_sha256"], "binding_sources": manifest["binding_sources"],
            "bundle_sha256": sha(manifest_raw), "bundle_artifacts": manifest["artifacts"], "native_qualification_id": manifest["qualification_id"],
            "native_matmul_qualification_id": report["matmul_qualification_id"], "source_evidence": source_evidence,
            "native_provenance_audit": p04_result, "native_report_sha256": sha(native_raw), "native_packet_files": len(native_input["files"]),
            "commands_verified": len(rows), "native_commands_verified": len(native_rows), "commands": [
                {key: row[key] for key in ("id", "exit_code", "process_started", "cleanup_complete", "log_sha256", "log_size_bytes")}
                for row in rows.values()], "packages": package, "installation": installation, "tool_identities": tools,
            "toolchain_version_pins": version_pins, "native_tool_versions": version_observations, "package_versions": PACKAGE_VERSIONS,
            "package_prerequisite_inventory_sha256": sha(canonical(package_tools)),
            "package_prerequisite_file_counts": {name: len(row["files"]) for name, row in package_tools["distributions"].items()},
            "dependencies": report["dependencies_before"], "elf_identities": elf_evidence,
            "system_elf_dependencies_identified_not_archived": external_dependencies,
            "retained_packet_inventory_sha256": sha(canonical(known)), "relocated_original_paths_required": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--packet", action="append", required=True, type=Path)
    parser.add_argument("--selected-scope", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = {"schema_version": 1, "audit": "independent-p05-retained-provenance-v1", "outcome": "fail",
              "acceptance_claimed": False, "phase_complete": False, "full_matrix": False, "packets": [],
              "selected_scope_requested": args.selected_scope,
              "auditor_sha256": sha(read(Path(__file__).resolve().parent, Path(__file__).name)),
              "p04_helper": {"path": P04_AUDITOR, "sha256": P04_AUDITOR_SHA256, "source": "recorded Git commit object"}}
    output = None
    try:
        output = root_path(args.output, fresh=True)
        git = Git(root_path(args.source_dir))
        packets = [root_path(path) for path in args.packet]
        require(len(packets) in (1, 2) and len(set(packets)) == len(packets), "duplicate or excessive packet paths")
        require(not any(output.is_relative_to(packet) for packet in packets), "audit output may not modify a retained input packet")
        for packet in packets:
            result["packets"].append(audit_packet(packet, git))
        items = result["packets"]
        formats = [row["format"] for row in items]
        require(len(formats) == len(set(formats)), "duplicate format packets")
        require(len({(row["revision"], row["tree"], row["binding_source_sha256"]) for row in items}) == 1, "mixed source/tree/package input matrix")
        for row in items[1:]:
            same(row["dependencies"], items[0]["dependencies"], "matrix native dependency identities differ")
            same({name: (value["sha256"], value["size_bytes"]) for name, value in row["tool_identities"].items()},
                 {name: (value["sha256"], value["size_bytes"]) for name, value in items[0]["tool_identities"].items()}, "matrix tool identities differ")
            same(row["installation"]["python_version"], items[0]["installation"]["python_version"], "matrix Python versions differ")
        complete = set(formats) == {"fp16", "bf16"}
        require(complete or args.selected_scope, "complete two-format SimX installed matrix is missing")
        result.update(outcome="pass", full_matrix=complete, scope="complete_two_format_matrix" if complete else "incomplete_selected_format_matrix")
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError,
            subprocess.SubprocessError, tarfile.TarError, zipfile.BadZipFile, zipfile.LargeZipFile, csv.Error, struct.error) as error:
        result["reason"] = str(error)
    result["limitations"] = [
        "Retained provenance and clean-install consistency only; no native rerun, numerical/dispatch acceptance, phase completion, framework support or hardware claim.",
        "Trusted-builder/nonhostile-filesystem scope: hashes bind recorded observations; this is not a hostile-process sandbox or authenticated execution attestation.",
        "Original absolute build/source/venv paths are compared as recorded names and are never required to exist after relocation.",
        "Main-repository bytes use actual Git commit objects; submodule file hashes/pins are recorded without fetching or reconstructing missing bodies.",
        "Native configure templates, stamps, compiler roles, effective-header observations and retained header identities are checked; configuration generators are not executed by this auditor.",
        "System Python, compiler-support files, package-build prerequisites and system ELF dependencies are identified rather than replay-archived. Tool semantic versions beyond retained g++/Clang/Make banners and VERSION/package/Python metadata are unavailable.",
        "P04 kernel ELF, libvortex2.a and softfloat.a are identity-only where absent from the retained packet; retained bundle libraries, host binaries, matmul kernel ELF and installed extension are parsed without execution.",
        "The existing independent P04 provenance auditor is reused only after its full body matches the explicitly reported SHA-256 pin; no P05 runner/record/package module is imported.",
    ]
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if output is not None:
        with output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
