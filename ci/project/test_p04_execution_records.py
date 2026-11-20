# SPDX-License-Identifier: Apache-2.0
"""Synthetic record corruption checks; these fixtures never execute a GPU."""

import copy
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import p04_execution_records as records
from p04_fixture_adapter import load_cases


ROOT = Path(__file__).resolve().parents[2]
BINDING = "0123456789abcdef" * 4
REVISION = "1234567890abcdef" * 2 + "12345678"
FIXTURE_SHA = hashlib.sha256((ROOT / "ci/project/fixtures/p04_tiny_mlp_v1.json").read_bytes()).hexdigest()


def packed(words):
    return b"".join(int(word, 16).to_bytes(4, "little") for word in words).hex()


def execution(complete=True):
    return {"validation": 0, "primary": 0, "cleanup": 0, "complete": complete}


def wire(dispatch):
    return struct.pack("<8I3Q", 1, 56, 1 if dispatch["input_dtype"] == "fp16" else 2, 0,
                       dispatch["m"], dispatch["n"], dispatch["k"], 0,
                       dispatch["a_address"], dispatch["b_address"], dispatch["d_address"]).hex()


def result(case, iteration=0, backend="simx"):
    poison = 0x7FC0DEAD if iteration == 0 else 0xDEADBEEF
    epoch = iteration * 10000
    trace = {
        "case_id": case["id"], "input_dtype": case["format"], "poison": poison,
        "native": [], "hidden_valid": True, "bridge_attempted": True,
        "bridge_valid": True, "bridge_compared": True, "assembled": True,
        "logits_valid": True, "logits_compared": True, "owner_closed": True,
        "bridge_status": 0, "hidden_words": list(case["hidden_words"]),
        "bridge_bytes": packed(case["bridge_words"]), "bridge_words": list(case["bridge_words"]),
        "output_words": list(case["output_words"]), "bridge_checked_words": 64,
        "bridge_mismatches": 0, "output_checked_words": 64, "output_mismatches": 0,
        "create_begin_ns": epoch + 100, "create_end_ns": epoch + 200, "advance_ns": 4000,
        "bridge_ns": 5, "bridge_compare_ns": 5, "assembly_ns": 5,
        "output_compare_ns": 5, "close_ns": 10,
        "resources": {"before_valid": True, "after_valid": True,
                      "before_status": 0, "after_status": 0,
                      "free_before": 0x100000, "used_before": 0x20000,
                      "free_after": 0x100000, "used_after": 0x20000},
        "owner_cleanup": execution(),
        "result": {"status": "success", "execution": execution(), "terminal": True},
    }
    for index, (name, shape, rows) in enumerate((
            ("hidden_matmul", (16, 8, 16), (0, 16)),
            ("output_rows_0_7", (8, 4, 8), (0, 8)),
            ("output_rows_8_15", (8, 4, 8), (8, 16)))):
        m, n, k = shape
        begin = epoch + 1000 + index * 1000
        a = packed(case["input_words"]) if index == 0 else trace["bridge_bytes"][(index - 1) * 256:index * 256]
        b = packed(case["w1_words"] if index == 0 else case["w2_words"])
        output = case["hidden_words"] if index == 0 else case["output_words"][(index - 1) * 32:index * 32]
        dispatch = {
            "qualification_id": BINDING, "input_dtype": case["format"], "m": m, "n": n, "k": k,
            "poison": poison, "a_address": 0x1000, "b_address": 0x2000, "d_address": 0x3000,
            "a_bytes": m * k * 2, "b_bytes": k * n * 2, "d_bytes": m * n * 4,
            "writes_enqueued": 3, "launches_enqueued": 1, "reads_enqueued": 1,
            "wait_calls": 1, "timed_out_waits": 0, "event_results": [0] * 5,
            "profiling_enabled": True, "event_profile_results": [0] * 5,
            "event_profile_queried": [True] * 5,
            "event_profiles": [{"queued_ns": begin + event, "submit_ns": begin + 20 + event * 10,
                                "start_ns": begin + 22 + event * 10, "end_ns": begin + 25 + event * 10}
                               for event in range(5)],
        }
        dispatch["argument_bytes"] = wire(dispatch)
        trace["native"].append({
            "operation_id": name, "sequence": index, "row_begin": rows[0], "row_end": rows[1],
            "submitted": True, "waited": True, "trace_valid": True, "output_valid": True,
            "compared": True, "closed": True, "submission": execution(False),
            "completion": execution(), "cleanup": execution(), "dispatch": dispatch,
            "a_size": m * k * 2, "b_size": k * n * 2, "output_count": m * n,
            "a_bytes": a, "b_bytes": b, "output_words": list(output),
            "checked_words": m * n, "mismatches": 0, "submit_begin_ns": begin,
            "submit_end_ns": begin + 10, "wait_ns": 100, "compare_ns": 5, "close_ns": 5,
        })
    return {
        "schema_version": 1, "model_id": "p04-tiny-mlp-v1", "fixture_id": "p04-tiny-mlp-fixture-v1",
        "fixture_sha256": FIXTURE_SHA, "source_revision": REVISION, "backend": backend,
        "iteration": iteration, "qualification_id": BINDING, "clock": "std::chrono::steady_clock",
        "timing_scope": "host_runtime_observations", "trace": trace,
    }


def output(rows):
    return "native runtime diagnostic\n" + "".join(
        "P04_RESULT " + json.dumps(row, separators=(",", ":")) + "\n" for row in rows) + "PASSED!\n"


def at(value, path):
    for part in path:
        value = value[part]
    return value


def leaves(value, path=()):
    if type(value) is dict:
        for key, child in value.items():
            yield from leaves(child, path + (key,))
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from leaves(child, path + (index,))
    else:
        yield path, value


def objects(value, path=()):
    if type(value) is dict:
        yield path
        for key, child in value.items():
            yield from objects(child, path + (key,))
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from objects(child, path + (index,))


class ModelRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()
        cls.case = next(case for case in cls.cases if case["id"] == "fp16-seeded_dense")

    def verify(self, text, *, case=None, iterations=1, binding_id=BINDING,
               backend="simx", source_revision=REVISION, fixture_sha256=FIXTURE_SHA):
        return records.verify_output(text, self.case if case is None else case, iterations, binding_id,
                                     backend=backend, source_revision=source_revision,
                                     fixture_sha256=fixture_sha256)

    def reject(self, text, **kwargs):
        with self.assertRaises(ValueError):
            self.verify(text, **kwargs)

    def test_every_frozen_case_in_both_backends_and_two_poisons(self):
        for case in self.cases:
            for backend in ("simx", "rtlsim"):
                rows = [result(case, iteration, backend) for iteration in range(2)]
                with self.subTest(case=case["id"], backend=backend):
                    self.assertEqual(self.verify(output(rows), case=case, backend=backend, iterations=2), rows)
        dispatch = result(self.case)["trace"]["native"][0]["dispatch"]
        self.assertEqual(dispatch["argument_bytes"],
            "0100000038000000010000000000000010000000080000001000000000000000"
            "001000000000000000200000000000000030000000000000")

    def test_observed_zero_duration_profiles_and_successful_timeout_resume_are_valid(self):
        row = result(self.case)
        trace = row["trace"]
        trace["create_begin_ns"] = trace["create_end_ns"] = 0
        for stage in trace["native"]:
            stage["submit_begin_ns"] = stage["submit_end_ns"] = 0
            stage["dispatch"]["wait_calls"] = 2
            stage["dispatch"]["timed_out_waits"] = 1
            for profile in stage["dispatch"]["event_profiles"]:
                profile.update({key: 0 for key in profile})
        self.assertEqual(self.verify(output([row])), [row])

    def test_all_actual_tensor_boundaries_are_exact_raw_words(self):
        for path in (("trace", "hidden_words"), ("trace", "bridge_words"), ("trace", "output_words"),
                     *(("trace", "native", index, "output_words") for index in range(3))):
            for index in (0, len(at(result(self.case), path)) - 1):
                row = result(self.case)
                words = at(row, path)
                words[index] = f"{int(words[index], 16) ^ 1:08x}"
                with self.subTest(path=path, index=index):
                    self.reject(output([row]))
        row = result(self.case)
        self.assertEqual(row["trace"]["hidden_words"][0], "bf800000")
        row["trace"]["hidden_words"][0] = "c0000000"
        row["trace"]["native"][0]["output_words"][0] = "c0000000"
        self.reject(output([row]))
        row = result(self.case)
        row["trace"]["hidden_words"][0] = "BF800000"
        self.reject(output([row]))
        zero = next(case for case in self.cases if case["id"] == "fp16-zero")
        row = result(zero)
        row["trace"]["hidden_words"][0] = "80000000"
        row["trace"]["native"][0]["output_words"][0] = "80000000"
        self.reject(output([row]), case=zero)

    def test_actual_input_bytes_cannot_be_replaced_or_row_blocks_swapped(self):
        for index in range(3):
            for field in ("a_bytes", "b_bytes"):
                row = result(self.case)
                stage = row["trace"]["native"][index]
                raw = bytearray.fromhex(stage[field])
                raw[-1] ^= 1
                stage[field] = raw.hex()
                with self.subTest(index=index, field=field):
                    self.reject(output([row]))
        split = next(case for case in self.cases if case["id"] == "bf16-split_boundary")
        row = result(split)
        left, right = row["trace"]["native"][1:]
        left["output_words"], right["output_words"] = right["output_words"], left["output_words"]
        row["trace"]["output_words"] = left["output_words"] + right["output_words"]
        self.reject(output([row]), case=split)
        row = result(split)
        row["trace"]["bridge_bytes"] = row["trace"]["bridge_bytes"][256:] + row["trace"]["bridge_bytes"][:256]
        self.reject(output([row]), case=split)

    def test_changed_identity_or_untrusted_invocation_is_rejected(self):
        for key in ("model_id", "fixture_id", "fixture_sha256", "source_revision", "backend",
                    "qualification_id", "clock", "timing_scope"):
            row = result(self.case)
            row[key] += "x"
            with self.subTest(key=key):
                self.reject(output([row]))
        for key, value in (("case_id", "another"), ("input_dtype", "bf16")):
            row = result(self.case)
            row["trace"][key] = value
            self.reject(output([row]))
        for name, values in (("binding_id", ("", BINDING.upper(), "g" * 64, True)),
                             ("source_revision", ("", "1" * 39, "G" * 40, 1)),
                             ("fixture_sha256", ("", "1" * 63, None)),
                             ("backend", ("xrt", "SIMX", False)),
                             ("iterations", (0, 3, True, 1.0))):
            for value in values:
                with self.subTest(argument=name, value=value):
                    self.reject(output([result(self.case)]), **{name: value})

    def test_native_graph_shapes_inventory_and_poison_are_checked(self):
        for index in range(3):
            for field, value in (("sequence", 3), ("row_begin", 1), ("row_end", 4),
                                 ("a_size", 0), ("b_size", 0), ("output_count", 0),
                                 ("checked_words", 0), ("mismatches", 1)):
                row = result(self.case)
                row["trace"]["native"][index][field] = value
                with self.subTest(index=index, field=field):
                    self.reject(output([row]))
            for field, value in (("m", 1), ("n", 1), ("k", 1), ("a_bytes", 0), ("b_bytes", 0),
                                 ("d_bytes", 0), ("writes_enqueued", 2), ("launches_enqueued", 0),
                                 ("reads_enqueued", 0), ("wait_calls", 0), ("timed_out_waits", 1),
                                 ("poison", 0xDEADBEEF), ("qualification_id", "f" * 64),
                                 ("input_dtype", "bf16")):
                row = result(self.case)
                row["trace"]["native"][index]["dispatch"][field] = value
                with self.subTest(index=index, dispatch=field):
                    self.reject(output([row]))
        for order in ([], [0, 1], [0, 1, 1], [0, 2, 1], [0, 1, 2, 2]):
            row = result(self.case)
            row["trace"]["native"] = [row["trace"]["native"][index] for index in order]
            self.reject(output([row]))
        rows = [result(self.case, 0), result(self.case, 1)]
        rows[1]["trace"]["poison"] = rows[0]["trace"]["poison"]
        self.reject(output(rows), iterations=2)

    def test_wire_bytes_and_allocation_ranges_are_independently_reconstructed(self):
        for stage_index in range(3):
            for index in (0, 4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 55):
                row = result(self.case)
                dispatch = row["trace"]["native"][stage_index]["dispatch"]
                raw = bytearray.fromhex(dispatch["argument_bytes"])
                raw[index] ^= 1
                dispatch["argument_bytes"] = raw.hex()
                self.reject(output([row]))
            for field, address in (("a_address", 0x1001), ("b_address", 0x1000),
                                   ("d_address", 0x2004), ("d_address", (1 << 64) - 4)):
                row = result(self.case)
                dispatch = row["trace"]["native"][stage_index]["dispatch"]
                dispatch[field] = address
                dispatch["argument_bytes"] = wire(dispatch)
                self.reject(output([row]))
        row = result(self.case)
        dispatch = row["trace"]["native"][0]["dispatch"]
        dispatch["a_address"] = 0x1ABC
        dispatch["argument_bytes"] = wire(dispatch).upper()
        self.reject(output([row]))
        row = result(self.case)
        dispatch = row["trace"]["native"][0]["dispatch"]
        dispatch["d_address"] = (1 << 64) - dispatch["d_bytes"]
        dispatch["argument_bytes"] = wire(dispatch)
        self.assertEqual(self.verify(output([row])), [row])

    def test_every_lifecycle_status_completion_and_resource_observation_is_required(self):
        paths = [("trace", "owner_cleanup"), ("trace", "result", "execution")]
        paths += [("trace", "native", index, role) for index in range(3)
                  for role in ("submission", "completion", "cleanup")]
        for path in paths:
            for key in ("validation", "primary", "cleanup"):
                row = result(self.case)
                at(row, path)[key] = 1
                self.reject(output([row]))
            if path[-1] != "submission":
                row = result(self.case)
                at(row, path)["complete"] = False
                self.reject(output([row]))
        for field, value in (("before_status", 1), ("after_status", 1),
                             ("used_after", 0x20001), ("free_after", 0xFFFFF)):
            row = result(self.case)
            row["trace"]["resources"][field] = value
            self.reject(output([row]))
        for status in ("in_progress", "runtime_error", "hidden_mismatch", "closed"):
            row = result(self.case)
            row["trace"]["result"]["status"] = status
            self.reject(output([row]))

    def test_every_success_flag_requires_an_actual_boolean_observation(self):
        original = result(self.case)
        for path, value in leaves(original):
            if type(value) is bool:
                replacements = (0, 1, "true", None) + ((False,) if value is True else ())
                for replacement in replacements:
                    row = copy.deepcopy(original)
                    at(row, path[:-1])[path[-1]] = replacement
                    with self.subTest(path=path, replacement=replacement):
                        self.reject(output([row]))

    def test_integer_measurements_reject_coercible_negative_and_out_of_range_values(self):
        original = result(self.case)
        for path, value in leaves(original):
            if type(value) is int:
                for replacement in (True, False, 0.0, "0", -1, 1 << 64):
                    row = copy.deepcopy(original)
                    at(row, path[:-1])[path[-1]] = replacement
                    with self.subTest(path=path, replacement=replacement):
                        self.reject(output([row]))

    def test_each_event_profile_and_dependency_chronology_is_observed(self):
        for stage_index in range(3):
            for event in range(5):
                for field, value in (("event_profile_queried", False), ("event_profile_results", 1),
                                     ("event_results", 1)):
                    row = result(self.case)
                    row["trace"]["native"][stage_index]["dispatch"][field][event] = value
                    self.reject(output([row]))
                row = result(self.case)
                profile = row["trace"]["native"][stage_index]["dispatch"]["event_profiles"][event]
                profile["start_ns"] = profile["end_ns"] + 1
                self.reject(output([row]))
        row = result(self.case)
        profiles = row["trace"]["native"][0]["dispatch"]["event_profiles"]
        profiles[1]["submit_ns"] = profiles[0]["end_ns"] - 1
        self.reject(output([row]))
        row = result(self.case)
        stage = row["trace"]["native"][0]
        stage["dispatch"]["event_profiles"][0]["queued_ns"] = stage["submit_end_ns"] + 1
        self.reject(output([row]))
        row = result(self.case)
        row["trace"]["native"][1]["submit_begin_ns"] = 1000
        self.reject(output([row]))
        row = result(self.case)
        row["trace"]["create_end_ns"] = 1100
        self.reject(output([row]))
        rows = [result(self.case, 0), result(self.case, 1)]
        rows[1]["trace"]["create_begin_ns"] = 100
        self.reject(output(rows), iterations=2)

    def test_missing_unknown_duplicate_fields_and_wrong_array_extents_fail(self):
        original = result(self.case)
        for path in objects(original):
            for mode in ("missing", "extra"):
                row = copy.deepcopy(original)
                target = at(row, path)
                if mode == "missing":
                    del target[next(iter(target))]
                else:
                    target["unexpected"] = 0
                with self.subTest(path=path, mode=mode):
                    self.reject(output([row]))
        for field in ("schema_version", "bridge_status", "queued_ns", "complete", "used_before"):
            text = output([original]).replace('"' + field + '":', '"' + field + '":0,"' + field + '":', 1)
            self.reject(text)
        for field in ("event_profiles", "event_results", "event_profile_results", "event_profile_queried"):
            for value in ([], [0] * 4, [0] * 6, {}, None):
                row = result(self.case)
                row["trace"]["native"][0]["dispatch"][field] = value
                self.reject(output([row]))
        for path in (("trace", "hidden_words"), ("trace", "bridge_words"), ("trace", "output_words"),
                     ("trace", "native", 0, "output_words")):
            for value in ([], {}, None, ["00000000"], [0] * len(at(original, path))):
                row = result(self.case)
                at(row, path[:-1])[path[-1]] = value
                self.reject(output([row]))
        for path in (("trace", "bridge_bytes"), ("trace", "native", 0, "a_bytes"),
                     ("trace", "native", 0, "dispatch", "argument_bytes")):
            for value in ("", "gg", None, at(original, path).upper(), at(original, path) + "00"):
                if value == at(original, path):
                    continue
                row = result(self.case)
                at(row, path[:-1])[path[-1]] = value
                self.reject(output([row]))

    def test_log_framing_failures_and_missing_extra_reordered_repetitions_fail(self):
        for order in ([], [0], [1], [0, 0], [1, 0], [0, 2], [0, 1, 2]):
            self.reject(output([result(self.case, index) for index in order]), iterations=2)
        valid = output([result(self.case)])
        for changed in (valid.replace("PASSED!", ""), valid + "PASSED!\n", valid + "trailing\n",
                        valid + "\n", valid.replace("P04_RESULT ", " P04_RESULT "),
                        valid.replace("P04_RESULT ", "P04_RESULT:"), valid + "ERROR\n",
                        "p04_result {}\n" + valid, "\x85" + valid,
                        "P04_FAILURE {}\n" + valid, "runtime error: UB\n" + valid,
                        "FAIL\n" + valid, "\x00" + valid, "\x1b" + valid, "\x7f" + valid):
            self.reject(changed)
        for number in ("NaN", "Infinity", "-Infinity", "1e100", "1.0"):
            self.reject(valid.replace('"bridge_status":0', '"bridge_status":' + number, 1))
        self.reject("P04_RESULT " + "[" * 2000 + "0" + "]" * 2000 + "\nPASSED!\n")
        self.reject(None)
        self.reject("\ud800" + valid)

    def test_log_and_individual_record_byte_bounds_are_enforced_before_parsing(self):
        valid = output([result(self.case)])
        size = len(valid.encode())
        with patch.object(records, "MAX_LOG_BYTES", size):
            self.assertEqual(len(self.verify(valid)), 1)
            self.reject(valid + " ")
            self.reject("é" + valid[:-1])
        payload = valid.splitlines()[1][len("P04_RESULT "):]
        with patch.object(records, "MAX_RECORD_BYTES", len(payload.encode())):
            self.assertEqual(len(self.verify(valid)), 1)
            self.reject(valid.replace("P04_RESULT ", "P04_RESULT  ", 1))
