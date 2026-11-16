# SPDX-License-Identifier: Apache-2.0
"""Independent declaration checks using synthetic, unqualified vendor inputs."""

from copy import deepcopy
import json
import unittest
from unittest import mock

import hwemu_contract as contract
from hwemu_fixture import HwemuFixture


GIB = 1024 ** 3
MIB = 1024 ** 2
EXPECTED_CONFIGS = [
    "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1", "-DVX_CFG_FPU_TYPE_STD",
]
EXPECTED_ROLES = {
    "vpp", "vivado", "emconfigutil", "platforminfo", "xrt_header",
    "xrt_library", "platform", "xclbin", "emconfig", "build_receipt", "xsim_hook",
}
EXPECTED_GENERATED = {
    ".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
    "hw/VX_config.vh", "hw/VX_types.vh", "ci/blackbox.sh", "ci/gen_config.py",
    "sw/kernel/Makefile", "sw/runtime/stub/Makefile", "sw/runtime/common.mk",
    "sw/runtime/xrt/Makefile", "sw/runtime/xrt/xrt.ini",
    "sw/runtime/xrt_config.stamp", "tests/regression/demo/Makefile",
    "tests/regression/demo/config.stamp", "tests/regression/common.mk",
    "hw/syn/xilinx/xrt/Makefile", "hw/syn/xilinx/common.mk", "hw/syn/xilinx/platform.mk",
}


def at(document, path):
    for key in path:
        document = document[key]
    return document


class HwemuContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HwemuFixture()
        cls.addClassCleanup(cls.fixture.close)
        cls.original = deepcopy(cls.fixture.manifest)
        cls.receipt = json.loads(cls.fixture.receipt_path.read_text(encoding="utf-8"))

    def manifest(self, path=None, value=None):
        result = deepcopy(self.original)
        if path is not None:
            at(result, path[:-1])[path[-1]] = value
        return result

    def object_paths(self):
        paths = [(), ("source",), ("build",), ("vendor",), ("platform",),
                 ("files",), ("generated",), ("budget",)]
        paths += [("vendor", name) for name in ("vitis", "vivado", "xrt")]
        paths += [("files", name) for name in EXPECTED_ROLES]
        paths += [("generated", name) for name in EXPECTED_GENERATED]
        return paths

    def identity_paths(self):
        return ([("files", name) for name in EXPECTED_ROLES]
                + [("generated", name) for name in EXPECTED_GENERATED])

    def assert_invalid(self, document):
        original = deepcopy(document)
        with self.assertRaises(ValueError):
            contract.validate_manifest(document)
        self.assertEqual(document, original)

    def test_real_generated_fixture_has_complete_frozen_declarations(self):
        result = contract.validate_manifest(self.original)
        self.assertEqual(result, self.original)
        self.assertEqual(result["target"], "hw_emu")
        self.assertEqual(result["build"]["configs"], EXPECTED_CONFIGS)
        self.assertEqual(set(result["files"]), EXPECTED_ROLES)
        self.assertEqual(set(result["generated"]), EXPECTED_GENERATED)
        self.assertEqual(len(result["files"]) + len(result["generated"]), 31)
        self.assertEqual(contract.validate_receipt(self.receipt, self.original), self.receipt)

    def test_success_returns_detached_nested_objects_without_side_effects(self):
        before = deepcopy(self.original)
        with mock.patch("builtins.open", side_effect=AssertionError("filesystem access")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("execution")):
            result = contract.validate_manifest(self.original)
            receipt = contract.validate_receipt(self.receipt, self.original)
        result["build"]["configs"].append("changed")
        result["files"]["xclbin"]["size_bytes"] = 1
        receipt["source"]["revision"] = "0" * 40
        self.assertEqual(self.original, before)
        self.assertEqual(self.receipt["source"]["revision"], before["source"]["revision"])

    def test_every_object_rejects_missing_and_unknown_fields(self):
        for path in self.object_paths():
            for key in at(self.original, path):
                candidate = self.manifest()
                del at(candidate, path)[key]
                with self.subTest(path=path, missing=key):
                    self.assert_invalid(candidate)
            candidate = self.manifest()
            at(candidate, path)["unexpected"] = "unreviewed input"
            with self.subTest(path=path, unknown=True):
                self.assert_invalid(candidate)

    def test_objects_reject_nonobjects_and_boolean_confusion(self):
        for path in self.object_paths():
            for value in (None, [], "", 0, True):
                candidate = self.manifest(path, value) if path else value
                with self.subTest(path=path, value=value):
                    self.assert_invalid(candidate)

    def test_schema_and_xlen_require_exact_integers(self):
        for path, required in ((("schema_version",), 1), (("build", "xlen"), 64)):
            for value in (True, False, None, str(required), float(required),
                          required - 1, required + 1):
                with self.subTest(path=path, value=value):
                    self.assert_invalid(self.manifest(path, value))

    def test_target_and_profile_cannot_select_a_different_execution(self):
        for value in ("xrtsim", "hw", "sw_emu", "HW_EMU", "hw_emu ", "", True, None):
            with self.subTest(target=value):
                self.assert_invalid(self.manifest(("target",), value))
        for value in ("ai-dev", "default", " ", True, None, []):
            with self.subTest(profile=value):
                self.assert_invalid(self.manifest(("build", "profile"), value))

    def test_configuration_cannot_drop_change_reorder_or_inject_flags(self):
        variants = [[], tuple(EXPECTED_CONFIGS), " ".join(EXPECTED_CONFIGS),
                    EXPECTED_CONFIGS[::-1], EXPECTED_CONFIGS + ["-DXRTSIM"],
                    EXPECTED_CONFIGS + ["-DVX_CFG_NUM_CORES=1"]]
        for index in range(len(EXPECTED_CONFIGS)):
            variants.append(EXPECTED_CONFIGS[:index] + EXPECTED_CONFIGS[index + 1:])
            changed = list(EXPECTED_CONFIGS)
            changed[index] += "0"
            variants.append(changed)
        for value in variants:
            with self.subTest(configs=value):
                self.assert_invalid(self.manifest(("build", "configs"), value))

    def test_source_revisions_are_complete_lowercase_hex(self):
        for key in ("revision", "tree"):
            for value in (None, 0, "", "a" * 39, "a" * 41, "A" * 40,
                          "g" * 40, "a" * 40 + "\n"):
                with self.subTest(key=key, value=value):
                    self.assert_invalid(self.manifest(("source", key), value))

    def test_all_identity_hashes_are_complete_lowercase_hex(self):
        for path in self.identity_paths():
            for value in (None, True, "", "a" * 63, "a" * 65, "A" * 64,
                          "g" * 64, "a" * 64 + "\n"):
                with self.subTest(path=path, value=value):
                    self.assert_invalid(self.manifest((*path, "sha256"), value))

    def test_all_required_inputs_reject_empty_or_invalid_sizes(self):
        for path in self.identity_paths():
            for value in (0, -1, True, False, None, "1", 1.0, 512 * MIB + 1):
                with self.subTest(path=path, value=value):
                    self.assert_invalid(self.manifest((*path, "size_bytes"), value))

    def test_all_absolute_paths_reject_shell_and_noncanonical_forms(self):
        paths = [("source", "root"), ("build", "root"), ("build", "tool_dir")]
        paths += [("vendor", name, "root") for name in ("vitis", "vivado", "xrt")]
        paths += [("files", role, "path") for role in EXPECTED_ROLES]
        hostile = (None, "", "/", "relative/file", "//tmp/file", "/tmp/./file",
                   "/tmp/../file", "/tmp//file", "/tmp/file/", "/tmp/a b",
                   "/tmp/$(touch)", "/tmp/`touch`", "/tmp/a;b", "/tmp/a#b",
                   "/tmp/a:b", "/tmp/a\\b", "/tmp/a\n", "/tmp/\x00", "/tmp/é",
                   "/" + "a" * 4096)
        for path in paths:
            for value in hostile:
                with self.subTest(path=path, value=repr(value)):
                    self.assert_invalid(self.manifest(path, value))

    def test_build_cannot_overlap_source_inputs(self):
        source = self.original["source"]["root"]
        for value in (source, str(self.fixture.base), source + "/sw",
                      source + "/build64/nested"):
            with self.subTest(root=value):
                self.assert_invalid(self.manifest(("build", "root"), value))
        candidate = self.manifest(("build", "root"), source + "/build64")
        self.assertEqual(contract.validate_manifest(candidate), candidate)

    def test_tool_directory_must_not_equal_source_or_overlap_build(self):
        build = self.original["build"]["root"]
        for value in (self.original["source"]["root"], build,
                      build + "/tools", str(self.fixture.base)):
            with self.subTest(tool_dir=value):
                self.assert_invalid(self.manifest(("build", "tool_dir"), value))

    def test_native_tools_and_source_must_not_contain_each_other(self):
        source = self.original["source"]["root"]
        nested_tools = self.manifest(("build", "tool_dir"), source + "/native-tools")
        self.assert_invalid(nested_tools)
        containing_tools = self.manifest(("build", "tool_dir"), str(self.fixture.base))
        containing_tools["build"]["root"] = "/synthetic-separate-build/build64"
        self.assert_invalid(containing_tools)
        sibling = self.manifest(("build", "tool_dir"), source + "-tools")
        self.assertEqual(contract.validate_manifest(sibling), sibling)

    def test_vendor_tools_and_source_hook_stay_bound_to_declared_roots(self):
        for role in ("vpp", "vivado", "emconfigutil", "platforminfo", "xsim_hook"):
            original = self.original["files"][role]["path"]
            for path in (original + "-other", "/foreign/" + original.rsplit("/", 1)[1]):
                with self.subTest(role=role, path=path):
                    self.assert_invalid(self.manifest(("files", role, "path"), path))

    def test_vendor_release_names_are_bounded_inert_identifiers(self):
        for name in ("vitis", "vivado", "xrt"):
            for value in (None, True, "", "a" * 81, "2025.1 beta", "$(version)",
                          "2025.1\n", "/2025.1"):
                with self.subTest(vendor=name, release=value):
                    self.assert_invalid(self.manifest(("vendor", name, "release"), value))
            for value in ("a", "a" * 80, "2025.1-build_2+rev"):
                candidate = self.manifest(("vendor", name, "release"), value)
                with self.subTest(vendor=name, valid=value):
                    self.assertEqual(contract.validate_manifest(candidate), candidate)

    def test_xrt_header_requires_a_descendant_of_its_include_root(self):
        include = self.original["vendor"]["xrt"]["root"] + "/include"
        for value in (include, include + "-other/xrt.h", "/foreign/include/xrt.h"):
            with self.subTest(path=value):
                self.assert_invalid(self.manifest(("files", "xrt_header", "path"), value))
        candidate = self.manifest(("files", "xrt_header", "path"), include + "/experimental/xrt_bo.h")
        self.assertEqual(contract.validate_manifest(candidate), candidate)

    def test_xrt_library_requires_exact_vendor_directory_and_supported_soname(self):
        root = self.original["vendor"]["xrt"]["root"]
        for suffix in ("lib/libxrtsim.so", "lib/libxrt_coreutil.so.bad",
                       "lib/nested/libxrt_coreutil.so", "lib64/libxrt_coreutil.so"):
            with self.subTest(suffix=suffix):
                self.assert_invalid(self.manifest(("files", "xrt_library", "path"), root + "/" + suffix))
        for name in ("libxrt_coreutil.so", "libxrt_coreutil.so.2.17.0"):
            candidate = self.manifest(("files", "xrt_library", "path"), root + "/lib/" + name)
            self.assertEqual(contract.validate_manifest(candidate), candidate)

    def test_platform_name_and_descriptor_must_match(self):
        for value in (None, True, "", "a" * 161, "a/b", "a b", "$(platform)"):
            with self.subTest(name=value):
                self.assert_invalid(self.manifest(("platform", "name"), value))
        for key, value in ((("platform", "name"), "another_platform"),
                           (("files", "platform", "path"), "/platform/another_platform.xpfm")):
            self.assert_invalid(self.manifest(key, value))

    def test_artifact_pair_requires_canonical_names_and_same_directory(self):
        for role, value in (("xclbin", "/artifacts/other.xclbin"),
                            ("emconfig", "/artifacts/other.json"),
                            ("emconfig", "/different/emconfig.json")):
            with self.subTest(role=role, path=value):
                self.assert_invalid(self.manifest(("files", role, "path"), value))

    def test_roles_cannot_alias_each_other_or_generated_build_inputs(self):
        for other in EXPECTED_ROLES - {"build_receipt"}:
            with self.subTest(alias=other):
                self.assert_invalid(self.manifest(("files", "build_receipt", "path"),
                                                 self.original["files"][other]["path"]))
        for generated in EXPECTED_GENERATED:
            with self.subTest(generated=generated):
                self.assert_invalid(self.manifest(("files", "build_receipt", "path"),
                                                 self.original["build"]["root"] + "/" + generated))

    def test_budgets_reject_boolean_nonfinite_fractional_and_out_of_range_values(self):
        bounds = {"jobs": (1, 2), "timeout_seconds": (1, 7200),
                  "min_free_bytes": (15 * GIB, 1024 * GIB),
                  "max_rss_bytes": (1, 6 * GIB), "max_log_bytes": (1, 16 * MIB),
                  "max_input_bytes": (1, 512 * MIB)}
        for key, (minimum, maximum) in bounds.items():
            for value in (True, False, None, "1", 1.0, float("inf"), float("nan"),
                          minimum - 1, maximum + 1):
                candidate = self.manifest(("budget", key), value)
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    contract.validate_manifest(candidate)
            for value in (minimum, maximum):
                if key == "max_input_bytes" and value == minimum:
                    continue
                candidate = self.manifest(("budget", key), value)
                with self.subTest(key=key, boundary=value):
                    self.assertEqual(contract.validate_manifest(candidate), candidate)

    def test_input_budget_counts_every_file_and_generated_identity(self):
        candidate = self.manifest()
        total = sum(at(candidate, path)["size_bytes"] for path in self.identity_paths())
        candidate["budget"]["max_input_bytes"] = total
        self.assertEqual(contract.validate_manifest(candidate), candidate)
        for path in self.identity_paths():
            increased = deepcopy(candidate)
            at(increased, path)["size_bytes"] += 1
            with self.subTest(path=path):
                self.assert_invalid(increased)
        candidate["budget"]["max_input_bytes"] -= 1
        self.assert_invalid(candidate)

    def test_smallest_complete_identity_set_consumes_thirty_one_bytes(self):
        candidate = self.manifest()
        for path in self.identity_paths():
            at(candidate, path)["size_bytes"] = 1
        candidate["budget"]["max_input_bytes"] = 31
        self.assertEqual(contract.validate_manifest(candidate), candidate)
        candidate["budget"]["max_input_bytes"] = 30
        self.assert_invalid(candidate)

    def test_aggregate_upper_bound_is_inclusive_and_cannot_be_exceeded(self):
        candidate = self.manifest()
        for path in self.identity_paths():
            at(candidate, path)["size_bytes"] = 1
        candidate["files"]["xclbin"]["size_bytes"] = 512 * MIB - 30
        self.assertEqual(contract.validate_manifest(candidate), candidate)
        candidate["files"]["xclbin"]["size_bytes"] += 1
        self.assert_invalid(candidate)

    def test_receipt_json_size_has_its_own_bound(self):
        candidate = self.manifest(("files", "build_receipt", "size_bytes"), 256 * 1024)
        self.assertEqual(contract.validate_manifest(candidate), candidate)
        candidate["files"]["build_receipt"]["size_bytes"] += 1
        self.assert_invalid(candidate)

    def test_receipt_cannot_add_budget_self_identity_or_approval_fields(self):
        variants = [dict(self.receipt, budget=deepcopy(self.original["budget"])),
                    dict(self.receipt, phase_complete=True),
                    dict(self.receipt, vendor_qualified=True)]
        recursive = deepcopy(self.receipt)
        recursive["files"]["build_receipt"] = deepcopy(self.original["files"]["build_receipt"])
        variants.append(recursive)
        for candidate in variants:
            with self.subTest(fields=set(candidate)), self.assertRaises(ValueError):
                contract.validate_receipt(candidate, self.original)

    def test_receipt_rejects_missing_declarations(self):
        for section in self.receipt:
            candidate = deepcopy(self.receipt)
            del candidate[section]
            with self.subTest(section=section), self.assertRaises(ValueError):
                contract.validate_receipt(candidate, self.original)
        for role in self.receipt["files"]:
            candidate = deepcopy(self.receipt)
            del candidate["files"][role]
            with self.subTest(role=role), self.assertRaises(ValueError):
                contract.validate_receipt(candidate, self.original)

    def test_receipt_rejects_well_formed_but_different_bindings(self):
        paths = [("source", "revision"), ("source", "tree")]
        for path in paths:
            candidate = deepcopy(self.receipt)
            at(candidate, path[:-1])[path[-1]] = "0" * 40
            with self.subTest(path=path), self.assertRaises(ValueError):
                contract.validate_receipt(candidate, self.original)
        for name in ("vitis", "vivado", "xrt"):
            candidate = deepcopy(self.receipt)
            candidate["vendor"][name]["release"] = "other-1.0"
            with self.subTest(vendor=name), self.assertRaises(ValueError):
                contract.validate_receipt(candidate, self.original)
        for section in ("files", "generated"):
            for name in self.receipt[section]:
                candidate = deepcopy(self.receipt)
                candidate[section][name]["sha256"] = "0" * 64
                with self.subTest(section=section, name=name), self.assertRaises(ValueError):
                    contract.validate_receipt(candidate, self.original)

    def test_receipt_validation_also_requires_a_valid_independent_manifest(self):
        candidate = self.manifest(("budget", "jobs"), True)
        with self.assertRaises(ValueError):
            contract.validate_receipt(self.receipt, candidate)


if __name__ == "__main__":
    unittest.main()
