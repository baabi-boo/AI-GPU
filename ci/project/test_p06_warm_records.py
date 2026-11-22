# SPDX-License-Identifier: Apache-2.0
"""Adversarial synthetic warm logs; this suite establishes no native result."""

from copy import deepcopy
import hashlib
import itertools
import json
import unittest
from unittest.mock import patch

import p06_warm_contract as manifest
import p06_warm_records as records
from p06_warm_test_fixture import BINDING, argument_hex, raw_records, render_log, synthetic_log


class WarmRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = manifest.load_contract()
        cls.examples = {(fmt, policy): raw_records(fmt, policy, contract=cls.contract)
                        for fmt, policy in itertools.product(manifest.FORMATS, manifest.POLICIES)}

    def raw(self, fmt="fp16", policy="per_operation"):
        return deepcopy(self.examples[fmt, policy])

    def verify(self, raw=None, *, fmt="fp16", policy="per_operation", text=None, **changes):
        case, operations, summary = self.raw(fmt, policy) if raw is None else raw
        kwargs = {"case": case, "fmt": fmt, "policy": policy, "binding_id": BINDING,
                  "sample_id": f"warm-simx-{fmt}-pair1-{policy}", "pair_index": 1,
                  "phase": "measured", "contract": self.contract}
        kwargs.update(changes)
        return records.verify_output(render_log(operations, summary) if text is None else text, **kwargs)

    def reject(self, change, *, fmt="fp16", policy="per_operation"):
        raw = self.raw(fmt, policy)
        change(*raw)
        with self.assertRaises(ValueError):
            self.verify(raw, fmt=fmt, policy=policy)

    @staticmethod
    def rebind_addresses(operation):
        dispatch = operation["dispatch"]
        addresses = [dispatch[name] for name in ("a_address", "b_address", "d_address")]
        dispatch["argument_bytes"] = argument_hex(operation["format"], addresses)

    def test_complete_four_format_policy_logs_recompute_all_observations(self):
        for fmt, policy in self.examples:
            with self.subTest(fmt=fmt, policy=policy):
                raw = self.raw(fmt, policy)
                result = self.verify(raw, fmt=fmt, policy=policy)
                self.assertEqual(result["operations"], raw[1])
                self.assertEqual(result["summary"], raw[2])
                self.assertEqual(result["raw_log_sha256"], hashlib.sha256(render_log(*raw[1:]).encode()).hexdigest())
                self.assertEqual(result["operation_durations_ns"], [100] * 33)
                self.assertEqual(result["timed_operation_durations_ns"], [100] * 32)
                self.assertEqual(result["accounting"], {"launches": 33, "checked_words": 1056,
                    "timed_operations": 32, "timed_useful_flops": 16384,
                    "input_h2d_bytes": 6336, "poison_h2d_bytes": 4224, "tensor_d2h_bytes": 4224})
                self.assertEqual(len(result["counter_deltas"]), 45)
                self.assertEqual(sum(row["available"] for row in result["counter_deltas"]), 33)
                self.assertFalse(result["performance_acceptance"])
                self.assertFalse(result["phase_acceptance"])

    def test_custom_identity_durations_and_exact_counter_deltas(self):
        durations = [17] + list(range(1, 33))
        raw = raw_records("bf16", "reusable_single_tile", pair_index=0, binding_id="a" * 64,
                          durations_ns=durations, counter_deltas={"cycles": 321, "instructions": 654},
                          contract=self.contract)
        result = self.verify(raw, fmt="bf16", policy="reusable_single_tile", pair_index=0,
            sample_id="warm-simx-bf16-pair0-reusable_single_tile", phase="warmup", binding_id="a" * 64)
        self.assertEqual(result["operation_durations_ns"], durations)
        self.assertEqual(result["timed_operation_durations_ns"], durations[1:])
        values = {row["name"]: row["value"] for row in result["counter_deltas"]}
        self.assertEqual((values["cycles"], values["instructions"]), (321, 654))

    def test_plain_diagnostics_and_recycled_default_addresses_are_valid(self):
        raw = self.raw()
        for operation in raw[1]:
            for name, address in zip(("a_address", "b_address", "d_address"), (0x10000, 0x10100, 0x10200)):
                operation["dispatch"][name] = address
            self.rebind_addresses(operation)
        text = render_log(*raw[1:]).replace("P06_WARM_OPERATION ", "ordinary diagnostic\nP06_WARM_OPERATION ")
        self.verify(raw, text=text.replace("\n", "\r\n"))

    def test_helper_is_deterministic_and_rejects_ambiguous_parameters(self):
        self.assertEqual(synthetic_log(contract=self.contract), render_log(*self.raw()[1:]))
        for change in ({"fmt": "tf32"}, {"policy": "pool"}, {"pair_index": True}, {"pair_index": 6},
                       {"start_ns": 20}, {"durations_ns": True}, {"durations_ns": 1.5},
                       {"durations_ns": [1] * 32}, {"durations_ns": [1] * 32 + [0]},
                       {"counter_deltas": {"unknown": 0}}, {"counter_deltas": {"cycles": True}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                raw_records(contract=self.contract, **change)

    def test_operation_and_summary_fields_are_exact(self):
        for target, keys in (("operation", manifest.OPERATION_KEYS), ("summary", manifest.SUMMARY_KEYS)):
            for key in keys:
                with self.subTest(target=target, missing=key):
                    self.reject(lambda c, o, s, key=key, target=target: (o[0] if target == "operation" else s).pop(key))
            with self.subTest(target=target, extra=True):
                self.reject(lambda c, o, s, target=target: (o[0] if target == "operation" else s).__setitem__("extra", 0))

    def test_nested_field_sets_cannot_hide_missing_or_additional_evidence(self):
        paths = [(1, 0, "dispatch"), (1, 0, "results"), (1, 0, "results", "wait"),
                 (1, 0, "counts_before"), (1, 0, "counts_after"), (2, "counts"),
                 (2, "results"), (2, "results", "close"), (2, "memory"),
                 (2, "memory", "after_batch"), (2, "snapshots"), (2, "snapshots", "after_prime"),
                 (2, "host_intervals_ns"), (2, "host_intervals_ns", "close"), (2, "device_release")]
        for path in paths:
            for extra in (False, True):
                raw = self.raw()
                target = raw
                for part in path:
                    target = target[part]
                if extra:
                    target["extra"] = 0
                else:
                    target.pop(next(iter(target)))
                with self.subTest(path=path, extra=extra), self.assertRaises(ValueError):
                    self.verify(raw)

    def test_identity_fields_are_bound_to_supervised_selection(self):
        values = {"schema_version": True, "contract_id": "other", "qualification_id": "a" * 64,
                  "sample_id": "warm-simx-fp16-pair2-per_operation", "format": "bf16",
                  "policy": "reusable_single_tile", "pair_index": True, "phase": "warmup"}
        for key, value in values.items():
            for target in ("operation", "summary"):
                with self.subTest(key=key, target=target):
                    self.reject(lambda c, o, s, key=key, value=value, target=target:
                        (o[13] if target == "operation" else s).__setitem__(key, value))

    def test_invalid_external_identity_and_contract_arguments_fail(self):
        for changed in ({"fmt": "FP16"}, {"policy": "default"}, {"binding_id": "A" * 64},
                        {"binding_id": "a" * 63}, {"pair_index": True}, {"pair_index": 6},
                        {"sample_id": "warm-simx-fp16-pair0-per_operation"}, {"phase": "warmup"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.verify(self.raw(), **changed)
        contract = deepcopy(self.contract)
        contract["analysis"]["candidate_median_percent_of_reference_max"] = 96
        with self.assertRaises(ValueError):
            self.verify(contract=contract)

    def test_independent_fixture_cannot_be_rewritten_to_match_bad_outputs(self):
        raw = self.raw()
        raw[0]["expected"][0] = "00000000"
        for operation in raw[1]:
            operation["actual_bits"][0] = "00000000"
        with self.assertRaises(ValueError):
            self.verify(raw)
        for key, value in (("id", "fp16-single-k03"), ("m", 7), ("format", "bf16")):
            with self.subTest(key=key):
                self.reject(lambda c, o, s, key=key, value=value: c.__setitem__(key, value))

    def test_every_operation_and_output_word_is_checked_independently(self):
        for index in range(33):
            word = index % 32
            with self.subTest(operation=index, word=word):
                self.reject(lambda c, o, s, index=index, word=word: o[index]["actual_bits"].__setitem__(
                    word, f"{int(o[index]['actual_bits'][word], 16) ^ 1:08x}"))

    def test_output_inventory_and_hex_encoding_are_strict(self):
        for value in ([], ["00000000"] * 31, ["00000000"] * 33, "00000000", None):
            with self.subTest(value=value):
                self.reject(lambda c, o, s, value=value: o[1].__setitem__("actual_bits", value))
        for value in (0, "0x000000", "FFFFFFFF", "0000000g", "000000000", "0000000", None):
            with self.subTest(word=value):
                self.reject(lambda c, o, s, value=value: o[1]["actual_bits"].__setitem__(0, value))

    def test_prime_and_sample_sequence_shape_poison_and_success_are_frozen(self):
        for key, value in (("operation_index", 2), ("role", "prime"), ("case_id", "other"),
                           ("m", 7), ("n", 8), ("k", 3), ("poison", 0xDEADBEEF),
                           ("checked", 31), ("mismatches", 1), ("passed", False)):
            with self.subTest(key=key):
                self.reject(lambda c, o, s, key=key, value=value: o[1].__setitem__(key, value))
        for key in ("operation_index", "m", "checked", "mismatches", "poison"):
            with self.subTest(integer=key):
                self.reject(lambda c, o, s, key=key: o[1].__setitem__(key, True))

    def test_dispatch_counts_results_and_profiling_cannot_be_forged(self):
        for key in ("a_bytes", "b_bytes", "d_bytes", "writes", "launches", "reads", "waits", "timed_out_waits"):
            with self.subTest(key=key):
                self.reject(lambda c, o, s, key=key: o[0]["dispatch"].__setitem__(key, o[0]["dispatch"][key] + 1))
        for key, value in (("profiling_enabled", True), ("profiling_enabled", 0),
                           ("event_results", [0] * 4), ("event_results", [0, 0, 0, 0, 1]),
                           ("event_results", [False] * 5)):
            with self.subTest(key=key, value=value):
                self.reject(lambda c, o, s, key=key, value=value: o[0]["dispatch"].__setitem__(key, value))

    def test_dispatch_wire_fields_are_checked_against_actual_addresses(self):
        for offset in (0, 4, 8, 12, 16, 20, 24, 28, 32, 40, 48):
            def mutate(case, operations, summary, offset=offset):
                wire = bytearray.fromhex(operations[5]["dispatch"]["argument_bytes"])
                wire[offset] ^= 1
                operations[5]["dispatch"]["argument_bytes"] = wire.hex()
            with self.subTest(offset=offset):
                self.reject(mutate)
        for value in ("00" * 55, "00" * 57, "G0" * 56, [0] * 56, None):
            with self.subTest(value=value):
                self.reject(lambda c, o, s, value=value: o[0]["dispatch"].__setitem__("argument_bytes", value))

    def test_aligned_disjoint_uint64_addresses_are_required_even_with_rebound_wire(self):
        for name, address in (("a_address", 1), ("b_address", 0x10040), ("d_address", 0x10100),
                              ("a_address", (1 << 64) - 64)):
            def mutate(case, operations, summary, name=name, address=address):
                operations[0]["dispatch"][name] = address
                self.rebind_addresses(operations[0])
            with self.subTest(name=name, address=address):
                self.reject(mutate)
        self.reject(lambda c, o, s: o[0]["dispatch"].__setitem__("a_address", True))

    def test_resident_addresses_must_remain_fixed_across_all_operations(self):
        def mutate(case, operations, summary):
            for name in ("a_address", "b_address", "d_address"):
                operations[-1]["dispatch"][name] += 0x10000
            self.rebind_addresses(operations[-1])
        self.reject(mutate, policy="reusable_single_tile")

    def test_submit_wait_close_success_and_completeness_are_distinct(self):
        for name in ("submit", "wait", "close"):
            for key in ("validation", "primary", "cleanup"):
                with self.subTest(name=name, key=key):
                    self.reject(lambda c, o, s, name=name, key=key: o[9]["results"][name].__setitem__(key, 1))
            with self.subTest(name=name, complete=True):
                self.reject(lambda c, o, s, name=name: o[9]["results"][name].__setitem__("complete", name == "submit"))
        for name in ("create", "close"):
            with self.subTest(owner=name):
                self.reject(lambda c, o, s, name=name: s["results"][name].__setitem__("complete", False))

    def test_tensor_and_device_lifetimes_must_reconcile_at_each_boundary(self):
        for policy in manifest.POLICIES:
            for target in ("counts_before", "counts_after"):
                for key in manifest.COUNT_KEYS:
                    with self.subTest(policy=policy, target=target, key=key):
                        self.reject(lambda c, o, s, target=target, key=key:
                            o[16][target].__setitem__(key, o[16][target][key] + 1), policy=policy)
            for key in manifest.COUNT_KEYS:
                with self.subTest(policy=policy, final=key):
                    self.reject(lambda c, o, s, key=key: s["counts"].__setitem__(key, s["counts"][key] + 1), policy=policy)

    def test_memory_queries_status_capacity_and_restoration_are_required(self):
        for name in manifest.MEMORY_NAMES:
            for key, value in (("queried", False), ("status", 1), ("used_bytes", True)):
                with self.subTest(name=name, key=key):
                    self.reject(lambda c, o, s, name=name, key=key: s["memory"][name].__setitem__(key, value))
        self.reject(lambda c, o, s: s["memory"]["after_batch"].__setitem__("free_bytes", 0))
        for name in ("after_prime", "after_batch", "before_release"):
            def mutate(case, operations, summary, name=name):
                summary["memory"][name]["free_bytes"] -= 1
                summary["memory"][name]["used_bytes"] += 1
            with self.subTest(name=name):
                self.reject(mutate)
        for value in (0, 1 << 64):
            def mutate(case, operations, summary, value=value):
                for memory in summary["memory"].values():
                    memory.update(free_bytes=value, used_bytes=0)
            with self.subTest(capacity=value):
                self.reject(mutate)

    def test_resident_requested_payload_cannot_exceed_reported_used_memory(self):
        def mutate(case, operations, summary):
            for name in ("after_create", "after_prime", "after_batch"):
                summary["memory"][name].update(used_bytes=575, free_bytes=(1 << 20) - 575)
        self.reject(mutate, policy="reusable_single_tile")

    def test_operation_intervals_are_positive_unsigned_and_nonoverlapping(self):
        for key, value in (("begin_ns", True), ("begin_ns", -1), ("end_ns", 1 << 64),
                           ("end_ns", 1.0), ("end_ns", None)):
            with self.subTest(key=key, value=value):
                self.reject(lambda c, o, s, key=key, value=value: o[1].__setitem__(key, value))
        self.reject(lambda c, o, s: o[1].__setitem__("end_ns", o[1]["begin_ns"]))
        self.reject(lambda c, o, s: o[1].__setitem__("end_ns", o[1]["begin_ns"] - 1))
        self.reject(lambda c, o, s: o[2].__setitem__("begin_ns", o[1]["end_ns"] - 1))

    def test_snapshots_cannot_overlap_creation_prime_batch_or_teardown(self):
        changes = [
            lambda c, o, s: s["host_intervals_ns"]["create"].__setitem__("begin_ns", 21),
            lambda c, o, s: s["host_intervals_ns"]["create"].__setitem__("end_ns", 29),
            lambda c, o, s: s["host_intervals_ns"]["create"].__setitem__("end_ns", o[0]["begin_ns"] + 1),
            lambda c, o, s: s["snapshots"]["after_prime"].__setitem__("query_begin_ns", o[0]["end_ns"] - 1),
            lambda c, o, s: s["snapshots"]["after_prime"].__setitem__("query_end_ns", o[1]["begin_ns"] + 1),
            lambda c, o, s: s["snapshots"]["after_batch"].__setitem__("query_begin_ns", o[-1]["end_ns"] - 1),
            lambda c, o, s: s["host_intervals_ns"]["close"].__setitem__("begin_ns", s["snapshots"]["after_batch"]["query_end_ns"] - 1),
            lambda c, o, s: s["snapshots"]["before_release"].__setitem__("query_begin_ns", s["host_intervals_ns"]["close"]["begin_ns"] - 1),
            lambda c, o, s: s["host_intervals_ns"]["close"].__setitem__("end_ns", s["snapshots"]["before_release"]["query_end_ns"] - 1),
        ]
        for index, change in enumerate(changes):
            with self.subTest(boundary=index):
                self.reject(change)

    def test_snapshot_inventory_types_and_query_order_are_exact(self):
        values = {"schema_version": True, "sample_id": "other", "context_id": 2,
                  "device_index": 1, "compiled_memory_block_bytes": 128,
                  "query_begin_ns": True, "query_end_ns": -1}
        for name in manifest.SNAPSHOT_NAMES:
            for key, value in values.items():
                with self.subTest(name=name, key=key):
                    self.reject(lambda c, o, s, name=name, key=key, value=value: s["snapshots"][name].__setitem__(key, value))
            with self.subTest(name=name, reversed=True):
                self.reject(lambda c, o, s, name=name: s["snapshots"][name].__setitem__(
                    "query_end_ns", s["snapshots"][name]["query_begin_ns"] - 1))

    def test_capability_values_status_and_order_are_independently_checked(self):
        for index in range(13):
            with self.subTest(capability=index):
                self.reject(lambda c, o, s, index=index: s["snapshots"]["after_batch"]["capabilities"][index].__setitem__(
                    "value", s["snapshots"]["after_batch"]["capabilities"][index]["value"] + 1))
        for change in (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                       lambda rows: rows.append(deepcopy(rows[0])),
                       lambda rows: rows[0].__setitem__("status", 1),
                       lambda rows: rows[0].__setitem__("id", True)):
            self.reject(lambda c, o, s, change=change: change(s["snapshots"]["after_open"]["capabilities"]))

    def test_every_counter_retains_frozen_metadata_and_native_status(self):
        for index in range(45):
            with self.subTest(counter=index):
                self.reject(lambda c, o, s, index=index: s["snapshots"]["after_batch"]["counters"][index].__setitem__("csr", 0))
        for key, value in (("name", "other"), ("mpm_class", 99), ("core_id", 1),
                           ("scope", "global"), ("unit", "nanoseconds"), ("required_isa", True),
                           ("enabled", 1), ("status", False), ("status", 1), ("value", True)):
            with self.subTest(key=key):
                self.reject(lambda c, o, s, key=key, value=value: s["snapshots"]["after_prime"]["counters"][0].__setitem__(key, value))

    def test_disabled_counters_are_unavailable_and_inventory_is_complete(self):
        disabled = [index for index, row in enumerate(self.raw()[2]["snapshots"]["after_batch"]["counters"]) if not row["enabled"]]
        self.assertEqual(len(disabled), 12)
        for index in disabled:
            for key, value in (("enabled", True), ("status", 0), ("value", 0)):
                with self.subTest(counter=index, key=key):
                    self.reject(lambda c, o, s, index=index, key=key, value=value:
                        s["snapshots"]["after_batch"]["counters"][index].__setitem__(key, value))
        for change in (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                       lambda rows: rows.append(deepcopy(rows[0])),
                       lambda rows: rows.__setitem__(1, deepcopy(rows[0]))):
            self.reject(lambda c, o, s, change=change: change(s["snapshots"]["before_release"]["counters"]))

    def test_counter_reset_wrap_and_zero_required_batch_delta_are_rejected(self):
        for name in ("after_prime", "after_batch", "before_release"):
            with self.subTest(snapshot=name):
                self.reject(lambda c, o, s, name=name: s["snapshots"][name]["counters"][1].__setitem__("value", 0))
        self.reject(lambda c, o, s: s["snapshots"]["after_prime"]["counters"][0].__setitem__("value", (1 << 64) - 1))
        for index in (0, 1):
            with self.subTest(required_counter=index):
                self.reject(lambda c, o, s, index=index: s["snapshots"]["after_batch"]["counters"][index].__setitem__(
                    "value", s["snapshots"]["after_prime"]["counters"][index]["value"]))

    def test_zero_optional_deltas_and_uint64_counter_extremes_remain_exact(self):
        raw = self.raw()
        for index, row in enumerate(raw[2]["snapshots"]["after_open"]["counters"]):
            if not row["enabled"]:
                continue
            for step, name in enumerate(manifest.SNAPSHOT_NAMES):
                increment = step if row["name"] in ("cycles", "instructions") else 0
                raw[2]["snapshots"][name]["counters"][index]["value"] = (1 << 64) - 4 + increment
        actual = self.verify(raw)
        for row in actual["counter_deltas"]:
            self.assertEqual(row["value"], (1 if row["name"] in ("cycles", "instructions") else 0)
                             if row["available"] else None)

    def test_summary_and_actual_release_are_not_replaced_by_pass_markers(self):
        for key, value in (("operations", 32), ("checked", 1055), ("mismatches", 1), ("passed", False)):
            with self.subTest(key=key):
                self.reject(lambda c, o, s, key=key, value=value: s.__setitem__(key, value))
        for key, value in (("schema_version", True), ("sample_id", "other"), ("context_id", 2), ("status", 1)):
            with self.subTest(release=key):
                self.reject(lambda c, o, s, key=key, value=value: s["device_release"].__setitem__(key, value))

    def test_missing_duplicate_reordered_or_misrouted_records_fail(self):
        text = render_log(*self.raw()[1:])
        lines = text.splitlines()
        for index in (1, 2, 17, 33, 34):
            for changed in (lines[:index] + lines[index + 1:], lines[:index] + [lines[index]] + lines[index:]):
                with self.subTest(index=index, size=len(changed)), self.assertRaises(ValueError):
                    self.verify(text="\n".join(changed) + "\n")
        changed = list(lines)
        changed[1], changed[2] = changed[2], changed[1]
        with self.assertRaises(ValueError):
            self.verify(text="\n".join(changed) + "\n")
        for prefix in ("P06_WARM_UNKNOWN {}\n", "P03_RESULT {}\n", "P04_RESULT {}\n",
                       "P05_RESULT {}\n", "prefix P06_WARM_OPERATION {}\n"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                self.verify(text=prefix + text)
        for changed in (text.replace("P06_WARM_OPERATION", "p06_warm_operation", 1),
                        text.replace("P06_WARM_OPERATION ", "P06_WARM_OPERATION\t", 1),
                        text.replace("P06_WARM_SUMMARY ", "P06_WARM_SUMMARY\n", 1)):
            with self.assertRaises(ValueError):
                self.verify(text=changed)

    def test_failure_tokens_controls_ambiguous_unicode_and_trailing_output_fail(self):
        text = render_log(*self.raw()[1:])
        for prefix in ("FAILED\n", "fail\n", "ERROR\n", "fatal\n", "ABORTED\n", "MISMATCH\n",
                       "Assertion synthetic failed\n", "Segmentation fault\n", "core dumped\n",
                       "runtime error: unsigned overflow\n", "P06_WARM_FAILURE {}\n",
                       "\x00", "\x1b", "\x7f", "\u0085", "\u2028", "\u2029", "\u00a0", "\ud800"):
            with self.subTest(prefix=repr(prefix)), self.assertRaises(ValueError):
                self.verify(text=prefix + text)
        for suffix in ("diagnostic\n", "PASSED!\n", "\n"):
            with self.subTest(suffix=repr(suffix)), self.assertRaises(ValueError):
                self.verify(text=text + suffix)
        for replacement in ("PASSED", " PASSED!", "passed!", "PASSED! PASSED!"):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.verify(text=text.replace("PASSED!", replacement))

    def test_json_types_duplicate_keys_depth_encoding_and_byte_bounds_fail_closed(self):
        text = render_log(*self.raw()[1:])
        for value in ("-0", "-1", "1.0", "1e0", "NaN", "Infinity", "true", "null", '"1000"',
                      str(1 << 64), "1" * 21, "[" * 17 + "0" + "]" * 17):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.verify(text=text.replace('"begin_ns":1000', '"begin_ns":' + value, 1))
        for key in ("schema_version", "operation_index", "dispatch", "status", "value", "counters"):
            with self.subTest(duplicate=key), self.assertRaises(ValueError):
                self.verify(text=text.replace('"' + key + '":', '"' + key + '":0,"' + key + '":', 1))
        for body in ("[]", "null", "{} trailing", '{"x":', '{"x":"\\ud800"}'):
            lines = text.splitlines()
            lines[1] = "P06_WARM_OPERATION " + body
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.verify(text="\n".join(lines) + "\n")
        with patch.object(records, "MAX_OUTPUT_BYTES", len(text.encode()) - 1), self.assertRaises(ValueError):
            self.verify(text=text)
        with patch.object(records, "MAX_RECORD_BYTES", 100), self.assertRaises(ValueError):
            self.verify(text=text)
        with self.assertRaises(ValueError):
            self.verify(text=text.encode())


if __name__ == "__main__":
    unittest.main()
