# SPDX-License-Identifier: Apache-2.0
"""Link the real benchmark observer to bounded host mocks; no GPU execution."""

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
OBSERVER = ROOT / "tests/regression/ai_bench_common/observer.cpp"
FIXTURES = ROOT / "ci/project/fixtures"
CONTRACT = ROOT / "ci/project/p06_benchmark_contract.json"


class BenchmarkObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("c++")
        if compiler is None:
            raise unittest.SkipTest("Benchmark observer tests require a host C++17 compiler")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-observer-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "observer-test"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "XLEN": "64",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        inputs = [OBSERVER, OBSERVER.with_name("counters.h"), CONTRACT,
                  FIXTURES / "p06_observer_api.cpp", FIXTURES / "p06_observer_caller.cpp",
                  ROOT / "VX_config.toml", ROOT / "VX_types.toml",
                  ROOT / "profiles/p02-tfr.json", ROOT / "ci/gen_config.py",
                  ROOT / "sw/runtime/include/vortex2.h"]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        for name in ("VX_config", "VX_types"):
            profile = (["--profile=p02-tfr", "--xlen=64", "--cflags=-DVX_CFG_XLEN=64"]
                       if name == "VX_config" else [])
            run_host_command([
                sys.executable, str(ROOT / "ci/gen_config.py"),
                "--config=" + str(ROOT / (name + ".toml")), "--format=cpp", "--resolved",
                "--output=" + str(cls.build / (name + ".h")), *profile,
            ], cwd=cls.build, env=cls.environment, timeout=30)
        # Separate caller/API translation units force the actual GNU --wrap link seam.
        run_host_command([
            compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
            "-I", str(cls.build), "-I", str(ROOT / "sw/runtime/include"),
            str(OBSERVER), str(FIXTURES / "p06_observer_api.cpp"),
            str(FIXTURES / "p06_observer_caller.cpp"),
            "-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release", "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=30)

    def run_case(self, scenario="happy", *, sample="fp16-single-measurement-0", fail_at=1):
        env = dict(self.environment, P06_TEST_CASE=scenario, P06_FAIL_N=str(fail_at))
        if sample is not None:
            env["P06_SAMPLE_ID"] = sample
        output = run_host_command([str(self.binary)], cwd=self.build, env=env, timeout=10)
        events = []
        for line in output.splitlines():
            if line.startswith(("P06_", "MOCK_")):
                marker, body = line.split(" ", 1)
                events.append((marker, json.loads(body)))
        summary = self.rows(events, "MOCK_SUMMARY")
        self.assertEqual(len(summary), 1, output)
        self.assertEqual(summary[0]["invalid_queries"], 0, output)
        self.assertEqual(summary[0]["queries_after_release"], 0, output)
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed during observer host tests: " + str(path))
        return events, summary[0]

    @staticmethod
    def rows(events, marker):
        return [body for name, body in events if name == marker]

    def failures(self, events):
        return [row["reason"] for row in self.rows(events, "P06_FAILURE")]

    def test_exact_contract_descriptors_and_real_query_arguments(self):
        events, summary = self.run_case()
        self.assertEqual(self.failures(events), [])
        self.assertEqual(summary, {"opens": 1, "releases": 1, "capabilities": 26,
                                  "counters": 66, "invalid_queries": 0,
                                  "queries_after_release": 0, "live_handles": 0})
        snapshots = self.rows(events, "P06_BEGIN") + self.rows(events, "P06_END")
        self.assertEqual(len(snapshots), 2)
        wanted_caps = self.contract["capabilities"]
        wanted_counters = [{key: value for key, value in row.items()
                            if key not in ("class_macro", "csr_macro")}
                           for row in self.contract["counters"]]
        enabled = []
        for snapshot in snapshots:
            self.assertEqual(set(snapshot), {"schema_version", "sample_id", "context_id",
                                            "device_index", "compiled_memory_block_bytes",
                                            "query_begin_ns", "query_end_ns", "capabilities",
                                            "counters"})
            self.assertEqual(snapshot["schema_version"], 1)
            self.assertEqual(snapshot["context_id"], 1)
            self.assertEqual(snapshot["device_index"], 0)
            self.assertEqual(snapshot["compiled_memory_block_bytes"], 64)
            self.assertLessEqual(snapshot["query_begin_ns"], snapshot["query_end_ns"])
            self.assertEqual([{key: row[key] for key in ("name", "id")}
                              for row in snapshot["capabilities"]], wanted_caps)
            for row in snapshot["capabilities"]:
                self.assertEqual(row["status"], 0)
                self.assertEqual(row["value"], self.contract["capability_values"][row["name"]])
            self.assertEqual([{key: value for key, value in row.items()
                               if key not in ("enabled", "status", "value")}
                              for row in snapshot["counters"]], wanted_counters)
            enabled = [row for row in snapshot["counters"] if row["enabled"]]
            disabled = [row for row in snapshot["counters"] if not row["enabled"]]
            self.assertEqual(len(enabled), 33)
            self.assertEqual(len(disabled), 12)
            for row in disabled:
                self.assertTrue(row["name"].startswith(("l2cache_", "l3cache_")))
                self.assertIsNone(row["status"])
                self.assertIsNone(row["value"])
            for row in enabled:
                self.assertEqual(row["status"], 0)
                self.assertGreater(row["value"], 2**63)
        self.assertLessEqual(snapshots[0]["query_end_ns"], snapshots[1]["query_begin_ns"])
        cap_requests = self.rows(events, "MOCK_CAP")
        self.assertEqual([row["id"] for row in cap_requests],
                         [row["id"] for row in wanted_caps] * 2)
        requests = [{key: value for key, value in row.items() if key != "call"}
                    for row in self.rows(events, "MOCK_COUNTER")]
        expected = [{key: row[key] for key in ("mpm_class", "csr", "core_id")}
                    for row in enabled] * 2
        self.assertEqual(requests, expected)

    def test_snapshot_and_cleanup_order_and_status_are_observed(self):
        events, _ = self.run_case()
        order = [name for name, _ in events
                 if name in ("MOCK_OPEN", "P06_BEGIN", "P06_END", "MOCK_RELEASE", "P06_RELEASE")]
        self.assertEqual(order, ["MOCK_OPEN", "P06_BEGIN", "P06_END", "MOCK_RELEASE", "P06_RELEASE"])
        self.assertEqual(self.rows(events, "P06_RELEASE"), [{
            "schema_version": 1, "sample_id": "fp16-single-measurement-0", "context_id": 1,
            "status": 0}])
        self.assertEqual(self.rows(events, "MOCK_RETURN"),
                         [{"operation": "open", "status": 0}, {"operation": "release", "status": 0}])

    def test_uint64_max_round_trips_without_signed_or_float_conversion(self):
        events, _ = self.run_case("unsigned_max")
        for marker in ("P06_BEGIN", "P06_END"):
            for row in self.rows(events, marker)[0]["counters"]:
                if row["enabled"]:
                    self.assertIs(type(row["value"]), int)
                    self.assertEqual(row["value"], 2**64 - 1)

    def test_optional_isa_absence_skips_queries_and_retains_null_rows(self):
        events, summary = self.run_case("no_optional_isa")
        for marker in ("P06_BEGIN", "P06_END"):
            for row in self.rows(events, marker)[0]["counters"]:
                self.assertEqual(row["enabled"], row["required_isa"] == 0)
                if row["required_isa"] != 0:
                    self.assertIsNone(row["status"])
                    self.assertIsNone(row["value"])
        unconditional = sum(row["required_isa"] == 0 for row in self.contract["counters"])
        self.assertEqual(summary["counters"], unconditional * 2)

    def test_counter_failures_keep_error_status_and_still_release(self):
        for scenario, status in (("counter_status", 7), ("counter_throw", None)):
            for fail_at in (1, 17, 33, 34, 50, 66):
                with self.subTest(scenario=scenario, fail_at=fail_at):
                    events, summary = self.run_case(scenario, fail_at=fail_at)
                    self.assertEqual(summary["counters"], 66)
                    self.assertEqual(summary["releases"], 1)
                    self.assertEqual(summary["live_handles"], 0)
                    self.assertIn("counter_query_failed", self.failures(events))
                    marker = "P06_BEGIN" if fail_at <= 33 else "P06_END"
                    rows = [row for row in self.rows(events, marker)[0]["counters"] if row["enabled"]]
                    failed = rows[(fail_at - 1) % 33]
                    self.assertEqual(failed["status"], status)
                    self.assertIsNone(failed["value"])
                    self.assertEqual(self.rows(events, "P06_RELEASE")[0]["status"], 0)

    def test_capability_failure_marks_availability_unknown_without_counter_queries(self):
        for scenario, status in (("cap_status", 6), ("cap_throw", None)):
            for fail_at in (1, 7, 13, 14, 20, 26):
                with self.subTest(scenario=scenario, fail_at=fail_at):
                    events, summary = self.run_case(scenario, fail_at=fail_at)
                    self.assertEqual(summary["capabilities"], 26)
                    self.assertEqual(summary["counters"], 33)
                    self.assertEqual(summary["releases"], 1)
                    self.assertEqual(summary["live_handles"], 0)
                    self.assertIn("capability_query_failed", self.failures(events))
                    self.assertIn("unsupported_or_unavailable_topology", self.failures(events))
                    marker = "P06_BEGIN" if fail_at <= 13 else "P06_END"
                    snapshot = self.rows(events, marker)[0]
                    self.assertEqual(snapshot["capabilities"][(fail_at - 1) % 13]["status"], status)
                    self.assertIsNone(snapshot["capabilities"][(fail_at - 1) % 13]["value"])
                    for row in snapshot["counters"]:
                        self.assertIsNone(row["enabled"])
                        self.assertIsNone(row["status"])
                        self.assertIsNone(row["value"])

    def test_unsupported_topology_never_queries_ambiguous_shared_counters(self):
        for scenario in ("topology_cores", "topology_clusters", "topology_socket"):
            with self.subTest(scenario=scenario):
                events, summary = self.run_case(scenario)
                self.assertEqual(summary["counters"], 0)
                self.assertEqual(summary["releases"], 1)
                self.assertEqual(self.failures(events).count("unsupported_or_unavailable_topology"), 2)

    def test_invalid_sample_ids_are_failed_without_suppressing_cleanup(self):
        for sample in (None, "", "A", "-a", "_a", "a b", "a\"b", "a\\b", "a\nb", "é", "a" * 129):
            with self.subTest(sample=sample):
                events, summary = self.run_case(sample=sample)
                self.assertIn("invalid_sample_identity", self.failures(events))
                self.assertEqual(summary["opens"], 1)
                self.assertEqual(summary["releases"], 1)
                self.assertEqual(summary["live_handles"], 0)
                self.assertEqual(self.rows(events, "P06_BEGIN")[0]["sample_id"], "")

    def test_valid_sample_id_boundaries_are_preserved(self):
        for sample in ("0", "a", "a-_09", "a" * 128):
            with self.subTest(sample=sample):
                events, _ = self.run_case(sample=sample)
                self.assertEqual(self.failures(events), [])
                for marker in ("P06_BEGIN", "P06_END", "P06_RELEASE"):
                    self.assertEqual(self.rows(events, marker)[0]["sample_id"], sample)

    def test_real_open_failure_or_exception_is_forwarded_without_queries(self):
        for scenario, status in (("open_status", 6), ("open_throw", 10),
                                 ("open_null", 0), ("null_output", 3)):
            with self.subTest(scenario=scenario):
                events, summary = self.run_case(scenario)
                self.assertEqual(summary["opens"], 1)
                self.assertEqual(summary["releases"], 0)
                self.assertEqual(summary["capabilities"], 0)
                self.assertEqual(summary["counters"], 0)
                self.assertEqual(self.rows(events, "P06_BEGIN"), [])
                self.assertEqual(self.rows(events, "MOCK_RETURN"), [{"operation": "open", "status": status}])
                self.assertIn("device_open_threw" if scenario == "open_throw" else "device_open_failed",
                              self.failures(events))

    def test_nonzero_device_index_is_forwarded_and_recorded_as_failure(self):
        events, summary = self.run_case("device_index")
        self.assertEqual(self.rows(events, "MOCK_OPEN")[0]["index"], 7)
        self.assertEqual(self.rows(events, "P06_BEGIN")[0]["device_index"], 7)
        self.assertIn("unsupported_device_index", self.failures(events))
        self.assertEqual(summary["releases"], 1)

    def test_release_failure_or_exception_cannot_be_reported_successful(self):
        for scenario, recorded, returned in (("release_status", 6, 6), ("release_throw", None, 10)):
            with self.subTest(scenario=scenario):
                events, summary = self.run_case(scenario)
                self.assertEqual(summary["releases"], 1)
                self.assertEqual(self.rows(events, "P06_RELEASE")[0]["status"], recorded)
                self.assertEqual(self.rows(events, "MOCK_RETURN")[-1]["status"], returned)
                self.assertIn("device_release_failed", self.failures(events))
                self.assertEqual(len(self.rows(events, "P06_END")), 1)

    def test_duplicate_open_is_rejected_but_both_cleanup_requests_are_forwarded(self):
        events, summary = self.run_case("duplicate_open")
        self.assertEqual(summary["opens"], 2)
        self.assertEqual(summary["releases"], 2)
        self.assertEqual(summary["live_handles"], 0)
        self.assertEqual(summary["counters"], 33)
        self.assertEqual(self.rows(events, "P06_END"), [])
        self.assertIn("multiple_device_opens", self.failures(events))
        self.assertEqual(self.failures(events).count("unmatched_device_release"), 2)

    def test_wrong_repeated_or_orphan_release_is_forwarded_without_querying_handle(self):
        for scenario, opens, releases, end_count in (("wrong_release", 1, 2, 0),
                                                    ("release_twice", 1, 2, 1),
                                                    ("release_without_open", 0, 1, 0)):
            with self.subTest(scenario=scenario):
                events, summary = self.run_case(scenario)
                self.assertEqual(summary["opens"], opens)
                self.assertEqual(summary["releases"], releases)
                self.assertEqual(summary["live_handles"], 0)
                self.assertEqual(len(self.rows(events, "P06_END")), end_count)
                self.assertEqual(len(self.rows(events, "P06_RELEASE")), releases)
                self.assertIn("unmatched_device_release", self.failures(events))
                self.assertIn(1, [row["status"] for row in self.rows(events, "P06_RELEASE")])

    @unittest.skipUnless(Path("/dev/full").exists(), "Output-failure probe requires /dev/full")
    def test_snapshot_output_failure_remains_visible_and_does_not_skip_cleanup(self):
        events, summary = self.run_case("output_full")
        self.assertIn("observer_output_failed", self.failures(events))
        self.assertEqual(summary["opens"], 1)
        self.assertEqual(summary["releases"], 1)
        self.assertEqual(summary["live_handles"], 0)


if __name__ == "__main__":
    unittest.main()
