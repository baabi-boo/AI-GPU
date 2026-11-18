# SPDX-License-Identifier: Apache-2.0
"""Actual host validation and wire-byte checks, without device execution."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "sw/runtime/ai"
HARNESS = ROOT / "ci/project/fixtures/p03_operator_contract_test.cpp"
MANIFEST = ROOT / "ci/project/p03_operator_manifest.json"


class OperatorContractHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if cls.compiler is None:
            raise AssertionError("Operator contract tests require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p03-contract-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "contract-test"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        cls.inputs = [HARNESS, CONTRACT / "contract.h", CONTRACT / "contract.cpp"]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in cls.inputs}
        run_host_command([
            cls.compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-I", str(CONTRACT),
            str(HARNESS), str(CONTRACT / "contract.cpp"), "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=30)

    def group(self, name):
        output = run_host_command([str(self.binary), name], cwd=self.build,
                                  env=self.environment, timeout=10)
        self.assertRegex(output, r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed during contract tests: " + str(path))
        self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*") if path.is_file()),
                        64 * 1024 * 1024, "Bounded host test storage exceeds 64 MiB")

    def test_both_formats_and_all_qualified_shape_tuples(self):
        self.group("positive_shapes")

    def test_versions_enums_rank_types_and_null_output(self):
        self.group("invalid_fields")

    def test_no_implicit_shape_cross_product_layout_transpose_or_batch(self):
        self.group("shape_and_layout")

    def test_allocation_subranges_overflow_alignment_and_last_byte(self):
        self.group("allocation_ranges")

    def test_ownership_access_aliases_and_consistent_allocation_identity(self):
        self.group("ownership_and_aliasing")

    def test_exact_capabilities_and_explicit_verified_profile_binding(self):
        self.group("capabilities")

    def test_independent_literal_little_endian_bytes_and_rv32_range(self):
        self.group("wire_bytes")

    def test_invalid_wire_fields_fail_atomically_with_useful_diagnostics(self):
        self.group("invalid_wire")


class OperatorManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text())
        self.operators = {entry["id"]: entry for entry in self.manifest["operators"]}

    def test_all_required_families_are_explicit_and_execution_is_unavailable(self):
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["contract_id"], "p03-native-operators-v1")
        self.assertEqual(len(self.manifest["operators"]), 8)
        self.assertEqual(set(self.operators), {
            "matmul", "gemv", "reduction", "softmax", "normalization", "activation", "layout_cast", "attention",
        })
        self.assertIs(self.manifest["execution_available"], False)
        self.assertEqual(self.operators["matmul"]["state"], "contract_only")
        for name, entry in self.operators.items():
            if name != "matmul":
                self.assertEqual(entry["state"], "unavailable", name)
        self.assertEqual({name: entry["enum_value"] for name, entry in self.operators.items()}, {
            "matmul": 1, "gemv": 2, "reduction": 3, "softmax": 4, "normalization": 5,
            "activation": 6, "layout_cast": 7, "attention": 8,
        })
        self.assertIs(self.manifest["cpu_fallback"], False)
        self.assertIs(self.manifest["installed_api"], False)

    def test_matmul_signature_matches_the_independent_ordinary_wmma_inventory_union(self):
        inventories = [json.loads((ROOT / "ci/project/fixtures" / filename).read_text())
                       for filename in ("p02_layout_v1.json", "p02_wmma_numerical_v1.json")]
        shapes_by_dtype = {}
        for inventory in inventories:
            for case in inventory["cases"]:
                shapes_by_dtype.setdefault(case["format"], set()).add(
                    tuple(case["dimensions"][axis] for axis in ("m", "n", "k")))
        expected = {(8, 4, 8), (8, 4, 16), (16, 8, 16)}
        self.assertEqual(shapes_by_dtype, {"fp16": expected, "bf16": expected})
        signature = self.operators["matmul"]["signature"]
        self.assertEqual(signature["input_dtypes"], ["fp16", "bf16"])
        self.assertEqual(signature["output_dtype"], "fp32")
        self.assertEqual(signature["rank"], 2)
        self.assertEqual(signature["shape_tuples"], [[8, 4, 8], [8, 4, 16], [16, 8, 16]])
        self.assertEqual((signature["a_layout"], signature["b_layout"], signature["d_layout"]),
                         ("row_major", "column_major", "row_major"))
        self.assertEqual(signature["initial_c_bits"], "00000000")
        self.assertEqual(signature["batch_count"], 1)
        self.assertIs(signature["transpose"], False)
        self.assertIs(signature["padding"], False)
        self.assertEqual(signature["empty_inputs"], "reject")
        self.assertEqual(signature["allocation_base_and_view_offset_alignment_bytes"], 4)

    def test_declared_profile_keeps_ordinary_wmma_geometry(self):
        profile = self.manifest["profile"]
        expected = {"execution_address_bits": 64, "threads_per_warp": 4, "warps_per_core": 4,
                    "cores": 1, "clusters": 1, "issue_width": 1, "local_mem_bytes": 16384}
        self.assertEqual({key: profile[key] for key in expected}, expected)
        for field in ("tensor_extension", "local_memory", "requires_verified_kernel_profile",
                      "requires_verified_device_profile"):
            self.assertIs(profile[field], True)
        source = json.loads((ROOT / profile["source"]).read_text())
        self.assertEqual(source["xlen"], 64)
        self.assertEqual(source["core"]["VX_CFG_NUM_THREADS"], profile["threads_per_warp"])
        self.assertEqual(source["core"]["VX_CFG_NUM_WARPS"], profile["warps_per_core"])
        self.assertEqual(source["core"]["VX_CFG_ISSUE_WIDTH"], profile["issue_width"])
        self.assertIs(source["core"]["VX_CFG_TCU_WGMMA_ENABLE"], False)
        self.assertIs(source["core"]["VX_CFG_TCU_SPARSE_ENABLE"], False)

    def test_argument_representation_is_distinct_from_execution_address_width(self):
        abi = self.manifest["argument_abi"]
        self.assertEqual(abi["size_bytes"], 56)
        self.assertEqual(abi["alignment_bytes"], 8)
        self.assertEqual(abi["address_bits"], [32, 64])
        self.assertEqual(abi["execution_address_bits"], [64])
        self.assertEqual(abi["byte_order"], "little_endian")
        self.assertIs(abi["consumer_available"], False)
        self.assertIs(abi["legacy_kernel_arg_compatible"], False)
        self.assertIs(abi["host_pointers_allowed"], False)
        self.assertEqual([(field["name"], field["offset"], field["type"]) for field in abi["fields"]], [
            ("abi_version", 0, "u32"), ("byte_size", 4, "u32"), ("input_dtype", 8, "u32"),
            ("flags", 12, "u32"), ("m", 16, "u32"), ("n", 20, "u32"), ("k", 24, "u32"),
            ("reserved", 28, "u32"), ("a_address", 32, "u64"), ("b_address", 40, "u64"),
            ("d_address", 48, "u64"),
        ])


if __name__ == "__main__":
    unittest.main()
