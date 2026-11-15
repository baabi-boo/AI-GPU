# Licensed under the Apache License, Version 2.0.
"""Regression checks for changes to execution inputs outside the GPU Git tree."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import baseline
from test_baseline import BaselineFixture, write


class ExecutionIdentityTests(BaselineFixture):
    def test_changed_ignored_dependency_fails_successful_case(self):
        def replace(name):
            if name == "gemm-fp16-simx":
                write(self.source / baseline.DEPENDENCIES[1], "different memory model")
        self.before_command = replace
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertIn("dependency identities changed", report["reason"])
        self.assertEqual(report["commands"][-1]["exit_code"], 0)
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        self.assertNotEqual(report["cases"][0]["dependencies_before"]["artifacts"],
                            report["cases"][0]["dependencies_after"]["artifacts"])
        self.assertTrue(all(item["outcome"] == "not_run" for item in report["cases"][1:]))
        self.assertEqual(self.saved_report()["outcome"], "fail")

    def test_missing_dependency_is_retained_as_a_blocked_identity(self):
        def remove(name):
            if name == "gemm-fp16-simx":
                (self.source / baseline.DEPENDENCIES[2]).unlink()
        self.before_command = remove
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        observed = report["cases"][0]["dependencies_after"]
        self.assertEqual(observed["outcome"], "blocked")
        self.assertEqual(len(observed["artifacts"]), 2)
        self.assertIn(baseline.DEPENDENCIES[2], observed["blockers"][0])

    def test_dependency_changed_after_plan_prevents_all_commands(self):
        args = baseline.argument_parser().parse_args(self.argv("run"))
        paths = baseline.resolve_paths(args)
        report = baseline.plan_run(args, paths)
        write(self.source / baseline.DEPENDENCIES[0], "new SoftFloat archive")
        result = baseline.execute_run(args, report, paths)
        self.assertEqual(result["outcome"], "fail")
        self.assert_no_execution()

    def test_dependency_changed_by_reconfigure_prevents_kernel_launch(self):
        def replace(name):
            if name == "gemm-fp16-simx-configure":
                write(self.source / baseline.DEPENDENCIES[0], "changed during configuration")
        self.before_command = replace
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual(self.executed[-1]["id"], "gemm-fp16-simx-configure")
        self.assertEqual(report["cases"][0]["outcome"], "fail")

    def test_final_dependency_check_invalidates_late_replacement(self):
        calls = 0
        def tools(*_):
            nonlocal calls
            calls += 1
            if calls == 2:
                write(self.source / baseline.DEPENDENCIES[1], "changed after final case")
            return copy.deepcopy(self.tools_record)
        self.tools_probe.side_effect = tools
        code, report = self.invoke("run", "--case", "gemm-fp16-simx")
        self.assertEqual(code, 1)
        self.assertEqual(report["cases"][0]["outcome"], "pass")
        self.assertIn("dependency identities changed", report["reason"])
        self.assertFalse(report["coverage"]["full_native_matrix_passed"])

    def test_host_blocker_stops_before_any_build(self):
        self.host_record.update(outcome="blocked", blockers=["compiler identity missing"])
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("compiler identity missing", report["blockers"])
        self.assert_no_execution()

    def test_host_change_between_plan_and_run_prevents_commands(self):
        args = baseline.argument_parser().parse_args(self.argv("run"))
        paths = baseline.resolve_paths(args)
        report = baseline.plan_run(args, paths)
        self.host_record["tools"]["g++"]["sha256"] = "f" * 64
        result = baseline.execute_run(args, report, paths)
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("host tool identities changed", result["reason"])
        self.assert_no_execution()

    def test_host_change_during_case_prevents_packet_pass(self):
        def change(name):
            if name == "gemm-fp16-simx":
                self.host_record["tools"]["g++"]["sha256"] = "f" * 64
        self.before_command = change
        code, report = self.invoke("run", "--case", "gemm-fp16-simx")
        self.assertEqual(code, 1)
        self.assertIn("host tool identities changed", report["reason"])
        self.assertNotEqual(report["host_before"], report["host_after"])

    def test_tooling_is_independent_and_exact_sources_are_retained(self):
        code, report = self.invoke("run", "--case", "gemm-fp16-simx")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["source_before"]["revision"], "a" * 40)
        self.assertNotEqual(report["tooling_before"]["checkout"]["revision"], "a" * 40)
        self.assertEqual(len(report["tooling_snapshots"]), len(baseline.TOOLING_FILES))
        expected = {item["path"]: item for item in report["tooling_before"]["files"]}
        for item in report["tooling_snapshots"]:
            contents = (self.output / item["path"]).read_bytes()
            self.assertEqual(item["sha256"], hashlib.sha256(contents).hexdigest())
            self.assertEqual(item["sha256"], expected[Path(item["path"]).name]["sha256"])
        self.assertNotIn(str(self.base), json.dumps(report))

    def test_changed_tooling_during_case_fails_before_next_case(self):
        current = baseline.collect_tooling()
        def replace(name):
            if name == "gemm-fp16-simx":
                current["files"][0]["sha256"] = "f" * 64
        self.before_command = replace
        with mock.patch.object(baseline, "collect_tooling", side_effect=lambda: copy.deepcopy(current)):
            code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertIn("executing helper identities changed", report["reason"])
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        self.assertTrue(all(item["outcome"] == "not_run" for item in report["cases"][1:]))

    def test_checkout_metadata_change_does_not_hide_stable_helper_contents(self):
        current = baseline.collect_tooling()
        def metadata_change(name):
            if name == "gemm-fp16-simx":
                current["checkout"]["revision"] = "f" * 40
                current["checkout"]["dirty"] = not current["checkout"]["dirty"]
        self.before_command = metadata_change
        with mock.patch.object(baseline, "collect_tooling", side_effect=lambda: copy.deepcopy(current)):
            code, report = self.invoke("run", "--case", "gemm-fp16-simx")
        self.assertEqual(code, 0, report)
        self.assertNotEqual(report["tooling_before"]["checkout"], report["tooling_after"]["checkout"])
        self.assertEqual(report["tooling_before"]["files"], report["tooling_after"]["files"])

    def test_empty_object_cache_is_explicit_and_reaches_nested_builds(self):
        with mock.patch.dict(os.environ, {"OBJCACHE": "untrusted-cache", "CCACHE_DISABLE": "0"}):
            code, report = self.invoke("run", "--case", "gemm-fp16-simx")
        self.assertEqual(code, 0, report)
        for observed in self.executed:
            self.assertEqual(observed["environment"]["OBJCACHE"], "")
            self.assertEqual(observed["environment"]["CCACHE_DISABLE"], "1")
        for observed in report["commands"]:
            self.assertEqual(observed["environment"]["OBJCACHE"], "")


class LoadedToolingTests(unittest.TestCase):
    def test_modified_source_after_module_import_is_not_misidentified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in baseline.TOOLING_FILES:
                (root / name).write_text("original helper\n")
            loaded = baseline.hash_artifacts(root, list(baseline.TOOLING_FILES))
            with mock.patch.object(baseline, "HERE", root), \
                    mock.patch.object(baseline, "LOADED_TOOLING", loaded):
                self.assertEqual(baseline.collect_tooling()["outcome"], "pass")
                (root / "baseline_matrix.py").write_text("changed after import\n")
                report = baseline.collect_tooling()
            self.assertEqual(report["outcome"], "blocked")
            self.assertIn("changed after import", report["blockers"][0])


if __name__ == "__main__":
    unittest.main()
