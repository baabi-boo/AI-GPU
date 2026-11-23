# SPDX-License-Identifier: Apache-2.0
"""Exercise fresh staging and the actual selected Make/CMake launcher mechanics."""

from collections import Counter
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_dependency_binary as binary
import p06_dependency_build as build
import p06_dependency_contract as contract
import p06_dependency_graph as graph
import p06_dependency_record as recorder


class DependencyBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-build-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.build = self.root / "build"
        self.packet = self.root / "packet"
        for path in (self.sources, self.build, self.packet):
            path.mkdir()
        for name in ("home", "tmp", "extension"):
            (self.build / name).mkdir()
        for name in ("records", "payloads", "launchers"):
            (self.packet / name).mkdir()
        self.tools = {}
        for name in build.HOST_TOOLS:
            path = shutil.which(name)
            if path is not None:
                self.tools[name] = recorder.file_identity(path)
        self.config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
            "contract_sha256": contract.contract_hash(), "roots": {
                "sources": str(self.sources), "build": str(self.build),
                "receipts": str(self.packet / "records"), "payloads": str(self.packet / "payloads")},
            "tools": {name: self.tools[name] for name in recorder.TOOLS}}
        self.config_path = self.packet / "tool-config.json"
        self.config_sha256 = build.write_json(self.config_path, self.config)["sha256"]
        self.environment = build.clean_environment(self.build)

    def execute(self, command, cwd):
        result = subprocess.run(command, cwd=cwd, env=self.environment, timeout=120,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result

    def records(self):
        producer = object.__new__(build.Builder)
        producer.output = self.packet
        return producer.all_records(passing=True)

    def shims(self):
        result = {}
        for name, role in (("ar", "archive"), ("ranlib", "index")):
            path = self.packet / "launchers" / (name + ".sh")
            path.write_text("#!/bin/sh\nexec " + shlex.join(build.launcher(
                self.config_path, self.config_sha256, self.tools, name, role)) + ' "$@"\n')
            path.chmod(0o755)
            result[name] = path
        return result

    def test_actual_make_override_preserves_automatic_outputs_and_archive_order(self):
        directory = self.sources / "softfloat/build/Linux-x86_64-GCC"
        directory.mkdir(parents=True)
        (directory / "first.c").write_text("int first(void) { return 11; }\n")
        (directory / "second.c").write_text("int second(void) { return 17; }\n")
        (directory / "Makefile").write_text(
            "OBJS = first.o second.o\n"
            "softfloat.a: $(OBJS)\n\t$(MAKELIB) $(OBJS)\n"
            "%.o: %.c\n\t$(COMPILE_C) $<\n")
        command, cwd = build.softfloat_command(self.sources, self.tools, self.config_path, self.config_sha256)
        self.execute(command, cwd)
        records = self.records()
        self.assertEqual(Counter(row["role"] for row in records), {"compile": 2, "archive": 1})
        selected = {Path(row["output_path"]).name: row for row in records if row["role"] == "compile"}
        members = [{"name": name, "sha256": selected[name]["output"]["sha256"],
                    "size_bytes": selected[name]["output"]["size_bytes"]}
                   for name in ("first.o", "second.o")]
        binary.validate_archive((directory / "softfloat.a").read_bytes(), members)
        archive = next(row for row in records if row["role"] == "archive")
        self.assertEqual(archive["requested_arguments"], ["crs", "softfloat.a", "first.o", "second.o"])
        self.assertTrue(all(row["output_absent_before"] for row in records))
        for row in selected.values():
            self.assertTrue(set(contract.SOFTFLOAT_OPTIONS).issubset(row["arguments"]))
            self.assertEqual([item["stage"] for item in row["children"]], ["dependencies", "tool"])
        generated = build.generated_sources(records, self.sources)
        self.assertEqual(len(generated), 7)
        self.assertIn("softfloat/build/Linux-x86_64-GCC/first.o.p06-before.d",
                      [row["path"] for row in generated])

    def test_actual_cmake_records_static_archive_index_and_shared_link_only(self):
        if "cmake" not in self.tools:
            self.skipTest("CMake is required for the actual launcher integration fixture")
        ramulator = self.sources / "ramulator"
        ramulator.mkdir()
        (ramulator / "static.cpp").write_text("int selected(void) { return 23; }\n")
        (ramulator / "shared.cpp").write_text("int selected(void); int sample(void) { return selected(); }\n")
        (ramulator / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\nproject(selected LANGUAGES CXX)\n"
            "add_library(yaml-cpp STATIC static.cpp)\n"
            "add_library(ramulator SHARED shared.cpp)\n"
            "target_link_libraries(ramulator PRIVATE yaml-cpp)\n"
            'set_target_properties(ramulator PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")\n')
        shims = self.shims()
        command, settings = build.cmake_command(self.sources, self.build, self.tools, self.config_path,
                                                self.config_sha256, shims["ar"], shims["ranlib"])
        self.execute(command, self.build)
        self.assertEqual(self.records(), [], "compiler probes must not create selected dependency receipts")
        self.execute([self.tools["cmake"]["path"], "--build", str(self.build / "ramulator"),
                      "--target", "ramulator", "--parallel", "2", "--verbose"], self.build)
        rows = self.records()
        self.assertEqual(Counter(row["role"] for row in rows), {"compile": 2, "archive": 1, "index": 1, "link": 1})
        created = next(row for row in rows if row["role"] == "archive")
        indexed = next(row for row in rows if row["role"] == "index")
        linked = next(row for row in rows if row["role"] == "link")
        self.assertEqual(created["requested_arguments"][0], "qc")
        self.assertEqual(indexed["output_before"], created["output"])
        self.assertEqual(linked["output_path"], str(ramulator / "libramulator.so"))
        self.assertIn(indexed["output"], linked["inputs_before"])
        members = binary.parse_archive(Path(indexed["output_path"]).read_bytes())["members"]
        binary.validate_link_map((self.build / "ramulator.map").read_text(),
            cwd=str(self.build / "ramulator"), archives={indexed["output_path"]: members},
            required_archives=[indexed["output_path"]])
        database = json.loads((self.build / "ramulator/compile_commands.json").read_text())
        self.assertEqual(len(database), 2)
        self.assertTrue(all(settings[key] == value for key, value in graph.CMAKE_OPTIONS.items()))
        extension_source = ramulator / "src/dram/impl/GDDR6.cpp"
        extension_source.parent.mkdir(parents=True)
        header = self.sources / "spdlog/include/dependency.h"
        header.parent.mkdir(parents=True)
        header.write_text("int sample(void);\n")
        extension_source.write_text("#include <dependency.h>\nint extension(void) { return sample(); }\n")
        compile_command, link_command = build.extension_commands(
            self.sources, self.build, self.tools, self.config_path, self.config_sha256)
        self.execute(compile_command, self.build / "extension")
        self.execute(link_command, self.build / "extension")
        extension_records = [row for row in self.records() if "/extension/" in row["output_path"]]
        self.assertEqual(Counter(row["role"] for row in extension_records), {"compile": 1, "link": 1})
        compiled = next(row for row in extension_records if row["role"] == "compile")
        self.assertIn(str(header), [row["path"] for row in compiled["inputs_before"]])
        self.assertIn("-MD", compiled["arguments"])
        extension_link = next(row for row in extension_records if row["role"] == "link")
        self.assertIn(linked["output"], extension_link["inputs_before"])
        binary.validate_link_map((self.build / "extension.map").read_text(),
            cwd=str(self.build / "extension"), archives={}, required_loads=[str(ramulator / "libramulator.so")])

    def test_stage_is_exclusive_and_rejects_aliases(self):
        original = self.root / "original"
        original.write_bytes(b"fresh dependency")
        destination = self.root / "stage/product"
        row = build.stage_file(original, destination)
        self.assertEqual(row, build.identity(destination))
        with self.assertRaisesRegex(ValueError, "not fresh"):
            build.stage_file(original, destination)
        alias = self.root / "alias"
        alias.symlink_to(original)
        with self.assertRaisesRegex(ValueError, "symlink"):
            build.stage_file(alias, self.root / "stage/alias-product")
        hardlink = self.root / "hardlink"
        os.link(original, hardlink)
        with self.assertRaisesRegex(ValueError, "hard links"):
            build.stage_file(original, self.root / "stage/hardlink-product")

    def test_pinned_literal_parentheses_do_not_relax_root_or_shell_rules(self):
        original = self.sources / "How-To-Parse-A-Document-(Old-API).md"
        original.write_bytes(b"pinned source documentation\n")
        destination = self.packet / "sources/yaml-cpp/docs" / original.name
        row = build.stage_file(original, destination)
        self.assertEqual(row, build.identity(destination))
        self.assertEqual(destination.read_bytes(), original.read_bytes())
        with self.assertRaisesRegex(ValueError, "safe literals"):
            build.canonical(original, existing=True)
        with self.assertRaisesRegex(ValueError, "safe literal"):
            build.canonical(self.sources / "$(command)", inventory_file=True)

    def test_receipt_lock_is_only_permitted_nondocument_and_must_be_empty(self):
        lock = self.packet / "records/.records.lock"
        lock.write_bytes(b"")
        self.assertEqual(self.records(), [])
        lock.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "lock differs"):
            self.records()
        lock.write_bytes(b"")
        (self.packet / "records/unexpected").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "inventory is invalid"):
            self.records()

    def test_clean_environment_removes_caller_compiler_selection(self):
        with mock.patch.dict(os.environ, {"CXX": "unexpected", "CPATH": "/untracked", "MAKEFLAGS": "-j64"}):
            environment = build.clean_environment(self.build)
        self.assertFalse(set(recorder.INJECTION_ENVIRONMENT) & set(environment))
        self.assertNotIn("CXX", environment)
        self.assertEqual(environment["MAKEFLAGS"], "-j2")
        self.assertEqual(environment["CMAKE_BUILD_PARALLEL_LEVEL"], "2")

    def test_first_failure_remains_primary_and_no_pass_flag_survives(self):
        producer = object.__new__(build.Builder)
        producer.report = {"outcome": "pass", "reason": None, "failures": [],
                           "commands": [{"process_started": True}], "fresh_dependency_build_passed": True}
        producer.fail(ValueError("compiler failed"), "execution")
        producer.fail(ValueError("retention also failed"), "final-retention")
        self.assertEqual(producer.report["reason"], "compiler failed")
        self.assertEqual(producer.report["outcome"], "fail")
        self.assertFalse(producer.report["fresh_dependency_build_passed"])
        self.assertEqual(len(producer.report["failures"]), 2)

    def test_resource_block_retains_original_preparation_and_failure(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        preparation = self.root / "preparation.json"
        revision = "1" * 40
        body = {"contract_id": "p06-dependency-preparation-v1",
                "outcome": "pass", "reason": None, "expected_revision": revision,
                "dependency_contract_sha256": contract.contract_hash(), "dependency_cache_used": False}
        build.write_json(preparation, body)
        args = SimpleNamespace(source_dir=build.ROOT, workspace_dir=workspace,
            preparation=preparation, output_dir=workspace / "evidence", expected_revision=revision)
        with mock.patch.object(build, "collect_source", return_value={"revision": revision}), \
                mock.patch.object(build.base, "_source_ok"), \
                mock.patch.object(build.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            report = build.build(args)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("15 GiB", report["reason"])
        self.assertFalse(report["fresh_dependency_build_passed"])
        self.assertEqual(report["commands"], [])
        self.assertFalse((workspace / "dependency-sources").exists())
        self.assertFalse((workspace / "dependency-build").exists())
        self.assertEqual((args.output_dir / "preparation.json").read_bytes(), preparation.read_bytes())
        self.assertEqual(json.loads((args.output_dir / "report.json").read_text()), report)
        self.assertTrue(all(report[name] is False for name in contract.FALSE_CLAIMS))


if __name__ == "__main__":
    unittest.main()
