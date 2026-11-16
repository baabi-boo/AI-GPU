# SPDX-License-Identifier: Apache-2.0
"""Check generated XRT setup and opt-in tracing without vendor tools."""

import configparser
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2]


class GeneratedXrtConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-xrt-config-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.build = cls.root / "build64"
        cls.build.mkdir()
        environment = os.environ.copy()
        for name in ("PROFILE", "XLEN", "TOOLDIR", "OSVERSION", "PREFIX",
                     "BASH_ENV", "ENV"):
            environment.pop(name, None)
        result = subprocess.run(
            [str(SOURCE / "configure"), "--xlen=64", "--osversion=ubuntu/focal",
             "--profile=", "--tooldir=" + str(cls.root / "tools")],
            cwd=cls.build, env=environment, capture_output=True, text=True,
            check=False, timeout=60,
        )
        if result.returncode != 0:
            raise AssertionError("fresh configure failed: " + result.stdout + result.stderr)
        cls.contents = (cls.build / "sw/runtime/xrt/xrt.ini").read_text(encoding="utf-8")
        cls.configuration = configparser.ConfigParser(interpolation=None)
        cls.configuration.read_string(cls.contents)

    def test_generated_hook_resolves_to_existing_source_script(self):
        hook = Path(self.configuration["Emulation"]["user_pre_sim_script"])
        self.assertEqual(hook, SOURCE / "sw/runtime/xrt/xsim.tcl")
        self.assertTrue(hook.is_file())
        self.assertNotIn("@", self.contents)

    def test_default_config_keeps_console_errors_without_waveform_or_profiles(self):
        self.assertEqual(self.configuration["Runtime"]["runtime_log"], "console")
        self.assertEqual(self.configuration["Emulation"]["debug_mode"], "off")
        self.assertFalse(self.configuration.getboolean("Debug", "profile"))
        self.assertFalse(self.configuration.getboolean("Debug", "timeline_trace"))
        self.assertEqual(self.configuration["Debug"]["data_transfer_trace"], "off")


class XrtWaveformHookTests(unittest.TestCase):
    def run_hook(self, value):
        interpreter = shutil.which("tclsh")
        if interpreter is None:
            self.skipTest("tclsh unavailable; waveform hook execution is not verified")
        environment = os.environ.copy()
        environment.pop("VORTEX_XRT_WAVEFORM", None)
        if value is not None:
            environment["VORTEX_XRT_WAVEFORM"] = value
        environment["AI_GPU_TEST_HOOK"] = str(SOURCE / "sw/runtime/xrt/xsim.tcl")
        script = """set calls {}
proc log_wave {args} {lappend ::calls $args}
if {[catch {source $::env(AI_GPU_TEST_HOOK)} message]} {
    puts stderr $message
    exit 1
}
puts [llength $calls]
foreach call $calls {puts $call}
"""
        result = subprocess.run(
            [interpreter], input=script, env=environment, capture_output=True,
            text=True, check=False, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout.splitlines()

    def test_default_and_non_opt_in_values_do_not_register_waveforms(self):
        for value in (None, "", "0", "false", "true", "01", "1 ", "[error injected]"):
            with self.subTest(value=value):
                self.assertEqual(self.run_hook(value), ["0"])

    def test_exact_opt_in_preserves_recursive_waveform_logging(self):
        self.assertEqual(self.run_hook("1"), ["1", "-r *"])


if __name__ == "__main__":
    unittest.main()
