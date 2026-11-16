# SPDX-License-Identifier: Apache-2.0
"""MX catalog format-bank prerequisites; no processor or RTL execution."""

from pathlib import Path
import re
import shlex
import subprocess
import sys
import unittest


SOURCE = Path(__file__).resolve().parents[2]
CATALOG = SOURCE / "ci/testcases/tensor_mx.yaml"
COMMON_ENABLES = ("VX_CFG_EXT_TCU_ENABLE", "VX_CFG_TCU_MX_ENABLE",
                  "VX_CFG_TCU_FP8_ENABLE")
# The native API and TFR lane mask also nest four-bit formats under FP8.
REQUIRED_ENABLES = {
    "mxfp8": COMMON_ENABLES,
    "mxbf8": COMMON_ENABLES,
    "mxfp4": COMMON_ENABLES + ("VX_CFG_TCU_FP4_ENABLE", "VX_CFG_TCU_MXFP4_ENABLE"),
    "nvfp4": COMMON_ENABLES + ("VX_CFG_TCU_FP4_ENABLE", "VX_CFG_TCU_NVFP4_ENABLE"),
}
NATIVE_CASES = {
    f"sgemm_tcu_mx-simx-{dtype}-nt{threads}"
    for dtype in REQUIRED_ENABLES for threads in (4, 8, 16, 32)
} | {"sgemm_tcu_mx-simx-nvfp4-nt4-tls", "sgemm_tcu_mx-ldm-2"}


def catalog_configs(text):
    """Read the catalog's fixed single-line id/config fields without PyYAML."""
    configs = {}
    case_id = None
    in_tests = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line == "tests:":
            if in_tests:
                raise ValueError("duplicate tests section")
            in_tests = True
        elif line.startswith("- id:"):
            match = re.fullmatch(r"- id: ([a-z0-9_-]+)", line)
            if not in_tests or not match or match[1] in configs:
                raise ValueError("invalid or duplicate catalog id")
            case_id = match[1]
            configs[case_id] = None
        elif re.match(r"\s*configs\+?\s*:", line):
            match = re.fullmatch(r"  configs: (.+)", line)
            if not match or case_id is None or configs[case_id] is not None:
                raise ValueError("expected one explicit scalar configs field per case")
            configs[case_id] = match[1]
        elif in_tests and not re.match(r"  (?:[a-z_]+:|-[ ])", line):
            raise ValueError("unsupported catalog field layout")
    if not configs or any(value is None for value in configs.values()):
        raise ValueError("missing catalog configs")
    return configs


def defines(configs):
    result = {}
    for token in shlex.split(configs, comments=True):
        match = re.fullmatch(r"-D([A-Za-z_][A-Za-z_0-9]*)(?:=(\S+))?", token)
        if not match or match[1] in result:
            raise ValueError("invalid or duplicate catalog define: " + token)
        result[match[1]] = match[2] if match[2] is not None else "1"
    if not result:
        raise ValueError("empty catalog configs")
    return result


class TensorMxCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configs = catalog_configs(CATALOG.read_text(encoding="utf-8"))
        cls.defines = {case_id: defines(flags) for case_id, flags in cls.configs.items()}
        cls.resolved = {}
        for case_id, flags in cls.configs.items():
            for xlen in (32, 64):
                result = subprocess.run(
                    [sys.executable, str(SOURCE / "ci/gen_config.py"),
                     "--config", str(SOURCE / "VX_config.toml"), "--format", "cflags",
                     f"--cflags=-DSIMULATION -DVX_CFG_XLEN={xlen} {flags}"],
                    check=True, capture_output=True, text=True, timeout=15,
                )
                cls.resolved[case_id, xlen] = set(shlex.split(result.stdout))

    def test_native_inventory_keeps_tfr_separate_from_dpi(self):
        for xlen in (32, 64):
            native = {case_id for case_id in self.configs
                      if "-DVX_CFG_TCU_TYPE_TFR" in self.resolved[case_id, xlen]}
            with self.subTest(xlen=xlen):
                self.assertEqual(native, NATIVE_CASES)
                self.assertEqual({self.defines[case_id]["ITYPE"] for case_id in native},
                                 set(REQUIRED_ENABLES))
            for case_id in self.configs.keys() - native:
                with self.subTest(case=case_id, xlen=xlen):
                    self.assertIn("-DVX_CFG_TCU_TYPE_DPI", self.resolved[case_id, xlen])
                    self.assertNotIn("-DVX_CFG_TCU_TYPE_TFR", self.resolved[case_id, xlen])

    def test_native_scaled_formats_explicitly_enable_required_banks(self):
        for case_id in sorted(NATIVE_CASES):
            flags = self.defines[case_id]
            for enable in REQUIRED_ENABLES[flags["ITYPE"]]:
                with self.subTest(case=case_id, enable=enable):
                    self.assertEqual(flags.get(enable), "1")
                    self.assertNotIn(enable.removesuffix("_ENABLE") + "_DISABLE", flags)
                    for xlen in (32, 64):
                        self.assertIn("-D" + enable, self.resolved[case_id, xlen])


if __name__ == "__main__":
    unittest.main()
