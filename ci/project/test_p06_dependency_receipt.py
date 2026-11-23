# SPDX-License-Identifier: Apache-2.0
"""Adversarial inert checks against actual compiler and generated CMake evidence."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from baseline_process import LIMITATIONS
import p06_dependency_build as builder
import p06_dependency_contract as contract
import p06_dependency_receipt as receipt
import p06_dependency_record as recorder
import test_p06_dependency_build as build_tests


class ReceiptReaderTests(unittest.TestCase):
    def test_inert_relative_paths_accept_the_complete_pinned_name_but_not_traversal(self):
        name = "sources/yaml-cpp/docs/How-To-Parse-A-Document-(Old-API).md"
        self.assertEqual(receipt.relative(name), name)
        for name in ("../file", "/file", "a/../file", "a//file", "a/./file", "a\\file", "$(id)", "a;id"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                receipt.relative(name)

    def test_duplicate_nonfinite_and_oversized_json_are_rejected(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff', b'[' * 2000):
            with self.subTest(data=data[:30]), self.assertRaises(ValueError):
                receipt.decode(data)
        with mock.patch.object(contract, "MAX_RECEIPT_BYTES", 4), self.assertRaises(ValueError):
            receipt.decode(b'{"a":0}')

    def test_packet_reader_rejects_symlinks_hardlinks_and_special_files(self):
        with tempfile.TemporaryDirectory(prefix="p06-reader-") as directory:
            root = Path(directory)
            (root / "body").write_bytes(b"bounded")
            read = receipt.PacketReader(root)
            self.assertEqual(read("body"), b"bounded")
            (root / "alias").symlink_to(root / "body")
            with self.assertRaises((OSError, ValueError)):
                read("alias")
            os.link(root / "body", root / "second")
            with self.assertRaisesRegex(ValueError, "regular file"):
                read("body")
            os.mkfifo(root / "fifo")
            with self.assertRaisesRegex(ValueError, "regular file"):
                read("fifo")

    def test_packet_reader_rejects_a_symlink_in_the_directory_chain(self):
        with tempfile.TemporaryDirectory(prefix="p06-reader-") as directory:
            root = Path(directory)
            (root / "actual").mkdir()
            (root / "actual/file").write_bytes(b"bounded")
            (root / "alias").symlink_to(root / "actual", target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                receipt.PacketReader(root)("alias/file")
            with self.assertRaises(ValueError):
                receipt.PacketReader(root / "alias")


class ActualRecordReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-inert-records-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        roots = {name: cls.root / name for name in recorder.ROOT_NAMES}
        for path in roots.values():
            path.mkdir()
        cls.config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
                      "contract_sha256": contract.contract_hash(),
                      "roots": {name: str(path) for name, path in roots.items()},
                      "tools": {name: recorder.file_identity(shutil.which(name)) for name in recorder.TOOLS}}
        config_path = cls.root / "config.json"
        config_path.write_bytes(contract.json_bytes(cls.config) + b"\n")
        cls.config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
        source, output = roots["sources"] / "sample.c", roots["build"] / "sample.o"
        source.write_text("int sample(void) { return 37; }\n")
        environment = builder.clean_environment(roots["build"])
        with mock.patch.dict(os.environ, environment, clear=True):
            compiled = recorder.run(config_path, cls.config_sha256, "gcc", "compile",
                ["-fPIC", "-c", str(source), "-o", str(output)], cwd=roots["build"])
            archive = roots["build"] / "libsample.a"
            created = recorder.run(config_path, cls.config_sha256, "ar", "archive",
                ["qc", str(archive), str(output)], cwd=roots["build"])
            indexed = recorder.run(config_path, cls.config_sha256, "ranlib", "index",
                [str(archive)], cwd=roots["build"])
            linked = recorder.run(config_path, cls.config_sha256, "g++", "link",
                ["-shared", str(output), "-Wl,-Map," + str(roots["build"] / "sample.map"),
                 "-o", str(roots["build"] / "libsample.so")], cwd=roots["build"])
        cls.records = {row["role"]: row for row in (compiled, created, indexed, linked)}
        for row in cls.records.values():
            if row["outcome"] != "pass":
                raise AssertionError(row["reason"])
        cls.payloads = {"payloads/" + path.name: path.read_bytes() for path in roots["payloads"].glob("*.bin")}
        cls.recorder = recorder.file_identity(recorder.__file__)

    def verify(self, value, payloads=None):
        return receipt._validate_record(value, self.config, self.config_sha256,
            (payloads or self.payloads).__getitem__, self.recorder)

    def test_actual_compile_archive_index_and_link_pass_as_inert_data(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("retained execution forbidden")), \
                mock.patch.object(Path, "open", side_effect=AssertionError("producer file access forbidden")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("producer resolution forbidden")):
            for row in self.records.values():
                with self.subTest(role=row["role"]):
                    self.assertEqual(self.verify(row), row)

    def test_missing_duplicate_reordered_or_invented_children_are_rejected(self):
        original = self.records["compile"]
        for children in ([], original["children"][:1], original["children"] * 2, list(reversed(original["children"]))):
            value = deepcopy(original)
            value["children"] = children
            with self.subTest(children=len(children)), self.assertRaises(ValueError):
                self.verify(value)

    def test_failed_not_started_or_cross_group_children_are_rejected(self):
        for field, changed in (("process_started", False), ("exit_code", 1), ("process_group", 123456789)):
            value = deepcopy(self.records["compile"])
            value["children"][0][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(value)

    def test_substituted_tool_source_output_and_config_are_rejected(self):
        original = self.records["compile"]
        changes = (("config_sha256", "0" * 64), ("tool_name", "ar"), ("output_absent_before", False),
                   ("reason", "earlier failure"), ("exit_code", True), ("unlisted", "extra"))
        for key, changed in changes:
            value = deepcopy(original)
            value[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(value)
        for key in ("output", "dependency_file", "dependency_prepass_file"):
            value = deepcopy(original)
            value[key]["sha256"] = "0" * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(value)

    def test_compiler_argument_injection_and_input_closure_removal_are_rejected(self):
        for key in ("arguments", "requested_arguments"):
            value = deepcopy(self.records["compile"])
            value[key].append("-DUNREVIEWED=1")
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(value)
        value = deepcopy(self.records["compile"])
        value["inputs_before"] = value["inputs_before"][1:]
        value["inputs_after"] = value["inputs_before"]
        with self.assertRaises(ValueError):
            self.verify(value)

    def test_index_options_cannot_be_changed_with_self_consistent_child_argv(self):
        value = deepcopy(self.records["index"])
        for key in ("arguments", "requested_arguments"):
            value[key] = ["-D", *value[key]]
        value["children"][0]["argv"].insert(1, "-D")
        with self.assertRaisesRegex(ValueError, "indexing command"):
            self.verify(value)

    def test_payload_substitution_is_rejected_without_reading_producer_paths(self):
        payloads = dict(self.payloads)
        output = self.records["compile"]["output"]
        payloads["payloads/" + output["payload"]] = b"same named unrelated object"
        with self.assertRaisesRegex(ValueError, "retained bytes"):
            self.verify(self.records["compile"], payloads)


class ActualCMakeReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the separately authored real Make/CMake fixture, retaining its
        # tiny generated graph for independent reader mutation tests.
        cls.fixture = build_tests.DependencyBuildTests("test_actual_cmake_records_static_archive_index_and_shared_link_only")
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.test_actual_cmake_records_static_archive_index_and_shared_link_only()
        fixture = cls.fixture
        cls.document = {"paths": {"source": str(builder.ROOT), "sources": str(fixture.sources),
                                  "build": str(fixture.build), "output": str(fixture.packet)},
                        "tools": fixture.tools, "tool_config": {"sha256": fixture.config_sha256},
                        "generated_inputs": [], "compile_database": None}
        _, cls.document["cmake_configuration"] = builder.cmake_command(fixture.sources, fixture.build,
            fixture.tools, fixture.config_path, fixture.config_sha256,
            fixture.packet / "launchers/ar.sh", fixture.packet / "launchers/ranlib.sh")
        cls.payloads = {}
        root = fixture.build / "ramulator"
        for path in sorted(root.rglob("*")):
            if path.is_file() and (path.suffix in (".txt", ".make", ".cmake", ".json") or path.name == "Makefile"):
                name = "build-inputs/" + path.relative_to(root).as_posix()
                raw = path.read_bytes()
                row = {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
                cls.payloads[name] = raw
                cls.document["generated_inputs"].append(row)
                if path.name == "compile_commands.json":
                    cls.document["compile_database"] = row
        cls.records = fixture.records()

    def verify(self, document=None, records=None, payloads=None):
        return receipt._verify_generated_build(document or self.document, records or self.records,
                                                (payloads or self.payloads).__getitem__)

    def mutate_retained(self, name, transform):
        document, payloads = deepcopy(self.document), dict(self.payloads)
        payloads[name] = transform(payloads[name])
        row = next(row for row in document["generated_inputs"] if row["path"] == name)
        row.update(sha256=hashlib.sha256(payloads[name]).hexdigest(), size_bytes=len(payloads[name]))
        return document, payloads

    def test_actual_generated_cache_flags_archives_and_links_pass(self):
        self.verify()

    def test_changed_cmake_cache_configuration_is_rejected_after_rehash(self):
        document, payloads = self.mutate_retained("build-inputs/CMakeCache.txt",
            lambda data: data.replace(b"SPDLOG_FMT_EXTERNAL:UNINITIALIZED=OFF", b"SPDLOG_FMT_EXTERNAL:UNINITIALIZED=ON"))
        self.assertNotEqual(payloads["build-inputs/CMakeCache.txt"], self.payloads["build-inputs/CMakeCache.txt"])
        with self.assertRaisesRegex(ValueError, "cache changes configured"):
            self.verify(document=document, payloads=payloads)

    def test_changed_cmake_target_flags_are_rejected_after_rehash(self):
        name = "build-inputs/CMakeFiles/ramulator.dir/flags.make"
        document, payloads = self.mutate_retained(name, lambda data: data.replace(b"-O3", b"-O0"))
        with self.assertRaisesRegex(ValueError, "generated target flags"):
            self.verify(document=document, payloads=payloads)

    def test_changed_cmake_link_recipe_is_rejected_after_rehash(self):
        name = "build-inputs/CMakeFiles/ramulator.dir/link.txt"
        document, payloads = self.mutate_retained(name, lambda data: data.replace(b" -shared ", b" -shared -Wl,--as-needed "))
        with self.assertRaisesRegex(ValueError, "generated CMake target recipe"):
            self.verify(document=document, payloads=payloads)

    def test_omitted_or_duplicate_generated_target_is_rejected(self):
        for mode in ("omitted", "duplicate"):
            document = deepcopy(self.document)
            if mode == "omitted":
                document["generated_inputs"] = [row for row in document["generated_inputs"]
                    if row["path"] != "build-inputs/CMakeFiles/ramulator.dir/flags.make"]
            else:
                document["generated_inputs"].append(document["generated_inputs"][0])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.verify(document=document)


class OuterRecipeReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = build_tests.DependencyBuildTests("test_actual_make_override_preserves_automatic_outputs_and_archive_order")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        fixture = self.fixture
        if "cmake" not in fixture.tools:
            self.skipTest("CMake identity is required for the reviewed recipe metadata fixture")
        shims = fixture.shims()
        self.document = {"paths": {"source": str(builder.ROOT), "sources": str(fixture.sources),
                                  "build": str(fixture.build), "output": str(fixture.packet)},
                        "tools": fixture.tools, "tool_config": {"sha256": fixture.config_sha256},
                        "environment": fixture.environment, "commands": []}
        softfloat, directory = builder.softfloat_command(fixture.sources, fixture.tools, fixture.config_path, fixture.config_sha256)
        configure, self.document["cmake_configuration"] = builder.cmake_command(fixture.sources, fixture.build,
            fixture.tools, fixture.config_path, fixture.config_sha256, shims["ar"], shims["ranlib"])
        compile_command, link = builder.extension_commands(fixture.sources, fixture.build, fixture.tools,
                                                          fixture.config_path, fixture.config_sha256)
        build = [fixture.tools["cmake"]["path"], "--build", str(fixture.build / "ramulator"),
                 "--target", "ramulator", "--parallel", "2", "--verbose"]
        self.payloads = {"launchers/" + name + ".sh": path.read_bytes() for name, path in shims.items()}
        for identifier, arguments, cwd, timeout in (("softfloat", softfloat, directory, 1800),
                ("ramulator-configure", configure, fixture.build, 120),
                ("ramulator-build", build, fixture.build, 1800),
                ("extension-compile", compile_command, fixture.build / "extension", 1800),
                ("extension-link", link, fixture.build / "extension", 1800)):
            log = "logs/" + identifier + ".log"
            self.payloads[log] = b"bounded recipe metadata fixture\n"
            self.document["commands"].append({"id": identifier, "argv": list(map(str, arguments)), "cwd": str(cwd),
                "environment": dict(fixture.environment), "timeout_seconds": timeout,
                "log": log, "process_started": True, "outcome": "pass", "exit_code": 0, "reason": None,
                "cleanup_complete": True, "duration_seconds": 0.1, "peak_rss_bytes": 100,
                "log_size_bytes": len(self.payloads[log]), "log_sha256": hashlib.sha256(self.payloads[log]).hexdigest(),
                "limitations": list(LIMITATIONS)})

    def verify(self, document=None, payloads=None):
        return receipt._verify_outer_commands(document or self.document, self.fixture.config,
                                              (payloads or self.payloads).__getitem__)

    def test_reviewed_exact_command_metadata_and_wrapper_bytes_pass(self):
        self.assertEqual(len(self.verify()), 5)

    def test_make_target_specialization_and_nested_job_changes_are_rejected(self):
        for index, original, changed in ((0, "-j2", "-j4"), (0, "SPECIALIZE_TYPE=RISCV", "SPECIALIZE_TYPE=8086"),
                                          (2, "ramulator", "all"), (2, "2", "4")):
            document = deepcopy(self.document)
            arguments = document["commands"][index]["argv"]
            arguments[arguments.index(original)] = changed
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.verify(document=document)

    def test_cmake_launcher_cannot_be_consistently_substituted_in_options_and_outer_argv(self):
        document = deepcopy(self.document)
        name = "CMAKE_CXX_COMPILER_LAUNCHER"
        original = document["cmake_configuration"][name]
        document["cmake_configuration"][name] = "/unreviewed/wrapper"
        arguments = document["commands"][1]["argv"]
        arguments[arguments.index("-D" + name + "=" + original)] = "-D" + name + "=/unreviewed/wrapper"
        with self.assertRaisesRegex(ValueError, "recorder launcher"):
            self.verify(document=document)

    def test_retained_archive_wrapper_must_execute_the_exact_recorder(self):
        payloads = dict(self.payloads, **{"launchers/ar.sh": b"#!/bin/sh\nexit 0\n"})
        with self.assertRaisesRegex(ValueError, "archive wrapper"):
            self.verify(payloads=payloads)

    def test_unbounded_environment_resources_and_extra_fields_are_rejected(self):
        for field, value in (("duration_seconds", float("inf")), ("peak_rss_bytes", contract.BUDGET["max_rss_bytes"] + 1),
                             ("exit_code", True), ("unlisted", "field"), ("cleanup_complete", False)):
            document = deepcopy(self.document)
            document["commands"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(document=document)
        document = deepcopy(self.document)
        document["environment"]["PATH"] = "/unreviewed:/usr/bin:/bin"
        for row in document["commands"]:
            row["environment"] = document["environment"]
        with self.assertRaisesRegex(ValueError, "build environment"):
            self.verify(document=document)


if __name__ == "__main__":
    unittest.main()
