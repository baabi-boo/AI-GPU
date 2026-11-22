# SPDX-License-Identifier: Apache-2.0
"""Independent warm statistics and trust checks using synthetic host records.

The fixture helper supplies numerical words, but all timing, transport,
checkout, build and counter observations here are invented. These tests do not
verify native execution or archive provenance.
"""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from p03_execution_records import qualification_id
import p06_warm_analyze as analyze
import p06_warm_contract as manifest
from p06_warm_records import verify_output
from p06_warm_test_fixture import raw_records, render_log


ROOT = manifest.ROOT
REVISION = "1" * 40
REFERENCE, CANDIDATE = "per_operation", "reusable_single_tile"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


def rational(value):
    return Fraction(value["numerator"], value["denominator"])


def synthetic_inputs(contract):
    """Produce complete raw observations around explicitly invented provenance."""
    digest = hashlib.sha256((ROOT / manifest.MANIFEST_PATH).read_bytes()).hexdigest()
    source = {"checkout": {"revision": REVISION, "tree": "2" * 40, "dirty": False,
              "changed_paths": [], "untracked_paths": [], "blockers": [], "outcome": "pass"},
              "files": [{"path": "SYNTHETIC-HOST-ONLY.txt", "sha256": "3" * 64,
                         "size_bytes": 1}]}
    builds = {}
    for fmt in ("fp16", "bf16"):
        builds["simx-" + fmt] = {
            "contract_id": manifest.CONTRACT_ID, "contract_sha256": digest,
            "source": deepcopy(source), "backend": "simx", "format": fmt,
            "case": manifest.select_cases(contract, formats=[fmt])[0],
            "corpus": [], "profile_sha256": "4" * 64, "kernel_source_sha256": "5" * 64,
            "compiler_records": [], "effective_headers": {}, "generated_identity": {},
            "generated_header_macros": {}, "expected_expanded_header_macros": {},
            "expected_backend_header_macros": {},
            "artifacts": [{"path": "synthetic-" + fmt, "sha256": "6" * 64, "size_bytes": 1}],
            "tools": {}, "dependencies": [], "sampling": deepcopy(contract["sampling"]),
            "performance_environment": {"PERF": "1"},
        }
    processes, logs = [], {}
    for planned in manifest.process_plan(contract):
        build = builds["simx-" + planned["format"]]
        build_id = qualification_id(build)
        binding = {"contract_id": manifest.CONTRACT_ID, "contract_sha256": digest,
                   "build_qualification_id": build_id, "build": build, "process": planned}
        binding_id = qualification_id(binding)
        body = encoded(binding)
        process = {**planned, "sample_id": planned["id"], "command_id": planned["id"],
            "outcome": "pass", "qualification_id": binding_id, "build_qualification_id": build_id,
            "binding": {"path": "snapshots/" + planned["id"] + "-binding.json",
                        "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)},
            "log": "logs/" + planned["id"] + ".log", "process_duration_seconds": 1.0,
            "observation": None}
        case, operations, summary = raw_records(
            planned["format"], planned["policy"], pair_index=planned["pair_index"],
            binding_id=binding_id, durations_ns=95 if planned["policy"] == CANDIDATE else 100,
            contract=contract)
        raw = render_log(operations, summary)
        process["observation"] = verify_output(raw, case=case, fmt=planned["format"],
            policy=planned["policy"], binding_id=binding_id, sample_id=planned["id"],
            pair_index=planned["pair_index"], phase=planned["phase"], contract=contract)
        processes.append(process)
        logs[planned["id"]] = raw
    return {"schema_version": 1, "processes": processes, "raw_logs": logs,
            "build_bindings": builds}


def replace_batch(envelope, contract, sample_id, *, durations=95, cycles=1000):
    process = next(row for row in envelope["processes"] if row["id"] == sample_id)
    case, operations, summary = raw_records(process["format"], process["policy"],
        pair_index=process["pair_index"], binding_id=process["qualification_id"],
        durations_ns=durations, counter_deltas={"cycles": cycles}, contract=contract)
    raw = render_log(operations, summary)
    envelope["raw_logs"][sample_id] = raw
    process["observation"] = verify_output(raw, case=case, fmt=process["format"],
        policy=process["policy"], binding_id=process["qualification_id"], sample_id=sample_id,
        pair_index=process["pair_index"], phase=process["phase"], contract=contract)


def decode_log(raw):
    operations = [json.loads(line.split(" ", 1)[1]) for line in raw.splitlines()
                  if line.startswith("P06_WARM_OPERATION ")]
    summary = json.loads(next(line.split(" ", 1)[1] for line in raw.splitlines()
                             if line.startswith("P06_WARM_SUMMARY ")))
    return operations, summary


def metric_batches(reference, candidate, *, reference_cycles=1000, candidate_cycles=1000):
    """Isolate reducer arithmetic; these are not raw observations or packets."""
    batches = []
    for policy, totals, cycles in ((REFERENCE, reference, reference_cycles),
                                   (CANDIDATE, candidate, candidate_cycles)):
        for index, total in enumerate(totals, 1):
            mean = Fraction(total, 32)
            batches.append({"format": "fp16", "included_in_conditional_criteria": True,
                "pair_index": index, "policy": policy,
                "id": f"warm-simx-fp16-pair{index}-{policy}", "timed_total_ns": total,
                "batch_mean_ns": {"numerator": mean.numerator, "denominator": mean.denominator,
                                  "value": float(mean)}, "reported_active_cycles": cycles})
    return batches


class WarmAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = manifest.load_contract()
        cls.original = synthetic_inputs(cls.contract)
        cls.original_digest = hashlib.sha256(encoded(cls.original)).hexdigest()
        cls.valid_result = cls.check(cls.original)
        temporary = tempfile.TemporaryDirectory(prefix="p06-warm-analysis-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.input_path = cls.directory / "valid-input.json"
        cls.input_path.write_bytes(encoded(cls.original))

    def setUp(self):
        self.input = deepcopy(self.original)

    def assert_blocked(self, result, conditional):
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["hypothesis_evaluation"], "blocked")
        self.assertEqual(result["conditional_evaluation"], conditional)
        self.assertEqual(result["conditional_evaluation_scope"],
                         "instrumented_host_time_and_unqualified_reported_counter_predicates")
        qualification = result["full_hypothesis_qualification"]
        self.assertEqual(qualification["status"], "blocked")
        self.assertIs(qualification["qualified"], False)
        self.assertEqual(qualification["finding_id"], "P06-WARM-RV64-MPM-HIGH-HALF")
        self.assertEqual(qualification["counter_transport"], "unqualified_low_32_bits")
        self.assertEqual(qualification["absolute_no_wrap_bound"], "not_established")
        for row in result["formats"]:
            self.assertNotIn("hypothesis_supported", row)
        for row in result["batches"]:
            self.assertNotIn("active_cycles", row)
            self.assertNotIn("counter_deltas", row)

    @classmethod
    def check(cls, envelope, *, contract=None, revision=REVISION):
        return analyze.analyze_processes(envelope["processes"], envelope["raw_logs"],
            build_bindings=envelope["build_bindings"], contract=cls.contract if contract is None else contract,
            expected_revision=revision)

    def reject(self, change, pattern="."):
        envelope = deepcopy(self.original)
        change(envelope)
        with self.assertRaisesRegex(analyze.AnalysisError, pattern):
            self.check(envelope)

    def tearDown(self):
        self.assertEqual(hashlib.sha256(encoded(self.original)).hexdigest(), self.original_digest,
                         "A test modified the shared valid input")

    def cli(self, *extra, incoming=None):
        argv = [str(ROOT / "ci/project/p06_warm_analyze.py"), "--input",
                str(self.input_path if incoming is None else incoming), "--source-revision", REVISION, *extra]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as output, \
                redirect_stderr(io.StringIO()) as errors:
            status = analyze.main()
        return status, output.getvalue(), errors.getvalue()

    def test_full_ordered_matrix_at_exact_threshold_remains_descriptive(self):
        result = self.valid_result
        self.assert_blocked(result, "satisfied")
        self.assertEqual(result["raw_record_validation"], "pass")
        self.assertEqual(result["archive_provenance_validation"], "required_from_caller")
        self.assertEqual(result["native_execution"], "not_run")
        for field in ("acceptance_claimed", "performance_acceptance", "phase_acceptance"):
            self.assertIs(result[field], False)
        self.assertEqual(result["source_revision"], REVISION)
        self.assertEqual(result["counts"], self.contract["complete_matrix"])
        self.assertEqual(result["counts"]["processes"], 24)
        self.assertEqual(result["counts"]["launches"], 792)
        self.assertEqual(result["counts"]["checked_words"], 25344)
        self.assertEqual(result["excluded_prime_operations"], 24)
        self.assertEqual(len(result["excluded_warmup_processes"]), 4)
        self.assertEqual([row["id"] for row in result["batches"]],
                         [row["id"] for row in manifest.process_plan(self.contract)])
        self.assertEqual(len({row["qualification_id"] for row in result["batches"]}), 24)
        self.assertEqual(len({row["raw_log_sha256"] for row in result["batches"]}), 24)
        for fmt in result["formats"]:
            self.assertEqual(rational(fmt["candidate_reference_median_ratio"]), Fraction(19, 20))
            self.assertEqual(len(fmt["pairs"]), 5)
            self.assertTrue(all(fmt["conditional_criteria"].values()))
            for policy in (REFERENCE, CANDIDATE):
                self.assertEqual(fmt["policy_statistics"][policy]["count"], 5)
                self.assertEqual(fmt["policy_statistics"][policy]["population_stddev"], 0.0)
        for batch in result["batches"]:
            self.assertEqual(batch["timed_operations"], 32)
            self.assertEqual(batch["timed_total_ns"], sum(batch["operation_durations_ns"][1:]))
            self.assertEqual(rational(batch["reported_active_cycles_per_useful_flop"]), Fraction(1000, 16384))

    def test_one_format_missing_host_threshold_is_conditionally_negative_and_blocked(self):
        for row in self.input["processes"]:
            if row["format"] == "bf16" and row["policy"] == CANDIDATE and row["phase"] == "measured":
                replace_batch(self.input, self.contract, row["id"], durations=96)
        result = self.check(self.input)
        self.assertEqual(result["raw_record_validation"], "pass")
        self.assert_blocked(result, "not_satisfied")
        self.assertTrue(result["formats"][0]["conditional_criteria_satisfied"])
        self.assertFalse(result["formats"][1]["conditional_criteria_satisfied"])
        self.assertEqual(result["formats"][1]["failed_conditional_criteria"], ["host_median_at_most_95_percent_of_reference"])

    def test_one_slow_host_pair_fails_conditional_criteria_despite_passing_median(self):
        identifier = "warm-simx-fp16-pair5-" + CANDIDATE
        replace_batch(self.input, self.contract, identifier, durations=101)
        result = self.check(self.input)
        self.assert_blocked(result, "not_satisfied")
        self.assertEqual(result["raw_record_validation"], "pass")
        fmt = result["formats"][0]
        self.assertEqual(fmt["failed_conditional_criteria"], ["no_slower_measured_host_pair"])
        self.assertEqual(rational(fmt["candidate_reference_median_ratio"]), Fraction(19, 20))
        self.assertEqual(rational(fmt["pairs"][4]["candidate_reference_host_ratio"]), Fraction(101, 100))
        self.assertEqual(len(result["batches"]), 24)

    def test_one_extra_reported_cycle_fails_conditional_criteria_even_when_host_improves(self):
        replace_batch(self.input, self.contract, "warm-simx-bf16-pair3-" + CANDIDATE,
                      durations=90, cycles=1001)
        result = self.check(self.input)
        self.assert_blocked(result, "not_satisfied")
        self.assertEqual(result["raw_record_validation"], "pass")
        fmt = result["formats"][1]
        self.assertEqual(fmt["failed_conditional_criteria"], ["no_increased_measured_pair_reported_cycles"])
        self.assertEqual(rational(fmt["pairs"][2]["candidate_reference_reported_cycle_ratio"]), Fraction(1001, 1000))
        for claim in ("acceptance_claimed", "performance_acceptance", "phase_acceptance"):
            self.assertIs(result[claim], False)

    def test_monotonic_low_words_can_reverse_true_cycles_but_never_qualify_hypothesis(self):
        true_endpoints = {REFERENCE: (0, (1 << 32) - 1), CANDIDATE: (1, (1 << 32) + 7)}
        true_deltas = {policy: end - begin for policy, (begin, end) in true_endpoints.items()}
        self.assertGreater(true_deltas[CANDIDATE], true_deltas[REFERENCE])
        reported_deltas = {}
        for process in self.input["processes"]:
            begin, end = (value & ((1 << 32) - 1) for value in true_endpoints[process["policy"]])
            self.assertGreater(end, begin)
            reported_deltas[process["policy"]] = end - begin
            operations, summary = decode_log(self.input["raw_logs"][process["id"]])
            for name, value in (("after_open", begin), ("after_prime", begin),
                                ("after_batch", end), ("before_release", end)):
                cycle = next(row for row in summary["snapshots"][name]["counters"]
                             if row["name"] == "cycles")
                cycle["value"] = value
            raw = render_log(operations, summary)
            self.input["raw_logs"][process["id"]] = raw
            case = manifest.select_cases(self.contract, formats=[process["format"]])[0]
            process["observation"] = verify_output(raw, case=case, fmt=process["format"],
                policy=process["policy"], binding_id=process["qualification_id"],
                sample_id=process["id"], pair_index=process["pair_index"], phase=process["phase"],
                contract=self.contract)
        self.assertEqual(reported_deltas, {REFERENCE: (1 << 32) - 1, CANDIDATE: 6})
        result = self.check(self.input)
        self.assertEqual(result["raw_record_validation"], "pass")
        self.assert_blocked(result, "satisfied")
        for fmt in result["formats"]:
            self.assertTrue(fmt["conditional_criteria_satisfied"])
            for pair in fmt["pairs"]:
                self.assertTrue(pair["candidate_reported_cycles_not_increased"])
                self.assertEqual(rational(pair["candidate_reference_reported_cycle_ratio"]),
                                 Fraction(6, (1 << 32) - 1))

    def test_primes_and_whole_warmup_pairs_cannot_change_conditional_criteria(self):
        for row in self.input["processes"]:
            candidate = row["policy"] == CANDIDATE
            samples = (100000 if candidate else 1) if row["phase"] == "warmup" else (95 if candidate else 100)
            prime = 500000000 if candidate else 1
            cycles = (50000 if candidate else 1) if row["phase"] == "warmup" else 1000
            replace_batch(self.input, self.contract, row["id"],
                          durations=[prime, *([samples] * 32)], cycles=cycles)
        result = self.check(self.input)
        self.assertEqual(result["formats"], self.valid_result["formats"])
        self.assert_blocked(result, "satisfied")
        for batch in result["batches"]:
            self.assertEqual(batch["prime_duration_ns"], 500000000 if batch["policy"] == CANDIDATE else 1)
            self.assertEqual(batch["included_in_conditional_criteria"], batch["pair_index"] != 0)
        self.assertEqual(sum(row["timed_operations"] for row in result["batches"]
                             if row["included_in_conditional_criteria"]), 640)

    def test_statistics_reduce_five_batch_means_and_preserve_fractional_nanoseconds(self):
        totals = [3200, 3232, 6401, 9615, 12799]
        for pair, total in enumerate(totals, 1):
            quotient, remainder = divmod(total, 32)
            intervals = [quotient + int(index < remainder) for index in range(32)]
            replace_batch(self.input, self.contract, f"warm-simx-fp16-pair{pair}-" + REFERENCE,
                          durations=[123456, *intervals])
        result = self.check(self.input)
        stats = result["formats"][0]["policy_statistics"][REFERENCE]
        values = [Fraction(total, 32) for total in totals]
        average = sum(values) / 5
        variance = sum(value * value for value in values) / 5 - average * average
        self.assertEqual(stats["count"], 5)
        self.assertEqual(rational(stats["minimum"]), Fraction(100))
        self.assertEqual(rational(stats["maximum"]), Fraction(12799, 32))
        self.assertEqual(rational(stats["median"]), Fraction(6401, 32))
        self.assertEqual(rational(stats["population_variance_ns2"]), variance)
        self.assertAlmostEqual(stats["population_stddev"], math.sqrt(float(variance)), places=12)
        self.assertNotEqual(rational(stats["median"]), average)

    def test_threshold_uses_exact_integers_when_float_ratios_are_identical(self):
        reference = 20 * (1 << 53)
        threshold = 19 * (1 << 53)
        self.assertEqual(float(Fraction(threshold - 1, reference)),
                         float(Fraction(threshold + 1, reference)))
        for offset, expected in ((-1, True), (0, True), (1, False)):
            with self.subTest(offset=offset):
                rows = metric_batches([reference] * 5, [threshold + offset] * 5)
                result = analyze._format_result("fp16", rows, self.contract, "7" * 64)
                self.assertIs(result["conditional_criteria"]["host_median_at_most_95_percent_of_reference"], expected)
                self.assertIs(result["conditional_criteria_satisfied"], expected)
                self.assertEqual(rational(result["candidate_reference_median_ratio"]),
                                 Fraction(threshold + offset, reference))

    def test_conditional_host_and_reported_cycle_comparisons_do_not_round_away_one_unit(self):
        base = 1 << 63
        self.assertEqual(float(base), float(base + 1))
        for host_extra, cycle_extra in ((1, 0), (0, 1)):
            with self.subTest(host_extra=host_extra, cycle_extra=cycle_extra):
                rows = metric_batches([base] * 5, [base + host_extra] * 5,
                    reference_cycles=base, candidate_cycles=base + cycle_extra)
                result = analyze._format_result("fp16", rows, self.contract, "7" * 64)
                self.assertIs(result["conditional_criteria"]["no_slower_measured_host_pair"], not host_extra)
                self.assertIs(result["conditional_criteria"]["no_increased_measured_pair_reported_cycles"], not cycle_extra)

    def test_exact_population_variance_preserves_small_spread_at_large_offsets(self):
        base = (1 << 63) + 1
        result = analyze._statistics([base + index for index in range(5)])
        self.assertEqual(rational(result["minimum"]), Fraction(base, 32))
        self.assertEqual(rational(result["maximum"]), Fraction(base + 4, 32))
        self.assertEqual(rational(result["median"]), Fraction(base + 2, 32))
        self.assertEqual(rational(result["population_variance_ns2"]), Fraction(1, 512))
        self.assertAlmostEqual(result["population_stddev"], math.sqrt(2) / 32, places=15)

    def test_no_subset_replacement_duplicate_or_reordered_processes(self):
        changes = {
            "missing": lambda value: value["processes"].pop(),
            "extra": lambda value: value["processes"].append(deepcopy(value["processes"][0])),
            "duplicated": lambda value: value["processes"].__setitem__(1, deepcopy(value["processes"][0])),
            "reversed": lambda value: value["processes"].reverse(),
            "swapped_pair": lambda value: value["processes"].__setitem__(slice(0, 2), value["processes"][1::-1]),
            "tuple": lambda value: value.__setitem__("processes", tuple(value["processes"])),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                self.reject(change)

    def test_process_identity_outcome_and_schema_are_exact(self):
        changes = {"id": "replacement", "backend": "rtlsim", "format": "bf16", "policy": CANDIDATE,
            "pair_index": True, "phase": "measured", "sample_id": "replacement",
            "command_id": "replacement", "outcome": "fail", "log": "../other.log",
            "qualification_id": "8" * 64, "build_qualification_id": "8" * 64}
        for key, value in changes.items():
            with self.subTest(field=key):
                self.reject(lambda envelope, key=key, value=value: envelope["processes"][0].__setitem__(key, value))
        for change in (lambda row: row.pop("binding"), lambda row: row.update(phase_acceptance=True)):
            self.reject(lambda envelope, change=change: change(envelope["processes"][0]), "incorrect fields")

    def test_raw_log_inventory_and_original_process_identity_are_required(self):
        first, second = (row["id"] for row in self.original["processes"][:2])
        changes = {
            "missing": lambda value: value["raw_logs"].pop(first),
            "extra": lambda value: value["raw_logs"].update(unexpected="PASSED!"),
            "reused": lambda value: value["raw_logs"].__setitem__(first, value["raw_logs"][second]),
            "nontext": lambda value: value["raw_logs"].__setitem__(first, []),
            "truncated": lambda value: value["raw_logs"].__setitem__(first, "PASSED!\n"),
            "failure": lambda value: value["raw_logs"].__setitem__(first, value["raw_logs"][first] + "ERROR\n"),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                self.reject(change)

    def test_caller_authored_summaries_cannot_override_raw_observations(self):
        changes = {
            "timing": lambda row: row["timed_operation_durations_ns"].__setitem__(0, 1),
            "float timing": lambda row: row["timed_operation_durations_ns"].__setitem__(0, 100.0),
            "extra interval": lambda row: row["timed_operation_durations_ns"].append(100),
            "missing prime": lambda row: row["operation_durations_ns"].pop(0),
            "counter": lambda row: row["counter_deltas"][0].__setitem__("value", 999),
            "counter availability": lambda row: row["counter_deltas"][0].__setitem__("available", 1),
            "accounting": lambda row: row["accounting"].__setitem__("launches", 32),
            "cleanup": lambda row: row["summary"]["counts"].__setitem__("errors", 1),
            "acceptance": lambda row: row.__setitem__("performance_acceptance", True),
            "raw digest": lambda row: row.__setitem__("raw_log_sha256", "0" * 64),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                self.reject(lambda value, change=change: change(value["processes"][0]["observation"]),
                            "revalidated raw observation")

    def test_rehashed_raw_corruption_does_not_acquire_validity(self):
        def corrupt_word(operations, summary):
            operations[0]["actual_bits"][0] = "deadbeef"

        def counter_reset(operations, summary):
            before = summary["snapshots"]["after_prime"]["counters"][0]["value"]
            summary["snapshots"]["after_batch"]["counters"][0]["value"] = before - 1

        def floating_interval(operations, summary):
            operations[1]["end_ns"] = float(operations[1]["end_ns"])

        for change in (corrupt_word, counter_reset, floating_interval):
            def corrupt(envelope, change=change):
                row = envelope["processes"][0]
                operations, summary = decode_log(envelope["raw_logs"][row["id"]])
                change(operations, summary)
                raw = render_log(operations, summary)
                envelope["raw_logs"][row["id"]] = raw
                row["observation"]["raw_log_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
            with self.subTest(change=change.__name__):
                self.reject(corrupt)

    def test_contract_changes_and_wrong_expected_revision_are_rejected(self):
        for revision in ("a" * 40, "short", "A" * 40, "", True, 1, None):
            with self.subTest(revision=revision), self.assertRaises(analyze.AnalysisError):
                self.check(self.original, revision=revision)
        for group, field, value in (("analysis", "candidate_median_percent_of_reference_max", 96),
                                    ("sampling", "timed_operations", 31),
                                    ("analysis", "optional_stopping", True)):
            contract = deepcopy(self.contract)
            contract[group][field] = value
            with self.subTest(field=field), self.assertRaises(analyze.AnalysisError):
                self.check(self.original, contract=contract)

    def test_build_inventory_and_exact_binding_schema_are_required(self):
        self.reject(lambda value: value["build_bindings"].pop("simx-bf16"))
        self.reject(lambda value: value["build_bindings"].update(unexpected={}))
        for key in self.original["build_bindings"]["simx-fp16"]:
            with self.subTest(missing=key):
                self.reject(lambda value, key=key: value["build_bindings"]["simx-fp16"].pop(key),
                            "incorrect fields")
        self.reject(lambda value: value["build_bindings"]["simx-fp16"].update(extra=True), "incorrect fields")

    def test_same_source_and_complete_build_identity_bind_both_policy_arms(self):
        changes = {
            "dirty source": lambda row: row["source"]["checkout"].update(dirty=True),
            "changed paths": lambda row: row["source"]["checkout"].update(changed_paths=["sw/changed.cpp"]),
            "untracked source": lambda row: row["source"]["checkout"].update(untracked_paths=["unbound.h"]),
            "source blockers": lambda row: row["source"]["checkout"].update(blockers=["unverified"]),
            "source outcome": lambda row: row["source"]["checkout"].update(outcome="fail"),
            "bad tree": lambda row: row["source"]["checkout"].update(tree="invalid"),
            "another source": lambda row: row["source"]["checkout"].update(tree="9" * 40),
            "contract digest": lambda row: row.update(contract_sha256="9" * 64),
            "format": lambda row: row.update(format="fp16"),
            "backend": lambda row: row.update(backend="rtlsim"),
            "fixture": lambda row: row["case"]["expected"].__setitem__(0, "deadbeef"),
            "sampling": lambda row: row["sampling"].update(timed_operations=31),
            "performance mode": lambda row: row.update(performance_environment={"PERF": "0"}),
            "binary bytes": lambda row: row["artifacts"][0].update(sha256="9" * 64),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                self.reject(lambda value, change=change: change(value["build_bindings"]["simx-bf16"]))
        for process_index in (0, 1):
            with self.subTest(arm=process_index):
                self.reject(lambda value, index=process_index:
                            value["processes"][index].update(build_qualification_id="9" * 64))

    def test_supervisor_duration_is_typed_finite_and_contains_owner_lifetime(self):
        for invalid in (True, False, -1, "1", None, float("nan"), float("inf"), 1e308, 0):
            with self.subTest(duration=repr(invalid)):
                self.reject(lambda value, invalid=invalid:
                            value["processes"][0].update(process_duration_seconds=invalid))
        row = self.input["processes"][0]
        intervals = row["observation"]["summary"]["host_intervals_ns"]
        span = intervals["close"]["end_ns"] - intervals["create"]["begin_ns"]
        row["process_duration_seconds"] = (span - 1000) / 1_000_000_000
        self.assert_blocked(self.check(self.input), "satisfied")
        row["process_duration_seconds"] = (span - 1002) / 1_000_000_000
        with self.assertRaisesRegex(analyze.AnalysisError, "supervised"):
            self.check(self.input)

    def test_statistics_helpers_reject_noninteger_or_incomplete_populations(self):
        for invalid in (True, False, 0, -1, 1.0, "1", None, float("nan"), float("inf")):
            values = [1, 2, 3, 4, invalid]
            with self.subTest(value=repr(invalid)), self.assertRaises(ValueError):
                analyze._statistics(values)
        for values in ([], [1] * 4, [1] * 6):
            with self.subTest(count=len(values)), self.assertRaises(ValueError):
                analyze._statistics(values)

    def test_input_observations_are_immutable_and_output_diagnostics_are_detached(self):
        before = encoded(self.input)
        with mock.patch("subprocess.Popen", side_effect=AssertionError("analysis executed a subprocess")):
            result = self.check(self.input)
        self.assertEqual(encoded(self.input), before)
        result["batches"][0]["operation_durations_ns"][0] = 0
        result["batches"][0]["reported_counter_deltas"][0]["value"] = 0
        result["counts"]["processes"] = 0
        result["full_hypothesis_qualification"]["qualified"] = True
        self.assertEqual(encoded(self.input), before)
        self.assertEqual(self.contract["complete_matrix"]["processes"], 24)
        self.assertIs(analyze._full_hypothesis_qualification()["qualified"], False)

    def test_fresh_cli_exposes_block_for_positive_and_negative_conditional_predicates(self):
        negative = deepcopy(self.original)
        replace_batch(negative, self.contract, "warm-simx-fp16-pair5-" + CANDIDATE, durations=101)
        for label, value, conditional in (("positive", self.original, "satisfied"),
                                          ("negative", negative, "not_satisfied")):
            incoming = self.directory / (label + "-fresh-input.json")
            incoming.write_bytes(encoded(value))
            for write_output in (False, True):
                command = [sys.executable, "-B", str(ROOT / "ci/project/p06_warm_analyze.py"),
                           "--input", str(incoming), "--source-revision", REVISION]
                output = self.directory / (label + "-fresh-result.json")
                if write_output:
                    command.extend(("--output", str(output)))
                with self.subTest(conditional=conditional, write_output=write_output):
                    run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                         check=False, timeout=60)
                    self.assertEqual((run.returncode, run.stderr), (0, ""))
                    emitted = json.loads(run.stdout)
                    self.assertEqual(emitted["hypothesis_evaluation"], "blocked")
                    self.assertEqual(emitted["conditional_evaluation"], conditional)
                    result = json.loads(output.read_bytes()) if write_output else emitted
                    self.assertEqual(emitted["full_hypothesis_qualification"],
                                     result["full_hypothesis_qualification"])
                    self.assertEqual(result["raw_record_validation"], "pass")
                    self.assert_blocked(result, conditional)

    def test_caller_cannot_supply_a_qualification_flag_or_claim(self):
        with self.assertRaises(TypeError):
            analyze.analyze_processes(self.original["processes"], self.original["raw_logs"],
                build_bindings=self.original["build_bindings"], contract=self.contract,
                expected_revision=REVISION, counter_transport_qualified=True)
        with self.assertRaises(SystemExit) as error:
            self.cli("--counter-transport-qualified")
        self.assertEqual(error.exception.code, 2)
        claimed = deepcopy(self.original)
        claimed["full_hypothesis_qualification"] = {"status": "pass", "qualified": True}
        incoming = self.directory / "claimed-qualification.json"
        incoming.write_bytes(encoded(claimed))
        status, output, errors = self.cli(incoming=incoming)
        self.assertEqual((status, output), (2, ""))
        self.assertIn("incorrect fields", errors)

    def test_cli_stdout_and_exclusive_file_output_agree(self):
        status, output, errors = self.cli()
        self.assertEqual((status, errors), (0, ""))
        self.assertEqual(json.loads(output), self.valid_result)
        destination = self.directory / "exclusive-analysis.json"
        status, output, errors = self.cli("--output", str(destination))
        self.assertEqual((status, errors), (0, ""))
        summary = json.loads(output)
        self.assertEqual(summary["schema_version"], 2)
        self.assertEqual(summary["hypothesis_evaluation"], "blocked")
        self.assertEqual(summary["conditional_evaluation"], "satisfied")
        self.assertEqual(summary["raw_record_validation"], "pass")
        self.assertEqual(summary["archive_provenance_validation"], "required_from_caller")
        self.assertEqual(summary["full_hypothesis_qualification"],
                         self.valid_result["full_hypothesis_qualification"])
        self.assertEqual(summary["report"], str(destination))
        original = destination.read_bytes()
        self.assertEqual(json.loads(original), self.valid_result)
        status, output, errors = self.cli("--output", str(destination))
        self.assertEqual((status, output), (2, ""))
        self.assertIn("File exists", errors)
        self.assertEqual(destination.read_bytes(), original)

    def test_cli_invalid_data_does_not_create_output(self):
        incoming = self.directory / "invalid-input.json"
        incoming.write_bytes(b'{"schema_version":1,"build_bindings":{},"processes":[],"raw_logs":{}}')
        destination = self.directory / "must-not-exist.json"
        status, output, errors = self.cli("--output", str(destination), incoming=incoming)
        self.assertEqual((status, output), (2, ""))
        self.assertIn("rejected", errors)
        self.assertNotIn("Traceback", errors)
        self.assertFalse(destination.exists())

    def test_cli_will_not_follow_an_existing_output_symlink(self):
        target = self.directory / "preserve.txt"
        target.write_text("preserve user bytes\n")
        link = self.directory / "analysis-link.json"
        link.symlink_to(target)
        status, output, errors = self.cli("--output", str(link))
        self.assertEqual((status, output), (2, ""))
        self.assertIn("File exists", errors)
        self.assertEqual(target.read_text(), "preserve user bytes\n")

    def test_json_reader_rejects_duplicate_fields_types_nonfinite_and_excess_nesting(self):
        bodies = [
            b'{"schema_version":1,"schema_version":1,"build_bindings":{},"processes":[],"raw_logs":{}}',
            b'{"schema_version":1,"build_bindings":{"x":1,"x":2},"processes":[],"raw_logs":{}}',
            b'{"schema_version":true,"build_bindings":{},"processes":[],"raw_logs":{}}',
            b'{"schema_version":1.0,"build_bindings":{},"processes":[],"raw_logs":{}}',
            b'{"schema_version":1,"build_bindings":{},"processes":[],"raw_logs":{},"extra":0}',
            b'[]', b'null', b'{}', b'{', b'\xff',
            b'{"schema_version":1,"build_bindings":{},"processes":[NaN],"raw_logs":{}}',
            b'{"schema_version":1,"build_bindings":{},"processes":[Infinity],"raw_logs":{}}',
            b'{"schema_version":1,"build_bindings":{},"processes":[-Infinity],"raw_logs":{}}',
            b'[' * 33 + b'0' + b']' * 33,
            b'{"schema_version":1,"build_bindings":{},"processes":[' + b'9' * 5000 + b'],"raw_logs":{}}',
        ]
        incoming = self.directory / "malformed.json"
        for index, body in enumerate(bodies):
            incoming.write_bytes(body)
            with self.subTest(case=index), self.assertRaises(ValueError):
                analyze._read_input(incoming)

    def test_json_reader_requires_bounded_regular_nonlinked_inputs(self):
        oversized = self.directory / "oversized.json"
        with oversized.open("wb") as stream:
            stream.truncate(analyze.MAX_INPUT_BYTES + 1)
        fifo = self.directory / "input-fifo"
        os.mkfifo(fifo)
        link = self.directory / "input-link.json"
        link.symlink_to(self.input_path)
        parent_link = self.directory / "linked-directory"
        parent_link.symlink_to(self.directory, target_is_directory=True)
        paths = (self.directory / "missing.json", self.directory, oversized, fifo, link,
                 parent_link / self.input_path.name, self.directory / "nested" / ".." / self.input_path.name)
        for path in paths:
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                analyze._read_input(path)

    def test_cli_rejects_overflowing_exponents_even_in_uninterpreted_binding_fields(self):
        incoming = self.directory / "overflow-input.json"
        value = deepcopy(self.original)
        value["processes"][0]["binding"]["size_bytes"] = "EXPONENT_SENTINEL"
        original = encoded(value)
        for token in (b"1e400", b"-1e400", b"1e999999"):
            incoming.write_bytes(original.replace(b'"EXPONENT_SENTINEL"', token))
            with self.subTest(token=token):
                status, output, errors = self.cli(incoming=incoming)
                self.assertEqual((status, output), (2, ""))
                self.assertIn("nonfinite", errors)
        incoming.write_bytes(
            b'{"schema_version":1,"build_bindings":{},'
            b'"processes":[{"process_duration_seconds":0.125}],"raw_logs":{"literal":"1e400"}}')
        parsed = analyze._read_input(incoming)
        self.assertEqual(parsed["processes"][0]["process_duration_seconds"], 0.125)
        self.assertEqual(parsed["raw_logs"]["literal"], "1e400")


if __name__ == "__main__":
    unittest.main()
