# SPDX-License-Identifier: Apache-2.0
"""Independent corruption tests of synthetic records, never native evidence."""

from copy import deepcopy
import hashlib
import json
import math
import unittest
from unittest.mock import patch

import p06_contract
import p06_records as records
from p06_test_samples import (BINDING, REVISION, raw_records, render_log,
                              sample, samples, synthetic_log)


class SampleRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = p06_contract.load_analysis_contract()
        cls.workloads = p06_contract.select_workloads(cls.contract)
        cls.operator = cls.workloads[0]
        cls.model = cls.workloads[3]

    def raw(self, workload=None):
        workload = self.operator if workload is None else workload
        return raw_records(workload, workload["id"] + "-measurement-0", contract=self.contract)

    def verify(self, text, workload=None, **changes):
        workload = self.operator if workload is None else workload
        kwargs = {"sample_id": workload["id"] + "-measurement-0", "source_revision": REVISION,
                  "fixture_sha256": workload["fixture_sha256"], "contract": self.contract}
        kwargs.update(changes)
        return records.verify_sample(text, workload, BINDING, **kwargs)

    def reject_raw(self, raw, workload=None):
        workload = self.operator if workload is None else workload
        with self.assertRaises(ValueError):
            self.verify(render_log(workload, raw), workload)

    def test_original_numerical_readers_receive_the_complete_unfiltered_log(self):
        for workload in self.workloads:
            raw = self.raw(workload)
            text = render_log(workload, raw)
            module = records.operator_records if workload["kind"] == "matmul" else records.model_records
            with self.subTest(workload=workload["id"]), patch.object(
                    module, "verify_output", wraps=module.verify_output) as verify:
                actual = self.verify(text, workload)
                self.assertEqual(verify.call_args.args[0], text)
                marker = "P03_RESULT" if workload["kind"] == "matmul" else "P04_RESULT"
                self.assertEqual(actual["numerical_results"], [raw[marker]])
                self.assertEqual(actual["raw_log_sha256"], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(actual["snapshots"], {"begin": raw["P06_BEGIN"], "end": raw["P06_END"]})
                self.assertEqual(actual["release"], raw["P06_RELEASE"])

    def test_accounting_is_derived_from_actual_matrix_dimensions_and_dispatches(self):
        expected = [(256, 192, 128), (512, 384, 128), (2048, 768, 512), (2560, 1152, 768)]
        for index, workload in enumerate(self.workloads):
            actual = self.verify(render_log(workload, self.raw(workload)), workload)
            macs, inputs, outputs = expected[index % 4]
            accounting = actual["accounting"]
            launches = 3 if workload["kind"] == "mlp" else 1
            self.assertEqual(accounting["macs"], macs)
            self.assertEqual(accounting["flops"], 2 * macs)
            self.assertEqual(accounting["input_h2d_bytes"], inputs)
            self.assertEqual(accounting["poison_h2d_bytes"], outputs)
            self.assertEqual(accounting["tensor_h2d_bytes"], inputs + outputs)
            self.assertEqual(accounting["tensor_d2h_bytes"], outputs)
            self.assertEqual(accounting["argument_payload_bytes"], 56 * launches)
            self.assertEqual(actual["dispatch_counts"]["launches"], launches)
            self.assertEqual(actual["dispatch_counts"]["tensor_writes"], 3 * launches)
            self.assertEqual(actual["dispatch_counts"]["tensor_reads"], launches)
            self.assertEqual(accounting["host_relu_elements"], 128 if launches == 3 else 0)
            self.assertEqual(accounting["host_cast_elements"], 128 if launches == 3 else 0)
            self.assertEqual(accounting["host_bridge_input_bytes"], 512 if launches == 3 else 0)
            self.assertEqual(accounting["host_bridge_output_bytes"], 256 if launches == 3 else 0)
            self.assertEqual(accounting["host_assembly_bytes"], 256 if launches == 3 else 0)

    def test_unsigned_counter_extremes_and_zero_optional_deltas_are_exact(self):
        raw = self.raw()
        for before, after in zip(raw["P06_BEGIN"]["counters"], raw["P06_END"]["counters"]):
            if before["enabled"]:
                before["value"] = (1 << 64) - 6
                after["value"] = (1 << 64) - 1 if before["name"] in ("cycles", "instructions") else before["value"]
        actual = self.verify(render_log(self.operator, raw))
        self.assertEqual(sum(row["available"] for row in actual["counter_deltas"]), 33)
        self.assertEqual(sum(not row["available"] for row in actual["counter_deltas"]), 12)
        for row in actual["counter_deltas"]:
            self.assertEqual(row["value"], (5 if row["name"] in ("cycles", "instructions") else 0)
                             if row["available"] else None)

    def test_marker_chronology_duplicates_missing_and_wrong_routes_are_rejected(self):
        for workload in (self.operator, self.model):
            text = render_log(workload, self.raw(workload))
            lines = text.splitlines()
            marked = [index for index, line in enumerate(lines) if line.startswith(("P06_", "P03_RESULT", "P04_RESULT"))]
            for index in marked:
                for changed in (lines[:index] + lines[index + 1:],
                                lines[:index] + [lines[index]] + lines[index:]):
                    with self.subTest(workload=workload["id"], line=index), self.assertRaises(ValueError):
                        self.verify("\n".join(changed) + "\n", workload)
            for left, right in zip(marked, marked[1:]):
                changed = list(lines)
                changed[left], changed[right] = changed[right], changed[left]
                with self.subTest(route=workload["kind"], swapped=(left, right)), self.assertRaises(ValueError):
                    self.verify("\n".join(changed) + "\n", workload)
            for prefix in ("P06_UNKNOWN {}\n", "P04_RESULT {}\n", "P03_RESULT {}\n", "prefix P06_BEGIN {}\n"):
                with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                    self.verify(prefix + text, workload)

    def test_operator_rejections_are_required_once_between_open_and_result(self):
        text = render_log(self.operator, self.raw())
        marker = "P03_REJECTIONS checked=2\n"
        for changed in (text.replace(marker, ""), marker + text.replace(marker, ""),
                        text.replace(marker, marker * 2), text.replace(marker, "P03_REJECTIONS checked=1\n"),
                        text.replace(marker, "") + marker):
            with self.subTest(text=changed[-80:]), self.assertRaises(ValueError):
                self.verify(changed)
        model_text = render_log(self.model, self.raw(self.model))
        with self.assertRaises(ValueError):
            self.verify(marker + model_text, self.model)

    def test_failure_text_hidden_markers_controls_and_trailing_output_fail(self):
        text = render_log(self.operator, self.raw())
        for prefix in ("ERROR: query failed\n", "P06_FAILURE {}\n", "P03_FAILURE bad\n",
                       "fatal: aborted\n", "Segmentation fault\n", "runtime error: overflow\n",
                       "false PASSED status\n", "\x00", "\x1b", "\x7f", "\u0085", "\u2028", "\u2029", "\ud800"):
            with self.subTest(prefix=repr(prefix)), self.assertRaises(ValueError):
                self.verify(prefix + text)
        for suffix in ("diagnostic\n", "PASSED!\n", "\n"):
            with self.subTest(suffix=repr(suffix)), self.assertRaises(ValueError):
                self.verify(text + suffix)
        for changed in (text.replace("P06_BEGIN", "p06_begin"), text.replace("P06_BEGIN ", "P06_BEGIN\t"),
                        text.replace("PASSED!", "PASSED"), text.replace("PASSED!", " PASSED!")):
            with self.subTest(text=changed[-40:]), self.assertRaises(ValueError):
                self.verify(changed)

    def test_json_transport_is_bounded_unambiguous_and_unsigned(self):
        text = render_log(self.operator, self.raw())
        for replacement in ("-1", "-0", "1.0", "1e0", "NaN", "Infinity", "true", "null",
                            json.dumps("150"), str(1 << 64), "[" * 17 + "0" + "]" * 17):
            changed = text.replace('"query_begin_ns":150', '"query_begin_ns":' + replacement, 1)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.verify(changed)
        for key in ("schema_version", "sample_id", "status", "value", "counters"):
            changed = text.replace('"' + key + '":', '"' + key + '":0,"' + key + '":', 1)
            with self.subTest(duplicate=key), self.assertRaises(ValueError):
                self.verify(changed)
        for payload in ("[]", "null", "{} trailing", "{" + '"x":' * 2):
            changed = text.splitlines()
            changed[1] = "P06_BEGIN " + payload
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.verify("\n".join(changed) + "\n")
        with patch.object(records, "MAX_LOG_BYTES", 100), self.assertRaises(ValueError):
            self.verify(text)
        with patch.object(records, "MAX_RECORD_BYTES", 100), self.assertRaises(ValueError):
            self.verify(text)

    def test_snapshot_scalar_identity_and_types_cannot_be_coerced(self):
        for marker in ("P06_BEGIN", "P06_END"):
            for field, values in {
                "schema_version": (True, 2), "sample_id": ("other", "", None),
                "context_id": (True, 2), "device_index": (False, 1),
                "compiled_memory_block_bytes": (True, 32, 128),
                "query_begin_ns": (True, -1, 1.0, "1", None, 1 << 64),
                "query_end_ns": (True, -1, 1.0, "1", None, 1 << 64),
            }.items():
                for value in values:
                    raw = self.raw()
                    raw[marker][field] = value
                    with self.subTest(marker=marker, field=field, value=value):
                        self.reject_raw(raw)
            for field in ("counters", "capabilities", "query_begin_ns"):
                raw = self.raw()
                del raw[marker][field]
                self.reject_raw(raw)
            raw = self.raw()
            raw[marker]["extra"] = 0
            self.reject_raw(raw)

    def test_capability_inventory_status_and_topology_are_frozen(self):
        for marker in ("P06_BEGIN", "P06_END"):
            for index in range(13):
                for field, value in (("value", self.raw()[marker]["capabilities"][index]["value"] + 1),
                                     ("status", 1), ("status", False), ("id", True), ("name", "other")):
                    raw = self.raw()
                    raw[marker]["capabilities"][index][field] = value
                    with self.subTest(marker=marker, index=index, field=field):
                        self.reject_raw(raw)
            for mutation in (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                             lambda rows: rows.append(deepcopy(rows[0])),
                             lambda rows: rows.__setitem__(1, deepcopy(rows[0]))):
                raw = self.raw()
                mutation(raw[marker]["capabilities"])
                self.reject_raw(raw)

    def test_counter_metadata_query_success_and_unavailability_are_exact(self):
        for marker in ("P06_BEGIN", "P06_END"):
            for field, value in (("name", "unknown"), ("mpm_class", 99), ("csr", 99), ("core_id", 1),
                                 ("scope", "global"), ("unit", "nanoseconds"), ("required_isa", True),
                                 ("enabled", False), ("enabled", 1), ("status", 1), ("status", None),
                                 ("status", False), ("value", None), ("value", True), ("value", -1),
                                 ("value", 1 << 64), ("value", 1.0), ("value", "1")):
                raw = self.raw()
                raw[marker]["counters"][0][field] = value
                with self.subTest(marker=marker, field=field, value=value):
                    self.reject_raw(raw)
            for field, value in (("status", 0), ("value", 0), ("enabled", True), ("enabled", None)):
                raw = self.raw()
                next(row for row in raw[marker]["counters"] if not row["enabled"])[field] = value
                self.reject_raw(raw)
            for mutation in (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                             lambda rows: rows.append(deepcopy(rows[0])),
                             lambda rows: rows.__setitem__(1, deepcopy(rows[0]))):
                raw = self.raw()
                mutation(raw[marker]["counters"])
                self.reject_raw(raw)

    def test_counter_wrap_regression_and_zero_work_are_rejected(self):
        for index, before in enumerate(self.raw()["P06_BEGIN"]["counters"]):
            if before["enabled"]:
                raw = self.raw()
                raw["P06_END"]["counters"][index]["value"] = before["value"] - 1
                with self.subTest(counter=before["name"]):
                    self.reject_raw(raw)
                if before["name"] in ("cycles", "instructions"):
                    raw["P06_END"]["counters"][index]["value"] = before["value"]
                    self.reject_raw(raw)

    def test_release_requires_matching_identity_and_real_success(self):
        for field, values in {"schema_version": (True, 2), "sample_id": ("other", None),
                              "context_id": (True, 2), "status": (True, 1, None)}.items():
            for value in values:
                raw = self.raw()
                raw["P06_RELEASE"][field] = value
                self.reject_raw(raw)
        for field in ("status", "sample_id"):
            raw = self.raw()
            del raw["P06_RELEASE"][field]
            self.reject_raw(raw)
        raw = self.raw()
        raw["P06_RELEASE"]["extra"] = 0
        self.reject_raw(raw)

    def test_bad_original_numerics_dispatch_bytes_and_cleanup_cannot_be_hidden(self):
        for workload in self.workloads:
            raw = self.raw(workload)
            marker = "P03_RESULT" if workload["kind"] == "matmul" else "P04_RESULT"
            numerical = raw[marker]
            if workload["kind"] == "matmul":
                words = numerical["actual_bits"]
            else:
                words = numerical["trace"]["output_words"]
            words[-1] = f"{int(words[-1], 16) ^ 1:08x}"
            self.reject_raw(raw, workload)
        for field, value in (("writes", 2), ("reads", 0), ("launches", 2), ("waits", 0),
                             ("a_bytes", 2), ("d_bytes", 4), ("argument_bytes", "00" * 56)):
            raw = self.raw()
            raw["P03_RESULT"]["dispatch"][field] = value
            self.reject_raw(raw)
        for field, value in (("primary", 1), ("cleanup", 1), ("used_after", 0), ("free_after", 0)):
            raw = self.raw()
            raw["P03_RESULT"]["resources"][field] = value
            self.reject_raw(raw)
        for index in range(3):
            for field, value in (("writes_enqueued", 2), ("launches_enqueued", 0),
                                 ("reads_enqueued", 0), ("a_bytes", 1), ("argument_bytes", "00" * 56)):
                raw = self.raw(self.model)
                raw["P04_RESULT"]["trace"]["native"][index]["dispatch"][field] = value
                self.reject_raw(raw, self.model)
            for field in ("a_bytes", "b_bytes"):
                raw = self.raw(self.model)
                stage = raw["P04_RESULT"]["trace"]["native"][index]
                changed = bytearray.fromhex(stage[field])
                changed[0] ^= 1
                stage[field] = changed.hex()
                self.reject_raw(raw, self.model)
        for field in ("owner_closed", "bridge_valid", "assembled"):
            raw = self.raw(self.model)
            raw["P04_RESULT"]["trace"][field] = False
            self.reject_raw(raw, self.model)

    def test_query_timing_respects_order_creation_work_and_close_boundaries(self):
        for marker, field, value in (("P06_BEGIN", "query_end_ns", 149),
                                     ("P06_END", "query_end_ns", 3999),
                                     ("P06_END", "query_begin_ns", 154)):
            raw = self.raw()
            raw[marker][field] = value
            self.reject_raw(raw)
        for marker, field, value in (("P06_BEGIN", "query_begin_ns", 99),
                                     ("P06_BEGIN", "query_end_ns", 201),
                                     ("P06_END", "query_begin_ns", 3064),
                                     ("P06_END", "query_end_ns", 4011)):
            raw = self.raw(self.model)
            raw[marker][field] = value
            self.reject_raw(raw, self.model)
        raw = self.raw(self.model)
        raw["P06_BEGIN"].update(query_begin_ns=100, query_end_ns=200)
        raw["P06_END"].update(query_begin_ns=4000, query_end_ns=4010)
        actual = self.verify(render_log(self.model, raw), self.model)
        self.assertEqual(actual["host_timings_ns"]["model_create"], 100)
        self.assertEqual(actual["host_timings_ns"]["observer_begin_query"], 100)
        self.assertEqual(actual["host_timings_ns"]["model_close"], 10)
        self.assertEqual(actual["host_timings_ns"]["observer_end_query"], 10)

    def test_external_identity_and_fixture_pins_are_not_inferred_from_log(self):
        text = render_log(self.operator, self.raw())
        for field, values in {"sample_id": ("other", "A", "-bad", "a" * 129, None),
                              "source_revision": ("0" * 39, "g" * 40, None),
                              "fixture_sha256": ("f" * 64, True)}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.verify(text, **{field: value})
        with patch.object(records.manifest, "_read_file", return_value=b"corrupted fixture"), self.assertRaises(ValueError):
            self.verify(text)
        workload = deepcopy(self.operator)
        workload["m"] += 8
        with self.assertRaises(ValueError):
            self.verify(text, workload)

    def test_model_nested_durations_fit_their_proven_parent_intervals(self):
        for field in ("advance_ns", "bridge_ns", "bridge_compare_ns", "assembly_ns", "output_compare_ns"):
            raw = self.raw(self.model)
            raw["P04_RESULT"]["trace"][field] = 500_000
            with self.subTest(field=field):
                self.reject_raw(raw, self.model)
        for index in range(3):
            for field in ("wait_ns", "compare_ns", "close_ns"):
                raw = self.raw(self.model)
                raw["P04_RESULT"]["trace"]["native"][index][field] = 500_000
                with self.subTest(stage=index, field=field):
                    self.reject_raw(raw, self.model)


class SampleSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = p06_contract.load_analysis_contract()
        cls.workloads = p06_contract.select_workloads(cls.contract)
        cls.all_samples = samples(cls.contract)

    def summarize(self, rows=None, workloads=None):
        return records.summarize(self.all_samples if rows is None else rows, self.contract,
                                 self.workloads if workloads is None else workloads)

    def test_full_inventory_and_measured_statistics_exclude_the_retained_warmup(self):
        original = deepcopy(self.all_samples)
        summary = self.summarize()
        self.assertEqual(summary["inventory"], {"workloads": 8, "warmup_processes": 8,
            "measured_processes": 40, "total_processes": 48, "warmup_launches": 12,
            "measured_launches": 60, "total_launches": 72})
        self.assertTrue(summary["full_matrix"])
        self.assertFalse(summary["acceptance_claimed"])
        for workload in summary["workloads"]:
            stats = workload["counter_statistics"][0]["statistics"]
            self.assertEqual({key: stats[key] for key in ("count", "minimum", "maximum", "median")},
                             {"count": 5, "minimum": 900, "maximum": 1300, "median": 1100})
            self.assertAlmostEqual(stats["population_stddev"], math.sqrt(20000))
            self.assertEqual(workload["process_duration_seconds"]["median"], 1.2)
            self.assertEqual(workload["process_duration_seconds"]["maximum"], 1.4)
            self.assertEqual(len(workload["warmup_sample_ids"]), 1)
            self.assertEqual(len(workload["measured_sample_ids"]), 5)
            self.assertEqual(sum(row["available"] for row in workload["counter_statistics"]), 33)
            self.assertTrue(all(row["statistics"] is None for row in workload["counter_statistics"] if not row["available"]))
        self.assertEqual(self.all_samples, original)

    def test_selected_format_is_complete_in_scope_and_never_a_full_matrix(self):
        for offset in (0, 24):
            selected = self.workloads[:4] if offset == 0 else self.workloads[4:]
            summary = self.summarize(self.all_samples[offset:offset + 24], selected)
            self.assertFalse(summary["full_matrix"])
            self.assertFalse(summary["acceptance_claimed"])
            self.assertEqual(summary["inventory"]["total_processes"], 24)
            self.assertEqual(summary["inventory"]["total_launches"], 36)
        for selected, rows in ((self.workloads[:1], self.all_samples[:6]),
                               (list(reversed(self.workloads)), self.all_samples),
                               ([], []), (self.workloads[:4], self.all_samples)):
            with self.subTest(workloads=[row["id"] for row in selected]), self.assertRaises(ValueError):
                self.summarize(rows, selected)

    def test_missing_extra_reordered_repeated_or_failed_samples_cannot_be_dropped(self):
        for mutation in (lambda rows: rows.pop(), lambda rows: rows.append(deepcopy(rows[-1])),
                         lambda rows: rows.reverse(), lambda rows: rows.__setitem__(1, deepcopy(rows[0])),
                         lambda rows: rows[0].update(phase="measurement"),
                         lambda rows: rows[0].update(repetition=True),
                         lambda rows: rows[0].update(outcome="fail"),
                         lambda rows: rows[0].update(sample_id="other"),
                         lambda rows: rows[0].update(workload_id="other"),
                         lambda rows: rows[0].update(extra=True),
                         lambda rows: rows[0].pop("observation")):
            rows = deepcopy(self.all_samples)
            mutation(rows)
            with self.assertRaises(ValueError):
                self.summarize(rows)

    def test_unique_command_log_binding_and_revision_are_required(self):
        for value in ("", "../run", "a" * 257, True):
            rows = deepcopy(self.all_samples)
            rows[0]["command_id"] = value
            with self.subTest(command_id=value), self.assertRaises(ValueError):
                self.summarize(rows)
        for mutation in (
            lambda rows: rows[1].update(command_id=rows[0]["command_id"]),
            lambda rows: rows[1]["observation"].update(raw_log_sha256=rows[0]["observation"]["raw_log_sha256"]),
            lambda rows: rows[0]["observation"].update(source_revision="f" * 40),
        ):
            rows = deepcopy(self.all_samples)
            mutation(rows)
            with self.assertRaises(ValueError):
                self.summarize(rows)
        rows = deepcopy(self.all_samples)
        rows[1] = sample(self.workloads[0], "measurement", 0, contract=self.contract, binding_id="f" * 64)
        with self.assertRaises(ValueError):
            self.summarize(rows)

    def test_stored_derived_fields_are_recomputed_from_retained_observations(self):
        for mutation in (
            lambda row: row["accounting"].update(macs=1),
            lambda row: row["accounting"].update(tensor_h2d_bytes=1),
            lambda row: row["counter_deltas"][0].update(value=1),
            lambda row: row["counter_deltas"][0].update(available=1),
            lambda row: row["host_timings_ns"].update(observer_begin_query=1),
            lambda row: row["dispatch_counts"].update(launches=2),
            lambda row: row["boundaries"].update(physical_time=True),
            lambda row: row["numerical_results"][0].update(mismatches=1),
            lambda row: row.update(contract_id="other"),
            lambda row: row.update(schema_version=True),
            lambda row: row.update(extra=True),
        ):
            rows = deepcopy(self.all_samples)
            mutation(rows[0]["observation"])
            with self.assertRaises(ValueError):
                self.summarize(rows)

    def test_process_duration_bounds_and_containment_are_enforced(self):
        for value in (True, None, "1", -1, float("nan"), float("inf"), 191, 10 ** 1000, 0):
            rows = deepcopy(self.all_samples)
            rows[0]["process_duration_seconds"] = value
            with self.subTest(value=repr(value)[:80]), self.assertRaises(ValueError):
                self.summarize(rows)
        rows = deepcopy(self.all_samples)
        rows[0]["process_duration_seconds"] = 0.000003
        self.summarize(rows)
        rows[0]["process_duration_seconds"] = 0.000002
        with self.assertRaises(ValueError):
            self.summarize(rows)

    def test_complete_observed_model_span_must_fit_its_process_receipt(self):
        rows = deepcopy(self.all_samples)
        workload = self.workloads[3]
        sample_id = rows[19]["sample_id"]
        raw = raw_records(workload, sample_id, contract=self.contract)
        trace = raw["P04_RESULT"]["trace"]
        trace.update(create_begin_ns=0, create_end_ns=1_000_100)
        raw["P06_BEGIN"].update(query_begin_ns=1_000_000, query_end_ns=1_000_005)
        raw["P06_END"].update(query_begin_ns=2_000_000, query_end_ns=2_000_005)
        for stage in trace["native"]:
            stage["submit_begin_ns"] += 1_000_100
            stage["submit_end_ns"] += 1_000_100
            for profile in stage["dispatch"]["event_profiles"]:
                for key in profile:
                    profile[key] += 1_000_100
        rows[19]["observation"] = records.verify_sample(
            render_log(workload, raw), workload, BINDING, sample_id=sample_id,
            source_revision=REVISION, fixture_sha256=workload["fixture_sha256"], contract=self.contract)
        rows[19]["process_duration_seconds"] = 0.0011
        with self.assertRaisesRegex(ValueError, "whole process duration"):
            self.summarize(rows)
        rows = deepcopy(self.all_samples)
        rows[18]["process_duration_seconds"] = 0.000002
        with self.assertRaises(ValueError):
            self.summarize(rows)


if __name__ == "__main__":
    unittest.main()
