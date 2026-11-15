# SPDX-License-Identifier: Apache-2.0
"""Stopped runner boundaries with synthetic observations; never GPU evidence."""

from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import baseline
from baseline_packet import verify_packet
from baseline_packet_fixture import (
    CASE_IDS, SYNTHETIC, make_packet, refresh_log, save_report,
)
from baseline_packet_io import PacketError


HERE = Path(__file__).resolve().parent
LAUNCH_STAGES = (
    "dependencies_before_execution", "tooling_before_execution",
    "host_before_execution", "tooling_snapshots",
)
CASE_STAGES = (
    "dependencies_before", "tooling_before", "source_before", "build_before",
    "dependencies_at_launch", "dependencies_after", "tooling_after",
    "source_after", "build_after",
)
FINAL_STAGES = ("tools_after", "host_after", "dependencies_after", "tooling_after")


class InterruptedPacketFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.run_number = 0

    def run_packet(self, interrupt_at=None, *, blocked_command=None):
        """Run real orchestration with inert inventories, logs and capture bytes."""
        self.run_number += 1
        run_root = self.base / ("run-" + str(self.run_number))
        fixture_root = run_root / "synthetic-inputs"
        template = make_packet(fixture_root)
        case_map = {case["id"]: case for case in template["cases"]}
        command_map = {command["id"]: command for command in template["commands"]}
        paths = {name: run_root / name for name in ("source", "build", "tools", "output")}
        paths.update(matrix=HERE / "p01_baseline.json",
                     bundle=HERE / "p01_toolchain.lock.json")
        for name in ("source", "tools"):
            paths[name].mkdir()
        args = baseline.argument_parser().parse_args([
            "run", "--source", str(paths["source"]), "--build-dir", str(paths["build"]),
            "--tool-dir", str(paths["tools"]), "--output", str(paths["output"]),
            "--timeout-seconds", "60",
        ])
        report = None
        interrupted = []

        def boundary(name):
            if name == interrupt_at:
                interrupted.append(name)
                raise KeyboardInterrupt

        def active_case():
            identifier = report.get("active_case") if report is not None else None
            if identifier is None:
                return None
            return next(case for case in report["cases"] if case["id"] == identifier)

        def observe(kind, *unused):
            case = active_case()
            if report is not None:
                if case is not None and kind in ("source", "build"):
                    stage = kind + ("_after" if kind + "_before" in case else "_before")
                    boundary((case["id"], stage))
                elif kind == "build":
                    boundary(("run", "build_configured"))
                elif kind == "host":
                    stage = "host_after" if "host_before_execution" in report else "host_before_execution"
                    boundary(("run", stage))
                elif kind == "tools":
                    boundary(("run", "tools_after"))
            key = "build_configured" if kind == "build" else kind + "_before"
            return deepcopy(template[key])

        original_dependencies = baseline._verify_dependencies
        original_tooling = baseline._verify_tooling
        original_checkpoint = baseline._checkpoint
        original_reference = baseline.reference_passed
        original_command_for = baseline.command_for

        def verify_dependencies(source, expected, destination, key):
            boundary((destination.get("id", "run"), key))
            original_dependencies(source, expected, destination, key)

        def verify_tooling(expected, destination, key):
            boundary((destination.get("id", "run"), key))
            original_tooling(expected, destination, key)

        def retain(identities):
            for identity in identities:
                relative = identity["path"]
                destination = paths["output"] / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((fixture_root / relative).read_bytes())
            return deepcopy(identities)

        def snapshot_tooling(output, expected):
            boundary(("run", "tooling_snapshots"))
            return retain(template["tooling_snapshots"])

        def command_for(case):
            boundary((case["id"], "workload_launch"))
            return original_command_for(case)

        def command(argv, cwd, environment, logfile, **budget):
            identifier = logfile.stem
            result = deepcopy(command_map[identifier])
            self.assertEqual(cwd, paths["build"])
            retain([{"path": result["log"]}])
            if identifier == blocked_command:
                result.update(outcome="blocked", exit_code=None, reason="launch_failed",
                              peak_rss_bytes=0)
                refresh_log(paths["output"], result, SYNTHETIC + "\nsynthetic launch blocked\n")
            for field in ("id", "argv", "cwd", "environment", "log"):
                del result[field]
            return result

        def checkpoint(output, current, current_paths):
            original_checkpoint(output, current, current_paths)
            if (current["state"] == "running" and current["commands"]
                    and "active_command" not in current):
                boundary(("command", current["commands"][-1]["id"]))

        def reference(logfile):
            boundary((active_case()["id"], "reference_marker_verified"))
            return original_reference(logfile)

        def capture(current_paths, output, case):
            boundary((case["id"], "capture"))
            result = case_map[case["id"]]
            retain(result["configuration_artifacts"])
            return {key: deepcopy(result[key]) for key in (
                "configuration_artifacts", "binary_identities", "native_flags_verified")}

        replacements = {
            "collect_source": lambda *args: observe("source", *args),
            "collect_build": lambda *args: observe("build", *args),
            "collect_host": lambda *args: observe("host", *args),
            "collect_tools": lambda *args: observe("tools", *args),
            "collect_tooling": lambda: deepcopy(template["tooling_before"]),
            "_dependency_identity": lambda *args: deepcopy(template["dependencies_planned"]),
            "_verify_dependencies": verify_dependencies,
            "_verify_tooling": verify_tooling,
            "_snapshot_tooling": snapshot_tooling,
            "command_for": command_for,
            "run_bounded": command,
            "_checkpoint": checkpoint,
            "reference_passed": reference,
            "capture_case": capture,
            "available_memory_bytes": lambda: 8 * 1024**3,
        }
        with ExitStack() as stack:
            for name, replacement in replacements.items():
                stack.enter_context(mock.patch.object(baseline, name, side_effect=replacement))
            stack.enter_context(mock.patch.object(
                baseline.shutil, "disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)))
            stack.enter_context(mock.patch.object(
                baseline, "_now", side_effect=[template["started_at"], template["finished_at"]]))
            report = baseline.plan_run(args, paths)
            self.assertEqual(report["blockers"], [])
            baseline.execute_run(args, report, paths)
        self.assertEqual(interrupted, [] if interrupt_at is None else [interrupt_at])
        saved = json.loads((paths["output"] / "report.json").read_bytes())
        self.assertEqual(saved["state"], "finished")
        self.assertNotIn("active_case", saved)
        self.assertNotIn("active_command", saved)
        if interrupt_at is not None:
            self.assertEqual(saved["outcome"], "fail")
            self.assertEqual(saved["reason"], "execution interrupted")
            self.assertIs(saved["coverage"]["full_native_matrix_passed"], False)
        return paths["output"], saved

    def assertInterruptedSummary(self, root, *, passed=(), failed=(), interrupted=(), not_run=()):
        for require_native in (False, True):
            with self.subTest(require_native=require_native):
                summary = verify_packet(root, require_native_pass=require_native)
                self.assertEqual(summary["integrity"], "verified")
                self.assertEqual(summary["run_outcome"], "fail")
                self.assertEqual(summary["outcome"], "fail" if require_native else "pass")
                self.assertIs(summary["native_matrix_passed"], False)
                self.assertIs(summary["requirement_satisfied"], not require_native)
                self.assertIs(summary["manifest"]["native_matrix_passed"], False)
                self.assertIs(summary["phase_complete"], False)
                self.assertEqual(summary["passed_ids"], list(passed))
                self.assertEqual(summary["failed_ids"], list(failed))
                self.assertEqual(summary["not_run_ids"], list(not_run))
                self.assertEqual(summary.get("interrupted_ids", []), list(interrupted))

    def assertInvalid(self, root, report, message="."):
        save_report(root, report)
        with self.assertRaisesRegex(PacketError, message):
            verify_packet(root)


class PacketInterruptionAcceptanceTests(InterruptedPacketFixture):
    def test_partial_launch_observations_are_valid_completed_interruptions(self):
        for index, stage in enumerate(LAUNCH_STAGES):
            with self.subTest(boundary=stage):
                root, report = self.run_packet(("run", stage))
                self.assertEqual([key for key in LAUNCH_STAGES if key in report],
                                 list(LAUNCH_STAGES[:index]))
                self.assertEqual(report["commands"], [])
                self.assertInterruptedSummary(root, not_run=CASE_IDS)

    def test_completed_prerequisite_prefixes_are_valid_interruptions(self):
        commands = ("configure", "kernel-library", "runtime-stub")
        for index, command in enumerate(commands):
            with self.subTest(boundary=command):
                root, report = self.run_packet(("command", command))
                self.assertEqual([entry["id"] for entry in report["commands"]],
                                 list(commands[:index + 1]))
                self.assertTrue(all(entry["outcome"] == "pass" for entry in report["commands"]))
                self.assertInterruptedSummary(root, not_run=CASE_IDS)

    def test_partial_case_observations_do_not_invalidate_a_finished_interruption(self):
        boundaries = (("tooling_before", 1), ("source_before", 2),
                      ("build_before", 3), ("dependencies_at_launch", 4),
                      ("workload_launch", 5))
        for stage, prefix_length in boundaries:
            with self.subTest(boundary=stage):
                root, report = self.run_packet((CASE_IDS[1], stage))
                case = report["cases"][1]
                self.assertEqual(case["outcome"], "not_run")
                self.assertEqual([key for key in CASE_STAGES if key in case],
                                 list(CASE_STAGES[:prefix_length]))
                self.assertInterruptedSummary(root, passed=CASE_IDS[:1],
                                              interrupted=CASE_IDS[1:2], not_run=CASE_IDS[2:])

    def test_workload_pass_is_provisional_until_reference_and_capture_complete(self):
        boundaries = (("dependencies_after", 5), ("tooling_after", 6),
                      ("source_after", 7), ("build_after", 8),
                      ("reference_marker_verified", 9), ("capture", 9))
        for stage, prefix_length in boundaries:
            with self.subTest(boundary=stage):
                root, report = self.run_packet((CASE_IDS[1], stage))
                case = report["cases"][1]
                self.assertEqual(case["outcome"], "pass")
                self.assertIsNone(case["reason"])
                self.assertEqual(report["commands"][-1]["id"], CASE_IDS[1])
                self.assertEqual(report["commands"][-1]["outcome"], "pass")
                self.assertEqual([key for key in CASE_STAGES if key in case],
                                 list(CASE_STAGES[:prefix_length]))
                self.assertNotIn("configuration_artifacts", case)
                if stage == "capture":
                    self.assertIs(case["reference_marker_verified"], True)
                else:
                    self.assertNotIn("reference_marker_verified", case)
                self.assertInterruptedSummary(root, passed=CASE_IDS[:1],
                                              interrupted=CASE_IDS[1:2], not_run=CASE_IDS[2:])

    def test_final_observation_prefix_keeps_completed_cases_without_native_success(self):
        for index, stage in enumerate(FINAL_STAGES):
            with self.subTest(boundary=stage):
                root, report = self.run_packet(("run", stage))
                self.assertTrue(all(case["outcome"] == "pass" for case in report["cases"]))
                self.assertEqual([key for key in FINAL_STAGES if key in report],
                                 list(FINAL_STAGES[:index]))
                self.assertInterruptedSummary(root, passed=CASE_IDS)

    def test_interruption_after_blocked_workload_remains_a_valid_failed_report(self):
        root, report = self.run_packet((CASE_IDS[1], "dependencies_after"),
                                      blocked_command=CASE_IDS[1])
        self.assertEqual(report["cases"][1]["outcome"], "blocked")
        self.assertEqual(report["commands"][-1]["outcome"], "blocked")
        self.assertInterruptedSummary(root, passed=CASE_IDS[:1], failed=CASE_IDS[1:2],
                                      not_run=CASE_IDS[2:])


class PacketInterruptionRejectionTests(InterruptedPacketFixture):
    def test_top_level_blocked_requires_the_owning_case_to_be_blocked(self):
        for command in (CASE_IDS[1] + "-configure", CASE_IDS[1]):
            with self.subTest(command=command):
                root, report = self.run_packet(blocked_command=command)
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(report["commands"][-1]["outcome"], "blocked")
                self.assertEqual(report["cases"][1]["outcome"], "blocked")
                self.assertEqual(verify_packet(root)["integrity"], "verified")
                report["cases"][1].update(outcome="fail", reason="nonzero_exit")
                self.assertInvalid(root, report)

    def test_interruption_reason_does_not_allow_nonprefix_commands(self):
        for mutation in ("missing_case_configure", "continued_after_failure",
                         "continued_after_blocked"):
            with self.subTest(mutation=mutation):
                root, report = self.run_packet((CASE_IDS[1], "capture"))
                if mutation == "missing_case_configure":
                    del report["commands"][-2]
                    message = "differs from its frozen invocation"
                else:
                    command = report["commands"][1]
                    if mutation == "continued_after_failure":
                        command.update(outcome="fail", exit_code=2, reason="nonzero_exit")
                    else:
                        command.update(outcome="blocked", exit_code=None, reason="launch_failed")
                    refresh_log(root, command, SYNTHETIC + "\nsynthetic prerequisite stopped\n")
                    message = "commands continued after a failed or blocked command"
                self.assertInvalid(root, report, message)

    def test_interruption_reason_does_not_allow_incomplete_or_active_commands(self):
        for mutation in ("incomplete_command", "active_command", "active_case"):
            with self.subTest(mutation=mutation):
                root, report = self.run_packet((CASE_IDS[1], "capture"))
                if mutation == "incomplete_command":
                    report["commands"][-1]["outcome"] = "not_run"
                    message = "command .* is incomplete"
                else:
                    report[mutation] = CASE_IDS[1]
                    message = "report has missing or unknown fields"
                self.assertInvalid(root, report, message)

    def test_interruption_reason_does_not_allow_gapped_case_observations(self):
        root, report = self.run_packet((CASE_IDS[1], "capture"))
        del report["cases"][1]["dependencies_after"]
        self.assertInvalid(root, report, "case provenance observations are out of sequence")

    def test_provisional_pass_requires_the_exact_interruption_reason(self):
        for reason in ("unrelated execution failure", "execution interrupted later"):
            with self.subTest(reason=reason):
                root, report = self.run_packet((CASE_IDS[1], "capture"))
                report["reason"] = reason
                self.assertInvalid(root, report)

    def test_interruption_cannot_excuse_continuing_after_an_incomplete_case(self):
        root, report = self.run_packet((CASE_IDS[1], "capture"))
        for key in ("reference_marker_verified", "configuration_artifacts",
                    "binary_identities", "native_flags_verified"):
            del report["cases"][0][key]
        self.assertInvalid(root, report)


if __name__ == "__main__":
    unittest.main()
