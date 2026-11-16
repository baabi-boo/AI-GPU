# Licensed under the Apache License, Version 2.0.
"""Runtime-inspector orchestration contracts; all build and smoke stages are inert.

The inspector's ELF parsing and actual loader behavior are exercised separately
in test_xrt_runtime. These tests supply its observations at the runner boundary
and prove that a successful smoke cannot bypass a failed or changed observation.
"""

import copy
import json
import os
from pathlib import Path
import signal
import unittest
from unittest import mock

import xrt_baseline
from test_xrt_baseline import REFERENCE_LOG, RunnerFixture, STAGES
from xrt_test_support import identity, write_file


class RuntimeIntegrationFixture(RunnerFixture):
    def setUp(self):
        super().setUp()
        readelf = write_file(self.base / "host/readelf", "INERT HOST INSPECTOR", executable=True)
        coreutil = copy.deepcopy(self.fixture.manifest["vendor"]["files"]["xrt_coreutil"])
        self.runtime_record["identities"] = {"readelf": readelf, "xrt_coreutil": coreutil}
        self.runtime_record["bindings"] = {
            "xrt_coreutil": {
                "requester": str(self.fixture.build / "sw/runtime/libvortex-xrt.so"),
                "kind": "DT_NEEDED", "name": "libxrt_coreutil.so",
                "lookup": str(self.fixture.xrt / "lib/libxrt_coreutil.so"),
                "resolved": coreutil["path"],
            },
        }

    def afterSmoke(self, change):
        self.after_stage = lambda stage: change() if stage == "smoke" else None

    def assertRuntimeFailure(self, report, *, after_smoke):
        self.assertEqual(report["outcome"], "fail", report)
        expected = list(STAGES if after_smoke else STAGES[:-1])
        self.assertEqual([call["id"] for call in self.calls], expected)
        self.assertEqual([entry["id"] for entry in report["commands"]], expected)
        # Each actual fixture command succeeded; the inspector must still veto
        # the overall result and keep the successful child exit separate.
        self.assertTrue(all(entry["outcome"] == "pass" for entry in report["commands"]))
        self.assertEqual(report["integration"]["outcome"], "fail" if after_smoke else "not_run")
        self.assertEqual(report["integration"]["exit_code"], 0 if after_smoke else None)
        stored = self.assertFinished(report)
        self.assertEqual(stored["integration"], report["integration"])
        self.assertEqual([entry["id"] for entry in stored["commands"]], expected)
        self.assertEqual(stored["reason"], report["reason"])
        self.assertFalse((self.fixture.output / "report.json.tmp").exists())
        if after_smoke:
            self.assertIs(report["reference_markers_verified"], True)
            self.assertEqual((self.fixture.output / "logs/smoke.log").read_text(), REFERENCE_LOG)
            self.assertEqual(report["runtime_before"]["outcome"], "pass")
        else:
            self.assertNotIn("reference_markers_verified", report)
            self.assertFalse((self.fixture.output / "logs/smoke.log").exists())
        self.assertNotAccepted(report)
        return stored

    def assertObservationDrift(self, change):
        before = copy.deepcopy(self.runtime_record)
        self.afterSmoke(change)
        report = self.run_fixture()
        stored = self.assertRuntimeFailure(report, after_smoke=True)
        self.assertEqual(self.runtime_observation.call_count, 2)
        self.assertEqual(report["runtime_before"], before)
        self.assertEqual(report["runtime_after"], self.runtime_record)
        self.assertEqual(report["runtime_after"]["outcome"], "pass")
        self.assertNotEqual(report["runtime_after"], report["runtime_before"])
        self.assertIn("runtime binding", report["reason"])
        self.assertNotEqual(stored["runtime_after"], stored["runtime_before"])
        return report

    def assertInspectorException(self, error, *, after_smoke):
        before = copy.deepcopy(self.runtime_record)
        self.runtime_observation.side_effect = [before, error] if after_smoke else error
        previous_handler = signal.getsignal(signal.SIGTERM)
        report = self.run_fixture()
        self.assertIs(signal.getsignal(signal.SIGTERM), previous_handler)
        stored = self.assertRuntimeFailure(report, after_smoke=after_smoke)
        self.assertEqual(self.runtime_observation.call_count, 2 if after_smoke else 1)
        self.assertNotIn("runtime_after", report)
        if not after_smoke:
            self.assertNotIn("runtime_before", report)
        reason = "execution interrupted" if isinstance(error, KeyboardInterrupt) else str(error)
        self.assertEqual(report["reason"], reason)
        self.assertEqual(stored["reason"], reason)


class RuntimeInspectorBoundaryTests(RuntimeIntegrationFixture):
    def test_plan_never_inspects_unbuilt_runtime_files(self):
        self.runtime_observation.side_effect = AssertionError("plan inspected runtime")
        code, report = self.invoke("plan", output=False)
        self.assertEqual(code, 0, report)
        self.assertEqual(report["outcome"], "pass")
        self.runtime_observation.assert_not_called()
        self.runner.assert_not_called()
        self.assertNotIn("runtime_before", report)
        self.assertNotIn("runtime_after", report)
        self.assertNotAccepted(report)

    def test_both_inspections_receive_the_exact_sanitized_smoke_environment(self):
        observations = []

        def observe(data, build, environment):
            observations.append((copy.deepcopy(data), build, copy.deepcopy(environment)))
            expected = STAGES[:-1] if len(observations) == 1 else STAGES
            self.assertEqual([call["id"] for call in self.calls], list(expected))
            self.assertEqual(data, self.fixture.manifest)
            self.assertEqual(build, self.fixture.build)
            checkpoint = json.loads((self.fixture.output / "report.json").read_text())
            self.assertEqual(checkpoint["state"], "running")
            self.assertNotEqual(checkpoint["outcome"], "pass")
            self.assertNotEqual(checkpoint["integration"]["outcome"], "pass")
            if len(observations) == 2:
                self.assertEqual(checkpoint["integration"]["exit_code"], 0)
                # The second inspection must cover changes during evidence
                # retention, after the smoke itself has completed.
                for relative in xrt_baseline.RETAINED_CONFIGS:
                    retained = self.fixture.output / "artifacts" / relative.replace("/", "_")
                    self.assertEqual(retained.read_bytes(), (build / relative).read_bytes())
            return copy.deepcopy(self.runtime_record)

        self.runtime_observation.side_effect = observe
        inherited = {
            "PATH": "/fixture/host/bin", "HOME": "/fixture/home",
            "LD_LIBRARY_PATH": "/untrusted/runtime", "LD_PRELOAD": "/untrusted/preload.so",
            "LD_AUDIT": "/untrusted/audit.so", "LD_DEBUG": "all", "LD_BIND_NOW": "1",
            "GLIBC_TUNABLES": "glibc.cpu.hwcaps=untrusted", "VORTEX_DRIVER": "xrtsim",
            "XCL_EMULATION_MODE": "sw_emu", "XRT_INI_PATH": "/untrusted/xrt.ini",
        }
        with mock.patch.dict(os.environ, inherited, clear=True):
            report = self.run_fixture()

        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(len(observations), 2)
        smoke = self.calls[-1]["environment"]
        for _, _, inspected in observations:
            self.assertEqual(inspected, smoke)
        self.assertEqual(smoke["LD_LIBRARY_PATH"].split(":"), [
            str(self.fixture.build / "sw/runtime"), str(self.fixture.xrt / "lib")])
        self.assertEqual(smoke["PATH"], inherited["PATH"])
        self.assertEqual(smoke["VORTEX_DRIVER"], "xrt")
        self.assertEqual(smoke["XCL_EMULATION_MODE"], "hw_emu")
        self.assertEqual(smoke["XCLBIN_PATH"], self.fixture.manifest["artifacts"]["xclbin"]["path"])
        self.assertEqual(smoke["EMCONFIG_PATH"], str(self.fixture.artifacts))
        self.assertEqual(smoke["XRT_INI_PATH"], str(self.fixture.output / "artifacts/xrt.ini"))
        self.assertEqual({key for key in smoke if key.startswith("LD_")}, {"LD_LIBRARY_PATH"})
        self.assertNotIn("GLIBC_TUNABLES", smoke)
        self.assertEqual(report["runtime_before"], report["runtime_after"])
        self.assertIn("runtime_before", self.checkpoints[-1])
        self.assertNotIn("runtime_after", self.checkpoints[-1])
        self.assertEqual(self.checkpoints[-1]["integration"]["outcome"], "not_run")
        self.assertEqual(self.assertFinished(report)["runtime_before"]["outcome"], "pass")

    def test_failed_runtime_build_never_invokes_the_inspector_or_smoke(self):
        self.failure = "vendor-runtime"
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([call["id"] for call in self.calls], list(STAGES[:-1]))
        self.runtime_observation.assert_not_called()
        self.assertNotIn("runtime_before", report)
        self.assertNotIn("runtime_after", report)
        self.assertEqual(report["integration"]["outcome"], "not_run")
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertFinished(report)

    def test_blocked_prelaunch_inspection_prevents_smoke_and_returns_failure(self):
        blocker = "runtime loader binding: required host readelf is unavailable"
        self.runtime_record.update(outcome="blocked", blockers=[blocker])
        code, report = self.invoke()
        self.assertEqual(code, 1)
        stored = self.assertRuntimeFailure(report, after_smoke=False)
        self.runtime_observation.assert_called_once()
        self.assertEqual(report["runtime_before"]["blockers"], [blocker])
        self.assertEqual(stored["runtime_before"]["outcome"], "blocked")
        self.assertEqual(stored["runtime_before"]["blockers"], [blocker])
        self.assertNotIn("runtime_after", report)

    def test_blocked_final_inspection_vetoes_a_successful_smoke(self):
        blocker = "runtime loader binding: system ld.so.preload can preempt the inspected bindings"
        self.afterSmoke(lambda: self.runtime_record.update(outcome="blocked", blockers=[blocker]))
        code, report = self.invoke()
        self.assertEqual(code, 1)
        stored = self.assertRuntimeFailure(report, after_smoke=True)
        self.assertEqual(self.runtime_observation.call_count, 2)
        self.assertEqual(report["runtime_after"]["outcome"], "blocked")
        self.assertEqual(stored["runtime_after"]["blockers"], [blocker])

    def test_readelf_failure_before_smoke_retains_a_finished_checkpoint(self):
        self.assertInspectorException(OSError("host readelf became inaccessible"), after_smoke=False)

    def test_validation_exception_before_smoke_retains_a_finished_checkpoint(self):
        self.assertInspectorException(ValueError("runtime observation is invalid"), after_smoke=False)

    def test_inspector_failure_after_smoke_cannot_leave_a_pass(self):
        self.assertInspectorException(RuntimeError("runtime observation failed after smoke"), after_smoke=True)

    def test_decode_failure_after_smoke_cannot_leave_a_pass(self):
        self.assertInspectorException(UnicodeError("runtime observation cannot be decoded"), after_smoke=True)

    def test_inspector_interruption_before_smoke_retains_no_execution_claim(self):
        self.assertInspectorException(KeyboardInterrupt(), after_smoke=False)

    def test_inspector_interruption_after_smoke_retains_the_successful_child_exit(self):
        self.assertInspectorException(KeyboardInterrupt(), after_smoke=True)


class RuntimeObservationDriftTests(RuntimeIntegrationFixture):
    def test_changed_runtime_identity_cannot_pass_with_successful_observations(self):
        self.assertObservationDrift(lambda: self.runtime_record["identities"]["xrt_coreutil"].update(
            sha256="f" * 64))

    def test_changed_lookup_cannot_pass_with_unchanged_identity_records(self):
        identities = copy.deepcopy(self.runtime_record["identities"])
        report = self.assertObservationDrift(lambda: self.runtime_record["bindings"]["xrt_coreutil"].update(
            resolved=str(self.fixture.xrt / "lib/same-bytes-at-another-path.so")))
        self.assertEqual(report["runtime_after"]["identities"], identities)

    def test_changed_readelf_bytes_cannot_pass_with_identical_library_bindings(self):
        bindings = copy.deepcopy(self.runtime_record["bindings"])
        report = self.assertObservationDrift(lambda: self.runtime_record["identities"]["readelf"].update(
            sha256="e" * 64))
        self.assertEqual(report["runtime_after"]["bindings"], bindings)

    def test_changed_readelf_path_cannot_pass_even_when_its_bytes_match(self):
        original = self.runtime_record["identities"]["readelf"]["sha256"]
        alternate = self.base / "host/other-readelf"
        write_file(alternate, Path(self.runtime_record["identities"]["readelf"]["path"]).read_bytes(),
                   executable=True)
        report = self.assertObservationDrift(lambda: self.runtime_record["identities"].update(
            readelf=identity(alternate)))
        self.assertEqual(report["runtime_after"]["identities"]["readelf"]["sha256"], original)

    def test_new_comment_only_system_preload_record_cannot_pass(self):
        preload = write_file(self.base / "system/ld.so.preload", "# No injected library.\n")
        self.assertObservationDrift(lambda: self.runtime_record["identities"].update(system_preload=preload))

    def test_removed_system_preload_record_cannot_pass(self):
        self.runtime_record["identities"]["system_preload"] = write_file(
            self.base / "system/ld.so.preload", "# Existing comment.\n")
        self.assertObservationDrift(lambda: self.runtime_record["identities"].pop("system_preload"))

    def test_runtime_drift_during_final_retention_is_checked_after_the_copy(self):
        original_retain = xrt_baseline._retain
        last_copy = self.fixture.output / "artifacts/hw_VX_types.vh"
        mutations = []

        def retain_then_change(path, destination, *args, **kwargs):
            result = original_retain(path, destination, *args, **kwargs)
            if destination == last_copy:
                self.assertEqual(self.runtime_observation.call_count, 1)
                self.runtime_record["identities"]["readelf"]["sha256"] = "d" * 64
                mutations.append(destination)
            return result

        with mock.patch.object(xrt_baseline, "_retain", side_effect=retain_then_change):
            report = self.run_fixture()

        self.assertEqual(mutations, [last_copy])
        self.assertRuntimeFailure(report, after_smoke=True)
        self.assertEqual(self.runtime_observation.call_count, 2)
        self.assertNotEqual(report["runtime_before"], report["runtime_after"])
        self.assertEqual(report["runtime_after"]["outcome"], "pass")


class RuntimeHelperProvenanceTests(RuntimeIntegrationFixture):
    def test_inspector_source_is_frozen_and_retained_with_the_executing_helpers(self):
        self.assertIn("xrt_runtime.py", xrt_baseline.TOOLING_FILES)
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "pass", report)
        original = self.helpers / "xrt_runtime.py"
        retained = self.fixture.output / "artifacts/tooling/xrt_runtime.py"
        self.assertEqual(retained.read_bytes(), original.read_bytes())
        self.assertIn(identity(retained), report["retained"])
        self.assertEqual(report["tooling_before"]["xrt_runtime.py"], {
            key: identity(original)[key] for key in ("sha256", "size_bytes")})
        self.assertFinished(report)

    def test_inspector_source_drift_after_plan_stops_before_any_execution(self):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report)
        with (self.helpers / "xrt_runtime.py").open("ab") as stream:
            stream.write(b"\n# Inspector changed after planning.\n")
        report = xrt_baseline.execute_run(args, report, paths)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("executing helpers changed", report["reason"])
        self.runner.assert_not_called()
        self.runtime_observation.assert_not_called()
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["integration"]["outcome"], "not_run")
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertFinished(report)


if __name__ == "__main__":
    unittest.main()
