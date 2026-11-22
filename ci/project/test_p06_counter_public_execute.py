# SPDX-License-Identifier: Apache-2.0
"""Host orchestration tests; controlled process records establish no native run."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys
import unittest
from unittest import mock

import p06_counter_public_execute as runner
from test_p06_checked_execute import NativeFixture, boundary_output, header_output


class ModuleObservations:
    """Override controlled observations without changing shared host modules."""

    def __init__(self, module, **observations):
        self._module = module
        self.__dict__.update(observations)

    def __getattr__(self, name):
        return getattr(self._module, name)


class PublicFixture(NativeFixture):
    def __enter__(self):
        super().__enter__()
        # These are synthetic inputs to the real validator, not native evidence.
        # Delegate other attributes dynamically so stderr redirects still work.
        self.stack.enter_context(mock.patch.object(runner, "sys", ModuleObservations(
            runner.sys, version_info=(3, 12, 14), platform="linux")))
        self.stack.enter_context(mock.patch.object(runner, "platform", ModuleObservations(
            runner.platform, python_implementation=lambda: "CPython")))
        self.tracked.update(runner.CRITICAL)
        self.tracked.update(runner.COPIED)
        self.tracked.update(("sw/runtime/common/device.cpp", "sw/runtime/common/queue.cpp",
                             "sw/runtime/simx/vortex.cpp", "sw/runtime/include/vortex2.h"))
        for name in self.tracked:
            path = self.paths["source"] / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("public fixture source: " + name + "\n", encoding="utf-8")
        self.tool_paths["executing_python"] = self.tool_paths["python3"]
        self.stack.enter_context(mock.patch.object(runner, "ROOT", self.paths["source"]))
        self.stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS",
            runner.hash_artifacts(self.paths["source"], runner.HELPERS)))
        self.stack.enter_context(mock.patch.object(runner, "collect_source", side_effect=lambda _: copy.deepcopy(self.checkout)))
        self.stack.enter_context(mock.patch.object(runner, "_git",
            side_effect=lambda *args: "\0".join(sorted(self.tracked)).encode()))
        self.stack.enter_context(mock.patch.object(runner, "available_memory_bytes", return_value=8 * runner.GIB))
        self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.command))
        self.public_validator = self.stack.enter_context(mock.patch.object(
            runner.public_build, "validate_build", side_effect=self.validate_public))
        self.output_validator = self.stack.enter_context(mock.patch.object(
            runner.public_records, "verify_output", side_effect=self.validate_output))
        return self

    def run(self, *extra):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            code = runner.main(self.argv(*extra))
        path = self.paths["output"] / "report.json"
        return code, json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def configure(self, argv, build):
        super().configure(argv, build)
        for name in runner.COPIED:
            path = build / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.paths["source"] / name).read_bytes())

    def build(self, name, cwd):
        if name != "public-build":
            return super().build(name, cwd)
        build = cwd.parents[1]
        for relative in (*runner.public_build.STAMPS, *runner.public_build.ARTIFACTS):
            path = build / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("public fixture artifact: " + relative + "\n", encoding="utf-8")
            path.chmod(0o700)
        self.public_objects = []
        for index in range(19):
            path = build / runner.PUBLIC_DIR / "obj" / ("fixture-" + str(index) + ".o")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("controlled public object " + str(index) + "\n", encoding="utf-8")
            self.public_objects.append(path)
        return "controlled public build process; compiler parser is tested separately\n"

    def validate_public(self, text, words, stamps, **context):
        self.asserted_public_context = context
        if not text.startswith("controlled public build process"):
            raise ValueError("controlled public build rejected")
        return {"object_identities": runner.file_identities(self.public_objects),
                "translation_units": 19, "link_count": 4}

    def validate_output(self, text, mode):
        expected = {"mode": mode, "host_fixture": True, "qualified": False, "ready_for_warm": False}
        if json.loads(text) != expected:
            raise ValueError("controlled public result rejected")
        return expected

    def command(self, argv, cwd, environment, log_path, **budget):
        cwd, log_path = Path(cwd), Path(log_path)
        name = log_path.stem
        self.calls.append({"id": name, "argv": list(argv), "cwd": cwd, "environment": dict(environment), **budget})
        result = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
                  "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024}
        result.update(self.results.get(name, {}))
        output = "controlled process completed\n"
        if name == "checked-configure" and result["outcome"] == "pass":
            self.configure(argv, cwd)
        elif name.endswith("-build") and result["outcome"] == "pass":
            output = self.build(name, cwd)
        elif name == "checked-header":
            output = header_output(True)
        elif name == "checked-boundaries":
            output = boundary_output(True)
        elif name.removeprefix("public-") in runner.MODES:
            output = json.dumps({"mode": name.removeprefix("public-"), "host_fixture": True,
                                 "qualified": False, "ready_for_warm": False})
        replacement = self.logs.get(name, output)
        output = replacement(output) if callable(replacement) else replacement
        log_path.write_text(output, encoding="utf-8")
        result.update(log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(), log_size_bytes=log_path.stat().st_size)
        self.after_command(name, cwd)
        return result


class PublicExecuteTests(unittest.TestCase):
    def assert_nonqualifying(self, report):
        self.assertEqual(report["state"], "finished")
        for key in ("qualified", "ready_for_warm", "acceptance_claimed", "phase_acceptance",
                    "performance_acceptance", "full_warm_coverage", "warm_execution"):
            self.assertIs(report[key], False, key)

    def assert_failed(self, code, report, reason=None):
        self.assertEqual(code, 1)
        self.assertIn(report["outcome"], ("fail", "blocked"))
        self.assertFalse(report["native_public_diagnostics_passed"])
        self.assertFalse(report["all_available_selector_transport"])
        self.assert_nonqualifying(report)
        self.assertTrue(report["errors"])
        if reason:
            self.assertIn(reason, "\n".join(item["reason"] for item in report["errors"]))

    def test_controlled_complete_flow_retains_every_execution_binding(self):
        with PublicFixture() as fixture:
            code, report = fixture.run("--expected-revision", "a" * 40, "--osversion", "ubuntu/jammy")
            self.assertEqual(code, 0, report["errors"])
            self.assertEqual(report["contract_id"], "simx-counter-public-native-v1")
            self.assertTrue(report["native_public_diagnostics_passed"])
            self.assertTrue(report["all_available_selector_transport"])
            self.assert_nonqualifying(report)
            self.assertEqual([cell["mode"] for cell in report["cells"]], list(runner.MODES))
            self.assertTrue(all(cell["outcome"] == "pass" for cell in report["cells"]))
            self.assertEqual(report["model_control"]["outcome"], "pass")
            self.assertEqual(len(report["commands"]), 14)
            self.assertEqual(len(report["model"]["compiler_records"]["object_identities"]), 45)
            self.assertEqual(len(report["bindings"]["public-objects"]["before"]), 19)
            self.assertEqual(len(report["bindings"]["public-artifacts"]["before"]), 4)
            for group in report["bindings"].values():
                self.assertEqual(group["before"], group["after"])
            expected_groups = set(report["bindings"])
            for check in report["stability_checks"]:
                if check["stage"].startswith(("before-public-", "after-public-")) and check["stage"] not in (
                        "before-public-build", "after-public-build"):
                    self.assertEqual(set(check["bindings"]), expected_groups)
            retained = {item["path"] for item in report["retained_sources"]}
            for path in ("sw/runtime/common/device.cpp", "sw/runtime/common/queue.cpp", "sw/runtime/simx/vortex.cpp",
                         "sw/runtime/include/vortex2.h", "tests/regression/ai_bench_common/counters.h"):
                self.assertIn("artifacts/source/" + path, retained)
            self.assertEqual(fixture.public_validator.call_count, 1)
            self.assertEqual(fixture.output_validator.call_count, 5)
            self.assertEqual(fixture.asserted_public_context["model_records"], report["model"]["compiler_records"])

    def test_fixed_budgets_and_scrubbed_environment_cover_both_builds_and_all_runs(self):
        with PublicFixture() as fixture, mock.patch.dict(os.environ, {
                "MAKEFLAGS": "-j99", "CONFIGS": "-DSIMX_FUNCTIONAL", "THREADS": "99",
                "LD_PRELOAD": "/foreign.so", "LD_LIBRARY_PATH": "/foreign", "PYTHONPATH": "/foreign"}):
            code, report = fixture.run()
            self.assertEqual(code, 0, report["errors"])
            for call in fixture.calls:
                self.assertEqual(call["min_free_bytes"], 15 * runner.GIB)
                self.assertEqual(call["max_rss_bytes"], 4 * runner.GIB)
                self.assertEqual(call["max_log_bytes"], 16 * 1024 * 1024)
                env = call["environment"]
                self.assertEqual(env["MAKEFLAGS"], "-j2")
                self.assertEqual(env["THREADS"], "1")
                self.assertFalse(set(("CONFIGS", "LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONPATH")) & set(env))
                if call["id"].endswith("-build"):
                    self.assertEqual(call["timeout_seconds"], 1800)
                    for value in ("-j2", "THREADS=1", "PROFILE=p02-tfr", "PERF=1", "CONFIGS=-DSIMX_CHECKED_COUNTERS=1"):
                        self.assertIn(value, call["argv"])
                if call["id"].removeprefix("public-") in runner.MODES:
                    self.assertEqual(env["VORTEX_DRIVER"], "simx")
                    self.assertEqual(call["timeout_seconds"], 180)
                    self.assertEqual(call["argv"][:3], [str(fixture.tool_paths["executing_python"]), "-I", "-c"])
                    self.assertIn("resource.setrlimit(resource.RLIMIT_CORE,(0,0))", call["argv"][3])

    def test_resource_and_source_blockers_prevent_process_start(self):
        for kind in ("disk", "memory", "dirty", "untracked", "revision", "helper"):
            with self.subTest(kind=kind), PublicFixture() as fixture:
                if kind == "disk":
                    fixture.disk.return_value = fixture.disk.return_value._replace(free=15 * runner.GIB - 1)
                elif kind == "memory":
                    fixture.stack.enter_context(mock.patch.object(runner, "available_memory_bytes", return_value=4 * runner.GIB - 1))
                elif kind == "dirty":
                    fixture.checkout["dirty"] = True
                elif kind == "untracked":
                    fixture.tracked.remove("tests/unittest/checked_counters/public_hooks.cpp")
                elif kind == "helper":
                    (fixture.paths["source"] / runner.HELPERS[0]).write_text("changed helper\n", encoding="utf-8")
                code, report = fixture.run(*(["--expected-revision", "f" * 40] if kind == "revision" else []))
                self.assert_failed(code, report)
                self.assertEqual(fixture.calls, [])

    def test_interpreter_identity_must_match_path_and_pin(self):
        for kind in ("path", "version", "implementation", "platform"):
            with self.subTest(kind=kind), PublicFixture() as fixture:
                if kind == "path":
                    fixture.tool_paths["executing_python"] = fixture.paths["tools"] / "executing_python"
                elif kind == "version":
                    fixture.stack.enter_context(mock.patch.object(runner.sys, "version_info", (3, 12, 13)))
                elif kind == "implementation":
                    fixture.stack.enter_context(mock.patch.object(runner.platform, "python_implementation", return_value="Other"))
                else:
                    fixture.stack.enter_context(mock.patch.object(runner.sys, "platform", "darwin"))
                code, report = fixture.run()
                self.assert_failed(code, report, "interpreter")
                self.assertEqual(fixture.calls, [])

    def test_controlled_interpreter_restores_mismatched_outer_observations(self):
        original_sys, original_platform = runner.sys, runner.platform
        validator = runner.interpreter_identity
        host_observations = (sys.version_info, sys.platform, platform.python_implementation())
        outer_sys = ModuleObservations(runner.sys, version_info=(3, 12, 3), platform="darwin")
        outer_platform = ModuleObservations(runner.platform, python_implementation=lambda: "Other")
        with mock.patch.object(runner, "sys", outer_sys), mock.patch.object(runner, "platform", outer_platform):
            with self.assertRaisesRegex(ValueError, "executing interpreter differs"):
                validator({})
            with PublicFixture() as fixture:
                self.assertIs(runner.interpreter_identity, validator)
                self.assertEqual((sys.version_info, sys.platform, platform.python_implementation()), host_observations)
                code, report = fixture.run()
                self.assertEqual(code, 0, report["errors"])
                self.assert_nonqualifying(report)
                self.assertEqual(report["interpreter"], {
                    "version": [3, 12, 14], "implementation": "CPython", "platform": "linux"})
                self.assertEqual(len(fixture.calls), 14)
            self.assertIs(runner.sys, outer_sys)
            self.assertIs(runner.platform, outer_platform)
            with self.assertRaisesRegex(ValueError, "executing interpreter differs"):
                validator({})
        self.assertIs(runner.sys, original_sys)
        self.assertIs(runner.platform, original_platform)
        self.assertEqual((sys.version_info, sys.platform, platform.python_implementation()), host_observations)

    def test_controlled_interpreter_preserves_redirected_validation_error(self):
        with PublicFixture() as fixture:
            self.assertEqual(fixture.run("--expected-revision", "invalid"), (2, None))
            self.assertIn("Public counter runner blocked: invalid expected revision", fixture.stderr.getvalue())
            self.assertEqual(fixture.calls, [])

    def test_failed_build_or_missing_cleanup_is_retained_and_stops_public_runs(self):
        for command, changes in (
                ("checked-build", {"outcome": "fail", "exit_code": 1, "reason": "exit_code"}),
                ("public-build", {"outcome": "fail", "exit_code": 1, "reason": "exit_code"}),
                ("public-normal", {"cleanup_complete": False}),
                ("public-normal", {"exit_code": True}),
                ("public-normal", {"process_started": False})):
            with self.subTest(command=command, changes=changes), PublicFixture() as fixture:
                fixture.results[command] = changes
                code, report = fixture.run()
                self.assert_failed(code, report, command)
                self.assertEqual(fixture.calls[-1]["id"], command)
                self.assertTrue((fixture.paths["output"] / "logs" / (command + ".log")).is_file())
                self.assertFalse(any(cell["outcome"] == "pass" for cell in report["cells"]))

    def test_boundary_and_public_output_rejections_stop_later_scenarios(self):
        for command in ("checked-boundaries", "public-normal"):
            with self.subTest(command=command), PublicFixture() as fixture:
                fixture.logs[command] = "{}\n"
                code, report = fixture.run()
                self.assert_failed(code, report)
                self.assertEqual(fixture.calls[-1]["id"], command)
                cell = report["model_control"] if command == "checked-boundaries" else report["cells"][0]
                self.assertEqual(cell["outcome"], "fail")
                self.assertTrue(cell["run_process_started"])

    def test_every_artifact_group_is_checked_before_following_execution(self):
        cases = {
            "configuration": "sw/VX_config.h",
            "model-stamp": runner.checked.STAMP,
            "generated-diagnostic-source": runner.checked.GENERATED_TCU,
            "model-objects": "sim/simx/obj/core.o",
            "model-binary": "sim/simx/checked_counters_test",
            "header-probe": "checked-header-probe.cpp",
            "public-stamps": runner.public_build.STAMPS[0],
            "public-objects": runner.PUBLIC_DIR + "/obj/fixture-0.o",
            "public-artifacts": runner.public_build.ARTIFACTS[0],
        }
        for group, relative in cases.items():
            with self.subTest(group=group), PublicFixture() as fixture:
                def change(name, cwd):
                    if name == "public-normal":
                        (fixture.paths["work"] / "checked" / relative).write_text("changed input\n", encoding="utf-8")
                fixture.after_command = change
                code, report = fixture.run()
                self.assert_failed(code, report, group)
                self.assertEqual(fixture.calls[-1]["id"], "public-normal")
                self.assertNotEqual(report["bindings"][group]["before"], report["bindings"][group]["after"])

    def test_source_dependency_log_and_retained_copy_drift_are_not_hidden(self):
        for kind in ("source", "dependency", "log", "retained"):
            with self.subTest(kind=kind), PublicFixture() as fixture:
                def change(name, cwd):
                    if name != "public-coherent-terminal":
                        return
                    if kind == "source":
                        path = fixture.paths["source"] / "sw/runtime/common/device.cpp"
                    elif kind == "dependency":
                        path = next(iter(fixture.dependencies.values()))
                    elif kind == "log":
                        path = fixture.paths["output"] / "logs/public-normal.log"
                    else:
                        path = fixture.paths["output"] / "artifacts/source/sw/runtime/common/device.cpp"
                    path.write_text("changed retained evidence\n", encoding="utf-8")
                fixture.after_command = change
                code, report = fixture.run()
                self.assert_failed(code, report)
                self.assertEqual(fixture.calls[-1]["id"], "public-coherent-terminal")

    def test_no_preexisting_or_overlapping_output_is_modified(self):
        with PublicFixture() as fixture:
            fixture.paths["output"].mkdir()
            marker = fixture.paths["output"] / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            code, report = fixture.run()
            self.assertEqual((code, report), (2, None))
            self.assertEqual(marker.read_text(), "preserve")
            self.assertEqual(fixture.calls, [])
        with PublicFixture() as fixture:
            fixture.paths["work"] = fixture.paths["source"] / "work"
            self.assertEqual(fixture.run(), (2, None))
            self.assertEqual(fixture.calls, [])

    def test_symlinked_or_empty_artifact_is_rejected(self):
        for kind in ("symlink", "empty"):
            with self.subTest(kind=kind), PublicFixture() as fixture:
                def change(name, cwd):
                    if name == "public-build":
                        path = fixture.paths["work"] / "checked" / runner.public_build.ARTIFACTS[0]
                        path.unlink()
                        if kind == "symlink":
                            path.symlink_to(fixture.tool_paths["g++"])
                        else:
                            path.write_bytes(b"")
                fixture.after_command = change
                code, report = fixture.run()
                self.assert_failed(code, report, "execution input")
                self.assertEqual(fixture.calls[-1]["id"], "public-build")


if __name__ == "__main__":
    unittest.main()
