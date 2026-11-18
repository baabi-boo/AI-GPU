# SPDX-License-Identifier: Apache-2.0
"""Frozen WGMMA LMEM capacity checks with real host preprocessing only.

The compiler records are synthetic transport fixtures. The generated-header
checks run the host preprocessor, without building or executing a processor.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import p02_wgmma_records as records
from test_p02_wgmma_matrix import (MANIFEST, ROOT, VARIANT, check_compiler,
                                   compiler_fixture, header_for)


CAPACITY_DEFINE = "#define VX_CFG_LMEM_SIZE __POW(2, VX_CFG_LMEM_LOG_SIZE)\n"
POW_DEFINE = "#define __POW(x,y) __vx_cfg_pow((x), (y))\n"


def record_roles(driver):
    roles = [(0, 0, "runtime"), (1, 0, "verilator" if driver == "rtlsim" else "backend_cpp")]
    if driver == "rtlsim":
        roles.append((1, 1, "backend_cpp"))
    return roles + [(2, 0, "kernel"), (2, 1, "host")]


def add_override(stamps, section, index, flag):
    result = stamps.copy()
    lines = result[section].splitlines()
    lines[index] += " " + flag
    result[section] = "\n".join(lines)
    return result


class LmemCompilerRecordTests(unittest.TestCase):
    def test_each_record_allows_omitted_or_exact_capacity(self):
        for driver in ("simx", "rtlsim"):
            original = compiler_fixture(driver)
            self.assertTrue(all("VX_CFG_LMEM_SIZE" not in row["configuration"]
                                for row in check_compiler(original, driver)))
            for section, index, role in record_roles(driver):
                stamps = add_override(original, section, index, "-DVX_CFG_LMEM_SIZE=16384")
                with self.subTest(driver=driver, role=role):
                    observed = check_compiler(stamps, driver)
                    selected = next(row for row in observed if row["role"] == role)
                    self.assertEqual(selected["configuration"]["VX_CFG_LMEM_SIZE"], "16384")

    def test_each_record_rejects_capacity_conflicting_with_frozen_16_kib(self):
        # 12288 still has clog2 == 14, so checking only the address window
        # cannot establish the required 16384-byte capacity.
        for driver in ("simx", "rtlsim"):
            original = compiler_fixture(driver)
            for section, index, role in record_roles(driver):
                for capacity in ("12288", "8192", "32768"):
                    stamps = add_override(original, section, index,
                                          "-DVX_CFG_LMEM_SIZE=" + capacity)
                    with self.subTest(driver=driver, role=role, capacity=capacity), \
                            self.assertRaisesRegex(ValueError, role + ".*VX_CFG_LMEM_SIZE"):
                        check_compiler(stamps, driver)

    def test_each_record_rejects_derived_capacity_helper_overrides(self):
        for driver in ("simx", "rtlsim"):
            original = compiler_fixture(driver)
            for section, index, role in record_roles(driver):
                for flag in ("-D__POW=other_pow", "-D__vx_cfg_pow=other_pow"):
                    stamps = add_override(original, section, index, flag)
                    with self.subTest(driver=driver, role=role, flag=flag), \
                            self.assertRaisesRegex(ValueError, role + ".*VX_CFG_LMEM_SIZE helper"):
                        check_compiler(stamps, driver)


class LmemEffectiveHeaderTests(unittest.TestCase):
    def test_canonical_expression_and_resolved_capacity_accept(self):
        generated = header_for(VARIANT)
        self.assertEqual(records.validate_header_macros(generated, VARIANT)["VX_CFG_LMEM_SIZE"],
                         "__POW(2, VX_CFG_LMEM_LOG_SIZE)")
        resolved = generated.replace(CAPACITY_DEFINE, "#define VX_CFG_LMEM_SIZE 16384\n")
        resolved = resolved.replace(POW_DEFINE, "")
        self.assertEqual(records.validate_header_macros(resolved, VARIANT)["VX_CFG_LMEM_SIZE"],
                         "16384")

    def test_missing_or_conflicting_effective_capacity_rejects(self):
        generated = header_for(VARIANT)
        for value in (None, "12288", "8192", "32768", "__POW(2, 13)",
                      "__POW(3, VX_CFG_LMEM_LOG_SIZE)", "OTHER_CAPACITY"):
            replacement = "" if value is None else "#define VX_CFG_LMEM_SIZE " + value + "\n"
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "VX_CFG_LMEM_SIZE"):
                records.validate_header_macros(generated.replace(CAPACITY_DEFINE, replacement), VARIANT)

    def test_derived_capacity_requires_frozen_address_window(self):
        for size in ("13", "15"):
            mutated = header_for(VARIANT).replace("#define VX_CFG_LMEM_LOG_SIZE 14\n",
                                                 "#define VX_CFG_LMEM_LOG_SIZE " + size + "\n")
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "VX_CFG_LMEM_LOG_SIZE"):
                records.validate_header_macros(mutated, VARIANT)

    def test_derived_capacity_binds_the_exact_generated_helper(self):
        generated = header_for(VARIANT)
        replacements = ("", "#define __POW(x,y) 12288\n", "#define __POW other_pow\n",
                        "#define __POW (x,y) __vx_cfg_pow((x), (y))\n",
                        "#define __POW(x,y) __vx_cfg_pow((x), 13)\n")
        for replacement in replacements:
            with self.subTest(replacement=replacement), \
                    self.assertRaisesRegex(ValueError, "VX_CFG_LMEM_SIZE helper"):
                records.validate_header_macros(generated.replace(POW_DEFINE, replacement), VARIANT)
        for shadow in ("#define __vx_cfg_pow other_pow\n", "#define __vx_cfg_pow(x,y) 12288\n"):
            with self.subTest(shadow=shadow), self.assertRaisesRegex(ValueError, "VX_CFG_LMEM_SIZE helper"):
                records.validate_header_macros(generated + shadow, VARIANT)

    def test_repeated_function_or_object_helper_definitions_reject(self):
        for duplicate in (POW_DEFINE, "#define __POW other_pow\n"):
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, "repeats a macro"):
                records.validate_header_macros(header_for(VARIANT) + duplicate, VARIANT)


class LmemGeneratedHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p02-wgmma-lmem-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.env = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                   "TMPDIR": str(cls.directory), "XLEN": "64"}
        cls.compiler = (shutil.which("g++", path=cls.env["PATH"])
                        or shutil.which("c++", path=cls.env["PATH"])
                        or shutil.which("clang++", path=cls.env["PATH"]))
        if cls.compiler is None:
            raise AssertionError("WGMMA LMEM checks require a host C++ preprocessor")
        cls.header = cls.directory / "VX_config.h"
        subprocess.run([sys.executable, str(ROOT / "ci/gen_config.py"),
                        "--config=" + str(ROOT / "VX_config.toml"), "--profile=", "--format=cpp",
                        "--output=" + str(cls.header)], cwd=cls.directory, env=cls.env,
                       capture_output=True, text=True, check=True, timeout=15)

    def preprocess(self, variant, *extra):
        # Compiler records carry resolved native enum selectors in addition to
        # the manifest's raw enums. Leave capacity to the generated header.
        result = subprocess.run([self.compiler, "-E", "-dM", "-x", "c++",
                                 *MANIFEST["configs"], *variant["configs"],
                                 "-DVX_CFG_TCU_TYPE_TFR", "-DVX_CFG_FPU_TYPE_STD", *extra,
                                 "-include", str(self.header), "/dev/null"],
                                cwd=self.directory, env=self.env, capture_output=True,
                                text=True, check=True, timeout=15)
        return result.stdout

    def test_all_frozen_variants_accept_the_actual_generated_expression(self):
        for variant in MANIFEST["variants"]:
            with self.subTest(variant=variant["id"]):
                output = self.preprocess(variant)
                self.assertIn(CAPACITY_DEFINE, output)
                self.assertIn(POW_DEFINE, output)
                observed = records.validate_header_macros(output, variant)
                self.assertEqual(observed["VX_CFG_LMEM_SIZE"], "__POW(2, VX_CFG_LMEM_LOG_SIZE)")
                self.assertEqual(observed["VX_CFG_LMEM_LOG_SIZE"], "14")

    def test_actual_preprocessing_preserves_and_rejects_conflicting_capacity(self):
        output = self.preprocess(VARIANT, "-DVX_CFG_LMEM_SIZE=12288")
        self.assertIn("#define VX_CFG_LMEM_SIZE 12288\n", output)
        self.assertIn("#define VX_CFG_LMEM_LOG_SIZE 14\n", output)
        with self.assertRaisesRegex(ValueError, "VX_CFG_LMEM_SIZE"):
            records.validate_header_macros(output, VARIANT)
        output = self.preprocess(VARIANT, "-DVX_CFG_LMEM_SIZE=16384")
        self.assertEqual(records.validate_header_macros(output, VARIANT)["VX_CFG_LMEM_SIZE"], "16384")

    def test_actual_preprocessing_rejects_helper_substitution(self):
        for flag in ("-D__POW(x,y)=12288", "-D__vx_cfg_pow(x,y)=12288",
                     "-D__POW=(x,y) __vx_cfg_pow((x), (y))"):
            output = self.preprocess(VARIANT, flag)
            self.assertIn(CAPACITY_DEFINE, output)
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "VX_CFG_LMEM_SIZE helper"):
                records.validate_header_macros(output, VARIANT)


if __name__ == "__main__":
    unittest.main()
