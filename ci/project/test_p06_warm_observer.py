# SPDX-License-Identifier: Apache-2.0
"""Fresh-process fault tests of the minimal observer over synthetic native APIs."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tests/regression/ai_warm_workspace"
FIXTURE = ROOT / "ci/project/fixtures/p06_warm_observer_test.cpp"


class WarmObserverFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise AssertionError("Warm observer checks require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-warm-observer-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.environment = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
            "LANG": "C", "LC_ALL": "C", "TMPDIR": str(cls.directory),
            "PYTHONDONTWRITEBYTECODE": "1", "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "MAKEFLAGS": "-j1", "THREADS": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
        }
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (
            Path(__file__).resolve(), FIXTURE, APP / "observer.cpp", APP / "observer.h",
            ROOT / "tests/regression/ai_bench_common/counters.h", ROOT / "sw/runtime/include/vortex2.h",
            ROOT / "VX_config.toml", ROOT / "VX_types.toml", ROOT / "profiles/p02-tfr.json",
            ROOT / "configure", ROOT / "ci/gen_config.py")}
        cls.host([str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                  "--osversion=ubuntu/focal", "--tooldir=" + str(cls.directory / "unused-tools")])
        cls.binary = cls.directory / "observer-fault-test"
        cls.host([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1",
                  "-g0", "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                  "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
                  "-I" + str(cls.directory / "sw"), "-I" + str(APP),
                  "-I" + str(ROOT / "sw/runtime/include"),
                  str(APP / "observer.cpp"), str(FIXTURE), "-o", str(cls.binary)], timeout=45)

    @classmethod
    def host(cls, argv, timeout=30):
        return run_host_command(argv, cwd=cls.directory, env=cls.environment, timeout=timeout)

    def tearDown(self):
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "observer test input changed: " + str(path))

    def run_scenario(self, scenario, *, valid=False):
        output = self.host([str(self.binary), scenario], timeout=10)
        self.assertEqual(len(output.splitlines()), 1, "observer emitted unexpected stdout/stderr")
        row = json.loads(output)
        self.assertIs(row["passed"], True)
        self.assertEqual(row["scenario"], scenario)
        self.assertEqual(row["native"]["address_queries"], 0)
        if valid:
            self.assertEqual(row["counts"]["errors"], 0)
            self.assertEqual(row["counts"]["premature_releases"], 0)
        else:
            self.assertGreater(row["counts"]["errors"] + row["counts"]["premature_releases"], 0)
        return row

    def test_complete_default_batch_has_fixed_silent_query_free_wrappers(self):
        row = self.run_scenario("default", valid=True)
        self.assertEqual(row["counts"]["buffer_create_calls"], 99)
        self.assertEqual(row["counts"]["buffer_release_calls"], 99)
        self.assertEqual(row["native"], {
            "opens": 1, "releases": 1, "creates": 99, "frees": 99,
            "memory_queries": 5, "capability_queries": 52, "counter_queries": 132, "address_queries": 0})

    def test_resident_batch_has_three_allocations_and_restores_memory(self):
        row = self.run_scenario("resident", valid=True)
        self.assertEqual(row["counts"]["buffer_create_calls"], 3)
        self.assertEqual(row["counts"]["buffer_release_calls"], 3)
        self.assertEqual(row["counts"]["peak_requested_payload_bytes"], 320)
        self.assertEqual(row["counts"]["live_requested_bytes"], 0)
        self.assertEqual(row["native"]["counter_queries"], 132)

    def test_invalid_device_open_arguments_phases_duplicates_and_failures(self):
        for scenario in ("open_index", "open_phase", "open_duplicate", "open_null_out",
                         "open_null_handle", "open_failed", "open_throw"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_allocation_arguments_phases_handles_capacity_and_limit_are_rejected(self):
        for scenario in ("create_no_device", "create_wrong_device", "create_size", "create_flags",
                         "create_idle", "create_closing", "create_owner_close", "create_duplicate",
                         "create_slots", "create_limit", "create_null_out", "create_null_handle"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_native_allocation_errors_and_exceptions_cannot_look_successful(self):
        for scenario in ("create_failed", "create_throw"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_buffer_cleanup_is_forwarded_despite_phase_handle_and_native_faults(self):
        for scenario in ("buffer_idle", "buffer_submit", "buffer_create", "buffer_no_device",
                         "buffer_unknown", "buffer_null", "buffer_failed", "buffer_throw"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_owner_cleanup_is_forwarded_despite_phase_handle_live_and_native_faults(self):
        for scenario in ("device_idle", "device_live", "device_unknown", "device_null",
                         "device_failed", "device_throw"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_memory_capability_and_counter_failures_are_retained_as_errors(self):
        for scenario in ("query_memory_failed", "query_memory_throw", "query_capability_failed",
                         "query_capability_throw", "query_counter_failed", "query_counter_throw"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
