# SPDX-License-Identifier: Apache-2.0
"""Check the additive WGMMA CI selections without compiling GPU software."""

import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
PROCESSOR_CATALOG = ROOT / "ci/testcases/p02_wgmma.yaml"
UNIT_CATALOG = ROOT / "ci/testcases/unittest.yaml"
MANIFEST = ROOT / "ci/project/p02_wgmma_matrix.json"
VARIANTS = {"dense-fp16-ss", "sparse-fp16-ss"}
BUDGET_ENV = {
    "MAKEFLAGS": "-j2", "THREADS": "2", "CMAKE_BUILD_PARALLEL_LEVEL": "2",
    "CCACHE_DISABLE": "1", "OBJCACHE": "", "PROFILE": "",
}


def unit_entry():
    lines = UNIT_CATALOG.read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if line == '  - id: "hw-tcu-wgmma"']
    if len(starts) != 1:
        raise ValueError("expected one WGMMA unit entry")
    entry = {"id": "hw-tcu-wgmma"}
    for line in lines[starts[0] + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - "):
            break
        match = re.fullmatch(r"    ([a-z_]+): (.+)", line)
        if not match or match[1] in entry:
            raise ValueError("invalid WGMMA unit field")
        entry[match[1]] = json.loads(match[2])
    return entry


def defines(flags, *, repeated_identical=False):
    result = {}
    for token in shlex.split(flags):
        match = re.fullmatch(r"-D([A-Za-z_][A-Za-z_0-9]*)(?:=(\S+))?", token)
        if not match:
            raise ValueError("invalid or repeated configuration define")
        value = match[2] or "1"
        if match[1] in result and (not repeated_identical or result[match[1]] != value):
            raise ValueError("invalid or repeated configuration define")
        result[match[1]] = value
    return result


class WgmmaCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text())
        spec = importlib.util.spec_from_file_location("p02_wgmma_impact", ROOT / "ci/change_impact.py")
        cls.impact = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.impact)
        cls.document = cls.impact.load_yaml_subset(PROCESSOR_CATALOG.read_text())
        cls.unit = unit_entry()
        # The policy's YAML subset keeps offline governance standard-library only.
        spec = importlib.util.spec_from_file_location("p02_wgmma_catalog", ROOT / "ci/testcase.py")
        cls.catalog = importlib.util.module_from_spec(spec)
        yaml = SimpleNamespace(safe_load=lambda stream: cls.impact.load_yaml_subset(stream.read()))
        with patch.dict(sys.modules, {"yaml": yaml}):
            spec.loader.exec_module(cls.catalog)
        cls.cases = cls.catalog.load_category(str(PROCESSOR_CATALOG))
        cls.unit_case = cls.catalog.Spec("unittest", cls.unit, cls.unit["driver"],
                                        {"xlen": [32, 64], "tier": "smoke"})
        cls.resolved = {}
        configs = {case.id.split(":")[1]: case.configs for case in cls.cases}
        configs["unit"] = cls.unit["configs"]
        for name, flags in configs.items():
            result = subprocess.run(
                [sys.executable, str(ROOT / "ci/gen_config.py"), "--config",
                 str(ROOT / "VX_config.toml"), "--format", "cflags", "--profile=",
                 "--cflags=-DSIMULATION " + flags],
                check=True, capture_output=True, text=True, timeout=15,
            )
            cls.resolved[name] = defines(result.stdout, repeated_identical=True)

    def test_new_category_is_discovered_and_contains_only_four_functional_points(self):
        self.assertIn((str(PROCESSOR_CATALOG), "p02_wgmma"),
                      self.catalog.testcase_files(str(ROOT / "ci/testcases")))
        self.assertEqual(self.document["category"], PROCESSOR_CATALOG.stem)
        self.assertEqual({case.id for case in self.cases}, {
            f"p02_wgmma:{variant}:{driver}"
            for variant in VARIANTS for driver in ("simx", "rtlsim")
        })
        self.assertEqual(len(self.cases), 4)
        self.assertTrue(all(case.tier == "smoke" for case in self.cases))

    def test_all_selections_are_rv64_and_do_not_claim_parity_or_expected_failures(self):
        for case in self.cases + [self.unit_case]:
            with self.subTest(case=case.id):
                self.assertEqual(case.xlens, [64])
                self.assertTrue(case.applies_to_xlen(64))
                self.assertFalse(case.applies_to_xlen(32))
                self.assertEqual(case.check, "")
                self.assertEqual(case.known_issue, "")
                self.assertFalse(case.release_parity)
        for entry in self.document["tests"] + [self.unit]:
            self.assertFalse({"check", "tolerance", "known_issue", "release_parity"} & entry.keys())

    def test_processor_flags_exactly_match_two_frozen_variants(self):
        variants = {item["id"]: item for item in self.manifest["variants"]}
        for case in self.cases:
            name = case.id.split(":")[1]
            with self.subTest(case=case.id):
                self.assertEqual(shlex.split(case.configs),
                                 self.manifest["configs"] + variants[name]["configs"])
                defines(case.configs)

    def test_processor_commands_bind_the_exact_first_pattern_and_two_launches(self):
        variants = {item["id"]: item for item in self.manifest["variants"]}
        for case in self.cases:
            variant = variants[case.id.split(":")[1]]
            argv, env = case.run_command(64)
            with self.subTest(case=case.id):
                self.assertEqual(argv, ["./ci/blackbox.sh", "--driver=" + case.driver,
                    "--app=p02_wgmma", "--args=--case=" + variant["cases"][0] + " --iterations=2",
                    "--profile=", "--perf=11"])
                self.assertEqual(env["CONFIGS"], case.configs)
                self.assertEqual(case.shape, {})
                self.assertEqual(case.flags, "--profile= --perf=11")

    def test_boolean_overrides_remain_bare_makefile_selectors(self):
        for case in self.cases + [self.unit_case]:
            for token in shlex.split(case.configs):
                if re.match(r"-DVX_CFG_.*_(?:ENABLE|DISABLE)(?:=|$)", token):
                    with self.subTest(case=case.id, token=token):
                        self.assertNotIn("=", token)

    def test_resolved_processor_and_unit_geometry_is_native_and_fixed(self):
        values = {
            "VX_CFG_XLEN": "64", "VX_CFG_NUM_CLUSTERS": "1", "VX_CFG_NUM_CORES": "1",
            "VX_CFG_NUM_THREADS": "8", "VX_CFG_NUM_WARPS": "8", "VX_CFG_ISSUE_WIDTH": "4",
            "VX_CFG_FETCH_WIDTH": "2", "VX_CFG_NUM_ALU_BLOCKS": "1",
            "VX_CFG_NUM_LSU_BLOCKS": "1", "VX_CFG_NUM_LSU_LANES": "8",
            "VX_CFG_NUM_FPU_BLOCKS": "1", "VX_CFG_NUM_TCU_BLOCKS": "4",
            "VX_CFG_NUM_TCU_LANES": "8", "VX_CFG_TCU_LATENCY": "4",
            "VX_CFG_TCU_USE_DSP": "0", "VX_CFG_LMEM_SIZE": "16384",
            "VX_CFG_LMEM_NUM_BANKS": "8", "VX_CFG_TCU_TYPE": "TFR", "VX_CFG_FPU_TYPE": "STD",
            "VX_CFG_TCU_TYPE_TFR": "1", "VX_CFG_FPU_TYPE_STD": "1",
            "VX_CFG_TCU_FP16_ENABLED": "1", "VX_CFG_TCU_WGMMA_ENABLED": "1",
        }
        for name, observed in self.resolved.items():
            with self.subTest(case=name):
                self.assertEqual({key: observed.get(key) for key in values}, values)
                self.assertNotIn("VX_CFG_TCU_TYPE_DPI", observed)
                self.assertNotIn("VX_CFG_TCU_TYPE_DSP", observed)
                self.assertNotIn("SV_DPI", observed)

    def test_sparse_bank_is_enabled_only_where_required(self):
        for name, observed in self.resolved.items():
            sparse = name in ("sparse-fp16-ss", "unit")
            with self.subTest(case=name):
                self.assertEqual(observed["VX_CFG_TCU_SPARSE_ENABLED"], str(int(sparse)))
                self.assertEqual("VX_CFG_TCU_SPARSE_ENABLE" in observed, sparse)
                for bank in ("TF32", "FP8", "FP4", "INT8", "INT4", "MX", "MXFP4", "NVFP4", "DSM"):
                    self.assertEqual(observed["VX_CFG_TCU_" + bank + "_ENABLED"], "0")
                self.assertEqual(observed["VX_CFG_EXT_LDST_MATRIX_ENABLED"], "0")

    def test_unit_is_self_built_with_bounded_workers_and_timeout(self):
        self.assertFalse(self.unit_case.needs_sim)
        self.assertEqual(self.unit_case.driver, "rtlsim")
        argv, env = self.unit_case.run_command(64)
        self.assertEqual(argv[:2], ["bash", "-c"])
        self.assertEqual(shlex.split(argv[2]), ["timeout", "--signal=TERM", "--kill-after=15s",
            "1800s", "make", "-j2", "-C", "hw/unittest/tcu_wgmma", "THREADS=2", "run"])
        self.assertEqual(env["CONFIGS"], self.unit["configs"])
        self.assertEqual(self.unit_case.tier, "smoke")

    def test_unit_does_not_inherit_application_or_performance_knobs(self):
        observed = defines(self.unit["configs"])
        self.assertFalse({"ITYPE", "OTYPE", "KUNROLL", "WGMMA_NRC", "PERF_ENABLE",
                          "P02_WGMMA_WITNESS", "P02_WGMMA_SPARSE"} & observed.keys())
        self.assertEqual(observed["VX_CFG_TCU_SPARSE_ENABLE"], "1")

    def test_new_entries_bound_compilation_and_disable_cross_run_object_caches(self):
        for case in self.cases + [self.unit_case]:
            with self.subTest(case=case.id):
                _, env = case.run_command(64)
                self.assertEqual({key: value for key, value in env.items() if key != "CONFIGS"},
                                 BUDGET_ENV)
                flags = defines(case.configs)
                self.assertFalse(any(name.startswith(("DBG_TRACE_", "VX_CFG_TCU_FEDP2K"))
                                     or name in {"DEBUG", "VCD_OUTPUT", "SAIF_OUTPUT",
                                                 "P02_WGMMA_WITNESS"} for name in flags))

    def test_touches_cover_each_new_test_and_its_shared_implementation(self):
        required = {"ci/testcases/p02_wgmma.yaml", "tests/regression/p02_wgmma/",
                    "tests/regression/sgemm_tcu_wg/", "tests/regression/sgemm_tcu_wg_sp/",
                    "hw/rtl/tcu/", "sim/simx/", "sim/rtlsim/", "sw/runtime/"}
        for case in self.cases:
            self.assertTrue(required <= set(case.touches))
            self.assertFalse(self.catalog._touched(case, ["docs/project/status.md"]))
        self.assertTrue({"hw/unittest/tcu_wgmma/", "hw/unittest/common.mk", "hw/rtl/tcu/"}
                        <= set(self.unit_case.touches))
        self.assertFalse(self.catalog._touched(self.unit_case, ["docs/project/status.md"]))

    def test_existing_impact_detector_sees_every_new_case(self):
        _, processor = self.impact.parse_testcases(PROCESSOR_CATALOG.read_text())
        _, units = self.impact.parse_testcases(UNIT_CATALOG.read_text())
        self.assertEqual(set(processor), VARIANTS)
        self.assertIn("hw-tcu-wgmma", units)
        self.assertIn("args", processor["dense-fp16-ss"])
        self.assertIn("configs", processor["sparse-fp16-ss"])
        self.assertIn("run", units["hw-tcu-wgmma"])

    def test_changed_or_removed_cases_remain_visible_to_coverage_enforcement(self):
        original = PROCESSOR_CATALOG.read_text()
        mutations = {
            "args": original.replace("--iterations=2", "--iterations=1", 1),
            "defaults": original.replace("  - 64", "  - 32", 1),
            "removed": original[:original.index("- id: sparse-fp16-ss")],
        }
        for label, changed in mutations.items():
            diff = SimpleNamespace(
                matching=lambda _: [SimpleNamespace(path="ci/testcases/p02_wgmma.yaml")],
                old=lambda _: original, new=lambda _: changed,
            )
            with self.subTest(mutation=label):
                findings = self.impact.detect_testcase_coverage(diff, {"paths": ["ci/testcases/**"]})
                self.assertEqual(len(findings), 1)
                self.assertIn(label, findings[0]["detail"])


if __name__ == "__main__":
    unittest.main()
