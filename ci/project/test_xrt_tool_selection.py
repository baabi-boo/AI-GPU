# Licensed under the Apache License, Version 2.0.
"""Inert compiler-selection checks across working directories and inventory checkpoints."""

import json
import os
from pathlib import Path
import unittest
from unittest import mock

import baseline_host
import xrt_baseline
from test_xrt_baseline import RunnerFixture, STAGES
from xrt_test_support import identity, write_file


VERSIONS = {
    "gcc": b"gcc (fixture) 11.3.0\n",
    "g++": b"g++ (fixture) 11.3.0\n",
    "make": b"GNU Make 4.4.1\n",
    "ld": b"GNU ld (fixture) 2.44\n",
    "as": b"GNU assembler (fixture) 2.44\n",
    "python3": b"Python 3.12.14\n",
    "cmake": b"cmake version 3.31.6\n",
}


class PathSelectionTests(RunnerFixture):
    def setUp(self):
        super().setUp()
        self.caller = self.base / "caller"
        self.child = self.base / "generated-build/sw/runtime/stub"
        self.empty_bin = self.base / "empty-bin"
        self.other_empty_bin = self.base / "other-empty-bin"
        self.empty_bin.mkdir()
        self.other_empty_bin.mkdir()
        for cwd in (self.caller, self.child):
            for directory in (cwd, cwd / "tools"):
                for name in (*VERSIONS, "cc1plus"):
                    write_file(directory / name, "INERT HOST TOOL: " + str(directory / name),
                               executable=True)

    def invalid_paths(self):
        empty, other = str(self.empty_bin), str(self.other_empty_bin)
        return ("", ":", "::", ":" + empty, empty + ":", empty + "::" + other,
                ".", "tools", "./tools", "./tools:" + empty,
                empty + ":./tools:" + other)

    def collect_from(self, cwd, environment):
        def probe(argv, **kwargs):
            selected = Path(argv[0])
            if argv[1:] == ["-print-prog-name=cc1plus"]:
                return 0, str(selected.parent / "cc1plus").encode()
            self.assertEqual(argv[1:], ["--version"])
            return 0, VERSIONS[selected.name]

        previous = Path.cwd()
        try:
            os.chdir(cwd)
            with mock.patch.object(baseline_host, "_probe", side_effect=probe), \
                    mock.patch.object(baseline_host, "_platform", return_value={
                        "system": "Linux", "machine": "x86_64",
                        "libc": {"name": "glibc", "version": "2.41"}}):
                return baseline_host.collect_host(environment)
        finally:
            os.chdir(previous)

    def test_cwd_dependent_paths_are_rejected_even_when_host_inventory_passes(self):
        for path in self.invalid_paths()[1:]:
            with self.subTest(path=path):
                inherited = {"PATH": path}
                caller = self.collect_from(self.caller, inherited)
                child = self.collect_from(self.child, inherited)
                self.assertEqual(caller["outcome"], "pass", caller)
                self.assertEqual(child["outcome"], "pass", child)
                self.assertNotEqual(caller["tools"]["g++"]["sha256"],
                                    child["tools"]["g++"]["sha256"])
                with self.assertRaisesRegex(ValueError, "PATH"):
                    xrt_baseline.clean_environment(
                        self.fixture.manifest, {}, environ=inherited)

    def test_empty_path_is_rejected_before_host_tool_lookup(self):
        with self.assertRaisesRegex(ValueError, "PATH"):
            xrt_baseline.clean_environment(self.fixture.manifest, {}, environ={"PATH": ""})

    def test_absolute_path_keeps_host_identity_stable_across_working_directories(self):
        path = str(self.caller / "tools") + ":" + str(self.empty_bin)
        cleaned = xrt_baseline.clean_environment(
            self.fixture.manifest, {}, environ={"PATH": path})
        self.assertEqual(cleaned["PATH"], path)
        caller = self.collect_from(self.caller, cleaned)
        child = self.collect_from(self.child, cleaned)
        self.assertEqual(caller["outcome"], "pass", caller)
        self.assertEqual(caller, child)
        self.assertEqual(caller["tools"]["g++"]["sha256"],
                         identity(self.caller / "tools/g++")["sha256"])

    def test_invalid_path_blocks_read_only_plan_before_host_or_build_execution(self):
        for path in self.invalid_paths():
            with self.subTest(path=path), mock.patch.dict(os.environ, {"PATH": path}):
                code, report = self.invoke("plan", output=False)
                self.assertEqual(code, 1)
                self.assertEqual(report["outcome"], "blocked")
                self.assertTrue(any("PATH" in item for item in report["blockers"]))
                self.assertEqual(report["commands"], [])
                self.assertEqual(report["integration"]["outcome"], "blocked")
                self.assertIsNone(report["integration"]["exit_code"])
                self.assertNotAccepted(report)
                self.assertFalse(self.fixture.output.exists())
                self.assertEqual(list(self.fixture.build.iterdir()), [])
        self.host_observation.assert_not_called()
        self.runner.assert_not_called()

    def test_invalid_path_run_retains_blocked_checkpoint_without_building(self):
        for index, path in enumerate(self.invalid_paths()):
            self.fixture.output = self.base / ("blocked-output-" + str(index))
            with self.subTest(path=path), mock.patch.dict(os.environ, {"PATH": path}):
                code, report = self.invoke()
                self.assertEqual(code, 1)
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(report["state"], "blocked")
                self.assertTrue(any("PATH" in item for item in report["blockers"]))
                self.assertEqual(report["commands"], [])
                self.assertEqual(report["integration"]["outcome"], "blocked")
                self.assertIsNone(report["integration"]["exit_code"])
                self.assertNotAccepted(report)
                stored = json.loads((self.fixture.output / "report.json").read_text())
                self.assertEqual(stored, report)
                self.assertIn("finished_at", stored)
                self.assertFalse((self.fixture.output / "report.json.tmp").exists())
                self.assertEqual(list(self.fixture.output.joinpath("logs").iterdir()), [])
                self.assertEqual(list(self.fixture.build.iterdir()), [])
        self.host_observation.assert_not_called()
        self.runner.assert_not_called()

    def test_path_becoming_relative_after_plan_preserves_failure_checkpoint(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.caller / "tools")}):
            args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        with mock.patch.dict(os.environ, {"PATH": "./tools"}):
            result = xrt_baseline.execute_run(args, report, paths)
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("PATH", result["reason"])
        self.assertEqual(result["commands"], [])
        self.assertEqual(result["integration"]["outcome"], "not_run")
        self.assertIsNone(result["integration"]["exit_code"])
        self.assertEqual(list(self.fixture.build.iterdir()), [])
        self.assertFinished(result)
        self.host_observation.assert_not_called()
        self.runner.assert_not_called()

    def test_absolute_path_reaches_all_child_stages_unchanged(self):
        path = str(self.caller / "tools") + ":" + str(self.empty_bin)
        with mock.patch.dict(os.environ, {"PATH": path}):
            report = self.run_fixture()
        self.assertEqual(report["outcome"], "pass", report.get("reason"))
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        for call in self.calls:
            self.assertEqual(call["environment"]["PATH"], path)
        for call in self.host_observation.call_args_list:
            self.assertEqual(call.args[0]["PATH"], path)
        self.assertFinished(report)


class NativeCompilerSelectionTests(RunnerFixture):
    def setUp(self):
        super().setUp()
        self.clang = self.fixture.tools / "llvm-vortex/bin/clang"
        self.clangxx = self.fixture.tools / "llvm-vortex/bin/clang++"
        write_file(self.clangxx, "INERT C++ DRIVER DISTINCT FROM CLANG", executable=True)

    def test_inventory_records_actual_clangxx_bytes_separately_from_clang(self):
        report = xrt_baseline.native_inventory(self.fixture.tools, self.bundle)
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        expected = identity(self.clangxx)
        self.assertEqual(report["identities"]["llvm_clangxx"], {
            "resolved": str(self.clangxx), "sha256": expected["sha256"],
            "size_bytes": expected["size_bytes"]})
        self.assertNotEqual(report["identities"]["llvm_clangxx"]["sha256"],
                            report["identities"]["llvm_clang"]["sha256"])

    def test_clangxx_alias_records_the_executable_target_identity(self):
        self.clangxx.unlink()
        self.clangxx.symlink_to("clang")
        report = xrt_baseline.native_inventory(self.fixture.tools, self.bundle)
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        self.assertEqual(report["identities"]["llvm_clangxx"],
                         report["identities"]["llvm_clang"])
        self.assertEqual(report["identities"]["llvm_clangxx"]["resolved"], str(self.clang))

    def test_missing_clangxx_blocks_and_retains_run_before_any_build(self):
        self.clangxx.unlink()
        code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(any("llvm_clangxx" in item for item in report["blockers"]))
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["integration"]["outcome"], "blocked")
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertEqual(list(self.fixture.build.iterdir()), [])
        self.assertEqual(json.loads((self.fixture.output / "report.json").read_text()), report)
        self.assertNotAccepted(report)
        self.host_observation.assert_not_called()
        self.runner.assert_not_called()

    def test_nonexecutable_clangxx_blocks_native_inventory(self):
        self.clangxx.chmod(0o600)
        report = xrt_baseline.native_inventory(self.fixture.tools, self.bundle)
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(any("llvm_clangxx" in item for item in report["blockers"]))
        self.assertNotIn("llvm_clangxx", report["identities"])

    def assertCompilerDrift(self, mutate, *, between_stages=False):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        clang_before = identity(self.clang)
        if between_stages:
            self.after_stage = lambda stage: mutate() if stage == "configure" else None
        else:
            mutate()
        result = xrt_baseline.execute_run(args, report, paths)
        self.assertEqual(result["outcome"], "fail", result.get("reason"))
        self.assertIn("native tool identities changed", result["reason"])
        self.assertEqual([call["id"] for call in self.calls],
                         ["configure"] if between_stages else [])
        self.assertEqual(identity(self.clang), clang_before)
        self.assertEqual(result["integration"]["outcome"], "not_run")
        self.assertIsNone(result["integration"]["exit_code"])
        self.assertNotAccepted(result)
        self.assertFinished(result)
        if not between_stages:
            self.host_observation.assert_not_called()
            self.runner.assert_not_called()

    def test_clangxx_removed_after_plan_is_detected_before_building(self):
        self.assertCompilerDrift(self.clangxx.unlink)

    def test_clangxx_same_size_content_change_after_plan_is_detected(self):
        changed = b"X" * self.clangxx.stat().st_size
        self.assertCompilerDrift(lambda: self.clangxx.write_bytes(changed))

    def test_clangxx_changes_between_stages_stop_before_kernel_compilation(self):
        self.assertCompilerDrift(lambda: self.clangxx.write_bytes(b"CHANGED C++ DRIVER"),
                                 between_stages=True)

    def test_clangxx_alias_retarget_after_plan_is_detected(self):
        alternative = self.clangxx.parent / "alternate-clangxx"
        write_file(alternative, "OTHER INERT C++ DRIVER", executable=True)
        self.clangxx.unlink()
        self.clangxx.symlink_to("clang")

        def retarget():
            self.clangxx.unlink()
            self.clangxx.symlink_to(alternative.name)

        self.assertCompilerDrift(retarget)


if __name__ == "__main__":
    unittest.main()
