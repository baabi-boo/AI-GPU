# SPDX-License-Identifier: Apache-2.0
"""Host-only runner boundaries; process mocks do not establish native coverage."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import p06_mpm_execute as runner


class NativeFixture:
    """Keep real identities and reports while replacing native command execution."""

    def __enter__(self):
        self.stack = ExitStack()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="p06-mpm-runner-"))).resolve()
        self.paths = {name: root / name for name in ("source", "tools", "work", "output")}
        for name in ("source", "tools"):
            self.paths[name].mkdir()
        for name in runner.CRITICAL:
            path = self.paths["source"] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture input: " + name + "\n", encoding="utf-8")
        self.tool_paths = {}
        for name in ("make", "g++", "python3", "executing_python", "verilator"):
            path = self.paths["tools"] / name
            path.write_text("fixture tool: " + name + "\n", encoding="utf-8")
            self.tool_paths[name] = path
        self.checkout = {"revision": "a" * 40, "tree": "b" * 40, "dirty": False, "blockers": []}
        self.tracked = set(runner.CRITICAL)
        self.results = {}
        self.logs = {}
        self.calls = []
        self.after_command = lambda name, cwd: None
        self.stack.enter_context(mock.patch.object(runner, "ROOT", self.paths["source"]))
        self.stack.enter_context(mock.patch.object(
            runner, "LOADED_HELPERS", runner.hash_artifacts(self.paths["source"], runner.HELPERS)))
        self.stack.enter_context(mock.patch.object(
            runner, "collect_source", side_effect=lambda source: copy.deepcopy(self.checkout)))
        self.stack.enter_context(mock.patch.object(
            runner, "_git", side_effect=lambda *args: "\0".join(sorted(self.tracked)).encode()))
        self.stack.enter_context(mock.patch.object(runner, "tools_snapshot", side_effect=self.tools_snapshot))
        self.stack.enter_context(mock.patch.object(runner, "available_memory_bytes", return_value=8 * runner.GIB))
        usage = shutil.disk_usage(root)._replace(free=64 * runner.GIB)
        self.stack.enter_context(mock.patch.object(runner.shutil, "disk_usage", return_value=usage))
        self.bounded = self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.command))
        return self

    def __exit__(self, *error):
        return self.stack.__exit__(*error)

    def tools_snapshot(self, paths, environment, engines):
        return {"tools": {name: runner.file_identity(path) for name, path in self.tool_paths.items()},
                "dependencies": {}, "missing": []}

    def argv(self, *extra):
        return ["--source-dir", str(self.paths["source"]), "--tools-dir", str(self.paths["tools"]),
                "--work-dir", str(self.paths["work"]), "--output", str(self.paths["output"]), *extra]

    def run(self, *extra):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = runner.main(self.argv(*extra))
        report_path = self.paths["output"] / "report.json"
        return code, json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None

    def command(self, argv, cwd, environment, log_path, **budget):
        cwd, log_path = Path(cwd), Path(log_path)
        name = log_path.stem
        self.calls.append({"id": name, "argv": argv, "cwd": cwd, "environment": dict(environment), **budget})
        result = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
                  "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024}
        result.update(self.results.get(name, {}))
        output = "fixture command completed\n"
        if name.endswith("-configure") and result["outcome"] == "pass":
            xlen = next(value.split("=", 1)[1] for value in argv if value.startswith("--xlen="))
            for relative in runner.GENERATED:
                path = cwd / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("generated fixture: " + relative + "\n", encoding="utf-8")
            config = {"XLEN": xlen, "PROFILE": "", "VORTEX_HOME": str(self.paths["source"]),
                      "TOOLDIR": str(self.paths["tools"])}
            for argument in argv:
                if argument.startswith("--osversion="):
                    config["OSVERSION"] = argument.split("=", 1)[1]
            (cwd / "config.mk").write_text(
                "".join(key + " ?= " + value + "\n" for key, value in config.items()), encoding="utf-8")
            for relative in runner.COPIED:
                destination = cwd / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.paths["source"] / relative, destination)
            for relative in runner.UNITS.values():
                (cwd / relative).mkdir(parents=True, exist_ok=True)
        elif name.endswith("-build") and result["outcome"] == "pass":
            engine = name.split("-")[-2]
            binary = cwd / runner.BINARIES[engine]
            binary.write_text("fixture binary for " + name + "\n", encoding="utf-8")
            binary.chmod(0o700)
            if engine == "simx":
                (cwd / "simx_config.stamp").write_text("fixture compiler stamp\n", encoding="utf-8")
        elif name.endswith("-run"):
            width, _, perf, engine, _ = name.split("-")
            if engine == "simx":
                output = f"MPM transport: XLEN={width[2:]} PERF={perf}\nPASSED: 7 MPM transport checks\n"
            else:
                output = (f"PASSED mpm_transport RV{width[2:]} PERF={int(perf == 'on')} TCU=0 "
                          "read_count=7 assertion_count=9 ignored=1 response_edges=2 counter_bits=44\n")
        log_path.write_text(self.logs.get(name, output), encoding="utf-8")
        result.update(log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(),
                      log_size_bytes=log_path.stat().st_size)
        self.after_command(name, cwd)
        return result


class MpmExecuteBoundaryTests(unittest.TestCase):
    def assert_nonqualifying(self, report):
        self.assertFalse(report["qualified"])
        self.assertFalse(report["acceptance_claimed"])
        self.assertEqual(report["absolute_no_wrap_bound"], "not_established")

    def test_cli_choices_defaults_and_invalid_os_bundle(self):
        with NativeFixture() as fixture:
            parser = runner.argument_parser()
            defaults = parser.parse_args(fixture.argv())
            self.assertEqual((defaults.xlen, defaults.engines, defaults.development), ("both", "both", False))
            for arguments in (("--xlen", "128"), ("--engines", "rtlsim"), ("--perf", "0")):
                with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        parser.parse_args(fixture.argv(*arguments))
                    self.assertEqual(error.exception.code, 2)
            code, report = fixture.run("--osversion", "bundle;command")
            self.assertEqual((code, report), (2, None))
            fixture.bounded.assert_not_called()

    def test_existing_output_is_preserved_without_running(self):
        with NativeFixture() as fixture:
            output = fixture.paths["output"]
            output.mkdir()
            sentinel = output / "report.json"
            sentinel.write_text('{"previous": true}\n', encoding="utf-8")
            before = sentinel.read_bytes()
            code, report = fixture.run()
            self.assertEqual(code, 2)
            self.assertEqual(report, {"previous": True})
            self.assertEqual(sentinel.read_bytes(), before)
            self.assertFalse(fixture.paths["work"].exists())
            fixture.bounded.assert_not_called()

    def test_paths_reject_existing_work_overlap_symlink_and_unsafe_literals(self):
        with NativeFixture() as fixture:
            args = runner.argument_parser().parse_args(fixture.argv())
            (fixture.paths["source"] / "tools").mkdir()
            inside_tools = copy.copy(args)
            inside_tools.tools_dir = fixture.paths["source"] / "tools"
            self.assertEqual(runner.resolve_paths(inside_tools)["tools"], inside_tools.tools_dir)
            link = fixture.paths["tools"].parent / "tools-link"
            link.symlink_to(fixture.paths["tools"], target_is_directory=True)
            for attribute, value in (
                ("work_dir", fixture.paths["source"] / "build"),
                ("output", fixture.paths["tools"] / "results"),
                ("output", fixture.paths["work"]),
                ("tools_dir", link),
                ("output", fixture.paths["output"].parent / "unsafe name"),
                ("source_dir", fixture.paths["tools"]),
            ):
                with self.subTest(attribute=attribute, value=value), self.assertRaises(ValueError):
                    candidate = copy.copy(args)
                    setattr(candidate, attribute, value)
                    runner.resolve_paths(candidate)
            fixture.paths["work"].mkdir()
            with self.assertRaisesRegex(ValueError, "work must be fresh"):
                runner.resolve_paths(args)
            fixture.bounded.assert_not_called()

    def test_formal_source_rejects_dirty_untracked_and_blocked_inputs(self):
        for condition in ("dirty", "untracked", "blocked"):
            with self.subTest(condition=condition), NativeFixture() as fixture:
                if condition == "dirty":
                    fixture.checkout["dirty"] = True
                elif condition == "untracked":
                    fixture.tracked.remove("sim/simx/core.cpp")
                else:
                    fixture.checkout["blockers"] = ["submodule unavailable"]
                code, report = fixture.run("--xlen", "32", "--engines", "rtl")
                self.assertEqual(code, 1)
                self.assertEqual(report["outcome"], "blocked")
                self.assertFalse(report["formal_qualification_eligible"])
                self.assertTrue(all(cell["outcome"] == "blocked" for cell in report["cells"] if cell["selected"]))
                fixture.bounded.assert_not_called()

    def test_development_still_requires_revision_and_tree_identity(self):
        for field in ("revision", "tree"):
            with self.subTest(field=field), NativeFixture() as fixture:
                fixture.checkout[field] = "unknown"
                code, report = fixture.run("--development")
                self.assertEqual((code, report["outcome"]), (1, "blocked"))
                self.assertIn("revision/tree", report["reason"])
                fixture.bounded.assert_not_called()

    def test_complete_matrix_has_eight_separate_bounded_executions(self):
        with NativeFixture() as fixture:
            code, report = fixture.run("--osversion", "ubuntu/24_04")
            self.assertEqual((code, report["state"], report["outcome"]), (0, "finished", "pass"))
            expected = {(width, perf, engine) for width in (32, 64)
                        for perf in ("off", "on") for engine in ("rtl", "simx")}
            self.assertEqual({(cell["xlen"], cell["perf"], cell["engine"]) for cell in report["cells"]}, expected)
            self.assertEqual(len(report["cells"]), 8)
            self.assertTrue(all(cell["selected"] and cell["outcome"] == "pass" for cell in report["cells"]))
            self.assertTrue(report["selected_matrix_complete"])
            self.assertTrue(report["full_matrix_completed"])
            self.assertEqual(report["full_matrix_outcome"], "pass")
            self.assertTrue(report["formal_qualification_eligible"])
            self.assert_nonqualifying(report)
            runs = [call for call in fixture.calls if call["id"].endswith("-run")]
            self.assertEqual(len(runs), 8)
            self.assertEqual(len({item["build_dir"] for item in report["variants"]}), 4)
            for call in fixture.calls:
                self.assertEqual(call["max_rss_bytes"], 4 * runner.GIB)
                self.assertEqual(call["min_free_bytes"], 15 * runner.GIB)
                self.assertEqual(call["max_log_bytes"], 16 * runner.MIB)
                self.assertEqual(set(call["resource_paths"]), set(fixture.paths.values()))
                stage = call["id"].rsplit("-", 1)[-1]
                self.assertEqual(call["timeout_seconds"], {"configure": 120, "build": 1800, "run": 180}.get(stage, 30))
            for call in runs:
                self.assertEqual(len(call["argv"]), 1)
                self.assertTrue(Path(call["argv"][0]).is_file())
            for variant in report["variants"]:
                self.assertEqual(variant["generated_before"], variant["generated_after"])
                for artifact in variant["retained_configuration"]:
                    self.assertTrue((fixture.paths["output"] / artifact["path"]).is_file())

    def test_distinct_interpreter_identities_are_retained(self):
        with NativeFixture() as fixture:
            code, report = fixture.run("--xlen", "64", "--engines", "simx")
            self.assertEqual((code, report["outcome"]), (0, "pass"))
            for name in ("python3", "executing_python"):
                identity = runner.file_identity(fixture.tool_paths[name])
                self.assertEqual(report["tools_before"]["tools"][name], identity)
                self.assertEqual(report["tools_after"]["tools"][name], identity)
            self.assertNotEqual(report["tools_before"]["tools"]["python3"],
                                report["tools_before"]["tools"]["executing_python"])
            self.assert_nonqualifying(report)

    def test_missing_executing_interpreter_blocks_before_commands(self):
        with NativeFixture() as fixture:
            inventory = fixture.tools_snapshot(fixture.paths, {}, ())
            del inventory["tools"]["executing_python"]
            inventory["missing"].append("executing_python")
            with mock.patch.object(runner, "tools_snapshot", return_value=inventory):
                code, report = fixture.run("--xlen", "64", "--engines", "simx")
            self.assertEqual((code, report["outcome"]), (1, "blocked"))
            self.assertIn("missing installed prerequisites: executing_python", report["reason"])
            self.assertFalse(report["formal_qualification_eligible"])
            fixture.bounded.assert_not_called()

    def test_subset_success_never_claims_full_matrix(self):
        with NativeFixture() as fixture:
            code, report = fixture.run("--xlen", "64", "--engines", "simx")
            self.assertEqual(code, 0)
            self.assertTrue(report["selected_matrix_complete"])
            self.assertFalse(report["full_matrix_completed"])
            self.assertEqual(report["full_matrix_outcome"], "not_run")
            self.assertFalse(report["formal_qualification_eligible"])
            self.assertEqual(len(report["cells"]), 8)
            selected = [cell for cell in report["cells"] if cell["selected"]]
            self.assertEqual({cell["id"] for cell in selected}, {"rv64-perf-off-simx", "rv64-perf-on-simx"})
            for cell in report["cells"]:
                if not cell["selected"]:
                    self.assertEqual((cell["outcome"], cell["run_outcome"], cell["reason"]),
                                     ("not_run", "not_run", "not selected"))
            self.assert_nonqualifying(report)

    def test_development_full_pass_remains_ineligible(self):
        with NativeFixture() as fixture:
            fixture.checkout.update(dirty=True, blockers=["submodule metadata incomplete"])
            fixture.tracked.remove("sim/simx/core.cpp")
            code, report = fixture.run("--development")
            self.assertEqual((code, report["outcome"]), (0, "pass"))
            self.assertTrue(report["full_matrix_completed"])
            self.assertFalse(report["formal_qualification_eligible"])
            self.assertEqual(report["source_before"]["untracked_critical"], ["sim/simx/core.cpp"])
            self.assert_nonqualifying(report)

    def test_environment_and_make_arguments_scrub_inherited_flags(self):
        poison = {name: "inherited-poison" for name in (
            "CONFIGS", "PROFILE", "DEBUG", "VCD", "DUMP_WAVEFORM", "VORTEX_DEBUG", "VORTEX_DRIVER",
            "SIMX_FLAGS", "LD_PRELOAD", "LD_LIBRARY_PATH", "CFLAGS", "CXXFLAGS", "LDFLAGS", "PYTHONPATH")}
        poison.update(PERF="0", THREADS="99", MAKEFLAGS="-j99", CCACHE_DISABLE="0", PATH="relative:.:/usr/bin")
        with mock.patch.dict(os.environ, poison), NativeFixture() as fixture:
            code, report = fixture.run("--xlen", "32")
            self.assertEqual(code, 0)
            for call in fixture.calls:
                environment = call["environment"]
                self.assertFalse(set(poison).difference({"PERF", "THREADS", "MAKEFLAGS", "CCACHE_DISABLE", "PATH"})
                                 .intersection(environment))
                self.assertEqual((environment["THREADS"], environment["MAKEFLAGS"], environment["CCACHE_DISABLE"]),
                                 ("1", "-j2", "1"))
                self.assertTrue(all(Path(path).is_absolute() for path in environment["PATH"].split(os.pathsep)))
                if "-perf-off-" in call["id"]:
                    self.assertNotIn("PERF", environment)
                    self.assertNotIn("PERF=0", call["argv"])
                if "-perf-on-" in call["id"]:
                    self.assertEqual(environment["PERF"], "1")
                if call["id"].endswith("-build"):
                    self.assertTrue({"-j2", "THREADS=1", "CONFIGS=", "PROFILE="}.issubset(call["argv"]))
                    self.assertIn("PERF=" + ("1" if "-perf-on-" in call["id"] else ""), call["argv"])
                if call["id"].endswith("-configure"):
                    self.assertIn("--profile=", call["argv"])
            self.assertEqual(report["environment"]["HOME"], str(fixture.paths["work"] / "home"))

    def test_nonzero_run_exit_cannot_be_rescued_by_success_banner_or_development(self):
        for development in (False, True):
            with self.subTest(development=development), NativeFixture() as fixture:
                fixture.results["rv32-perf-off-rtl-run"] = {
                    "outcome": "fail", "exit_code": 7, "reason": "nonzero_exit"}
                options = ("--development",) if development else ()
                code, report = fixture.run("--xlen", "32", "--engines", "rtl", *options)
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                failed = next(cell for cell in report["cells"] if cell["id"] == "rv32-perf-off-rtl")
                self.assertEqual((failed["run_outcome"], failed["outcome"], failed["reason"]),
                                 ("fail", "fail", "nonzero_exit"))
                self.assertNotIn("observations", failed)
                command = next(command for command in report["commands"] if command["id"] == failed["run_command"])
                self.assertEqual(command["exit_code"], 7)
                self.assertFalse(report["selected_matrix_complete"])
                self.assertFalse(report["formal_qualification_eligible"])

    def test_missing_wrong_and_duplicate_run_banners_fail(self):
        for engine, text in (
            ("rtl", "PASSED\n"),
            ("rtl", "PASSED mpm_transport RV64 PERF=0 TCU=0 read_count=7 assertion_count=9 ignored=1 response_edges=2 counter_bits=44\n"),
            ("simx", "PASSED: 7 MPM transport checks\n"),
            ("simx", "MPM transport: XLEN=32 PERF=on\nPASSED: 7 MPM transport checks\n"),
            ("simx", "MPM transport: XLEN=32 PERF=off\nPASSED: 0 MPM transport checks\n"),
            ("simx", "MPM transport: XLEN=32 PERF=off\n" * 2 + "PASSED: 7 MPM transport checks\n"),
        ):
            with self.subTest(engine=engine, text=text), NativeFixture() as fixture:
                fixture.logs[f"rv32-perf-off-{engine}-run"] = text
                code, report = fixture.run("--xlen", "32", "--engines", engine)
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                failed = next(cell for cell in report["cells"] if cell["id"] == f"rv32-perf-off-{engine}")
                self.assertEqual((failed["run_outcome"], failed["outcome"]), ("pass", "fail"))
                self.assertRegex(failed["reason"], "marker|banner")

    def test_resource_stop_and_incomplete_cleanup_are_fatal(self):
        for reason, cleanup in (("memory_limit", True), ("disk_reserve", True), ("log_limit", True),
                                ("monitor_failed", True), ("interrupted_signal_15", True), ("timeout", False)):
            with self.subTest(reason=reason, cleanup=cleanup), NativeFixture() as fixture:
                fixture.results["rv32-perf-off-rtl-run"] = {
                    "outcome": "fail", "exit_code": -15, "reason": reason, "cleanup_complete": cleanup}
                code, report = fixture.run("--xlen", "32", "--engines", "rtl", "--development")
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertEqual(report["reason"], "execution stopped: " + reason)
                self.assertFalse(any(call["id"].startswith("rv32-perf-on") for call in fixture.calls))
                pending = next(cell for cell in report["cells"] if cell["id"] == "rv32-perf-on-rtl")
                self.assertEqual(pending["outcome"], "blocked")

    def test_timeout_is_retained_when_later_cell_succeeds(self):
        with NativeFixture() as fixture:
            fixture.results["rv32-perf-off-simx-run"] = {
                "outcome": "fail", "exit_code": -15, "reason": "timeout"}
            code, report = fixture.run("--xlen", "32", "--engines", "simx", "--development")
            self.assertEqual((code, report["outcome"]), (1, "fail"))
            cells = {cell["id"]: cell for cell in report["cells"]}
            failed = cells["rv32-perf-off-simx"]
            self.assertEqual((failed["run_outcome"], failed["outcome"], failed["reason"]),
                             ("fail", "fail", "timeout"))
            self.assertEqual(cells["rv32-perf-on-simx"]["outcome"], "pass")
            self.assertFalse(report["formal_qualification_eligible"])
            self.assert_nonqualifying(report)

    def test_successful_build_without_executable_does_not_run(self):
        for state in ("missing", "not_executable"):
            with self.subTest(state=state), NativeFixture() as fixture:
                def break_binary(name, cwd):
                    if name == "rv32-perf-off-rtl-build":
                        binary = cwd / runner.BINARIES["rtl"]
                        if state == "missing":
                            binary.unlink()
                        else:
                            binary.chmod(0o600)
                fixture.after_command = break_binary
                code, report = fixture.run("--xlen", "32", "--engines", "rtl")
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertIn("binary missing or not executable", report["reason"])
                self.assertFalse(any(call["id"].endswith("-run") for call in fixture.calls))
                self.assertTrue(all(cell["run_outcome"] == "not_run" for cell in report["cells"]))
                self.assertFalse(report["selected_matrix_complete"])

    def test_source_configuration_binary_and_tool_changes_fail_closed(self):
        for changed in ("source", "configuration", "binary", "tool", "executing_python"):
            with self.subTest(changed=changed), NativeFixture() as fixture:
                def mutate(name, cwd):
                    if name != "rv32-perf-off-rtl-run":
                        return
                    target = {
                        "source": fixture.paths["source"] / "sim/simx/core.cpp",
                        "configuration": fixture.paths["work"] / "rv32-perf-off/sw/VX_config.h",
                        "binary": cwd / runner.BINARIES["rtl"],
                        "tool": fixture.tool_paths["make"],
                        "executing_python": fixture.tool_paths["executing_python"],
                    }[changed]
                    target.write_bytes(target.read_bytes() + b"changed\n")
                fixture.after_command = mutate
                code, report = fixture.run("--xlen", "32", "--engines", "rtl")
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertIn("changed", report["reason"])
                self.assertFalse(report["formal_qualification_eligible"])
                self.assertFalse(report["selected_matrix_complete"])
                if changed in ("source", "tool", "executing_python"):
                    self.assertFalse(report[("source" if changed == "source" else "tools") + "_stable"])
                if changed == "executing_python":
                    self.assertEqual(report["tools_before"]["tools"]["python3"],
                                     report["tools_after"]["tools"]["python3"])
                    self.assertNotEqual(report["tools_before"]["tools"]["executing_python"],
                                        report["tools_after"]["tools"]["executing_python"])
                if changed == "binary":
                    cell = next(cell for cell in report["cells"] if "binary_before" in cell)
                    self.assertNotEqual(cell["binary_before"], cell["binary_after"])
                self.assertTrue((fixture.paths["output"] / "logs/rv32-perf-off-rtl-run.log").is_file())

    def test_changed_loaded_helper_blocks_before_commands(self):
        with NativeFixture() as fixture:
            (fixture.paths["source"] / runner.HELPERS[0]).write_text("changed helper\n", encoding="utf-8")
            code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (1, "blocked"))
            self.assertIn("helper bytes changed", report["reason"])
            fixture.bounded.assert_not_called()

    def test_partial_failure_preserves_completed_cell_and_evidence(self):
        with NativeFixture() as fixture:
            fixture.results["rv32-perf-on-rtl-build"] = {
                "outcome": "fail", "exit_code": 2, "reason": "nonzero_exit"}
            code, report = fixture.run("--xlen", "32", "--engines", "rtl")
            self.assertEqual((code, report["state"], report["outcome"]), (1, "finished", "fail"))
            cells = {cell["id"]: cell for cell in report["cells"]}
            passed = cells["rv32-perf-off-rtl"]
            self.assertEqual(passed["outcome"], "pass")
            self.assertEqual(passed["binary_before"], passed["binary_after"])
            self.assertEqual(cells["rv32-perf-on-rtl"]["outcome"], "fail")
            self.assertEqual(cells["rv32-perf-on-rtl"]["run_outcome"], "not_run")
            self.assertFalse(report["full_matrix_completed"])
            for command in report["commands"]:
                data = (fixture.paths["output"] / command["log"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), command["log_sha256"])
                self.assertEqual(len(data), command["log_size_bytes"])
            self.assertTrue(all(variant["retained_configuration"] for variant in report["variants"]))
            self.assertFalse((fixture.paths["output"] / "report.json.tmp").exists())

    def test_configure_failure_keeps_missing_runs_explicit(self):
        with NativeFixture() as fixture:
            fixture.results["rv32-perf-off-configure"] = {
                "outcome": "fail", "exit_code": 1, "reason": "nonzero_exit"}
            code, report = fixture.run("--xlen", "32")
            self.assertEqual((code, report["outcome"]), (1, "blocked"))
            for cell in report["cells"]:
                if cell["selected"] and cell["perf"] == "off":
                    self.assertEqual((cell["outcome"], cell["run_outcome"]), ("blocked", "not_run"))
                    self.assertIn("configure failed", cell["reason"])
                if cell["selected"] and cell["perf"] == "on":
                    self.assertEqual(cell["outcome"], "pass")
            self.assertEqual(report["full_matrix_outcome"], "not_run")
            self.assertFalse(report["selected_matrix_complete"])


class MpmToolSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-mpm-tools-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name in ("make", "g++", "gcc", "ar", "as", "ld", "bash", "python3", "executing-python"):
            path = self.root / name
            path.write_text("executable identity: " + name + "\n", encoding="utf-8")
            path.chmod(0o700)
        self.paths = {"source": self.root, "tools": self.root}
        self.environment = {"PATH": str(self.root)}

    def snapshot(self, executing_python):
        with mock.patch.object(runner.sys, "executable", str(executing_python)):
            return runner.tools_snapshot(self.paths, self.environment, ())

    def test_actual_snapshot_uses_executing_interpreter_independently_of_path(self):
        snapshot = self.snapshot(self.root / "executing-python")
        self.assertEqual(snapshot["missing"], [])
        self.assertEqual(snapshot["tools"]["python3"], runner.file_identity(self.root / "python3"))
        self.assertEqual(snapshot["tools"]["executing_python"],
                         runner.file_identity(self.root / "executing-python"))
        self.assertNotEqual(snapshot["tools"]["python3"]["sha256"],
                            snapshot["tools"]["executing_python"]["sha256"])

    def test_missing_or_unexecutable_executing_interpreter_is_not_replaced_by_path(self):
        unexecutable = self.root / "executing-python"
        unexecutable.chmod(0o600)
        for selected in ("", self.root / "absent-python", unexecutable):
            with self.subTest(selected=selected):
                snapshot = self.snapshot(selected)
                self.assertEqual(snapshot["missing"], ["executing_python"])
                self.assertNotIn("executing_python", snapshot["tools"])
                self.assertIn("python3", snapshot["tools"])

    def test_executing_interpreter_replacement_changes_real_snapshot(self):
        selected = self.root / "executing-python"
        before = self.snapshot(selected)
        selected.write_text("replacement interpreter\n", encoding="utf-8")
        after = self.snapshot(selected)
        self.assertNotEqual(before, after)
        self.assertNotEqual(before["tools"]["executing_python"]["sha256"],
                            after["tools"]["executing_python"]["sha256"])
        self.assertEqual(before["tools"]["python3"], after["tools"]["python3"])


if __name__ == "__main__":
    unittest.main()
