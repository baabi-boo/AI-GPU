# SPDX-License-Identifier: Apache-2.0
"""Compiler-record failures stop inert runner fixtures before vendor launch."""

import unittest
from unittest import mock

import xrt_baseline
from test_xrt_baseline import RunnerFixture, STAGES


REQUIRED_FLAG = "-DVX_CFG_NUM_CLUSTERS=1"


class CompilerExecutionBoundaryTests(RunnerFixture):
    def change_record(self, role, transform):
        relative = ("sw/runtime/xrt_config.stamp" if role == "runtime"
                    else "tests/regression/demo/config.stamp")
        path = self.fixture.build / relative
        records = path.read_text(encoding="utf-8").split("\n")
        index = {"runtime": 0, "kernel": 0, "host": 1, "linker": 2}[role]
        records[index] = transform(records[index])
        path.write_text("\n".join(records), encoding="utf-8")

    def reject_before_smoke(self, mutation, expected_blocker):
        def after_vendor_build(stage):
            if stage == "vendor-runtime":
                mutation()

        self.after_stage = after_vendor_build
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail", report)
        self.assertIn("effective configuration failed validation", report["reason"])
        self.assertEqual([call["id"] for call in self.calls], list(STAGES[:-1]))
        self.assertEqual([entry["id"] for entry in report["commands"]], list(STAGES[:-1]))
        self.assertEqual(report["effective_before"]["outcome"], "blocked")
        self.assertIs(report["effective_before"]["native_flags_verified"], False)
        self.assertTrue(any(expected_blocker in blocker
                            for blocker in report["effective_before"]["blockers"]), report)
        self.assertEqual(report["integration"]["outcome"], "not_run")
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertFalse((self.fixture.output / "logs/smoke.log").exists())
        self.assertEqual(self.runtime_observation.call_count, 0)
        stored = self.assertFinished(report)
        self.assertEqual(stored["effective_before"], report["effective_before"])
        self.assertEqual(stored["integration"]["outcome"], "not_run")

    def test_complete_records_reach_the_inert_smoke_without_accepting_a_gate(self):
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "pass", report.get("reason"))
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        self.assertIs(report["effective_before"]["native_flags_verified"], True)
        self.assertEqual(report["effective_after"], report["effective_before"])
        self.assertFinished(report)

    def test_consumed_runtime_macro_blocks_launch(self):
        self.reject_before_smoke(
            lambda: self.change_record("runtime", lambda line: line.replace(
                REQUIRED_FLAG, "-I " + REQUIRED_FLAG)),
            "XRT runtime stamp does not establish the frozen native RV64 configuration")

    def test_kernel_configuration_cannot_supply_a_missing_host_macro(self):
        self.reject_before_smoke(
            lambda: self.change_record("host", lambda line: line.replace(REQUIRED_FLAG, "")),
            "demo host stamp does not establish the frozen native RV64 configuration")

    def test_wrong_kernel_isa_blocks_launch_despite_rv64_definitions(self):
        self.reject_before_smoke(
            lambda: self.change_record("kernel", lambda line: line.replace(
                "-march=rv64imafd", "-march=rv32imaf")), "kernel ISA/ABI")

    def test_missing_kernel_abi_blocks_launch(self):
        self.reject_before_smoke(
            lambda: self.change_record("kernel", lambda line: line.replace("-mabi=lp64d", "")),
            "kernel ISA/ABI")

    def test_glob_operand_blocks_launch(self):
        self.reject_before_smoke(
            lambda: self.change_record("host", lambda line: line.replace(
                REQUIRED_FLAG, "-I* " + REQUIRED_FLAG)), "shell expansion")

    def test_non_lf_separators_cannot_supply_a_build_record(self):
        def merge_records():
            path = self.fixture.build / "tests/regression/demo/config.stamp"
            path.write_text("\v".join(path.read_text(encoding="utf-8").splitlines()) + "\n",
                            encoding="utf-8")

        self.reject_before_smoke(merge_records, "control characters or record separators")

    def test_different_linker_binding_blocks_launch(self):
        self.reject_before_smoke(
            lambda: self.change_record("linker", lambda _line: "-L/other/runtime -lvortex"),
            "frozen runtime binding")

    def test_post_smoke_invalid_record_cannot_become_a_successful_packet(self):
        original_retain = xrt_baseline._retain
        last_snapshot = self.fixture.build / xrt_baseline.RETAINED_CONFIGS[-1]
        mutations = []

        def retain_then_mutate(path, destination, *args, **kwargs):
            retained = original_retain(path, destination, *args, **kwargs)
            if path == last_snapshot:
                self.change_record("runtime", lambda line: line.replace(
                    REQUIRED_FLAG, "-I " + REQUIRED_FLAG))
                mutations.append(path)
            return retained

        with mock.patch.object(xrt_baseline, "_retain", side_effect=retain_then_mutate):
            report = self.run_fixture()

        self.assertEqual(mutations, [last_snapshot])
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        self.assertEqual(report["effective_before"]["outcome"], "pass")
        self.assertEqual(report["effective_after"]["outcome"], "blocked")
        self.assertIs(report["effective_after"]["native_flags_verified"], False)
        self.assertTrue(any("frozen native RV64 configuration" in blocker
                            for blocker in report["effective_after"]["blockers"]))
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertEqual(report["integration"]["exit_code"], 0)
        self.assertIs(report["reference_markers_verified"], True)
        stored = self.assertFinished(report)
        self.assertEqual(stored["effective_after"], report["effective_after"])


if __name__ == "__main__":
    unittest.main()
