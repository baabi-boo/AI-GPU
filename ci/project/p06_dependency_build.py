#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and stage the three selected SimX dependencies from fresh locked sources."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import sys

sys.dont_write_bytecode = True

from baseline_inventory import collect_source
from baseline_process import run_bounded
import p02_matrix as base
import p06_dependency_binary as binary
import p06_dependency_contract as contract
import p06_dependency_graph as graph
import p06_dependency_record as recorder
import p06_dependency_sources as sources
from baseline_packet_io import load_json_bytes
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
RECORDER = ROOT / "ci/project/p06_dependency_record.py"
HOST_TOOLS = ("gcc", "g++", "ar", "ranlib", "cmake", "make", "python3")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(path, *, existing=False, inventory_file=False):
    if inventory_file:
        result = Path(os.path.abspath(path))
        require(re.fullmatch(r"/[A-Za-z0-9_./+()\-]+", str(result)),
                "inventory path must be an absolute safe literal")
        require(result.resolve(strict=existing) == result,
                "inventory path must not traverse a symlink")
    else:
        result = base._path(path, existing=existing)
    require(result == Path(path).absolute() and result.resolve() == result,
            "dependency path must be canonical without symlink traversal")
    for parent in (result, *result.parents):
        require(not parent.is_symlink(), "dependency path traverses a symlink")
    return result


def identity(path, *, relative_to=None):
    path = canonical(path, existing=True, inventory_file=True)
    information = path.stat()
    require(stat.S_ISREG(information.st_mode) and information.st_nlink == 1,
            "retained input must be a regular file without hard links")
    require(0 <= information.st_size <= contract.MAX_FILE_BYTES, "retained file exceeds its byte bound")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {"path": path.relative_to(relative_to).as_posix() if relative_to else str(path),
            "sha256": digest.hexdigest(), "size_bytes": information.st_size}


def write_json(path, value):
    raw = contract.json_bytes(value) + b"\n"
    require(len(raw) <= contract.MAX_RECEIPT_BYTES, "JSON evidence exceeds its byte bound")
    with path.open("xb") as stream:
        stream.write(raw)
    return identity(path)


def read_json(path):
    path = canonical(path, existing=True)
    require(path.stat().st_size <= contract.MAX_RECEIPT_BYTES, "JSON input exceeds its byte bound")
    return load_json_bytes(path.read_bytes(), "dependency build input")


def clean_environment(build, host_bin=None):
    entries = ([str(host_bin)] if host_bin is not None else [])
    entries += [str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    return {"PATH": os.pathsep.join(dict.fromkeys(entries)),
            "HOME": str(build / "home"), "TMPDIR": str(build / "tmp"),
            "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}


def tool_inventory(environment):
    result = {}
    for name in HOST_TOOLS:
        path = shutil.which(name, path=environment["PATH"])
        require(path is not None and os.access(path, os.X_OK), "required dependency tool is absent: " + name)
        result[name] = recorder.file_identity(path)
    require(result["python3"] == recorder.file_identity(sys.executable),
            "dependency launcher Python differs from the executing interpreter")
    return result


def helper_inventory():
    names = {Path(__file__).resolve()}
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if name:
            path = Path(name).resolve()
            if path.suffix == ".py" and path.is_relative_to(ROOT / "ci/project"):
                names.add(path)
    return [identity(path, relative_to=ROOT) for path in sorted(names)]


def launcher(config, digest, tools, tool, role, *, compiler_launcher=False):
    words = [tools["python3"]["path"], str(RECORDER), "--config", str(config),
             "--config-sha256", digest, "--tool", tool, "--role", role]
    if compiler_launcher:
        words.append("--compiler-launcher")
    return [*words, "--"]


def softfloat_command(source_root, tools, config, config_sha256):
    directory = source_root / "softfloat/build/Linux-x86_64-GCC"
    compile_words = [*launcher(config, config_sha256, tools, "gcc", "compile"),
        "-c", "-Werror-implicit-function-declaration", "-DSOFTFLOAT_FAST_INT64",
        *contract.SOFTFLOAT_OPTIONS, "-I.", "-I../../source/RISCV", "-I../../source/include", "-O2", "-o"]
    archive_words = [*launcher(config, config_sha256, tools, "ar", "archive"), "crs"]
    return [tools["make"]["path"], "--no-print-directory", "-j2", "--output-sync=target",
            "SPECIALIZE_TYPE=RISCV", "SOFTFLOAT_OPTS=" + " ".join(contract.SOFTFLOAT_OPTIONS),
            "COMPILE_C=" + shlex.join(compile_words) + " $@",
            "MAKELIB=" + shlex.join(archive_words) + " $@", "softfloat.a"], directory


def cmake_command(source_root, build, tools, config, config_sha256, archiver, indexer):
    binary_root = build / "ramulator"
    settings = dict(graph.CMAKE_OPTIONS,
        CMAKE_CXX_COMPILER=tools["g++"]["path"], CMAKE_MAKE_PROGRAM=tools["make"]["path"],
        CMAKE_AR=str(archiver), CMAKE_RANLIB=str(indexer),
        CMAKE_CXX_COMPILER_LAUNCHER=";".join(launcher(config, config_sha256, tools, "g++", "compile", compiler_launcher=True)),
        CMAKE_CXX_LINKER_LAUNCHER=";".join(launcher(config, config_sha256, tools, "g++", "link", compiler_launcher=True)),
        CMAKE_SHARED_LINKER_FLAGS="-Wl,-Map," + str(build / "ramulator.map"),
        FETCHCONTENT_SOURCE_DIR_SPDLOG=str(source_root / "spdlog"),
        FETCHCONTENT_SOURCE_DIR_ARGPARSE=str(source_root / "argparse"))
    settings["FETCHCONTENT_SOURCE_DIR_YAML-CPP"] = str(source_root / "yaml-cpp")
    command = [tools["cmake"]["path"], "-S", str(source_root / "ramulator"), "-B", str(binary_root),
               "-G", "Unix Makefiles", *("-D" + name + "=" + value for name, value in sorted(settings.items()))]
    return command, settings


def extension_commands(source_root, build, tools, config, config_sha256):
    extension = build / "extension"
    object_path, product = extension / "gddr6.o", extension / "libramulator-vortex.so"
    compile_arguments = [*launcher(config, config_sha256, tools, "g++", "compile"),
        "-std=c++20", "-O3", "-DNDEBUG", "-fPIC",
        "-isystem", str(source_root / "ramulator/src"), "-isystem", str(source_root / "spdlog/include"),
        "-isystem", str(source_root / "yaml-cpp/include"), "-c",
        str(source_root / "ramulator/src/dram/impl/GDDR6.cpp"), "-o", str(object_path)]
    link_arguments = [*launcher(config, config_sha256, tools, "g++", "link"),
        "-shared", str(object_path), "-L" + str(source_root / "ramulator"), "-lramulator",
        "-Wl,-Map," + str(build / "extension.map"), "-o", str(product)]
    return compile_arguments, link_arguments


def generated_sources(records, source_root):
    selected = {}
    for row in sorted(records, key=lambda item: item.get("finished_ns") or item.get("started_ns") or 0):
        for name in ("output", "dependency_file", "dependency_prepass_file", "link_map"):
            item = row.get(name)
            if type(item) is dict and Path(item["path"]).is_relative_to(source_root):
                relative = Path(item["path"]).relative_to(source_root).as_posix()
                selected[relative] = {"path": relative, "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
    return [selected[name] for name in sorted(selected)]


def stage_file(original, destination):
    original = canonical(original, existing=True, inventory_file=True)
    destination = canonical(destination, inventory_file=True)
    before = identity(original)
    require(not os.path.lexists(destination), "dependency staging destination is not fresh: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canonical(destination.parent, existing=True, inventory_file=True)
    with original.open("rb") as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    os.chmod(destination, stat.S_IMODE(original.stat().st_mode))
    after = identity(destination)
    require((before["sha256"], before["size_bytes"]) == (after["sha256"], after["size_bytes"])
            and identity(original) == before, "dependency input changed during staging")
    return after


class Builder:
    def __init__(self, args):
        self.args = args
        self.source = canonical(args.source_dir, existing=True)
        self.workspace = canonical(args.workspace_dir, existing=True)
        self.output = canonical(args.output_dir)
        require(self.source == ROOT and not base._overlap(self.source, self.workspace),
                "use this checkout and an independent owned dependency workspace")
        require(self.output.is_relative_to(self.workspace) and self.output != self.workspace,
                "dependency output must lie inside its owned workspace")
        require(not os.path.lexists(self.output), "dependency evidence output must be fresh")
        host_bin = getattr(args, "host_bin", None)
        self.host_bin = canonical(host_bin, existing=True) if host_bin is not None else None
        require(self.host_bin is None or self.host_bin.is_dir(), "host-bin must be a directory")
        self.output.mkdir(mode=0o700)
        for name in ("logs", "records", "payloads", "helpers", "build-inputs", "launchers"):
            (self.output / name).mkdir(mode=0o700)
        self.source_root = self.workspace / "dependency-sources"
        self.build_root = self.workspace / "dependency-build"
        self.environment = clean_environment(self.build_root, self.host_bin)
        self.report = {"schema_version": 1, "contract_id": contract.CONTRACT_ID,
            "dependency_contract_sha256": contract.contract_hash(), "expected_revision": args.expected_revision,
            "state": "running", "outcome": "blocked", "reason": None, "failures": [],
            "paths": {"source": str(self.source), "workspace": str(self.workspace), "sources": str(self.source_root),
                      "build": str(self.build_root), "output": str(self.output)},
            "preparation": None, "helper_sources": [], "environment": self.environment,
            "budget": dict(contract.BUDGET), "source_manifest": None, "source_plan": [], "tools": {},
            "tool_config": None, "commands": [], "records": [], "compile_database": None,
            "cmake_configuration": {}, "generated_inputs": [], "generated_sources": [],
            "products": {}, "archives": [], "external_archives": [], "maps": [], "staged_files": [], "retained_files": [],
            "stability_checks": [], "source_checkout_before": None, "source_checkout_after": None,
            "fresh_dependency_build_passed": False, **dict.fromkeys(contract.FALSE_CLAIMS, False)}
        self.helpers = None
        self.receipt_reader = None
        self.initial_checkout = None
        self.save()

    def save(self):
        base._write_json(self.output / "report.json", self.report)

    def fail(self, error, stage):
        reason = str(error) or "interrupted"
        self.report["failures"].append({"stage": stage, "reason": reason})
        if self.report["reason"] is None:
            self.report["reason"] = reason
        self.report["outcome"] = "fail" if any(row.get("process_started") for row in self.report["commands"]) else "blocked"
        self.report["fresh_dependency_build_passed"] = False

    def retain(self, original, relative):
        target = self.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        stage_file(original, target)
        return identity(target, relative_to=self.output)

    def snapshot(self, name, value):
        path = self.output / name
        write_json(path, value)
        return identity(path, relative_to=self.output)

    def all_records(self, *, passing=False):
        entries = sorted((self.output / "records").iterdir())
        lock = self.output / "records/.records.lock"
        if lock in entries:
            require(identity(lock)["size_bytes"] == 0, "execution receipt lock differs")
            entries.remove(lock)
        require(len(entries) <= contract.MAX_RECORDS and all(path.suffix == ".json" for path in entries),
                "execution receipt inventory is invalid or excessive")
        rows = [read_json(path) for path in entries]
        if passing:
            require(all(row.get("state") == "finished" and row.get("outcome") == "pass"
                        and row.get("process_started") is True and type(row.get("exit_code")) is int
                        and row["exit_code"] == 0 and row.get("reason") is None and not row.get("failures")
                        for row in rows), "dependency tool execution did not finish successfully")
        return rows

    def stable(self, label):
        if self.helpers is not None:
            require(helper_inventory() == self.helpers, "dependency build helper changed")
        if self.report["tools"]:
            require(tool_inventory(self.environment) == self.report["tools"], "dependency build tool changed")
        check = {"label": label}
        if self.report["source_manifest"] is not None:
            generated = generated_sources(self.all_records(), self.source_root)
            check["sources"] = sources.verify_sources(self.report["source_manifest"], self.source_root,
                                                       generated_files=generated)
            self.report["generated_sources"] = generated
        for item in self.report["staged_files"]:
            require(identity(Path(item["path"])) == item, "staged dependency changed")
        check["staged_sha256"] = contract.digest(self.report["staged_files"])
        self.report["stability_checks"].append(check)

    def command(self, identifier, arguments, cwd, *, timeout=1800):
        require(not any(row["id"] == identifier for row in self.report["commands"]), "duplicate dependency command")
        self.stable("before-" + identifier)
        row = {"id": identifier, "argv": list(map(str, arguments)), "cwd": str(cwd),
               "environment": dict(self.environment), "timeout_seconds": timeout,
               "log": "logs/" + identifier + ".log", "process_started": None}
        self.report["commands"].append(row)
        self.save()
        row.update(run_bounded(row["argv"], cwd, self.environment, self.output / row["log"],
            timeout_seconds=timeout, min_free_bytes=contract.BUDGET["min_free_bytes"],
            max_rss_bytes=contract.BUDGET["max_rss_bytes"], max_log_bytes=contract.BUDGET["max_log_bytes"],
            resource_paths=(self.source, self.workspace, self.output)))
        self.save()
        require(row.get("process_started") is True and row.get("outcome") == "pass"
                and type(row.get("exit_code")) is int and row["exit_code"] == 0
                and row.get("cleanup_complete") is True and row.get("reason") is None,
                "dependency command failed: " + identifier + ": " + str(row.get("reason")))
        self.all_records(passing=True)
        self.stable("after-" + identifier)
        self.save()
        return (self.output / row["log"]).read_text(encoding="utf-8")

    def payload_descriptor(self, original):
        item = identity(original)
        relative = "payloads/" + item["sha256"] + ".bin"
        target = self.output / relative
        if target.exists():
            require(identity(target)["sha256"] == item["sha256"], "existing retained payload changed")
        else:
            self.retain(original, relative)
        return identity(target, relative_to=self.output)

    def archive(self, name, path, members):
        parsed = binary.validate_archive(path.read_bytes(), members)
        result = {"name": name, "original_path": str(path), "descriptor": self.payload_descriptor(path),
                  "members": parsed["members"]}
        self.report["archives"].append(result)
        return result

    def verify_products(self):
        records = self.all_records(passing=True)
        compiled = [row for row in records if row["role"] == "compile"]
        expected = {str(self.source_root / row["source"]): row for row in self.report["source_plan"]}
        actual = {}
        for row in compiled:
            names = [word for word in row["requested_arguments"] if word.endswith(recorder.SOURCE_SUFFIXES)]
            require(len(names) == 1, "compile record has an ambiguous selected source")
            source = str((Path(row["cwd"]) / names[0]).resolve()) if not names[0].startswith("/") else names[0]
            require(source in expected and source not in actual, "dependency compile source is extra or duplicated")
            actual[source] = row
        require(set(actual) == set(expected), "dependency translation-unit graph is incomplete")
        for component in ("softfloat", "yaml-cpp", "spdlog"):
            members = []
            for plan in self.report["source_plan"]:
                if plan["component"] == component:
                    output = actual[str(self.source_root / plan["source"])]["output"]
                    members.append({"name": plan["archive_member"], "sha256": output["sha256"],
                                    "size_bytes": output["size_bytes"]})
            if component == "softfloat":
                path = self.source_root / "softfloat/build/Linux-x86_64-GCC/softfloat.a"
            else:
                matching = [row for row in records if row["role"] == "index"
                            and Path(row["output_path"]).name == "lib" + component + ".a"]
                require(len(matching) == 1, "selected dependency archive has no unique index record")
                path = Path(matching[0]["output_path"])
            self.archive(component, path, members)
        archives = {row["original_path"]: row["members"] for row in self.report["archives"]}
        for name, path, cwd, required, loads in (
            ("ramulator", self.build_root / "ramulator.map", self.build_root / "ramulator",
             [row["original_path"] for row in self.report["archives"] if row["name"] == "yaml-cpp"],
             [row["original_path"] for row in self.report["archives"] if row["name"] in ("yaml-cpp", "spdlog")]),
            ("extension", self.build_root / "extension.map", self.build_root / "extension", [],
             [str(self.source_root / "ramulator/libramulator.so")]),
        ):
            parsed = binary.parse_link_map(path.read_text(), cwd=str(cwd))
            for selected in parsed["selected_members"]:
                original = selected["archive"]
                if original in archives:
                    continue
                basename = Path(original).name
                require(basename in ("libgcc.a", "libgcc_eh.a"), "link selected an unreviewed external archive")
                command_id = "locate-" + basename.replace(".", "-")
                observed = self.command(command_id,
                    [self.report["tools"]["g++"]["path"], "-print-file-name=" + basename], self.build_root, timeout=30).strip()
                require(Path(observed).is_absolute() and Path(original).resolve() == Path(observed).resolve(),
                        "link selected a different compiler support archive")
                external_path = Path(original)
                members = binary.parse_archive(external_path.read_bytes())["members"]
                self.report["external_archives"].append({"name": basename, "original_path": original,
                    "descriptor": self.payload_descriptor(external_path.resolve()), "members": members,
                    "tool_resolution_command_id": command_id})
                archives[original] = members
            verified = binary.validate_link_map(path.read_text(), cwd=str(cwd), archives=archives,
                                                required_archives=required, required_loads=loads)
            self.report["maps"].append({"name": name, "cwd": str(cwd),
                "descriptor": self.payload_descriptor(path), "verification": verified})
        originals = {"softfloat": self.source_root / "softfloat/build/Linux-x86_64-GCC/softfloat.a",
                     "ramulator": self.source_root / "ramulator/libramulator.so",
                     "extension": self.build_root / "extension/libramulator-vortex.so"}
        for name, path in originals.items():
            item = identity(path)
            descriptor = self.payload_descriptor(path)
            self.report["products"][name] = {"original_path": str(path),
                "staged_path": str(self.source / contract.PRODUCTS[name]), "sha256": item["sha256"],
                "size_bytes": item["size_bytes"], "payload": descriptor["path"]}

    def retain_build_inputs(self):
        selected = []
        for path in (self.build_root / "ramulator").rglob("*"):
            if path.is_file() and (path.suffix in (".cmake", ".make", ".txt", ".json", ".h", ".hpp",
                                                  *recorder.SOURCE_SUFFIXES)
                                  or path.name == "Makefile"):
                selected.append(path)
        for path in sorted(selected):
            relative = "build-inputs/" + path.relative_to(self.build_root / "ramulator").as_posix()
            self.report["generated_inputs"].append(self.retain(path, relative))
            if path.name == "compile_commands.json":
                require(self.report["compile_database"] is None, "duplicate compilation database")
                self.report["compile_database"] = self.report["generated_inputs"][-1]
        require(self.report["compile_database"] is not None, "CMake compilation database is absent")

    def stage(self):
        for name in ("yaml-cpp", "spdlog", "argparse"):
            destination = self.source / contract.PINS[name]["path"]
            require(not os.path.lexists(destination), "fetched measurement inputs already exist")
            manifest = next(row for row in self.report["source_manifest"]["sources"] if row["name"] == name)
            for item in manifest["files"]:
                self.report["staged_files"].append(stage_file(self.source_root / name / item["path"], destination / item["path"]))
        for name in contract.PRODUCTS:
            product = self.report["products"][name]
            self.report["staged_files"].append(stage_file(Path(product["original_path"]), Path(product["staged_path"])))
        self.report["staged_files"].sort(key=lambda item: item["path"])

    def execute(self):
        try:
            require(type(self.args.expected_revision) is str
                    and re.fullmatch(r"[0-9a-f]{40}", self.args.expected_revision), "exact expected revision required")
            self.initial_checkout = collect_source(self.source)
            base._source_ok({"checkout": self.initial_checkout}, False)
            require(self.initial_checkout["revision"] == self.args.expected_revision, "dependency source revision differs")
            self.report["source_checkout_before"] = self.snapshot("source-checkout-before.json", self.initial_checkout)
            preparation_path = canonical(self.args.preparation, existing=True)
            preparation = read_json(preparation_path)
            self.receipt_reader = importlib.import_module("p06_dependency_receipt")
            require(Path(self.receipt_reader.__file__).resolve() == ROOT / "ci/project/p06_dependency_receipt.py",
                    "dependency receipt reader loaded from an unexpected location")
            declared_host_bin = self.receipt_reader.validate_preparation(
                preparation, self.args.expected_revision, paths=self.report["paths"], checkout=self.initial_checkout)
            require(declared_host_bin == (str(self.host_bin) if self.host_bin is not None else None),
                    "host-bin differs from the selected dependency preparation")
            self.report["preparation"] = self.retain(preparation_path, "preparation.json")
            require(shutil.disk_usage(self.workspace).free >= contract.BUDGET["min_free_bytes"]
                    and shutil.disk_usage(self.source).free >= contract.BUDGET["min_free_bytes"],
                    "fresh dependency build requires the 15 GiB disk reserve")
            require((available_memory_bytes() or 0) >= contract.BUDGET["max_rss_bytes"],
                    "fresh dependency build requires 4 GiB available RAM")
            require(not os.path.lexists(self.build_root) and not os.path.lexists(self.source_root),
                    "dependency source/build workspace is not fresh")
            self.build_root.mkdir(mode=0o700)
            for name in ("home", "tmp", "extension"):
                (self.build_root / name).mkdir(mode=0o700)
            self.report["tools"] = tool_inventory(self.environment)
            self.receipt_reader.validate_preparation(preparation, self.args.expected_revision,
                paths=self.report["paths"], tools=self.report["tools"])
            self.helpers = helper_inventory()
            self.report["helper_sources"] = list(self.helpers)
            for row in self.helpers:
                self.retain(self.source / row["path"], "helpers/" + row["path"])
            repositories = {name: Path(path) for name, path in preparation["repositories"].items()}
            self.report["source_manifest"] = sources.materialize_sources(repositories, self.source_root)
            self.receipt_reader.validate_preparation(preparation, self.args.expected_revision,
                paths=self.report["paths"], tools=self.report["tools"], manifest=self.report["source_manifest"])
            self.report["source_plan"] = graph.source_plan(self.report["source_manifest"],
                lambda name, path: (self.source_root / name / path).read_bytes())
            for repository in self.report["source_manifest"]["sources"]:
                for row in repository["files"]:
                    relative = repository["name"] + "/" + row["path"]
                    self.retain(self.source_root / relative, "sources/" + relative)
            config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
                "contract_sha256": contract.contract_hash(), "roots": {
                    "sources": str(self.source_root), "build": str(self.build_root),
                    "receipts": str(self.output / "records"), "payloads": str(self.output / "payloads")},
                "tools": {name: self.report["tools"][name] for name in recorder.TOOLS}}
            config_path = self.output / "tool-config.json"
            self.report["tool_config"] = self.snapshot("tool-config.json", config)
            config_sha256 = self.report["tool_config"]["sha256"]
            shims = {}
            for name, role in (("ar", "archive"), ("ranlib", "index")):
                path = self.output / "launchers" / (name + ".sh")
                path.write_text("#!/bin/sh\nexec " + shlex.join(launcher(config_path, config_sha256,
                    self.report["tools"], name, role)) + ' "$@"\n')
                path.chmod(0o755)
                shims[name] = path
            self.stable("sources-frozen")
            self.save()
            arguments, cwd = softfloat_command(self.source_root, self.report["tools"], config_path, config_sha256)
            self.command("softfloat", arguments, cwd)
            arguments, settings = cmake_command(self.source_root, self.build_root, self.report["tools"],
                                                config_path, config_sha256, shims["ar"], shims["ranlib"])
            self.report["cmake_configuration"] = settings
            self.command("ramulator-configure", arguments, self.build_root, timeout=120)
            self.command("ramulator-build", [self.report["tools"]["cmake"]["path"], "--build",
                str(self.build_root / "ramulator"), "--target", "ramulator", "--parallel", "2", "--verbose"], self.build_root)
            compile_arguments, link_arguments = extension_commands(self.source_root, self.build_root,
                self.report["tools"], config_path, config_sha256)
            self.command("extension-compile", compile_arguments, self.build_root / "extension")
            self.command("extension-link", link_arguments, self.build_root / "extension")
            self.verify_products()
            self.retain_build_inputs()
            self.stage()
            self.stable("staged-and-verified")
            checkout = collect_source(self.source)
            self.report["source_checkout_after"] = self.snapshot("source-checkout-after.json", checkout)
            require(checkout == self.initial_checkout, "measurement source changed while staging dependencies")
            self.report["outcome"] = "pass"
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, KeyboardInterrupt) as error:
            self.fail(error, "execution")
        finally:
            for stage, operation in (("final-stability", lambda: self.stable("final")),
                                     ("final-records", self._retain_record_inventory)):
                try:
                    operation()
                except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                    self.fail(error, stage)
            try:
                self.report["retained_files"] = self.retained_inventory()
            except (OSError, ValueError, RuntimeError) as error:
                self.fail(error, "final-retention")
            self.report["state"] = "finished"
            self.report["fresh_dependency_build_passed"] = self.report["outcome"] == "pass"
            self.save()
        if self.report["outcome"] == "pass":
            try:
                self.receipt_reader.load_receipt(self.output / "report.json",
                    expected_sha256=identity(self.output / "report.json")["sha256"],
                    expected_revision=self.args.expected_revision)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, ImportError) as error:
                self.fail(error, "inert-verification")
                self.save()
        return self.report

    def _retain_record_inventory(self):
        self.report["records"] = [identity(path, relative_to=self.output)
                                  for path in sorted((self.output / "records").glob("*.json"))]

    def retained_inventory(self):
        rows, total = [], 0
        for path in sorted(self.output.rglob("*")):
            require(not path.is_symlink(), "retained dependency packet contains a symlink")
            if path.is_dir() or path == self.output / "report.json":
                continue
            row = identity(path, relative_to=self.output)
            total += row["size_bytes"]
            require(total <= contract.MAX_PACKET_BYTES, "retained dependency packet exceeds its byte bound")
            rows.append(row)
        return rows


def build(args):
    return Builder(args).execute()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--workspace-dir", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--host-bin", type=Path,
                        help="host-tool directory recorded by the selected local preparation")
    args = parser.parse_args(argv)
    try:
        report = build(args)
        print(json.dumps({key: report[key] for key in ("outcome", "reason", "fresh_dependency_build_passed")}, sort_keys=True))
        return 0 if report["fresh_dependency_build_passed"] else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "fresh_dependency_build_passed": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
