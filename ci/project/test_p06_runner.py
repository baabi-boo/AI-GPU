# SPDX-License-Identifier: Apache-2.0
"""Host-only runner tests; external builds and executions are simulated.

Real contract/fixture loading, compiler-record parsing, sample validation,
summary reduction, hashes and packet writes surround the simulated process
boundary. These synthetic packets are not native execution evidence.
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

import p06_execute as runner
import p04_model_contract
from p06_contract import load_analysis_contract
from p06_test_frozen_sources import frozen_source_paths, stage_frozen_sources
from p06_test_samples import REVISION, synthetic_log
from test_p02_matrix import STAMP_SAMPLES, sample as compiler_sample


ROOT = runner.ROOT
CONTRACT = load_analysis_contract()
FIRST_SAMPLE = "simx-fp16-single-dense_boundaries-warmup-0"
ORIGINAL_HASH = runner.hash_artifacts
ORIGINAL_SUMMARIZE = runner.summarize
HEADER = STAMP_SAMPLES["header"]
EXPANDED_HEADER = HEADER.rstrip() + "\n" + "".join(
    "#define " + name + "_DISABLE 1\n" for name in runner.DISABLED)


def arguments(*options):
    return runner.argument_parser().parse_args([
        "run", "--tools-dir", "/p06-host-harness/tools",
        "--work-dir", "/p06-host-harness/work", "--output", "/p06-host-harness/output",
        *options])


class RunnerHarness:
    """Replace external observations while exercising the real runner decisions."""

    def __init__(self, test, *options, full=False):
        self.args = arguments(*(options or (() if full else ("--format", "fp16"))))
        temporary = tempfile.TemporaryDirectory(prefix="p06-runner-host-")
        test.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = {"source": root / "source", "work": root / "work", "output": root / "output",
                      "tools": root / "tools", "host_bin": None, "verilator": root / "tools/verilator"}
        # Keep the real native loader strict. Original execution inputs are
        # archived data; currently imported helpers remain current source.
        frozen = {row["path"] for row in CONTRACT["source_inputs"]}
        frozen.update(p04_model_contract.ARTIFACT_PATHS)
        frozen.update((runner.MANIFEST_PATH, "ci/project/fixtures/p02_tfr_v1.json"))
        names = frozen | set(runner.SOURCE_FILES + runner.base.COPIED)
        names.update(row["path"] for row in runner.LOADED_HELPERS)
        names.update(("configure", "sim/rtlsim/verilator.vlt.in"))
        for name in sorted(names):
            target = self.paths["source"] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        stage_frozen_sources(self.paths["source"], frozen & set(frozen_source_paths()))
        self.paths["tools"].mkdir()
        self.resources = {"available_memory_bytes": runner.BUDGET["max_rss_bytes"],
                          "free_disk_bytes": {key: runner.BUDGET["min_free_bytes"]
                                              for key in ("source", "tools", "work", "output")}}
        self.snapshot = {"checkout": {"revision": REVISION, "tree": "f" * 40,
                                     "dirty": False, "changed_paths": [], "untracked_paths": [],
                                     "blockers": []},
                         "files": ORIGINAL_HASH(self.paths["source"], sorted(set(runner.SOURCE_FILES)))}
        self.calls = []
        self.snapshot_calls = 0
        self.fail_id = None
        self.response_changes = {}
        self.response_remove = ()
        self.exception = None
        self.change_log = lambda name, text: text
        self.after_command = lambda name, argv, cwd: None
        self.on_snapshot = lambda count: None
        self.final_drift = None
        self.finished_summary = False
        self.final_resource_error = False
        self.stack = ExitStack()
        test.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(runner, "source_snapshot", side_effect=self.source_snapshot))
        self.stack.enter_context(mock.patch.object(runner.base, "_resources", side_effect=self.resource_snapshot))
        self.stack.enter_context(mock.patch.object(runner.base, "tool_inventory", side_effect=self.tool_inventory))
        self.stack.enter_context(mock.patch.object(runner, "hash_artifacts", side_effect=self.hash_artifacts))
        self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.process))
        self.stack.enter_context(mock.patch.object(runner, "summarize", side_effect=self.summarize))
        self.validate_records = self.stack.enter_context(mock.patch.object(
            runner, "validate_records", wraps=runner.validate_records))
        self.verify = self.stack.enter_context(mock.patch.object(runner, "verify_sample", wraps=runner.verify_sample))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stack.close()

    def source_snapshot(self, _):
        self.snapshot_calls += 1
        self.on_snapshot(self.snapshot_calls)
        value = copy.deepcopy(self.snapshot)
        if self.finished_summary and self.final_drift == "source":
            value["files"][0]["sha256"] = "0" * 64
        return value

    def resource_snapshot(self, _):
        if self.finished_summary and self.final_resource_error:
            raise OSError("synthetic final resource inventory failure")
        return copy.deepcopy(self.resources)

    def tool_inventory(self, *_):
        value = {name: {"path": "/p06-host-harness/" + name, "sha256": "a" * 64}
                 for name in ("g++", "clang", "make", "python3")}
        if self.finished_summary and self.final_drift == "tools":
            value["g++"]["sha256"] = "b" * 64
        return value

    def hash_artifacts(self, root, paths):
        paths = tuple(paths)
        if Path(root) == self.paths["source"] and paths == runner.base.DEPENDENCIES:
            changed = self.finished_summary and self.final_drift == "dependencies"
            return [{"path": name, "sha256": ("b" if changed else "a") * 64, "size_bytes": 1}
                    for name in paths]
        return ORIGINAL_HASH(root, paths)

    def summarize(self, *args):
        value = ORIGINAL_SUMMARIZE(*args)
        self.finished_summary = True
        return value

    def configure_files(self, build, fmt):
        source = self.paths["source"]
        for relative in runner.artifacts():
            if relative == runner.HEADER_PROBE:
                continue
            destination = build / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("synthetic host-test build: " + fmt + ":" + destination.name + "\n")
        for relative in runner.base.COPIED:
            (build / relative).write_bytes((source / relative).read_bytes())
        (build / "sim/rtlsim/verilator.vlt").write_text(
            (source / "sim/rtlsim/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(source)))
        for app in runner.APPS.values():
            (build / app / "Makefile").write_bytes((source / app / "Makefile").read_bytes())
        settings = {"XLEN": "64", "PROFILE": "p02-tfr", "VORTEX_HOME": str(source),
                    "TOOLDIR": str(self.paths["tools"]), "OSVERSION": "ubuntu/focal"}
        (build / "config.mk").write_text("".join(key + " ?= " + value + "\n"
                                                 for key, value in settings.items()))
        (build / ".config.stamp").write_text(
            "XLEN=64 PROFILE=p02-tfr SOURCE_DIR=" + str(source) + " BUILDDIR=" + str(build)
            + " TOOLDIR=" + str(self.paths["tools"]) + "\n")
        options = dict(source=source, build=build, tools=self.paths["tools"], fmt=fmt)
        (build / "sw/runtime/simx_rt_config.stamp").write_text(compiler_sample("simx_rt", **options))
        (build / "sw/runtime/simx_config.stamp").write_text(
            compiler_sample("simx_backend", **options).rstrip() + " -DPERF_ENABLE\n")
        app_lines = compiler_sample("application", **options).splitlines()
        app_lines[1] = app_lines[1].replace(
            "-I" + str(source / "third_party/softfloat/source/include"),
            "-I" + str(source / "sw/runtime/ai"))
        app_lines[2] = "-Wl,--wrap=vx_device_open -Wl,--wrap=vx_device_release -L" + str(
            build / "sw/runtime") + " -lvortex"
        for app in runner.APPS.values():
            (build / app / "config.stamp").write_text("\n".join(app_lines) + "\n")

    def process(self, argv, cwd, env, logfile, **budgets):
        name, cwd = logfile.stem, Path(cwd)
        self.calls.append((name, list(argv), cwd, dict(env), dict(budgets)))
        text = "synthetic host-test process; no compiler or GPU execution\n"
        if name.endswith("-configure"):
            self.configure_files(cwd, name.split("-")[1])
        elif name.endswith("-header-reproduce"):
            destination = Path(next(arg[len("--output="):] for arg in argv if arg.startswith("--output=")))
            relative = "sw/VX_config.h" if name.endswith("-cpp-header-reproduce") else "hw/VX_config.vh"
            destination.write_bytes((cwd / relative).read_bytes())
        elif name.endswith("-expected-flags"):
            text = "-DVX_CFG_XLEN=64\n"
        elif name.endswith("-header"):
            if name in ("simx-fp16-header", "simx-bf16-header"):
                text = HEADER
            else:
                text = EXPANDED_HEADER
                if "-backend_cpp-" in name:
                    text += "#define PERF_ENABLE 1\n"
        elif "--case" in argv:
            values = dict(zip(argv[1::2], argv[2::2]))
            workload = next(row for row in CONTRACT["workloads"] if row["case_id"] == values["--case"])
            text = synthetic_log(workload, env["P06_SAMPLE_ID"], contract=CONTRACT,
                                 binding_id=values["--qualification-id"],
                                 source_revision=values.get("--source-revision", REVISION))
        text = self.change_log(name, text)
        logfile.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        self.after_command(name, argv, cwd)
        response = {"outcome": "pass", "exit_code": 0, "process_started": True,
                    "cleanup_complete": True, "duration_seconds": 1.0, "peak_rss_bytes": 1024,
                    "log_sha256": hashlib.sha256(logfile.read_bytes()).hexdigest(),
                    "log_size_bytes": logfile.stat().st_size, "reason": None}
        if name == self.fail_id:
            if self.exception is not None:
                raise self.exception
            response.update(self.response_changes)
            for key in self.response_remove:
                response.pop(key, None)
        return response

    def execute(self):
        report = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return report

    def sample_calls(self):
        return [call for call in self.calls if "--case" in call[1]]


class PlanAndBoundaryTests(unittest.TestCase):
    def test_canonical_full_and_selected_plans_do_not_modify_contract(self):
        original = copy.deepcopy(CONTRACT)
        for formats, count, launches in ((None, 48, 72), (["fp16"], 24, 36), (["bf16"], 24, 36)):
            workloads = runner.select_workloads(CONTRACT, formats)
            plan = runner.sample_plan(workloads, CONTRACT)
            with self.subTest(formats=formats):
                self.assertEqual(len(plan), count)
                self.assertEqual(len({row["sample_id"] for row in plan}), count)
                self.assertEqual(sum(row["expected_launches"] for row in workloads) * 6, launches)
                for index, workload in enumerate(workloads):
                    rows = plan[6 * index:6 * (index + 1)]
                    self.assertEqual([(row["phase"], row["repetition"]) for row in rows],
                                     [("warmup", 0), *[("measurement", n) for n in range(5)]])
                    self.assertEqual({row["workload_id"] for row in rows}, {workload["id"]})
        self.assertEqual(CONTRACT, original)

    def test_cli_rejects_undeclared_modes_formats_iterations_and_resource_limits(self):
        for options in (("--backend", "rtlsim"), ("--format", "tf32"), ("--iterations", "2"),
                        ("--jobs", "3"), ("--jobs", "0"), ("--timeout-seconds", "1801"),
                        ("--timeout-seconds", "0"), ("--run-timeout-seconds", "181"),
                        ("--run-timeout-seconds", "0"), ("--run-timeout-seconds", "NaN")):
            with self.subTest(options=options), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                arguments(*options)

    def test_environment_discards_ambient_configuration_and_preloads(self):
        with tempfile.TemporaryDirectory(prefix="p06-environment-") as directory:
            paths = {"host_bin": None, "work": Path(directory)}
            ambient = {key: "untrusted-value" for key in
                       ("CONFIGS", "PERF", "SIMX_FUNCTIONAL", "VORTEX_PROFILING", "LD_PRELOAD",
                        "PYTHONPATH", "CXXFLAGS", "LD_LIBRARY_PATH", "P06_SAMPLE_ID")}
            with mock.patch.dict(os.environ, ambient):
                env = runner.base.clean_environment(paths, 2)
            self.assertTrue(set(ambient).isdisjoint(env))
            self.assertEqual((env["MAKEFLAGS"], env["THREADS"], env["CCACHE_DISABLE"]), ("-j2", "2", "1"))

    def test_paths_require_fresh_nonoverlapping_unsymlinked_roots(self):
        with tempfile.TemporaryDirectory(prefix="p06-paths-") as temporary:
            parent = Path(temporary)
            tools = parent / "tools"
            tools.mkdir()
            alias = parent / "alias"
            alias.symlink_to(tools, target_is_directory=True)
            for work, output, tool_root in ((tools, parent / "packet", tools),
                    (ROOT / "p06-not-created", parent / "packet", tools),
                    (parent / "build", parent / "build/packet", tools),
                    (parent / "build", parent / "packet", alias)):
                args = arguments()
                args.source_dir, args.tools_dir = ROOT, tool_root
                args.work_dir, args.output = work, output
                with self.subTest(work=work, output=output), self.assertRaises(ValueError):
                    runner.base.resolve_paths(args)
            args.tools_dir, args.work_dir, args.output = tools, parent / "build", parent / "packet"
            self.assertEqual(runner.base.resolve_paths(args)["source"], ROOT)

    def test_snapshot_adds_own_inputs_and_loaded_helpers_to_inherited_inventory(self):
        with mock.patch.object(runner.model_run, "source_snapshot", return_value={
                "checkout": {"revision": REVISION, "inputs": ORIGINAL_HASH(ROOT, ["ci/blackbox.sh"])},
                "files": ORIGINAL_HASH(ROOT, ["configure"])}):
            snapshot = runner.source_snapshot(ROOT)
        required = {"configure", "ci/blackbox.sh", *runner.SOURCE_FILES,
                    *(row["path"] for row in runner.LOADED_HELPERS)}
        self.assertEqual({row["path"] for row in snapshot["files"]}, required)
        self.assertEqual(snapshot["files"], ORIGINAL_HASH(ROOT, sorted(required)))


class ExecutionAndRetentionTests(unittest.TestCase):
    def test_changed_runtime_source_is_blocked_before_any_process(self):
        for name in ("sw/runtime/ai/runtime.cpp", "sw/runtime/ai/runtime.h",
                     "sw/runtime/ai/mlp_runtime.cpp"):
            with self.subTest(path=name), RunnerHarness(self) as harness:
                path = harness.paths["source"] / name
                path.write_bytes(path.read_bytes() + b"\n// changed execution input\n")
                report = harness.execute()
                self.assertEqual(report["outcome"], "blocked")
                self.assertIn("frozen source input differs: " + name, report["reason"])
                self.assertEqual(report["commands"], [])
                self.assertEqual(report["samples"], [])
                self.assertEqual(harness.calls, [])
                harness.verify.assert_not_called()

    def test_selected_packet_retains_actual_logs_bindings_and_fixed_boundaries(self):
        with RunnerHarness(self) as harness:
            report = harness.execute()
            self.assertEqual(report["outcome"], "pass", report["reason"])
            self.assertEqual(report, harness.saved)
            self.assertEqual(report["completed_samples"], 24)
            self.assertTrue(report["selected_scope_completed"])
            self.assertFalse(report["full_matrix_requested"])
            self.assertFalse(report["full_matrix_completed"])
            self.assertFalse(report["acceptance_claimed"])
            self.assertFalse(report["phase_complete"])
            self.assertEqual(report["summary"]["inventory"]["total_launches"], 36)
            variant = report["variants"][0]
            self.assertEqual(variant["artifacts_before"], variant["artifacts_after"])
            self.assertEqual({row["path"] for row in variant["artifacts_before"]}, set(runner.artifacts()))
            binding = json.loads((harness.paths["output"] / variant["binding"]["path"]).read_text())
            self.assertEqual(runner.qualification_id(binding), variant["qualification_id"])
            self.assertEqual(binding["source"], harness.snapshot)
            self.assertEqual(binding["artifacts"], variant["artifacts_before"])
            self.assertEqual(binding["applications"], variant["applications"])
            self.assertEqual(binding["profile_sha256"], runner.PROFILE_SHA256)
            build = harness.paths["work"] / "simx-fp16"
            self.assertEqual((build / runner.HEADER_PROBE).read_bytes(), b"#include <VX_config.h>\n")
            for kind, application in variant["applications"].items():
                for compiler in application["compiler_records"]:
                    role = compiler["role"]
                    command = next(row for row in report["commands"]
                                   if row["id"] == "simx-fp16-" + kind + "-" + role + "-header")
                    expected_cwd = {"runtime": build / "sw/runtime/simx",
                                    "backend_cpp": build / "sim/simx"}.get(
                                        role, build / runner.APPS[kind])
                    self.assertEqual(command["cwd"], str(expected_cwd))
                    self.assertEqual(command["argv"][-1], str(build / runner.HEADER_PROBE))
                    self.assertNotIn("-include", command["argv"])
                    self.assertEqual([arg[2:] for arg in command["argv"] if arg.startswith("-I")],
                                     compiler["include_paths"])
            self.assertEqual(harness.validate_records.call_count, 2)
            self.assertEqual(harness.verify.call_count, 24)
            for row in (*report["retained_sources"], variant["binding"], report["summary_snapshot"],
                        *(item for stage in variant["retained_builds"] for item in stage["files"])):
                self.assertEqual(ORIGINAL_HASH(harness.paths["output"], [row["path"]])[0], row)
            for sample in report["samples"]:
                command = next(row for row in report["commands"] if row["id"] == sample["command_id"])
                raw = (harness.paths["output"] / command["log"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), sample["observation"]["raw_log_sha256"])
                self.assertEqual(sample["process_duration_seconds"], command["duration_seconds"])
                self.assertIn(b"synthetic host-test observation; no native execution", raw)

    def test_full_scope_builds_both_apps_once_per_format_before_frozen_sampling(self):
        with RunnerHarness(self, full=True) as harness:
            report = harness.execute()
            self.assertEqual(report["outcome"], "pass", report["reason"])
            self.assertEqual([row["id"] for row in report["variants"]], ["simx-fp16", "simx-bf16"])
            self.assertEqual((report["completed_samples"], len(harness.sample_calls())), (48, 48))
            self.assertEqual(report["summary"]["inventory"], CONTRACT["inventory"])
            self.assertTrue(report["full_matrix_completed"])
            self.assertFalse(report["acceptance_claimed"])
            ids = [call[0] for call in harness.calls]
            for fmt in ("fp16", "bf16"):
                prefix = "simx-" + fmt
                runtime = [call for call in harness.calls if call[0] == prefix + "-runtime"]
                self.assertEqual(len(runtime), 1)
                first = ids.index(prefix + "-single-dense_boundaries-warmup-0")
                for kind in ("matmul", "mlp"):
                    self.assertLess(ids.index(prefix + "-build-" + kind), first)
                self.assertEqual(runtime[0][3]["PERF"], "1")
                self.assertIn("-DITYPE=" + fmt, runtime[0][3]["CONFIGS"])
            self.assertNotEqual(report["variants"][0]["qualification_id"], report["variants"][1]["qualification_id"])

    def test_all_processes_keep_budgets_and_sample_arguments_are_original(self):
        with RunnerHarness(self) as harness:
            report = harness.execute()
            self.assertEqual(report["outcome"], "pass", report["reason"])
            self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                             "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})
            for name, argv, cwd, env, budgets in harness.calls:
                with self.subTest(command=name):
                    self.assertEqual({key: budgets[key] for key in runner.BUDGET}, runner.BUDGET)
                    self.assertEqual(budgets["resource_paths"], (
                        harness.paths["source"], harness.paths["work"], harness.paths["output"]))
                    self.assertNotIn("HOME", env)
                    self.assertNotIn("VORTEX_PROFILING", env)
                    self.assertLessEqual(budgets["timeout_seconds"], 1800)
                    if "--case" in argv:
                        self.assertEqual(argv[argv.index("--iterations") + 1], "1")
                        self.assertEqual(argv[0], str(cwd / cwd.name))
                        self.assertEqual(argv[argv.index("--module") + 1], str(cwd / "kernel.vxbin"))
                        self.assertEqual(env["VORTEX_DRIVER"], "simx")
                        self.assertEqual(env["LD_LIBRARY_PATH"], str(harness.paths["work"] / "simx-fp16/sw/runtime"))
                        self.assertEqual(name, "simx-" + env["P06_SAMPLE_ID"])
                        self.assertEqual(budgets["timeout_seconds"], 180)
                        self.assertNotIn("PERF", env)

    def test_bad_exit_cleanup_or_missing_start_stops_before_parsing_and_never_retries(self):
        for changes in ({"outcome": "fail", "exit_code": 1}, {"exit_code": 1},
                        {"cleanup_complete": False}, {"process_started": False}, {"outcome": "blocked"}):
            with self.subTest(changes=changes), RunnerHarness(self) as harness:
                harness.fail_id, harness.response_changes = FIRST_SAMPLE, changes
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("command failed", report["reason"])
                self.assertEqual(report["completed_samples"], 0)
                self.assertEqual(report["samples"][0]["outcome"], "fail")
                self.assertEqual(len(harness.sample_calls()), 1)
                harness.verify.assert_not_called()
                self.assertEqual(report["state"], "finished")

    def test_failed_measurement_keeps_warmup_and_stops_remaining_repetitions(self):
        with RunnerHarness(self) as harness:
            harness.fail_id = FIRST_SAMPLE.replace("warmup-0", "measurement-1")
            harness.response_changes = {"outcome": "fail", "exit_code": 9}
            report = harness.execute()
            self.assertEqual(report["outcome"], "fail")
            self.assertEqual([row["outcome"] for row in report["samples"]], ["pass", "pass", "fail"])
            self.assertEqual(report["completed_samples"], 2)
            self.assertEqual(harness.calls[-1][0], harness.fail_id)
            self.assertNotIn("summary", report)

    def test_log_digest_size_and_utf8_fail_before_any_numerical_parse(self):
        for changes, bad_text in (({"log_sha256": "0" * 64}, False), ({"log_size_bytes": 0}, False),
                                  ({}, True)):
            with self.subTest(changes=changes, bad_text=bad_text), RunnerHarness(self) as harness:
                harness.fail_id, harness.response_changes = FIRST_SAMPLE, changes
                if bad_text:
                    harness.change_log = lambda name, text: b"\xff\n" if name == FIRST_SAMPLE else text
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_samples"], 0)
                harness.verify.assert_not_called()
                self.assertTrue((harness.paths["output"] / ("logs/" + FIRST_SAMPLE + ".log")).exists())

    def test_missing_negative_string_and_boolean_duration_receipts_fail(self):
        for value in (None, -1, "1.0", True, "missing"):
            with self.subTest(value=value), RunnerHarness(self) as harness:
                harness.fail_id = FIRST_SAMPLE
                if value == "missing":
                    harness.response_remove = ("duration_seconds",)
                else:
                    harness.response_changes = {"duration_seconds": value}
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_samples"], 0)
                harness.verify.assert_not_called()

    def test_exceptions_and_interruption_retain_failed_command_and_sample(self):
        for error in (OSError("synthetic process error"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), RunnerHarness(self) as harness:
                harness.fail_id, harness.exception = FIRST_SAMPLE, error
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["state"], "finished")
                self.assertEqual(report["commands"][-1]["outcome"], "fail")
                self.assertEqual(report["samples"][-1]["outcome"], "fail")
                self.assertEqual(report["completed_samples"], 0)
                self.assertIn("source_after", report)

    def test_invalid_original_numerics_or_observer_log_prevents_summary(self):
        for replacement in ("PASSED!\n", "P06_FAILURE {\"reason\":\"query_failed\"}\nPASSED!\n"):
            with self.subTest(replacement=replacement), RunnerHarness(self) as harness:
                harness.change_log = lambda name, text: replacement if name == FIRST_SAMPLE else text
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(harness.verify.call_count, 1)
                self.assertEqual(report["completed_samples"], 0)
                self.assertNotIn("summary", report)


class BuildAndProvenanceFailureTests(unittest.TestCase):
    def test_resource_shortfall_and_programmatic_overbudget_arguments_block_before_processes(self):
        for kind in ("disk", "memory", "memory_missing", "jobs", "build_timeout", "run_timeout"):
            with self.subTest(kind=kind), RunnerHarness(self) as harness:
                if kind == "disk":
                    harness.resources["free_disk_bytes"]["output"] -= 1
                elif kind == "memory":
                    harness.resources["available_memory_bytes"] -= 1
                elif kind == "memory_missing":
                    harness.resources["available_memory_bytes"] = None
                else:
                    field, value = {"jobs": ("jobs", 3), "build_timeout": ("timeout_seconds", 1801),
                                    "run_timeout": ("run_timeout_seconds", 181)}[kind]
                    setattr(harness.args, field, value)
                report = harness.execute()
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(harness.calls, [])
                self.assertEqual(report["completed_samples"], 0)
                self.assertEqual(report["state"], "finished")
                self.assertFalse(report["acceptance_claimed"])

    def test_dirty_source_blocks_formal_execution_but_development_never_accepts(self):
        for development in (False, True):
            with self.subTest(development=development), RunnerHarness(self) as harness:
                harness.args.development = development
                harness.snapshot["checkout"].update(dirty=True, changed_paths=["synthetic-change"],
                    blockers=["source contains tracked changes or nonignored untracked inputs"])
                report = harness.execute()
                self.assertEqual(report["outcome"], "pass" if development else "blocked", report["reason"])
                self.assertFalse(report["acceptance_claimed"])
                self.assertFalse(report["phase_complete"])
                if not development:
                    self.assertEqual(harness.calls, [])

    def test_duplicate_format_and_changed_loaded_helper_or_fixture_header_block_early(self):
        for kind in ("formats", "helper", "fixture"):
            with self.subTest(kind=kind), RunnerHarness(self) as harness:
                if kind == "formats":
                    harness.args.format = ["fp16", "fp16"]
                elif kind == "helper":
                    changed = copy.deepcopy(runner.LOADED_HELPERS)
                    changed[0]["sha256"] = "0" * 64
                    harness.stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS", changed))
                else:
                    harness.stack.enter_context(mock.patch.object(runner, "render_header", return_value="stale\n"))
                report = harness.execute()
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(harness.calls, [])

    def test_configure_and_each_build_failure_retain_stage_and_prevent_sampling(self):
        for suffix in ("configure", "runtime", "build-matmul", "build-mlp"):
            with self.subTest(stage=suffix), RunnerHarness(self) as harness:
                harness.fail_id = "simx-fp16-" + suffix
                harness.response_changes = {"outcome": "fail", "exit_code": 2}
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(harness.calls[-1][0], harness.fail_id)
                self.assertEqual(harness.sample_calls(), [])
                self.assertEqual(report["variants"][0]["retained_builds"][-1]["stage"], "failure")

    def test_stale_generated_makefile_header_and_copied_inputs_are_rejected(self):
        for kind in ("makefile", "header", "copied"):
            with self.subTest(kind=kind), RunnerHarness(self) as harness:
                def change(name, argv, cwd):
                    if kind == "makefile" and name.endswith("-configure"):
                        (cwd / runner.APPS["mlp"] / "Makefile").write_text("stale benchmark makefile\n")
                    elif kind == "copied" and name.endswith("-configure"):
                        (cwd / "sw/runtime/common.mk").write_text("stale shared makefile\n")
                    elif kind == "header" and name.endswith("-cpp-header-reproduce"):
                        (cwd / "p06-header-check/VX_config.h").write_text("stale header\n")
                harness.after_command = change
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(harness.sample_calls(), [])

    def test_actual_bad_compiler_stamp_and_effective_header_fail_before_samples(self):
        for kind in ("compiler", "header", "flags"):
            with self.subTest(kind=kind), RunnerHarness(self) as harness:
                def change(name, argv, cwd):
                    if kind == "compiler" and name == "simx-fp16-build-mlp":
                        path = cwd / "config.stamp"
                        path.write_text(path.read_text().replace("-DKUNROLL=1", "-DKUNROLL=2"))
                harness.after_command = change
                if kind == "header":
                    harness.change_log = lambda name, text: (text + "#define VX_CFG_UNDECLARED_LATENCY 9\n"
                        if name == "simx-fp16-mlp-host-header" else text)
                elif kind == "flags":
                    harness.change_log = lambda name, text: "-include /unretained/header\n" if name.endswith("-expected-flags") else text
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(harness.sample_calls(), [])

    def test_shared_runtime_and_kernel_mismatch_cannot_be_frozen(self):
        for kind in ("runtime", "kernel"):
            with self.subTest(kind=kind), RunnerHarness(self) as harness:
                def change(name, argv, cwd):
                    if name == "simx-fp16-build-mlp":
                        target = (harness.paths["work"] / "simx-fp16/sw/runtime/libsimx.so"
                                  if kind == "runtime" else cwd / "kernel.vxbin")
                        target.write_text("changed synthetic build input\n")
                harness.after_command = change
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("shared runtime changed" if kind == "runtime" else "kernels differ", report["reason"])
                self.assertEqual(harness.sample_calls(), [])
                self.assertNotIn("qualification_id", report["variants"][0])

    def test_artifact_drift_before_and_during_sample_invalidates_packet(self):
        for when in ("before", "during"):
            with self.subTest(when=when), RunnerHarness(self) as harness:
                target = harness.paths["work"] / "simx-fp16" / runner.APPS["matmul"] / "kernel.vxbin"
                if when == "before":
                    harness.on_snapshot = lambda count: target.write_text("changed before sample\n") if count == 3 else None
                else:
                    harness.after_command = lambda name, argv, cwd: target.write_text("changed during sample\n") if name == FIRST_SAMPLE else None
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("artifacts changed " + when + " sample", report["reason"])
                self.assertEqual(report["completed_samples"], 0)
                self.assertEqual(len(harness.sample_calls()), 0 if when == "before" else 1)
                harness.verify.assert_not_called()
                self.assertTrue(any(row["stage"] == "final-build-snapshot" for row in report["failures"]))

    def test_source_tool_and_dependency_final_drift_override_completed_samples(self):
        for kind in ("source", "tools", "dependencies"):
            with self.subTest(kind=kind), RunnerHarness(self) as harness:
                harness.final_drift = kind
                report = harness.execute()
                self.assertEqual(report["completed_samples"], 24)
                self.assertEqual(report["outcome"], "fail")
                self.assertFalse(report[kind + "_stable"])
                self.assertFalse(report["selected_scope_completed"])
                self.assertFalse(report["full_matrix_completed"])
                self.assertEqual(report["failures"][-1]["stage"], "final-" + kind + "-snapshot")
                self.assertEqual(report, harness.saved)

    def test_final_resource_inventory_error_overrides_apparent_success(self):
        with RunnerHarness(self) as harness:
            harness.final_resource_error = True
            report = harness.execute()
            self.assertEqual(report["completed_samples"], 24)
            self.assertEqual(report["outcome"], "fail")
            self.assertEqual(report["failures"][-1]["stage"], "final-resources")
            self.assertFalse(report["selected_scope_completed"])

    def test_main_reports_path_block_without_running_external_commands(self):
        output = io.StringIO()
        with mock.patch.object(runner.base, "resolve_paths", side_effect=ValueError("synthetic unsafe path")), \
                mock.patch.object(runner, "execute") as execute, redirect_stdout(output):
            result = runner.main(["run", "--tools-dir", "/unused/tools", "--work-dir", "/unused/build", "--output", "/unused/packet"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "blocked")
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
