# SPDX-License-Identifier: Apache-2.0
"""Exercise the complete inert planner against real synthetic source/build inputs."""

from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import unittest
from unittest import mock

from hwemu_fixture import HwemuFixture, identity
from hwemu_io import InputError
import hwemu_plan


GIB = 1024 ** 3
FILE_ROLES = (
    "vpp", "vivado", "emconfigutil", "platforminfo", "xrt_header",
    "xrt_library", "platform", "xclbin", "emconfig", "build_receipt",
    "xsim_hook",
)
GENERATED_PATHS = (
    ".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
    "hw/VX_config.vh", "hw/VX_types.vh", "ci/blackbox.sh", "ci/gen_config.py",
    "sw/kernel/Makefile", "sw/runtime/stub/Makefile", "sw/runtime/common.mk",
    "sw/runtime/xrt/Makefile", "sw/runtime/xrt/xrt.ini",
    "sw/runtime/xrt_config.stamp", "tests/regression/demo/Makefile",
    "tests/regression/demo/config.stamp", "tests/regression/common.mk",
    "hw/syn/xilinx/xrt/Makefile", "hw/syn/xilinx/common.mk",
    "hw/syn/xilinx/platform.mk",
)
INITIAL_SOURCE_BLOCKER = (
    "source identity, cleanliness, or submodule provenance is inconsistent"
)
FINAL_SOURCE_BLOCKER = "source identity or submodule state changed during inspection"
RECEIPT_BLOCKER = "build receipt is malformed or differs from the declared inputs"
RECHECK_BLOCKER = "retained inputs or directories changed during inspection"


class HwemuPlanIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HwemuFixture()
        cls.addClassCleanup(cls.fixture.close)

    def setUp(self):
        self.manifest = deepcopy(self.fixture.manifest)

    @staticmethod
    def ample_resources(directories):
        # The fixture can live on a small /tmp filesystem. Keep the production
        # 15-GiB reserve intact and replace only the host resource observation.
        return {
            "free_disk_bytes": {label: 32 * GIB for label in directories},
            "available_memory_bytes": 8 * GIB,
            "cgroup_limit_bytes": None,
        }

    def plan(self, manifest=None):
        with mock.patch("hwemu_plan._sample_resources",
                        side_effect=self.ample_resources):
            return hwemu_plan.create_plan(self.manifest if manifest is None else manifest)

    @contextmanager
    def preserve_file(self, path):
        original = path.read_bytes()
        metadata = path.stat()
        try:
            yield
        finally:
            path.write_bytes(original)
            path.chmod(stat.S_IMODE(metadata.st_mode))
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

    @contextmanager
    def changed(self, path, content):
        with self.preserve_file(path):
            path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
            yield

    @contextmanager
    def absent(self, path):
        retained = path.with_name(path.name + ".planner-test-retained")
        self.assertFalse(retained.exists())
        path.rename(retained)
        try:
            yield
        finally:
            retained.rename(path)

    @contextmanager
    def added(self, path, content):
        self.assertFalse(path.exists())
        path.write_text(content, encoding="utf-8")
        try:
            yield
        finally:
            path.unlink()

    @contextmanager
    def rebound_receipt(self, receipt, manifest):
        content = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
        with self.changed(self.fixture.receipt_path, content):
            manifest["files"]["build_receipt"] = identity(self.fixture.receipt_path)
            yield

    def assert_boundaries(self, report):
        self.assertIs(report["execution_performed"], False)
        self.assertIs(report["phase_complete"], False)
        self.assertIs(report["launch_ready"], False)
        self.assertIs(report["vendor_qualification_verified"], False)
        self.assertEqual(report["vendor_qualification"], "unverified")
        self.assertEqual(report["acceptance_id"], "P01-A03")
        self.assertEqual(report["acceptance_outcome"], "blocked")
        self.assertTrue(report["limitations"])

    def assert_blocked(self, report, blocker=None):
        self.assert_boundaries(report)
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertIs(report["input_consistency_verified"], False)
        self.assertIsNone(report["candidate"])
        self.assertTrue(report["blockers"])
        if blocker is not None:
            self.assertEqual(report["blockers"], [blocker])

    def snapshot(self):
        result = {}
        for path in self.fixture.base.rglob("*"):
            metadata = path.lstat()
            if path.is_file():
                result[str(path.relative_to(self.fixture.base))] = (
                    metadata.st_mode, metadata.st_size, metadata.st_mtime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            elif path.is_dir():
                result[str(path.relative_to(self.fixture.base))] = (metadata.st_mode,)
            else:
                self.fail("the synthetic fixture unexpectedly contains a special input")
        return result

    def test_complete_fixture_plans_with_real_source_and_build_checks(self):
        self.assertEqual(set(self.manifest["files"]), set(FILE_ROLES))
        self.assertEqual(set(self.manifest["generated"]), set(GENERATED_PATHS))
        self.assertEqual(self.manifest["budget"]["min_free_bytes"], 15 * GIB)
        original = deepcopy(self.manifest)
        before = self.snapshot()
        with mock.patch("hwemu_plan._sample_resources",
                        side_effect=self.ample_resources) as sample:
            report = hwemu_plan.create_plan(self.manifest)
        self.assertEqual(report["outcome"], "planned", report["blockers"])
        self.assertIs(report["input_consistency_verified"], True)
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["source"], self.fixture.source_observation)
        self.assert_boundaries(report)
        self.assertEqual(sample.call_count, 2)
        self.assertEqual(set(report["resources"]), {"initial", "final"})
        declared_count = len(FILE_ROLES) + len(GENERATED_PATHS)
        self.assertGreater(report["checked_input_count"], declared_count)
        declared_bytes = sum(item["size_bytes"] for item in self.manifest["files"].values())
        declared_bytes += sum(item["size_bytes"] for item in self.manifest["generated"].values())
        self.assertGreaterEqual(report["checked_input_bytes"], declared_bytes)
        self.assertLessEqual(report["checked_input_bytes"], self.manifest["budget"]["max_input_bytes"])
        self.assertEqual(self.manifest, original)
        self.assertEqual(self.snapshot(), before)

    def test_candidate_has_exact_frozen_arguments_and_fresh_environment(self):
        poisoned = {
            "HWEMU_PRIVATE_TEST_VALUE": "must-not-be-inherited",
            "CONFIGS": "-DXRTSIM", "PROFILE": "unexpected", "MAKEFLAGS": "-j99",
            "JOBS": "99", "CCACHE_DISABLE": "0", "XRT_DEVICE_INDEX": "7",
            "VORTEX_XRT_WAVEFORM": "1", "XILINX_VITIS": "/private/unrelated",
        }
        with mock.patch.dict(os.environ, poisoned):
            report = self.plan()
        self.assertEqual(report["outcome"], "planned", report["blockers"])
        candidate = report["candidate"]
        self.assertEqual(candidate["cwd"], str(self.fixture.build))
        self.assertEqual(candidate["argv"], [
            "./ci/blackbox.sh", "--driver=xrt", "--target=hw_emu", "--app=demo", "--args=-n1",
        ])
        self.assertEqual(candidate["environment"], {
            "PATH": f"{self.fixture.vendor}/vitis/bin:{self.fixture.vendor}/vivado/bin:/usr/bin:/bin",
            "LANG": "C", "LC_ALL": "C",
            "CONFIGS": "-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 "
                       "-DVX_CFG_NUM_WARPS=4 -DVX_CFG_NUM_THREADS=4 "
                       "-DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_FPU_TYPE_STD",
            "PROFILE": "", "XILINX_VITIS": str(self.fixture.vendor / "vitis"),
            "XILINX_VIVADO": str(self.fixture.vendor / "vivado"),
            "XILINX_XRT": str(self.fixture.vendor / "xrt"),
            "PLATFORM": self.manifest["files"]["platform"]["path"],
            "FPGA_BIN_DIR": str(self.fixture.artifacts),
            "MAKEFLAGS": "-j2", "JOBS": "2", "MAX_JOBS": "2", "THREADS": "2",
            "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "VORTEX_XRT_WAVEFORM": "0", "XRT_DEVICE_INDEX": "0",
        })
        self.assertIs(candidate["inherit_environment"], False)
        self.assertIs(candidate["supervision_required"], True)
        self.assertEqual(candidate["budget"], self.manifest["budget"])
        candidate["budget"]["jobs"] = 1
        self.assertEqual(self.manifest["budget"]["jobs"], 2)
        self.assert_boundaries(report)

    def test_missing_role_and_generated_declarations_are_blocked(self):
        for section, names in (("files", FILE_ROLES), ("generated", GENERATED_PATHS)):
            for name in names:
                with self.subTest(section=section, name=name):
                    manifest = deepcopy(self.manifest)
                    del manifest[section][name]
                    self.assert_blocked(self.plan(manifest),
                                        "manifest does not satisfy the frozen emulation contract")

    def test_every_declared_file_must_exist(self):
        for role in FILE_ROLES:
            path = Path(self.manifest["files"][role]["path"])
            with self.subTest(role=role), self.absent(path):
                # The hook is tracked source; its absence must fail the earlier
                # real Git cleanliness check before the input loop is reached.
                blocker = INITIAL_SOURCE_BLOCKER if role == "xsim_hook" else (
                    "declared " + role + " input is missing, unsafe, changed, or mismatched")
                self.assert_blocked(self.plan(), blocker)

    def test_every_declared_file_size_and_digest_are_checked(self):
        for role in FILE_ROLES:
            for field in ("size_bytes", "sha256"):
                with self.subTest(role=role, field=field):
                    manifest = deepcopy(self.manifest)
                    declared = manifest["files"][role]
                    declared[field] = (declared[field] + 1 if field == "size_bytes"
                                       else "0" * 64)
                    self.assert_blocked(self.plan(manifest),
                                        "declared " + role + " input is missing, unsafe, changed, or mismatched")

    def test_every_generated_file_must_exist_and_match_both_identity_fields(self):
        for relative in GENERATED_PATHS:
            blocker = "generated " + relative + " identity is missing, unsafe, changed, or mismatched"
            with self.subTest(path=relative, mutation="missing"), \
                    self.absent(self.fixture.build / relative):
                self.assert_blocked(self.plan(), blocker)
            for field in ("size_bytes", "sha256"):
                with self.subTest(path=relative, mutation=field):
                    manifest = deepcopy(self.manifest)
                    declared = manifest["generated"][relative]
                    declared[field] = (declared[field] + 1 if field == "size_bytes"
                                       else "0" * 64)
                    self.assert_blocked(self.plan(manifest), blocker)

    def test_rehashed_receipt_cannot_change_independent_declarations(self):
        original = json.loads(self.fixture.receipt_path.read_text(encoding="utf-8"))
        mutations = {
            "source": lambda receipt: receipt["source"].update(revision="0" * 40),
            "build": lambda receipt: receipt["build"].update(tool_dir=str(self.fixture.base / "other-tools")),
            "vendor": lambda receipt: receipt["vendor"]["vitis"].update(release="different-release"),
            "file": lambda receipt: receipt["files"]["vpp"].update(sha256="0" * 64),
            "generated": lambda receipt: receipt["generated"][".config.stamp"].update(sha256="0" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(binding=name):
                manifest = deepcopy(self.manifest)
                receipt = deepcopy(original)
                mutate(receipt)
                with self.rebound_receipt(receipt, manifest):
                    self.assert_blocked(self.plan(manifest), RECEIPT_BLOCKER)

    def test_rehashed_generated_shim_is_blocked_by_the_build_content_check(self):
        path = self.fixture.build / "sw/runtime/xrt_config.stamp"
        with self.changed(path, path.read_bytes().rstrip(b"\n") + b" -DXRTSIM\n"):
            self.manifest["generated"]["sw/runtime/xrt_config.stamp"] = identity(path, include_path=False)
            receipt = deepcopy({key: value for key, value in self.manifest.items() if key != "budget"})
            del receipt["files"]["build_receipt"]
            with self.rebound_receipt(receipt, self.manifest):
                self.assert_blocked(self.plan(),
                                    "generated build content does not satisfy the frozen source and runtime contract")

    def source_drifts(self):
        clean = self.fixture.source_observation
        result = []
        for key in ("revision", "tree"):
            changed = deepcopy(clean)
            changed[key] = "0" * 40
            result.append((key, changed))
        changed = deepcopy(clean)
        changed.update(dirty=True, clean=False)
        result.append(("dirty", changed))
        changed = deepcopy(clean)
        changed["submodules"]["at_recorded_revisions"] = False
        result.append(("submodule_revision", changed))
        changed = deepcopy(clean)
        changed["submodules"]["errors"] = ["submodule observation failed"]
        result.append(("submodule_error", changed))
        return result

    def test_initial_source_commit_tree_dirty_and_submodule_drift_are_blocked(self):
        for name, changed in self.source_drifts():
            with self.subTest(state=name), mock.patch(
                    "hwemu_plan.observe_source", return_value=changed) as observe:
                self.assert_blocked(self.plan(), INITIAL_SOURCE_BLOCKER)
                observe.assert_called_once_with(str(self.fixture.source))

    def test_final_source_commit_tree_dirty_and_submodule_drift_are_blocked(self):
        for name, changed in self.source_drifts():
            with self.subTest(state=name), mock.patch(
                    "hwemu_plan.observe_source",
                    side_effect=[deepcopy(self.fixture.source_observation), changed]) as observe:
                self.assert_blocked(self.plan(), FINAL_SOURCE_BLOCKER)
                self.assertEqual(observe.call_count, 2)

    def test_final_source_must_equal_the_entire_initial_observation(self):
        changed = deepcopy(self.fixture.source_observation)
        changed["submodules"].update(declared_count=1, observed_count=1, initialized_count=1)
        with mock.patch("hwemu_plan.observe_source",
                        side_effect=[deepcopy(self.fixture.source_observation), changed]):
            self.assert_blocked(self.plan(), FINAL_SOURCE_BLOCKER)

    def test_real_tracked_and_untracked_source_changes_are_blocked_and_redacted(self):
        tracked = self.fixture.source / "SYNTHETIC.md"
        with self.changed(tracked, tracked.read_bytes() + b"private-source-content\n"):
            self.assert_blocked(self.plan(), INITIAL_SOURCE_BLOCKER)
        private_name = "private-source-token.txt"
        with self.added(self.fixture.source / private_name, "private-source-content\n"):
            report = self.plan()
            self.assert_blocked(report, INITIAL_SOURCE_BLOCKER)
            encoded = json.dumps(report)
            self.assertNotIn(private_name, encoded)
            self.assertNotIn("private-source-content", encoded)
            self.assertNotIn(str(self.fixture.base), encoded)

    def test_retained_input_changes_are_caught_after_the_build_check(self):
        path = self.fixture.artifacts / "vortex_afu.xclbin"
        check_build = hwemu_plan.check_build

        def change_after_build_check(inputs, manifest):
            check_build(inputs, manifest)
            path.write_bytes(path.read_bytes() + b"changed after inspection\n")

        with self.preserve_file(path), mock.patch(
                "hwemu_plan.check_build", side_effect=change_after_build_check) as check:
            self.assert_blocked(self.plan(), RECHECK_BLOCKER)
            self.assertEqual(check.call_count, 1)

    def test_caught_exception_details_are_not_disclosed(self):
        private = "/private/customer-token.bin secret=do-not-publish"
        for exception in (ValueError, OSError, TypeError, KeyError, AttributeError):
            with self.subTest(exception=exception.__name__), mock.patch(
                    "hwemu_plan.Inputs.check_file", side_effect=exception(private)):
                report = self.plan()
                self.assert_blocked(report,
                                    "declared vpp input is missing, unsafe, changed, or mismatched")
                self.assertNotIn(private, json.dumps(report))
                self.assertNotIn(str(self.fixture.base), json.dumps(report))
        with hwemu_plan.Inputs() as inputs, \
                mock.patch.object(inputs, "recheck", side_effect=InputError(private)), \
                mock.patch("hwemu_plan.Inputs", return_value=inputs):
            report = self.plan()
            self.assert_blocked(report, RECHECK_BLOCKER)
            self.assertNotIn(private, json.dumps(report))

    def test_malformed_rehashed_receipt_does_not_disclose_its_contents(self):
        private = "customer-receipt-secret"
        with self.changed(self.fixture.receipt_path, '{"private":"' + private + '",'):
            self.manifest["files"]["build_receipt"] = identity(self.fixture.receipt_path)
            report = self.plan()
        self.assert_blocked(report, RECEIPT_BLOCKER)
        self.assertNotIn(private, json.dumps(report))

    def test_planning_invokes_only_read_only_git_and_never_vendor_or_setup(self):
        popen = subprocess.Popen
        calls = []

        def read_only_git(argv, *arguments, **keywords):
            self.assertIsInstance(argv, (list, tuple))
            self.assertEqual(argv[0], "git")
            self.assertFalse(keywords.get("shell", False))
            command = argv[argv.index("-C") + 2:]
            self.assertIn(tuple(command), (
                ("config", "--includes", "--null", "--name-only", "--get-regexp",
                 r"^(filter\..*\.(clean|process)|extensions\.partialclone|remote\..*\.promisor)$"),
                ("rev-parse", "--show-toplevel"),
                ("rev-parse", "--verify", "HEAD"),
                ("rev-parse", "--verify", "HEAD^{tree}"),
                ("ls-files", "-v", "--stage", "-z"),
                ("ls-tree", "-r", "-z", "HEAD"),
                ("ls-files", "--others", "--exclude-standard", "-z"),
            ))
            calls.append(tuple(argv))
            return popen(argv, *arguments, **keywords)

        marker = self.fixture.base / "setup-was-executed"
        script = "#!/bin/sh\nprintf 'unexpected setup execution' > " + str(marker) + "\n"
        setup_paths = (
            self.fixture.vendor / "vitis/settings64.sh",
            self.fixture.vendor / "vivado/settings64.sh",
            self.fixture.vendor / "xrt/setup.sh",
        )
        with ExitStack() as stack:
            for path in setup_paths:
                stack.enter_context(self.added(path, script))
                path.chmod(0o755)
            before = self.snapshot()
            stack.enter_context(mock.patch("subprocess.Popen", side_effect=read_only_git))
            stack.enter_context(mock.patch("os.system", side_effect=AssertionError("shell execution")))
            report = self.plan()
            self.assertEqual(report["outcome"], "planned", report["blockers"])
            self.assertTrue(calls)
            self.assertFalse(marker.exists())
            self.assertEqual(self.snapshot(), before)
            self.assert_boundaries(report)


if __name__ == "__main__":
    unittest.main()
