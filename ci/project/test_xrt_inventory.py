# Licensed under the Apache License, Version 2.0.
"""Independent file-backed inventory checks; no vendor execution is represented."""

from contextlib import ExitStack
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import xrt_inventory
from xrt_test_support import FIXTURE_CONFIGS, VendorFixture, identity, write_file


class InventoryFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.fixture = VendorFixture(self.root / "fixture")

    def inspect(self, fixture=None, source_record=None):
        fixture = fixture or self.fixture
        record = source_record if source_record is not None else fixture.source_record
        with mock.patch.object(xrt_inventory, "collect_source", return_value=copy.deepcopy(record)), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("inspection executed a process")), \
                mock.patch("os.system", side_effect=AssertionError("inspection executed a shell")):
            return xrt_inventory.inspect_manifest(fixture.manifest, fixture.source)

    def assertBlocked(self, report, reason):
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(any(reason in blocker for blocker in report["blockers"]), report)
        if "phase_complete" in report:
            self.assertIs(report["phase_complete"], False)
            self.assertEqual(report["acceptance"], "not_evaluated")


class ManifestInventoryTests(InventoryFixture):
    def test_valid_inert_binding_does_not_grant_acceptance(self):
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["blockers"], [])
        self.assertIs(report["phase_complete"], False)
        self.assertEqual(report["acceptance"], "not_evaluated")
        self.assertTrue(report["receipt_bound"])
        self.assertEqual(report["identities"]["xclbin"], self.fixture.manifest["artifacts"]["xclbin"])
        self.assertTrue(any("do not establish" in text for text in report["limitations"]))

    def test_each_required_vendor_file_must_exist(self):
        for role in self.fixture.files:
            with self.subTest(role=role):
                fixture = VendorFixture(self.root / ("missing-" + role))
                Path(fixture.files[role]["path"]).unlink()
                self.assertBlocked(self.inspect(fixture), "vendor " + role)

    def test_changed_vendor_bytes_cannot_reuse_a_receipt(self):
        tool = Path(self.fixture.files["vpp"]["path"])
        tool.write_text("replacement tool bytes\n", encoding="utf-8")
        self.assertBlocked(self.inspect(), "vendor vpp")

    def test_required_vendor_program_must_be_executable(self):
        Path(self.fixture.files["platforminfo"]["path"]).chmod(0o600)
        self.assertBlocked(self.inspect(), "not executable")

    def test_extra_simulator_and_runtime_headers_are_required(self):
        for index, relative in enumerate(("bin/xsim", "include/experimental/xrt_ip.h")):
            with self.subTest(relative=relative):
                fixture = VendorFixture(self.root / ("extra-" + str(index)))
                root = fixture.vivado if relative.startswith("bin/") else fixture.xrt
                (root / relative).unlink()
                self.assertBlocked(self.inspect(fixture), "vendor prerequisite")

    def test_changed_observed_header_is_recorded_in_identity(self):
        before = self.inspect()
        header = self.fixture.xrt / "include/experimental/xrt_bo.h"
        header.write_text("different supporting header\n", encoding="utf-8")
        after = self.inspect()
        self.assertEqual(after["outcome"], "pass", after)
        key = "xrt_root:include/experimental/xrt_bo.h"
        self.assertNotEqual(before["identities"][key], after["identities"][key])

    def test_missing_platform_artifacts_receipt_and_review_are_blocked(self):
        for role in ("platform", "xclbin", "emconfig", "build_receipt", "qualification_review"):
            with self.subTest(role=role):
                fixture = VendorFixture(self.root / ("missing-record-" + role))
                records = {"platform": fixture.manifest["platform"]["file"],
                           **fixture.manifest["artifacts"],
                           "build_receipt": fixture.manifest["build_receipt"],
                           "qualification_review": fixture.manifest["qualification_review"]}
                Path(records[role]["path"]).unlink()
                self.assertBlocked(self.inspect(fixture), role)

    def test_changed_image_bytes_are_blocked(self):
        Path(self.fixture.manifest["artifacts"]["xclbin"]["path"]).write_bytes(b"different image")
        self.assertBlocked(self.inspect(), "xclbin")

    def test_changed_build_log_is_blocked(self):
        Path(self.fixture.receipt["commands"][0]["log"]["path"]).write_text("changed\n")
        self.assertBlocked(self.inspect(), "build receipt binding")

    def test_receipt_cannot_bind_a_different_source_or_platform(self):
        for index, key in enumerate(("source", "platform")):
            with self.subTest(key=key):
                fixture = VendorFixture(self.root / ("receipt-mismatch-" + str(index)))
                if key == "source":
                    fixture.receipt[key]["revision"] = "c" * 40
                else:
                    fixture.receipt[key]["name"] = "different_platform"
                fixture.refresh()
                report = self.inspect(fixture)
                self.assertBlocked(report, "build receipt binding")
                self.assertIs(report["receipt_bound"], False)

    def test_failed_build_command_cannot_qualify_artifacts(self):
        self.fixture.receipt["commands"][0]["exit_code"] = 1
        self.fixture.refresh()
        self.assertBlocked(self.inspect(), "build receipt binding")

    def test_receipt_command_strings_remain_inert(self):
        sentinel = self.root / "receipt-executed"
        self.fixture.receipt["commands"][0]["argv"] = ["/bin/sh", "-c", "touch " + str(sentinel)]
        self.fixture.refresh()
        self.assertEqual(self.inspect()["outcome"], "pass")
        self.assertFalse(sentinel.exists())

    def test_source_revision_and_tree_must_match(self):
        for key in ("revision", "tree"):
            with self.subTest(key=key):
                source = copy.deepcopy(self.fixture.source_record)
                source[key] = "c" * 40
                self.assertBlocked(self.inspect(source_record=source), "source commit/tree")

    def test_dirty_source_blocker_is_preserved(self):
        source = copy.deepcopy(self.fixture.source_record)
        source.update(outcome="blocked", dirty=True, blockers=["source checkout is dirty"])
        self.assertBlocked(self.inspect(source_record=source), "source checkout is dirty")

    def test_uninitialized_submodule_blocker_is_preserved(self):
        source = copy.deepcopy(self.fixture.source_record)
        source.update(outcome="blocked", blockers=["submodule is not at its recorded revision: dependency"])
        self.assertBlocked(self.inspect(source_record=source), "submodule")

    def test_normal_internal_library_symlink_selects_the_pinned_target(self):
        lookup = self.fixture.xrt / "lib/libxrt_coreutil.so"
        target = lookup.with_name("libxrt_coreutil.so.2")
        lookup.rename(target)
        lookup.symlink_to(target.name)
        self.fixture.files["xrt_coreutil"] = identity(target)
        self.fixture.refresh(bind_receipt=True)
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["lookup_bindings"]["xrt_coreutil"]["resolved"], str(target))

    def test_library_lookup_cannot_select_an_unpinned_file(self):
        lookup = self.fixture.xrt / "lib/libxrt_coreutil.so"
        target = lookup.with_name("libxrt_coreutil.so.unpinned")
        write_file(target, lookup.read_bytes())
        lookup.unlink()
        lookup.symlink_to(target.name)
        self.assertBlocked(self.inspect(), "does not select the pinned file")

    def test_library_symlink_cannot_escape_vendor_root(self):
        lookup = self.fixture.xrt / "lib/libxrt_coreutil.so"
        outside = self.root / "outside-library.so"
        write_file(outside, lookup.read_bytes())
        lookup.unlink()
        lookup.symlink_to(outside)
        self.fixture.files["xrt_coreutil"] = identity(outside)
        self.fixture.refresh(bind_receipt=True)
        self.assertBlocked(self.inspect(), "escapes its declared root")

    def test_artifact_symlink_is_not_treated_as_a_pinned_regular_file(self):
        image = Path(self.fixture.manifest["artifacts"]["xclbin"]["path"])
        replacement = self.root / "replacement-image"
        write_file(replacement, image.read_bytes())
        image.unlink()
        image.symlink_to(replacement)
        self.assertBlocked(self.inspect(), "xclbin")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO checks require POSIX")
    def test_fifo_image_is_rejected_without_waiting_for_a_writer(self):
        image = Path(self.fixture.manifest["artifacts"]["xclbin"]["path"])
        image.unlink()
        os.mkfifo(image)
        self.assertBlocked(self.inspect(), "xclbin")

    def test_invalid_emconfig_bytes_remain_blocked_when_rehashed(self):
        for index, contents in enumerate((b"{}", b"[]", b"not JSON", b'{"x":1,"x":2}',
                                          b'{"x":1e9999}')):
            with self.subTest(contents=contents):
                fixture = VendorFixture(self.root / ("emconfig-" + str(index)))
                record = fixture.manifest["artifacts"]["emconfig"]
                fixture.manifest["artifacts"]["emconfig"] = write_file(record["path"], contents)
                fixture.refresh(bind_receipt=True)
                self.assertBlocked(self.inspect(fixture), "emulation configuration")

    def test_invalid_review_bytes_remain_blocked_when_rehashed(self):
        for index, contents in enumerate((b" \n\t", b"review\x00text", b"\xff")):
            with self.subTest(contents=contents):
                fixture = VendorFixture(self.root / ("review-" + str(index)))
                record = fixture.manifest["qualification_review"]
                fixture.manifest["qualification_review"] = write_file(record["path"], contents)
                fixture.refresh()
                self.assertBlocked(self.inspect(fixture), "qualification review")


class EnvironmentProbeTests(InventoryFixture):
    def test_empty_environment_reports_missing_prerequisites(self):
        report = xrt_inventory.probe_environment({"PATH": str(self.root / "missing")})
        self.assertBlocked(report, "required vendor executable")
        self.assertTrue(all(not item["available_on_path"] for item in report["tools"].values()))
        self.assertTrue(all(not item["set"] for item in report["roots"].values()))

    def test_present_names_do_not_establish_qualification_or_execute(self):
        environment = {"PATH": os.pathsep.join((str(self.fixture.vitis / "bin"),
                                               str(self.fixture.vivado / "bin"))),
                       "XILINX_VITIS": str(self.fixture.vitis),
                       "XILINX_VIVADO": str(self.fixture.vivado),
                       "XILINX_XRT": str(self.fixture.xrt)}
        with mock.patch("subprocess.Popen", side_effect=AssertionError("probe executed a process")):
            report = xrt_inventory.probe_environment(environment)
        self.assertTrue(all(item["available_on_path"] for item in report["tools"].values()))
        self.assertBlocked(report, "pinned platform/artifact manifest")
        self.assertEqual(len(report["blockers"]), 1)
        self.assertNotIn(str(self.fixture.vitis), str(report))


class GeneratedBuildInventoryTests(InventoryFixture):
    def setUp(self):
        super().setUp()
        self.base_result = {"outcome": "pass", "blockers": [], "identity_matches": True}
        self.stack.enter_context(mock.patch.object(xrt_inventory, "collect_build", return_value=self.base_result))
        for relative in ("sw/runtime/xrt/Makefile", "tests/regression/demo/Makefile",
                         "sw/runtime/common.mk", "tests/regression/common.mk"):
            contents = "INERT RECIPE " + relative + "\n"
            write_file(self.fixture.source / relative, contents)
            write_file(self.fixture.build / relative, contents)
        template = "[Emulation]\nuser_pre_sim_script=@VORTEX_HOME@/sw/runtime/xrt/xsim.tcl\n"
        write_file(self.fixture.source / "sw/runtime/xrt/xrt.ini.in", template)
        write_file(self.fixture.build / "sw/runtime/xrt/xrt.ini",
                   template.replace("@VORTEX_HOME@", str(self.fixture.source)))
        for relative in ("sw/runtime/xrt/vortex.cpp", "sw/runtime/xrt/xsim.tcl",
                         "tests/regression/demo/main.cpp", "tests/regression/demo/kernel.cpp",
                         "tests/regression/demo/common.h"):
            write_file(self.fixture.source / relative, "INERT SOURCE " + relative + "\n")

    def inspect_build(self):
        return xrt_inventory.inspect_build(self.fixture.build, self.fixture.source)

    def test_matching_generated_xrt_inputs_are_identified(self):
        report = self.inspect_build()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertIn("sw/runtime/xrt/xrt.ini", report["identities"])

    def test_native_generated_build_blocker_is_preserved(self):
        self.base_result.update(outcome="blocked", blockers=["generated native headers are stale"])
        self.assertBlocked(self.inspect_build(), "generated native headers are stale")

    def test_stale_xrt_makefile_is_rejected_even_with_new_timestamp(self):
        makefile = self.fixture.build / "sw/runtime/xrt/Makefile"
        makefile.write_text("stale recipe with newer modification time\n")
        os.utime(makefile, (2_000_000_000, 2_000_000_000))
        self.assertBlocked(self.inspect_build(), "generated input differs")

    def test_old_nonexistent_tcl_path_is_rejected_even_if_template_matches(self):
        old_template = "[Emulation]\nuser_pre_sim_script=@VORTEX_HOME@/runtime/xrt/xsim.tcl\n"
        write_file(self.fixture.source / "sw/runtime/xrt/xrt.ini.in", old_template)
        write_file(self.fixture.build / "sw/runtime/xrt/xrt.ini",
                   old_template.replace("@VORTEX_HOME@", str(self.fixture.source)))
        self.assertBlocked(self.inspect_build(), "pre-simulation script")

    def test_missing_referenced_tcl_source_is_blocked(self):
        (self.fixture.source / "sw/runtime/xrt/xsim.tcl").unlink()
        self.assertBlocked(self.inspect_build(), "sw/runtime/xrt/xsim.tcl")


class EffectiveConfigurationTests(InventoryFixture):
    def setUp(self):
        super().setUp()
        self.flags = "-DVX_CFG_XLEN=64 " + " ".join(FIXTURE_CONFIGS)
        self.stamps = (self.fixture.build / "tests/regression/demo/config.stamp",
                       self.fixture.build / "sw/runtime/xrt_config.stamp")
        for path in self.stamps:
            write_file(path, self.flags + "\n")
        self.binaries = [self.fixture.build / relative for relative in (
            "tests/regression/demo/demo", "tests/regression/demo/kernel.vxbin",
            "sw/runtime/libvortex.so", "sw/runtime/libvortex-xrt.so")]
        for index, path in enumerate(self.binaries):
            write_file(path, "INERT OUTPUT: " + path.name + "\n", executable=index == 0)

    def inspect_effective(self):
        return xrt_inventory.inspect_effective(self.fixture.build)

    def test_exact_vendor_flags_and_outputs_are_identified(self):
        report = self.inspect_effective()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertTrue(report["native_flags_verified"])
        self.assertEqual(len(report["identities"]), 6)

    def test_simulation_runtime_definitions_are_rejected_in_either_stamp(self):
        for path in self.stamps:
            for flag in ("-DXRTSIM", "-DXRTSIM=0", "-D XRTSIM", "-D XRTSIM=1",
                         '"-DXRTSIM"', "-D 'XRTSIM'"):
                with self.subTest(path=path, flag=flag):
                    write_file(path, self.flags + " " + flag + "\n")
                    self.assertBlocked(self.inspect_effective(), "simulation")
                    write_file(path, self.flags + "\n")

    def test_joined_and_spaced_configuration_undefines_are_rejected(self):
        for flag in ("-UVX_CFG_FPU_TYPE_STD", "-U VX_CFG_FPU_TYPE_STD", "-U XRTSIM"):
            with self.subTest(flag=flag):
                write_file(self.stamps[0], self.flags + " " + flag + "\n")
                self.assertBlocked(self.inspect_effective(), "undefine")

    def test_wrong_xlen_geometry_and_conflicting_definitions_are_rejected(self):
        for flags in (self.flags.replace("XLEN=64", "XLEN=32"),
                      self.flags.replace("NUM_THREADS=4", "NUM_THREADS=8"),
                      self.flags + " -DVX_CFG_NUM_THREADS=8"):
            with self.subTest(flags=flags):
                write_file(self.stamps[1], flags + "\n")
                self.assertBlocked(self.inspect_effective(), "configuration")

    def test_dpi_or_other_scalar_arithmetic_is_rejected(self):
        for flag in ("-DVX_CFG_TCU_TYPE_DPI", "-DVX_CFG_TCU_TYPE=DPI",
                     "-DVX_CFG_FPU_TYPE_DPI", "-DVX_CFG_FPU_TYPE=DSP"):
            with self.subTest(flag=flag):
                write_file(self.stamps[0], self.flags + " " + flag + "\n")
                self.assertBlocked(self.inspect_effective(), "non-native arithmetic")

    def test_each_output_binary_is_required(self):
        for path in self.binaries:
            with self.subTest(path=path):
                contents = path.read_bytes()
                executable = path == self.binaries[0]
                path.unlink()
                self.assertBlocked(self.inspect_effective(), str(path.relative_to(self.fixture.build)))
                write_file(path, contents, executable=executable)

    def test_demo_must_be_executable(self):
        self.binaries[0].chmod(0o600)
        self.assertBlocked(self.inspect_effective(), "not executable")


if __name__ == "__main__":
    unittest.main()
