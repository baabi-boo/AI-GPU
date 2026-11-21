# SPDX-License-Identifier: Apache-2.0
"""Independent arithmetic checks of post-replay helpers, never native evidence.

The small records below isolate metric reduction. Archive validation has its own
integration tests; these records are not asserted to be qualified GPU packets.
"""

from copy import deepcopy
from fractions import Fraction
import math
import unittest

import p06_analyze as analyze


def observation_sample(*, phase="measurement", repetition=0, cycles=5952,
                       instructions=509, reads=36, writes=13, flops=512,
                       macs=256, inputs=192, poison=128, output=128, block=64):
    identifier = "fp16-metric-example-" + phase + "-" + str(repetition)
    return {
        "sample_id": identifier, "workload_id": "fp16-metric-example",
        "phase": phase, "repetition": repetition, "command_id": "run-" + identifier,
        "process_duration_seconds": 0.140123,
        "observation": {
            "raw_log_sha256": "a" * 64,
            "accounting": {
                "flops": flops, "macs": macs, "input_h2d_bytes": inputs,
                "poison_h2d_bytes": poison, "tensor_d2h_bytes": output,
            },
            "counter_deltas": [
                {"name": "cycles", "value": cycles},
                {"name": "instructions", "value": instructions},
                {"name": "memory_reads", "value": reads},
                {"name": "memory_writes", "value": writes},
                {"name": "l2cache_reads", "value": None},
            ],
            "snapshots": {"begin": {"compiled_memory_block_bytes": block}},
            "host_timings_ns": {
                "model_create": 5000, "model_advance": 40000,
                "native_stage_0_wait": 30000, "model_close": 3000,
                "observer_begin_query": 1000, "observer_end_query": 2000,
            },
        },
    }


def workload():
    return {"id": "fp16-metric-example", "format": "fp16", "kind": "matmul",
            "native_shapes": [[8, 4, 8]],
            "accounting": deepcopy(observation_sample()["observation"]["accounting"])}


def population_deviation(values):
    """Reference with exact rational intermediate arithmetic."""
    values = [Fraction(value) for value in values]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(float(variance))


class AnalysisMetricTests(unittest.TestCase):
    def test_six_metric_definitions_use_the_declared_work_and_byte_boundaries(self):
        actual = analyze._sample_metrics(observation_sample())["metrics"]
        expected = {
            "active_cycles_per_useful_flop": (Fraction(5952, 512), "active_core_cycles_per_flop"),
            "retired_macroinstructions_per_mac": (Fraction(509, 256), "retired_macroinstructions_per_mac"),
            "logical_tensor_bytes": (448, "bytes"),
            "modeled_external_read_request_bytes": (2304, "modeled_request_bytes"),
            "modeled_external_write_request_bytes": (832, "modeled_request_bytes"),
            "useful_flops_per_logical_tensor_byte": (Fraction(8, 7), "flops_per_payload_byte"),
        }
        self.assertEqual(set(actual), set(expected))
        for name, (value, unit) in expected.items():
            with self.subTest(metric=name):
                self.assertEqual(actual[name]["value"], float(value) if isinstance(value, Fraction) else value)
                self.assertEqual(actual[name]["unit"], unit)
                self.assertIsNone(actual[name]["unavailable_reason"])
        self.assertEqual(actual["active_cycles_per_useful_flop"]["numerator"], 5952)
        self.assertEqual(actual["active_cycles_per_useful_flop"]["denominator"], 512)
        self.assertEqual(actual["retired_macroinstructions_per_mac"]["denominator"], 256)
        self.assertEqual(actual["useful_flops_per_logical_tensor_byte"]["denominator"], 448)
        # Poison is included in payload accounting; modeled request bytes remain separate.
        self.assertNotEqual(actual["logical_tensor_bytes"]["value"], 192 + 128)
        self.assertNotEqual(actual["logical_tensor_bytes"]["value"], 2304 + 832)

    def test_large_counter_operands_and_request_bytes_remain_exact_integers(self):
        largest = (1 << 64) - 1
        result = analyze._sample_metrics(observation_sample(
            cycles=largest, instructions=largest - 2, reads=largest, writes=(1 << 63) + 3))
        self.assertEqual(result["counter_values"]["cycles"], largest)
        ratio = result["metrics"]["active_cycles_per_useful_flop"]
        self.assertIs(type(ratio["numerator"]), int)
        self.assertEqual(ratio["numerator"], largest)
        self.assertEqual(ratio["value"], float(Fraction(largest, 512)))
        for direction, expected in (("read", largest * 64), ("write", ((1 << 63) + 3) * 64)):
            quantity = result["metrics"]["modeled_external_" + direction + "_request_bytes"]
            self.assertIs(type(quantity["value"]), int)
            self.assertEqual(quantity["value"], expected)
            self.assertEqual(quantity["memory_block_bytes"], 64)

    def test_ratios_are_computed_per_sample_before_population_statistics(self):
        # Unequal toy denominators distinguish arithmetic order. They isolate the
        # reducer; real frozen-workload accounting is separately enforced by replay.
        pairs = [(2, 2), (100, 10), (12, 3), (8, 2), (1, 10)]
        samples = [observation_sample(repetition=i, cycles=numerator, flops=denominator)
                   for i, (numerator, denominator) in enumerate(pairs)]
        result = analyze._diagnostics(samples, [workload()])[0]
        ratios = [Fraction(numerator, denominator) for numerator, denominator in pairs]
        stats = result["measured_metric_statistics"]["active_cycles_per_useful_flop"]["statistics"]
        self.assertEqual(stats["count"], 5)
        self.assertEqual(stats["minimum"], 0.1)
        self.assertEqual(stats["maximum"], 10.0)
        self.assertEqual(stats["median"], 4.0)
        self.assertNotEqual(stats["median"], 8 / 3)  # Ratio of the two medians.
        self.assertNotEqual(stats["median"], 123 / 27)  # Ratio of the two totals.
        self.assertAlmostEqual(stats["population_stddev"], population_deviation(ratios), places=14)
        self.assertEqual([row["metrics"]["active_cycles_per_useful_flop"]["value"]
                          for row in result["samples"]], [float(value) for value in ratios])

    def test_warmup_is_retained_but_excluded_from_every_metric_statistic(self):
        warmup = observation_sample(phase="warmup", cycles=1 << 63, reads=1 << 62)
        measured = [observation_sample(repetition=i, cycles=value, reads=i + 1)
                    for i, value in enumerate((128, 256, 512, 768, 1024))]
        result = analyze._diagnostics([warmup, *measured], [workload()])[0]
        self.assertEqual(len(result["samples"]), 6)
        self.assertEqual(result["samples"][0]["counter_values"]["cycles"], 1 << 63)
        for row in result["measured_metric_statistics"].values():
            self.assertEqual(row["statistics"]["count"], 5)
        cycle_stats = result["measured_metric_statistics"]["active_cycles_per_useful_flop"]["statistics"]
        self.assertEqual((cycle_stats["minimum"], cycle_stats["median"], cycle_stats["maximum"]),
                         (0.25, 1.0, 2.0))
        self.assertAlmostEqual(cycle_stats["population_stddev"], math.sqrt(0.41), places=14)
        read_stats = result["measured_metric_statistics"]["modeled_external_read_request_bytes"]["statistics"]
        self.assertEqual((read_stats["minimum"], read_stats["median"], read_stats["maximum"]),
                         (64, 192, 320))

    def test_unavailable_counters_are_distinct_from_measured_zero(self):
        result = analyze._sample_metrics(observation_sample(reads=None, writes=0))
        missing = result["metrics"]["modeled_external_read_request_bytes"]
        self.assertIsNone(missing["value"])
        self.assertIsNone(missing["requests"])
        self.assertEqual(missing["unavailable_reason"], "unavailable_counter")
        zero = result["metrics"]["modeled_external_write_request_bytes"]
        self.assertEqual(zero["value"], 0)
        self.assertIsNone(zero["unavailable_reason"])
        self.assertIsNone(result["counter_values"]["l2cache_reads"])

    def test_zero_or_missing_ratio_operands_preserve_their_distinct_reasons(self):
        for numerator, denominator, reason in ((5, 0, "zero_denominator"),
                                                (0, 0, "zero_denominator"),
                                                (None, 5, "unavailable_operand"),
                                                (5, None, "unavailable_operand"),
                                                (None, 0, "unavailable_operand")):
            with self.subTest(numerator=numerator, denominator=denominator):
                row = analyze._ratio(numerator, denominator, "test-unit")
                self.assertIsNone(row["value"])
                self.assertEqual(row["unavailable_reason"], reason)
                self.assertEqual((row["numerator"], row["denominator"]), (numerator, denominator))
        zero = analyze._ratio(0, 7, "test-unit")
        self.assertEqual(zero["value"], 0.0)
        self.assertIsNone(zero["unavailable_reason"])

    def test_missing_one_measurement_does_not_produce_partial_subset_statistics(self):
        samples = [observation_sample(repetition=i, reads=None if i == 2 else i)
                   for i in range(5)]
        result = analyze._diagnostics(samples, [workload()])[0]
        metric = result["measured_metric_statistics"]["modeled_external_read_request_bytes"]
        self.assertIsNone(metric["statistics"])
        self.assertEqual(metric["unavailable_sample_ids"], [samples[2]["sample_id"]])
        self.assertEqual(len(result["samples"]), 5)
        self.assertEqual(result["measured_metric_statistics"]["logical_tensor_bytes"]["statistics"]["count"], 5)

    def test_large_request_statistics_keep_integer_extrema_and_exact_small_spread(self):
        base = (1 << 63) + 1
        samples = [observation_sample(repetition=i, reads=base + i) for i in range(5)]
        result = analyze._diagnostics(samples, [workload()])[0]
        stats = result["measured_metric_statistics"]["modeled_external_read_request_bytes"]["statistics"]
        self.assertEqual((stats["minimum"], stats["median"], stats["maximum"]),
                         (base * 64, (base + 2) * 64, (base + 4) * 64))
        for field in ("minimum", "median", "maximum"):
            self.assertIs(type(stats[field]), int)
        self.assertAlmostEqual(stats["population_stddev"], 64 * math.sqrt(2), places=12)

    def test_host_intervals_and_input_records_are_preserved_without_subtraction(self):
        sample = observation_sample()
        before = deepcopy(sample)
        result = analyze._sample_metrics(sample)
        self.assertEqual(result["process_duration_seconds"], 0.140123)
        self.assertEqual(result["host_timings_ns"], before["observation"]["host_timings_ns"])
        self.assertEqual(sample, before)
        # A caller mutating the derived report cannot modify the original timing receipt.
        result["host_timings_ns"]["model_advance"] = 0
        self.assertEqual(sample, before)
        source_workload = workload()
        diagnostic = analyze._diagnostics([sample], [source_workload])[0]
        diagnostic["accounting_per_invocation"]["flops"] = 0
        diagnostic["native_shapes"][0][0] = 0
        self.assertEqual(source_workload, workload())

    def test_invalid_numeric_values_are_not_coerced_into_valid_metrics(self):
        for invalid in (True, False, -1, 1.5, float("nan"), float("inf"), "7"):
            with self.subTest(value=repr(invalid)):
                with self.assertRaises(ValueError):
                    analyze._ratio(invalid, 1, "test-unit")
                with self.assertRaises(ValueError):
                    analyze._ratio(1, invalid, "test-unit")
                with self.assertRaises(ValueError):
                    analyze._quantity(invalid, "test-unit")
        for invalid in ([], [True], [float("nan")], [float("inf")]):
            with self.subTest(statistics=repr(invalid)), self.assertRaises(ValueError):
                analyze._statistics(invalid)


if __name__ == "__main__":
    unittest.main()
