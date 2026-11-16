# Licensed under the Apache License, Version 2.0.
"""Verify XRT emulation configuration in a fresh generated build tree."""

import configparser
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class XrtConfigurationTests(unittest.TestCase):
    def test_generated_pre_sim_script_resolves_to_tracked_source(self):
        with tempfile.TemporaryDirectory(prefix="ai-gpu-xrt-config-") as directory:
            base = Path(directory)
            build = base / "build64"
            build.mkdir()
            result = subprocess.run(
                [str(ROOT / "configure"), "--xlen=64", "--osversion=ubuntu/focal",
                 "--profile=", "--tooldir=" + str(base / "unused-tools"),
                 "--prefix=" + str(base / "unused-install")],
                cwd=build, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-4096:])
            contents = (build / "sw/runtime/xrt/xrt.ini").read_text(encoding="utf-8")
            self.assertNotRegex(contents, r"@[A-Z_]+@")
            configuration = configparser.ConfigParser(interpolation=None)
            configuration.read_string(contents)
            script = Path(configuration["Emulation"]["user_pre_sim_script"])
            self.assertEqual(script, ROOT / "sw/runtime/xrt/xsim.tcl")
            self.assertTrue(script.is_file(), "generated XRT INI references a missing Tcl script")


if __name__ == "__main__":
    unittest.main()
