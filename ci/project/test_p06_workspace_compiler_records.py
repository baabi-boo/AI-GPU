# SPDX-License-Identifier: Apache-2.0
"""Independent retained-stamp mutations only; no compiler or GPU is executed."""

from copy import deepcopy
import hashlib
from pathlib import Path
import re
import shlex
import unittest

import p06_workspace_compiler_records as records
from p06_workspace_test_samples import (
    BUILD, COMPILER_ROLES, FORMATS, SOURCE, WRAPPERS, change_role, compiler_stamps,
)


def replace_define(text, name, value=None):
    replacement = "" if value is None else "-D" + name + "=" + value
    return re.sub(r"(?<!\S)-D" + re.escape(name) + r"(?:=[^\s]+)?(?=\s|$)", replacement, text)


class WorkspaceCompilerRecordTests(unittest.TestCase):
    rejection_checks = 0

    def validate(self, stamps=None, *, driver="simx", fmt="bf16", **options):
        if stamps is None:
            stamps = compiler_stamps()
        arguments = dict(driver=driver, fmt=fmt, source=SOURCE, build=BUILD, jobs=2)
        arguments.update(options)
        return records.validate_records(*stamps, **arguments)

    def reject(self, stamps, **options):
        type(self).rejection_checks += 1
        with self.assertRaises(ValueError):
            self.validate(stamps, **options)

    def test_every_original_role_hash_and_include_path_is_retained_for_both_backends_and_formats(self):
        for driver, roles in COMPILER_ROLES.items():
            for fmt in FORMATS:
                for jobs in (1, 2):
                    original = compiler_stamps(driver, fmt, jobs)
                    saved = deepcopy(original)
                    result = self.validate(original, driver=driver, fmt=fmt, jobs=jobs)
                    with self.subTest(driver=driver, fmt=fmt, jobs=jobs):
                        self.assertEqual([row["role"] for row in result], [role for _, _, role in roles])
                        self.assertEqual(original, saved)
                    for row, (outer, inner, role) in zip(result, roles):
                        with self.subTest(driver=driver, fmt=fmt, role=role):
                            text = original[outer].splitlines()[inner]
                            self.assertEqual(row["sha256"], hashlib.sha256(text.encode()).hexdigest())
                            self.assertEqual(row["configuration"]["ITYPE"], fmt)
                            self.assertEqual(row["configuration"]["OTYPE"], "fp32")
                            self.assertIn("-DVX_CFG_TCU_TYPE=TFR", row["macro_flags"])
                            self.assertTrue(row["include_paths"])

    def test_single_role_cannot_borrow_another_roles_required_configuration(self):
        required = ("VX_CFG_NUM_THREADS", "VX_CFG_XLEN_64", "VX_CFG_TCU_TYPE", "VX_CFG_FPU_TYPE",
                    "VX_PROFILE", "ITYPE", "OTYPE", "KUNROLL", "NDEBUG")
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for name in required:
                    changed = change_role(compiler_stamps(driver), outer, inner,
                                          lambda line: replace_define(line, name))
                    self.assertNotEqual(changed, compiler_stamps(driver))
                    with self.subTest(driver=driver, role=role, macro=name):
                        self.reject(changed, driver=driver)

    def test_native_arithmetic_selectors_cannot_be_removed_from_selecting_roles(self):
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                if driver == "rtlsim" and role == "backend_cpp":
                    continue
                for macro in ("VX_CFG_TCU_TYPE_TFR", "VX_CFG_FPU_TYPE_STD"):
                    changed = change_role(compiler_stamps(driver), outer, inner,
                                          lambda line: replace_define(line, macro))
                    with self.subTest(driver=driver, role=role, macro=macro):
                        self.reject(changed, driver=driver)

    def test_profile_format_geometry_and_native_enums_cannot_change_in_one_role(self):
        substitutions = {"VX_PROFILE": "other", "ITYPE": "fp16", "OTYPE": "fp16", "KUNROLL": "2",
                         "VX_CFG_XLEN": "32", "VX_CFG_NUM_CORES": "2", "VX_CFG_NUM_THREADS": "8",
                         "VX_CFG_TCU_LATENCY": "5", "VX_CFG_TCU_TYPE": "DPI", "VX_CFG_FPU_TYPE": "DPI"}
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for name, value in substitutions.items():
                    changed = change_role(compiler_stamps(driver), outer, inner,
                                          lambda line: replace_define(line, name, value))
                    with self.subTest(driver=driver, role=role, macro=name):
                        self.reject(changed, driver=driver)

    def test_isa_and_unknown_configuration_macros_are_rejected_in_each_role(self):
        flags = ("-DVX_CFG_EXT_C_ENABLE=0", "-DVX_CFG_EXT_A_ENABLE", "-DVX_CFG_EXT_F_DISABLE",
                 "-DVX_CFG_EXT_D_DISABLE", "-DVX_CFG_FLEN_32", "-DVX_CFG_EXT_ZICOND_DISABLE",
                 "-DVX_CFG_UNDECLARED_WORKSPACE_OPTION=1", "-DVX_CFG_FUTURE_OPTION_DISABLE=0")
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for flag in flags:
                    changed = change_role(compiler_stamps(driver), outer, inner, lambda line: line + " " + flag)
                    with self.subTest(driver=driver, role=role, flag=flag):
                        self.reject(changed, driver=driver)

    def test_derived_hardware_overrides_reject_in_expanded_and_sparse_roles(self):
        substitutions = {"VX_CFG_NUM_TCU_BLOCKS": "2", "VX_CFG_MEM_ADDR_WIDTH": "32",
                         "VX_CFG_FLEN": "32", "VX_CFG_DCACHE_WRITEBACK": "0",
                         "VX_CFG_NUM_FPU_LANES": "8", "VX_CFG_PLATFORM_MEMORY_NUM_BANKS": "4"}
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for name, value in substitutions.items():
                    def change(line):
                        if re.search(r"(?<!\S)-D" + name + r"(?:=|\s|$)", line):
                            return replace_define(line, name, value)
                        return line + " -D" + name + "=" + value
                    changed = change_role(compiler_stamps(driver), outer, inner, change)
                    with self.subTest(driver=driver, role=role, macro=name):
                        self.reject(changed, driver=driver)

    def test_dpi_arithmetic_disabled_feature_and_isa_flags_are_not_harmless_when_zero(self):
        flags = ("-DVX_CFG_TCU_TYPE_DPI=0", "-DVX_CFG_FPU_TYPE_DPI=0", "-DVX_CFG_FPU_TYPE_DSP=0",
                 "-DVX_CFG_XLEN_32=0", "-DVX_CFG_TCU_FP8_ENABLE=0", "-DVX_CFG_TCU_WGMMA_ENABLE=0",
                 "-DVX_CFG_EXT_LDST_MATRIX_ENABLE=0", "-DVX_CFG_TCU_FEDP2K=0",
                 "-march=rv32imafd", "-march=rv64imafdc", "-mabi=lp64", "-mabi=ilp32d")
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for flag in flags:
                    with self.subTest(driver=driver, role=role, flag=flag):
                        self.reject(change_role(compiler_stamps(driver), outer, inner,
                                                lambda line: line + " " + flag), driver=driver)

    def test_counters_traces_functional_concurrency_and_alternate_backends_fail_per_role(self):
        flags = ("-DPERF_ENABLE=0", "-DDEBUG=0", "-DVCD_OUTPUT=0", "-DSAIF_OUTPUT=0",
                 "-DTRACING_ALL=0", "-DDBG_TRACE_CORE=0", "-DSIMX_FUNCTIONAL=0", "-DSIMX_MT=0",
                 "-DWGMMA_TEST=0", "-DXRTSIM=0", "-DUSE_SST=0", "-DUSE_GEM5=0", "-DAXI_BUS=0")
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for flag in flags:
                    with self.subTest(driver=driver, role=role, flag=flag):
                        self.reject(change_role(compiler_stamps(driver), outer, inner,
                                                lambda line: line + " " + flag), driver=driver)

    def test_hostile_forwarded_flags_cannot_hide_behind_preprocessor_transports(self):
        flags = ("-D SIMX_FUNCTIONAL=0", "--define-macro SIMX_FUNCTIONAL=0",
                 "--define-macro=SIMX_FUNCTIONAL=0", "-Wp,-DSIMX_FUNCTIONAL=0",
                 "-Xpreprocessor -DSIMX_FUNCTIONAL=0", "-Wp,-U,VX_CFG_NUM_THREADS",
                 "-Xpreprocessor -UVX_CFG_NUM_THREADS", "-Wp,-include,/unbound/header",
                 "-Xpreprocessor -include -Xpreprocessor /unbound/header", "-Wp,-Ofast",
                 "-Xpreprocessor -ffast-math", "-Wp,-I/unbound/include", "-Wp,-isystem,/unbound/include",
                 "-Xclang -ffast-math", "-Xlinker --wrap=vx_start")
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for flag in flags:
                    with self.subTest(driver=driver, role=role, flag=flag):
                        self.reject(change_role(compiler_stamps(driver), outer, inner,
                                                lambda line: line + " " + flag), driver=driver)

    def test_shell_response_and_unretained_include_inputs_cannot_execute_or_change_flags(self):
        flags = ("$(touch never-execute)", "`touch never-execute`", ";touch never-execute",
                 "@unretained.rsp", "-include /unretained/header", "-imacros /unretained/header",
                 "-isystem /unretained/include", "-I/elsewhere", "-I" + str(SOURCE) + "/../outside",
                 "-D", "-I", "-Xpreprocessor", "-Wp,", "-DUNDECLARED_OPTION=1",
                 "-ffast-math", "-Ofast", "-fno-signed-zeros", "-funsafe-math-optimizations", "-g")
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for flag in flags:
                    with self.subTest(driver=driver, role=role, flag=flag):
                        self.reject(change_role(compiler_stamps(driver), outer, inner,
                                                lambda line: line + " " + flag), driver=driver)

    def test_each_role_requires_exact_include_order_and_inventory(self):
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                original = compiler_stamps(driver)
                words = shlex.split(original[outer].splitlines()[inner])
                includes = [word for word in words if word.startswith("-I")]
                self.assertGreaterEqual(len(includes), 2)
                first, second = includes[:2]
                mutations = (
                    lambda text: text.replace(first, "", 1),
                    lambda text: text + " " + first,
                    lambda text: text.replace(first, second, 1),
                    lambda text: text.replace(first, "@FIRST@", 1).replace(second, first, 1).replace("@FIRST@", second),
                    lambda text: text.replace(first, "-Wp," + first, 1),
                    lambda text: text.replace(first, "-Xpreprocessor " + first, 1),
                    lambda text: "-I" + str(BUILD / "shadow") + " " + text,
                )
                for index, mutate in enumerate(mutations):
                    with self.subTest(driver=driver, role=role, mutation=index):
                        self.reject(change_role(original, outer, inner, mutate), driver=driver)

    def test_memory_cache_and_diagnostic_configuration_cannot_change(self):
        flags = ("-DVX_CFG_MEM_BLOCK_SIZE=128", "-DVX_CFG_ICACHE_DISABLE=0",
                 "-DVX_CFG_DCACHE_ENABLE=0", "-DVX_CFG_L2_ENABLE=0", "-DVX_CFG_L3_ENABLE=0",
                 "-DVX_CFG_VM_ENABLE=0", "-DVX_CFG_LMEM_DISABLE=0",
                 "-DVX_DBG_STALL_TIMEOUT=1", "-DVX_DBG_DEBUG_LEVEL=4")
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                for flag in flags:
                    with self.subTest(driver=driver, role=role, flag=flag):
                        self.reject(change_role(compiler_stamps(driver), outer, inner,
                                                lambda line: line + " " + flag), driver=driver)

    def test_missing_repeated_changed_and_conflicting_compiler_options_fail(self):
        for driver, roles in COMPILER_ROLES.items():
            for outer, inner, role in roles:
                flag = "--assert" if role == "verilator" else "-Wall"
                changes = (lambda text: text.replace(flag, "", 1),
                           lambda text: text + " " + flag,
                           lambda text: text + " -O0",
                           lambda text: text + " -DNDEBUG=0")
                for index, change in enumerate(changes):
                    with self.subTest(driver=driver, role=role, mutation=index):
                        self.reject(change_role(compiler_stamps(driver), outer, inner, change), driver=driver)

    def test_verilator_exact_options_package_order_and_makeflags_are_preserved(self):
        text = compiler_stamps("rtlsim")[1].splitlines()[0]
        changes = {
            "jobs": text.replace("-j 2", "-j 3"),
            "assertions": text.replace("--assert", "--no-assert"),
            "initialization": text.replace("--x-initial unique", "--x-initial 0"),
            "makeflags_duplicate": text + " -MAKEFLAGS OPT_FAST=-O2",
            "makeflags_reordered": text.replace("OPT_FAST=-O2", "@TEMP@").replace("OPT_GLOBAL=-O2", "OPT_FAST=-O2").replace("@TEMP@", "OPT_GLOBAL=-O2"),
            "makeflags_override": text.replace("OPT_FAST=-O2", "OPT_FAST=-Ofast"),
            "package_order": text.replace("VX_gpu_pkg.sv", "@TEMP@").replace("VX_trace_pkg.sv", "VX_gpu_pkg.sv").replace("@TEMP@", "VX_trace_pkg.sv"),
            "top_module": text.replace("--top-module rtlsim_shim", "--top-module alternative"),
            "trace": text + " --trace",
        }
        for name, changed in changes.items():
            with self.subTest(mutation=name):
                self.reject(change_role(compiler_stamps("rtlsim"), 1, 0, lambda _: changed), driver="rtlsim")

    def test_simulation_macros_are_required_only_in_the_original_rtl_roles(self):
        for outer, inner, role in COMPILER_ROLES["rtlsim"]:
            for name in ("SIMULATION", "SV_DPI"):
                if role in ("verilator", "backend_cpp"):
                    changed = change_role(compiler_stamps("rtlsim"), outer, inner,
                                          lambda text: replace_define(text, name))
                else:
                    changed = change_role(compiler_stamps("rtlsim"), outer, inner,
                                          lambda text: text + " -D" + name)
                with self.subTest(role=role, macro=name):
                    self.reject(changed, driver="rtlsim")
        for outer, inner, role in COMPILER_ROLES["simx"]:
            with self.subTest(driver="simx", role=role):
                self.reject(change_role(compiler_stamps(), outer, inner,
                                        lambda text: text + " -DSIMULATION -DSV_DPI"))

    def test_wrappers_have_exact_order_count_and_runtime_library_binding(self):
        valid = [*WRAPPERS, "-L" + str(BUILD / "sw/runtime"), "-lvortex"]
        alternatives = [list(reversed(valid)), [*reversed(WRAPPERS), *valid[4:]],
                        valid + ["-lm"], valid + ["-Wl,--wrap=vx_start"], valid + ["-lvortex"],
                        [*WRAPPERS, "-L/unbound/runtime", "-lvortex"],
                        [*WRAPPERS, "-L" + str(BUILD / "sw/runtime/../runtime"), "-lvortex"],
                        [*WRAPPERS, "-L" + str(BUILD / "sw/runtime"), "-lvortex_fake"],
                        [*WRAPPERS, "@linker-options"]]
        for index in range(4):
            alternatives.extend((valid[:index] + valid[index + 1:], valid + [valid[index]],
                                 valid[:index] + ["-Wl,--wrap=vx_unknown"] + valid[index + 1:]))
        for driver in COMPILER_ROLES:
            for index, linker in enumerate(alternatives):
                changed = change_role(compiler_stamps(driver), 2, 2, lambda _: " ".join(linker))
                with self.subTest(driver=driver, mutation=index):
                    self.reject(changed, driver=driver)

    def test_separate_record_count_order_and_backend_identity_are_required(self):
        for driver in COMPILER_ROLES:
            original = compiler_stamps(driver)
            for outer in range(3):
                lines = original[outer].splitlines()
                for replacement in ("", "\n".join(lines[1:]), original[outer] + lines[0] + "\n"):
                    changed = list(original)
                    changed[outer] = replacement
                    with self.subTest(driver=driver, stamp=outer, mutation=replacement[:30]):
                        self.reject(changed, driver=driver)
            changed = list(original)
            application = changed[2].splitlines()
            changed[2] = "\n".join((application[1], application[0], application[2])) + "\n"
            self.reject(changed, driver=driver)
            wrong_driver = "rtlsim" if driver == "simx" else "simx"
            self.reject(compiler_stamps(wrong_driver), driver=driver)
        changed = compiler_stamps("rtlsim")
        changed[1] = "\n".join(reversed(changed[1].splitlines())) + "\n"
        self.reject(changed, driver="rtlsim")

    def test_backend_dependency_target_is_bound_to_original_build(self):
        needle = str(BUILD / "sw/runtime/simx_config.stamp")
        original = compiler_stamps()
        self.assertIn(needle, original[1])
        for replacement in ("/unbound/simx_config.stamp", needle + " -MF " + needle):
            with self.subTest(replacement=replacement):
                self.reject(change_role(original, 1, 0, lambda text: text.replace(needle, replacement)))

    def test_stamp_text_limits_control_characters_types_and_unicode_are_strict(self):
        for outer in range(3):
            for mutation in (lambda text: text.encode(), lambda text: None,
                             lambda text: text + "\x00", lambda text: text + "\x1b",
                             lambda text: text + "\u2028", lambda text: text + "\ud800",
                             lambda text: "x" * (1024 * 1024 + 1)):
                changed = compiler_stamps()
                changed[outer] = mutation(changed[outer])
                with self.subTest(stamp=outer, mutation=mutation):
                    self.reject(changed)

    def test_backend_format_jobs_and_absolute_source_build_bindings_are_strict(self):
        alternatives = ({"driver": "xrt"}, {"driver": True}, {"fmt": "tf32"}, {"fmt": 1},
                        {"jobs": True}, {"jobs": 1.0}, {"jobs": 0}, {"jobs": 3},
                        {"source": Path("relative")}, {"build": Path("relative")},
                        {"source": Path("/retained/../other")}, {"build": Path("/retained/../other")},
                        {"source": Path("/different-source")}, {"build": Path("/different-build")})
        for options in alternatives:
            with self.subTest(options=options):
                self.reject(compiler_stamps(), **options)


if __name__ == "__main__":
    unittest.main()
