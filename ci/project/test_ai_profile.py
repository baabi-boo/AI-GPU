# SPDX-License-Identifier: Apache-2.0
"""Source-only checks for the unqualified AI development profile."""

from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import shlex
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "VX_config.toml"
PROFILE = ROOT / "profiles/ai-dev.json"
SPEC = importlib.util.spec_from_file_location("ai_gpu_profile_gen_config", ROOT / "ci/gen_config.py")
gen_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gen_config
SPEC.loader.exec_module(gen_config)


class AiDevelopmentProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(PROFILE.read_text(encoding="utf-8"))
        cls.toml = gen_config._load_toml(str(CONFIG))
        cls.defaults, _ = gen_config._flatten_with_layout(cls.toml)
        cls.enums = gen_config._load_enums(cls.toml)
        cls.builtins = gen_config._load_var_table(cls.toml, "builtin")
        cls.params = gen_config._load_var_table(cls.toml, "param")
        cls.profile = gen_config.load_profile("ai-dev", str(ROOT / "profiles"))

    def invoke(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            result = gen_config.main(["--config", str(CONFIG), "--profile", "ai-dev", *arguments])
        self.assertEqual(result, 0)
        return output.getvalue().strip()

    def test_profile_is_explicitly_unqualified_without_performance_reference(self):
        self.assertIn("UNQUALIFIED", self.data["description"])
        self.assertNotIn("reference", self.data)
        self.assertNotIn("extends", self.data)
        self.assertNotIn("platform", self.data)

    def test_existing_profile_schema_accepts_all_selected_knobs(self):
        gen_config.validate_profile(
            self.profile, self.defaults, self.enums, set(self.builtins) | set(self.params))
        self.assertEqual(self.profile.name, "ai-dev")
        self.assertEqual(self.profile.chain, ["ai-dev"])

    def test_rv64_is_selected_and_rv32_is_rejected(self):
        self.assertEqual(self.invoke("--profile-xlen"), "64")
        with self.assertRaisesRegex(ValueError, "XLEN=32"):
            self.invoke("--xlen", "32", "--merge-configs")

    def test_bounded_catalog_geometry_and_native_flags(self):
        expected = {
            "VX_CFG_NUM_CLUSTERS": 1, "VX_CFG_NUM_CORES": 1,
            "VX_CFG_NUM_WARPS": 8, "VX_CFG_NUM_THREADS": 8,
            "VX_CFG_ISSUE_WIDTH": 2, "VX_CFG_NUM_ALU_BLOCKS": 1,
            "VX_CFG_NUM_LSU_BLOCKS": 1, "VX_CFG_NUM_FPU_BLOCKS": 1,
            "VX_CFG_FPU_TYPE": "STD", "VX_CFG_TCU_TYPE": "TFR",
            "VX_CFG_EXT_TCU_ENABLE": True, "VX_CFG_TCU_WGMMA_ENABLE": True,
            "VX_CFG_TCU_FP16_ENABLE": True,
        }
        self.assertEqual(self.profile.values, expected)
        tokens = shlex.split(self.invoke("--xlen", "64", "--merge-configs"))
        self.assertIn("-DVX_CFG_TCU_TYPE=TFR", tokens)
        self.assertIn("-DVX_CFG_FPU_TYPE=STD", tokens)
        self.assertIn("-DVX_CFG_EXT_TCU_ENABLE", tokens)
        self.assertIn("-DVX_CFG_TCU_WGMMA_ENABLE", tokens)
        self.assertFalse(any("DPI" in token for token in tokens))

    def test_tensor_geometry_obeys_inherited_full_issue_and_warp_constraints(self):
        resolver = gen_config.Resolver(
            self.defaults, dict(self.profile.values), self.enums, self.builtins, self.params)
        self.assertEqual(resolver.resolve("VX_CFG_NUM_TCU_BLOCKS"), 2)
        self.assertEqual(resolver.resolve("VX_CFG_NUM_TCU_BLOCKS"), resolver.resolve("VX_CFG_ISSUE_WIDTH"))
        self.assertEqual(resolver.resolve("VX_CFG_NUM_TCU_LANES"), resolver.resolve("VX_CFG_NUM_THREADS"))

    def test_native_arithmetic_is_pinned_even_when_dpi_is_available(self):
        overrides = dict(self.profile.values, SV_DPI=True)
        resolver = gen_config.Resolver(self.defaults, overrides, self.enums, self.builtins, self.params)
        self.assertEqual(resolver.resolve("VX_CFG_TCU_TYPE"), "TFR")
        self.assertEqual(resolver.resolve("VX_CFG_FPU_TYPE"), "STD")
        self.assertFalse(resolver.resolve("VX_CFG_TCU_TYPE_DPI"))
        self.assertFalse(resolver.resolve("VX_CFG_FPU_TYPE_DPI"))

    def test_application_signature_is_not_embedded_in_hardware_profile(self):
        for name in ("ITYPE", "OTYPE", "WGMMA_NRC"):
            self.assertNotIn(name, self.profile.values)
        tokens = shlex.split(self.invoke(
            "--xlen", "64", "--merge-configs",
            "--cflags=-DITYPE=fp16 -DOTYPE=fp32 -DWGMMA_NRC=16"))
        for token in ("-DITYPE=fp16", "-DOTYPE=fp32", "-DWGMMA_NRC=16"):
            self.assertIn(token, tokens)

    def test_explicit_overrides_replace_profile_flags(self):
        tokens = shlex.split(self.invoke(
            "--xlen", "64", "--merge-configs",
            "--cflags=-DVX_CFG_TCU_TYPE_DPI -DVX_CFG_EXT_TCU_DISABLE"))
        self.assertIn("-DVX_CFG_TCU_TYPE_DPI", tokens)
        self.assertNotIn("-DVX_CFG_TCU_TYPE=TFR", tokens)
        self.assertIn("-DVX_CFG_EXT_TCU_DISABLE", tokens)
        self.assertNotIn("-DVX_CFG_EXT_TCU_ENABLE", tokens)

    def test_invalid_arithmetic_backend_is_rejected(self):
        invalid = copy.deepcopy(self.profile)
        invalid.values["VX_CFG_TCU_TYPE"] = "NOT_A_BACKEND"
        with self.assertRaises(ValueError):
            gen_config.validate_profile(
                invalid, self.defaults, self.enums, set(self.builtins) | set(self.params))

    def test_loading_and_merging_do_not_mutate_global_defaults(self):
        before = CONFIG.read_bytes()
        defaults_before = copy.deepcopy(self.defaults)
        self.invoke("--xlen", "64", "--merge-configs")
        self.assertEqual(CONFIG.read_bytes(), before)
        self.assertEqual(self.defaults, defaults_before)
        self.assertIs(self.defaults["VX_CFG_EXT_TCU_ENABLE"], False)
        self.assertIs(self.defaults["VX_CFG_TCU_WGMMA_ENABLE"], False)

    def test_every_override_has_source_provenance(self):
        source_text = "\n".join(self.data["sources"])
        for name in (*self.profile.values, "xlen"):
            with self.subTest(name=name):
                self.assertIn(name, source_text)


if __name__ == "__main__":
    unittest.main()
