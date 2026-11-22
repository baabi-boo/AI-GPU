# SPDX-License-Identifier: Apache-2.0
"""Check recursive compiler selection with Make dry-runs, without compilation."""

import copy
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest

from test_p06_managed_preflight_runner import ManagedHarness
from tensor_host_tools import run_host_command
import p06_managed_preflight_execute as runner


ROOT = Path(__file__).resolve().parents[2]


def compiler_lines(text, names):
    result = []
    for line in text.splitlines():
        if not any(line.startswith(name + " ") for name in names):
            continue
        words = shlex.split(line)
        if words and words[0] in names:
            result.append(words)
    return result


class ManagedPreflightKernelRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-managed-kernel-route-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.tools = cls.directory / "tools"
        cls.marker = cls.directory / "compiler-was-executed"
        cls.make = shutil.which("make")
        if cls.make is None:
            raise AssertionError("Recursive compiler-route tests require GNU Make")
        cls.selected = {
            "gcc": cls.tools / "host-gcc",
            "g++": cls.tools / "host-g++",
            "riscv-gcc": cls.tools / "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",
            "riscv-ar": cls.tools / "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc-ar",
            "riscv-dump": cls.tools / "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-objdump",
            "clang": cls.tools / "llvm-vortex/bin/clang",
            "clang++": cls.tools / "llvm-vortex/bin/clang++",
            "objdump": cls.tools / "llvm-vortex/bin/llvm-objdump",
            "objcopy": cls.tools / "llvm-vortex/bin/llvm-objcopy",
        }
        for path in cls.selected.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$P06_COMPILER_ROUTE_SENTINEL"\nexit 97\n')
            path.chmod(0o700)
        cls.environment = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
            "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(cls.directory), "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "P06_COMPILER_ROUTE_SENTINEL": str(cls.marker),
        }
        # Capture command construction from the actual executor. External builds,
        # resources and processes are synthetic in this existing bounded harness.
        with ManagedHarness() as fixture:
            result = fixture.run()
            if result["outcome"] != "pass":
                raise AssertionError("Runner command-capture harness failed: " + str(result["reason"]))
            cls.calls = {call["id"]: copy.deepcopy(call) for call in fixture.calls}
            cls.captured_tools = {name: str(path) for name, path in fixture.tool_paths.items()}
            cls.captured_work = str(fixture.paths["work"])
        cls.generated = {}
        for fmt in ("fp16", "bf16"):
            build = cls.directory / ("simx-" + fmt)
            build.mkdir()
            cls.run_command([ROOT / "configure", "--xlen=64", "--profile=p02-tfr",
                             "--osversion=ubuntu/focal", "--tooldir=" + str(cls.tools)], build)
            call = cls.calls["simx-" + fmt + "-application"]
            replacements = {
                cls.captured_tools["make"]: cls.make,
                cls.captured_tools["g++"]: str(cls.selected["g++"]),
                cls.captured_tools["gcc"]: str(cls.selected["gcc"]),
                cls.captured_work: str(cls.directory),
            }
            argv = list(call["argv"])
            for index, argument in enumerate(argv):
                for original, replacement in replacements.items():
                    argument = argument.replace(original, replacement)
                argv[index] = argument
            # Preserve the runner's -j2 and output synchronization. Only disable
            # execution and included dependency-file regeneration for inspection.
            argv[1:1] = ["-n", "--old-file=.depend"]
            current = dict(cls.environment, CONFIGS=call["environment"]["CONFIGS"], PERF="1")
            fixed = cls.run_command(argv, build / runner.APP, current)
            old_argv = [*argv[:-1], "CC=" + str(cls.selected["gcc"]), argv[-1]]
            old = cls.run_command(old_argv, build / runner.APP, current)
            cls.generated[fmt] = {"build": build, "fixed": fixed, "old": old,
                                  "fixed_argv": argv, "old_argv": old_argv}
        if cls.marker.exists():
            raise AssertionError("A compiler or binary tool ran during the dry-run fixture")

    @classmethod
    def run_command(cls, argv, cwd, environment=None):
        return run_host_command(list(map(str, argv)), cwd=cwd, env=environment or cls.environment,
                                timeout=90, max_output_bytes=4 * 1024**2)

    def test_actual_runner_application_omits_host_cc_for_both_formats(self):
        for fmt in ("fp16", "bf16"):
            with self.subTest(fmt=fmt):
                call = self.calls["simx-" + fmt + "-application"]
                self.assertEqual(call["argv"], [self.captured_tools["make"], "--no-print-directory",
                    "-j2", "THREADS=1", "CXX=" + self.captured_tools["g++"],
                    "--output-sync=target", "all"])
                self.assertNotIn("CC", call["environment"])
                self.assertNotIn("CXX", call["environment"])

    def test_actual_runner_backend_keeps_exact_host_cc_and_cxx(self):
        for fmt in ("fp16", "bf16"):
            with self.subTest(fmt=fmt):
                call = self.calls["simx-" + fmt + "-backend"]
                build = Path(self.captured_work) / ("simx-" + fmt)
                self.assertEqual(call["argv"], [self.captured_tools["make"], "--no-print-directory",
                    "-j2", "THREADS=1", "CXX=" + self.captured_tools["g++"],
                    "CC=" + self.captured_tools["gcc"], "DESTDIR=" + str(build / "sw/runtime"),
                    "-f", str(build / runner.APP / "backend.mk"), str(build / "sw/runtime/libvortex-simx.so")])

    def test_old_override_reproduces_host_cc_in_all_kernel_library_compiles(self):
        for fmt, row in self.generated.items():
            with self.subTest(fmt=fmt):
                commands = compiler_lines(row["old"], {str(self.selected["gcc"])})
                compiles = [words for words in commands if "-c" in words]
                self.assertEqual(len(compiles), 14)
                self.assertTrue(all("-march=rv64imafd" in words and "-mabi=lp64d" in words
                                    and "-mcmodel=medany" in words for words in compiles))
                self.assertTrue(all(any(word.startswith(str(ROOT / "sw/kernel/src") + "/")
                                             for word in words) for words in compiles))

    def test_fixed_recursive_kernel_library_uses_configured_riscv_gcc(self):
        for fmt, row in self.generated.items():
            with self.subTest(fmt=fmt):
                cross = compiler_lines(row["fixed"], {str(self.selected["riscv-gcc"])})
                compiles = [words for words in cross if "-c" in words]
                self.assertEqual(len(compiles), 14)
                self.assertEqual(sum("-DKMU_ENABLE" in words for words in compiles), 7)
                self.assertTrue(all("-march=rv64imafd" in words and "-mabi=lp64d" in words
                                    and "-mcmodel=medany" in words for words in compiles))
                self.assertEqual(compiler_lines(row["fixed"], {str(self.selected["gcc"])}), [])

    def test_application_kernel_still_uses_configured_riscv_clang(self):
        for fmt, row in self.generated.items():
            with self.subTest(fmt=fmt):
                for route in ("old", "fixed"):
                    commands = compiler_lines(row[route], {str(self.selected["clang++"])})
                    self.assertTrue(commands)
                    self.assertTrue(all("--target=riscv64-unknown-elf" in words and "-mabi=lp64d" in words
                                        for words in commands))
                    self.assertTrue(any(str(ROOT / "sw/kernel/ai/matmul.cpp") in words for words in commands))

    def test_host_application_and_runtime_remain_on_host_cxx(self):
        for fmt, row in self.generated.items():
            with self.subTest(fmt=fmt):
                for route in ("old", "fixed"):
                    commands = compiler_lines(row[route], {str(self.selected["g++"])})
                    self.assertEqual(len(commands), 2)
                    self.assertTrue(any(str(ROOT / runner.APP / "main.cpp") in words for words in commands))
                    self.assertTrue(any(str(ROOT / "sw/runtime/stub/vortex.cpp") in words for words in commands))
                    self.assertTrue(all(not any(word.startswith(("-march=rv", "-mabi=lp"))
                                                for word in words) for words in commands))

    def test_kernel_archiver_and_dump_still_use_the_pinned_cross_tools(self):
        for fmt, row in self.generated.items():
            with self.subTest(fmt=fmt):
                archives = compiler_lines(row["fixed"], {str(self.selected["riscv-ar"])})
                self.assertEqual(len(archives), 2)
                self.assertEqual({words[2] for words in archives}, {"libvortex.a", "libvortex2.a"})
                self.assertEqual(len(compiler_lines(row["fixed"], {str(self.selected["riscv-dump"])})), 2)

    def test_dry_runs_never_compile_link_or_create_native_outputs(self):
        self.assertFalse(self.marker.exists())
        for fmt, row in self.generated.items():
            with self.subTest(fmt=fmt):
                build = row["build"]
                for relative in (*runner.BINARY_FILES, "sw/kernel/vx_start.S.o", "sw/kernel/vx_start.S.2.o"):
                    self.assertFalse((build / relative).exists(), relative)
                self.assertEqual((build / runner.APP / "Makefile").read_bytes(),
                                 (ROOT / runner.APP / "Makefile").read_bytes())


if __name__ == "__main__":
    unittest.main()
