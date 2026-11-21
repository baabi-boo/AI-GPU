# SPDX-License-Identifier: Apache-2.0
"""Independent stamp and host-preprocessor checks; no GPU compilation or execution."""

import copy
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import p02_matrix_records as legacy
import p06_compiler_records as records
from p06_execute import (HEADER_PROBE, HEADER_PROBE_CONTENT, effective_header_command,
                         validate_effective_header)
from test_p02_matrix import BUILD, SOURCE, STAMP_SAMPLES, sample


ROOT = Path(__file__).resolve().parents[2]
ROLES = ((0, 0, "runtime"), (1, 0, "backend_cpp"),
         (2, 0, "kernel"), (2, 1, "host"))
WRAPPERS = ("-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release")


def fixture_stamps(fmt="bf16"):
    """Adapt retained legacy parser fixtures; these are not new native evidence."""
    runtime = sample("simx_rt", fmt=fmt)
    backend = sample("simx_backend", fmt=fmt).rstrip("\n") + " -DPERF_ENABLE\n"
    application = sample("application", fmt=fmt).splitlines()
    application[1] = application[1].replace(
        "-I" + str(SOURCE / "third_party/softfloat/source/include"),
        "-I" + str(SOURCE / "sw/runtime/ai"))
    application[2] = " ".join((*WRAPPERS, "-L" + str(BUILD / "sw/runtime"), "-lvortex"))
    return [runtime, backend, "\n".join(application) + "\n"]


def change_role(stamps, outer, inner, transform):
    changed = list(stamps)
    lines = changed[outer].splitlines()
    lines[inner] = transform(lines[inner])
    changed[outer] = "\n".join(lines) + "\n"
    return changed


class BenchmarkCompilerRecordTests(unittest.TestCase):
    def validate(self, stamps, fmt="bf16", **kwargs):
        options = dict(fmt=fmt, source=SOURCE, build=BUILD, jobs=2)
        options.update(kwargs)
        return records.validate_records(*stamps, **options)

    def test_four_roles_preserve_raw_hashes_and_flags_in_both_formats(self):
        for fmt in ("fp16", "bf16"):
            original = fixture_stamps(fmt)
            saved = copy.deepcopy(original)
            result = self.validate(original, fmt)
            self.assertEqual([row["role"] for row in result], [row[2] for row in ROLES])
            for (outer, inner, role), row in zip(ROLES, result):
                with self.subTest(fmt=fmt, role=role):
                    text = original[outer].splitlines()[inner]
                    self.assertEqual(row["sha256"], hashlib.sha256(text.encode()).hexdigest())
                    self.assertEqual(row["configuration"]["ITYPE"], fmt)
                    self.assertEqual(row["configuration"]["OTYPE"], "fp32")
                    self.assertEqual("PERF_ENABLE" in row["configuration"], role == "backend_cpp")
                    self.assertIn("-DVX_CFG_TCU_TYPE_TFR", row["macro_flags"])
                    self.assertIn("-DVX_CFG_FPU_TYPE_STD", row["macro_flags"])
            self.assertEqual(original, saved)

    def test_no_cross_role_pooling_or_missing_native_selectors(self):
        for outer, inner, role in ROLES:
            for flag in ("-DVX_CFG_NUM_THREADS=4", "-DVX_CFG_TCU_TYPE_TFR",
                         "-DVX_CFG_FPU_TYPE_STD", "-DITYPE=bf16", "-DKUNROLL=1"):
                original = fixture_stamps()
                self.assertIn(flag, original[outer].splitlines()[inner])
                changed = change_role(original, outer, inner, lambda line: line.replace(flag, ""))
                with self.subTest(role=role, flag=flag), self.assertRaises(ValueError):
                    self.validate(changed)

    def test_perf_is_exactly_once_and_only_in_backend(self):
        for value in ("", "-DPERF_ENABLE=0", "-DPERF_ENABLE -DPERF_ENABLE",
                      "-DPERF_ENABLE -Wp,-DPERF_ENABLE=1"):
            original = fixture_stamps()
            original[1] = original[1].replace("-DPERF_ENABLE", value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate(original)
        for outer, inner, role in ROLES:
            if role == "backend_cpp":
                continue
            changed = change_role(fixture_stamps(), outer, inner, lambda text: text + " -DPERF_ENABLE")
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.validate(changed)

    def test_functional_zero_and_concurrency_cannot_hide_in_macro_transport(self):
        flags = ("-DSIMX_FUNCTIONAL=0", "-D SIMX_FUNCTIONAL=0",
                 "--define-macro=SIMX_FUNCTIONAL=0", "--define-macro SIMX_FUNCTIONAL=0",
                 "-Wp,-DSIMX_FUNCTIONAL=0", "-Xpreprocessor -DSIMX_FUNCTIONAL=0",
                 "-DSIMX_MT=0", "-DSIMX_MT=4")
        for outer, inner, role in ROLES:
            for flag in flags:
                changed = change_role(fixture_stamps(), outer, inner, lambda text: text + " " + flag)
                with self.subTest(role=role, flag=flag), self.assertRaises(ValueError):
                    self.validate(changed)

    def test_isa_geometry_arithmetic_and_instrumentation_are_frozen_per_role(self):
        flags = ("-march=rv64imafdc", "-DVX_CFG_XLEN_32", "-DVX_CFG_NUM_CORES=2",
                 "-DVX_CFG_MEM_BLOCK_SIZE=128", "-DVX_CFG_TCU_LATENCY=5",
                 "-DVX_CFG_TCU_TYPE_DPI=0", "-DVX_CFG_FPU_TYPE_DPI=0",
                 "-DVX_CFG_TCU_FP8_ENABLE=0", "-DVX_CFG_L2_ENABLE=0",
                 "-DVX_CFG_VM_ENABLE=0", "-DVX_CFG_ICACHE_DISABLE=0",
                 "-DDEBUG=0", "-DTRACING_ALL=0", "-DDBG_TRACE_CORE=0",
                 "-D__FAST_MATH__=0", "-D__FINITE_MATH_ONLY__=1",
                 "-ffast-math", "-Ofast", "-fno-signed-zeros", "-fno-math-errno")
        for outer, inner, role in ROLES:
            for flag in flags:
                changed = change_role(fixture_stamps(), outer, inner, lambda text: text + " " + flag)
                with self.subTest(role=role, flag=flag), self.assertRaises(ValueError):
                    self.validate(changed)

    def test_shell_response_include_and_option_operand_escapes_fail(self):
        flags = ("$(touch sentinel)", "`touch sentinel`", ";touch sentinel", "@options.txt",
                 "-include /unretained/header", "-I/outside", "-I" + str(SOURCE) + "/../outside",
                 "-I -DPERF_ENABLE", "-Xpreprocessor", "-Wp,-U,VX_CFG_NUM_CORES",
                 "-DUNDECLARED_OPTION=1", "-g", "-O2")
        for outer, inner, role in ROLES:
            for flag in flags:
                changed = change_role(fixture_stamps(), outer, inner, lambda text: text + " " + flag)
                with self.subTest(role=role, flag=flag), self.assertRaises(ValueError):
                    self.validate(changed)

    def test_record_inventory_order_and_bounded_text(self):
        for index in range(3):
            for mutation in (lambda text: "\n".join(text.splitlines()[1:]),
                             lambda text: text + text.splitlines()[0] + "\n",
                             lambda text: text + "\x00", lambda text: text + "\rmalformed",
                             lambda text: "x" * (1024 * 1024 + 1), lambda text: text.encode()):
                changed = fixture_stamps()
                changed[index] = mutation(changed[index])
                with self.subTest(stamp=index, mutation=mutation), self.assertRaises(ValueError):
                    self.validate(changed)
        changed = fixture_stamps()
        lines = changed[2].splitlines()
        changed[2] = "\n".join((lines[1], lines[0], lines[2]))
        with self.assertRaises(ValueError):
            self.validate(changed)

    def test_link_order_runtime_binding_and_dependency_target(self):
        valid = [*WRAPPERS, "-L" + str(BUILD / "sw/runtime"), "-lvortex"]
        alternatives = (valid[1:] + valid[:1], [*reversed(WRAPPERS), *valid[2:]],
                        valid[1:], valid + ["-lm"], [*WRAPPERS, "-L/other", "-lvortex"],
                        [*WRAPPERS, "-L" + str(BUILD / "sw/runtime/../runtime"), "-lvortex"])
        for linker in alternatives:
            changed = change_role(fixture_stamps(), 2, 2, lambda _: " ".join(linker))
            with self.subTest(linker=linker), self.assertRaises(ValueError):
                self.validate(changed)
        original = fixture_stamps()
        needle = str(BUILD / "sw/runtime/simx_config.stamp")
        self.assertIn(needle, original[1])
        original[1] = original[1].replace(needle, "/unbound/simx_config.stamp")
        with self.assertRaises(ValueError):
            self.validate(original)

    def test_include_search_rejects_extra_missing_reordered_and_forwarded_paths(self):
        for outer, inner, role in ROLES:
            row = self.validate(fixture_stamps())[next(i for i, item in enumerate(ROLES)
                                                     if item[2] == role)]
            first, second = ("-I" + path for path in row["include_paths"][:2])
            changes = (
                lambda text: "-I" + str(BUILD / "shadow") + " " + text,
                lambda text: text + " -I" + str(SOURCE / "unexpected"),
                lambda text: text.replace(first, "", 1),
                lambda text: text.replace(first, second, 1),
                lambda text: text.replace(first, "-Wp," + first, 1),
                lambda text: text.replace(first, "-Xpreprocessor " + first, 1),
            )
            for change in changes:
                with self.subTest(role=role, change=change), self.assertRaises(ValueError):
                    self.validate(change_role(fixture_stamps(), outer, inner, change))

    def test_input_types_format_jobs_and_paths_are_not_coerced(self):
        for options in ({"fmt": "tf32"}, {"jobs": True}, {"jobs": 1.0}, {"jobs": 3},
                        {"source": Path("relative")}, {"build": Path("/build/../other")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.validate(fixture_stamps(), **options)
        self.assertEqual(len(self.validate(fixture_stamps(), jobs=1)), 4)

    def test_old_contract_still_rejects_performance_instrumentation(self):
        with self.assertRaises(ValueError):
            legacy.validate_records(sample("simx_rt"),
                                    sample("simx_backend").rstrip() + " -DPERF_ENABLE\n",
                                    sample("application"), driver="simx", fmt="bf16",
                                    source=SOURCE, build=BUILD, jobs=2)

    def test_header_parser_rejects_duplicate_functional_and_nonmacro_rows(self):
        original = STAMP_SAMPLES["header"]
        expected = records.validate_header_macros(original)
        for text in (original + "\n#define VX_CFG_XLEN 64\n",
                     original + "\n#define SIMX_FUNCTIONAL 0\n",
                     original + "\n#define SIMX_FUNCTIONAL(x) x\n",
                     original + "\n#define PERF_ENABLE(x) x\n",
                     original + "\nnot a preprocessor record\n"):
            with self.subTest(extra=text[len(original):]), self.assertRaises(ValueError):
                records.validate_header_macros(text)
        for role in ("verilator", "", None):
            with self.subTest(role=role), self.assertRaises(ValueError):
                validate_effective_header(original, expected, role=role)


class GeneratedBenchmarkCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.make, cls.cpp = shutil.which("make"), shutil.which("g++")
        if not cls.make or not cls.cpp:
            raise unittest.SkipTest("make/g++ unavailable; actual generated stamps are not verified")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-p06-compilers-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.marker = cls.directory / "forbidden-compiler-used"
        guard = cls.directory / "forbidden-compiler"
        guard.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$P06_COMPILER_SENTINEL"\nexit 97\n')
        guard.chmod(0o700)
        cls.env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                   "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
                   "P06_COMPILER_SENTINEL": str(cls.marker)}
        cls.guard_options = [name + "=" + str(guard) for name in ("CC", "CXX", "VX_CC", "VX_CXX")]
        cls.generated = {}
        for fmt in ("fp16", "bf16"):
            build = cls.directory / fmt
            build.mkdir()
            cls.run_host([str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                          "--osversion=ubuntu/focal", "--tooldir=" + str(cls.directory / "unused-tools")], build)
            env = dict(cls.env, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1", PERF="1")
            runtime_dir = build / "sw/runtime"
            for relative, target in (("sw/runtime/simx", "simx_rt_config.stamp"),
                                     ("sim/simx", "simx_config.stamp")):
                cls.run_host([cls.make, "--no-print-directory", "-s", "-j1", "-C", relative,
                              *cls.guard_options, "DESTDIR=" + str(runtime_dir), str(runtime_dir / target)],
                             build, env)
            runtime = (runtime_dir / "simx_rt_config.stamp").read_text()
            backend = (runtime_dir / "simx_config.stamp").read_text()
            applications = {}
            for kind in ("matmul", "mlp"):
                relative = "tests/regression/ai_bench_" + kind
                cls.run_host([cls.make, "--no-print-directory", "-s", "-j1", "--old-file=.depend",
                              "-C", relative, *cls.guard_options, "config.stamp"], build, env)
                applications[kind] = (build / relative / "config.stamp").read_text()
            baseline_text = cls.preprocess(build, ["-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64"])
            baseline = records.validate_header_macros(baseline_text)
            resolved = cls.run_host([sys.executable, str(ROOT / "ci/gen_config.py"),
                                    "--config=" + str(ROOT / "VX_config.toml"), "--profile=p02-tfr",
                                    "--xlen=64", "--format=cflags", "--cflags=" + env["CONFIGS"] +
                                    " -DVX_CFG_XLEN=64"], build)
            # The profile's explicit disabled selectors remain present in raw Make records.
            disabled = ["-D" + name + "_DISABLE" for name in legacy.DISABLED]
            expanded_text = cls.preprocess(build, shlex.split(resolved) + disabled)
            expected = records.validate_header_macros(expanded_text)
            backend_expected = dict(baseline, **{name + "_DISABLE": "1" for name in legacy.DISABLED})
            probe = build / HEADER_PROBE
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(HEADER_PROBE_CONTENT)
            cls.generated[fmt] = dict(build=build, runtime=runtime, backend=backend,
                                      applications=applications, baseline=baseline,
                                      expected=expected, backend_expected=backend_expected)

    @classmethod
    def run_host(cls, argv, cwd, env=None):
        process = subprocess.run(argv, cwd=cwd, env=cls.env if env is None else env,
                                 capture_output=True, text=True, timeout=30, check=False)
        if process.returncode:
            raise AssertionError("host stamp/preprocessor command failed: " +
                                 repr(argv) + "\n" + (process.stdout + process.stderr)[-4096:])
        if "Traceback (most recent call last)" in process.stderr or "Undefined key" in process.stderr:
            raise AssertionError("configuration command hid an error: " + process.stderr[-4096:])
        return process.stdout

    @classmethod
    def preprocess(cls, build, flags):
        return cls.run_host([cls.cpp, "-E", "-dM", "-x", "c++", *flags,
                             "-include", str(build / "sw/VX_config.h"), "/dev/null"], build)

    def validated(self, fmt, kind="matmul"):
        row = self.generated[fmt]
        return records.validate_records(row["runtime"], row["backend"], row["applications"][kind],
                                        fmt=fmt, source=ROOT, build=row["build"], jobs=1)

    def test_actual_make_stamps_and_every_effective_role_match_both_formats_and_apps(self):
        for fmt, row in self.generated.items():
            for kind in ("matmul", "mlp"):
                for record in self.validated(fmt, kind):
                    role = record["role"]
                    expected = row["backend_expected"] if role == "backend_cpp" else row["expected"]
                    argv, directory = effective_header_command(self.cpp, row["build"],
                        row["build"] / ("tests/regression/ai_bench_" + kind), record)
                    output = self.run_host([str(value) for value in argv], directory)
                    with self.subTest(fmt=fmt, application=kind, role=role):
                        result = validate_effective_header(output, expected, role=role)
                        self.assertEqual({key: value for key, value in result.items()
                                          if key.startswith("VX_CFG_")}, expected)
                        self.assertEqual("PERF_ENABLE" in result, role == "backend_cpp")

    def test_allowed_include_directory_shadow_is_observed_instead_of_forced_header(self):
        row = self.generated["fp16"]
        with tempfile.TemporaryDirectory(prefix="header-search-", dir=self.directory) as directory:
            source, build = Path(directory) / "source", Path(directory) / "build"
            (build / "sw").mkdir(parents=True)
            (build / "sw/VX_config.h").write_bytes((row["build"] / "sw/VX_config.h").read_bytes())
            probe = build / HEADER_PROBE
            probe.parent.mkdir(parents=True)
            probe.write_bytes(HEADER_PROBE_CONTENT)
            stamps = [text.replace(str(ROOT), str(source)).replace(str(row["build"]), str(build))
                      for text in (row["runtime"], row["backend"], row["applications"]["matmul"])]
            validated = records.validate_records(*stamps, fmt="fp16", source=source, build=build, jobs=1)
            for role, shadow in (("backend_cpp", source / "sim/simx/VX_config.h"),
                                 ("runtime", build / "sw/runtime/common/VX_config.h")):
                record = next(item for item in validated if item["role"] == role)
                expected = row["backend_expected"] if role == "backend_cpp" else row["expected"]
                argv, cwd = effective_header_command(self.cpp, build,
                    build / "tests/regression/ai_bench_matmul", record)
                cwd.mkdir(parents=True, exist_ok=True)
                shadow.parent.mkdir(parents=True, exist_ok=True)
                for addition in ("#define SIMX_FUNCTIONAL 0\n",
                                 "#undef VX_CFG_PLATFORM_MEMORY_LATENCY\n"
                                 "#define VX_CFG_PLATFORM_MEMORY_LATENCY 123\n"):
                    shadow.write_text('#include "' + str(build / "sw/VX_config.h") + '"\n' + addition)
                    output = self.run_host([str(value) for value in argv], cwd)
                    with self.subTest(role=role, addition=addition), self.assertRaises(ValueError):
                        validate_effective_header(output, expected, role=role)
                shadow.unlink()

    def test_expression_defaults_and_resolved_values_are_both_accepted(self):
        for fmt, row in self.generated.items():
            with self.subTest(fmt=fmt):
                self.assertEqual(row["baseline"]["VX_CFG_SIMD_WIDTH"], "VX_CFG_NUM_THREADS")
                self.assertEqual(row["expected"]["VX_CFG_SIMD_WIDTH"], "4")
                self.assertNotEqual(row["baseline"]["VX_CFG_LMEM_SIZE"], row["expected"]["VX_CFG_LMEM_SIZE"])
                self.assertEqual(row["expected"]["VX_CFG_LMEM_SIZE"], "16384")

    def test_unlisted_latency_cache_and_new_hardware_macros_cannot_bypass_complete_map(self):
        changes = (("VX_CFG_PLATFORM_MEMORY_LATENCY", "123"),
                   ("VX_CFG_ICACHE_MSHR_SIZE", "31"), ("VX_CFG_UNREVIEWED_OPTION", "1"))
        row = self.generated["bf16"]
        for record in self.validated("bf16"):
            role = record["role"]
            expected = row["backend_expected"] if role == "backend_cpp" else row["expected"]
            for name, value in changes:
                flags = [flag for flag in record["macro_flags"]
                         if not re.fullmatch(r"-D" + name + r"(?:=.*)?", flag)]
                output = self.preprocess(row["build"], flags + ["-D" + name + "=" + value])
                # These intentionally pass the short scalar checklist: complete-map binding is necessary.
                observed = records.validate_header_macros(output, performance=role == "backend_cpp")
                self.assertEqual(observed[name], value)
                with self.subTest(role=role, macro=name), self.assertRaisesRegex(ValueError, "independently generated profile"):
                    validate_effective_header(output, expected, role=role)

    def test_role_header_performance_cannot_be_dropped_added_or_functional(self):
        row = self.generated["fp16"]
        for record in self.validated("fp16"):
            role = record["role"]
            expected = row["backend_expected"] if role == "backend_cpp" else row["expected"]
            perf = [flag for flag in record["macro_flags"] if not flag.startswith("-DPERF_ENABLE")]
            if role != "backend_cpp":
                perf.append("-DPERF_ENABLE")
            for flags in (perf, record["macro_flags"] + ["-DSIMX_FUNCTIONAL=0"],
                          record["macro_flags"] + ["-DSIMX_MT=0"]):
                output = self.preprocess(row["build"], flags)
                with self.subTest(role=role, flags=flags[-1:]), self.assertRaises(ValueError):
                    validate_effective_header(output, expected, role=role)

    def test_stamp_generation_never_invokes_a_compiler_or_creates_native_binaries(self):
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.directory / "unused-tools").exists())
        for row in self.generated.values():
            for relative in ("sw/runtime/libsimx.so", "sw/runtime/libvortex.so",
                             "tests/regression/ai_bench_matmul/ai_bench_matmul",
                             "tests/regression/ai_bench_matmul/kernel.elf",
                             "tests/regression/ai_bench_mlp/ai_bench_mlp",
                             "tests/regression/ai_bench_mlp/kernel.vxbin"):
                with self.subTest(relative=relative):
                    self.assertFalse((row["build"] / relative).exists())


if __name__ == "__main__":
    unittest.main()
