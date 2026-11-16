# Licensed under the Apache License, Version 2.0.
"""File-backed resource refusals without vendor or GPU execution."""

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import xrt_baseline
from test_xrt_baseline import RunnerFixture, STAGES
from xrt_test_support import write_file


class XrtResourceTests(RunnerFixture):
    def output_bytes(self):
        return sum(path.stat().st_size for path in self.fixture.output.rglob("*")
                   if path.is_file())

    def replace_receipt_log(self, size):
        command = self.fixture.receipt["commands"][0]
        command["log"] = write_file(Path(command["log"]["path"]), b"L" * size)
        self.fixture.refresh()

    def assertReserveFailure(self, report, stages=()):
        self.assertEqual(report["outcome"], "fail", report)
        self.assertIn("selected reserve", report["reason"])
        self.assertEqual([call["id"] for call in self.calls], list(stages))
        self.assertNotAccepted(report)
        stored = self.assertFinished(report)
        self.assertEqual(stored["reason"], report["reason"])
        self.assertFalse((self.fixture.output / "report.json.tmp").exists())
        return stored

    def test_three_mib_receipt_log_cannot_consume_one_mib_headroom(self):
        self.replace_receipt_log(3 * xrt_baseline.MIB)
        args = xrt_baseline.argument_parser().parse_args(
            self.argv() + ["--min-free-gib", "7.5"])
        paths = xrt_baseline.resolve_paths(args)
        minimum = int(7.5 * xrt_baseline.GIB)

        def free_space(_):
            return SimpleNamespace(free=minimum + xrt_baseline.MIB - self.output_bytes())

        with mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            report = xrt_baseline.plan_run(args, paths)
            self.assertEqual(report["outcome"], "pass", report["blockers"])
            report = xrt_baseline.execute_run(args, report, paths)

        self.assertReserveFailure(report)
        self.assertFalse((self.fixture.output / "artifacts/build-logs/0.log").exists())
        self.assertLessEqual(self.output_bytes(), xrt_baseline.MIB)
        self.assertEqual(report["commands"], [])
        self.assertIsNone(report["integration"]["exit_code"])
        self.runner.assert_not_called()

    def test_cumulative_receipt_copies_recheck_remaining_headroom(self):
        self.replace_receipt_log(600 * 1024)
        second = copy.deepcopy(self.fixture.receipt["commands"][0])
        second["log"] = write_file(self.base / "second.log", b"M" * (600 * 1024))
        self.fixture.receipt["commands"].append(second)
        self.fixture.refresh()
        minimum = 15 * xrt_baseline.GIB

        def free_space(_):
            return SimpleNamespace(free=minimum + xrt_baseline.MIB - self.output_bytes())

        with mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            report = self.run_fixture()

        self.assertReserveFailure(report)
        logs = self.fixture.output / "artifacts/build-logs"
        self.assertEqual((logs / "0.log").stat().st_size, 600 * 1024)
        self.assertFalse((logs / "1.log").exists())
        self.assertLessEqual(self.output_bytes(), xrt_baseline.MIB)
        self.runner.assert_not_called()

    def test_final_configuration_copy_cannot_consume_selected_reserve(self):
        minimum = 15 * xrt_baseline.GIB
        bytes_after_smoke = None

        def after_stage(stage):
            nonlocal bytes_after_smoke
            if stage == "configure":
                write_file(self.fixture.build / "sw/VX_config.h", b"H" * (768 * 1024))
            if stage == "smoke":
                bytes_after_smoke = self.output_bytes()

        def free_space(_):
            if bytes_after_smoke is None:
                return SimpleNamespace(free=64 * xrt_baseline.GIB)
            return SimpleNamespace(free=minimum + 128 * 1024
                                   - (self.output_bytes() - bytes_after_smoke))

        self.after_stage = after_stage
        with mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            report = self.run_fixture()

        self.assertReserveFailure(report, STAGES)
        self.assertFalse((self.fixture.output / "artifacts/sw_VX_config.h").exists())
        self.assertLessEqual(self.output_bytes() - bytes_after_smoke, 128 * 1024)
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertEqual(report["integration"]["exit_code"], 0)

    def test_smoke_ini_write_checks_its_required_bytes(self):
        original = xrt_baseline._retain
        copied_logs = False
        minimum = 15 * xrt_baseline.GIB

        def retain(path, destination, *args, **kwargs):
            nonlocal copied_logs
            record = original(path, destination, *args, **kwargs)
            if destination.parent.name == "build-logs":
                copied_logs = True
            return record

        def free_space(_):
            free = minimum + len(xrt_baseline.SMOKE_INI.encode()) - 1
            return SimpleNamespace(free=free if copied_logs else 64 * xrt_baseline.GIB)

        with mock.patch.object(xrt_baseline, "_retain", side_effect=retain), \
                mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            report = self.run_fixture()

        stored = self.assertReserveFailure(report)
        self.assertEqual(stored["checkpoint_scope"], "failure_status_only")
        self.assertFalse((self.fixture.output / "artifacts/xrt.ini").exists())
        self.runner.assert_not_called()

    def test_already_breached_reserve_retains_compact_failure_without_launch(self):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        with mock.patch.object(xrt_baseline.shutil, "disk_usage", return_value=SimpleNamespace(
                free=report["budget"]["min_free_bytes"] - 1)):
            report = xrt_baseline.execute_run(args, report, paths)

        stored = self.assertReserveFailure(report)
        self.assertEqual(stored["checkpoint_scope"], "failure_status_only")
        self.assertLessEqual((self.fixture.output / "report.json").stat().st_size, 16 * 1024)
        self.assertEqual(stored["commands"], [])
        self.assertEqual(list((self.fixture.output / "artifacts").iterdir()), [])
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()

    def test_compact_checkpoint_preserves_original_failure_when_reserve_drops(self):
        exhausted = False

        def host_failure(*_):
            nonlocal exhausted
            exhausted = True
            raise OSError("synthetic host identity failure")

        def free_space(_):
            return SimpleNamespace(free=(15 * xrt_baseline.GIB - 1) if exhausted
                                   else 64 * xrt_baseline.GIB)

        self.host_observation.side_effect = host_failure
        with mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            report = self.run_fixture()

        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["reason"], "synthetic host identity failure")
        stored = self.assertFinished(report)
        self.assertEqual(stored["checkpoint_scope"], "failure_status_only")
        self.assertEqual(stored["reason"], report["reason"])
        self.assertLessEqual((self.fixture.output / "report.json").stat().st_size, 16 * 1024)
        self.runner.assert_not_called()

    def test_final_checkpoint_reserve_failure_cannot_escape_finalization(self):
        original = xrt_baseline._checkpoint
        exhausted = False

        def checkpoint(output, report, paths, data):
            nonlocal exhausted
            if report["state"] == "finished":
                exhausted = True
            return original(output, report, paths, data)

        def free_space(_):
            return SimpleNamespace(free=(15 * xrt_baseline.GIB - 1) if exhausted
                                   else 64 * xrt_baseline.GIB)

        with mock.patch.object(xrt_baseline, "_checkpoint", side_effect=checkpoint), \
                mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            report = self.run_fixture()

        stored = self.assertReserveFailure(report, STAGES)
        self.assertEqual(stored["checkpoint_scope"], "failure_status_only")
        self.assertEqual(stored["integration"]["outcome"], "fail")
        self.assertEqual(stored["integration"]["exit_code"], 0)
        self.assertLessEqual((self.fixture.output / "report.json").stat().st_size, 16 * 1024)

    def test_plan_checks_actual_parent_temp_filesystem(self):
        ambient = self.base / "parent-temp"
        ambient.mkdir()
        minimum = 15 * xrt_baseline.GIB

        def free_space(path):
            return SimpleNamespace(free=minimum - 1 if Path(path) == ambient
                                   else 64 * xrt_baseline.GIB)

        with mock.patch.object(tempfile, "tempdir", str(ambient)), \
                mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            _, _, report = self.plan("plan", output=False)

        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("free disk is below the selected reserve", report["blockers"])
        self.assertIn({"path": str(ambient), "bytes": minimum - 1},
                      report["resources"]["free_disk_bytes"])
        self.assertFalse(self.fixture.output.exists())
        self.runner.assert_not_called()
        self.build_observation.assert_not_called()

    def test_command_budgets_include_parent_temp_and_child_temp(self):
        ambient = self.base / "parent-temp"
        ambient.mkdir()
        with mock.patch.object(tempfile, "tempdir", str(ambient)):
            report = self.run_fixture()

        self.assertEqual(report["outcome"], "pass", report.get("reason"))
        for call in self.calls:
            self.assertIn(ambient, call["budget"]["resource_paths"])
            self.assertIn(self.fixture.output / "tmp", call["budget"]["resource_paths"])
            self.assertNotEqual(str(ambient), call["environment"]["TMPDIR"])

    def test_parent_temp_reserve_drop_after_plan_stops_before_probes(self):
        ambient = self.base / "parent-temp"
        ambient.mkdir()

        def free_space(path):
            return SimpleNamespace(free=15 * xrt_baseline.GIB - 1 if Path(path) == ambient
                                   else 64 * xrt_baseline.GIB)

        with mock.patch.object(tempfile, "tempdir", str(ambient)):
            args, paths, report = self.plan()
            self.assertEqual(report["outcome"], "pass", report["blockers"])
            with mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
                report = xrt_baseline.execute_run(args, report, paths)

        self.assertReserveFailure(report)
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()
        self.build_observation.assert_not_called()

    def test_parent_temp_is_rechecked_before_header_validation(self):
        ambient = self.base / "parent-temp"
        ambient.mkdir()
        exhausted = False

        def after_stage(stage):
            nonlocal exhausted
            exhausted = stage == "configure"

        def free_space(path):
            low = exhausted and Path(path) == ambient
            return SimpleNamespace(free=15 * xrt_baseline.GIB - 1 if low
                                   else 64 * xrt_baseline.GIB)

        self.after_stage = after_stage
        with mock.patch.object(tempfile, "tempdir", str(ambient)), \
                mock.patch.object(xrt_baseline.shutil, "disk_usage", side_effect=free_space):
            report = self.run_fixture()

        self.assertReserveFailure(report, ("configure",))
        self.build_observation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
