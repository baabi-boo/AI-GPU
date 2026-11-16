# SPDX-License-Identifier: Apache-2.0
"""Check strict records against real generated Make stamp recipes."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from compiler_records import validate_records
from xrt_contract import CONFIGS


SOURCE = Path(__file__).resolve().parents[2]


class GeneratedCompilerRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        make = shutil.which("make")
        if make is None:
            raise unittest.SkipTest("make unavailable; generated compiler records are not verified")
        if not os.access(SOURCE / "configure", os.X_OK):
            raise unittest.SkipTest("executable configure unavailable; generated records are not verified")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-compiler-records-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.build = cls.root / "build64"
        cls.build.mkdir()
        cls.tools = cls.root / "unused-tools"
        cls.vendor = cls.root / "unused-xrt"
        cls.compiler_marker = cls.root / "compiler-invoked"
        compiler_guard = cls.root / "forbidden-compiler"
        compiler_guard.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0" >> "$AI_GPU_COMPILER_SENTINEL"\nexit 97\n',
            encoding="utf-8",
        )
        compiler_guard.chmod(0o700)
        environment = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
        environment.update(PATH=environment.get("PATH", os.defpath), LANG="C", LC_ALL="C",
                           PYTHONDONTWRITEBYTECODE="1",
                           AI_GPU_COMPILER_SENTINEL=str(cls.compiler_marker))

        def run(arguments, cwd):
            result = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                                    text=True, check=False, timeout=30)
            if result.returncode != 0:
                raise AssertionError("generated stamp command failed: " +
                                     (result.stdout + result.stderr)[-4096:])

        run([str(SOURCE / "configure"), "--xlen=64", "--osversion=ubuntu/focal",
             "--profile=", "--tooldir=" + str(cls.tools),
             "--prefix=" + str(cls.root / "unused-install")], cls.build)
        common = ["TARGET=hw_emu", "CONFIGS=" + " ".join(CONFIGS),
                  "XILINX_XRT=" + str(cls.vendor), "PROFILE=",
                  *[name + "=" + str(compiler_guard)
                    for name in ("CC", "CXX", "VX_CC", "VX_CXX")]]
        # The included .depend target would otherwise invoke a host preprocessor.
        run([make, "--no-print-directory", "-s", "-j1", "--old-file=.depend",
             "-C", "tests/regression/demo", *common, "config.stamp"], cls.build)
        runtime_directory = cls.build / "sw/runtime"
        runtime_stamp = runtime_directory / "xrt_config.stamp"
        run([make, "--no-print-directory", "-s", "-j1", "-C", "sw/runtime/xrt",
             *common, "DESTDIR=" + str(runtime_directory), str(runtime_stamp)], cls.build)
        cls.runtime = runtime_stamp.read_text(encoding="utf-8")
        cls.demo = (cls.build / "tests/regression/demo/config.stamp").read_text(encoding="utf-8")

    def test_real_resolved_records_satisfy_shared_validator(self):
        self.assertIsNone(validate_records(self.runtime, self.demo, str(self.build), CONFIGS))

    def test_generated_roles_and_link_binding_match_actual_recipe(self):
        self.assertEqual(len(self.runtime.rstrip("\n").split("\n")), 1)
        records = self.demo.rstrip("\n").split("\n")
        self.assertEqual(len(records), 3)
        kernel, host, linker = map(shlex.split, records)
        self.assertIn("-march=rv64imafd", kernel)
        self.assertIn("-mabi=lp64d", kernel)
        self.assertNotIn("-march=rv64imafd", host)
        self.assertEqual(linker, ["-L" + str(self.build / "sw/runtime"), "-lvortex"])
        for role in (shlex.split(self.runtime), kernel, host):
            self.assertIn("-DVX_CFG_XLEN=64", role)
            self.assertIn("-DVX_CFG_XLEN_64", role)
            self.assertNotIn("-DXRTSIM", role)

    def test_stamp_targets_require_no_compiler_or_vendor_installation(self):
        self.assertFalse(self.compiler_marker.exists(), "a stamp target invoked a compiler")
        self.assertFalse(self.tools.exists())
        self.assertFalse(self.vendor.exists())
        for relative in ("tests/regression/demo/demo", "tests/regression/demo/kernel.vxbin",
                         "tests/regression/demo/kernel.elf", "sw/runtime/libvortex.so",
                         "sw/runtime/libvortex-xrt.so"):
            with self.subTest(relative=relative):
                self.assertFalse((self.build / relative).exists())


if __name__ == "__main__":
    unittest.main()
