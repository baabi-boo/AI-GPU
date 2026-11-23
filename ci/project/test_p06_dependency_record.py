# SPDX-License-Identifier: Apache-2.0
"""Exercise actual compiler children and failure-preserving dependency receipts."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_record as recorder


class DependencyRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-recorder-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.roots = {name: self.root / name for name in recorder.ROOT_NAMES}
        for path in self.roots.values():
            path.mkdir()
        self.tools = {}
        for name in recorder.TOOLS:
            path = shutil.which(name)
            self.assertIsNotNone(path, name + " must be available for the actual-child test")
            self.tools[name] = recorder.file_identity(path)
        self.config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
                       "contract_sha256": contract.contract_hash(),
                       "roots": {name: str(path) for name, path in self.roots.items()},
                       "tools": self.tools}
        self.config_path = self.root / "config.json"
        self.write_config()
        self.source = self.roots["sources"] / "sample.c"
        self.source.write_text("int sample(void) { return 37; }\n")
        self.output = self.roots["build"] / "sample.o"
        self.environment = mock.patch.dict(os.environ, {
            name: value for name, value in os.environ.items()
            if name not in recorder.INJECTION_ENVIRONMENT}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config, sort_keys=True) + "\n")
        self.config_sha256 = hashlib.sha256(self.config_path.read_bytes()).hexdigest()

    def run_tool(self, tool, role, args, **kwargs):
        result = recorder.run(self.config_path, self.config_sha256, tool, role, args,
                              cwd=self.roots["build"], **kwargs)
        path = self.roots["receipts"] / (result["id"] + ".json")
        self.assertEqual(json.loads(path.read_text()), result)
        return result

    def compile(self, args=None, **kwargs):
        return self.run_tool("gcc", "compile", args or ["-fPIC", "-c", str(self.source),
                                                        "-o", str(self.output)], **kwargs)

    def assert_payload(self, item):
        body = (self.roots["payloads"] / item["payload"]).read_bytes()
        self.assertEqual(hashlib.sha256(body).hexdigest(), item["sha256"])
        self.assertEqual(len(body), item["size_bytes"])

    def test_real_compile_observes_prepass_actual_child_and_isystem_header(self):
        includes = self.roots["sources"] / "include"
        includes.mkdir()
        header = includes / "selected.h"
        header.write_text("#define SELECTED_VALUE 37\n")
        self.source.write_text('#include <selected.h>\nint sample(void) { return SELECTED_VALUE; }\n')
        result = self.compile(["-fPIC", "-isystem", str(includes), "-c", str(self.source),
                               "-o", str(self.output)])
        self.assertEqual(result["outcome"], "pass", result["reason"])
        self.assertIs(result["process_started"], True)
        self.assertEqual(result["exit_code"], 0)
        self.assertIsNone(result["output_before"])
        self.assertIs(result["output_absent_before"], True)
        self.assertEqual([row["stage"] for row in result["children"]], ["dependencies", "tool"])
        self.assertTrue(all(row["process_started"] and row["exit_code"] == 0
                            and row["process_group"] == os.getpgrp() for row in result["children"]))
        self.assertLessEqual(result["children"][0]["finished_ns"], result["children"][1]["started_ns"])
        self.assertEqual(result["inputs_before"], result["inputs_after"])
        self.assertIn(str(header), [row["path"] for row in result["inputs_before"]])
        self.assertEqual(result["arguments"][-5:], ["-MD", "-MF", str(self.output) + ".d", "-MT", str(self.output)])
        self.assertEqual(result["children"][1]["argv"], [self.tools["gcc"]["path"], *result["arguments"]])
        for item in [result["output"], result["dependency_file"], result["dependency_prepass_file"],
                     *result["inputs_before"]]:
            self.assert_payload(item)

    def test_actual_archive_index_and_shared_link_join_input_and_product_bytes(self):
        compiled = self.compile()
        self.assertEqual(compiled["outcome"], "pass", compiled["reason"])
        archive = self.roots["build"] / "libsample.a"
        created = self.run_tool("ar", "archive", ["qc", str(archive), str(self.output)])
        self.assertEqual(created["outcome"], "pass", created["reason"])
        self.assertEqual(created["inputs_before"], [compiled["output"]])
        indexed = self.run_tool("ranlib", "index", [str(archive)])
        self.assertEqual(indexed["outcome"], "pass", indexed["reason"])
        self.assertEqual(indexed["output_before"], created["output"])
        self.assertIs(indexed["output_absent_before"], False)
        self.assertEqual(indexed["inputs_after"], [indexed["output"]])
        library = self.roots["build"] / "libsample.so"
        link_map = self.roots["build"] / "sample.map"
        linked = self.run_tool("g++", "link", ["-shared", str(self.output),
            "-Wl,-Map," + str(link_map), "-o", str(library)])
        self.assertEqual(linked["outcome"], "pass", linked["reason"])
        self.assertEqual(linked["inputs_before"], [compiled["output"]])
        self.assertEqual(linked["inputs_before"], linked["inputs_after"])
        self.assert_payload(linked["output"])
        self.assert_payload(linked["link_map"])

    def test_cmake_launcher_requires_exact_selected_compiler(self):
        args = [self.tools["gcc"]["path"], "-fPIC", "-c", str(self.source), "-o", str(self.output)]
        result = self.compile(args, compiler_launcher=True)
        self.assertEqual(result["outcome"], "pass", result["reason"])
        self.assertEqual(result["requested_arguments"], args[1:])
        with self.assertRaisesRegex(recorder.RecorderError, "unexpected compiler"):
            self.compile(["/other/gcc", *args[1:]], compiler_launcher=True)

    def test_cmake_existing_depfile_selection_is_preserved_with_full_MD(self):
        depfile = self.roots["build"] / "cmake-object.d"
        result = self.compile(["-fPIC", "-MMD", "-MP", "-MT", "sample.o", "-MF", str(depfile),
                               "-c", str(self.source), "-o", str(self.output)])
        self.assertEqual(result["outcome"], "pass", result["reason"])
        self.assertEqual(result["dependency_file"]["path"], str(depfile))
        self.assertEqual(result["arguments"][-5:], ["-MD", "-MF", str(depfile), "-MT", str(self.output)])

    def test_stale_object_blocks_before_any_child(self):
        self.output.write_bytes(b"old object")
        result = self.compile()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("pre-existing tool output", result["reason"])
        self.assertFalse(result["process_started"])
        self.assertEqual(result["children"], [])
        self.assertIs(result["output_absent_before"], False)
        self.assertEqual(result["output_before"]["sha256"], hashlib.sha256(b"old object").hexdigest())
        self.assertEqual(self.output.read_bytes(), b"old object")

    def test_stale_dependency_file_blocks_before_any_child(self):
        Path(str(self.output) + ".p06-before.d").write_text("stale")
        result = self.compile()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("pre-existing tool output", result["reason"])
        self.assertEqual(result["children"], [])

    def test_duplicate_invocation_cannot_replace_original_receipt(self):
        result = self.compile()
        before = (self.roots["receipts"] / (result["id"] + ".json")).read_bytes()
        with self.assertRaises(FileExistsError):
            self.compile()
        self.assertEqual((self.roots["receipts"] / (result["id"] + ".json")).read_bytes(), before)

    def test_config_digest_mismatch_is_rejected_before_accessing_roots(self):
        with self.assertRaisesRegex(recorder.RecorderError, "config digest mismatch"):
            recorder.run(self.config_path, "0" * 64, "gcc", "compile", ["-c", str(self.source),
                         "-o", str(self.output)], cwd=self.roots["build"])
        self.assertEqual(list(self.roots["receipts"].iterdir()), [])

    def test_wrong_tool_identity_is_rejected(self):
        self.config["tools"]["gcc"]["sha256"] = "0" * 64
        self.write_config()
        with self.assertRaisesRegex(recorder.RecorderError, "selected tool identity differs"):
            self.compile()

    def test_symlink_output_and_source_are_rejected_without_execution(self):
        real = self.roots["sources"] / "real.c"
        self.source.rename(real)
        self.source.symlink_to(real)
        with self.assertRaisesRegex(recorder.RecorderError, "symlink"):
            self.compile()
        self.source.unlink()
        real.rename(self.source)
        destination = self.roots["build"] / "real.o"
        self.output.symlink_to(destination)
        with self.assertRaisesRegex(recorder.RecorderError, "symlink"):
            self.compile()

    def test_unsupported_response_and_forced_input_expansion_reject(self):
        for forbidden in ("@inputs.rsp", "-include", "-imacros", "-fplugin=evil.so", "-specs=evil"):
            with self.subTest(argument=forbidden), self.assertRaisesRegex(recorder.RecorderError,
                                                                           "input expansion"):
                self.compile(["-c", str(self.source), forbidden, "-o", str(self.output)])

    def test_external_output_is_rejected(self):
        with self.assertRaisesRegex(recorder.RecorderError, "outside owned"):
            self.compile(["-c", str(self.source), "-o", str(self.root / "outside.o")])

    def test_input_environment_injection_fails_with_retained_receipt(self):
        with mock.patch.dict(os.environ, {"CPATH": str(self.roots["sources"])}):
            result = self.compile()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("input environment", result["reason"])
        self.assertEqual(result["children"], [])

    def test_empty_compiler_input_environment_is_also_rejected(self):
        with mock.patch.dict(os.environ, {"GCC_EXEC_PREFIX": ""}):
            result = self.compile()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("input environment", result["reason"])
        self.assertEqual(result["children"], [])

    def test_compiler_failure_survives_later_config_failure(self):
        self.source.write_text("int sample(void) { invalid syntax; }\n")
        real_popen = subprocess.Popen

        def popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            original_wait = process.wait

            def wait(*wait_args, **wait_kwargs):
                result = original_wait(*wait_args, **wait_kwargs)
                if result:
                    self.config_path.write_bytes(self.config_path.read_bytes() + b" ")
                return result

            process.wait = wait
            return process

        with mock.patch.object(recorder.subprocess, "Popen", side_effect=popen):
            result = self.compile()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("tool child failed with exit code", result["reason"])
        self.assertTrue(result["process_started"])
        self.assertGreater(result["exit_code"], 0)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["failures"][0]["stage"], "execution")
        self.assertTrue(any(row["stage"] == "final-config" for row in result["failures"]))
        self.assertIsNone(result["output"])

    def test_header_changed_after_prepass_is_rejected(self):
        header = self.roots["sources"] / "selected.h"
        header.write_text("#define VALUE 1\n")
        self.source.write_text('#include "selected.h"\nint sample(void) { return VALUE; }\n')
        real_popen = subprocess.Popen

        def popen(argv, *args, **kwargs):
            if "-c" in argv:
                header.write_text("#define VALUE 2\n")
            return real_popen(argv, *args, **kwargs)

        with mock.patch.object(recorder.subprocess, "Popen", side_effect=popen):
            result = self.compile()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("tool input changed", result["reason"])
        self.assertIsNotNone(result["output"])

    def test_echo_only_selected_tool_cannot_supply_compilation_evidence(self):
        self.config["tools"]["gcc"] = recorder.file_identity(shutil.which("true"))
        self.write_config()
        result = self.compile()
        self.assertEqual(result["outcome"], "fail")
        self.assertFalse(result["process_started"])
        self.assertEqual(result["children"][0]["exit_code"], 0)
        self.assertIsNone(result["output"])

    def test_dependency_parser_rejects_wrong_targets_extra_rules_and_escapes(self):
        for contents in (b"wrong.o: file.c\n", b"sample.o: file.c\nother.o: hidden.c\n",
                         b"sample.o: file\\ name.c\n", b"sample.o: $(hidden)\n",
                         b"sample.o: file.c file.c\n"):
            with self.subTest(contents=contents), self.assertRaises((recorder.RecorderError, ValueError)):
                recorder.dependency_paths(contents, target=self.output, cwd=self.roots["build"])

    def test_link_requires_one_explicit_map_and_fresh_outputs(self):
        self.assertEqual(self.compile()["outcome"], "pass")
        library = self.roots["build"] / "libsample.so"
        with self.assertRaisesRegex(recorder.RecorderError, "explicit linker map"):
            self.run_tool("g++", "link", ["-shared", str(self.output), "-o", str(library)])
        link_map = self.roots["build"] / "existing.map"
        link_map.write_text("stale map")
        result = self.run_tool("g++", "link", ["-shared", str(self.output),
            "-Wl,-Map=" + str(link_map), "-o", str(library)])
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("pre-existing tool output", result["reason"])
        self.assertEqual(result["children"], [])

    def test_thin_archiver_operation_and_role_substitution_reject(self):
        with self.assertRaisesRegex(recorder.RecorderError, "ordinary creation"):
            self.run_tool("ar", "archive", ["crsT", "lib.a", "sample.o"])
        with self.assertRaisesRegex(recorder.RecorderError, "does not match"):
            self.run_tool("gcc", "archive", ["crs", "lib.a", "sample.o"])

    def test_parallel_compiles_keep_distinct_receipts_and_shared_payloads(self):
        second = self.roots["sources"] / "second.c"
        second.write_text("int second(void) { return 91; }\n")
        other_output = self.roots["build"] / "second.o"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.compile), pool.submit(self.compile,
                ["-fPIC", "-c", str(second), "-o", str(other_output)])]
            results = [future.result() for future in futures]
        self.assertTrue(all(result["outcome"] == "pass" for result in results), results)
        self.assertEqual(len({result["id"] for result in results}), 2)
        self.assertEqual(len(list(self.roots["receipts"].glob("*.json"))), 2)
        for result in results:
            for item in result["inputs_before"]:
                self.assert_payload(item)

    def test_cli_executes_the_real_selected_tool(self):
        result = subprocess.run([sys.executable, str(Path(recorder.__file__).resolve()),
            "--config", str(self.config_path), "--config-sha256", self.config_sha256,
            "--tool", "gcc", "--role", "compile", "--compiler-launcher", "--",
            self.tools["gcc"]["path"], "-fPIC", "-c", str(self.source), "-o", str(self.output)],
            cwd=self.roots["build"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        receipts = list(self.roots["receipts"].glob("*.json"))
        self.assertEqual(len(receipts), 1)
        row = json.loads(receipts[0].read_text())
        self.assertEqual(row["outcome"], "pass")
        self.assertEqual(row["children"][1]["argv"][0], self.tools["gcc"]["path"])


if __name__ == "__main__":
    unittest.main()
