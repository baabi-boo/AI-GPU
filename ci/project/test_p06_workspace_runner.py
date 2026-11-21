# SPDX-License-Identifier: Apache-2.0
"""Python-only workspace orchestration tests, never native execution evidence.

Only external process, tool/resource and checkout observations are simulated.
Fixture producers, compiler records, output parsing, generated-input checks,
hashes, bindings, completion decisions and retained packets stay real.
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

import p06_workspace_execute as runner
import p06_workspace_test_samples as samples
from baseline_inventory import SOURCE_INPUTS
from test_p02_matrix import BUILD, SOURCE, TOOLS, STAMP_SAMPLES


ROOT = runner.ROOT
ORIGINAL_HASH = runner.hash_artifacts
ORIGINAL_DIGEST = runner._digest
CONTRACT = runner.load_contract()
BACKENDS = ("simx", "rtlsim")
FORMATS = ("fp16", "bf16")
POLICIES = ("per_operation", "reusable_single_tile")
SEQUENCE = ("single-dense_boundaries", "numerical-zero", "single-k03",
            "single-dense_boundaries")
HEADER = STAMP_SAMPLES["header"]
EXPANDED_HEADER = HEADER.rstrip() + "\n" + "".join(
    "#define " + name + "_DISABLE 1\n" for name in runner.DISABLED)
FIRST_PROCESS = "simx-fp16-per_operation"
SECOND_PROCESS = "simx-fp16-reusable_single_tile"


def arguments(*options):
    return runner.argument_parser().parse_args([
        "run", "--tools-dir", "/workspace-host-test/tools",
        "--work-dir", "/workspace-host-test/work", "--output", "/workspace-host-test/output",
        *options])


class WorkspaceHarness:
    """Write synthetic external observations around the unmodified runner."""

    def __init__(self, test, *options, full=False):
        self.args = arguments(*(options or (() if full else ("--backend", "simx", "--format", "fp16"))))
        temporary = tempfile.TemporaryDirectory(prefix="workspace-runner-host-")
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
        self.variant_count = len(self.args.backend or BACKENDS) * len(self.args.format or FORMATS)
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
        if self.snapshot_calls == 2 + 6 * self.variant_count:
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
        names = ("g++", "clang", "make", "python3", "riscv-gcc", "verilator")
        result = {name: {"path": "/workspace-host-test/" + name,
                         "sha256": "a" * 64, "size_bytes": 1} for name in names}
        if self.drift == "tools":
            result["clang"]["sha256"] = "b" * 64
        return result

    def hash_artifacts(self, root, names):
        names = tuple(names)
        if Path(root) == ROOT and names == runner.base.DEPENDENCIES:
            return [{"path": name, "sha256": ("b" if self.drift == "dependencies" else "a") * 64,
                     "size_bytes": 1} for name in names]
        return ORIGINAL_HASH(root, names)

    def configure_files(self, build, driver, fmt):
        for relative in runner.artifacts(driver):
            if relative == runner.HEADER_PROBE:
                continue
            path = build / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic host-test build; no executable: " + fmt + ":" + relative + "\n")
        for relative in runner.base.COPIED + (runner.APP + "/Makefile",):
            (build / relative).write_bytes((ROOT / relative).read_bytes())
        (build / "sim/rtlsim/verilator.vlt").write_text(
            (ROOT / "sim/rtlsim/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(ROOT)))
        settings = {"XLEN": "64", "PROFILE": "p02-tfr", "VORTEX_HOME": str(ROOT),
                    "TOOLDIR": str(self.paths["tools"]), "OSVERSION": "ubuntu/focal"}
        (build / "config.mk").write_text("".join(key + " ?= " + value + "\n" for key, value in settings.items()))
        (build / ".config.stamp").write_text(
            "XLEN=64 PROFILE=p02-tfr SOURCE_DIR=" + str(ROOT) + " BUILDDIR=" + str(build)
            + " TOOLDIR=" + str(self.paths["tools"]) + "\n")
        stamps = samples.compiler_stamps(driver, fmt, self.args.jobs)
        names = ("sw/runtime/" + driver + "_rt_config.stamp",
                 "sw/runtime/" + driver + "_config.stamp", runner.APP + "/config.stamp")
        for relative, stamp in zip(names, stamps):
            for before, after in ((SOURCE, ROOT), (BUILD, build), (TOOLS, self.paths["tools"])):
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
            text = HEADER if name in {driver + "-" + fmt + "-header" for driver in BACKENDS for fmt in FORMATS} else EXPANDED_HEADER
            if name.startswith("rtlsim-") and name.endswith("-backend_cpp-header"):
                text = "\n".join(line for line in text.splitlines()
                                 if not line.startswith(("#define VX_CFG_TCU_TYPE_TFR ",
                                                         "#define VX_CFG_FPU_TYPE_STD "))) + "\n"
        elif "--policy" in argv:
            values = dict(zip(argv[1::2], argv[2::2]))
            records = samples.process_records(name.split("-")[1], values["--policy"])
            for record in [*records["operations"], records["summary"]]:
                record["qualification_id"] = values["--qualification-id"]
            self.change_records(name, records)
            text = samples.render_log(records)
        text = self.change_log(name, text)
        logfile.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        self.after_command(name, argv, cwd)
        response = {"outcome": "pass", "exit_code": 0, "process_started": True,
                    "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024,
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
        result = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return result

    def launches(self):
        return [call for call in self.calls if "--policy" in call[1]]


class WorkspaceSelectionAndBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = runner.load_cases(ROOT)

    def test_full_and_all_selected_scopes_keep_canonical_four_call_sequences(self):
        original = copy.deepcopy(self.cases)
        for backends in (None, ["simx"], ["rtlsim"], ["rtlsim", "simx"]):
            for formats in (None, ["fp16"], ["bf16"], ["bf16", "fp16"]):
                with self.subTest(backends=backends, formats=formats):
                    args = arguments()
                    args.backend, args.format = backends, formats
                    cases, variants, full = runner.select_cases(self.cases, args, CONTRACT)
                    expected = [(driver, fmt) for driver in BACKENDS if driver in (backends or BACKENDS)
                                for fmt in FORMATS if fmt in (formats or FORMATS)]
                    self.assertEqual(variants, expected)
                    self.assertIs(full, len(expected) == 4)
                    self.assertEqual([row["id"] for row in cases],
                                     [fmt + "-" + suffix for fmt in FORMATS if fmt in (formats or FORMATS)
                                      for suffix in SEQUENCE])
                    plan = runner.process_plan(variants, CONTRACT)
                    self.assertEqual([(row["backend"], row["format"], row["policy"]) for row in plan],
                                     [(driver, fmt, policy) for driver, fmt in expected for policy in POLICIES])
                    self.assertEqual(len({row["id"] for row in plan}), 2 * len(expected))
                    for row in plan:
                        self.assertEqual(row["case_ids"], [row["format"] + "-" + suffix for suffix in SEQUENCE])
        self.assertEqual(self.cases, original)

    def test_empty_duplicate_unsupported_and_incomplete_selections_are_rejected(self):
        for field, values in (("backend", []), ("backend", ["simx", "simx"]),
                              ("backend", ["xrt"]), ("format", []),
                              ("format", ["fp16", "fp16"]), ("format", ["tf32"])):
            with self.subTest(field=field, values=values):
                args = arguments()
                setattr(args, field, values)
                with self.assertRaises(ValueError):
                    runner.select_cases(self.cases, args, CONTRACT)
        for mutation in ("missing", "duplicate", "shape", "unchanged_input"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.cases)
                if mutation == "missing":
                    changed.pop()
                elif mutation == "duplicate":
                    changed[-1] = copy.deepcopy(changed[0])
                else:
                    case = next(row for row in changed if row["id"] == "fp16-numerical-zero")
                    if mutation == "shape":
                        case["m"] = 16
                    else:
                        case["a_words"] = next(row["a_words"] for row in changed
                                               if row["id"] == "fp16-single-dense_boundaries")
                with self.assertRaises(ValueError):
                    runner.select_cases(changed, arguments(), CONTRACT)

    def test_cli_exposes_no_scope_policy_dirty_source_or_budget_escape(self):
        forbidden = [("--development",), ("--case", "fp16-single-k03"), ("--iterations", "1"),
                     ("--policy", "per_operation"), ("--allow-dirty",), ("--warmups", "0"),
                     ("--max-rss-bytes", "8589934592"), ("--min-free-bytes", "0"),
                     ("--max-log-bytes", "33554432"), ("--jobs", "0"), ("--jobs", "3"),
                     ("--timeout-seconds", "0"), ("--timeout-seconds", "1801"),
                     ("--run-timeout-seconds", "0"), ("--run-timeout-seconds", "181")]
        for options in forbidden:
            with self.subTest(options=options), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                arguments(*options)
            self.assertEqual(error.exception.code, 2)
        args = arguments("--jobs", "1", "--timeout-seconds", "1", "--run-timeout-seconds", "1")
        self.assertEqual((args.jobs, args.timeout_seconds, args.run_timeout_seconds), (1, 1, 1))
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                                      "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})

    def test_paths_require_fresh_disjoint_source_external_real_directories(self):
        with tempfile.TemporaryDirectory(prefix="workspace-paths-") as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            args = arguments("--source-dir", str(ROOT), "--tools-dir", str(tools),
                             "--work-dir", str(root / "work"), "--output", str(root / "packet"))
            good = runner.base.resolve_paths(args)
            self.assertNotEqual(good["work"], good["output"])
            link = root / "tools-link"
            link.symlink_to(tools, target_is_directory=True)
            for field, value in (("work_dir", tools), ("output", tools), ("output", args.work_dir),
                                 ("work_dir", ROOT / "workspace-test-build"),
                                 ("output", ROOT / "workspace-test-packet"),
                                 ("work_dir", root / "absent" / "work"),
                                 ("tools_dir", link), ("source_dir", root),
                                 ("work_dir", root / "unsafe path")):
                with self.subTest(field=field, value=value):
                    changed = copy.copy(args)
                    setattr(changed, field, value)
                    with self.assertRaises(ValueError):
                        runner.base.resolve_paths(changed)
            args.work_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "fresh"):
                runner.base.resolve_paths(args)

    def test_source_inventory_binds_checkout_inputs_runtime_and_transitive_helpers(self):
        checkout = {"revision": "1" * 40, "tree": "2" * 40, "dirty": False,
                    "changed_paths": [], "untracked_paths": [], "blockers": [],
                    "inputs": ORIGINAL_HASH(ROOT, SOURCE_INPUTS)}
        with mock.patch.object(runner.base, "collect_source", return_value=checkout):
            snapshot = runner.source_snapshot(ROOT)
        names = {row["path"] for row in snapshot["files"]}
        expected = set(runner.SOURCE_FILES + runner.operator_run.SOURCE_FILES + SOURCE_INPUTS
                       + runner.base.CORPUS + runner.base.COPIED + runner.base.TOOLING)
        expected.update("ci/project/" + name for name in (
            "p06_workspace_compiler_records.py", "p06_compiler_records.py", "compiler_records.py",
            "baseline_packet_contract.py", "baseline_packet_io.py", "p02_fixture_oracle.py",
            "p02_layout_fixture_oracle.py", "p02_wmma_numerical_fixture_oracle.py"))
        self.assertLessEqual(expected, names)
        self.assertLessEqual({row["path"] for row in runner.LOADED_HELPERS}, names)
        self.assertEqual(len(names), len(snapshot["files"]))
        self.assertEqual(snapshot["files"], ORIGINAL_HASH(ROOT, sorted(names)))
        self.assertEqual(snapshot["checkout"], checkout)


class WorkspaceExecutionTests(unittest.TestCase):
    def assert_no_acceptance(self, report):
        for key in ("acceptance_claimed", "performance_acceptance", "phase_acceptance", "phase_complete"):
            self.assertIs(report[key], False, key)

    def test_full_matrix_runs_eight_distinct_policy_processes_and_checks_real_records(self):
        with WorkspaceHarness(self, full=True) as harness:
            report = harness.execute()
            self.assertEqual(report["outcome"], "pass", report["reason"])
            expected_ids = [driver + "-" + fmt + "-" + policy
                            for driver in BACKENDS for fmt in FORMATS for policy in POLICIES]
            self.assertEqual([item["id"] for item in report["processes"]], expected_ids)
            self.assertEqual([item[0] for item in harness.launches()], expected_ids)
            self.assertEqual((report["completed_processes"], report["completed_launches"], report["checked_words"]),
                             (8, 32, 1024))
            self.assertTrue(report["full_matrix_requested"])
            self.assertTrue(report["full_matrix_completed"])
            self.assertTrue(report["selected_scope_completed"])
            self.assertEqual(harness.verify.call_count, 8)
            self.assertEqual(harness.validate_records.call_count, 4)
            self.assertEqual(len({row["qualification_id"] for row in report["processes"]}), 8)
            self.assertEqual(report, harness.saved)
            self.assert_no_acceptance(report)
            self.assertTrue(report["retained_files_stable"])
            self.assertEqual(report["raw_logs"], ORIGINAL_HASH(
                harness.paths["output"], [row["log"] for row in report["commands"]]))
            for variant in report["variants"]:
                self.assertEqual(variant["artifacts_before"], variant["artifacts_after"])
                self.assertEqual(set(variant["effective_headers"]),
                                 {"runtime", "backend_cpp", "kernel", "host"}
                                 | ({"verilator"} if variant["backend"] == "rtlsim" else set()))
            for process, call in zip(report["processes"], harness.launches()):
                binding = json.loads((harness.paths["output"] / process["binding"]["path"]).read_text())
                self.assertEqual(runner.qualification_id(binding), process["qualification_id"])
                self.assertEqual(binding["policy"], process["policy"])
                self.assertEqual(binding["process_id"], process["id"])
                self.assertEqual([case["id"] for case in binding["cases"]], process["case_ids"])
                self.assertEqual(binding["sequence"], CONTRACT["sequence"])
                self.assertLessEqual({"source", "corpus", "tools", "dependencies", "compiler_records",
                                     "effective_headers", "generated_identity", "artifacts",
                                     "contract_sha256", "profile_sha256", "kernel_source_sha256"}, set(binding))
                app = harness.paths["work"] / (process["backend"] + "-" + process["format"]) / runner.APP
                self.assertEqual(call[1], [str(app / "ai_workspace"), "--policy", process["policy"],
                                          "--module", str(app / "kernel.vxbin"), "--qualification-id",
                                          process["qualification_id"]])
                self.assertEqual(call[2], app)
                self.assertEqual(call[3]["VORTEX_DRIVER"], process["backend"])
                self.assertEqual(call[3]["LD_LIBRARY_PATH"], str(app.parents[2] / "sw/runtime"))

    def test_each_selected_variant_completes_both_policies_without_full_matrix_claim(self):
        for driver in BACKENDS:
            for fmt in FORMATS:
                with self.subTest(driver=driver, fmt=fmt), WorkspaceHarness(
                        self, "--backend", driver, "--format", fmt) as harness:
                    report = harness.execute()
                    self.assertEqual(report["outcome"], "pass", report["reason"])
                    self.assertEqual((report["completed_processes"], report["completed_launches"], report["checked_words"]),
                                     (2, 8, 256))
                    self.assertEqual(report["selected_counts"], {"processes": 2, "launches": 8, "checked_words": 256})
                    self.assertEqual(len(report["variants"]), 1)
                    self.assertEqual([row["policy"] for row in report["processes"]], list(POLICIES))
                    self.assertTrue(report["selected_scope_completed"])
                    self.assertFalse(report["full_matrix_requested"])
                    self.assertFalse(report["full_matrix_completed"])
                    self.assert_no_acceptance(report)

    def test_command_limits_and_environments_cannot_inherit_ambient_escape_flags(self):
        injected = {"PATH": "/untrusted", "HOME": "/untrusted", "CONFIGS": "-DPERF_ENABLE",
                    "MAKEFLAGS": "-j100", "THREADS": "100", "CMAKE_BUILD_PARALLEL_LEVEL": "100",
                    "CCACHE_DISABLE": "0", "OBJCACHE": "ccache", "CXX": "/untrusted/compiler",
                    "BASH_ENV": "/untrusted/script", "PYTHONPATH": "/untrusted/python",
                    "LD_PRELOAD": "/untrusted/library", "LD_LIBRARY_PATH": "/untrusted/lib",
                    "VORTEX_DRIVER": "xrt", "SIMX_FAST": "1", "P06_POLICY": "escape"}
        with mock.patch.dict(os.environ, injected), WorkspaceHarness(self) as harness:
            report = harness.execute()
            self.assertEqual(report["outcome"], "pass", report["reason"])
            base_env = runner.base.clean_environment(harness.paths, 2)
            base_env.pop("HOME")
            for name, argv, cwd, environment, budgets in harness.calls:
                expected = dict(base_env)
                if name.endswith(("-runtime", "-application")):
                    expected["CONFIGS"] = "-DITYPE=fp16 -DOTYPE=fp32 -DKUNROLL=1"
                    self.assertIn("-j2", argv)
                    self.assertIn("THREADS=2", argv)
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
            self.assertEqual(report["budget"]["jobs"], 2)

    def test_nonzero_timeout_incomplete_cleanup_and_missing_receipt_stop_at_failed_policy(self):
        responses = [({"outcome": "fail", "exit_code": 9, "reason": "synthetic nonzero exit"}, ()),
                     ({"outcome": "fail", "exit_code": -15, "reason": "wall timeout"}, ()),
                     ({"exit_code": 1}, ()), ({"cleanup_complete": False}, ()),
                     ({"process_started": False}, ()), ({}, ("exit_code",))]
        for changes, removed in responses:
            with self.subTest(changes=changes, removed=removed), WorkspaceHarness(self, full=True) as harness:
                harness.fail_id = SECOND_PROCESS
                harness.response_changes, harness.response_remove = changes, removed
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual((report["completed_processes"], report["completed_launches"], report["checked_words"]),
                                 (1, 4, 128))
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

    def test_successful_exit_does_not_hide_partial_reordered_wrong_bits_or_wrong_policy_output(self):
        for mutation in ("partial", "reordered", "bits", "policy", "binding", "close"):
            with self.subTest(mutation=mutation), WorkspaceHarness(self) as harness:
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
                    else:
                        records["operations"][0]["results"]["close"]["complete"] = False
                harness.change_records = change
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 1)
                self.assertEqual(report["commands"][-1]["exit_code"], 0)
                self.assertEqual(harness.verify.call_count, 2)
                self.assertFalse(report["selected_scope_completed"])
                self.assertFalse(report["full_matrix_completed"])
                self.assertEqual(report["processes"][-1]["outcome"], "fail")
                self.assertIn("log", report["processes"][-1])


class WorkspaceProvenanceAndFailureTests(unittest.TestCase):
    def test_invalid_programmatic_budgets_and_resource_shortfalls_block_before_commands(self):
        for kind in ("disk", "memory", "memory_missing", "jobs", "jobs_bool", "build_timeout", "run_timeout"):
            with self.subTest(kind=kind), WorkspaceHarness(self) as harness:
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

    def test_dirty_source_stale_helper_frozen_kernel_profile_and_fixture_block_early(self):
        for kind in ("dirty", "helper", "kernel", "profile", "fixture"):
            with self.subTest(kind=kind), WorkspaceHarness(self) as harness:
                if kind == "dirty":
                    harness.args.development = True
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

    def test_failed_build_commands_keep_generated_inputs_and_prevent_policy_execution(self):
        for stage in ("configure", "runtime", "application"):
            with self.subTest(stage=stage), WorkspaceHarness(self) as harness:
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

    def test_stale_generated_makefiles_headers_compiler_records_and_effective_headers_fail(self):
        for kind in ("makefile", "copied", "configuration", "header", "compiler", "effective", "flags"):
            with self.subTest(kind=kind), WorkspaceHarness(self) as harness:
                def change(name, argv, cwd):
                    if name.endswith("-configure"):
                        targets = {"makefile": runner.APP + "/Makefile", "copied": "sw/runtime/common.mk",
                                   "configuration": "config.mk"}
                        if kind in targets:
                            (cwd / targets[kind]).write_text("stale generated input\n")
                    elif kind == "header" and name.endswith("-cpp-header-reproduce"):
                        (cwd / Path(runner.HEADER_PROBE).parent / "VX_config.h").write_text("stale header\n")
                    elif kind == "compiler" and name.endswith("-application"):
                        path = cwd / "config.stamp"
                        path.write_text(path.read_text().replace("-DKUNROLL=1", "-DKUNROLL=2"))
                harness.after_command = change
                if kind == "effective":
                    harness.change_log = lambda name, text: text + "#define PERF_ENABLE(x) x\n" if name.endswith("-host-header") else text
                elif kind == "flags":
                    harness.change_log = lambda name, text: "-include /unretained/header\n" if name.endswith("-expected-flags") else text
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail", report["reason"])
                self.assertEqual(harness.launches(), [])
                self.assertTrue(report["failures"])
                self.assertFalse(report["selected_scope_completed"])

    def test_source_tool_and_dependency_drift_retains_first_completed_process_and_failed_attempt(self):
        for kind in ("source", "tools", "dependencies"):
            with self.subTest(kind=kind), WorkspaceHarness(self) as harness:
                harness.after_command = lambda name, argv, cwd: setattr(harness, "drift", kind) if name == SECOND_PROCESS else None
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn(kind + " changed", report["reason"])
                self.assertEqual(report["completed_processes"], 1)
                self.assertEqual(report["processes"][-1]["outcome"], "fail")
                self.assertFalse(report[kind + "_stable"])
                self.assertIn("final-" + kind + "-snapshot", {row["stage"] for row in report["failures"]})
                self.assertFalse(report["full_matrix_completed"])

    def test_artifact_drift_before_and_during_policy_prevents_a_passing_observation(self):
        for when in ("before", "during"):
            for artifact in ("ai_workspace", "kernel.vxbin"):
                with self.subTest(when=when, artifact=artifact), WorkspaceHarness(self) as harness:
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

    def test_final_stability_failures_override_apparent_full_matrix_success(self):
        for kind in ("source", "tools", "dependencies", "resources"):
            with self.subTest(kind=kind), WorkspaceHarness(self, full=True) as harness:
                if kind == "resources":
                    harness.final_resource_error = True
                else:
                    harness.final_drift = kind
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 8)
                self.assertEqual(report["completed_launches"], 32)
                self.assertEqual(report["checked_words"], 1024)
                self.assertFalse(report["selected_scope_completed"])
                self.assertFalse(report["full_matrix_completed"])
                self.assertIn("final-resources" if kind == "resources" else "final-" + kind + "-snapshot",
                              {row["stage"] for row in report["failures"]})
                self.assertEqual(report, harness.saved)

    def test_raw_log_and_retained_source_build_binding_tampering_invalidates_completed_scope(self):
        for kind in ("log", "source", "build", "binding"):
            with self.subTest(kind=kind), WorkspaceHarness(self) as harness:
                def change(name, argv, cwd):
                    if name != SECOND_PROCESS:
                        return
                    relative = {
                        "log": "logs/" + FIRST_PROCESS + ".log",
                        "source": "artifacts/source/ci/project/p06_workspace_execute.py",
                        "build": "artifacts/simx-fp16/frozen/" + runner.APP + "/config.stamp",
                        "binding": "snapshots/" + FIRST_PROCESS + "-binding.json",
                    }[kind]
                    path = harness.paths["output"] / relative
                    path.write_bytes(path.read_bytes() + b"tampered\n")
                harness.after_command = change
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 2)
                self.assertFalse(report["selected_scope_completed"])
                self.assertFalse(report["full_matrix_completed"])
                self.assertIn("final-log-verification" if kind == "log" else "final-retained-evidence",
                              {row["stage"] for row in report["failures"]})
                self.assertEqual(report, harness.saved)

    def test_missing_or_mismatched_log_receipts_never_verify_process_output(self):
        for changes in ({"log_sha256": "0" * 64}, {"log_size_bytes": 1}, {"log_sha256": None}):
            with self.subTest(changes=changes), WorkspaceHarness(self) as harness:
                harness.fail_id, harness.response_changes = FIRST_PROCESS, changes
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["completed_processes"], 0)
                self.assertIn("log", report["reason"])
                harness.verify.assert_not_called()
                self.assertIn("final-log-verification", {row["stage"] for row in report["failures"]})

    def test_main_reports_fresh_path_block_without_launching_commands(self):
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
