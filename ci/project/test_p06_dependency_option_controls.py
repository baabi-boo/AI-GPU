# SPDX-License-Identifier: Apache-2.0
"""Reach recipe-option gates using positive metadata and tiny real host builds.

The outer-command fixture contains synthetic supervision metadata. The generated
CMake and individual tool-receipt fixtures execute tiny host inputs. Neither is
a complete pinned dependency build or a native lifetime original. In particular,
these tests do not replace a whole-original SoftFloat compile-graph mutation.
"""

from copy import deepcopy
import hashlib
import re
import shlex
import unittest

import p06_dependency_build as builder
import p06_dependency_receipt as receipt
import p06_dependency_record as recorder
import test_p06_dependency_build as build_tests
import test_p06_dependency_receipt as receipt_tests


class OuterRecipeOptionControls(unittest.TestCase):
    def setUp(self):
        self.fixture = receipt_tests.OuterRecipeReviewTests(
            "test_reviewed_exact_command_metadata_and_wrapper_bytes_pass")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.document = self.fixture.document
        self.payloads = self.fixture.payloads
        # Every mutation starts from a positive through the unchanged validator.
        self.assertEqual(len(self.verify(self.document)), 5)

    def verify(self, document):
        return receipt._verify_outer_commands(
            document, self.fixture.fixture.config, self.payloads.__getitem__)

    def replace_make_word(self, document, variable, original, replacement):
        arguments = document["commands"][0]["argv"]
        positions = [i for i, value in enumerate(arguments) if value.startswith(variable + "=")]
        self.assertEqual(len(positions), 1)
        position = positions[0]
        value = arguments[position].split("=", 1)[1]
        words = shlex.split(value)

        def render(items):
            if variable in ("COMPILE_C", "MAKELIB"):
                self.assertEqual(items[-1], "$@")
                return shlex.join(items[:-1]) + " $@"
            return " ".join(items)

        # Preserve the original quoting and Make automatic-output spelling;
        # otherwise a formatting-only rejection could hide the option mutation.
        self.assertEqual(render(words), value)
        self.assertEqual(words.count(original), 1)
        index = words.index(original)
        if replacement is None:
            del words[index]
        else:
            words[index] = replacement
        arguments[position] = variable + "=" + render(words)

    def change_cmake(self, document, name, replacement):
        original = document["cmake_configuration"][name]
        self.assertNotEqual(original, replacement)
        arguments = document["commands"][1]["argv"]
        old_argument = "-D" + name + "=" + original
        self.assertEqual(arguments.count(old_argument), 1)
        document["cmake_configuration"][name] = replacement
        arguments[arguments.index(old_argument)] = "-D" + name + "=" + replacement

    def rejects(self, document, reason):
        self.assertNotEqual(document, self.document)
        with self.assertRaisesRegex(ValueError, re.escape(reason)):
            self.verify(document)

    def test_positive_fixture_reaches_complete_outer_recipe_validation(self):
        self.assertEqual(set(self.verify(self.document)), {
            "softfloat", "ramulator-configure", "ramulator-build",
            "extension-compile", "extension-link"})

    def test_softfloat_tls_replacement_changes_both_declaration_and_compile_recipe(self):
        document = deepcopy(self.document)
        for variable in ("SOFTFLOAT_OPTS", "COMPILE_C"):
            self.replace_make_word(document, variable, "-DTHREAD_LOCAL=_Thread_local",
                                   "-DTHREAD_LOCAL=__thread")
        self.rejects(document, "SoftFloat outer recipe or worker bound differs")

    def test_softfloat_tls_removal_changes_both_declaration_and_compile_recipe(self):
        document = deepcopy(self.document)
        for variable in ("SOFTFLOAT_OPTS", "COMPILE_C"):
            self.replace_make_word(document, variable, "-DTHREAD_LOCAL=_Thread_local", None)
        self.rejects(document, "SoftFloat outer recipe or worker bound differs")

    def test_softfloat_round_odd_and_fast_division_removal_reach_recipe_gate(self):
        for option in ("-DSOFTFLOAT_ROUND_ODD", "-DSOFTFLOAT_FAST_DIV32TO16",
                       "-DSOFTFLOAT_FAST_DIV64TO32"):
            with self.subTest(option=option):
                document = deepcopy(self.document)
                for variable in ("SOFTFLOAT_OPTS", "COMPILE_C"):
                    self.replace_make_word(document, variable, option, None)
                self.rejects(document, "SoftFloat outer recipe or worker bound differs")

    def test_wrong_softfloat_specialization_changes_make_and_include_together(self):
        document = deepcopy(self.document)
        arguments = document["commands"][0]["argv"]
        index = arguments.index("SPECIALIZE_TYPE=RISCV")
        arguments[index] = "SPECIALIZE_TYPE=8086"
        self.replace_make_word(document, "COMPILE_C", "-I../../source/RISCV", "-I../../source/8086")
        self.rejects(document, "SoftFloat outer recipe or worker bound differs")

    def test_softfloat_compiler_substitution_reaches_reviewed_launcher_recipe(self):
        document = deepcopy(self.document)
        self.replace_make_word(document, "COMPILE_C", "gcc", "g++")
        self.rejects(document, "SoftFloat outer recipe or worker bound differs")

    def test_softfloat_archiver_and_archive_mode_cannot_change(self):
        for original, replacement in (("ar", "ranlib"), ("crs", "cr")):
            with self.subTest(replacement=replacement):
                document = deepcopy(self.document)
                self.replace_make_word(document, "MAKELIB", original, replacement)
                self.rejects(document, "SoftFloat outer recipe or worker bound differs")

    def test_external_and_standard_fmt_changes_update_declared_and_invoked_settings(self):
        for name in ("SPDLOG_FMT_EXTERNAL", "SPDLOG_FMT_EXTERNAL_HO", "SPDLOG_USE_STD_FORMAT"):
            with self.subTest(name=name):
                document = deepcopy(self.document)
                self.change_cmake(document, name, "ON")
                self.rejects(document, "CMake source/configuration selection changed")

    def test_cmake_language_pic_and_selected_library_modes_cannot_change(self):
        changes = (("CMAKE_BUILD_TYPE", "Debug"), ("CMAKE_CXX_STANDARD", "17"),
                   ("CMAKE_CXX_EXTENSIONS", "ON"), ("CMAKE_POSITION_INDEPENDENT_CODE", "OFF"),
                   ("YAML_BUILD_SHARED_LIBS", "ON"), ("SPDLOG_BUILD_SHARED", "ON"),
                   ("SPDLOG_NO_TLS", "ON"))
        for name, replacement in changes:
            with self.subTest(name=name):
                document = deepcopy(self.document)
                self.change_cmake(document, name, replacement)
                self.rejects(document, "CMake source/configuration selection changed")

    def test_cmake_cannot_enable_fetches_even_with_matching_configure_arguments(self):
        for name in ("FETCHCONTENT_FULLY_DISCONNECTED", "FETCHCONTENT_UPDATES_DISCONNECTED"):
            with self.subTest(name=name):
                document = deepcopy(self.document)
                self.change_cmake(document, name, "OFF")
                self.rejects(document, "CMake source/configuration selection changed")

    def test_selected_cmake_compiler_make_and_link_map_cannot_change(self):
        changes = (("CMAKE_CXX_COMPILER", "/unreviewed/g++"),
                   ("CMAKE_MAKE_PROGRAM", "/unreviewed/make"),
                   ("CMAKE_SHARED_LINKER_FLAGS", "-Wl,-Map," + self.document["paths"]["build"] + "/other.map"))
        for name, replacement in changes:
            with self.subTest(name=name):
                document = deepcopy(self.document)
                self.change_cmake(document, name, replacement)
                self.rejects(document, "CMake compiler or map selection differs")

    def test_cmake_archiver_and_indexer_cannot_bypass_retained_wrappers(self):
        for name, tool in (("CMAKE_AR", "ar"), ("CMAKE_RANLIB", "ranlib")):
            with self.subTest(name=name):
                document = deepcopy(self.document)
                self.change_cmake(document, name, document["tools"][tool]["path"])
                self.rejects(document, "CMake archive tool wrapper differs")

    def test_cmake_cannot_select_another_local_fetched_source(self):
        document = deepcopy(self.document)
        self.change_cmake(document, "FETCHCONTENT_SOURCE_DIR_SPDLOG",
                          document["paths"]["sources"] + "/replacement-spdlog")
        self.rejects(document, "CMake selected different fetched source inputs")

    def test_extension_compiler_and_linker_selection_remain_fixed(self):
        for index in (3, 4):
            with self.subTest(command=self.document["commands"][index]["id"]):
                document = deepcopy(self.document)
                arguments = document["commands"][index]["argv"]
                tool_index = arguments.index("--tool") + 1
                self.assertEqual(arguments[tool_index], "g++")
                arguments[tool_index] = "gcc"
                self.rejects(document, "extension outer recipe differs")

    def test_extension_map_substitution_reaches_its_exact_link_recipe(self):
        document = deepcopy(self.document)
        arguments = document["commands"][4]["argv"]
        original = "-Wl,-Map," + document["paths"]["build"] + "/extension.map"
        arguments[arguments.index(original)] = "-Wl,-Map," + document["paths"]["build"] + "/other.map"
        self.rejects(document, "extension outer recipe differs")


class ActualGeneratedOptionControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = build_tests.DependencyBuildTests(
            "test_actual_cmake_records_static_archive_index_and_shared_link_only")
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.test_actual_cmake_records_static_archive_index_and_shared_link_only()
        fixture = cls.fixture
        cls.document = {"paths": {"source": str(builder.ROOT), "sources": str(fixture.sources),
                                  "build": str(fixture.build), "output": str(fixture.packet)},
                        "tools": fixture.tools, "tool_config": {"sha256": fixture.config_sha256},
                        "generated_inputs": [], "compile_database": None}
        _, cls.document["cmake_configuration"] = builder.cmake_command(
            fixture.sources, fixture.build, fixture.tools, fixture.config_path,
            fixture.config_sha256, fixture.packet / "launchers/ar.sh", fixture.packet / "launchers/ranlib.sh")
        cls.payloads = {}
        root = fixture.build / "ramulator"
        for path in sorted(root.rglob("*")):
            if path.is_file() and (path.suffix in (".txt", ".make", ".cmake", ".json") or path.name == "Makefile"):
                name = "build-inputs/" + path.relative_to(root).as_posix()
                raw = path.read_bytes()
                descriptor = {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
                cls.payloads[name] = raw
                cls.document["generated_inputs"].append(descriptor)
                if path.name == "compile_commands.json":
                    cls.document["compile_database"] = descriptor
        for path in (fixture.packet / "payloads").glob("*.bin"):
            cls.payloads["payloads/" + path.name] = path.read_bytes()
        cls.records = fixture.records()
        cls.recorder_identity = recorder.file_identity(recorder.__file__)

    def setUp(self):
        self.verify_generated(self.document, self.records, self.payloads)
        for record in self.records:
            self.verify_record(record)

    def verify_generated(self, document, records, payloads):
        return receipt._verify_generated_build(document, records, payloads.__getitem__)

    def verify_record(self, record):
        return receipt._validate_record(record, self.fixture.config, self.fixture.config_sha256,
                                        self.payloads.__getitem__, self.recorder_identity)

    def change_retained(self, document, payloads, name, transform):
        original = payloads[name]
        changed = transform(original)
        self.assertNotEqual(changed, original)
        payloads[name] = changed
        row = next(row for row in document["generated_inputs"] if row["path"] == name)
        row.update(sha256=hashlib.sha256(changed).hexdigest(), size_bytes=len(changed))

    def test_actual_tiny_records_and_generated_recipes_pass_without_semantic_patches(self):
        self.assertEqual(len(self.records), 7)
        self.verify_generated(self.document, self.records, self.payloads)

    def test_generated_release_and_linker_flags_reject_after_descriptor_rehash(self):
        changes = ((b"CMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG", b"CMAKE_CXX_FLAGS_RELEASE:STRING=-O0 -DNDEBUG"),
                   (b"CMAKE_STATIC_LINKER_FLAGS:STRING=\n", b"CMAKE_STATIC_LINKER_FLAGS:STRING=-s\n"),
                   (b"CMAKE_SHARED_LINKER_FLAGS_RELEASE:STRING=\n",
                    b"CMAKE_SHARED_LINKER_FLAGS_RELEASE:STRING=-Wl,--as-needed\n"))
        for original, replacement in changes:
            with self.subTest(setting=original):
                document, payloads = deepcopy(self.document), dict(self.payloads)
                self.assertEqual(payloads["build-inputs/CMakeCache.txt"].count(original), 1)
                self.change_retained(document, payloads, "build-inputs/CMakeCache.txt",
                                     lambda data: data.replace(original, replacement))
                with self.assertRaisesRegex(ValueError, "cache changes the selected build environment"):
                    self.verify_generated(document, self.records, payloads)

    def test_generated_archive_and_index_commands_cannot_bypass_wrappers_after_rehash(self):
        for tool in ("ar", "ranlib"):
            with self.subTest(tool=tool):
                document, payloads = deepcopy(self.document), dict(self.payloads)
                wrapper = document["paths"]["output"] + "/launchers/" + tool + ".sh"
                names = [name for name, raw in payloads.items()
                         if name.endswith("/link.txt") and wrapper.encode() in raw]
                self.assertEqual(len(names), 1)
                self.change_retained(document, payloads, names[0],
                                     lambda data: data.replace(wrapper.encode(), document["tools"][tool]["path"].encode()))
                with self.assertRaisesRegex(ValueError, "generated CMake target recipe"):
                    self.verify_generated(document, self.records, payloads)

    def test_self_consistent_archive_argv_change_reaches_generated_recipe_join(self):
        records = deepcopy(self.records)
        changed = next(row for row in records if row["role"] == "archive")
        self.assertEqual(changed["requested_arguments"][0], "qc")
        changed["requested_arguments"][0] = "q"
        changed["arguments"][0] = "q"
        changed["children"][0]["argv"][1] = "q"
        # Internal receipt consistency is insufficient: the generated recipe
        # must still be the selected recipe that actually created the archive.
        self.verify_record(changed)
        with self.assertRaisesRegex(ValueError, "generated CMake target recipe"):
            self.verify_generated(self.document, records, self.payloads)

    def test_self_consistent_executable_substitution_reaches_selected_tool_identity(self):
        for role in ("compile", "archive", "link"):
            with self.subTest(role=role):
                record = deepcopy(next(row for row in self.records if row["role"] == role))
                alternate = "/unreviewed/" + record["tool_name"]
                record["tool"]["path"] = record["tool"]["resolved_path"] = alternate
                for child in record["children"]:
                    child["argv"][0] = alternate
                with self.assertRaisesRegex(ValueError, "selected a different executable"):
                    self.verify_record(record)

    def test_self_consistent_map_argv_changes_reach_retained_link_map_join(self):
        original = next(row for row in self.records if row["role"] == "link")
        map_flag = next(word for word in original["requested_arguments"] if word.startswith("-Wl,-Map,"))
        for mode in ("replace", "remove", "duplicate"):
            with self.subTest(mode=mode):
                record = deepcopy(original)
                arguments = list(record["requested_arguments"])
                index = arguments.index(map_flag)
                if mode == "replace":
                    arguments[index] = map_flag + ".other"
                elif mode == "remove":
                    del arguments[index]
                else:
                    arguments.insert(index, map_flag)
                record["requested_arguments"] = list(arguments)
                record["arguments"] = list(arguments)
                record["children"][0]["argv"] = [record["tool"]["path"], *arguments]
                with self.assertRaisesRegex(ValueError, "link map is not the actual link output"):
                    self.verify_record(record)


if __name__ == "__main__":
    unittest.main()
