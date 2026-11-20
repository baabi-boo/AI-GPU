# SPDX-License-Identifier: Apache-2.0
"""Host-only orchestration and fail-closed tests for the P04 execution runner.

The process boundary, source inventory, tool inventory, and compiler probes are
simulated. No compiler, simulator, GPU, or native application runs here. Fixture
loading, generated fixture comparison, file hashes, packet writing, selection,
and output-record verification use production helpers. Synthetic observation
records are shared with the record parser's adversarial tests, not GPU evidence.
"""

from contextlib import ExitStack, redirect_stderr
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p04_execute as runner
from p04_fixture_adapter import load_cases
from test_p04_execution_records import output, result


ROOT = runner.ROOT
REVISION = "1234567890abcdef" * 2 + "12345678"
CASES = load_cases(ROOT)


def arguments(*options):
    return runner.base.argument_parser().parse_args([
        "run", "--tools-dir", "/p04-host-harness/tools",
        "--work-dir", "/p04-host-harness/work", "--output", "/p04-host-harness/output",
        *options])


class RunnerHarness:
    """Fake external processes around the real runner's acceptance decisions."""

    def __init__(self, test, *options):
        self.args = arguments(*(options or ("--backend", "simx", "--case", "fp16-zero")))
        temporary = tempfile.TemporaryDirectory(prefix="p04-runner-host-", dir=ROOT.parent)
        test.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = {"source": ROOT, "work": root / "work", "output": root / "output",
                      "tools": root / "tools", "host_bin": None, "verilator": root / "tools/verilator"}
        self.paths["tools"].mkdir()
        self.snapshot = {"checkout": {"revision": REVISION, "tree": "f" * 40,
                                     "dirty": False, "changed_paths": [], "untracked_paths": [],
                                     "blockers": []}, "files": []}
        self.resources = {"available_memory_bytes": runner.BUDGET["max_rss_bytes"],
                          "free_disk_bytes": {key: runner.BUDGET["min_free_bytes"]
                                              for key in ("source", "tools", "work", "output")}}
        self.process_calls = []
        self.snapshots = self.tool_calls = self.dependency_calls = 0
        self.source_drift_at = self.tool_drift_at = self.dependency_drift_at = None
        self.fail_id = None
        self.process_result = {}
        self.after_command = lambda name, argv, cwd: None
        self.change_log = lambda text: text
        self.hash_files = runner.hash_artifacts
        self.compiler_records = [dict(role="runtime"), dict(role="backend_cpp", macro_flags=[]),
                                 dict(role="kernel"), dict(role="host")]
        self.stack = ExitStack()
        test.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(runner, "source_snapshot", side_effect=self.source_snapshot))
        self.stack.enter_context(mock.patch.object(runner.base, "_resources", side_effect=lambda _: copy.deepcopy(self.resources)))
        self.stack.enter_context(mock.patch.object(runner.base, "tool_inventory", side_effect=self.tool_inventory))
        self.stack.enter_context(mock.patch.object(runner, "hash_artifacts", side_effect=self.hash_artifacts))
        self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.process))
        self.stack.enter_context(mock.patch.object(runner.base, "_generated_identity", return_value=[]))
        self.stack.enter_context(mock.patch.object(runner, "validate_header_macros", return_value={"host_mock": True}))
        self.validate_records = self.stack.enter_context(mock.patch.object(
            runner, "validate_records", return_value=self.compiler_records))
        self.verify = self.stack.enter_context(mock.patch.object(runner, "verify_output", wraps=runner.verify_output))

    def source_snapshot(self, source):
        self.snapshots += 1
        value = copy.deepcopy(self.snapshot)
        if self.source_drift_at is not None and self.snapshots >= self.source_drift_at:
            value["files"].append({"path": "changed-during-host-test", "sha256": "f" * 64})
        return value

    def tool_inventory(self, paths, env, backends):
        self.tool_calls += 1
        value = {name: {"path": "/p04-host-harness/" + name, "sha256": "a" * 64}
                 for name in ("g++", "clang", "make", "python3", "verilator")}
        if self.tool_drift_at is not None and self.tool_calls >= self.tool_drift_at:
            value["g++"]["sha256"] = "b" * 64
        return value

    def hash_artifacts(self, root, paths):
        if Path(root) == ROOT and tuple(paths) == runner.base.DEPENDENCIES:
            self.dependency_calls += 1
            changed = self.dependency_drift_at is not None and self.dependency_calls >= self.dependency_drift_at
            return [{"path": path, "sha256": ("b" if changed else "a") * 64,
                     "size_bytes": 1} for path in paths]
        return self.hash_files(root, paths)

    def process(self, argv, cwd, env, logfile, **budgets):
        name = logfile.stem
        self.process_calls.append((name, list(argv), Path(cwd), dict(env), dict(budgets)))
        text = "host-only synthetic process output\n"
        if name.endswith("-configure"):
            driver = name.split("-")[0]
            for relative in runner.artifacts(driver):
                destination = cwd / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("host-only simulated artifact: " + relative + "\n")
            (cwd / runner.APP / "Makefile").write_bytes((ROOT / runner.APP / "Makefile").read_bytes())
        elif name.endswith("-header-reproduce"):
            destination = Path(next(arg[len("--output="):] for arg in argv if arg.startswith("--output=")))
            relative = "sw/VX_config.h" if name.endswith("-cpp-header-reproduce") else "hw/VX_config.vh"
            destination.write_bytes((cwd / relative).read_bytes())
        elif "--case" in argv:
            values = {argv[index]: argv[index + 1] for index in range(1, len(argv), 2)}
            case = next(case for case in CASES if case["id"] == values["--case"])
            rows = []
            for iteration in range(int(values["--iterations"])):
                row = result(case, iteration, values["--backend"])
                row["source_revision"] = values["--source-revision"]
                row["qualification_id"] = values["--qualification-id"]
                for stage in row["trace"]["native"]:
                    stage["dispatch"]["qualification_id"] = values["--qualification-id"]
                rows.append(row)
            text = self.change_log(output(rows))
        logfile.write_text(text)
        self.after_command(name, argv, Path(cwd))
        response = {"outcome": "pass", "exit_code": 0, "cleanup_complete": True,
                    "log_sha256": hashlib.sha256(logfile.read_bytes()).hexdigest(),
                    "log_size_bytes": logfile.stat().st_size, "reason": None}
        if name == self.fail_id:
            response.update(self.process_result)
        return response

    def execute(self):
        report = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return report


class SelectionTests(unittest.TestCase):
    def test_full_inventory_means_twenty_cases_forty_models_and_120_launches(self):
        before = copy.deepcopy(CASES)
        cases, variants, full = runner.select_cases(CASES, arguments())
        self.assertEqual(variants, [("simx", "fp16"), ("simx", "bf16"),
                                    ("rtlsim", "fp16"), ("rtlsim", "bf16")])
        executions = sum(case["format"] == fmt for _, fmt in variants for case in cases)
        self.assertEqual((len(cases), executions, executions * 2, executions * 6), (10, 20, 40, 120))
        self.assertTrue(full)
        self.assertEqual(CASES, before)

    def test_clean_partial_selection_preserves_order_and_never_claims_full(self):
        args = arguments("--backend", "rtlsim", "--case", "bf16-split_boundary",
                         "--case", "bf16-zero", "--iterations", "1")
        self.assertFalse(args.development)
        cases, variants, full = runner.select_cases(CASES, args)
        self.assertEqual([case["id"] for case in cases], ["bf16-zero", "bf16-split_boundary"])
        self.assertEqual(variants, [("rtlsim", "bf16")])
        self.assertFalse(full)
        self.assertFalse(runner.select_cases(CASES, arguments("--iterations", "1"))[2])

    def test_duplicate_unknown_conflicting_and_empty_selections_are_rejected(self):
        candidates = [("--backend", "simx", "--backend", "simx"),
                      ("--format", "fp16", "--format", "fp16"),
                      ("--case", "fp16-zero", "--case", "fp16-zero"),
                      ("--case", "missing"), ("--format", "bf16", "--case", "fp16-zero")]
        for options in candidates:
            with self.subTest(options=options), self.assertRaises(ValueError):
                runner.select_cases(CASES, arguments(*options))
        args = arguments()
        args.case = []
        with self.assertRaises(ValueError):
            runner.select_cases(CASES, args)

    def test_missing_duplicate_reordered_and_extra_inventory_is_rejected(self):
        for cases in (CASES[:-1], [CASES[0], *CASES[:-1]], list(reversed(CASES)), [*CASES, CASES[0]]):
            with self.subTest(ids=[case["id"] for case in cases]), self.assertRaises(ValueError):
                runner.select_cases(cases, arguments())

    def test_cli_limits_reject_unknown_variants_and_unbounded_resources(self):
        for flag, value in (("--backend", "xrt"), ("--format", "tf32"), ("--jobs", "3"),
                            ("--iterations", "3"), ("--timeout-seconds", "1801"),
                            ("--run-timeout-seconds", "0")):
            with self.subTest(flag=flag), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                arguments(flag, value)


class FailureGateTests(unittest.TestCase):
    def test_clean_partial_packet_retains_bound_bodies_and_never_accepts_a_phase(self):
        harness = RunnerHarness(self)
        report = harness.execute()
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertEqual(report, harness.saved)
        self.assertFalse(report["development"])
        self.assertFalse(report["full_matrix_requested"])
        self.assertFalse(report["acceptance_claimed"])
        self.assertFalse(report["phase_complete"])
        self.assertEqual((report["completed_case_executions"], report["completed_model_runs"],
                          report["completed_launches"]), (1, 2, 6))
        self.assertEqual(report["tensor_h2d_bytes"], 3840)
        self.assertEqual(report["tensor_d2h_bytes"], 1536)
        self.assertEqual(report["comparison_counts"], {"hidden_words": 256, "bridge_words": 128,
                         "output_block_words": 128, "assembled_output_words": 128})
        self.assertTrue(report["source_stable"])
        retained = {row["path"] for row in report["retained_sources"]}
        required = {item["path"] for item in runner.LOADED_HELPERS} | set(runner.SOURCE_FILES)
        required |= {"ci/project/compiler_records.py", "ci/project/baseline_packet_contract.py",
                     "sw/runtime/common/event.cpp", "sw/runtime/common/queue.cpp",
                     "sw/runtime/ai/runtime.cpp", "sw/kernel/ai/matmul.cpp"}
        self.assertTrue({"artifacts/source/" + path for path in required} <= retained)
        for row in report["retained_sources"]:
            self.assertEqual(harness.hash_files(harness.paths["output"], [row["path"]])[0], row)
        variant = report["variants"][0]
        self.assertEqual(variant["artifacts_before"], variant["artifacts_after"])
        self.assertEqual({item["path"] for item in variant["artifacts_before"]}, set(runner.artifacts("simx")))
        binding = json.loads((harness.paths["output"] / variant["binding"]["path"]).read_text())
        self.assertEqual(runner.qualification_id(binding), variant["qualification_id"])
        self.assertEqual(binding["source"], harness.snapshot["checkout"])
        self.assertEqual(binding["compiler_records"], harness.compiler_records)
        self.assertEqual(binding["artifacts"], variant["artifacts_before"])
        self.assertEqual(binding["fixture_sha256"], report["fixture_sha256"])
        self.assertEqual(binding["profile_sha256"], runner.PROFILE_SHA256)
        self.assertEqual(binding["dependencies"], report["dependencies_before"])
        for name, argv, cwd, env, budgets in harness.process_calls:
            with self.subTest(command=name):
                self.assertEqual({key: budgets[key] for key in runner.BUDGET}, runner.BUDGET)
                self.assertEqual(budgets["resource_paths"], (ROOT, harness.paths["work"], harness.paths["output"]))
                self.assertNotIn("HOME", env)
                self.assertLessEqual(budgets["timeout_seconds"], 1800)
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                         "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})
        records_call = harness.validate_records.call_args
        self.assertEqual(len(records_call.args), 3)
        self.assertEqual(len(set(records_call.args)), 3)
        self.assertEqual(records_call.kwargs["driver"], "simx")

    def test_full_host_harness_packet_counts_all_four_variants(self):
        harness = RunnerHarness(self, "--iterations", "2")
        report = harness.execute()
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertTrue(report["full_matrix_requested"])
        self.assertEqual((len(report["variants"]), report["completed_case_executions"],
                          report["completed_model_runs"], report["completed_launches"]), (4, 20, 40, 120))
        self.assertFalse(report["acceptance_claimed"])
        self.assertEqual(harness.verify.call_count, 20)

    def test_failed_exit_or_incomplete_cleanup_stops_before_parsing_success_text(self):
        for response in ({"outcome": "fail", "exit_code": 1}, {"exit_code": 1},
                         {"cleanup_complete": False}, {"outcome": "blocked"}):
            with self.subTest(response=response):
                harness = RunnerHarness(self)
                harness.fail_id = "simx-fp16-fp16-zero"
                harness.process_result = response
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("command failed", report["reason"])
                harness.verify.assert_not_called()
                self.assertEqual(report["variants"][0]["cases"], [])
                self.assertEqual(harness.process_calls[-1][0], harness.fail_id)
                self.assertEqual(report["state"], "finished")
                self.assertIn("source_after", report)
                harness.stack.close()

    def test_failed_configure_stops_before_compiler_records_or_model(self):
        harness = RunnerHarness(self)
        harness.fail_id = "simx-fp16-configure"
        harness.process_result = {"outcome": "fail", "exit_code": 2}
        report = harness.execute()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(harness.process_calls[-1][0], harness.fail_id)
        harness.validate_records.assert_not_called()
        harness.verify.assert_not_called()

    def test_bad_compiler_records_stop_before_model_launch(self):
        harness = RunnerHarness(self)
        harness.validate_records.side_effect = ValueError("synthetic compiler record rejection")
        report = harness.execute()
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("compiler record rejection", report["reason"])
        harness.verify.assert_not_called()
        self.assertFalse(any("--case" in call[1] for call in harness.process_calls))

    def test_stale_generated_makefile_and_reproduced_header_are_rejected(self):
        for kind in ("makefile", "header"):
            with self.subTest(kind=kind):
                harness = RunnerHarness(self)
                def change(name, argv, cwd):
                    if kind == "makefile" and name.endswith("-configure"):
                        (cwd / runner.APP / "Makefile").write_text("stale generated Makefile\n")
                    elif kind == "header" and name.endswith("-cpp-header-reproduce"):
                        (cwd / "p04-header-check/VX_config.h").write_text("stale header\n")
                harness.after_command = change
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("Makefile" if kind == "makefile" else "header did not reproduce", report["reason"])
                harness.verify.assert_not_called()
                harness.stack.close()

    def test_output_for_an_old_binding_or_bare_success_marker_cannot_pass(self):
        for mutate in (lambda text: "PASSED!\n", lambda text: text.replace(
                '"qualification_id":"', '"qualification_id":"stale-', 1)):
            with self.subTest(mutation=mutate):
                harness = RunnerHarness(self)
                harness.change_log = mutate
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["variants"][0]["cases"], [])
                self.assertEqual(harness.verify.call_count, 1)
                harness.stack.close()

    def test_artifact_mutation_during_launch_is_rejected_before_output_parse(self):
        harness = RunnerHarness(self)
        def change(name, argv, cwd):
            if "--case" in argv:
                (cwd / "kernel.vxbin").write_text("changed during the simulated launch\n")
        harness.after_command = change
        report = harness.execute()
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("artifacts changed during launch", report["reason"])
        harness.verify.assert_not_called()

    def test_finally_source_tool_and_dependency_drift_override_apparent_pass(self):
        for attribute, reason in (("source_drift_at", "source changed"),
                                  ("tool_drift_at", "tools changed"),
                                  ("dependency_drift_at", "dependencies changed")):
            with self.subTest(attribute=attribute):
                harness = RunnerHarness(self)
                setattr(harness, attribute, 5)
                report = harness.execute()
                self.assertEqual(report["completed_model_runs"], 2)
                self.assertEqual(report["outcome"], "fail")
                self.assertIn(reason, report["reason"])
                self.assertEqual(harness.saved["outcome"], "fail")
                harness.stack.close()

    def test_recorded_final_tool_snapshot_is_checked_before_passing(self):
        harness = RunnerHarness(self)
        # The first finalization check sees the original tools; the separately
        # recorded tools-after observation sees a replaced compiler.
        harness.tool_drift_at = 6
        report = harness.execute()
        self.assertEqual(report["completed_model_runs"], 2)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("tools changed", report["reason"])
        self.assertEqual(harness.saved["outcome"], "fail")

    def test_missing_memory_or_disk_reserve_blocks_before_any_command(self):
        for memory, disk in ((None, 15 * 1024**3), (4 * 1024**3 - 1, 15 * 1024**3),
                             (4 * 1024**3, 15 * 1024**3 - 1)):
            with self.subTest(memory=memory, disk=disk):
                harness = RunnerHarness(self)
                harness.resources["available_memory_bytes"] = memory
                harness.resources["free_disk_bytes"]["output"] = disk
                report = harness.execute()
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(harness.process_calls, [])
                harness.stack.close()

    def test_dirty_formal_checkout_blocks_and_development_never_claims_acceptance(self):
        for development in (False, True):
            with self.subTest(development=development):
                harness = RunnerHarness(self)
                harness.args.development = development
                harness.snapshot["checkout"].update(dirty=True, changed_paths=["host-test-only"],
                    blockers=["source contains tracked changes or nonignored untracked inputs"])
                report = harness.execute()
                self.assertEqual(report["outcome"], "pass" if development else "blocked", report["reason"])
                self.assertFalse(report["acceptance_claimed"])
                self.assertFalse(report["phase_complete"])
                if not development:
                    self.assertEqual(harness.process_calls, [])
                harness.stack.close()

    def test_changed_loaded_helper_or_stale_fixture_header_blocks_before_commands(self):
        for target in ("helper", "fixture_header"):
            with self.subTest(target=target):
                harness = RunnerHarness(self)
                if target == "helper":
                    changed = copy.deepcopy(runner.LOADED_HELPERS)
                    changed[0]["sha256"] = "0" * 64
                    harness.stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS", changed))
                else:
                    harness.stack.enter_context(mock.patch.object(runner, "render_header", return_value="stale\n"))
                report = harness.execute()
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(harness.process_calls, [])
                harness.stack.close()


class PathGateTests(unittest.TestCase):
    def test_nonfresh_overlapping_and_symlinked_roots_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="p04-path-host-", dir=ROOT.parent) as temporary:
            parent = Path(temporary)
            tools = parent / "tools"
            tools.mkdir()
            alias = parent / "tool-alias"
            alias.symlink_to(tools, target_is_directory=True)
            for work, output, tool_root in ((tools, parent / "packet", tools),
                                            (ROOT / "p04-never-created", parent / "packet", tools),
                                            (parent / "build", parent / "build/packet", tools),
                                            (parent / "build", parent / "packet", alias)):
                args = arguments()
                args.source_dir, args.tools_dir = ROOT, tool_root
                args.work_dir, args.output = work, output
                with self.subTest(work=work, output=output, tools=tool_root), self.assertRaises(ValueError):
                    runner.base.resolve_paths(args)


if __name__ == "__main__":
    unittest.main()
