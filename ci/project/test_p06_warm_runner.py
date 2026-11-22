# SPDX-License-Identifier: Apache-2.0
"""Host-only warm orchestration tests; external observations are synthetic.

The real runner, fixtures, compiler/output validators, binding hashes and packet
writer surround simulated builds and processes. No native GPU work runs here.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_warm_execute as runner
import p06_warm_test_fixture as samples
from p06_workspace_test_samples import compiler_stamps
from baseline_inventory import SOURCE_INPUTS
from test_p02_matrix import BUILD, SOURCE, TOOLS, STAMP_SAMPLES


ROOT = runner.ROOT
ORIGINAL_HASH = runner.hash_artifacts
ORIGINAL_DIGEST = runner._digest
CONTRACT = runner.load_contract()
FORMATS = ("fp16", "bf16")
POLICIES = ("per_operation", "reusable_single_tile")
HEADER = STAMP_SAMPLES["header"]
EXPANDED_HEADER = HEADER.rstrip() + "\n" + "".join(
    "#define " + name + "_DISABLE 1\n" for name in runner.DISABLED)
FIRST_PROCESS = "warm-simx-fp16-pair0-per_operation"
SECOND_PROCESS = "warm-simx-fp16-pair0-reusable_single_tile"
LAST_PROCESS = "warm-simx-bf16-pair5-per_operation"


def arguments(*options):
    return runner.argument_parser().parse_args([
        "run", "--tools-dir", "/warm-host-test/tools",
        "--work-dir", "/warm-host-test/work", "--output", "/warm-host-test/output",
        *options])


class WarmHarness:
    """Replace external observations while retaining actual orchestration checks."""

    def __init__(self, test, *options):
        self.args = arguments(*options)
        temporary = tempfile.TemporaryDirectory(prefix="warm-runner-host-")
        test.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.args.source_dir = ROOT
        self.args.tools_dir = root / "tools"
        self.args.work_dir = root / "work"
        self.args.output = root / "packet"
        self.args.tools_dir.mkdir()
        self.paths = runner.base.resolve_paths(self.args)
        self.resources = {
            "available_memory_bytes": 4 * 1024**3,
            "free_disk_bytes": {key: 15 * 1024**3 for key in ("source", "tools", "work", "output")},
        }
        self.snapshot = {
            "checkout": {"revision": "1" * 40, "tree": "2" * 40, "dirty": False,
                         "changed_paths": [], "untracked_paths": [], "blockers": []},
            "files": ORIGINAL_HASH(ROOT, sorted(set(runner.SOURCE_FILES))),
        }
        self.calls = []
        self.snapshot_calls = self.resource_calls = 0
        self.fail_id = self.exception = self.drift = self.final_drift = None
        self.response_changes = {}
        self.response_remove = ()
        self.change_log = lambda name, text: text
        self.change_records = lambda name, records: None
        self.after_command = lambda name, argv, cwd: None
        self.on_snapshot = lambda count: None
        self.final_resource_error = False
        self.stack = ExitStack()
        test.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(runner, "source_snapshot", side_effect=self.source_snapshot))
        self.stack.enter_context(mock.patch.object(runner.base, "_resources", side_effect=self.resource_snapshot))
        self.stack.enter_context(mock.patch.object(runner.base, "tool_inventory", side_effect=self.tool_inventory))
        self.stack.enter_context(mock.patch.object(runner, "hash_artifacts", side_effect=self.hash_artifacts))
        self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.process))
        self.validate_records = self.stack.enter_context(mock.patch.object(
            runner, "validate_records", wraps=runner.validate_records))
        self.verify = self.stack.enter_context(mock.patch.object(
            runner, "verify_output", wraps=runner.verify_output))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stack.close()

    def source_snapshot(self, _):
        self.snapshot_calls += 1
        self.on_snapshot(self.snapshot_calls)
        if self.snapshot_calls == 54:
            self.drift = self.final_drift or self.drift
        value = copy.deepcopy(self.snapshot)
        if self.drift == "source":
            value["checkout"]["tree"] = "3" * 40
        return value

    def resource_snapshot(self, _):
        self.resource_calls += 1
        if self.resource_calls == 2 and self.final_resource_error:
            raise OSError("synthetic final resource inventory failure")
        return copy.deepcopy(self.resources)

    def tool_inventory(self, *_):
        result = {name: {"path": "/warm-host-test/" + name,
                         "sha256": "a" * 64, "size_bytes": 1}
                  for name in ("g++", "clang", "make", "python3", "riscv-gcc")}
        if self.drift == "tools":
            result["clang"]["sha256"] = "b" * 64
        return result

    def hash_artifacts(self, root, names):
        names = tuple(names)
        if Path(root) == self.paths["source"] and names == runner.base.DEPENDENCIES:
            return [{"path": name, "sha256": ("b" if self.drift == "dependencies" else "a") * 64,
                     "size_bytes": 1} for name in names]
        return ORIGINAL_HASH(root, names)

    def configure_files(self, build, driver, fmt):
        source = self.paths["source"]
        for relative in runner.artifacts(driver):
            if relative == runner.HEADER_PROBE:
                continue
            path = build / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic host-test build; no executable: " + fmt + ":" + relative + "\n")
        for relative in runner.base.COPIED + (runner.APP + "/Makefile",):
            (build / relative).write_bytes((source / relative).read_bytes())
        (build / "sim/rtlsim/verilator.vlt").write_text(
            (source / "sim/rtlsim/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(source)))
        settings = {"XLEN": "64", "PROFILE": "p02-tfr", "VORTEX_HOME": str(source),
                    "TOOLDIR": str(self.paths["tools"]), "OSVERSION": "ubuntu/focal"}
        (build / "config.mk").write_text("".join(key + " ?= " + value + "\n" for key, value in settings.items()))
        (build / ".config.stamp").write_text(
            "XLEN=64 PROFILE=p02-tfr SOURCE_DIR=" + str(source) + " BUILDDIR=" + str(build)
            + " TOOLDIR=" + str(self.paths["tools"]) + "\n")
        stamps = compiler_stamps(driver, fmt, self.args.jobs)
        stamps[1] = stamps[1].rstrip() + " -DPERF_ENABLE\n"
        names = ("sw/runtime/" + driver + "_rt_config.stamp",
                 "sw/runtime/" + driver + "_config.stamp", runner.APP + "/config.stamp")
        for relative, stamp in zip(names, stamps):
            for before, after in ((SOURCE, source), (BUILD, build), (TOOLS, self.paths["tools"])):
                stamp = stamp.replace(str(before), str(after))
            (build / relative).write_text(stamp)

    def process(self, argv, cwd, environment, logfile, **budget):
        name, cwd = logfile.stem, Path(cwd)
        self.calls.append((name, list(argv), cwd, dict(environment), dict(budget)))
        text = "synthetic host-test process; no native compiler or GPU execution\n"
        if name.endswith("-configure"):
            driver, fmt = name.split("-")[:2]
            self.configure_files(cwd, driver, fmt)
        elif name.endswith("-header-reproduce"):
            destination = Path(next(arg[len("--output="):] for arg in argv if arg.startswith("--output=")))
            relative = "sw/VX_config.h" if name.endswith("-cpp-header-reproduce") else "hw/VX_config.vh"
            destination.write_bytes((cwd / relative).read_bytes())
        elif name.endswith("-expected-flags"):
            text = "-DVX_CFG_XLEN=64\n"
        elif name.endswith("-header"):
            text = HEADER if name in ("simx-fp16-header", "simx-bf16-header") else EXPANDED_HEADER
            if name.endswith("-backend_cpp-header"):
                text += "#define PERF_ENABLE 1\n"
        elif "--policy" in argv:
            values = dict(zip(argv[1::2], argv[2::2]))
            _, operations, summary = samples.raw_records(
                name.split("-")[2], values["--policy"], pair_index=int(values["--pair-index"]),
                binding_id=values["--qualification-id"], contract=CONTRACT)
            records = {"operations": operations, "summary": summary}
            self.change_records(name, records)
            text = samples.render_log(records["operations"], records["summary"])
        text = self.change_log(name, text)
        logfile.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        self.after_command(name, argv, cwd)
        response = {"outcome": "pass", "exit_code": 0, "process_started": True,
                    "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024,
                    "log_sha256": hashlib.sha256(logfile.read_bytes()).hexdigest(),
                    "log_size_bytes": logfile.stat().st_size, "reason": None,
                    "limitations": list(runner.base.PROCESS_LIMITATIONS)}
        if name == self.fail_id:
            if self.exception is not None:
                raise self.exception
            response.update(self.response_changes)
            for key in self.response_remove:
                response.pop(key, None)
        return response

    def execute(self):
        result = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return result

    def launches(self):
        return [call for call in self.calls if "--policy" in call[1]]


class WarmBoundaryTests(unittest.TestCase):
    def test_cli_keeps_fixed_full_matrix_and_bounded_resources(self):
        forbidden = [("--backend", "simx"), ("--format", "fp16"), ("--case", "dense"),
                     ("--policy", "per_operation"), ("--pair-index", "1"), ("--phase", "measured"),
                     ("--iterations", "32"), ("--warmups", "0"), ("--samples", "5"),
                     ("--allow-dirty",), ("--development",), ("--max-rss-bytes", "8589934592"),
                     ("--min-free-bytes", "0"), ("--max-log-bytes", "33554432"),
                     ("--jobs", "0"), ("--jobs", "3"), ("--timeout-seconds", "0"),
                     ("--timeout-seconds", "1801"), ("--run-timeout-seconds", "0"),
                     ("--run-timeout-seconds", "181"), ("--run-timeout-seconds", "NaN")]
        for options in forbidden:
            with self.subTest(options=options), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                arguments(*options)
            self.assertEqual(error.exception.code, 2)
        args = arguments("--jobs", "1", "--timeout-seconds", "1", "--run-timeout-seconds", "1")
        self.assertEqual((args.jobs, args.timeout_seconds, args.run_timeout_seconds), (1, 1, 1))
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                                      "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})

    def test_paths_require_fresh_disjoint_unsymlinked_external_directories(self):
        with tempfile.TemporaryDirectory(prefix="warm-paths-") as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            args = arguments("--source-dir", str(ROOT), "--tools-dir", str(tools),
                             "--work-dir", str(root / "work"), "--output", str(root / "packet"))
            runner.base.resolve_paths(args)
            alias = root / "alias"
            alias.symlink_to(tools, target_is_directory=True)
            for field, value in (("work_dir", tools), ("output", tools), ("output", args.work_dir),
                                 ("work_dir", ROOT / "warm-test-build"),
                                 ("output", ROOT / "warm-test-packet"), ("tools_dir", alias),
                                 ("work_dir", root / "absent" / "work"),
                                 ("work_dir", root / "unsafe path"), ("source_dir", root)):
                with self.subTest(field=field, value=value):
                    changed = copy.copy(args)
                    setattr(changed, field, value)
                    with self.assertRaises(ValueError):
                        runner.base.resolve_paths(changed)
            args.work_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "fresh"):
                runner.base.resolve_paths(args)

    def test_source_snapshot_binds_preparation_runtime_and_transitive_helpers(self):
        checkout = {"revision": "1" * 40, "tree": "2" * 40, "dirty": False,
                    "changed_paths": [], "untracked_paths": [], "blockers": [],
                    "inputs": ORIGINAL_HASH(ROOT, SOURCE_INPUTS)}
        with mock.patch.object(runner.base, "collect_source", return_value=checkout):
            snapshot = runner.source_snapshot(ROOT)
        names = {row["path"] for row in snapshot["files"]}
        expected = set(runner.SOURCE_FILES + runner.operator_run.SOURCE_FILES + SOURCE_INPUTS
                       + runner.base.CORPUS + runner.base.COPIED + runner.base.TOOLING)
        expected.update((".github/workflows/p04-model.yml", "third_party/Makefile",
                         "ci/project/p06_warm_compiler_records.py", "ci/project/p06_warm_contract.py",
                         "ci/project/p06_warm_records.py", "ci/project/compiler_records.py"))
        self.assertLessEqual(expected, names)
        self.assertLessEqual({row["path"] for row in runner.LOADED_HELPERS}, names)
        self.assertEqual(snapshot["files"], ORIGINAL_HASH(ROOT, sorted(names)))
        self.assertEqual(snapshot["checkout"], checkout)

    def test_supervisor_containment_has_only_the_frozen_allowance(self):
        observation = {"summary": {"host_intervals_ns": {
            "create": {"begin_ns": 100, "end_ns": 200},
            "close": {"begin_ns": 1000100, "end_ns": 1001100}}}}
        runner.validate_process_duration(observation, 0.001, CONTRACT)
        changed = copy.deepcopy(observation)
        changed["summary"]["host_intervals_ns"]["close"]["end_ns"] += 1
        with self.assertRaises(ValueError):
            runner.validate_process_duration(changed, 0.001, CONTRACT)
        for duration in (True, -1, float("nan"), float("inf"), "1", None):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                runner.validate_process_duration(observation, duration, CONTRACT)


class WarmExecutionTests(unittest.TestCase):
    def assert_no_acceptance(self, report):
        for key in ("acceptance_claimed", "performance_acceptance", "phase_acceptance", "phase_complete"):
            self.assertIs(report[key], False, key)
        self.assertEqual(report["hypothesis_evaluation"], "not_evaluated")

    def test_full_paired_matrix_uses_two_builds_and_verifies_all_original_records(self):
        with WarmHarness(self) as harness:
            report = harness.execute()
            self.assertEqual(report["outcome"], "pass", report["reason"])
            plan = []
            expected_commands = ["version-" + name for name in ("gpp", "clang", "make", "python3", "riscv-gcc")]
            expected_stability = []
            for fmt in FORMATS:
                variant = "simx-" + fmt
                expected_commands.extend(variant + "-" + name for name in (
                    "configure", "header", "cpp-header-reproduce", "verilog-header-reproduce",
                    "expected-flags", "expected-expanded-header", "runtime", "application",
                    "runtime-header", "backend_cpp-header", "kernel-header", "host-header"))
                expected_stability.append("before-" + variant)
                for pair in range(6):
                    for policy in POLICIES if pair % 2 == 0 else POLICIES[::-1]:
                        name = f"warm-simx-{fmt}-pair{pair}-{policy}"
                        plan.append(name)
                        expected_commands.append(name)
                        expected_stability.extend(("before-" + name, "after-" + name))
                expected_stability.append("after-" + variant)
            self.assertEqual([row["id"] for row in report["processes"]], plan)
            self.assertEqual([call[0] for call in harness.launches()], plan)
            self.assertEqual([row["id"] for row in report["commands"]], expected_commands)
            self.assertEqual(len(expected_commands), 53)
            self.assertEqual([row["label"] for row in report["stability_checks"]], expected_stability)
            self.assertEqual(len(expected_stability), 52)
            self.assertEqual(harness.snapshot_calls, 54)
            self.assertEqual((report["completed_processes"], report["completed_launches"], report["checked_words"]),
                             (24, 792, 25344))
            self.assertEqual((report["measured_processes"], report["measured_operations"]), (20, 640))
            self.assertTrue(report["full_matrix_requested"])
            self.assertTrue(report["full_matrix_completed"])
            self.assertTrue(report["selected_scope_completed"])
            self.assertEqual(harness.verify.call_count, 24)
            self.assertEqual(harness.validate_records.call_count, 2)
            self.assertEqual(len({row["qualification_id"] for row in report["processes"]}), 24)
            self.assertEqual(report, harness.saved)
            self.assert_no_acceptance(report)
            self.assertTrue(report["retained_files_stable"])
            self.assertEqual(report["raw_logs"], ORIGINAL_HASH(
                harness.paths["output"], [row["log"] for row in report["commands"]]))
            for variant in report["variants"]:
                self.assertEqual(variant["artifacts_before"], variant["artifacts_after"])
                self.assertEqual(set(variant["effective_headers"]), {"runtime", "backend_cpp", "kernel", "host"})
                self.assertEqual([row["stage"] for row in variant["retained_builds"]],
                                 ["configured", "runtime", "built", "frozen"])
                bindings = {row["build_qualification_id"] for row in report["processes"]
                            if row["format"] == variant["format"]}
                self.assertEqual(bindings, {variant["qualification_id"]})
            for process, call in zip(report["processes"], harness.launches()):
                binding = json.loads((harness.paths["output"] / process["binding"]["path"]).read_text())
                self.assertEqual(runner.qualification_id(binding), process["qualification_id"])
                self.assertEqual(runner.qualification_id(binding["build"]), process["build_qualification_id"])
                self.assertEqual(binding["build_qualification_id"], process["build_qualification_id"])
                self.assertEqual(binding["process"]["id"], process["id"])
                self.assertEqual(binding["build"]["sampling"], CONTRACT["sampling"])
                self.assertEqual(binding["build"]["performance_environment"], {"PERF": "1"})
                app = harness.paths["work"] / ("simx-" + process["format"]) / runner.APP
                self.assertEqual(call[1], [str(app / "ai_warm_workspace"), "--policy", process["policy"],
                    "--module", str(app / "kernel.vxbin"), "--qualification-id", process["qualification_id"],
                    "--sample-id", process["id"], "--pair-index", str(process["pair_index"]),
                    "--phase", process["phase"]])
                self.assertEqual(call[2], app)
                self.assertEqual(call[3]["VORTEX_DRIVER"], "simx")
                self.assertEqual(call[3]["LD_LIBRARY_PATH"], str(app.parents[2] / "sw/runtime"))
                self.assertEqual(len(process["observation"]["timed_operation_durations_ns"]), 32)

    def test_environment_and_budgets_are_exact_and_perf_is_confined_to_builds(self):
        injected = {key: "untrusted" for key in (
            "PATH", "HOME", "CONFIGS", "PERF", "MAKEFLAGS", "THREADS", "CMAKE_BUILD_PARALLEL_LEVEL",
            "CCACHE_DISABLE", "OBJCACHE", "CXX", "BASH_ENV", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "VORTEX_DRIVER", "SIMX_FAST", "SIMX_FUNCTIONAL", "P06_WARM_POLICY")}
        with mock.patch.dict(os.environ, injected), WarmHarness(self, "--jobs", "1") as harness:
            report = harness.execute()
            self.assertEqual(report["outcome"], "pass", report["reason"])
            base_env = runner.base.clean_environment(harness.paths, 1)
            base_env.pop("HOME")
            for name, argv, cwd, environment, budgets in harness.calls:
                expected = dict(base_env)
                if name.endswith(("-runtime", "-application")):
                    expected.update(CONFIGS=f"-DITYPE={name.split('-')[1]} -DOTYPE=fp32 -DKUNROLL=1", PERF="1")
                    self.assertIn("-j1", argv)
                    self.assertIn("THREADS=1", argv)
                elif name.endswith("-header-reproduce"):
                    expected["XLEN"] = "64"
                elif "--policy" in argv:
                    expected.update(VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(cwd.parents[2] / "sw/runtime"))
                self.assertEqual(environment, expected, name)
                self.assertEqual({key: budgets[key] for key in runner.BUDGET}, runner.BUDGET)
                self.assertEqual(budgets["resource_paths"], tuple(harness.paths[key]
                                 for key in ("source", "tools", "work", "output")))
                timeout = (180 if "--policy" in argv else 120 if name.endswith("-configure") else
                           1800 if name.endswith(("-runtime", "-application")) else 30)
                self.assertEqual(budgets["timeout_seconds"], timeout, name)
            self.assertEqual(report["budget"]["jobs"], 1)

    def test_nonzero_timeout_missing_process_or_cleanup_stops_without_replacement(self):
        responses = [({"outcome": "fail", "exit_code": 9, "reason": "synthetic nonzero exit"}, ()),
                     ({"outcome": "fail", "exit_code": -15, "reason": "wall timeout"}, ()),
                     ({"exit_code": 1}, ()), ({"cleanup_complete": False}, ()),
                     ({"process_started": False}, ()), ({}, ("exit_code",))]
        for changes, removed in responses:
            with self.subTest(changes=changes, removed=removed), WarmHarness(self) as harness:
                harness.fail_id = SECOND_PROCESS
                harness.response_changes, harness.response_remove = changes, removed
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual((report["completed_processes"], report["completed_launches"], report["checked_words"]),
                                 (1, 33, 1056))
                self.assertEqual([row["outcome"] for row in report["processes"]], ["pass", "fail"])
                self.assertEqual([call[0] for call in harness.launches()], [FIRST_PROCESS, SECOND_PROCESS])
                self.assertEqual(len(report["variants"]), 1)
                failed = report["commands"][-1]
                self.assertEqual(failed["id"], SECOND_PROCESS)
                self.assertIn(failed["log"], {row["path"] for row in report["raw_logs"]})
                self.assertEqual(report["failures"][0]["process_id"], SECOND_PROCESS)
                self.assertEqual(report["variants"][0]["retained_builds"][-1]["stage"], "failure")
                self.assertFalse(report["selected_scope_completed"])
                self.assertFalse(report["full_matrix_completed"])
                self.assert_no_acceptance(report)
                self.assertEqual(report, harness.saved)

    def test_successful_exit_cannot_hide_partial_wrong_identity_bits_or_close(self):
        for mutation in ("partial", "reordered", "bits", "policy", "binding", "pair", "close"):
            with self.subTest(mutation=mutation), WarmHarness(self) as harness:
                def change(name, records):
                    if name != SECOND_PROCESS:
                        return
                    if mutation == "partial":
                        records["operations"].pop()
                    elif mutation == "reordered":
                        records["operations"][0], records["operations"][1] = records["operations"][1], records["operations"][0]
                    elif mutation == "bits":
                        records["operations"][1]["actual_bits"][0] = "3f800000"
                    elif mutation == "policy":
                        records["operations"][0]["policy"] = "per_operation"
                    elif mutation == "binding":
                        records["summary"]["qualification_id"] = "0" * 64
                    elif mutation == "pair":
                        records["operations"][0]["pair_index"] = 1
                    else:
                        records["operations"][0]["results"]["close"]["complete"] = False
                harness.change_records = change
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 1)
                self.assertEqual(report["commands"][-1]["exit_code"], 0)
                self.assertEqual(harness.verify.call_count, 2)
                self.assertFalse(report["full_matrix_completed"])
                self.assertEqual(report["processes"][-1]["outcome"], "fail")
                self.assertIn("log", report["processes"][-1])


class WarmFailureAndRetentionTests(unittest.TestCase):
    def test_invalid_programmatic_budgets_and_resource_shortfalls_block_before_commands(self):
        for kind in ("disk", "memory", "memory_missing", "jobs", "jobs_bool", "build_timeout", "run_timeout"):
            with self.subTest(kind=kind), WarmHarness(self) as harness:
                if kind == "disk":
                    harness.resources["free_disk_bytes"]["output"] -= 1
                elif kind.startswith("memory"):
                    harness.resources["available_memory_bytes"] = None if kind.endswith("missing") else 4 * 1024**3 - 1
                else:
                    name, value = {"jobs": ("jobs", 3), "jobs_bool": ("jobs", True),
                                   "build_timeout": ("timeout_seconds", 1801),
                                   "run_timeout": ("run_timeout_seconds", 181)}[kind]
                    setattr(harness.args, name, value)
                report = harness.execute()
                self.assertEqual(report["outcome"], "blocked", report["reason"])
                self.assertEqual(harness.calls, [])
                self.assertEqual(report["completed_processes"], 0)
                self.assertFalse(report["full_matrix_completed"])
                self.assertEqual(report["state"], "finished")

    def test_dirty_source_stale_loaded_helper_kernel_profile_or_fixture_blocks_early(self):
        for kind in ("dirty", "helper", "kernel", "profile", "fixture"):
            with self.subTest(kind=kind), WarmHarness(self) as harness:
                if kind == "dirty":
                    harness.snapshot["checkout"].update(dirty=True, changed_paths=["synthetic-change"],
                        blockers=["source contains tracked changes or nonignored untracked inputs"])
                elif kind == "helper":
                    changed = copy.deepcopy(runner.LOADED_HELPERS)
                    changed[0]["sha256"] = "0" * 64
                    harness.stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS", changed))
                elif kind in ("kernel", "profile"):
                    target = ROOT / ("sw/kernel/ai/matmul.cpp" if kind == "kernel" else "profiles/p02-tfr.json")
                    harness.stack.enter_context(mock.patch.object(runner, "_digest", side_effect=lambda path:
                        ("0" * 64, 1) if Path(path) == target else ORIGINAL_DIGEST(path)))
                else:
                    harness.stack.enter_context(mock.patch.object(runner, "render_header", return_value=b"stale fixture\n"))
                report = harness.execute()
                self.assertEqual(report["outcome"], "blocked", report["reason"])
                self.assertEqual(harness.calls, [])
                self.assertFalse(report["selected_scope_completed"])
                self.assertTrue(report["failures"])
                self.assertEqual(report, harness.saved)

    def test_build_failure_retains_generated_inputs_and_prevents_native_processes(self):
        for stage in ("configure", "runtime", "application"):
            with self.subTest(stage=stage), WarmHarness(self) as harness:
                harness.fail_id = "simx-fp16-" + stage
                harness.response_changes = {"outcome": "fail", "exit_code": 2, "reason": "synthetic build failure"}
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(harness.calls[-1][0], harness.fail_id)
                self.assertEqual(harness.launches(), [])
                retained = report["variants"][0]["retained_builds"][-1]
                self.assertEqual(retained["stage"], "failure")
                self.assertTrue(retained["files"])
                self.assertEqual(report["completed_launches"], 0)

    def test_stale_generated_inputs_missing_perf_or_changed_effective_headers_fail(self):
        for kind in ("makefile", "copied", "configuration", "header", "compiler", "perf", "effective", "flags"):
            with self.subTest(kind=kind), WarmHarness(self) as harness:
                def change(name, argv, cwd):
                    if name.endswith("-configure"):
                        targets = {"makefile": runner.APP + "/Makefile", "copied": "sw/runtime/common.mk",
                                   "configuration": "config.mk"}
                        if kind in targets:
                            (cwd / targets[kind]).write_text("stale generated input\n")
                    elif kind == "header" and name.endswith("-cpp-header-reproduce"):
                        (cwd / Path(runner.HEADER_PROBE).parent / "VX_config.h").write_text("stale header\n")
                    elif name.endswith("-application"):
                        if kind == "compiler":
                            path = cwd / "config.stamp"
                            path.write_text(path.read_text().replace("-DKUNROLL=1", "-DKUNROLL=2"))
                        elif kind == "perf":
                            path = cwd.parents[2] / "sw/runtime/simx_config.stamp"
                            path.write_text(path.read_text().replace("-DPERF_ENABLE", ""))
                harness.after_command = change
                if kind == "effective":
                    harness.change_log = lambda name, text: text + "#define PERF_ENABLE 1\n" if name.endswith("-host-header") else text
                elif kind == "flags":
                    harness.change_log = lambda name, text: "-include /unretained/header\n" if name.endswith("-expected-flags") else text
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail", report["reason"])
                self.assertEqual(harness.launches(), [])
                self.assertTrue(report["failures"])
                self.assertFalse(report["full_matrix_completed"])

    def test_missing_compiler_record_or_generated_header_retains_failed_build(self):
        for kind in ("compiler", "header"):
            with self.subTest(kind=kind), WarmHarness(self) as harness:
                def remove(name, argv, cwd):
                    if kind == "compiler" and name == "simx-fp16-application":
                        (cwd / "config.stamp").unlink()
                    elif kind == "header" and name == "simx-fp16-configure":
                        (cwd / "sw/VX_config.h").unlink()
                harness.after_command = remove
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["state"], "finished")
                self.assertEqual(harness.launches(), [])
                self.assertEqual(report["completed_launches"], 0)
                self.assertFalse(report["full_matrix_completed"])
                self.assertEqual(report["variants"][0]["retained_builds"][-1]["stage"], "failure")
                self.assertEqual(report, harness.saved)

    def test_source_tool_or_dependency_drift_excludes_the_affected_batch(self):
        for kind in ("source", "tools", "dependencies"):
            with self.subTest(kind=kind), WarmHarness(self) as harness:
                harness.after_command = lambda name, argv, cwd: setattr(harness, "drift", kind) if name == SECOND_PROCESS else None
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn(kind + " changed", report["reason"])
                self.assertEqual(report["completed_processes"], 1)
                self.assertEqual(report["processes"][-1]["outcome"], "fail")
                self.assertFalse(report[kind + "_stable"])
                self.assertIn("final-" + kind + "-snapshot", {row["stage"] for row in report["failures"]})
                self.assertFalse(report["full_matrix_completed"])

    def test_artifact_drift_before_or_during_launch_prevents_verified_samples(self):
        for when in ("before", "during"):
            for artifact in ("ai_warm_workspace", "kernel.vxbin"):
                with self.subTest(when=when, artifact=artifact), WarmHarness(self) as harness:
                    target = harness.paths["work"] / "simx-fp16" / runner.APP / artifact
                    if when == "before":
                        harness.on_snapshot = lambda count: target.write_text("changed artifact\n") if count == 3 else None
                    else:
                        harness.after_command = lambda name, argv, cwd: target.write_text("changed artifact\n") if name == FIRST_PROCESS else None
                    report = harness.execute()
                    self.assertEqual(report["outcome"], "fail")
                    self.assertIn("artifacts changed " + when + " process", report["reason"])
                    self.assertEqual(report["completed_processes"], 0)
                    self.assertEqual(len(harness.launches()), 0 if when == "before" else 1)
                    harness.verify.assert_not_called()
                    self.assertIn("final-build-snapshot", {row["stage"] for row in report["failures"]})

    def test_final_stability_failures_override_apparent_complete_matrix_success(self):
        for kind in ("source", "tools", "dependencies", "resources"):
            with self.subTest(kind=kind), WarmHarness(self) as harness:
                if kind == "resources":
                    harness.final_resource_error = True
                else:
                    harness.final_drift = kind
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual((report["completed_processes"], report["completed_launches"], report["checked_words"]),
                                 (24, 792, 25344))
                self.assertFalse(report["selected_scope_completed"])
                self.assertFalse(report["full_matrix_completed"])
                self.assertIn("final-resources" if kind == "resources" else "final-" + kind + "-snapshot",
                              {row["stage"] for row in report["failures"]})
                self.assertEqual(report, harness.saved)

    def test_final_disk_shortfall_invalidates_complete_attempt_and_retains_all_verified_counts(self):
        with WarmHarness(self) as harness:
            minimum = 15 * 1024**3

            def consume_final_reserve(name, argv, cwd):
                if name == LAST_PROCESS:
                    harness.resources["free_disk_bytes"]["output"] = minimum - 1

            harness.after_command = consume_final_reserve
            report = harness.execute()
            self.assertEqual(report["outcome"], "fail")
            self.assertEqual(report["state"], "finished")
            self.assertEqual(report["resources_before"]["free_disk_bytes"]["output"], minimum)
            self.assertEqual(report["resources_after"]["free_disk_bytes"]["output"], minimum - 1)
            self.assertEqual((report["completed_processes"], report["completed_launches"], report["checked_words"]),
                             (24, 792, 25344))
            self.assertEqual(len(harness.calls), 53)
            self.assertTrue(all(process["outcome"] == "pass" for process in report["processes"]))
            self.assertFalse(report["selected_scope_completed"])
            self.assertFalse(report["full_matrix_completed"])
            self.assertEqual([failure["stage"] for failure in report["failures"]], ["final-resources"])
            self.assertIn("disk reserve", report["reason"])
            for key in ("acceptance_claimed", "performance_acceptance", "phase_acceptance", "phase_complete"):
                self.assertIs(report[key], False, key)
            self.assertEqual(report["hypothesis_evaluation"], "not_evaluated")
            self.assertEqual(report, harness.saved)

    def test_log_source_build_and_binding_tampering_invalidates_completed_matrix(self):
        for kind in ("log", "source", "build", "binding"):
            with self.subTest(kind=kind), WarmHarness(self) as harness:
                def change(name, argv, cwd):
                    if name != LAST_PROCESS:
                        return
                    relative = {
                        "log": "logs/" + FIRST_PROCESS + ".log",
                        "source": "artifacts/source/ci/project/p06_warm_execute.py",
                        "build": "artifacts/simx-fp16/frozen/" + runner.APP + "/config.stamp",
                        "binding": "snapshots/" + FIRST_PROCESS + "-binding.json",
                    }[kind]
                    path = harness.paths["output"] / relative
                    if kind == "binding":
                        path.unlink()
                    else:
                        path.write_bytes(path.read_bytes() + b"tampered\n")
                harness.after_command = change
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 24)
                self.assertFalse(report["full_matrix_completed"])
                self.assertIn("final-log-verification" if kind == "log" else "final-retained-evidence",
                              {row["stage"] for row in report["failures"]})
                self.assertEqual(report, harness.saved)

    def test_missing_or_mismatched_log_receipts_never_reach_record_validation(self):
        for changes in ({"log_sha256": "0" * 64}, {"log_size_bytes": 1}, {"log_sha256": None}):
            with self.subTest(changes=changes), WarmHarness(self) as harness:
                harness.fail_id, harness.response_changes = FIRST_PROCESS, changes
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 0)
                self.assertIn("log", report["reason"])
                harness.verify.assert_not_called()
                self.assertIn("final-log-verification", {row["stage"] for row in report["failures"]})

    def test_oversized_raw_log_remains_retained_but_is_not_parsed(self):
        with WarmHarness(self) as harness:
            harness.change_log = lambda name, text: b"x" * (16 * 1024**2 + 1) if name == FIRST_PROCESS else text
            report = harness.execute()
            self.assertEqual(report["outcome"], "fail")
            self.assertEqual(report["completed_processes"], 0)
            self.assertGreater((harness.paths["output"] / report["commands"][-1]["log"]).stat().st_size,
                               runner.BUDGET["max_log_bytes"])
            harness.verify.assert_not_called()

    def test_invalid_or_impossible_supervisor_duration_cannot_pass_a_batch(self):
        for duration in (True, -1, "1", None, 0):
            with self.subTest(duration=duration), WarmHarness(self) as harness:
                harness.fail_id = FIRST_PROCESS
                harness.response_changes = {"duration_seconds": duration}
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 0)
                self.assertFalse(report["full_matrix_completed"])

    def test_exception_and_interruption_checkpoint_failed_process_and_raw_output(self):
        for error in (OSError("synthetic process failure"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), WarmHarness(self) as harness:
                harness.fail_id, harness.exception = FIRST_PROCESS, error
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["state"], "finished")
                self.assertEqual(report["completed_processes"], 0)
                self.assertEqual(report["processes"][-1]["outcome"], "fail")
                self.assertTrue((harness.paths["output"] / report["commands"][-1]["log"]).is_file())
                self.assertEqual(report, harness.saved)

    def test_main_path_failure_returns_machine_readable_block_without_execution(self):
        output = io.StringIO()
        with mock.patch.object(runner.base, "resolve_paths", side_effect=ValueError("unsafe path")), \
                mock.patch.object(runner, "execute") as execute, redirect_stdout(output):
            code = runner.main(["run", "--tools-dir", "/unused/tools", "--work-dir", "/unused/work", "--output", "/unused/output"])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["outcome"], "blocked")
        self.assertFalse(result["acceptance_claimed"])
        self.assertFalse(result["performance_acceptance"])
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
