# SPDX-License-Identifier: Apache-2.0
"""Exercise the contract Makefile with a real nested make and host compiler."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import time
import unittest

from baseline_process import GIB, MIB, run_bounded
from tensor_host_tools import run_host_command


SOURCE = Path(__file__).resolve().parents[2]
CONFIGS = ("-DSIMULATION -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_TYPE_TFR "
           "-DVX_CFG_NUM_THREADS=4 -DVX_CFG_ISSUE_WIDTH=1")


class TensorContractBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p02-build-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.build = self.base / "build"
        self.build.mkdir()
        self.env = {"PATH": os.environ.get("PATH", os.defpath),
                    "LC_ALL": "C", "CCACHE_DISABLE": "1", "OBJCACHE": ""}
        self.compiler = shutil.which("c++", path=self.env["PATH"])
        self.assertIsNotNone(self.compiler, "A host C++ compiler is required")
        run_host_command(
            [str(SOURCE / "configure"), "--xlen=64", "--profile=",
             "--osversion=ubuntu/focal", "--tooldir=" + str(self.base / "tools")],
            cwd=self.build, env=self.env, timeout=60,
        )
        self.unit = self.build / "hw/unittest/tcu_contract"
        self.guard = self.base / "guard.cpp"
        self.guard.write_text(
            "#ifdef __FAST_MATH__\n#error rejected_configuration\n#endif\n"
            "int main() { return 0; }\n", encoding="utf-8",
        )
        tool = self.base / "tools/verilator/bin/verilator"
        tool.parent.mkdir(parents=True)
        tool.write_text("#!" + sys.executable + "\n" + textwrap.dedent(r'''
            import os
            from pathlib import Path
            import subprocess
            import sys

            arguments = sys.argv[1:]
            cflags = arguments[arguments.index("-CFLAGS") + 1]
            source = arguments[arguments.index("-CFLAGS") - 1]
            output = arguments[arguments.index("-o") + 1]
            with Path("verilator-invocations").open("a") as stream:
                stream.write("invoked\n")
            objects = Path("obj_dir")
            objects.mkdir(exist_ok=True)
            (objects / "Makefile").write_text(
                "all: " + output + "\n"
                + output + ": main.o\n\t$(CXX) $< -o $@\n"
                + "main.o: " + source + "\n\t$(CXX) $(CXXFLAGS) -c $< -o $@\n"
            )
            raise SystemExit(subprocess.call([
                "make", "--no-print-directory", "-j1", "-C", str(objects),
                "CXX=" + os.environ["P02_TEST_COMPILER"], "CXXFLAGS=" + cflags,
            ]))
        '''), encoding="utf-8")
        tool.chmod(0o755)
        self.env["P02_TEST_COMPILER"] = self.compiler
        self.commands = 0

    def make(self, *, flags="-std=c++17", fails=False):
        self.commands += 1
        log = self.unit / ("make-" + str(self.commands) + ".log")
        result = run_bounded(
            ["make", "--no-print-directory", "-j1", "THREADS=1",
             "CONFIGS=" + CONFIGS, "SRCS=" + str(self.guard),
             "CXXFLAGS=" + flags, "all"],
            self.unit, self.env, log, timeout_seconds=60,
            min_free_bytes=GIB, max_log_bytes=MIB, max_rss_bytes=GIB,
            resource_paths=(self.base,),
        )
        output = log.read_text(encoding="utf-8", errors="replace")
        self.assertTrue(result["cleanup_complete"], result)
        self.assertEqual(result["outcome"], "fail" if fails else "pass", output)
        if fails:
            self.assertNotEqual(result["exit_code"], 0, output)
        return output

    def invocations(self):
        return len((self.unit / "verilator-invocations").read_text().splitlines())

    def test_generated_rtl_and_verilator_inputs_reach_outer_build(self):
        self.make()
        self.assertEqual(self.invocations(), 1)
        self.make()
        self.assertEqual(self.invocations(), 1, "Unchanged builds should be reusable")
        for count, relative in enumerate(("hw/VX_types.vh", "hw/unittest/verilator.vlt"), 2):
            with self.subTest(dependency=relative):
                dependency = self.build / relative
                changed = max(time.time_ns(), (self.unit / "tcu_contract").stat().st_mtime_ns + 1)
                os.utime(dependency, ns=(changed, changed))
                self.make()
                self.assertEqual(self.invocations(), count)
                # The stand-in does not consume RTL; advance the output as codegen would.
                (self.unit / "tcu_contract").touch()
                self.make()
                self.assertEqual(self.invocations(), count)

    def test_flag_change_recompiles_guard_and_removes_old_outputs(self):
        self.make()
        self.assertTrue((self.unit / "tcu_contract").is_file())
        self.assertTrue((self.unit / "obj_dir/main.o").is_file())
        (self.unit / "tfr_model").write_text("old model output\n", encoding="utf-8")
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                output = self.make(flags="-std=c++17 -D__FAST_MATH__", fails=True)
                self.assertIn("rejected_configuration", output)
                self.assertFalse((self.unit / "tcu_contract").exists())
                self.assertFalse((self.unit / "tfr_model").exists())
                self.assertFalse((self.unit / "obj_dir/main.o").exists())
        self.make()
        self.assertTrue((self.unit / "tcu_contract").is_file())


if __name__ == "__main__":
    unittest.main()
