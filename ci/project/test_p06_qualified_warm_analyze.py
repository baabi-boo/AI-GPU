# SPDX-License-Identifier: Apache-2.0
"""Fixed arithmetic controls using synthetic data, not qualification evidence."""

from copy import deepcopy
from fractions import Fraction
import hashlib
import math
import unittest

from p03_execution_records import qualification_id
import p06_qualified_warm_analyze as analyze
import p06_qualified_warm_contract as qualified
import p06_warm_analyze as historical
import p06_warm_contract as warm
from p06_warm_records import verify_output
from p06_warm_test_fixture import raw_records, render_log


REVISION = "1" * 40
REFERENCE, CANDIDATE = warm.POLICIES


def rational(value):
    return Fraction(value["numerator"], value["denominator"])


def synthetic_population():
    """Invent reducer inputs; builds and records do not constitute an archive."""
    builds = {"simx-" + fmt: {"synthetic_arithmetic_only": True, "format": fmt}
              for fmt in warm.FORMATS}
    processes = []
    for planned in qualified.process_plan():
        duration = 100 if planned["policy"] == REFERENCE else 90
        intervals = [duration] * 32
        processes.append({**planned, "outcome": "pass",
            "build_binding_sha256": qualification_id(builds["simx-" + planned["format"]]),
            "execution_binding_sha256": hashlib.sha256(planned["id"].encode()).hexdigest(),
            "process_duration_seconds": 1.0,
            "observation": {"warm": {
                "timed_operation_durations_ns": intervals,
                "operation_durations_ns": [1000000, *intervals],
                "raw_log_sha256": hashlib.sha256(("raw:" + planned["id"]).encode()).hexdigest(),
                "counter_deltas": [{"name": "cycles", "available": True, "value": 1000}],
            }}})
    return processes, builds


def selected(processes, *, fmt=None, policy=None, pair=None):
    return [row for row in processes
            if (fmt is None or row["format"] == fmt)
            and (policy is None or row["policy"] == policy)
            and (pair is None or row["pair_index"] == pair)]


def set_total(process, total):
    quotient, remainder = divmod(total, 32)
    intervals = [quotient + int(index < remainder) for index in range(32)]
    observation = process["observation"]["warm"]
    observation["timed_operation_durations_ns"] = intervals
    observation["operation_durations_ns"] = [observation["operation_durations_ns"][0], *intervals]


class QualifiedWarmArithmeticTests(unittest.TestCase):
    def setUp(self):
        self.processes, self.builds = synthetic_population()

    def result(self, *, revision=REVISION):
        return analyze.analyze_population(self.processes, self.builds,
                                          expected_revision=revision)

    def test_complete_success_retains_exact_counts_and_nonacceptance(self):
        result = self.result()
        self.assertEqual(result["hypothesis_evaluation"], "satisfied")
        self.assertEqual(result["counts"], warm.load_contract()["complete_matrix"])
        self.assertEqual(len(result["batches"]), 24)
        self.assertEqual(sum(row["included_in_conditional_criteria"] for row in result["batches"]), 20)
        self.assertEqual(result["excluded_prime_operations"], 24)
        self.assertEqual(result["excluded_warmup_processes"],
                         [row["id"] for row in qualified.process_plan() if row["pair_index"] == 0])
        self.assertEqual(result["native_execution"], "not_run")
        for name in ("performance_acceptance", "phase_acceptance", "acceptance_claimed"):
            self.assertIs(result[name], False)
        self.assertNotIn("counter_qualification_passed", result)
        self.assertNotIn("qualified_warm_passed", result)
        for fmt in result["formats"]:
            self.assertTrue(fmt["conditional_criteria_satisfied"])
            self.assertEqual(len(fmt["pairs"]), 5)
            self.assertEqual(rational(fmt["candidate_reference_median_ratio"]), Fraction(9, 10))
            self.assertEqual({row["count"] for row in fmt["policy_statistics"].values()}, {5})

    def test_exact_95_percent_boundary_passes(self):
        for process in selected(self.processes, policy=CANDIDATE):
            set_total(process, 3040)
        result = self.result()
        self.assertEqual(result["hypothesis_evaluation"], "satisfied")
        self.assertTrue(all(rational(row["candidate_reference_median_ratio"]) == Fraction(19, 20)
                            for row in result["formats"]))

    def test_one_nanosecond_above_boundary_fails_without_pair_regression(self):
        for process in selected(self.processes, policy=CANDIDATE):
            set_total(process, 3041)
        result = self.result()
        self.assertEqual(result["hypothesis_evaluation"], "not_satisfied")
        for fmt in result["formats"]:
            self.assertEqual(fmt["failed_conditional_criteria"],
                             ["host_median_at_most_95_percent_of_reference"])
            self.assertEqual(rational(fmt["candidate_reference_median_ratio"]), Fraction(3041, 3200))

    def test_large_integer_boundary_is_decided_without_float_rounding(self):
        # Arithmetic stress only: these totals are not valid native timing samples.
        reference = 20 * 2**55
        candidate = 19 * 2**55 + 1
        self.assertEqual(float(Fraction(candidate, reference)), 0.95)
        for process in self.processes:
            set_total(process, reference if process["policy"] == REFERENCE else candidate)
        result = self.result()
        self.assertEqual(result["hypothesis_evaluation"], "not_satisfied")
        self.assertTrue(all(not row["conditional_criteria"]["host_median_at_most_95_percent_of_reference"]
                            for row in result["formats"]))

    def test_single_slower_pair_fails_even_when_candidate_median_improves(self):
        set_total(selected(self.processes, fmt="fp16", policy=CANDIDATE, pair=3)[0], 3232)
        result = self.result()
        fmt = result["formats"][0]
        self.assertEqual(result["hypothesis_evaluation"], "not_satisfied")
        self.assertTrue(fmt["conditional_criteria"]["host_median_at_most_95_percent_of_reference"])
        self.assertEqual(fmt["failed_conditional_criteria"], ["no_slower_measured_host_pair"])
        self.assertEqual([row["pair_index"] for row in fmt["pairs"]
                          if not row["candidate_host_time_not_slower"]], [3])
        self.assertEqual(len(fmt["pairs"]), 5)

    def test_single_cycle_increase_fails_with_host_predicates_satisfied(self):
        process = selected(self.processes, fmt="bf16", policy=CANDIDATE, pair=4)[0]
        process["observation"]["warm"]["counter_deltas"][0]["value"] = 1001
        result = self.result()
        self.assertEqual(result["hypothesis_evaluation"], "not_satisfied")
        self.assertEqual(result["formats"][1]["failed_conditional_criteria"],
                         ["no_increased_measured_pair_reported_cycles"])
        self.assertTrue(result["formats"][0]["conditional_criteria_satisfied"])

    def test_both_formats_must_satisfy_all_predicates(self):
        for failed_format in warm.FORMATS:
            with self.subTest(fmt=failed_format):
                self.processes, self.builds = synthetic_population()
                for process in selected(self.processes, fmt=failed_format, policy=CANDIDATE):
                    set_total(process, 3072)
                result = self.result()
                self.assertEqual(result["hypothesis_evaluation"], "not_satisfied")
                self.assertEqual([row["format"] for row in result["formats"]
                                  if not row["conditional_criteria_satisfied"]], [failed_format])

    def test_warmup_pairs_and_every_prime_are_excluded_but_retained(self):
        expected = self.result()["formats"]
        for process in self.processes:
            process["observation"]["warm"]["operation_durations_ns"][0] = 10**15
            if process["pair_index"] == 0:
                set_total(process, 10**15 if process["policy"] == CANDIDATE else 32)
                process["observation"]["warm"]["counter_deltas"][0]["value"] = (
                    10**15 if process["policy"] == CANDIDATE else 1)
        result = self.result()
        self.assertEqual(result["formats"], expected)
        self.assertEqual(len(result["batches"]), 24)
        self.assertTrue(all(row["prime_duration_ns"] == 10**15 for row in result["batches"]))

    def test_batch_statistic_is_mean_of_all_32_intervals(self):
        for process in selected(self.processes, policy=CANDIDATE):
            observation = process["observation"]["warm"]
            observation["timed_operation_durations_ns"] = [1] * 31 + [3200]
            observation["operation_durations_ns"] = [1, *observation["timed_operation_durations_ns"]]
        result = self.result()
        self.assertEqual(result["hypothesis_evaluation"], "not_satisfied")
        for row in selected(result["batches"], policy=CANDIDATE):
            self.assertEqual(rational(row["batch_mean_ns"]), Fraction(3231, 32))

    def test_statistics_use_five_batch_means_and_population_variance(self):
        for process in self.processes:
            if process["pair_index"]:
                set_total(process, process["pair_index"] * (3200 if process["policy"] == REFERENCE else 2880))
        result = self.result()
        for fmt in result["formats"]:
            stats = fmt["policy_statistics"][REFERENCE]
            self.assertEqual([rational(stats[name]) for name in ("minimum", "maximum", "median")],
                             [100, 500, 300])
            self.assertEqual(rational(stats["population_variance_ns2"]), 20000)
            self.assertEqual(stats["population_stddev"], math.sqrt(20000))
            self.assertEqual(rational(fmt["candidate_reference_median_ratio"]), Fraction(9, 10))

    def test_missing_extra_or_nonlist_population_is_rejected(self):
        original = self.processes
        for value in ([], original[:-1], original + [deepcopy(original[0])], tuple(original), {}):
            with self.subTest(type=type(value), count=len(value)), self.assertRaises(ValueError):
                self.processes = value
                self.result()

    def test_reordered_or_duplicated_sample_is_rejected(self):
        for duplicate in (False, True):
            self.processes, self.builds = synthetic_population()
            if duplicate:
                self.processes[1] = deepcopy(self.processes[0])
            else:
                self.processes[0], self.processes[1] = self.processes[1], self.processes[0]
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                self.result()

    def test_failed_warmup_or_measured_sample_cannot_be_discarded(self):
        for pair in (0, 1, 5):
            self.processes, self.builds = synthetic_population()
            selected(self.processes, fmt="fp16", policy=CANDIDATE, pair=pair)[0]["outcome"] = "fail"
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                self.result()

    def test_noncanonical_sampling_fields_are_rejected(self):
        for key, value in (("phase", "measured"), ("pair_index", False), ("pair_index", 0.0),
                           ("sample_id", "unbound"), ("policy", "resident"), ("backend", "rtlsim")):
            self.processes, self.builds = synthetic_population()
            self.processes[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.result()

    def test_both_policies_are_bound_to_the_same_selected_format_build(self):
        process = selected(self.processes, fmt="fp16", policy=CANDIDATE, pair=3)[0]
        process["build_binding_sha256"] = qualification_id(self.builds["simx-bf16"])
        with self.assertRaises(ValueError):
            self.result()
        for build_keys in (("simx-fp16",), ("simx-fp16", "simx-bf16", "other")):
            self.processes, self.builds = synthetic_population()
            self.builds = {name: self.builds.get(name, {}) for name in build_keys}
            with self.subTest(keys=build_keys), self.assertRaises(ValueError):
                self.result()

    def test_raw_transcript_reuse_and_invalid_execution_identity_reject(self):
        self.processes[1]["observation"]["warm"]["raw_log_sha256"] = (
            self.processes[0]["observation"]["warm"]["raw_log_sha256"])
        with self.assertRaises(ValueError):
            self.result()
        for value in (None, "a" * 63, "A" * 64):
            self.processes, self.builds = synthetic_population()
            self.processes[0]["execution_binding_sha256"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.result()

    def test_exact_operation_count_positive_integer_intervals_and_prime_are_required(self):
        for value in ([100] * 31, [100] * 33, [0] * 32, [True] * 32, [100.0] * 32):
            self.processes, self.builds = synthetic_population()
            self.processes[0]["observation"]["warm"]["timed_operation_durations_ns"] = value
            with self.subTest(value=value[:1], count=len(value)), self.assertRaises(ValueError):
                self.result()
        for value in (0, -1, True, 100.0):
            self.processes, self.builds = synthetic_population()
            self.processes[0]["observation"]["warm"]["operation_durations_ns"][0] = value
            with self.subTest(prime=value), self.assertRaises(ValueError):
                self.result()
        self.processes, self.builds = synthetic_population()
        self.processes[0]["observation"]["warm"]["operation_durations_ns"][-1] += 1
        with self.assertRaises(ValueError):
            self.result()

    def test_cycles_require_exact_single_positive_available_uint64(self):
        for value in (0, -1, True, 1000.0, 2**64):
            self.processes, self.builds = synthetic_population()
            self.processes[0]["observation"]["warm"]["counter_deltas"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.result()
        for values in ([], [{"name": "cycles", "available": False, "value": 1000}],
                       [{"name": "cycles", "available": True, "value": 1000}] * 2):
            self.processes, self.builds = synthetic_population()
            self.processes[0]["observation"]["warm"]["counter_deltas"] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.result()

    def test_expected_revision_requires_exact_lowercase_git_identity(self):
        for value in (None, True, "1" * 39, "A" * 40, "master"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.result(revision=value)

    def test_reducer_accepts_the_production_warm_record_shape(self):
        process = self.processes[0]
        contract = warm.load_contract()
        case, operations, summary = raw_records(process["format"], process["policy"],
            pair_index=process["pair_index"], binding_id=process["execution_binding_sha256"],
            contract=contract)
        process["observation"]["warm"] = verify_output(render_log(operations, summary),
            case=case, fmt=process["format"], policy=process["policy"],
            binding_id=process["execution_binding_sha256"], sample_id=process["sample_id"],
            pair_index=process["pair_index"], phase=process["phase"], contract=contract)
        self.assertEqual(self.result()["hypothesis_evaluation"], "satisfied")

    def test_historical_analyzer_stays_blocked_on_favorable_complete_records(self):
        from test_p06_warm_analyze import synthetic_inputs
        contract = warm.load_contract()
        original = synthetic_inputs(contract)
        result = historical.analyze_processes(original["processes"], original["raw_logs"],
            build_bindings=original["build_bindings"], contract=contract, expected_revision=REVISION)
        self.assertEqual(result["conditional_evaluation"], "satisfied")
        self.assertEqual(result["hypothesis_evaluation"], "blocked")
        self.assertIs(result["full_hypothesis_qualification"]["qualified"], False)
        self.assertEqual(result["full_hypothesis_qualification"]["finding_id"],
                         "P06-WARM-RV64-MPM-HIGH-HALF")


if __name__ == "__main__":
    unittest.main()
