# SPDX-License-Identifier: Apache-2.0
"""Independent source-inventory regressions; synthetic records are not GPU evidence.

These checks require the known frozen P01 recursive inventory and consistency
between recorded observations. They do not authenticate an arbitrary Git tree
or reconstruct absent source files from asserted revision or content hashes.
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from baseline_packet import verify_packet
from baseline_packet_fixture import make_packet
from baseline_packet_io import PacketError


# Keep the expected closure independent of verifier and fixture constants.
DECLARED_PATHS = (
    "third_party/cocogfx", "third_party/cvfpu", "third_party/hardfloat",
    "third_party/ramulator", "third_party/softfloat",
)
NESTED_PATHS = (
    "third_party/cvfpu/src/common_cells",
    "third_party/cvfpu/src/fpu_div_sqrt_mvp",
    "third_party/cvfpu/tb/flexfloat",
)


def source_observations(report):
    """Enumerate the initial observation and both boundaries of all six cases."""
    yield "source_before", report["source_before"]
    for case in report["cases"]:
        for stage in ("source_before", "source_after"):
            yield case["id"] + "." + stage, case[stage]


def submodule(source, path):
    return next(entry for entry in source["submodules"]["entries"]
                if entry["path"] == path)


def reverse_object_keys(value):
    if isinstance(value, dict):
        return {key: reverse_object_keys(item)
                for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reverse_object_keys(item) for item in value]
    return value


class PacketSourceProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "packet"
        self.report = make_packet(self.root)

    def verify(self, report):
        # Preserve object insertion order so the equal-value control really
        # exercises independently serialized observations with different keys.
        (self.root / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return verify_packet(self.root, require_native_pass=True)

    def assertNativeConsistency(self, report):
        result = self.verify(report)
        self.assertEqual(result["outcome"], "pass")
        self.assertIs(result["native_matrix_passed"], True)
        self.assertIs(result["requirement_satisfied"], True)
        self.assertIs(result["phase_complete"], False)
        self.assertEqual(result["integration_outcome"], "blocked")
        return result

    def assertInvalid(self, report, reason):
        with self.assertRaisesRegex(PacketError, reason):
            self.verify(report)

    def test_five_declarations_and_eight_recursive_entries_are_accepted(self):
        observations = list(source_observations(self.report))
        self.assertEqual(len(observations), 13)
        self.assertEqual(len({id(source) for _, source in observations}), 13)
        for label, source in observations:
            with self.subTest(observation=label):
                modules = source["submodules"]
                self.assertEqual(modules["declared_count"], 5)
                self.assertEqual(len(modules["entries"]), 8)
                self.assertEqual({entry["path"] for entry in modules["entries"]},
                                 set(DECLARED_PATHS + NESTED_PATHS))
                self.assertTrue(all(entry["status"] == "initialized"
                                    for entry in modules["entries"]))
        self.assertNativeConsistency(self.report)

    def test_coherent_omission_of_each_nested_path_or_all_three_is_rejected(self):
        for omitted in [*({path} for path in NESTED_PATHS), set(NESTED_PATHS)]:
            with self.subTest(omitted=sorted(omitted)):
                report = deepcopy(self.report)
                for _, source in source_observations(report):
                    modules = source["submodules"]
                    modules["entries"] = [entry for entry in modules["entries"]
                                          if entry["path"] not in omitted]
                    self.assertEqual(modules["declared_count"], 5)
                    self.assertEqual(len(modules["entries"]), 8 - len(omitted))
                initial = report["source_before"]
                self.assertTrue(all(source == initial
                                    for _, source in source_observations(report)))
                self.assertInvalid(report, "recursive submodule inventory")

    def test_selective_nested_omission_is_rejected_at_every_source_boundary(self):
        for label, _ in source_observations(self.report):
            for path in NESTED_PATHS:
                with self.subTest(observation=label, path=path):
                    report = deepcopy(self.report)
                    source = dict(source_observations(report))[label]
                    source["submodules"]["entries"].remove(submodule(source, path))
                    self.assertInvalid(report, "recursive submodule inventory")

    def test_nested_revision_drift_is_rejected_at_every_source_boundary(self):
        for label, _ in source_observations(self.report):
            for path in NESTED_PATHS:
                with self.subTest(observation=label, path=path):
                    report = deepcopy(self.report)
                    source = dict(source_observations(report))[label]
                    entry = submodule(source, path)
                    self.assertNotEqual(entry["revision"], "f" * 40)
                    entry["revision"] = "f" * 40
                    self.assertInvalid(report, "drift overlaps continued or passing execution")

    def test_source_revision_and_tree_drift_are_rejected_at_every_boundary(self):
        for label, _ in source_observations(self.report):
            for field in ("revision", "tree"):
                with self.subTest(observation=label, field=field):
                    report = deepcopy(self.report)
                    source = dict(source_observations(report))[label]
                    self.assertNotEqual(source[field], "f" * 40)
                    source[field] = "f" * 40
                    self.assertInvalid(report, "drift overlaps continued or passing execution")

    def test_same_sized_inventory_cannot_substitute_a_different_nested_path(self):
        for path in NESTED_PATHS:
            with self.subTest(path=path):
                report = deepcopy(self.report)
                for _, source in source_observations(report):
                    submodule(source, path)["path"] = path + "_replacement"
                    self.assertEqual(len(source["submodules"]["entries"]), 8)
                self.assertInvalid(report, "recursive submodule inventory")

    def test_recursive_count_cannot_replace_the_five_top_level_declarations(self):
        for declared in (0, 4, 6, 8):
            with self.subTest(declared_count=declared):
                report = deepcopy(self.report)
                for _, source in source_observations(report):
                    source["submodules"]["declared_count"] = declared
                self.assertInvalid(report, "recursive submodule inventory")

    def test_coherent_nested_status_mismatches_cannot_claim_a_passing_inventory(self):
        statuses = ("not_initialized", "revision_mismatch", "conflict", "unknown")
        for path in NESTED_PATHS:
            for status in statuses:
                with self.subTest(path=path, status=status):
                    report = deepcopy(self.report)
                    for _, source in source_observations(report):
                        submodule(source, path)["status"] = status
                    reason = ("invalid submodule status" if status == "unknown"
                              else "uninitialized submodule")
                    self.assertInvalid(report, reason)

    def test_coherent_duplicate_nested_entries_are_rejected_even_when_identical(self):
        for path in NESTED_PATHS:
            for conflicting in (False, True):
                with self.subTest(path=path, conflicting_revision=conflicting):
                    report = deepcopy(self.report)
                    for _, source in source_observations(report):
                        duplicate = deepcopy(submodule(source, path))
                        if conflicting:
                            duplicate["revision"] = "f" * 40
                        source["submodules"]["entries"].append(duplicate)
                    self.assertInvalid(report, "duplicate submodules")

    def test_coherent_malformed_nested_revisions_are_rejected(self):
        for path in NESTED_PATHS:
            for revision in (None, "f" * 39, "g" * 40):
                with self.subTest(path=path, revision=revision):
                    report = deepcopy(self.report)
                    for _, source in source_observations(report):
                        submodule(source, path)["revision"] = revision
                    self.assertInvalid(report, "valid hexadecimal identity")

    def test_coherent_inventory_error_cannot_claim_a_passing_observation(self):
        report = deepcopy(self.report)
        for _, source in source_observations(report):
            source["submodules"]["errors"] = ["synthetic recursive inventory error"]
        self.assertInvalid(report, "recursive submodule inventory")

    def test_equal_source_metadata_with_reordered_object_keys_is_stable(self):
        initial = self.report["source_before"]
        for case in self.report["cases"]:
            for stage in ("source_before", "source_after"):
                case[stage] = reverse_object_keys(deepcopy(initial))
                self.assertEqual(case[stage], initial)
                self.assertNotEqual(list(case[stage]), list(initial))
                self.assertNotEqual(list(case[stage]["pins"]), list(initial["pins"]))
        self.assertNativeConsistency(self.report)

    def test_coherent_synthetic_revision_assertions_remain_metadata(self):
        # A well-formed, consistent replacement assertion is not independently
        # authenticatable without the original Git/source objects. Preserve that
        # stated boundary while requiring all eight known paths to remain.
        for _, source in source_observations(self.report):
            source["revision"] = "a" * 40
            source["tree"] = "b" * 40
            for index, entry in enumerate(source["submodules"]["entries"]):
                entry["revision"] = str(index + 1) * 40
        result = self.assertNativeConsistency(self.report)
        self.assertEqual(result["source_revision"], "a" * 40)
        self.assertEqual(result["source_tree"], "b" * 40)
        self.assertTrue(any("do not prove honest execution" in limitation
                            for limitation in result["limitations"]))


if __name__ == "__main__":
    unittest.main()
