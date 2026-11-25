# SPDX-License-Identifier: Apache-2.0
"""Fresh hosted capacity admission before an inert native supervisor boundary."""

import json
from pathlib import Path
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import test_p06_qualified_warm_capacity as capacity_fixtures
import test_p06_qualified_warm_hosted as hosted_fixtures


GIB = 1024**3
PRE_NATIVE_RECEIPT = "hosted/pre-native-capacity.json"


class HostedNativeCapacityTests(unittest.TestCase):
    def setUp(self):
        self.real_gate = hosted.capacity_gate
        self.real_observe = hosted.capacity.observe_capacity
        self.case = hosted_fixtures.HostedCompositionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.memory = capacity_fixtures.Fixture().root_layout()
        self.memory.scalar(1, "memory.max", 8 * GIB)
        self.memory.scalar(1, "memory.current", GIB)
        self.free_disk = {self.case.source: 20 * GIB, self.case.attempt: 20 * GIB}
        self.after_acquisition = lambda: None
        self.gate_boundaries = []
        self.receipt_at_native = None
        self.gate = self.case.stack.enter_context(mock.patch.object(
            hosted, "capacity_gate", side_effect=self.capacity_gate))
        self.case.stack.enter_context(mock.patch.object(
            hosted.capacity, "observe_capacity",
            side_effect=lambda: self.real_observe(self.memory.read, clock=lambda: 0)))
        self.case.stack.enter_context(mock.patch.object(
            hosted.shutil, "disk_usage",
            side_effect=lambda path: mock.Mock(free=self.free_disk[Path(path)])))
        self.case.stack.enter_context(mock.patch.object(
            hosted, "run_bounded", side_effect=self.command))

    def capacity_gate(self, source, attempt):
        self.gate_boundaries.append([row["module"] for row in self.case.calls])
        return self.real_gate(source, attempt)

    def command(self, argv, *args, **kwargs):
        module = Path(argv[2]).stem if len(argv) > 2 and argv[1] == "-B" else "recipient-probe"
        if module == "p06_qualified_warm_run":
            path = self.case.attempt / PRE_NATIVE_RECEIPT
            self.receipt_at_native = json.loads(path.read_text()) if path.exists() else None
        result = self.case.command(argv, *args, **kwargs)
        if module == "p06_qualified_warm_inputs":
            self.after_acquisition()
        return result

    def receipts(self):
        reports = []
        for relative in ("hosted/capacity.json", PRE_NATIVE_RECEIPT):
            path = self.case.attempt / relative
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            report = json.loads(path.read_text())
            self.assertIs(report["effective_capacity_established"], False)
            self.assertEqual(report["observation"]["effective_capacity_status"], "unknown")
            self.assertEqual(report["observation"]["full_ancestry_status"], "unknown")
            self.assertIsNone(report["observation"]["effective_headroom_bytes"])
            reports.append(report)
        self.assertIs(reports[0]["gate_satisfied"], True)
        self.assertEqual(reports[0]["observation"]["visible_headroom_bytes"], 7 * GIB)
        return reports

    def assert_blocked_closeout(self, result, *, gate_calls=2):
        self.assertEqual(self.gate.call_count, gate_calls)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["orchestration_passed"], False)
        self.assertIs(result["qualified_warm_passed"], False)
        self.assertIs(result["writers_finished_observed"], True)
        self.assertIs(result["packaging_passed"], True)
        self.assertIs(result["encryption_passed"], True)
        self.assertNotIn("native-supervisor", [row["id"] for row in result["stages"]])
        self.assertNotIn("p06_qualified_warm_run", [row["module"] for row in self.case.calls])
        packed = next(row for row in self.case.calls if row["module"] == "p06_qualified_warm_pack")
        self.assertIn("partial", packed["argv"])
        self.assertIn("hosted=" + str(self.case.attempt / "hosted"), packed["argv"])
        for relative in ("hosted/attempt-before-closeout.json", "retention/hosted-closeout.json"):
            retained = json.loads((self.case.attempt / relative).read_text())
            self.assertEqual(retained["native_execution"], "not_run")
            self.assertIs(retained["writers_finished_observed"], True)
            self.assertIs(retained["orchestration_passed"], False)

    def test_parent_usage_growth_blocks_native_and_preserves_closeout(self):
        self.after_acquisition = lambda: self.memory.scalar(1, "memory.current", 5 * GIB)
        result = self.case.execute()
        self.assert_blocked_closeout(result)
        initial, fresh = self.receipts()
        self.assertEqual(initial["observation"]["host_available_bytes"], 8 * GIB)
        self.assertEqual(fresh["observation"]["host_available_bytes"], 8 * GIB)
        self.assertEqual(fresh["observation"]["visible_headroom_bytes"], 3 * GIB)
        self.assertIs(fresh["observation"]["observation_complete"], True)
        self.assertIs(fresh["observation"]["known_memory_shortfall"], True)
        self.assertIs(fresh["gate_satisfied"], False)

    def test_host_memory_drop_blocks_native_and_preserves_closeout(self):
        self.after_acquisition = lambda: self.memory.files.update({
            "/proc/meminfo": b"MemTotal: 16777216 kB\nMemAvailable: 3145728 kB\n"})
        result = self.case.execute()
        self.assert_blocked_closeout(result)
        _, fresh = self.receipts()
        self.assertEqual(fresh["observation"]["host_available_bytes"], 3 * GIB)
        self.assertEqual(fresh["observation"]["visible_headroom_bytes"], 7 * GIB)
        self.assertIs(fresh["observation"]["known_memory_shortfall"], True)
        self.assertIs(fresh["gate_satisfied"], False)

    def test_incomplete_fresh_observation_blocks_native_and_preserves_closeout(self):
        self.after_acquisition = lambda: self.memory.files.pop(
            self.memory.directories[1] + "/memory.current")
        result = self.case.execute()
        self.assert_blocked_closeout(result)
        _, fresh = self.receipts()
        self.assertIs(fresh["observation"]["observation_complete"], False)
        self.assertIs(fresh["observation"]["known_memory_shortfall"], False)
        self.assertIs(fresh["gate_satisfied"], False)

    def check_disk_drop(self, path, label):
        self.after_acquisition = lambda: self.free_disk.update({path: 15 * GIB - 1})
        result = self.case.execute()
        self.assert_blocked_closeout(result)
        _, fresh = self.receipts()
        self.assertIs(fresh["observation"]["observation_complete"], True)
        self.assertIs(fresh["observation"]["known_memory_shortfall"], False)
        self.assertEqual(fresh["free_disk_bytes"][label], 15 * GIB - 1)
        self.assertIs(fresh["gate_satisfied"], False)

    def test_source_disk_drop_blocks_native_and_preserves_closeout(self):
        self.check_disk_drop(self.case.source, "source")

    def test_attempt_disk_drop_blocks_native_and_preserves_closeout(self):
        self.check_disk_drop(self.case.attempt, "attempt")

    def test_fresh_threshold_equal_capacity_is_retained_before_native(self):
        def change():
            self.memory.scalar(1, "memory.current", 4 * GIB)
            self.memory.files["/proc/meminfo"] = b"MemAvailable: 4194304 kB\n"
            self.free_disk.update({self.case.source: 15 * GIB, self.case.attempt: 15 * GIB})

        self.after_acquisition = change
        result = self.case.execute()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["native_execution"], "run")
        self.assertEqual(self.gate.call_count, 2)
        self.assertEqual(self.gate_boundaries, [
            ["recipient-probe"],
            ["recipient-probe", "p06_qualified_warm_control", "p06_qualified_warm_inputs"],
        ])
        _, fresh = self.receipts()
        self.assertEqual(fresh, self.receipt_at_native)
        self.assertIs(fresh["gate_satisfied"], True)
        self.assertEqual(fresh["observation"]["host_available_bytes"], 4 * GIB)
        self.assertEqual(fresh["observation"]["visible_headroom_bytes"], 4 * GIB)
        self.assertEqual(fresh["free_disk_bytes"], {"source": 15 * GIB, "attempt": 15 * GIB})
        native = [row for row in self.case.calls if row["module"] == "p06_qualified_warm_run"]
        self.assertEqual(len(native), 1)
        self.assertEqual(native[0]["budget"]["min_free_bytes"], 15 * GIB)
        self.assertEqual(native[0]["budget"]["max_rss_bytes"], 4 * GIB)
        self.assertEqual(native[0]["budget"]["timeout_seconds"], 5520)

    def check_receipt_write_error(self, *, partial):
        original_write = hosted._write
        target = self.case.attempt / PRE_NATIVE_RECEIPT

        def write(path, value):
            if path == target:
                if partial:
                    with path.open("xb") as stream:
                        stream.write(b"{")
                raise OSError("injected private receipt write failure")
            return original_write(path, value)

        with mock.patch.object(hosted, "_write", side_effect=write):
            result = self.case.execute()
        self.assert_blocked_closeout(result)
        self.assertTrue((self.case.attempt / "hosted/capacity.json").is_file())
        self.assertEqual(target.exists(), partial)
        if partial:
            self.assertEqual(target.read_bytes(), b"{")
        self.assertIn({"stage": "execution", "error_type": "OSError"}, result["failures"])

    def test_pre_native_receipt_creation_error_prevents_native(self):
        self.check_receipt_write_error(partial=False)

    def test_pre_native_receipt_partial_write_error_prevents_native(self):
        self.check_receipt_write_error(partial=True)

    def test_failed_acquisition_receipt_precedes_capacity_refresh(self):
        def change():
            path = self.case.attempt / "acquisition/input-acquisition.json"
            report = json.loads(path.read_text())
            report["outcome"] = "fail"
            self.case.write(path, report)

        self.after_acquisition = change
        result = self.case.execute()
        self.assert_blocked_closeout(result, gate_calls=1)
        self.assertFalse((self.case.attempt / PRE_NATIVE_RECEIPT).exists())


if __name__ == "__main__":
    unittest.main()
