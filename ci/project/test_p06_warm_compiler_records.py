# SPDX-License-Identifier: Apache-2.0
"""Mutate freshly generated warm records; execute only host preprocessing.

Compiler guards prevent native backend/kernel builds. No simulator, GPU kernel,
archived command, or retained compiler text is executed by a validator.
"""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import unittest

from baseline_packet_contract import _stamp_flags
from p02_matrix_records import DISABLED
import p06_warm_compiler_records as records
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
APP = "tests/regression/ai_warm_workspace"
ROLES = ((0, 0, "runtime"), (1, 0, "backend_cpp"), (2, 0, "kernel"), (2, 1, "host"))
WRAPPERS = ("-Wl,--wrap=vx_buffer_create", "-Wl,--wrap=vx_buffer_release",
            "-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release")


def change_role(stamps, outer, inner, change):
    result = list(stamps)
    lines = result[outer].splitlines()
    lines[inner] = change(lines[inner])
    result[outer] = "\n".join(lines) + "\n"
    return tuple(result)


def replace_define(text, name, value=None):
    replacement = "" if value is None else "-D" + name + "=" + value
    return re.sub(r"(?<!\S)-D" + re.escape(name) + r"(?:=[^\s]+)?(?=\s|$)", replacement, text)


def hardware_macros(text):
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*))?", line)
        if match and (match[1].startswith("VX_CFG_") or match[1] == "PERF_ENABLE"):
            if match[1] in result:
                raise AssertionError("Host preprocessor repeated a hardware macro")
            result[match[1]] = match[2] or "1"
    return result


class WarmCompilerRecordTests(unittest.TestCase):
    rejection_checks = 0

    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        cls.make = shutil.which("make")
        if not cls.compiler or not cls.make:
            raise AssertionError("Warm compiler tests require make and a C++17 host preprocessor")
        temporary = tempfile.TemporaryDirectory(prefix="p06-warm-compiler-", dir=ROOT.parent)
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.guard_marker = cls.directory / "forbidden-compiler-used"
        guard = cls.directory / "compiler-guard"
        guard.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$P06_WARM_COMPILER_GUARD"\nexit 97\n')
        guard.chmod(0o700)
        cls.environment = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
            "LANG": "C", "LC_ALL": "C", "TMPDIR": str(cls.directory),
            "PYTHONDONTWRITEBYTECODE": "1", "MAKEFLAGS": "-j1", "THREADS": "1",
            "CCACHE_DISABLE": "1", "OBJCACHE": "", "P06_WARM_COMPILER_GUARD": str(cls.guard_marker),
        }
        names = (
            "configure", "Makefile.in", "config.mk.in", "VERSION", "VX_config.toml", "VX_types.toml",
            "profiles/p02-tfr.json", "ci/gen_config.py", "sw/runtime/common.mk",
            "sw/runtime/simx/Makefile", "sim/common.mk", "sim/simx/Makefile",
            "tests/regression/common.mk", APP + "/Makefile",
            "ci/project/p06_warm_compiler_records.py", "ci/project/p06_workspace_compiler_records.py",
            "ci/project/p06_compiler_records.py", "ci/project/compiler_records.py",
            "ci/project/baseline_packet_contract.py", "ci/project/p02_matrix_records.py",
        )
        cls.source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
        guard_options = [name + "=" + str(guard) for name in ("CC", "CXX", "VX_CC", "VX_CXX")]
        cls.generated = {}
        for fmt in ("fp16", "bf16"):
            build = cls.directory / fmt
            build.mkdir()
            cls.host([str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                      "--osversion=ubuntu/focal", "--tooldir=" + str(cls.directory / "unused-tools")], build)
            current = dict(cls.environment, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1", PERF="1")
            runtime = build / "sw/runtime"
            for relative, target in (("sw/runtime/simx", "simx_rt_config.stamp"),
                                     ("sim/simx", "simx_config.stamp")):
                cls.host([cls.make, "--no-print-directory", "-s", "-j1", "-C", relative,
                          *guard_options, "DESTDIR=" + str(runtime), str(runtime / target)], build, current)
            cls.host([cls.make, "--no-print-directory", "-s", "-j1", "--old-file=.depend",
                      "-C", APP, *guard_options, "config.stamp"], build, current)
            stamps = ((runtime / "simx_rt_config.stamp").read_text(),
                      (runtime / "simx_config.stamp").read_text(),
                      (build / APP / "config.stamp").read_text())
            if cls.guard_marker.exists():
                raise AssertionError("Generating records invoked a forbidden native compiler")
            flags = cls.host([sys.executable, str(ROOT / "ci/gen_config.py"),
                "--config=" + str(ROOT / "VX_config.toml"), "--profile=p02-tfr", "--xlen=64",
                "--format=cflags", f"--cflags=-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1 -DVX_CFG_XLEN=64"], build)
            expanded = cls.host([cls.compiler, "-E", "-dM", "-x", "c++",
                *shlex.split(flags), *("-D" + name + "_DISABLE" for name in DISABLED),
                "-include", str(build / "sw/VX_config.h"), "/dev/null"], build)
            base = cls.host([cls.compiler, "-E", "-dM", "-x", "c++",
                "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", "-include", str(build / "sw/VX_config.h"),
                "/dev/null"], build)
            expected = {role: hardware_macros(expanded) for _, _, role in ROLES}
            expected["backend_cpp"] = dict(hardware_macros(base), PERF_ENABLE="1",
                                            **{name + "_DISABLE": "1" for name in DISABLED})
            probe = build / "warm-compiler-include-probe.cpp"
            probe.write_text("#include <VX_config.h>\n")
            directories = {"runtime": build / "sw/runtime/simx", "backend_cpp": build / "sim/simx",
                           "kernel": build / APP, "host": build / APP}
            headers = {}
            for outer, inner, role in ROLES:
                original = stamps[outer].splitlines()[inner]
                includes = [word for word in shlex.split(original) if word.startswith("-I")]
                headers[role] = cls.host([cls.compiler, "-E", "-dM", "-x", "c++",
                    *_stamp_flags(original, "untouched generated " + role), *includes, str(probe)],
                    directories[role])
            cls.generated[fmt] = {"build": build, "stamps": stamps, "headers": headers,
                                  "expected": expected}

    @classmethod
    def host(cls, argv, cwd, environment=None):
        return run_host_command(argv, cwd=cwd, env=environment or cls.environment, timeout=30)

    def tearDown(self):
        self.assertFalse(self.guard_marker.exists(), "Record generation invoked a native compiler")
        for name, digest in self.source_hashes.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)

    def validate(self, stamps=None, *, fmt="fp16", **options):
        selected = self.generated[fmt]
        arguments = dict(driver="simx", fmt=fmt, source=ROOT, build=selected["build"], jobs=1)
        arguments.update(options)
        return records.validate_records(*(selected["stamps"] if stamps is None else stamps), **arguments)

    def reject(self, stamps=None, **options):
        type(self).rejection_checks += 1
        with self.assertRaises((ValueError, TypeError)):
            self.validate(stamps, **options)

    def reject_header(self, text, *, role="runtime", expected=None, **options):
        type(self).rejection_checks += 1
        arguments = dict(driver="simx", role=role)
        arguments.update(options)
        if expected is None:
            expected = self.generated["fp16"]["expected"][role]
        with self.assertRaises((ValueError, TypeError)):
            records.validate_effective_header(text, expected, **arguments)

    def test_untouched_generated_records_bind_each_original_role_and_format(self):
        for fmt, generated in self.generated.items():
            original = generated["stamps"]
            for jobs in (1, 2):
                with self.subTest(fmt=fmt, jobs=jobs):
                    result = self.validate(fmt=fmt, jobs=jobs)
                    self.assertEqual([row["role"] for row in result], [role for _, _, role in ROLES])
                    for row, (outer, inner, role) in zip(result, ROLES):
                        text = original[outer].splitlines()[inner]
                        self.assertEqual(row["sha256"], hashlib.sha256(text.encode()).hexdigest())
                        self.assertEqual(row["configuration"]["ITYPE"], fmt)
                        self.assertEqual(row["configuration"]["OTYPE"], "fp32")
                        self.assertEqual(row["configuration"]["VX_CFG_TCU_TYPE"], "TFR")
                        self.assertEqual(row["configuration"]["VX_CFG_FPU_TYPE"], "STD")
                        self.assertEqual("PERF_ENABLE" in row["configuration"], role == "backend_cpp")
                    self.assertEqual(generated["stamps"], original)
            self.assertEqual(shlex.split(original[2].splitlines()[2]),
                             [*WRAPPERS, "-L" + str(generated["build"] / "sw/runtime"), "-lvortex"])

    def test_all_eight_real_effective_headers_match_independent_generated_expectations(self):
        for fmt, generated in self.generated.items():
            for _, _, role in ROLES:
                with self.subTest(fmt=fmt, role=role):
                    actual = records.validate_effective_header(generated["headers"][role],
                        generated["expected"][role], driver="simx", role=role)
                    self.assertEqual(actual, generated["expected"][role])
                    self.assertEqual(actual.get("PERF_ENABLE"), "1" if role == "backend_cpp" else None)

    def test_each_role_independently_requires_profile_dtype_geometry_and_native_selectors(self):
        required = ("VX_PROFILE", "ITYPE", "OTYPE", "KUNROLL", "NDEBUG", "VX_CFG_XLEN",
                    "VX_CFG_XLEN_64", "VX_CFG_NUM_THREADS", "VX_CFG_TCU_TYPE", "VX_CFG_FPU_TYPE",
                    "VX_CFG_TCU_TYPE_TFR", "VX_CFG_FPU_TYPE_STD")
        for outer, inner, role in ROLES:
            for name in required:
                with self.subTest(role=role, macro=name):
                    self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner,
                                            lambda text: replace_define(text, name)))

    def test_conflicting_and_unsupported_macros_cannot_be_hidden_in_other_roles(self):
        flags = ("-DVX_CFG_XLEN=32", "-DITYPE=bf16", "-DOTYPE=fp16", "-DKUNROLL=2",
                 "-DVX_PROFILE=other", "-DNDEBUG=0", "-DVX_CFG_TCU_TYPE_DPI=0",
                 "-DVX_CFG_FPU_TYPE_DSP=0", "-DVX_CFG_XLEN_32=0", "-DVX_CFG_UNKNOWN=1",
                 "-DVX_CFG_EXT_A_ENABLE=0", "-DVX_CFG_TCU_FP8_ENABLE=0", "-DUNBOUND_OPTION=1")
        for outer, inner, role in ROLES:
            for flag in flags:
                with self.subTest(role=role, flag=flag):
                    self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner,
                                            lambda text: text + " " + flag))

    def test_performance_selector_is_required_once_and_only_in_the_backend(self):
        original = self.generated["fp16"]["stamps"]
        for value in (None, "0", "2", ""):
            with self.subTest(backend_value=value):
                self.reject(change_role(original, 1, 0, lambda text: replace_define(text, "PERF_ENABLE", value)))
        for suffix in (" -DPERF_ENABLE", " -DPERF_ENABLE=1", " -D PERF_ENABLE=1",
                       " -Wp,-DPERF_ENABLE=1", " -Xpreprocessor -DPERF_ENABLE=1"):
            with self.subTest(duplicate=suffix):
                self.reject(change_role(original, 1, 0, lambda text: text + suffix))
        for outer, inner, role in ROLES:
            if role == "backend_cpp":
                continue
            for flag in ("-DPERF_ENABLE", "-DPERF_ENABLE=0", "-DPERF_ENABLE=1"):
                with self.subTest(role=role, leak=flag):
                    self.reject(change_role(original, outer, inner, lambda text: text + " " + flag))

    def test_identical_nonperformance_definitions_preserve_semantics_but_change_record_hash(self):
        original = self.generated["fp16"]["stamps"]
        for outer, inner, role in ROLES:
            with self.subTest(role=role):
                changed = change_role(original, outer, inner, lambda text: text + " -DITYPE=fp16")
                before, after = self.validate(original), self.validate(changed)
                index = [item[2] for item in ROLES].index(role)
                self.assertEqual(before[index]["configuration"], after[index]["configuration"])
                self.assertNotEqual(before[index]["sha256"], after[index]["sha256"])

    def test_debug_functional_concurrency_and_backend_changes_fail_in_every_role(self):
        flags = ("-DDEBUG=0", "-DVCD_OUTPUT=0", "-DSAIF_OUTPUT=0", "-DTRACING_ALL=0",
                 "-DDBG_TRACE_CORE=0", "-DSIMX_FUNCTIONAL=0", "-DSIMX_MT=0", "-DWGMMA_TEST=0",
                 "-DXRTSIM=0", "-DUSE_SST=0", "-DUSE_GEM5=0", "-DSIMULATION=0", "-DSV_DPI=0")
        for outer, inner, role in ROLES:
            for flag in flags:
                with self.subTest(role=role, flag=flag):
                    self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner,
                                            lambda text: text + " " + flag))

    def test_expanded_and_sparse_derived_configuration_changes_are_rejected(self):
        changes = {"VX_CFG_NUM_THREADS": "8", "VX_CFG_NUM_CORES": "2", "VX_CFG_MEM_BLOCK_SIZE": "128",
                   "VX_CFG_DCACHE_WRITEBACK": "0", "VX_CFG_TCU_LATENCY": "5",
                   "VX_CFG_FPU_TYPE": "DPI", "VX_CFG_TCU_TYPE": "DPI", "VX_CFG_NUM_TCU_BLOCKS": "2",
                   "VX_CFG_MEM_ADDR_WIDTH": "32", "VX_CFG_FLEN": "32",
                   "VX_DBG_STALL_TIMEOUT": "1", "VX_DBG_DEBUG_LEVEL": "4"}
        for outer, inner, role in ROLES:
            for name, value in changes.items():
                def mutation(text):
                    if re.search(r"(?<!\S)-D" + name + r"(?:=|\s|$)", text):
                        return replace_define(text, name, value)
                    return text + " -D" + name + "=" + value
                with self.subTest(role=role, macro=name):
                    self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner, mutation))

    def test_required_warning_optimization_standard_and_kernel_abi_options_cannot_weaken(self):
        common = ("-Wall", "-Wextra", "-Wfatal-errors", "-Werror")
        required = {
            "runtime": (*common, "-std=c++17", "-fPIC", "-O2"),
            "backend_cpp": (*common, "-std=c++17", "-fPIC", "-O2", "-MMD", "-MP"),
            "kernel": (*common, "-march=rv64imafd", "-mabi=lp64d", "-O3", "-mcmodel=medany",
                       "-fno-rtti", "-fno-exceptions", "-nostartfiles", "-nostdlib",
                       "-fdata-sections", "-ffunction-sections", "-Wno-unused-command-line-argument"),
            "host": (*common, "-std=c++17", "-pedantic", "-O2"),
        }
        for outer, inner, role in ROLES:
            for flag in required[role]:
                for mutation in (lambda words, flag=flag: [word for word in words if word != flag],
                                 lambda words, flag=flag: [*words, flag]):
                    with self.subTest(role=role, option=flag, mutation=mutation):
                        self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner,
                            lambda text: " ".join(mutation(shlex.split(text)))))
            for flag in ("-O0", "-Ofast", "-ffast-math", "-funsafe-math-optimizations", "-g",
                         "-std=c++11", "-Wno-error", "-march=rv32imafd", "-mabi=lp64"):
                with self.subTest(role=role, added=flag):
                    self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner,
                                            lambda text: text + " " + flag))

    def test_each_include_order_and_path_is_bound_to_its_role(self):
        original = self.generated["fp16"]["stamps"]
        for outer, inner, role in ROLES:
            text = original[outer].splitlines()[inner]
            includes = [word for word in shlex.split(text) if word.startswith("-I")]
            first, second = includes[:2]
            mutations = (
                lambda line: line.replace(first, "", 1),
                lambda line: line + " " + first,
                lambda line: line.replace(first, second, 1),
                lambda line: line.replace(first, "@FIRST@", 1).replace(second, first, 1).replace("@FIRST@", second),
                lambda line: line.replace(first, "-I" + str(ROOT / "../shadow"), 1),
                lambda line: line.replace(first, "-I/other/source", 1),
                lambda line: line.replace(first, "-Wp," + first, 1),
                lambda line: line.replace(first, "-Xpreprocessor " + first, 1),
                lambda line: "-I/override " + line,
            )
            for index, mutation in enumerate(mutations):
                with self.subTest(role=role, mutation=index):
                    self.reject(change_role(original, outer, inner, mutation))

    def test_backend_dependency_record_target_is_required_once_and_exact(self):
        original = self.generated["fp16"]["stamps"]
        target = str(self.generated["fp16"]["build"] / "sw/runtime/simx_config.stamp")
        for mutate in (lambda line: line.replace("-MF " + target, "", 1),
                       lambda line: line.replace(target, target + ".other", 1),
                       lambda line: line + " -MF " + target,
                       lambda line: line.replace("-MF " + target, "-MF", 1)):
            self.reject(change_role(original, 1, 0, mutate))

    def test_forwarded_flags_cannot_inject_alternate_macros_options_or_include_inputs(self):
        flags = ("-D SIMX_FUNCTIONAL=0", "--define-macro=SIMX_FUNCTIONAL=0",
                 "--define-macro SIMX_FUNCTIONAL=0", "-Wp,-DSIMX_FUNCTIONAL=0",
                 "-Xpreprocessor -DSIMX_FUNCTIONAL=0", "-Wp,-U,VX_CFG_NUM_THREADS",
                 "-Xpreprocessor -UVX_CFG_NUM_THREADS", "-Wp,-I/unretained", "-Wp,-Ofast",
                 "-Xpreprocessor -ffast-math", "-Xclang -ffast-math", "-Xlinker --wrap=vx_start",
                 "-Wp,-include,/unretained/header", "-Xpreprocessor -include -Xpreprocessor /unretained/header")
        for outer, inner, role in ROLES:
            for flag in flags:
                with self.subTest(role=role, flag=flag):
                    self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner,
                                            lambda text: text + " " + flag))

    def test_shell_response_file_and_unretained_inputs_remain_unexecuted_and_rejected(self):
        sentinel = self.directory / "injected-command-executed"
        flags = ("$(touch " + str(sentinel) + ")", "`touch " + str(sentinel) + "`",
                 ";touch " + str(sentinel), "@unretained.rsp", "-include /unretained/header",
                 "-imacros /unretained/header", "-isystem /unretained/include", "-D", "-I",
                 "-Xpreprocessor", "-Wp,", "unbound-source.cpp", "-o /unbound/output")
        for outer, inner, role in ROLES:
            for flag in flags:
                with self.subTest(role=role, flag=flag):
                    self.reject(change_role(self.generated["fp16"]["stamps"], outer, inner,
                                            lambda text: text + " " + flag))
                    self.assertFalse(sentinel.exists())

    def test_linker_requires_exact_four_wrappers_order_and_runtime_library(self):
        original = self.generated["fp16"]["stamps"]
        valid = shlex.split(original[2].splitlines()[2])
        alternatives = [list(reversed(valid)), [*reversed(valid[:4]), *valid[4:]],
                        valid + ["-lm"], valid + ["-Wl,--wrap=vx_start"], valid + ["-lvortex"],
                        [*valid[:4], "-L/unbound/runtime", "-lvortex"],
                        [*valid[:4], valid[4] + "/../runtime", "-lvortex"],
                        [*valid[:-1], "-lvortex_fake"], [*valid[:4], "@linker-options"]]
        for index in range(4):
            alternatives.extend((valid[:index] + valid[index + 1:], valid + [valid[index]]))
        for index, words in enumerate(alternatives):
            with self.subTest(mutation=index):
                self.reject(change_role(original, 2, 2, lambda _: " ".join(words)))

    def test_missing_extra_and_reordered_original_records_are_rejected(self):
        original = self.generated["fp16"]["stamps"]
        for index in range(3):
            lines = original[index].splitlines()
            for replacement in ("", "\n".join(lines[1:]), original[index] + lines[0] + "\n"):
                changed = list(original)
                changed[index] = replacement
                with self.subTest(stamp=index, replacement=replacement[:24]):
                    self.reject(changed)
        self.reject((original[1], original[0], original[2]))
        self.reject(change_role(change_role(original, 2, 0, lambda _: original[2].splitlines()[1]),
                                2, 1, lambda _: original[2].splitlines()[0]))

    def test_invalid_argument_types_backend_format_job_budget_and_root_bindings_are_rejected(self):
        for name, values in (("driver", ("rtlsim", "xrt", "SIMX", True, None)),
                             ("jobs", (0, 3, -1, True, 1.0, "1", None)),
                             ("source", ("relative", ROOT / "../AI-GPU", "/wrong-source")),
                             ("build", ("relative", self.directory / "fp16/../fp16", "/wrong-build"))):
            for value in values:
                with self.subTest(argument=name, value=value):
                    self.reject(**{name: value})
        selected = self.generated["fp16"]
        for fmt in ("fp32", "FP16", True, None, 1):
            with self.subTest(fmt=fmt), self.assertRaises((ValueError, TypeError)):
                records.validate_records(*selected["stamps"], fmt=fmt, source=ROOT,
                                         build=selected["build"], jobs=1)
        self.reject(self.generated["bf16"]["stamps"])

    def test_compiler_records_reject_controls_nontext_and_byte_overflow(self):
        original = self.generated["fp16"]["stamps"]
        for index in range(3):
            for value in (None, b"flags", 1, [], "\ud800", "x" * (1024 * 1024 + 1)):
                changed = list(original)
                changed[index] = value
                with self.subTest(stamp=index, type=type(value).__name__):
                    self.reject(changed)
            for char in ("\0", "\r", "\v", "\f", "\x1b", "\x7f", "\x85", "\xa0", "\u2028", "\u2029"):
                changed = list(original)
                changed[index] += char
                with self.subTest(stamp=index, control=repr(char)):
                    self.reject(changed)

    def test_effective_headers_reject_wrong_or_repeated_counter_selectors(self):
        generated = self.generated["fp16"]
        for _, _, role in ROLES:
            text = generated["headers"][role]
            if role == "backend_cpp":
                for replacement in ("", "#define PERF_ENABLE 0", "#define PERF_ENABLE 2"):
                    self.reject_header(text.replace("#define PERF_ENABLE 1", replacement), role=role)
            else:
                self.reject_header(text + "\n#define PERF_ENABLE 1\n", role=role)
            self.reject_header(text + "\n#define PERF_ENABLE 1\n#define PERF_ENABLE 1\n", role=role)

    def test_effective_headers_reject_mode_arithmetic_and_configuration_drift(self):
        generated = self.generated["fp16"]
        additions = ("SIMX_FUNCTIONAL 0", "SIMX_MT 0", "DEBUG 0", "TRACING_ALL 0",
                     "VCD_OUTPUT 0", "XRTSIM 0", "VX_CFG_TCU_TYPE_DPI 0", "VX_CFG_FPU_TYPE_DSP 0",
                     "VX_CFG_UNKNOWN 1", "VX_CFG_EXT_A_ENABLE 0", "__FAST_MATH__ 1")
        for _, _, role in ROLES:
            text = generated["headers"][role]
            for definition in additions:
                with self.subTest(role=role, definition=definition):
                    self.reject_header(text + "\n#define " + definition + "\n", role=role)
            for name in ("VX_CFG_NUM_THREADS", "VX_CFG_TCU_TYPE_TFR", "VX_CFG_FPU_TYPE_STD",
                         "VX_CFG_XLEN_64", "VX_CFG_DCACHE_ENABLE", "VX_CFG_MEM_BLOCK_SIZE"):
                changed = re.sub(r"^#define " + name + r"(?:[ \t].*)?\n", "", text, flags=re.MULTILINE)
                self.assertNotEqual(changed, text)
                self.reject_header(changed, role=role)

    def test_effective_headers_require_the_expected_inventory_and_supported_role(self):
        text = self.generated["fp16"]["headers"]["runtime"]
        expected = self.generated["fp16"]["expected"]["runtime"]
        for value in ([], "macros", 1, True, dict(expected, VX_CFG_NUM_THREADS="8"),
                      {name: item for name, item in expected.items() if name != "VX_CFG_XLEN"}):
            with self.subTest(expected=type(value).__name__):
                self.reject_header(text, expected=value)
        for role in ("verilator", "linker", "unknown", None, True):
            with self.subTest(role=role):
                self.reject_header(text, role=role, expected=expected)
        for driver in ("rtlsim", "xrt", None, True):
            with self.subTest(driver=driver):
                self.reject_header(text, expected=expected, driver=driver)

    def test_effective_header_text_requires_bounded_unique_macro_only_records(self):
        text = self.generated["fp16"]["headers"]["runtime"]
        changes = (None, b"macros", 1, [], "x" * (1024 * 1024 + 1), "\ud800",
                   text + "\nFAILED!\n", text + "\n#include <unretained.h>\n",
                   text + "\n#define VX_CFG_XLEN 64\n", text + "\n#define VX_CFG_NUM_THREADS(x) 4\n",
                   text + "".join("#define UNRELATED_" + str(index) + " 1\n" for index in range(8193)))
        for index, changed in enumerate(changes):
            with self.subTest(mutation=index):
                self.reject_header(changed)
        for char in ("\0", "\r", "\v", "\x85", "\u2028"):
            self.reject_header(text + char)


if __name__ == "__main__":
    unittest.main()
