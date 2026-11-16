# SPDX-License-Identifier: Apache-2.0
"""Check effective SimX configuration with generated Makefiles and a preprocessor."""

import os
from pathlib import Path
import shlex
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


SOURCE = Path(__file__).resolve().parents[2]
TCU_TYPES = ("DPI", "DSP", "BHF", "TFR", "FPNEW")
FPU_TYPES = ("DPI", "DSP", "FPNEW", "STD")


class SimxConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p02-simx-config-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        temporary = cls.base / "tmp"
        temporary.mkdir()
        cls.env = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                   "TMPDIR": str(temporary), "CCACHE_DISABLE": "1", "OBJCACHE": ""}
        cls.compiler = (shutil.which("c++", path=cls.env["PATH"])
                        or shutil.which("g++", path=cls.env["PATH"])
                        or shutil.which("clang++", path=cls.env["PATH"]))
        if cls.compiler is None:
            raise AssertionError("SimX configuration checks require a host C++ compiler")
        cls.make = shutil.which("make", path=cls.env["PATH"])
        if cls.make is None:
            raise AssertionError("SimX configuration checks require make")
        cls.builds = {}
        for xlen, profile in ((32, ""), (64, ""), (64, "p02-tfr")):
            build = cls.base / ("build" + str(xlen) + ("-" + profile if profile else ""))
            build.mkdir()
            run_host_command(
                [str(SOURCE / "configure"), "--xlen=" + str(xlen),
                 "--profile=" + profile, "--osversion=ubuntu/focal",
                 "--tooldir=" + str(cls.base / "unused-tools")],
                cwd=build, env=cls.env, timeout=60,
            )
            cls.builds[xlen, profile] = build
        cls.probe_source = cls.base / "probe.cpp"
        cls.probe_source.write_text('#include "VX_config.h"\n', encoding="utf-8")
        cls.probe_makefile = cls.base / "probe.mk"
        cls.probe_makefile.write_text(
            "$(DESTDIR)/probe.o: $(CONFIG_FILE)\n"
            "\t$(CXX) $(CXXFLAGS) -E -dM $(PROBE_SOURCE) -o $@\n",
            encoding="utf-8",
        )

    def probe(self, xlen, configs="", profile=""):
        build = self.builds[xlen, profile]
        destination = Path(tempfile.mkdtemp(prefix="probe-", dir=self.base))
        output = destination / "probe.o"
        run_host_command(
            [self.make, "--no-print-directory", "-j1", "-f", "Makefile",
             "-f", str(self.probe_makefile), "CXX=" + self.compiler,
             "DESTDIR=" + str(destination), "PROBE_SOURCE=" + str(self.probe_source),
             "CONFIGS=" + configs, str(output)],
            cwd=build / "sim/simx", env=self.env, timeout=30,
        )
        macros = {}
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.startswith("#define "):
                name, _, value = line[len("#define "):].partition(" ")
                macros[name] = value
        flags = shlex.split((destination / "simx_config.stamp").read_text(encoding="utf-8"))
        for token in shlex.split(configs):
            self.assertIn(token, flags, "The actual compiler must retain the raw configuration")
        self.assertEqual(macros["VX_CFG_XLEN"], str(xlen))
        self.assertIn("VX_CFG_XLEN_" + str(xlen), macros)
        self.assertNotIn("VX_CFG_XLEN_" + str(96 - xlen), macros)
        return macros, flags

    def assert_arithmetic(self, macros, tcu, fpu):
        for prefix, selected, choices in (("TCU", tcu, TCU_TYPES), ("FPU", fpu, FPU_TYPES)):
            name = "VX_CFG_" + prefix + "_TYPE"
            self.assertEqual(macros[name], selected)
            self.assertEqual([choice for choice in choices if name + "_" + choice in macros],
                             [selected], "Exactly one arithmetic selector must reach the compiler")

    def assert_boolean(self, macros, name, enabled):
        self.assertEqual(name + "_ENABLE" in macros, enabled)
        self.assertEqual(macros[name + "_ENABLED"], str(int(enabled)))

    def test_raw_enum_overrides_and_boolean_disables_at_both_xlens(self):
        for xlen in (32, 64):
            for tcu in ("TFR", "DPI"):
                for fpu in ("STD", "DPI"):
                    with self.subTest(xlen=xlen, tcu=tcu, fpu=fpu):
                        configs = (f"-DVX_CFG_TCU_TYPE={tcu} -DVX_CFG_FPU_TYPE={fpu} "
                                   "-DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_FP16_DISABLE "
                                   "-DVX_CFG_LMEM_DISABLE -DVX_CFG_EXT_D_DISABLE "
                                   "-DVX_CFG_TCU_FP8_ENABLE -DSIMX_CONFIG_PROBE=19")
                        macros, flags = self.probe(xlen, configs)
                        self.assert_arithmetic(macros, tcu, fpu)
                        self.assertIn("-DVX_CFG_TCU_TYPE_" + tcu, flags)
                        self.assertIn("-DVX_CFG_FPU_TYPE_" + fpu, flags)
                        for name in ("VX_CFG_TCU_FP16", "VX_CFG_LMEM", "VX_CFG_EXT_D"):
                            self.assert_boolean(macros, name, False)
                        for name in ("VX_CFG_EXT_TCU", "VX_CFG_TCU_FP8"):
                            self.assert_boolean(macros, name, True)
                        self.assertEqual(macros["VX_CFG_FLEN"], "32")
                        self.assertEqual(macros["SIMX_CONFIG_PROBE"], "19")

    def test_defaults_keep_header_boolean_and_xlen_derivations(self):
        for xlen in (32, 64):
            with self.subTest(xlen=xlen):
                macros, _ = self.probe(xlen)
                self.assert_arithmetic(macros, "TFR", "STD")
                self.assert_boolean(macros, "VX_CFG_EXT_TCU", False)
                self.assert_boolean(macros, "VX_CFG_TCU_FP16", True)
                self.assert_boolean(macros, "VX_CFG_LMEM", True)
                self.assert_boolean(macros, "VX_CFG_EXT_D", xlen == 64)
                self.assertEqual(macros["VX_CFG_FLEN"], str(xlen))

    def test_profile_resolves_both_input_formats_without_losing_disables(self):
        for input_format in ("fp16", "bf16"):
            with self.subTest(input_format=input_format):
                configs = f"-DITYPE={input_format} -DOTYPE=fp32 -DKUNROLL=1"
                macros, flags = self.probe(64, configs, "p02-tfr")
                self.assert_arithmetic(macros, "TFR", "STD")
                for token in ("-DVX_CFG_TCU_TYPE=TFR", "-DVX_CFG_TCU_TYPE_TFR",
                              "-DVX_CFG_FPU_TYPE=STD", "-DVX_CFG_FPU_TYPE_STD"):
                    self.assertIn(token, flags)
                self.assertEqual(macros["VX_CFG_NUM_THREADS"], "4")
                self.assertEqual(macros["VX_CFG_TCU_LATENCY"], "4")
                self.assert_boolean(macros, "VX_CFG_EXT_TCU", True)
                self.assert_boolean(macros, "VX_CFG_TCU_FP16", True)
                self.assert_boolean(macros, "VX_CFG_LMEM", True)
                for bank in ("TF32", "FP8", "FP4", "INT8", "INT4", "MX", "MXFP4",
                             "NVFP4", "SPARSE", "DSM", "WGMMA"):
                    name = "VX_CFG_TCU_" + bank
                    self.assert_boolean(macros, name, False)
                    self.assertIn("-D" + name + "_DISABLE", flags)
                self.assert_boolean(macros, "VX_CFG_EXT_LDST_MATRIX", False)
                self.assertNotIn("VX_CFG_TCU_FEDP2K", macros)
                self.assertEqual(macros["ITYPE"], input_format)
                self.assertEqual(macros["OTYPE"], "fp32")
                self.assertEqual(macros["KUNROLL"], "1")

    def test_raw_dpi_overrides_the_native_profile(self):
        configs = ("-DVX_CFG_TCU_TYPE=DPI -DVX_CFG_FPU_TYPE=DPI "
                   "-DVX_CFG_TCU_FP16_DISABLE -DVX_CFG_EXT_TCU_DISABLE")
        macros, flags = self.probe(64, configs, "p02-tfr")
        self.assert_arithmetic(macros, "DPI", "DPI")
        self.assert_boolean(macros, "VX_CFG_TCU_FP16", False)
        self.assert_boolean(macros, "VX_CFG_EXT_TCU", False)
        self.assertNotIn("-DVX_CFG_TCU_TYPE=TFR", flags)
        self.assertNotIn("-DVX_CFG_FPU_TYPE=STD", flags)

    def test_explicit_selector_overrides_still_select_dpi(self):
        configs = "-DVX_CFG_TCU_TYPE_DPI -DVX_CFG_FPU_TYPE_DPI"
        for xlen in (32, 64):
            with self.subTest(xlen=xlen):
                macros, _ = self.probe(xlen, configs)
                self.assert_arithmetic(macros, "DPI", "DPI")


if __name__ == "__main__":
    unittest.main()
