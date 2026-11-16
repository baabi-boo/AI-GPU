# Licensed under the Apache License, Version 2.0.
"""Checkpoint and retention drift tests using inert file-backed runner inputs."""

import copy
from pathlib import Path
import unittest
from unittest import mock

import xrt_baseline
from test_xrt_baseline import RunnerFixture, STAGES
from xrt_test_support import identity, write_file, write_json


class DriftCheckpointFixture(RunnerFixture):
    def assertFailedBeforeLaunch(self, report):
        self.assertEqual(report["outcome"], "fail", report.get("reason"))
        self.assertEqual(report["commands"], [])
        self.assertEqual(self.calls, [])
        self.runner.assert_not_called()
        self.assertEqual(report["integration"]["outcome"], "not_run")
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertNotAccepted(report)
        stored = self.assertFinished(report)
        self.assertEqual(stored["commands"], [])
        self.assertIsNone(stored["integration"]["exit_code"])
        self.assertEqual(stored["integration"]["outcome"], "not_run")
        self.assertFalse((self.fixture.output / "report.json.tmp").exists())
        return stored

    def assertManifestFailure(self, mutate):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        mutate()
        result = xrt_baseline.execute_run(args, report, paths)
        stored = self.assertFailedBeforeLaunch(result)
        self.assertIn("manifest became invalid after planning", result["reason"])
        self.assertIn("manifest became invalid after planning", stored["reason"])
        self.host_observation.assert_not_called()
        self.assertEqual(list(self.fixture.build.iterdir()), [])


class ManifestDriftTests(DriftCheckpointFixture):
    def test_corrupt_manifest_after_successful_plan_retains_failure_checkpoint(self):
        self.assertManifestFailure(lambda: self.fixture.manifest_path.write_bytes(b"{broken-json"))

    def test_removed_manifest_after_successful_plan_retains_failure_checkpoint(self):
        self.assertManifestFailure(self.fixture.manifest_path.unlink)

    def test_symlinked_manifest_after_successful_plan_retains_failure_checkpoint(self):
        def replace_with_symlink():
            target = self.base / "same-manifest.json"
            target.write_bytes(self.fixture.manifest_path.read_bytes())
            self.fixture.manifest_path.unlink()
            self.fixture.manifest_path.symlink_to(target)

        self.assertManifestFailure(replace_with_symlink)

    def test_changed_manifest_output_overlap_retains_failure_checkpoint(self):
        def introduce_overlap():
            changed = copy.deepcopy(self.fixture.manifest)
            changed["qualification_review"]["path"] = str(self.fixture.output / "review.txt")
            write_json(self.fixture.manifest_path, changed)

        self.assertManifestFailure(introduce_overlap)


class RetentionDriftTests(DriftCheckpointFixture):
    def test_receipt_logs_and_emconfig_retain_original_bytes_and_hashes(self):
        fixture = self.fixture
        emconfig = Path(fixture.manifest["artifacts"]["emconfig"]["path"])
        fixture.manifest["artifacts"]["emconfig"] = write_file(
            emconfig, b'{ "synthetic_fixture" : true, "preserve_spacing" : 1 }\r\n')
        first = fixture.receipt["commands"][0]
        first["log"] = write_file(Path(first["log"]["path"]), b"First fixture log\r\n\xff\x00\n")
        second = copy.deepcopy(first)
        second["argv"] = ["second-fixture-command-never-executed"]
        second["log"] = write_file(fixture.base / "records/second.log", b"Second fixture log\n\x80\n")
        fixture.receipt["commands"].append(second)
        fixture.refresh(bind_receipt=True)
        originals = {
            "emconfig.json": fixture.manifest["artifacts"]["emconfig"],
            "build_receipt": fixture.manifest["build_receipt"],
            "build-logs/0.log": first["log"],
            "build-logs/1.log": second["log"],
        }
        expected_bytes = {name: Path(record["path"]).read_bytes()
                          for name, record in originals.items()}

        report = self.run_fixture()

        self.assertEqual(report["outcome"], "pass", report.get("reason"))
        retained = {Path(item["path"]): item for item in report["retained"]}
        stored = self.assertFinished(report)
        stored_retained = {item["path"]: item for item in stored["retained"]}
        for name, original in originals.items():
            with self.subTest(artifact=name):
                path = fixture.output / "artifacts" / name
                self.assertIn(path, retained)
                self.assertEqual(path.read_bytes(), expected_bytes[name])
                self.assertEqual(identity(path), retained[path])
                record = stored_retained["$OUTPUT/artifacts/" + name]
                for key in ("sha256", "size_bytes"):
                    self.assertEqual(retained[path][key], original[key])
                    self.assertEqual(record[key], original[key])
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        self.assertNotAccepted(report)

    def test_receipt_log_mutation_during_retention_stops_before_launch(self):
        original_retain = xrt_baseline._retain
        log = Path(self.fixture.receipt["commands"][0]["log"]["path"])
        destination = self.fixture.output / "artifacts/build-logs/0.log"

        def mutate_then_retain(path, target, *args, **kwargs):
            if target == destination:
                log.write_bytes(b"Receipt log changed after the inventory check.\n")
            return original_retain(path, target, *args, **kwargs)

        with mock.patch.object(xrt_baseline, "_retain", side_effect=mutate_then_retain):
            report = self.run_fixture()

        self.assertFailedBeforeLaunch(report)
        self.assertIn("retained input differs from its frozen identity", report["reason"])
        self.assertFalse(destination.exists())
        self.assertTrue((self.fixture.output / "artifacts/build_receipt").is_file())
        self.assertTrue((self.fixture.output / "artifacts/emconfig.json").is_file())
        for retained in report["retained"]:
            self.assertEqual(identity(retained["path"]), retained)

    def test_emconfig_mutation_after_its_copy_is_detected_before_launch(self):
        original_retain = xrt_baseline._retain
        emconfig = Path(self.fixture.manifest["artifacts"]["emconfig"]["path"])
        original_bytes = emconfig.read_bytes()
        destination = self.fixture.output / "artifacts/emconfig.json"

        def retain_then_mutate(path, target, *args, **kwargs):
            retained = original_retain(path, target, *args, **kwargs)
            if target == destination:
                emconfig.write_bytes(b'{"changed_after_copy": true}\n')
            return retained

        with mock.patch.object(xrt_baseline, "_retain", side_effect=retain_then_mutate):
            report = self.run_fixture()

        self.assertFailedBeforeLaunch(report)
        self.assertIn("changed after planning", report["reason"])
        self.assertEqual(destination.read_bytes(), original_bytes)
        record = next(item for item in report["retained"] if item["path"] == str(destination))
        self.assertEqual(identity(destination), record)

    def assertFinalRetentionDrift(self, mutate):
        original_retain = xrt_baseline._retain
        destination = self.fixture.output / "artifacts/hw_VX_types.vh"
        mutations = []

        def retain_then_mutate(path, target, *args, **kwargs):
            retained = original_retain(path, target, *args, **kwargs)
            if target == destination:
                mutate()
                mutations.append(target)
            return retained

        with mock.patch.object(xrt_baseline, "_retain", side_effect=retain_then_mutate):
            report = self.run_fixture()

        self.assertEqual(mutations, [destination])
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        self.assertEqual(report["outcome"], "fail", "input changed during final evidence retention")
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertEqual(report["integration"]["exit_code"], 0)
        self.assertIs(report["reference_markers_verified"], True)
        self.assertNotAccepted(report)
        self.assertFinished(report)

    def test_manifest_mutation_during_final_retention_cannot_pass(self):
        def mutate():
            with self.fixture.manifest_path.open("ab") as stream:
                stream.write(b"\n")

        self.assertFinalRetentionDrift(mutate)

    def test_effective_stamp_mutation_during_final_retention_cannot_pass(self):
        def mutate():
            with (self.fixture.build / "sw/runtime/xrt_config.stamp").open("ab") as stream:
                stream.write(b" -DXRTSIM\n")

        self.assertFinalRetentionDrift(mutate)

    def test_binary_mutation_during_final_retention_cannot_pass(self):
        self.assertFinalRetentionDrift(lambda: (
            self.fixture.build / "sw/runtime/libvortex-xrt.so").write_bytes(b"CHANGED AFTER SMOKE"))

    def test_completed_command_log_mutation_during_final_retention_cannot_pass(self):
        self.assertFinalRetentionDrift(lambda: (
            self.fixture.output / "logs/configure.log").write_bytes(b"CHANGED COMPLETED LOG\n"))

    def test_retained_helper_mutation_during_final_retention_cannot_pass(self):
        self.assertFinalRetentionDrift(lambda: (
            self.fixture.output / "artifacts/tooling/xrt_contract.py").write_bytes(b"CHANGED HELPER COPY\n"))

    def test_stamp_changed_for_copy_then_restored_cannot_enter_retained_evidence(self):
        original_retain = xrt_baseline._retain
        destination = self.fixture.output / "artifacts/sw_runtime_xrt_config.stamp"
        mutations = []

        def transiently_mutate(path, target, *args, **kwargs):
            if target != destination:
                return original_retain(path, target, *args, **kwargs)
            original_bytes = path.read_bytes()
            path.write_bytes(original_bytes + b" -DXRTSIM\n")
            mutations.append(path)
            try:
                return original_retain(path, target, *args, **kwargs)
            finally:
                path.write_bytes(original_bytes)

        with mock.patch.object(xrt_baseline, "_retain", side_effect=transiently_mutate):
            report = self.run_fixture()

        self.assertEqual(mutations, [self.fixture.build / "sw/runtime/xrt_config.stamp"])
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("retained input differs from its frozen identity", report["reason"])
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertEqual(report["integration"]["exit_code"], 0)
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        self.assertFalse(destination.exists())
        self.assertNotAccepted(report)
        self.assertFinished(report)


class ProbeFailureTests(DriftCheckpointFixture):
    def test_host_probe_io_error_retains_failure_with_null_integration_exit(self):
        self.host_observation.side_effect = OSError("synthetic host identity probe failure")
        report = self.run_fixture()
        self.assertFailedBeforeLaunch(report)
        self.assertIn("synthetic host identity probe failure", report["reason"])
        self.assertNotIn("retained", report)

    def test_host_probe_interrupt_retains_failure_with_null_integration_exit(self):
        self.host_observation.side_effect = KeyboardInterrupt
        report = self.run_fixture()
        self.assertFailedBeforeLaunch(report)
        self.assertEqual(report["reason"], "execution interrupted")
        self.assertNotIn("retained", report)


if __name__ == "__main__":
    unittest.main()
