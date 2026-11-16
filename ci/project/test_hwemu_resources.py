# SPDX-License-Identifier: Apache-2.0
"""Independent resource and directory boundaries for the inert hw_emu planner."""

from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
import os
import unittest
from unittest import mock

from hwemu_fixture import HwemuFixture
import hwemu_plan


GIB = 1024 ** 3
DIRECTORY_BLOCKER = "a required directory is missing, unsafe, changed, or unreadable"
RECHECK_BLOCKER = "retained inputs or directories changed during inspection"
MEMORY_BLOCKER = "available host memory is unknown or below the declared RSS budget"


class HwemuResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HwemuFixture()
        cls.addClassCleanup(cls.fixture.close)

    def setUp(self):
        self.manifest = deepcopy(self.fixture.manifest)

    def resource_paths(self):
        fixture = self.fixture
        return {
            "source": fixture.source,
            "build": fixture.build,
            "native_tools": fixture.tools,
            "vendor_vitis": fixture.vendor / "vitis",
            "vendor_vivado": fixture.vendor / "vivado",
            "vendor_xrt": fixture.vendor / "xrt",
            "files_vpp": fixture.vendor / "vitis/bin",
            "files_vivado": fixture.vendor / "vivado/bin",
            "files_emconfigutil": fixture.vendor / "vitis/bin",
            "files_platforminfo": fixture.vendor / "vitis/bin",
            "files_xrt_header": fixture.vendor / "xrt/include",
            "files_xrt_library": fixture.vendor / "xrt/lib",
            "files_platform": fixture.vendor / "platform",
            "files_xclbin": fixture.artifacts,
            "files_emconfig": fixture.artifacts,
            "files_build_receipt": fixture.base,
            "files_xsim_hook": fixture.source / "sw/runtime/xrt",
        }

    def resources(self):
        return {
            "free_disk_bytes": {label: 32 * GIB for label in self.resource_paths()},
            "available_memory_bytes": 8 * GIB,
            "cgroup_limit_bytes": None,
        }

    def plan_with_samples(self, *samples):
        with mock.patch("hwemu_plan._sample_resources", side_effect=samples) as sample:
            report = hwemu_plan.create_plan(self.manifest)
        self.assertEqual(sample.call_count, len(samples))
        for call in sample.call_args_list:
            self.assertEqual(set(call.args[0]), set(self.resource_paths()))
        return report

    def assert_boundaries(self, report):
        for field in ("execution_performed", "phase_complete", "launch_ready",
                      "vendor_qualification_verified"):
            self.assertIs(report[field], False)
        self.assertEqual(report["vendor_qualification"], "unverified")
        self.assertEqual(report["acceptance_id"], "P01-A03")
        self.assertEqual(report["acceptance_outcome"], "blocked")
        self.assertTrue(report["limitations"])

    def assert_blocked(self, report, blockers):
        self.assert_boundaries(report)
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertIs(report["input_consistency_verified"], False)
        self.assertIsNone(report["candidate"])
        self.assertEqual(report["blockers"], blockers)

    def assert_planned(self, report):
        self.assert_boundaries(report)
        self.assertEqual(report["outcome"], "planned", report["blockers"])
        self.assertEqual(report["blockers"], [])
        self.assertIs(report["input_consistency_verified"], True)
        self.assertIsNotNone(report["candidate"])
        self.assertIs(report["candidate"]["supervision_required"], True)
        self.assertEqual(set(report["resources"]), {"initial", "final"})

    @staticmethod
    def disk_blocker(label):
        return "disk reserve is unavailable or insufficient for " + label

    def test_every_resource_directory_has_the_expected_retained_identity(self):
        with ExitStack() as stack:
            directories = hwemu_plan._open_directories(self.manifest, stack)
            self.assertEqual(set(directories), set(self.resource_paths()))
            for label, path in self.resource_paths().items():
                with self.subTest(label=label):
                    retained = os.fstat(directories[label].fd)
                    expected = path.stat()
                    self.assertEqual((retained.st_dev, retained.st_ino),
                                     (expected.st_dev, expected.st_ino))
            self.assertIs(directories["files_xclbin"], directories["files_emconfig"])
            self.assertIs(directories["files_vpp"], directories["files_platforminfo"])
            self.assertIs(directories["files_vpp"], directories["files_emconfigutil"])

    def test_each_directory_below_the_disk_reserve_blocks_before_input_checks(self):
        for label in self.resource_paths():
            with self.subTest(label=label):
                resources = self.resources()
                resources["free_disk_bytes"][label] = self.manifest["budget"]["min_free_bytes"] - 1
                report = self.plan_with_samples(resources)
                self.assert_blocked(report, [self.disk_blocker(label)])
                self.assertEqual(report["resources"], {"initial": resources})
                self.assertIsNone(report["source"])
                self.assertEqual(report["checked_input_count"], 0)

    def test_unknown_disk_space_blocks_for_each_directory(self):
        for label in self.resource_paths():
            with self.subTest(label=label):
                resources = self.resources()
                resources["free_disk_bytes"][label] = None
                self.assert_blocked(self.plan_with_samples(resources),
                                    [self.disk_blocker(label)])

    def test_exact_disk_reserve_is_accepted_for_every_directory(self):
        resources = self.resources()
        resources["free_disk_bytes"] = {
            label: self.manifest["budget"]["min_free_bytes"]
            for label in self.resource_paths()
        }
        self.assertEqual(self.manifest["budget"]["min_free_bytes"], 15 * GIB)
        report = self.plan_with_samples(deepcopy(resources), deepcopy(resources))
        self.assert_planned(report)
        self.assertEqual(report["resources"], {"initial": resources, "final": resources})

    def test_unknown_or_insufficient_host_memory_blocks_initial_inspection(self):
        for memory in (None, 0, self.manifest["budget"]["max_rss_bytes"] - 1):
            with self.subTest(memory=memory):
                resources = self.resources()
                resources["available_memory_bytes"] = memory
                report = self.plan_with_samples(resources)
                self.assert_blocked(report, [MEMORY_BLOCKER])
                self.assertEqual(report["resources"], {"initial": resources})
                self.assertIsNone(report["source"])

    def test_exact_host_memory_budget_is_accepted(self):
        resources = self.resources()
        resources["available_memory_bytes"] = self.manifest["budget"]["max_rss_bytes"]
        report = self.plan_with_samples(deepcopy(resources), deepcopy(resources))
        self.assert_planned(report)
        self.assertIsNone(report["resources"]["initial"]["cgroup_limit_bytes"])
        self.assertIsNone(report["resources"]["final"]["cgroup_limit_bytes"])

    def test_each_directory_dropping_below_reserve_at_final_sample_blocks_candidate(self):
        for label in self.resource_paths():
            with self.subTest(label=label):
                initial, final = self.resources(), self.resources()
                final["free_disk_bytes"][label] = self.manifest["budget"]["min_free_bytes"] - 1
                report = self.plan_with_samples(initial, final)
                self.assert_blocked(report, [self.disk_blocker(label)])
                self.assertEqual(report["resources"], {"initial": initial, "final": final})
                self.assertEqual(report["source"], self.fixture.source_observation)

    def test_unknown_or_insufficient_final_memory_prevents_candidate(self):
        for memory in (None, self.manifest["budget"]["max_rss_bytes"] - 1):
            with self.subTest(memory=memory):
                initial, final = self.resources(), self.resources()
                final["available_memory_bytes"] = memory
                report = self.plan_with_samples(initial, final)
                self.assert_blocked(report, [MEMORY_BLOCKER])
                self.assertEqual(report["resources"], {"initial": initial, "final": final})
                self.assertEqual(report["source"], self.fixture.source_observation)

    def test_simultaneous_disk_and_memory_shortages_are_all_retained(self):
        resources = self.resources()
        resources["free_disk_bytes"] = {label: 0 for label in self.resource_paths()}
        resources["available_memory_bytes"] = None
        expected = [self.disk_blocker(label) for label in self.resource_paths()]
        self.assert_blocked(self.plan_with_samples(resources), expected + [MEMORY_BLOCKER])

    def test_initial_and_final_resource_errors_are_redacted(self):
        private = "/private/resource-customer-token secret=not-for-report"
        for final in (False, True):
            for error in (OSError, ValueError, TypeError, KeyError, AttributeError):
                with self.subTest(final=final, error=error.__name__):
                    samples = [self.resources()] if final else []
                    samples.append(error(private))
                    report = self.plan_with_samples(*samples)
                    blocker = ("final resource observations are unavailable" if final
                               else "resource observations are unavailable")
                    self.assert_blocked(report, [blocker])
                    self.assertNotIn(private, json.dumps(report))
                    self.assertNotIn(str(self.fixture.base), json.dumps(report))
                    self.assertEqual(set(report["resources"]), {"initial"} if final else set())

    def test_invalid_memory_observations_are_reported_as_unknown(self):
        with ExitStack() as stack:
            directories = hwemu_plan._open_directories(self.manifest, stack)
            for memory in (None, -1, True, False, 1.5, "6442450944"):
                with self.subTest(memory=memory), mock.patch(
                        "hwemu_plan.preflight.available_memory_bytes", return_value=memory):
                    resources = hwemu_plan._sample_resources(directories)
                self.assertIsNone(resources["available_memory_bytes"])
                self.assertIsNone(resources["cgroup_limit_bytes"])
                self.assertEqual(set(resources["free_disk_bytes"]), set(self.resource_paths()))

    def test_real_resource_record_drives_the_result_without_host_capacity_assumptions(self):
        report = hwemu_plan.create_plan(self.manifest)
        self.assertIn("initial", report["resources"])
        expected_blockers = []
        for stage, resources in report["resources"].items():
            with self.subTest(stage=stage):
                self.assertEqual(set(resources["free_disk_bytes"]), set(self.resource_paths()))
                self.assertIsNone(resources["cgroup_limit_bytes"])
                for label, available in resources["free_disk_bytes"].items():
                    if available is not None:
                        self.assertIs(type(available), int)
                        self.assertGreaterEqual(available, 0)
                    if available is None or available < self.manifest["budget"]["min_free_bytes"]:
                        expected_blockers.append(self.disk_blocker(label))
                memory = resources["available_memory_bytes"]
                if memory is not None:
                    self.assertIs(type(memory), int)
                    self.assertGreaterEqual(memory, 0)
                if memory is None or memory < self.manifest["budget"]["max_rss_bytes"]:
                    expected_blockers.append(MEMORY_BLOCKER)
        if expected_blockers:
            self.assert_blocked(report, expected_blockers)
        else:
            self.assert_planned(report)

    @contextmanager
    def replaced_directory(self, path, *, symlink):
        retained = path.with_name(path.name + ".resource-test-retained")
        self.assertFalse(retained.exists())
        path.rename(retained)
        try:
            if symlink:
                path.symlink_to(retained, target_is_directory=True)
            else:
                path.mkdir()
            try:
                yield
            finally:
                if symlink:
                    path.unlink()
                else:
                    path.rmdir()
        finally:
            retained.rename(path)

    def test_symlinked_native_tools_vendor_roots_and_artifact_directories_are_rejected(self):
        paths = {"native_tools": self.fixture.tools, "artifacts": self.fixture.artifacts}
        paths.update({"vendor_" + name: self.fixture.vendor / name
                      for name in ("vitis", "vivado", "xrt")})
        for label, path in paths.items():
            with self.subTest(label=label), self.replaced_directory(path, symlink=True), \
                    mock.patch("hwemu_plan._sample_resources") as sample:
                report = hwemu_plan.create_plan(self.manifest)
                self.assert_blocked(report, [DIRECTORY_BLOCKER])
                self.assertEqual(report["resources"], {})
                self.assertIsNone(report["source"])
                sample.assert_not_called()

    def test_parent_directory_replacement_after_source_observation_blocks_candidate(self):
        paths = {
            "source": self.fixture.source,
            "vendor_binary_parent": self.fixture.vendor / "vitis/bin",
            "native_tools": self.fixture.tools,
        }
        observe_source = hwemu_plan.observe_source
        for label, path in paths.items():
            for symlink in (False, True):
                with self.subTest(label=label, symlink=symlink), ExitStack() as stack:
                    observations = []

                    def replace_after_final_observation(root):
                        observation = observe_source(root)
                        observations.append(observation)
                        if len(observations) == 2:
                            stack.enter_context(self.replaced_directory(path, symlink=symlink))
                        return observation

                    stack.enter_context(mock.patch("hwemu_plan.observe_source",
                                                   side_effect=replace_after_final_observation))
                    initial = self.resources()
                    report = self.plan_with_samples(initial)
                    self.assertEqual(observations, [self.fixture.source_observation] * 2)
                    self.assert_blocked(report, [RECHECK_BLOCKER])
                    self.assertEqual(report["resources"], {"initial": initial})


if __name__ == "__main__":
    unittest.main()
