# SPDX-License-Identifier: Apache-2.0
"""Actual counter errors through the public runtime, with controlled Processor/RAM."""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import unittest

import test_p06_simulator_public as public
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/checked_counter_public.cpp"


def replace_once(source, original, replacement):
    if source.count(original) != 1:
        raise AssertionError("Controlled-model injection site is no longer unique: " + original)
    return source.replace(original, replacement, 1)


class CheckedCounterPublicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Counter public integration requires C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-checked-public-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name).resolve()
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1", "LD_LIBRARY_PATH": str(cls.build),
            "VORTEX_CP_POLL_TIMEOUT_S": "2", "VORTEX_DRIVER": "simx",
        }
        source_files = [
            FIXTURE, public.FIXTURE, public.CONTROL, Path(public.__file__).resolve(),
            Path(__file__).resolve(), ROOT / "sim/common/perf_counter.h",
            ROOT / "configure", ROOT / "VX_config.toml", ROOT / "VX_types.toml",
            ROOT / "profiles/p02-tfr.json", ROOT / "ci/gen_config.py",
            ROOT / "ci/project/tensor_host_tools.py", ROOT / "ci/project/baseline_process.py",
            ROOT / "sw/runtime/stub/vortex.cpp", ROOT / "sw/runtime/simx/vortex.cpp",
            *(ROOT / "sw/runtime/common" / name for name in public.COMMON_SOURCES),
            *(ROOT / "sw/runtime/common").glob("*.h"), ROOT / "sw/runtime/common/callbacks.inc",
            *(ROOT / "sw/runtime/include").glob("*.h"), *(ROOT / "sw/common").glob("*.h"),
            ROOT / "sim/common/cmd_processor.cpp", ROOT / "sim/common/cmd_processor.h",
        ]
        cls.identities = cls.hash_files(source_files)
        run_host_command(["bash", str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                          "--osversion=ubuntu/focal", "--tooldir=" + str(cls.build / "unused-tools")],
                         cwd=cls.build, env=cls.environment, timeout=120)
        shims = cls.build / "controlled-model"
        shims.mkdir()
        control = replace_once(
            public.CONTROL.read_text(encoding="utf-8"), "#include <stdexcept>\n",
            '#include <stdexcept>\n\nextern "C" void checked_counter_trigger(unsigned site);\n')
        control = replace_once(
            control, 'throw std::runtime_error("injected simulator exception");',
            'checked_counter_trigger(1);\n      throw std::logic_error("counter trigger returned");')
        processor = replace_once(
            public.PROCESSOR_SHIM, "    completion_test::control.dcr_reads.fetch_add(1);\n",
            "    completion_test::control.dcr_reads.fetch_add(1);\n    checked_counter_trigger(2);\n")
        (shims / "mem.h").write_text(public.MEMORY_SHIM, encoding="utf-8")
        (shims / "processor.h").write_text(processor, encoding="utf-8")
        (shims / "control.h").write_text(control, encoding="utf-8")
        cls.generated = cls.hash_files([
            *shims.glob("*.h"), cls.build / "config.mk", cls.build / ".config.stamp",
            cls.build / "sw/VX_config.h", cls.build / "sw/VX_types.h",
        ])
        config_flags = shlex.split(run_host_command([
            "python3", str(ROOT / "ci/gen_config.py"), "--config=" + str(ROOT / "VX_config.toml"),
            "--profile=p02-tfr", "--cflags=-DVX_CFG_XLEN=64",
        ], cwd=cls.build, env=cls.environment, timeout=30))
        flags = [compiler, "-std=c++17", "-O2", "-g0", "-Wall", "-Wextra", "-Werror",
                 "-DNDEBUG", *config_flags, "-DSIMX_CHECKED_COUNTERS=1",
                 "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread"]
        includes = ["-I", str(cls.build / "sw"), "-I", str(ROOT / "sw/runtime/common"),
                    "-I", str(ROOT / "sw/runtime/include"), "-I", str(ROOT / "sw/common"),
                    "-I", str(ROOT / "sw/kernel/include")]
        runtime_sources = [ROOT / "sw/runtime/stub/vortex.cpp",
                           *(ROOT / "sw/runtime/common" / name for name in public.COMMON_SOURCES)]
        run_host_command([*flags, *includes, "-fPIC", "-shared", *map(str, runtime_sources),
                          "-ldl", "-Wl,-soname,libvortex.so", "-o", str(cls.build / "libvortex.so")],
                         cwd=cls.build, env=cls.environment, timeout=180)
        run_host_command([
            *flags, "-I", str(shims), *includes,
            "-I", str(ROOT / "sim/simx"), "-I", str(ROOT / "sim/common"),
            "-DPUBLIC_COMPLETION_BACKEND", "-DCOMPLETION_SIMX", "-fPIC", "-shared",
            str(ROOT / "sw/runtime/simx/vortex.cpp"), str(ROOT / "sim/common/cmd_processor.cpp"),
            str(FIXTURE), "-o", str(cls.build / "libvortex-simx.so"),
        ], cwd=cls.build, env=cls.environment, timeout=60)
        cls.binary = cls.build / "checked-counter-public"
        run_host_command([*flags, *includes, str(FIXTURE), "-L", str(cls.build),
                          "-lvortex", "-ldl", "-o", str(cls.binary)],
                         cwd=cls.build, env=cls.environment, timeout=60)
        cls.binaries = cls.hash_files([
            cls.binary, cls.build / "libvortex.so", cls.build / "libvortex-simx.so",
        ])
        if cls.hash_files(cls.identities) != cls.identities or cls.hash_files(cls.generated) != cls.generated:
            raise AssertionError("Counter public integration inputs changed during compilation")

    @staticmethod
    def hash_files(paths):
        return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def verify_identities(self):
        for identities in (self.identities, self.generated, self.binaries):
            self.assertEqual(self.hash_files(identities), identities,
                             "Counter public integration inputs or binary changed")

    def group(self, group):
        for memory in ("ram", "llc"):
            with self.subTest(memory=memory):
                self.verify_identities()
                output = run_host_command([str(self.binary), group, memory], cwd=self.build,
                                          env=self.environment, timeout=15)
                faults = "0" if group == "success" else "1"
                self.assertRegex(output, r"\APASS checked-counter-public " + re.escape(group)
                                 + r" checks=[1-9][0-9]* typed_faults=" + faults + r" native_model=0\n\Z")
                self.verify_identities()

    def test_normal_public_completion_and_cleanup_remain_usable(self):
        self.group("success")

    def test_async_counter_overflow_survives_public_waits_and_queue_error_consumption(self):
        self.group("async-overflow")

    def test_async_counter_underflow_remains_terminal_after_public_waits(self):
        self.group("async-underflow")

    def test_async_negative_counter_operand_preserves_public_failure_and_cleanup(self):
        self.group("async-negative")

    def test_synchronous_counter_aggregate_error_keeps_output_unchanged_and_backend_terminal(self):
        self.group("query-overflow")


if __name__ == "__main__":
    unittest.main()
