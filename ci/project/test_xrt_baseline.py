# Licensed under the Apache License, Version 2.0.
"""File-backed runner orchestration tests; no vendor or GPU execution occurs."""

from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import xrt_baseline
import xrt_inventory
from xrt_test_support import (FIXTURE_CONFIGS, VendorFixture, compiler_stamps,
                              identity, write_file)


HERE = Path(__file__).resolve().parent
HELPER_CONTENTS = {name: (HERE / name).read_bytes()
                   for name in xrt_baseline.TOOLING_FILES}
STAGES = ("configure", "kernel-library", "runtime-stub", "application",
          "vendor-runtime", "smoke")
REFERENCE_LOG = "\n".join((
    "Synthetic orchestration fixture; no vendor execution.",
    "open device connection", "data type: integer", "number of points: 16",
    "buffer size: 64 bytes", "upload source buffer0", "upload source buffer1",
    "launch kernel", "download destination buffer", "wait for completion",
    "verify result", "cleanup", "PASSED!", "",
))
BUILD_COPIES = ("sw/runtime/xrt/Makefile", "tests/regression/demo/Makefile",
                "sw/runtime/common.mk", "tests/regression/common.mk")
GENERATED_FILES = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
                   "hw/VX_config.vh", "hw/VX_types.vh")


class RunnerFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.fixture = VendorFixture(self.base / "fixture")
        self.bundle = self.base / "native-toolchain.lock.json"
        self.bundle.write_bytes((HERE / "p01_toolchain.lock.json").read_bytes())
        for role, relative in xrt_baseline.TOOL_BINARIES.items():
            write_file(self.fixture.tools / relative, "INERT NATIVE TOOL: " + role,
                       executable=True)
        for relative in xrt_baseline.LIBRARIES:
            write_file(self.fixture.tools / relative, "INERT NATIVE LIBRARY")
        # Isolate helper-drift tests from the shared checkout without replacing hashing.
        self.helpers = self.base / "helpers"
        for name, contents in HELPER_CONTENTS.items():
            write_file(self.helpers / name, contents)
        self.stack.enter_context(mock.patch.object(xrt_baseline, "HERE", self.helpers))
        for relative in BUILD_COPIES + xrt_inventory.SOURCE_FILES + ("configure",):
            write_file(self.fixture.source / relative, "INERT SOURCE: " + relative + "\n")
        write_file(self.fixture.source / "sw/runtime/xrt/xrt.ini.in",
                   "[Emulation]\nuser_pre_sim_script=@VORTEX_HOME@/sw/runtime/xrt/xsim.tcl\n")
        self.source_observation = self.stack.enter_context(mock.patch.object(
            xrt_inventory, "collect_source",
            side_effect=lambda _: copy.deepcopy(self.fixture.source_record)))
        # Native configure/header generation and host version probes are external
        # observations. The XRT-specific inspectors still read every fixture file.
        self.build_record = {"outcome": "pass", "blockers": [], "xlen": 64,
                             "profile": "", "os_bundle": "ubuntu/focal",
                             "identity_matches": True}
        self.build_observation = self.stack.enter_context(mock.patch.object(
            xrt_inventory, "collect_build",
            side_effect=lambda *_: copy.deepcopy(self.build_record)))
        self.host_record = {"outcome": "pass", "blockers": [],
                            "tools": {"compiler": {"sha256": "1" * 64}}}
        self.host_observation = self.stack.enter_context(mock.patch.object(
            xrt_baseline, "collect_host",
            side_effect=lambda *_: copy.deepcopy(self.host_record)))
        # The file-backed stages contain inert text. Real ELF loader resolution
        # is independently exercised by the compiled CPU fixtures.
        self.runtime_record = {"outcome": "pass", "blockers": [], "identities": {},
                               "bindings": {}, "limitations": ["Synthetic ELF observation."]}
        self.runtime_observation = self.stack.enter_context(mock.patch.object(
            xrt_baseline, "inspect_runtime",
            side_effect=lambda *_: copy.deepcopy(self.runtime_record)))
        self.stack.enter_context(mock.patch.object(
            xrt_baseline.shutil, "disk_usage",
            return_value=SimpleNamespace(free=64 * xrt_baseline.GIB)))
        self.stack.enter_context(mock.patch.object(
            xrt_baseline, "available_memory_bytes", return_value=32 * xrt_baseline.GIB))
        self.calls = []
        self.checkpoints = []
        self.failure = None
        self.cleanup_complete = True
        self.before_stage = None
        self.after_stage = None
        self.smoke_log = REFERENCE_LOG
        self.runner = self.stack.enter_context(mock.patch.object(
            xrt_baseline, "run_bounded", side_effect=self.fake_command))
        self.stack.enter_context(mock.patch(
            "subprocess.Popen", side_effect=AssertionError("fixture launched a subprocess")))
        self.stack.enter_context(mock.patch(
            "os.system", side_effect=AssertionError("fixture launched a shell")))

    def argv(self, mode="run", output=True):
        fixture = self.fixture
        arguments = [mode, "--source", str(fixture.source),
                     "--build-dir", str(fixture.build),
                     "--tool-dir", str(fixture.tools),
                     "--manifest", str(fixture.manifest_path),
                     "--bundle-manifest", str(self.bundle)]
        if output:
            arguments.extend(("--output", str(fixture.output)))
        return arguments

    def plan(self, mode="run", output=True):
        args = xrt_baseline.argument_parser().parse_args(self.argv(mode, output))
        paths = xrt_baseline.resolve_paths(args)
        return args, paths, xrt_baseline.plan_run(args, paths)

    def run_fixture(self):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        return xrt_baseline.execute_run(args, report, paths)

    def invoke(self, mode="run", output=True):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = xrt_baseline.main(self.argv(mode, output))
        return code, json.loads(stream.getvalue())

    def generate_artifacts(self, stage):
        source, build = self.fixture.source, self.fixture.build
        if stage == "configure":
            for relative in ("sw/kernel", "sw/runtime/stub"):
                (build / relative).mkdir(parents=True, exist_ok=True)
            for relative in BUILD_COPIES:
                write_file(build / relative, (source / relative).read_bytes())
            template = (source / "sw/runtime/xrt/xrt.ini.in").read_bytes()
            write_file(build / "sw/runtime/xrt/xrt.ini",
                       template.replace(b"@VORTEX_HOME@", str(source).encode()))
            for relative in GENERATED_FILES:
                write_file(build / relative, "INERT GENERATED FILE: " + relative + "\n")
        if stage == "runtime-stub":
            write_file(build / "sw/runtime/libvortex.so", "INERT RUNTIME STUB")
        if stage == "application":
            write_file(build / "tests/regression/demo/demo", "INERT HOST BINARY", executable=True)
            write_file(build / "tests/regression/demo/kernel.vxbin", "INERT KERNEL BINARY")
            write_file(build / "tests/regression/demo/config.stamp",
                       compiler_stamps(build)["demo"])
        if stage == "vendor-runtime":
            write_file(build / "sw/runtime/libvortex-xrt.so", "INERT VENDOR RUNTIME")
            write_file(build / "sw/runtime/xrt_config.stamp",
                       compiler_stamps(build)["runtime"])

    def fake_command(self, argv, cwd, environment, log, **budget):
        stage = log.stem
        self.calls.append({"id": stage, "argv": list(argv), "cwd": cwd,
                           "environment": dict(environment), "budget": budget})
        checkpoint = json.loads((self.fixture.output / "report.json").read_text())
        self.checkpoints.append(checkpoint)
        self.assertEqual(checkpoint["active_command"], stage)
        self.assertEqual(checkpoint["commands"][-1]["id"], stage)
        self.assertEqual(checkpoint["commands"][-1]["outcome"], "not_run")
        self.assertIsNone(checkpoint["commands"][-1]["exit_code"])
        if self.before_stage is not None:
            self.before_stage(stage)
        if stage != self.failure:
            self.generate_artifacts(stage)
        recorded = write_file(log, self.smoke_log if stage == "smoke" else "Synthetic stage only.\n")
        if self.after_stage is not None:
            self.after_stage(stage)
        return {"outcome": "fail" if stage == self.failure else "pass",
                "exit_code": 7 if stage == self.failure else 0,
                "cleanup_complete": self.cleanup_complete,
                "log_sha256": recorded["sha256"], "log_size_bytes": recorded["size_bytes"]}

    def assertNotAccepted(self, report):
        self.assertIs(report["phase_complete"], False)
        self.assertEqual(report["acceptance"], "not_evaluated")

    def assertFinished(self, report):
        self.assertEqual(report["state"], "finished")
        self.assertIn("finished_at", report)
        self.assertNotIn("active_command", report)
        stored = json.loads((self.fixture.output / "report.json").read_text())
        self.assertEqual(stored["outcome"], report["outcome"])
        self.assertEqual(stored["state"], "finished")
        self.assertNotIn("active_command", stored)
        self.assertNotAccepted(stored)
        return stored

    def mutate(self, role):
        if role == "source":
            self.fixture.source_record["tree"] = "c" * 40
        elif role == "vendor":
            Path(self.fixture.files["vpp"]["path"]).write_bytes(b"CHANGED VENDOR BYTES")
        elif role == "manifest":
            with self.fixture.manifest_path.open("ab") as stream:
                stream.write(b"\n")
        elif role == "helpers":
            with (self.helpers / "xrt_contract.py").open("ab") as stream:
                stream.write(b"\n# Changed fixture helper.\n")
        elif role == "native":
            relative = xrt_baseline.TOOL_BINARIES["riscv_gcc"]
            (self.fixture.tools / relative).write_bytes(b"CHANGED NATIVE BYTES")
        elif role == "host":
            self.host_record["tools"]["compiler"]["sha256"] = "2" * 64
        else:
            raise AssertionError("unknown drift role: " + role)

    def assertDrift(self, role, after_plan):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        if after_plan:
            self.mutate(role)
        else:
            self.after_stage = lambda stage: self.mutate(role) if stage == "configure" else None
        report = xrt_baseline.execute_run(args, report, paths)
        self.assertEqual(report["outcome"], "fail", report)
        self.assertIn("changed", report["reason"])
        self.assertEqual([call["id"] for call in self.calls], [] if after_plan else ["configure"])
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertNotEqual(report["integration"]["outcome"], "pass")
        self.assertFinished(report)


class XrtPlanTests(RunnerFixture):
    def test_plan_is_read_only_and_does_not_probe_or_execute_tools(self):
        before = {str(path.relative_to(self.base)): identity(path)
                  for path in self.base.rglob("*") if path.is_file()}
        code, report = self.invoke("plan", output=False)
        after = {str(path.relative_to(self.base)): identity(path)
                 for path in self.base.rglob("*") if path.is_file()}
        self.assertEqual(code, 0, report)
        self.assertEqual(report["outcome"], "pass")
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["integration"]["outcome"], "not_run")
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertEqual(len(report["planned_commands"]), 6)
        self.assertEqual(before, after)
        self.assertEqual(list(self.fixture.build.iterdir()), [])
        self.assertFalse(self.fixture.output.exists())
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()
        self.build_observation.assert_not_called()
        self.assertNotAccepted(report)

    def test_missing_vendor_prerequisite_blocks_without_launch(self):
        Path(self.fixture.files["vpp"]["path"]).unlink()
        code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["state"], "blocked")
        self.assertTrue(any("vendor vpp" in blocker for blocker in report["blockers"]))
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["integration"],
                         {"gate": "P01-A03", "outcome": "blocked", "exit_code": None})
        self.assertEqual(list(self.fixture.build.iterdir()), [])
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()
        self.assertNotAccepted(report)
        self.assertTrue((self.fixture.output / "report.json").is_file())

    def test_helpers_changed_since_import_block_planning(self):
        self.mutate("helpers")
        _, _, report = self.plan()
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("executing helpers changed after import", report["blockers"])
        self.assertEqual(report["commands"], [])
        self.runner.assert_not_called()


class XrtRunTests(RunnerFixture):
    def test_six_stage_success_retains_real_identities_without_acceptance(self):
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        self.assertEqual([entry["id"] for entry in report["commands"]], list(STAGES))
        self.assertTrue(all(entry["outcome"] == "pass" for entry in report["commands"]))
        self.assertEqual(report["integration"],
                         {"gate": "P01-A03", "outcome": "pass", "exit_code": 0})
        self.assertIs(report["reference_markers_verified"], True)
        self.assertEqual(report["inventory_after"], report["inventory_before"])
        self.assertEqual(report["effective_after"], report["effective_before"])
        self.assertEqual(report["build_after"], report["build_before_smoke"])
        self.assertEqual(report["host_after"], report["host_before"])
        for retained in report["retained"]:
            self.assertEqual(identity(retained["path"]), retained)
        for relative, recorded in report["binary_identities"].items():
            observed = identity(self.fixture.build / relative)
            self.assertEqual(recorded, {key: observed[key] for key in ("sha256", "size_bytes")})
        for command in report["commands"]:
            observed = identity(self.fixture.output / command["log"])
            self.assertEqual(command["log_sha256"], observed["sha256"])
            self.assertEqual(command["log_size_bytes"], observed["size_bytes"])
        self.assertNotAccepted(report)
        self.assertFinished(report)

    def test_fixed_target_configuration_argv_and_sanitized_environment(self):
        inherited = {"PATH": "/inert/host/bin", "HOME": "/inert/home",
                     "LM_LICENSE_FILE": "secret-license-value",
                     "XILINXD_LICENSE_FILE": "other-secret-license-value",
                     "LD_PRELOAD": "/untrusted.so", "LD_LIBRARY_PATH": "/untrusted/lib",
                     "CONFIGS": "-DXRTSIM -DVX_CFG_NUM_THREADS=99", "MAKEFLAGS": "-j999",
                     "PYTHONPATH": "/untrusted/python", "TARGET": "hw",
                     "VORTEX_DRIVER": "simx", "XCL_EMULATION_MODE": "sw_emu",
                     "XCLBIN_PATH": "/untrusted/image", "EMCONFIG_PATH": "/untrusted/emconfig",
                     "XRT_INI_PATH": "/untrusted/xrt.ini", "XRT_DEVICE_INDEX": "99",
                     "TMPDIR": "/untrusted/tmp", "JOBS": "999", "BASH_ENV": "/untrusted/rc"}
        with mock.patch.dict(os.environ, inherited, clear=True):
            report = self.run_fixture()
        self.assertEqual(report["outcome"], "pass", report)
        fixture = self.fixture
        self.assertEqual(self.calls[0]["argv"], [str(fixture.source / "configure"),
                         "--xlen=64", "--osversion=ubuntu/focal", "--tooldir=" + str(fixture.tools)])
        make = ["make", "-j2", "TARGET=hw_emu", "CONFIGS=" + " ".join(FIXTURE_CONFIGS),
                "JOBS=2", "IMPL_MAX_THREADS=2"]
        suffixes = (["-C", "sw/kernel"], ["-C", "sw/runtime/stub"],
                    ["-C", "tests/regression/demo", "all"],
                    ["-C", "tests/regression/demo", "runtime-xrt"])
        for call, suffix in zip(self.calls[1:5], suffixes):
            self.assertEqual(call["argv"], make + suffix)
        self.assertEqual(self.calls[-1]["argv"],
                         [str(fixture.build / "tests/regression/demo/demo"), "-n1"])
        self.assertEqual(self.calls[-1]["cwd"], fixture.build / "tests/regression/demo")
        for call in self.calls:
            environment = call["environment"]
            self.assertEqual(environment["CONFIGS"], " ".join(FIXTURE_CONFIGS))
            self.assertEqual(environment["TARGET"], "hw_emu")
            self.assertEqual(environment["MAKEFLAGS"], "-j2")
            self.assertEqual(environment["JOBS"], "2")
            self.assertEqual(environment["IMPL_MAX_THREADS"], "2")
            self.assertEqual(environment["LM_LICENSE_FILE"], inherited["LM_LICENSE_FILE"])
            self.assertEqual(environment["TMPDIR"], str(fixture.output / "tmp"))
            self.assertEqual(environment["XILINX_VITIS"], str(fixture.vitis))
            self.assertEqual(environment["XILINX_VIVADO"], str(fixture.vivado))
            self.assertEqual(environment["XILINX_XRT"], str(fixture.xrt))
            for key in ("LD_PRELOAD", "PYTHONPATH", "BASH_ENV"):
                self.assertNotIn(key, environment)
            self.assertEqual(call["budget"]["timeout_seconds"], 1800)
            self.assertEqual(call["budget"]["min_free_bytes"], 15 * xrt_baseline.GIB)
            self.assertEqual(call["budget"]["max_rss_bytes"], 6 * xrt_baseline.GIB)
            self.assertEqual(call["budget"]["max_log_bytes"], 16 * xrt_baseline.MIB)
        for call in self.calls[:-1]:
            self.assertEqual(call["cwd"], fixture.build)
            for key in ("LD_LIBRARY_PATH", "VORTEX_DRIVER", "XCL_EMULATION_MODE",
                        "XCLBIN_PATH", "EMCONFIG_PATH", "XRT_INI_PATH", "XRT_DEVICE_INDEX"):
                self.assertNotIn(key, call["environment"])
        smoke = self.calls[-1]["environment"]
        self.assertEqual(smoke["VORTEX_DRIVER"], "xrt")
        self.assertEqual(smoke["XCL_EMULATION_MODE"], "hw_emu")
        self.assertEqual(smoke["XCLBIN_PATH"], str(fixture.artifacts / "vortex_afu.xclbin"))
        self.assertEqual(smoke["EMCONFIG_PATH"], str(fixture.artifacts))
        self.assertEqual(smoke["XRT_DEVICE_INDEX"], "0")
        self.assertEqual(smoke["LD_LIBRARY_PATH"],
                         str(fixture.build / "sw/runtime") + ":" + str(fixture.xrt / "lib"))
        self.assertEqual(smoke["XRT_INI_PATH"], str(fixture.output / "artifacts/xrt.ini"))
        self.assertIn("timeline_trace=false", Path(smoke["XRT_INI_PATH"]).read_text())
        serialized = json.dumps(report) + (fixture.output / "report.json").read_text()
        self.assertNotIn("secret-license-value", serialized)
        self.assertNotIn("fixture-command-never-executed",
                         json.dumps([call["argv"] for call in self.calls]))

    def test_configure_failure_stops_before_build_and_retains_checkpoint(self):
        self.failure = "configure"
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([call["id"] for call in self.calls], ["configure"])
        self.assertEqual(report["commands"][0]["exit_code"], 7)
        self.assertNotIn("build_configured", report)
        self.assertIsNone(report["integration"]["exit_code"])
        stored = self.assertFinished(report)
        self.assertEqual(stored["commands"][0]["outcome"], "fail")
        self.assertTrue((self.fixture.output / "logs/configure.log").is_file())

    def test_application_failure_retains_partial_commands_without_smoke(self):
        self.failure = "application"
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([call["id"] for call in self.calls], list(STAGES[:4]))
        self.assertEqual([entry["outcome"] for entry in report["commands"]],
                         ["pass", "pass", "pass", "fail"])
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertNotIn("reference_markers_verified", report)
        self.assertEqual(len(self.assertFinished(report)["commands"]), 4)

    def test_incomplete_process_cleanup_stops_the_sequence(self):
        self.cleanup_complete = False
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([call["id"] for call in self.calls], ["configure"])
        self.assertIs(report["commands"][0]["cleanup_complete"], False)
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertFinished(report)

    def test_interrupt_retains_the_pending_command_checkpoint(self):
        def interrupt(stage):
            if stage == "kernel-library":
                raise KeyboardInterrupt
        self.before_stage = interrupt
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["reason"], "execution interrupted")
        self.assertEqual([call["id"] for call in self.calls], list(STAGES[:2]))
        self.assertEqual(report["commands"][-1]["outcome"], "not_run")
        self.assertIsNone(report["commands"][-1]["exit_code"])
        self.assertEqual(len(self.assertFinished(report)["commands"]), 2)

    def test_host_prerequisite_failure_blocks_before_configure(self):
        self.host_record.update(outcome="blocked", blockers=["native compiler is unavailable"])
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["integration"]["outcome"], "blocked")
        self.assertIsNone(report["integration"]["exit_code"])
        self.runner.assert_not_called()
        self.assertFinished(report)

    def test_missing_effective_artifact_blocks_smoke(self):
        def remove_kernel(stage):
            if stage == "vendor-runtime":
                (self.fixture.build / "tests/regression/demo/kernel.vxbin").unlink()
        self.after_stage = remove_kernel
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([call["id"] for call in self.calls], list(STAGES[:5]))
        self.assertEqual(report["effective_before"]["outcome"], "blocked")
        self.assertTrue(any("kernel.vxbin" in item for item in report["effective_before"]["blockers"]))
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertFinished(report)

    def test_non_native_effective_flags_block_smoke(self):
        def contaminate(stage):
            if stage == "vendor-runtime":
                stamp = self.fixture.build / "sw/runtime/xrt_config.stamp"
                write_file(stamp, stamp.read_text().rstrip("\n")
                           + " -DXRTSIM -DVX_CFG_FPU_TYPE_DPI\n")
        self.after_stage = contaminate
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([call["id"] for call in self.calls], list(STAGES[:5]))
        self.assertTrue(any("shim" in item
                            for item in report["effective_before"]["blockers"]))
        self.assertIsNone(report["integration"]["exit_code"])
        self.assertFinished(report)

    def test_successful_exit_without_reference_milestones_is_not_success(self):
        self.smoke_log = "Synthetic process exit only.\nPASSED!\n"
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["commands"][-1]["outcome"], "pass")
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertEqual(report["integration"]["exit_code"], 0)
        self.assertIs(report["reference_markers_verified"], False)
        self.assertIn("unique ordered integer reference milestones", report["reason"])
        self.assertFinished(report)

    def test_smoke_failure_cannot_be_rescued_by_pass_markers(self):
        self.failure = "smoke"
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertEqual(report["integration"]["exit_code"], 7)
        self.assertNotIn("reference_markers_verified", report)
        self.assertFinished(report)

    def test_effective_binary_drift_during_smoke_is_rejected(self):
        def change_binary(stage):
            if stage == "smoke":
                (self.fixture.build / "sw/runtime/libvortex-xrt.so").write_bytes(b"CHANGED RUNTIME")
        self.after_stage = change_binary
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "fail")
        self.assertIs(report["reference_markers_verified"], True)
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertIn("changed during execution", report["reason"])
        self.assertFinished(report)

    def test_source_changed_after_plan(self):
        self.assertDrift("source", after_plan=True)

    def test_vendor_changed_after_plan(self):
        self.assertDrift("vendor", after_plan=True)

    def test_manifest_changed_after_plan(self):
        self.assertDrift("manifest", after_plan=True)

    def test_helpers_changed_after_plan(self):
        self.assertDrift("helpers", after_plan=True)

    def test_native_tool_changed_after_plan(self):
        self.assertDrift("native", after_plan=True)

    def test_source_changed_between_stages(self):
        self.assertDrift("source", after_plan=False)

    def test_vendor_changed_between_stages(self):
        self.assertDrift("vendor", after_plan=False)

    def test_manifest_changed_between_stages(self):
        self.assertDrift("manifest", after_plan=False)

    def test_helpers_changed_between_stages(self):
        self.assertDrift("helpers", after_plan=False)

    def test_native_tool_changed_between_stages(self):
        self.assertDrift("native", after_plan=False)

    def test_host_changed_between_stages(self):
        self.assertDrift("host", after_plan=False)


if __name__ == "__main__":
    unittest.main()
