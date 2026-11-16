# Licensed under the Apache License, Version 2.0.
"""Orchestration contracts over real, inert files; no GPU compilation is performed."""

from argparse import Namespace
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import baseline_inventory
import local_qualification as runner
import local_qualification_inventory as inventory
from local_qualification_cases import select_cases


PINS = {
    "VORTEX_VERSION": "3.0", "TOOLCHAIN_REV": "v3.0.2",
    "GEM5_REV": "v25.0.0.1", "FIRESIM_REV": "57bb93f1e23daf46198659ddd93608f70121fee0",
}
DEMO_LOG = "\n".join((
    "open device connection", "data type: integer", "number of points: 16",
    "buffer size: 64 bytes", "upload source buffer0", "upload source buffer1",
    "load kernel module", "launch kernel", "download destination buffer",
    "wait for completion", "verify result", "cleanup", "PASSED!", "",
))
GENERATOR = """import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--config')
p.add_argument('--output')
p.add_argument('--format')
p.add_argument('--resolved', action='store_true')
a = p.parse_args()
Path(a.output).write_text('// inert fixture ' + a.format + '\\n' + Path(a.config).read_text())
"""


def write(path, contents, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents if isinstance(contents, bytes) else contents.encode("utf-8"))
    if executable:
        path.chmod(0o700)


def git(root, *arguments):
    environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Local Qualification Fixture",
         "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
         *arguments], env=environment, capture_output=True, text=True, timeout=10,
        check=True,
    ).stdout.strip()


def tree_identity(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(),
                                         path.stat().st_mtime_ns, path.stat().st_mode)
            for path in root.rglob("*") if path.is_file()}


class PathBudgetEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="local-qualification-paths-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        for name in ("source", "tools", "dependencies", "headers"):
            (self.base / name).mkdir()
        self.args = Namespace(
            mode="run", source=self.base / "source", tool_dir=self.base / "tools",
            dependency_source=self.base / "dependencies", header_dir=self.base / "headers",
            build_root=self.base / "build", output=self.base / "output", case=["cp-llc-port"],
            jobs=2, timeout_seconds=1800, max_rss_gib=6, max_log_mib=16, min_free_gib=15,
        )

    def test_fresh_separate_roots_are_resolved_without_creating_them(self):
        paths = runner.resolve_paths(self.args)
        self.assertEqual(paths["build"], self.args.build_root)
        self.assertEqual(paths["output"], self.args.output)
        self.assertFalse(paths["build"].exists())
        self.assertFalse(paths["output"].exists())

    def test_existing_file_directory_fifo_and_dangling_symlink_are_not_fresh(self):
        for kind in ("file", "directory", "fifo", "symlink"):
            path = self.base / kind
            if kind == "file":
                path.write_text("already owned")
            elif kind == "directory":
                path.mkdir()
            elif kind == "fifo":
                os.mkfifo(path)
            else:
                path.symlink_to(self.base / "missing")
            for field in ("build_root", "output"):
                with self.subTest(kind=kind, field=field):
                    args = copy.copy(self.args)
                    setattr(args, field, path)
                    with self.assertRaises(ValueError):
                        runner.resolve_paths(args)

    def test_build_and_output_cannot_overlap_an_input_or_each_other(self):
        for input_name in ("source", "tools", "dependencies", "headers"):
            for field in ("build_root", "output"):
                with self.subTest(input=input_name, field=field):
                    args = copy.copy(self.args)
                    setattr(args, field, self.base / input_name / "new")
                    with self.assertRaises(ValueError):
                        runner.resolve_paths(args)
        self.args.output = self.args.build_root
        with self.assertRaises(ValueError):
            runner.resolve_paths(self.args)

    def test_symlink_traversal_and_shell_metacharacters_are_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.args.source, target_is_directory=True)
        for field, value in (("source", alias), ("build_root", alias / "new"),
                             ("output", self.base / "a b"),
                             ("build_root", self.base / "a;touch-sentinel"),
                             ("output", self.base / "$(touch-sentinel)")):
            with self.subTest(field=field, value=value):
                args = copy.copy(self.args)
                setattr(args, field, value)
                with self.assertRaises(ValueError):
                    runner.resolve_paths(args)

    def test_missing_parent_and_non_directory_inputs_are_rejected(self):
        for field, value in (("build_root", self.base / "absent/new"),
                             ("output", self.base / "absent/new")):
            args = copy.copy(self.args)
            setattr(args, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.resolve_paths(args)
        file = self.base / "file"
        file.write_text("not an input root")
        self.args.source = file
        with self.assertRaises(ValueError):
            runner.resolve_paths(self.args)

    def test_only_plan_can_omit_an_output_root(self):
        self.args.output = None
        with self.assertRaisesRegex(ValueError, "requires --output"):
            runner.resolve_paths(self.args)
        self.args.mode = "plan"
        self.assertIsNone(runner.resolve_paths(self.args)["output"])

    def test_budget_accepts_exact_floors_and_ceilings(self):
        upper = runner._budget(self.args)
        self.assertEqual(upper, {
            "jobs": 2, "timeout_seconds": 1800, "max_rss_bytes": 6 * runner.GIB,
            "max_log_bytes": 16 * runner.MIB, "min_free_bytes": 15 * runner.GIB,
        })
        self.args.jobs = 1
        self.args.timeout_seconds = 1
        self.args.max_rss_gib = 1 / runner.GIB
        self.args.max_log_mib = 1 / runner.MIB
        lower = runner._budget(self.args)
        self.assertEqual(lower["max_rss_bytes"], 1)
        self.assertEqual(lower["max_log_bytes"], 1)
        self.assertEqual(lower["timeout_seconds"], 1)

    def test_budget_rejects_values_outside_fixed_limits_and_nonfinite_inputs(self):
        invalid = {
            "jobs": (0, 3, True, 1.0),
            "timeout_seconds": (0, 0.5, 1801, True, float("nan"), float("inf")),
            "max_rss_gib": (0, 0.5 / runner.GIB, 6.01, -1, "6", 10**400),
            "max_log_mib": (0, 0.5 / runner.MIB, 16.01, False, float("-inf")),
            "min_free_gib": (math.nextafter(15.0, 0), 0, float("inf"), 2**64),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    args = copy.copy(self.args)
                    setattr(args, field, value)
                    with self.assertRaises(ValueError):
                        runner._budget(args)

    def test_hostile_environment_cannot_override_tools_parallelism_or_runtime(self):
        paths = runner.resolve_paths(self.args)
        hostile = {
            "PATH": "/usr/bin:/bin", "HOME": "/fixture/home", "TMPDIR": "/hostile",
            "TMP": "/hostile", "TEMP": "/hostile", "MAKEFLAGS": "-j999 -e",
            "CONFIGS": "-DHOSTILE", "CFLAGS": "-include /hostile.h",
            "CXXFLAGS": "-DHOSTILE", "CPATH": "/hostile", "LIBRARY_PATH": "/hostile",
            "LD_PRELOAD": "/hostile.so", "LD_LIBRARY_PATH": "/hostile",
            "LD_AUDIT": "/hostile.so", "PYTHONPATH": "/hostile", "PYTHONHOME": "/hostile",
            "BASH_ENV": "/hostile.sh", "ENV": "/hostile.sh", "CC": "/hostile/cc",
            "CXX": "/hostile/cxx", "THIRD_PARTY_DIR": "/hostile",
            "CPLUS_INCLUDE_PATH": "/hostile", "XRT_INI_PATH": "/hostile.ini",
            "XCL_EMULATION_MODE": "hw_emu", "XRTSIM_WARM_OPEN": "1",
            "VX_MEM_RSP_REORDER": "7", "VX_MEM_RSP_STALL": "999",
            "VORTEX_DRIVER": "simx", "TARGET": "hw", "DEBUG": "3", "PERF": "7",
            "VORTEX_XRT_WAVEFORM": "1", "GIT_CONFIG_COUNT": "1",
        }
        before = dict(hostile)
        current = runner.clean_environment(paths, jobs=1, environ=hostile)
        self.assertEqual(hostile, before)
        self.assertEqual(current["PATH"], hostile["PATH"])
        self.assertEqual(current["HOME"], hostile["HOME"])
        self.assertEqual(current["MAKEFLAGS"], "-j1")
        self.assertEqual(current["THREADS"], "1")
        self.assertEqual(current["CMAKE_BUILD_PARALLEL_LEVEL"], "1")
        self.assertEqual(current["CCACHE_DISABLE"], "1")
        self.assertEqual(current["OBJCACHE"], "")
        self.assertEqual(current["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(current["THIRD_PARTY_DIR"], str(paths["dependencies"] / "third_party"))
        self.assertEqual(current["CPLUS_INCLUDE_PATH"], str(paths["headers"]))
        self.assertEqual(set(hostile).intersection(current),
                         {"PATH", "HOME", "MAKEFLAGS", "THIRD_PARTY_DIR", "CPLUS_INCLUDE_PATH"})

    def test_empty_or_relative_path_entries_fail_before_any_launch(self):
        paths = runner.resolve_paths(self.args)
        for value in ("", ":/usr/bin", "/usr/bin:", ".:/usr/bin", "relative/bin", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.clean_environment(paths, environ={"PATH": value})


class RunnerFixture:
    def __init__(self, base):
        self.base = base
        self.source = base / "source"
        self.tools = base / "tools"
        self.dependencies = base / "dependencies"
        self.headers = base / "headers"
        self.helpers = base / "helpers"
        self.host = base / "host"
        self.calls = []
        self.checkpoints = []
        self.after_command = lambda name, build: None
        self.failures = {}
        self.logs = {"cp-llc-port": "PASSED\n", "demo": DEMO_LOG}
        self.attempt = 0
        for directory in (self.source, self.tools, self.headers, self.helpers, self.host):
            directory.mkdir(parents=True)
        cases = select_cases(["demo", "cp-llc-port"])
        names = set(baseline_inventory.SOURCE_INPUTS)
        names.update(baseline_inventory.COPIED_BUILD_INPUTS.values())
        names.update(inventory.COPIED_INPUTS.values())
        names.update(path for case in cases for path in case["sources"])
        names.add("third_party/Makefile")
        for name in names:
            write(self.source / name, "inert fixture input: " + name + "\n")
        write(self.source / "VERSION", "".join(key + "=" + value + "\n" for key, value in PINS.items()))
        write(self.source / ".gitignore", "*.so\n*.a\n")
        write(self.source / ".gitmodules", '[submodule "ramulator"]\n'
              '\tpath = third_party/ramulator\n\turl = https://example.invalid/inert-fixture.git\n')
        write(self.source / "config.mk.in", "".join(key + " ?= @" + value + "@\n" for key, value in (
            ("XLEN", "XLEN"), ("TOOLDIR", "TOOLDIR"), ("OSVERSION", "OSVERSION"),
            ("PROFILE", "PROFILE"), ("VORTEX_HOME", "VORTEX_HOME"))))
        write(self.source / "ci/gen_config.py", GENERATOR)
        module = self.source / "third_party/ramulator"
        write(module / "src/dram/impl/GDDR6.cpp", "inert dependency extension\n")
        write(module / ".gitignore", "*.so\n*.a\n")
        for relative in inventory.EXTERNAL_HEADER_ROOTS:
            write(self.source / relative / "fixture.h", "inert external header\n")
        for repository in (module, self.source):
            git(repository, "init", "-q")
            git(repository, "add", ".")
            git(repository, "commit", "-qm", "isolated inert fixture")
        git(self.source, "submodule", "init")
        shutil.copytree(self.source, self.dependencies)
        for name in ("third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
                     "third_party/ramulator/libramulator.so",
                     "third_party/ramulator_ext/libramulator-vortex.so"):
            write(self.dependencies / name, "inert dependency library\n")
        for name in baseline_inventory.TOOL_BINARIES.values():
            write(self.tools / name, "#!/bin/sh\nprintf 'Inert compiler fixture 1.0\\n'\n", True)
        for name in baseline_inventory.LIBRARIES:
            write(self.tools / name, "inert compiler support archive\n")
        write(self.headers / "uuid/uuid.h", "inert UUID header\n")
        versions = {"gcc": "gcc fixture 1.0", "g++": "g++ fixture 1.0",
                    "make": "GNU Make fixture 1.0", "ld": "GNU ld fixture 1.0",
                    "as": "GNU assembler fixture 1.0", "python3": "Python 3.11.0",
                    "cmake": "cmake version 3.0"}
        for name, version in versions.items():
            body = "#!/bin/sh\n"
            if name == "g++":
                body += ('if [ "$1" = "-print-prog-name=cc1plus" ]; then\n'
                         "printf '%s\\n' " + shlex.quote(str(self.host / "cc1plus")) + "\nexit 0\nfi\n")
            write(self.host / name, body + "printf '%s\\n' " + shlex.quote(version) + "\n", True)
        write(self.host / "cc1plus", "#!/bin/sh\nexit 0\n", True)
        for item in inventory.collect_helpers():
            shutil.copy2(inventory.HERE / item["path"], self.helpers / item["path"])
        self.environment = {"PATH": str(self.host) + os.pathsep + os.defpath,
                            "HOME": str(base / "home")}
        self.args = Namespace(mode="run", source=self.source, tool_dir=self.tools,
                              dependency_source=self.dependencies, header_dir=self.headers,
                              case=["cp-llc-port"], jobs=1, timeout_seconds=30,
                              max_rss_gib=1, max_log_mib=1, min_free_gib=15,
                              build_root=None, output=None)
        self.fresh_paths()

    def fresh_paths(self):
        self.attempt += 1
        self.args.build_root = self.base / ("build-" + str(self.attempt))
        self.args.output = self.base / ("output-" + str(self.attempt))
        self.paths = runner.resolve_paths(self.args)

    def configure(self, build):
        stamp = {"XLEN": "64", "TOOLDIR": str(self.tools), "OSVERSION": "ubuntu/focal",
                 "PREFIX": str(build / "install"), "PROFILE": "", "SOURCE_DIR": str(self.source),
                 "BUILDDIR": str(build), **PINS}
        substitutions = dict(stamp, VORTEX_HOME=str(self.source), INSTALLDIR=stamp["PREFIX"])
        write(build / ".config.stamp", " ".join(key + "=" + value for key, value in stamp.items()))
        copies = {"config.mk": "config.mk.in", "ci/blackbox.sh": "ci/blackbox.sh",
                  **baseline_inventory.COPIED_BUILD_INPUTS, **inventory.COPIED_INPUTS}
        for case in select_cases(self.args.case):
            prefix = "tests/regression/" if case["kind"] == "app" else "hw/unittest/"
            relative = prefix + case["app"] + "/Makefile"
            copies[relative] = relative
        for destination, origin in copies.items():
            contents = (self.source / origin).read_text()
            if origin.endswith(".in"):
                for key, value in substitutions.items():
                    contents = contents.replace("@" + key + "@", value)
            write(build / destination, contents)
        for relative in baseline_inventory.GENERATED_HEADERS:
            output = build / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, "-I", "-S", "-B", str(self.source / "ci/gen_config.py"),
                            "--config", str(self.source / (output.stem + ".toml")),
                            "--output", str(output), "--format",
                            "cpp" if relative.startswith("sw/") else "verilog"],
                           env={"PATH": os.defpath}, check=True, capture_output=True, timeout=5)

    def command(self, argv, build, environment, log, **budget):
        name = log.stem
        self.calls.append({"id": name, "argv": list(argv), "cwd": build,
                           "environment": dict(environment), "budget": budget})
        self.checkpoints.append(json.loads((self.args.output / "report.json").read_text()))
        text = "inert command fixture\n"
        if name.endswith("-configure"):
            self.configure(build)
        for case in select_cases(self.args.case):
            if name == case["id"] + "-build":
                for relative in case["artifacts"]:
                    write(build / relative, "inert output: " + relative + "\n")
            elif name == case["id"] + "-run":
                text = self.logs[case["id"]]
        write(log, text)
        self.after_command(name, build)
        result = {"outcome": "pass", "exit_code": 0, "reason": None, "cleanup_complete": True,
                  "process_started": True,
                  "elapsed_seconds": 0.01, "peak_rss_bytes": 1024, "log_bytes": log.stat().st_size}
        result.update(self.failures.get(name, {}))
        return result


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="local-qualification-runner-")
        self.addCleanup(temporary.cleanup)
        self.fixture = RunnerFixture(Path(temporary.name).resolve())
        self.enterContext(mock.patch.dict(os.environ, self.fixture.environment, clear=True))
        self.enterContext(mock.patch.object(runner, "HERE", self.fixture.helpers))
        self.enterContext(mock.patch.object(inventory, "HERE", self.fixture.helpers))
        capacity = type(shutil.disk_usage(self.fixture.base))(64 * runner.GIB, runner.GIB, 63 * runner.GIB)
        self.capacity = self.enterContext(mock.patch.object(runner.shutil, "disk_usage", return_value=capacity))
        self.process = self.enterContext(mock.patch.object(runner, "run_bounded", side_effect=self.fixture.command))

    def plan(self):
        report = runner.plan_run(self.fixture.args, self.fixture.paths)
        self.assertEqual(report["outcome"], "pass", report.get("blockers"))
        return report

    def run_fixture(self, report=None):
        return runner.execute_run(self.fixture.args, self.plan() if report is None else report,
                                  self.fixture.paths)

    def assertNotPromoted(self, report):
        self.assertIs(report["supplemental"], True)
        for key in ("qualifies_P01_A03", "vendor_execution_performed", "phase_complete"):
            self.assertIs(report[key], False, key)

    def assertRetained(self, report, outcome):
        self.assertEqual(report["outcome"], outcome, report.get("reason"))
        self.assertEqual(report["state"], "finished")
        self.assertIsNotNone(report["finished_at"])
        self.assertNotIn("active_command", report)
        retained = json.loads((self.fixture.args.output / "report.json").read_text())
        self.assertEqual(retained, report)
        self.assertNotPromoted(retained)
        for checkpoint in self.fixture.checkpoints:
            self.assertEqual(checkpoint["state"], "running")
            self.assertNotEqual(checkpoint["outcome"], "pass")
            self.assertNotPromoted(checkpoint)
        return retained

    def test_plan_is_read_only_and_never_claims_workload_execution(self):
        self.fixture.args.mode = "plan"
        before = tree_identity(self.fixture.base)
        report = self.plan()
        self.assertEqual(tree_identity(self.fixture.base), before)
        self.assertFalse(self.fixture.args.output.exists())
        self.assertFalse(self.fixture.args.build_root.exists())
        self.process.assert_not_called()
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["state"], "planned")
        self.assertFalse(report["execution_performed"])
        self.assertFalse(report["workload_command_started"])
        self.assertTrue(all(case["outcome"] == "not_run" for case in report["cases"]))
        self.assertNotPromoted(report)

    def test_blocked_input_inventory_prevents_output_creation_and_launch(self):
        (self.fixture.headers / "uuid/uuid.h").unlink()
        report = runner.plan_run(self.fixture.args, self.fixture.paths)
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(report["blockers"])
        self.assertIs(runner.execute_run(self.fixture.args, report, self.fixture.paths), report)
        self.process.assert_not_called()
        self.assertFalse(self.fixture.args.output.exists())
        self.assertFalse(self.fixture.args.build_root.exists())
        self.assertNotPromoted(report)

    def test_disk_below_reserve_blocks_the_plan_without_launch(self):
        self.capacity.return_value = type(self.capacity.return_value)(16 * runner.GIB, 2 * runner.GIB,
                                                                      14 * runner.GIB)
        report = runner.plan_run(self.fixture.args, self.fixture.paths)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("free disk is below the retained reserve", report["blockers"])
        runner.execute_run(self.fixture.args, report, self.fixture.paths)
        self.process.assert_not_called()

    def test_passing_subset_retains_bytes_and_budgets_without_vendor_or_phase_promotion(self):
        report = self.run_fixture()
        self.assertRetained(report, "pass")
        self.assertEqual(report["selected_ids"], ["cp-llc-port"])
        self.assertEqual([entry["id"] for entry in report["commands"]],
                         ["units-configure", "cp-llc-port-build", "cp-llc-port-run"])
        self.assertEqual(report["cases"][0]["outcome"], "pass")
        self.assertEqual(report["cases"][0]["artifacts_before"], report["cases"][0]["artifacts_after"])
        self.assertTrue(report["workload_command_started"])
        self.assertTrue(report["snapshots"])
        for snapshot in report["snapshots"]:
            retained = snapshot["retained"]
            contents = (self.fixture.args.output / retained["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(contents).hexdigest(), snapshot["source"]["sha256"])
            self.assertEqual(len(contents), snapshot["source"]["size_bytes"])
        for call in self.fixture.calls:
            self.assertEqual(call["budget"], {
                **{key: value for key, value in report["budget"].items() if key != "jobs"},
                "resource_paths": tuple(self.fixture.paths.values()),
            })
            self.assertEqual(call["environment"]["CONFIGS"], report["cases"][0]["configs"])
            self.assertEqual(call["environment"]["MAKEFLAGS"], "-j1")

    def test_changed_case_budget_or_environment_invalidates_a_plan_before_launch(self):
        report = self.plan()
        for field, value in (("case", ["demo"]), ("jobs", 2), ("timeout_seconds", 31)):
            original = getattr(self.fixture.args, field)
            with self.subTest(field=field):
                setattr(self.fixture.args, field, value)
                with self.assertRaisesRegex(ValueError, "plan no longer matches"):
                    self.run_fixture(copy.deepcopy(report))
            setattr(self.fixture.args, field, original)
        with mock.patch.dict(os.environ, {"HOME": str(self.fixture.base / "other-home")}):
            with self.assertRaisesRegex(ValueError, "environment changed"):
                self.run_fixture(report)
        self.process.assert_not_called()
        self.assertFalse(self.fixture.args.output.exists())

    def test_command_failure_timeout_log_stop_and_incomplete_cleanup_never_pass(self):
        failures = (
            {"outcome": "fail", "exit_code": 7, "reason": "command exited unsuccessfully"},
            {"outcome": "fail", "exit_code": -15, "reason": "timeout limit exceeded"},
            {"outcome": "fail", "exit_code": -15, "reason": "log size limit exceeded"},
            {"outcome": "pass", "exit_code": 0, "cleanup_complete": False},
            {"outcome": "pass", "exit_code": 9},
        )
        for failure in failures:
            with self.subTest(failure=failure):
                self.fixture.fresh_paths()
                self.fixture.failures = {"cp-llc-port-run": failure}
                report = self.run_fixture()
                self.assertRetained(report, "fail")
                self.assertEqual(report["cases"][0]["outcome"], "fail")
                self.assertNotIn("observations", report["cases"][0])
                self.assertEqual(report["commands"][-1]["exit_code"], failure["exit_code"])
                self.assertTrue(report["workload_command_started"])

    def test_failed_build_never_launches_a_workload(self):
        self.fixture.failures["cp-llc-port-build"] = {"outcome": "fail", "exit_code": 2}
        report = self.run_fixture()
        self.assertRetained(report, "fail")
        self.assertEqual([entry["id"] for entry in report["commands"]],
                         ["units-configure", "cp-llc-port-build"])
        self.assertFalse(report["workload_command_started"])
        self.assertFalse((self.fixture.args.output / "logs/cp-llc-port-run.log").exists())

    def test_inputs_changed_between_plan_and_execution_block_before_launch(self):
        inputs = (self.fixture.source / "configure",
                  self.fixture.tools / baseline_inventory.TOOL_BINARIES["llvm_clang"],
                  self.fixture.dependencies / "third_party/ramulator/libramulator.so",
                  self.fixture.headers / "uuid/uuid.h")
        for path in inputs:
            original = path.read_bytes()
            with self.subTest(path=path.relative_to(self.fixture.base)):
                self.fixture.fresh_paths()
                report = self.plan()
                path.write_bytes(original + b"\nchanged\n")
                self.assertRetained(self.run_fixture(report), "blocked")
                self.assertEqual(report["commands"], [])
                self.assertFalse(report["checks"][-1]["inputs_match"])
                self.assertFalse(self.fixture.args.build_root.exists())
            path.write_bytes(original)
        self.process.assert_not_called()

    def test_input_drift_after_a_successful_command_vetoes_pass(self):
        inputs = (self.fixture.source / "configure",
                  self.fixture.tools / baseline_inventory.TOOL_BINARIES["llvm_clang"],
                  self.fixture.dependencies / "third_party/ramulator/libramulator.so",
                  self.fixture.headers / "uuid/uuid.h")
        for path in inputs:
            original = path.read_bytes()
            with self.subTest(path=path.relative_to(self.fixture.base)):
                self.fixture.fresh_paths()
                self.fixture.after_command = lambda name, build: (
                    path.write_bytes(original + b"\nchanged\n") if name == "cp-llc-port-run" else None)
                report = self.run_fixture()
                self.assertRetained(report, "fail")
                self.assertEqual(report["commands"][-1]["outcome"], "pass")
                self.assertEqual(report["cases"][0]["outcome"], "fail")
                self.assertEqual(report["checks"][-1]["stage"], "after-cp-llc-port-run")
                self.assertFalse(report["checks"][-1]["inputs_match"])
            path.write_bytes(original)

    def test_helper_drift_before_and_after_launch_is_detected_from_actual_bytes(self):
        path = self.fixture.helpers / "baseline_process.py"
        original = path.read_bytes()
        for stage in ("before", "after"):
            with self.subTest(stage=stage):
                self.fixture.fresh_paths()
                self.fixture.after_command = lambda name, build: None
                report = self.plan()
                if stage == "before":
                    path.write_bytes(original + b"\n# changed helper\n")
                else:
                    self.fixture.after_command = lambda name, build: (
                        path.write_bytes(original + b"\n# changed helper\n")
                        if name == "cp-llc-port-run" else None)
                report = self.run_fixture(report)
                self.assertRetained(report, "blocked" if stage == "before" else "fail")
                self.assertFalse(report["checks"][-1]["helpers_match"])
                self.assertTrue(report["checks"][-1]["inputs_match"])
            path.write_bytes(original)

    def test_invalid_generated_configuration_prevents_build_and_workload(self):
        self.fixture.after_command = lambda name, build: (
            write(build / "config.mk", "XLEN ?= 32\n") if name == "units-configure" else None)
        report = self.run_fixture()
        self.assertRetained(report, "fail")
        self.assertEqual([entry["id"] for entry in report["commands"]], ["units-configure"])
        self.assertEqual(report["generated_failure"]["outcome"], "blocked")
        self.assertFalse(report["workload_command_started"])

    def test_generated_recipe_or_header_drift_before_and_after_workload_fails(self):
        for stage, relative in (("cp-llc-port-build", "hw/unittest/common.mk"),
                                ("cp-llc-port-run", "sw/VX_config.h")):
            with self.subTest(stage=stage, relative=relative):
                self.fixture.fresh_paths()
                self.fixture.after_command = lambda name, build: (
                    write(build / relative, "changed configuration\n") if name == stage else None)
                report = self.run_fixture()
                self.assertRetained(report, "fail")
                self.assertEqual(report["generated_drift"]["group"], "units")
                self.assertEqual(report["cases"][0]["outcome"], "fail")
                self.assertEqual(report["workload_command_started"], stage.endswith("-run"))

    def test_case_binary_and_effective_build_record_drift_during_launch_fail(self):
        for relative in select_cases(["cp-llc-port"])[0]["artifacts"]:
            with self.subTest(relative=relative):
                self.fixture.fresh_paths()
                self.fixture.after_command = lambda name, build: (
                    write(build / relative, "changed launch input\n") if name == "cp-llc-port-run" else None)
                report = self.run_fixture()
                self.assertRetained(report, "fail")
                case = report["cases"][0]
                self.assertNotEqual(case["artifacts_before"], case["artifacts_after"])
                self.assertIn("changed during launch", case["reason"])
                self.assertNotIn("observations", case)
                self.assertEqual(report["commands"][-1]["outcome"], "pass")

    def test_missing_wrong_or_ambiguous_output_markers_cannot_pass_a_successful_child(self):
        self.fixture.args.case = ["demo"]
        invalid_logs = ("", "PASSED!\n", DEMO_LOG.replace("number of points: 16", "number of points: 1"),
                        DEMO_LOG.replace("verify result\n", ""), DEMO_LOG + "PASSED!\n",
                        DEMO_LOG + "FAILED\n")
        for log in invalid_logs:
            with self.subTest(log=log):
                self.fixture.fresh_paths()
                self.fixture.logs["demo"] = log
                report = self.run_fixture()
                self.assertRetained(report, "fail")
                self.assertEqual(report["commands"][-1]["exit_code"], 0)
                self.assertEqual(report["commands"][-1]["outcome"], "pass")
                self.assertEqual(report["cases"][0]["outcome"], "fail")
                self.assertNotIn("observations", report["cases"][0])

    def test_partially_passing_matrix_keeps_named_results_and_cannot_promote_phase(self):
        self.fixture.args.case = ["demo", "cp-llc-port"]
        self.fixture.failures["cp-llc-port-run"] = {"outcome": "fail", "exit_code": 3}
        report = self.run_fixture()
        self.assertRetained(report, "fail")
        self.assertEqual(report["selected_ids"], ["demo", "cp-llc-port"])
        self.assertEqual({case["id"]: case["outcome"] for case in report["cases"]},
                         {"demo": "pass", "cp-llc-port": "fail"})
        self.assertNotPromoted(report)

    def test_checkpoint_collision_stops_execution_and_retains_compact_failure(self):
        self.fixture.after_command = lambda name, build: (
            write(self.fixture.args.output / "report.json.tmp", "occupied\n")
            if name == "units-configure" else None)
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([entry["id"] for entry in report["commands"]], ["units-configure"])
        self.assertFalse(report["workload_command_started"])
        checkpoint = json.loads((self.fixture.args.output / "report.json").read_text())
        self.assertNotEqual(checkpoint["outcome"], "pass")
        failure = json.loads((self.fixture.args.output / "failure.json").read_text())
        self.assertEqual(failure["outcome"], "fail")
        self.assertEqual(failure["state"], "finished")
        self.assertTrue(failure["full_report_checkpoint_failed"])
        self.assertEqual(failure["completed_command_ids"], ["units-configure"])
        self.assertNotPromoted(failure)
        self.assertLessEqual((self.fixture.args.output / "failure.json").stat().st_size,
                             runner.FAILURE_CHECKPOINT_BYTES)

    def test_failed_final_report_replace_cannot_leave_an_overall_pass(self):
        replace = os.replace

        def fail_finished(source, destination):
            data = json.loads(Path(source).read_text())
            if data["state"] == "finished":
                raise OSError("injected final atomic replacement failure")
            return replace(source, destination)

        with mock.patch.object(runner.os, "replace", side_effect=fail_finished):
            report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["cases"][0]["outcome"], "pass")
        previous = json.loads((self.fixture.args.output / "report.json").read_text())
        self.assertNotEqual(previous["outcome"], "pass")
        self.assertFalse((self.fixture.args.output / "report.json.tmp").exists())
        failure = json.loads((self.fixture.args.output / "failure.json").read_text())
        self.assertEqual(failure["outcome"], "fail")
        self.assertTrue(failure["full_report_checkpoint_failed"])
        self.assertEqual(failure["completed_command_ids"],
                         ["units-configure", "cp-llc-port-build", "cp-llc-port-run"])
        self.assertNotPromoted(failure)


if __name__ == "__main__":
    unittest.main()
