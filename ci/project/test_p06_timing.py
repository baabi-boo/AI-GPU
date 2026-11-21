# SPDX-License-Identifier: Apache-2.0
"""Synthetic lifecycle timing regressions; no GPU execution is performed."""

from copy import deepcopy
import unittest

import p06_contract
import p06_records as records
from p06_test_samples import BINDING, REVISION, raw_records, render_log, samples


class ModelTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = p06_contract.load_contract()
        cls.workloads = {
            fmt: p06_contract.select_workloads(cls.contract, [fmt])
            for fmt in ("fp16", "bf16")
        }
        cls.rows = {fmt: samples(cls.contract, [fmt]) for fmt in cls.workloads}

    def raw(self, fmt, phase="measurement"):
        workload = self.workloads[fmt][-1]
        sample_id = workload["id"] + "-" + phase + "-0"
        return raw_records(workload, sample_id, contract=self.contract)

    def verify(self, fmt, raw):
        workload = self.workloads[fmt][-1]
        return records.verify_sample(
            render_log(workload, raw), workload, BINDING,
            sample_id=raw["P06_BEGIN"]["sample_id"], source_revision=REVISION,
            fixture_sha256=workload["fixture_sha256"], contract=self.contract)

    def summarize(self, fmt, raw, duration):
        rows = deepcopy(self.rows[fmt])
        sample_id = raw["P06_BEGIN"]["sample_id"]
        row = next(row for row in rows if row["sample_id"] == sample_id)
        row["observation"] = self.verify(fmt, raw)
        row["process_duration_seconds"] = duration
        return records.summarize(rows, self.contract, self.workloads[fmt])

    @staticmethod
    def scale_times(value, factor):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_ns") and type(item) is int:
                    value[key] = item * factor
                else:
                    ModelTimingTests.scale_times(item, factor)
        elif isinstance(value, list):
            for item in value:
                ModelTimingTests.scale_times(item, factor)

    @staticmethod
    def tight_timeline(raw, wait_ns=100):
        trace = raw["P04_RESULT"]["trace"]
        cursor = trace["create_end_ns"]
        for index, stage in enumerate(trace["native"]):
            stage.update(submit_begin_ns=cursor, submit_end_ns=cursor + 10,
                         wait_ns=wait_ns)
            for event, profile in enumerate(stage["dispatch"]["event_profiles"]):
                profile.update(queued_ns=cursor + event, submit_ns=cursor + 20 + event * 10,
                               start_ns=cursor + 22 + event * 10, end_ns=cursor + 25 + event * 10)
            cursor += 10 + wait_ns + 5 + 5
            if index == 0:
                cursor += 5 + 5
        cursor += 5 + 5
        trace["advance_ns"] = cursor - trace["create_end_ns"]
        raw["P06_END"].update(query_begin_ns=cursor + 2, query_end_ns=cursor + 7)

    def test_serial_lifecycle_cannot_exceed_process_even_when_each_interval_fits(self):
        for fmt in self.workloads:
            for phase in ("warmup", "measurement"):
                raw = self.raw(fmt, phase)
                self.scale_times(raw, 1_000_000)
                raw["P04_RESULT"]["trace"]["close_ns"] = 3_500_000_000
                # Each interval and the 3.905 s context fit; 7.1 s of serial work does not.
                with self.subTest(format=fmt, phase=phase), self.assertRaises(ValueError):
                    self.summarize(fmt, raw, 4.0)

    def test_process_rounding_allowance_applies_once_to_the_serial_lifecycle(self):
        for fmt in self.workloads:
            for close_ns in (1400, 2400):
                raw = self.raw(fmt)
                raw["P04_RESULT"]["trace"]["close_ns"] = close_ns
                # Lifecycle totals are 5000 ns and 6000 ns; the receipt is 5000 ns.
                with self.subTest(format=fmt, close_ns=close_ns):
                    self.summarize(fmt, raw, 0.000005)
            raw = self.raw(fmt)
            raw["P04_RESULT"]["trace"]["close_ns"] = 2401
            with self.subTest(format=fmt, excess_ns=1), self.assertRaises(ValueError):
                self.summarize(fmt, raw, 0.000005)

    def test_decimal_duration_preserves_the_exact_lifecycle_allowance(self):
        for fmt in self.workloads:
            raw = self.raw(fmt)
            # Creation + advance = 3600 ns; the complete lifecycle is 130000 ns.
            raw["P04_RESULT"]["trace"]["close_ns"] = 126400
            with self.subTest(format=fmt, lifecycle_ns=130000):
                self.summarize(fmt, raw, 0.000129)
            raw["P04_RESULT"]["trace"]["close_ns"] += 1
            with self.subTest(format=fmt, lifecycle_ns=130001), self.assertRaisesRegex(
                    ValueError, "serial model lifecycle exceeds"):
                self.summarize(fmt, raw, 0.000129)

    def test_decimal_duration_preserves_the_exact_context_allowance(self):
        for fmt in self.workloads:
            for context_ns in (130000, 130001):
                raw = self.raw(fmt)
                end_ns = raw["P04_RESULT"]["trace"]["create_begin_ns"] + context_ns
                raw["P06_END"].update(query_begin_ns=end_ns - 5, query_end_ns=end_ns)
                with self.subTest(format=fmt, context_ns=context_ns):
                    if context_ns == 130000:
                        self.summarize(fmt, raw, 0.000129)
                    else:
                        with self.assertRaisesRegex(ValueError, "retained host interval exceeds"):
                            self.summarize(fmt, raw, 0.000129)

    def test_decimal_conversion_does_not_coerce_invalid_process_durations(self):
        for fmt in self.workloads:
            for duration in (True, False, float("nan"), float("inf"), -float("inf"), "0.000129"):
                rows = deepcopy(self.rows[fmt])
                rows[0]["process_duration_seconds"] = duration
                with self.subTest(format=fmt, duration=duration), self.assertRaisesRegex(
                        ValueError, "invalid bounded-process duration"):
                    records.summarize(rows, self.contract, self.workloads[fmt])

    def test_disjoint_stage_waits_cannot_each_consume_the_same_advance_interval(self):
        for fmt in self.workloads:
            for phase in ("warmup", "measurement"):
                raw = self.raw(fmt, phase)
                for stage in raw["P04_RESULT"]["trace"]["native"]:
                    stage["wait_ns"] = 3000
                with self.subTest(format=fmt, phase=phase), self.assertRaises(ValueError):
                    self.verify(fmt, raw)

    def test_each_serial_host_child_contributes_to_the_advance_bound(self):
        for fmt in self.workloads:
            for field in ("bridge_ns", "bridge_compare_ns", "assembly_ns", "output_compare_ns"):
                raw = self.raw(fmt)
                raw["P04_RESULT"]["trace"][field] = 3400
                with self.subTest(format=fmt, field=field), self.assertRaises(ValueError):
                    self.verify(fmt, raw)
            for index in range(3):
                for field in ("wait_ns", "compare_ns", "close_ns"):
                    raw = self.raw(fmt)
                    raw["P04_RESULT"]["trace"]["native"][index][field] = 3400
                    with self.subTest(format=fmt, stage=index, field=field), self.assertRaises(ValueError):
                        self.verify(fmt, raw)

    def test_serial_submit_scopes_are_included_without_adding_event_profiles(self):
        for fmt in self.workloads:
            raw = self.raw(fmt)
            for stage in raw["P04_RESULT"]["trace"]["native"]:
                stage["submit_end_ns"] = stage["submit_begin_ns"] + 1000
                stage["wait_ns"] = 200
            # Ordered submissions fit their absolute timeline; all serial children total 3650 ns.
            with self.subTest(format=fmt), self.assertRaises(ValueError):
                self.verify(fmt, raw)

    def test_exact_child_boundary_preserves_overlapping_event_and_query_observations(self):
        for fmt in self.workloads:
            raw = self.raw(fmt)
            self.tight_timeline(raw)
            trace = raw["P04_RESULT"]["trace"]
            # The fixture has 380 ns of host child scopes and 45 ns of nested event work.
            with self.subTest(format=fmt):
                observation = self.verify(fmt, raw)
                self.assertEqual(observation["host_timings_ns"]["model_advance"], 380)
                self.assertEqual(observation["host_timings_ns"]["observer_begin_query"], 5)
                self.assertEqual(observation["host_timings_ns"]["observer_end_query"], 5)
            trace["advance_ns"] = 379
            with self.subTest(format=fmt, excess_ns=1), self.assertRaises(ValueError):
                self.verify(fmt, raw)

    def test_timeout_resume_wait_duration_is_already_accumulated(self):
        for fmt in self.workloads:
            raw = self.raw(fmt)
            self.tight_timeline(raw, wait_ns=200)
            trace = raw["P04_RESULT"]["trace"]
            for stage in trace["native"]:
                stage["dispatch"].update(wait_calls=2, timed_out_waits=1)
            with self.subTest(format=fmt):
                observation = self.verify(fmt, raw)
                self.assertEqual(observation["host_timings_ns"]["native_stage_0_wait"], 200)

    def test_zero_duration_observations_remain_valid(self):
        for fmt in self.workloads:
            raw = self.raw(fmt)
            self.scale_times(raw, 0)
            with self.subTest(format=fmt):
                observation = self.verify(fmt, raw)
                self.assertTrue(all(value == 0 for value in observation["host_timings_ns"].values()))


if __name__ == "__main__":
    unittest.main()
