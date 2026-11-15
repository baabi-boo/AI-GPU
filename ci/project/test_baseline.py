# Licensed under the Apache License, Version 2.0.
"""Independent baseline orchestration checks with inert build fixtures."""

from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import baseline


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "ci/project/p01_baseline.json"
BUNDLES = ROOT / "ci/project/p01_toolchain.lock.json"
SOURCE = {
    "outcome": "pass", "blockers": [], "revision": "a" * 40,
    "tree": "b" * 40, "dirty": False, "pins": {"TOOLCHAIN_REV": "v3.0.2"},
    "submodules": {"entries": [], "errors": []}, "inputs": [],
}
TOOLS = {"outcome": "pass", "blockers": [], "tools": {"compiler": "c" * 64}}
BUILD = {"outcome": "pass", "blockers": [], "identity_matches": True, "xlen": 64}
HOST = {"outcome": "pass", "blockers": [], "tools": {"g++": {"sha256": "e" * 64}}}


def write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


class BaselineFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.source = self.base / "source"
        self.build = self.base / "build64"
        self.tools = self.base / "tools"
        self.output = self.base / "results"
        for path in (self.source, self.build, self.tools):
            path.mkdir()
        for relative in baseline.DEPENDENCIES:
            write(self.source / relative, "inert pinned dependency\n")
        write(self.source / "configure", "inert configure input\n")
        self.matrix = baseline.load_matrix(MATRIX)
        self.case_map = {case["id"]: case for case in self.matrix["cases"]}
        self.source_record = copy.deepcopy(SOURCE)
        self.tools_record = copy.deepcopy(TOOLS)
        self.build_record = copy.deepcopy(BUILD)
        self.host_record = copy.deepcopy(HOST)
        self.source_probe = self.stack.enter_context(mock.patch.object(
            baseline, "collect_source", side_effect=lambda _: copy.deepcopy(self.source_record)))
        self.tools_probe = self.stack.enter_context(mock.patch.object(
            baseline, "collect_tools", side_effect=lambda *_: copy.deepcopy(self.tools_record)))
        self.build_probe = self.stack.enter_context(mock.patch.object(
            baseline, "collect_build", side_effect=lambda *_: copy.deepcopy(self.build_record)))
        self.host_probe = self.stack.enter_context(mock.patch.object(
            baseline, "collect_host", side_effect=lambda *_: copy.deepcopy(self.host_record)))
        self.executed = []
        self.failure = None
        self.marker = "PASSED!\n"
        self.drift_after_case = False
        self.modify_tools_after_case = False
        self.before_command = None
        self.runner = self.stack.enter_context(mock.patch.object(
            baseline, "run_bounded", side_effect=self.fake_command))

    def argv(self, mode="run", *extra, output=True):
        result = [mode, "--source", str(self.source), "--build-dir", str(self.build),
                  "--tool-dir", str(self.tools), "--matrix", str(MATRIX),
                  "--bundle-manifest", str(BUNDLES), "--min-free-gib", "0.001"]
        if output:
            result.extend(("--output", str(self.output)))
        return result + list(extra)

    def invoke(self, mode="run", *extra, output=True):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = baseline.main(self.argv(mode, *extra, output=output))
        return code, json.loads(stream.getvalue())

    def case_artifacts(self, case, configs=None):
        flags = "-DVX_CFG_XLEN=64 " + (configs or baseline.config_for(case))
        for relative in baseline._stamp_paths(case):
            write(self.build / relative, flags + "\n")
        for relative in (
            "tests/regression/" + case["app"] + "/" + case["app"],
            "tests/regression/" + case["app"] + "/kernel.vxbin",
            "sw/runtime/libvortex-" + case["driver"] + ".so",
            "sw/runtime/lib" + case["driver"] + ".so",
        ):
            write(self.build / relative, "inert binary for " + case["id"])

    def fake_command(self, argv, cwd, environment, logfile, **budget):
        name = logfile.stem
        checkpoint = json.loads((self.output / "report.json").read_text())
        self.assertEqual(checkpoint["active_command"], name)
        self.assertEqual(checkpoint["commands"][-1]["outcome"], "not_run")
        self.assertEqual(Path(cwd), self.build)
        self.executed.append({"id": name, "argv": list(argv), "environment": dict(environment),
                              "budget": budget})
        if self.before_command:
            self.before_command(name)
        is_case = name in self.case_map
        if is_case:
            self.case_artifacts(self.case_map[name], environment["CONFIGS"])
        failed = name == self.failure
        text = "fixture command failed\n" if failed else self.marker if is_case else "fixture command completed\n"
        with logfile.open("x", encoding="utf-8") as stream:
            stream.write(text)
        if is_case and self.drift_after_case:
            self.source_record.update(outcome="blocked", dirty=True, blockers=["source was modified"])
        if is_case and self.modify_tools_after_case:
            self.tools_record["tools"]["compiler"] = "d" * 64
        return {
            "outcome": "fail" if failed else "pass", "exit_code": 17 if failed else 0,
            "reason": "nonzero_exit" if failed else None, "duration_seconds": 0.001,
            "log_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "log_size_bytes": len(text.encode()), "peak_rss_bytes": 4096,
            "cleanup_complete": True, "limitations": [],
        }

    def saved_report(self):
        return json.loads((self.output / "report.json").read_text())

    def assert_no_execution(self):
        self.runner.assert_not_called()
        self.assertEqual(list(self.build.iterdir()), [])


class PlanningTests(BaselineFixture):
    def test_plan_is_read_only_and_keeps_execution_unclaimed(self):
        before = {str(path): path.read_bytes() for path in self.base.rglob("*") if path.is_file()}
        code, report = self.invoke("plan")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["state"], "planned")
        self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"]))
        self.assertFalse(report["phase_complete"])
        self.assertEqual(report["integration"]["outcome"], "blocked")
        self.assertFalse(self.output.exists())
        self.assert_no_execution()
        after = {str(path): path.read_bytes() for path in self.base.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_dirty_or_unpinned_sources_never_launch_commands(self):
        for kind in ("source", "tools"):
            with self.subTest(kind=kind):
                record = self.source_record if kind == "source" else self.tools_record
                record.update(outcome="blocked", blockers=[kind + " identity failed"])
                code, report = self.invoke("run")
                self.assertEqual(code, 1)
                self.assertEqual(report["outcome"], "blocked")
                self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"]))
                self.assert_no_execution()
                self.assertEqual(self.saved_report()["outcome"], "blocked")
                self.output = self.base / "another-results"
                record.update(outcome="pass", blockers=[])

    def test_missing_dependency_and_disk_reserve_block_execution(self):
        (self.source / baseline.DEPENDENCIES[0]).unlink()
        code, report = self.invoke("plan")
        self.assertEqual(code, 1)
        self.assertTrue(any("dependencies" in item for item in report["blockers"]))
        self.assert_no_execution()
        write(self.source / baseline.DEPENDENCIES[0], "restored inert fixture")
        with mock.patch.object(baseline.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
            code, report = self.invoke("plan")
        self.assertEqual(code, 1)
        self.assertTrue(any("reserve" in item for item in report["blockers"]))
        self.assert_no_execution()

    def test_unknown_case_is_rejected_before_output_or_execution(self):
        code, report = self.invoke("run", "--case", "not-a-baseline-case")
        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "blocked")
        self.assertFalse(self.output.exists())
        self.assert_no_execution()

    def test_run_requires_fresh_output_and_preserves_existing_content(self):
        code, report = self.invoke("run", output=False)
        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "blocked")
        self.output.mkdir()
        write(self.output / "valuable.txt", "preserve me")
        code, _ = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual((self.output / "valuable.txt").read_text(), "preserve me")
        self.assert_no_execution()

    def test_source_overlap_and_symlink_paths_are_rejected(self):
        arguments = baseline.argument_parser().parse_args(self.argv("plan"))
        variants = [
            ("build_dir", self.source), ("build_dir", self.source / "src"),
            ("output", self.source / "results"), ("output", self.tools / "results"),
            ("tool_dir", self.source), ("output", self.base / "unsafe;output"),
        ]
        (self.base / "link-source").symlink_to(self.source, target_is_directory=True)
        variants.append(("source", self.base / "link-source"))
        for key, value in variants:
            with self.subTest(key=key, value=value):
                changed = copy.copy(arguments)
                setattr(changed, key, value)
                with self.assertRaises(ValueError):
                    baseline.resolve_paths(changed)
        self.assert_no_execution()


class ExecutionTests(BaselineFixture):
    def test_full_matrix_pass_retains_every_case_without_phase_acceptance(self):
        code, report = self.invoke("run")
        self.assertEqual(code, 0, report)
        self.assertEqual(len(report["cases"]), 6)
        self.assertTrue(all(case["outcome"] == "pass" for case in report["cases"]))
        self.assertTrue(report["coverage"]["full_native_matrix_passed"])
        self.assertFalse(report["phase_complete"])
        self.assertEqual(report["integration"]["outcome"], "blocked")
        self.assertEqual(report["integration"]["target"], "hw_emu")
        self.assertEqual(self.saved_report(), report)
        self.assertNotIn("active_case", report)
        self.assertNotIn("active_command", report)
        self.assertNotIn(str(self.base), json.dumps(report))
        self.assertTrue((self.output / "matrix.json").is_file())
        for case in report["cases"]:
            self.assertTrue(case["reference_marker_verified"])
            self.assertTrue(case["native_flags_verified"])
            for artifact in case["configuration_artifacts"]:
                actual = self.output / artifact["path"]
                self.assertEqual(artifact["sha256"], hashlib.sha256(actual.read_bytes()).hexdigest())

    def test_successful_subset_is_explicitly_incomplete_coverage(self):
        code, report = self.invoke("run", "--case", "gemm-bf16-simx")
        self.assertEqual(code, 0, report)
        self.assertEqual([case["id"] for case in report["cases"]], ["gemm-bf16-simx"])
        self.assertEqual(len(report["coverage"]["required_ids"]), 6)
        self.assertFalse(report["coverage"]["full_matrix_selected"])
        self.assertFalse(report["coverage"]["full_native_matrix_passed"])
        self.assertFalse(report["phase_complete"])

    def test_failed_prerequisite_stops_before_all_cases(self):
        self.failure = "kernel-library"
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual([item["id"] for item in self.executed], ["configure", "kernel-library"])
        self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"]))
        self.assertEqual(report["commands"][-1]["exit_code"], 17)
        self.assertEqual(self.saved_report()["outcome"], "fail")

    def test_failed_case_keeps_prior_pass_and_later_not_run(self):
        self.failure = "gemm-fp16-rtlsim"
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual([case["outcome"] for case in report["cases"]],
                         ["pass", "fail", "not_run", "not_run", "not_run", "not_run"])
        self.assertEqual(self.executed[-1]["id"], self.failure)
        self.assertEqual(report["commands"][-1]["exit_code"], 17)
        self.assertTrue((self.output / report["commands"][-1]["log"]).is_file())
        self.assertFalse(report["coverage"]["full_native_matrix_passed"])

    def test_exit_zero_without_reference_marker_fails_case(self):
        self.marker = "process completed without numerical comparison\n"
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual(report["commands"][-1]["exit_code"], 0)
        self.assertEqual(report["commands"][-1]["outcome"], "pass")
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        self.assertFalse(report["cases"][0]["reference_marker_verified"])
        self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"][1:]))

    def test_generated_identity_failure_stops_before_workload(self):
        def change_build(name):
            if name == "configure":
                self.build_record.update(outcome="blocked", blockers=["wrong generated input"])
        self.before_command = change_build
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual([item["id"] for item in self.executed], ["configure"])
        self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"]))
        self.assertIn("identity", report["reason"])

    def test_source_change_during_case_invalidates_the_passing_exit(self):
        self.drift_after_case = True
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        self.assertEqual(report["commands"][-1]["exit_code"], 0)
        self.assertIn("source changed", report["reason"])
        self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"][1:]))

    def test_tool_change_after_selected_run_invalidates_packet(self):
        self.modify_tools_after_case = True
        code, report = self.invoke("run", "--case", "gemm-fp16-simx")
        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("tool identities changed", report["reason"])
        self.assertFalse(report["coverage"]["full_native_matrix_passed"])

    def test_configuration_drift_fails_reference_pass(self):
        original = self.case_artifacts
        def drift(case, configs=None):
            original(case, configs.replace("-DVX_CFG_FPU_TYPE_STD", "-DVX_CFG_FPU_TYPE_DPI"))
        self.case_artifacts = drift
        code, report = self.invoke("run")
        self.assertEqual(code, 1)
        self.assertTrue(report["cases"][0]["reference_marker_verified"])
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"][1:]))

    def test_matrix_change_between_plan_and_run_blocks_without_commands(self):
        args = baseline.argument_parser().parse_args(self.argv("run"))
        paths = baseline.resolve_paths(args)
        report = baseline.plan_run(args, paths)
        report["matrix"]["sha256"] = "0" * 64
        result = baseline.execute_run(args, report, paths)
        self.assertEqual(result["outcome"], "blocked")
        self.assertTrue(any("matrix changed" in item for item in result["blockers"]))
        self.assert_no_execution()

    def test_source_change_between_plan_and_run_blocks_without_commands(self):
        args = baseline.argument_parser().parse_args(self.argv("run"))
        paths = baseline.resolve_paths(args)
        report = baseline.plan_run(args, paths)
        self.source_record["revision"] = "d" * 40
        result = baseline.execute_run(args, report, paths)
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("source changed", result["reason"])
        self.assert_no_execution()

    def test_selected_budgets_and_clean_environment_reach_every_command(self):
        inherited = {"CONFIGS": "-DVX_CFG_TCU_TYPE_DPI", "PROFILE": "untrusted",
                     "DEBUG": "4", "PERF": "1", "TARGET": "hw", "CC": "inert-compiler",
                     "CXXFLAGS": "untrusted", "LD_PRELOAD": "untrusted", "MAKEFLAGS": "-j99"}
        with mock.patch.dict(os.environ, inherited):
            code, report = self.invoke("run", "--case", "gemm-fp16-simx", "--jobs", "1",
                                       "--timeout-seconds", "7", "--max-log-mib", "2",
                                       "--max-rss-gib", "0.5")
        self.assertEqual(code, 0, report)
        for observed in self.executed:
            environment = observed["environment"]
            for key in set(inherited) - {"CONFIGS", "MAKEFLAGS"}:
                self.assertNotIn(key, environment)
            self.assertEqual(environment["MAKEFLAGS"], "-j1")
            self.assertEqual(environment["THREADS"], "1")
            self.assertEqual(environment["CCACHE_DISABLE"], "1")
            self.assertEqual(observed["budget"]["timeout_seconds"], 7)
            self.assertEqual(observed["budget"]["max_log_bytes"], 2 * baseline.MIB)
            self.assertEqual(observed["budget"]["max_rss_bytes"], baseline.GIB // 2)
            if observed["id"] in self.case_map:
                self.assertEqual(environment["CONFIGS"], baseline.config_for(self.case_map[observed["id"]]))
            else:
                self.assertNotIn("CONFIGS", environment)


class ContractHelpersTests(BaselineFixture):
    def test_only_unique_standalone_reference_pass_is_accepted(self):
        log = self.base / "reference.log"
        for content, expected in (
            ("comparing output\nPASSED!\n", True), ("PASSED!\r\n", True),
            ("not PASSED!\n", False), ("PASSED! extra text\n", False),
            ("PASSED!\nPASSED!\n", False), ("PASSED!\nFAILED!\n", False),
            ("PASSED!\nFound 2 errors!\n", False), ("\n", False),
        ):
            with self.subTest(content=content):
                log.write_text(content)
                self.assertIs(baseline.reference_passed(log), expected)

    def test_budget_rejects_nonfinite_nonpositive_boolean_and_overflow_values(self):
        args = baseline.argument_parser().parse_args(self.argv("plan"))
        for field in ("timeout_seconds", "min_free_gib", "max_log_mib", "max_rss_gib"):
            for value in (0, -1, True, float("nan"), float("inf"), 1e100):
                with self.subTest(field=field, value=value):
                    changed = copy.copy(args)
                    setattr(changed, field, value)
                    with self.assertRaises(ValueError):
                        baseline._budget(changed)
        for jobs in (0, 3, True):
            with self.assertRaises(ValueError):
                baseline.clean_environment({}, jobs=jobs)

    def test_effective_native_type_alias_cannot_contradict_native_suffix(self):
        case = self.case_map["gemm-fp16-rtlsim"]
        args = baseline.argument_parser().parse_args(self.argv("plan", output=False))
        paths = baseline.resolve_paths(args)
        for alias in ("VX_CFG_FPU_TYPE", "VX_CFG_TCU_TYPE"):
            with self.subTest(alias=alias):
                output = self.base / alias
                output.mkdir()
                (output / "artifacts").mkdir()
                paths["output"] = output
                self.case_artifacts(case, baseline.config_for(case) + " -D" + alias + "=DPI")
                with self.assertRaises(ValueError):
                    baseline.capture_case(paths, output, case)


if __name__ == "__main__":
    unittest.main()
