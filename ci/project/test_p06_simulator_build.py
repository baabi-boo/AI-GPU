# SPDX-License-Identifier: Apache-2.0
"""Check incremental backend dependencies without compiling simulator libraries."""

import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SimulatorCompletionBuildTests(unittest.TestCase):
    def test_changed_helper_rebuilds_both_backends_without_compiling_the_header(self):
        with tempfile.TemporaryDirectory(prefix="simulator-completion-build-") as directory:
            base = Path(directory)
            build = base / "build"
            build.mkdir()
            env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                   "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}
            configured = subprocess.run(
                [str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                 "--osversion=ubuntu/focal", "--tooldir=" + str(base / "unused-tools")],
                cwd=build, env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            destination = build / "sw/runtime"
            header = ROOT / "sw/runtime/common/async_run.h"
            self.assertTrue(header.is_file())
            unrelated = base / "unrelated.h"
            unrelated.write_text("unrelated dependency probe\n", encoding="utf-8")
            for backend in ("simx", "rtlsim"):
                with self.subTest(backend=backend):
                    unit = destination / backend
                    self.assertEqual((unit / "Makefile").read_bytes(),
                                     (ROOT / "sw/runtime" / backend / "Makefile").read_bytes())
                    driver = destination / ("lib" + backend + ".so")
                    stamp = destination / (backend + "_rt_config.stamp")
                    target = destination / ("libvortex-" + backend + ".so")
                    for path in (driver, stamp, target):
                        path.write_text("dependency graph placeholder, not a binary\n", encoding="utf-8")
                    command = ["make", "--no-print-directory", "-j1",
                               "DESTDIR=" + str(destination), "CXX=completion-compile-probe",
                               "-o", str(driver), "-o", str(stamp)]

                    def make(*arguments):
                        return subprocess.run(command + list(arguments) + [str(target)],
                                              cwd=unit, env=env, capture_output=True,
                                              text=True, timeout=20)

                    unchanged = make("-q")
                    self.assertEqual(unchanged.returncode, 0, unchanged.stdout + unchanged.stderr)
                    unrelated_change = make("-q", "-W", str(unrelated))
                    self.assertEqual(unrelated_change.returncode, 0,
                                     unrelated_change.stdout + unrelated_change.stderr)
                    changed = make("-q", "-W", str(header))
                    self.assertEqual(changed.returncode, 1, changed.stdout + changed.stderr)
                    planned = make("-n", "-W", str(header))
                    self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
                    recipes = [shlex.split(line) for line in planned.stdout.splitlines()
                               if line.startswith("completion-compile-probe ")]
                    self.assertEqual(len(recipes), 1, planned.stdout)
                    self.assertNotIn(str(header), recipes[0])
                    self.assertIn(str(ROOT / "sw/runtime" / backend / "vortex.cpp"), recipes[0])
                    self.assertEqual(target.read_text(encoding="utf-8"),
                                     "dependency graph placeholder, not a binary\n")


if __name__ == "__main__":
    unittest.main()
