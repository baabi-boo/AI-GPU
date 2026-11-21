# SPDX-License-Identifier: Apache-2.0
"""Synthetic record corruption checks; accepted parser fixtures prove no execution."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import p02_matrix as matrix
import p03_execution_records as matmul_records
import p04_execution_records as model_records
import p05_execution_records as records
from p05_qualification_test_fixture import MODEL_INDEX, P02, raw_log, synthetic


def change_word(words, index=0):
    words[index] = f"{int(words[index], 16) ^ 1:08x}"


def wire(trace):
    return struct.pack("<8I3Q", 1, 56, 1 if trace["input_dtype"] == "fp16" else 2, 0,
                       trace["m"], trace["n"], trace["k"], 0,
                       trace["a_address"], trace["b_address"], trace["d_address"]).hex()


class SelectionTests(unittest.TestCase):
    def test_exact_frozen_cases_shapes_and_poisons_in_both_formats(self):
        self.assertEqual(records.POISONS, (0x7FC0DEAD, 0xDEADBEEF))
        self.assertEqual(len(P02), 88)
        for fmt in ("fp16", "bf16"):
            selected = records.select_matmul_cases(P02, fmt)
            self.assertEqual([case["id"] for case in selected], [fmt + "-" + family for family in (
                "single-dense_boundaries", "numerical-cross_tile_rounding_positive", "multi-dense_boundaries")])
            self.assertEqual([(case["m"], case["n"], case["k"]) for case in selected],
                             [(8, 4, 8), (8, 4, 16), (16, 8, 16)])
            self.assertEqual([case["id"] for case in records.select_model_cases(list(MODEL_INDEX.values()), fmt)],
                             [fmt + "-" + family for family in (
                                 "seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")])

    def test_matmul_inventory_corruption_is_rejected(self):
        for label, mutate in (
                ("missing", lambda cases: cases.pop()),
                ("extra", lambda cases: cases.append(copy.deepcopy(cases[0]))),
                ("duplicate", lambda cases: cases[1].update(id=cases[0]["id"])),
                ("wrong format", lambda cases: cases[0].update(format="bf16")),
                ("missing selected", lambda cases: cases[0].update(id="unselected")),
                ("wrong shape", lambda cases: cases[0].update(k=16))):
            cases = copy.deepcopy(P02)
            # The selected first layout case is not necessarily first in the fixture inventory.
            if label in ("missing selected", "wrong shape"):
                index = next(i for i, case in enumerate(cases) if case["id"] == "fp16-single-dense_boundaries")
                cases[0], cases[index] = cases[index], cases[0]
            mutate(cases)
            with self.subTest(label=label), self.assertRaises(ValueError):
                records.select_matmul_cases(cases, "fp16")
        for fmt in ("fp32", "", None):
            with self.subTest(format=fmt), self.assertRaises(ValueError):
                records.select_matmul_cases(P02, fmt)

    def test_model_inventory_corruption_is_rejected(self):
        for label, mutate in (("missing", lambda cases: cases.pop()),
                              ("extra", lambda cases: cases.append(cases[0])),
                              ("reorder", lambda cases: cases.reverse()),
                              ("format", lambda cases: cases[0].update(format="bf16")),
                              ("id", lambda cases: cases[0].update(id="fp16-replacement"))):
            cases = copy.deepcopy(list(MODEL_INDEX.values()))
            mutate(cases)
            with self.subTest(label=label), self.assertRaises(ValueError):
                records.select_model_cases(cases, "fp16")

    def test_p03_full_matrix_gate_still_rejects_this_comparison_slice(self):
        args = argparse.Namespace(backend=["simx"], format=["fp16"], case=None, iterations=2, development=False)
        with self.assertRaisesRegex(ValueError, "partial matrices"):
            matrix.select_cases(P02, args)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-record-host-mock-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.value, self.request, self.native = synthetic(self.root)

    def verify(self, value=None, *, raw=None, native=None):
        value = self.value if value is None else value
        return records.verify_observations(value, self.request,
            raw_log=raw_log(value) if raw is None else raw, **(self.native if native is None else native))

    def reject(self, value, *, message=None, raw=None, native=None):
        # Matching JSON and raw rows must still pass all semantic checks.
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        value = records.decode_json(payload)
        context = self.assertRaisesRegex(ValueError, message) if message else self.assertRaises(ValueError)
        with context:
            self.verify(value, raw=raw, native=native)

    def test_two_mock_formats_have_exact_counts_and_word_totals(self):
        for fmt in ("fp16", "bf16"):
            value, request, native = synthetic(self.root / fmt, fmt)
            result = records.verify_observations(value, request, raw_log=raw_log(value), **native)
            self.assertEqual(result, {"counts": {"matmul_runs": 6, "model_runs": 10,
                "matmul_launches": 6, "model_launches": 30, "total_launches": 36},
                "matmul_words": 384, "model_hidden_words": 1280, "model_bridge_words": 640,
                "model_output_words": 640, "event_profile_pairs": 180})
            self.assertFalse(value["acceptance_claimed"])
            self.assertNotEqual(native["native_matmuls"][request["matmul_cases"][0]["id"]][0]["qualification_id"],
                                request["binding"]["qualification_id"])

    def test_actual_records_reach_unchanged_p03_and_p04_validators(self):
        with patch.object(records.matmul_records, "verify_output", wraps=matmul_records.verify_output) as matmul, \
             patch.object(records.model_records, "verify_output", wraps=model_records.verify_output) as model:
            self.verify()
        self.assertEqual(matmul.call_count, 3)
        self.assertEqual(model.call_count, 5)
        for index, call in enumerate(model.call_args_list):
            wrapped, case, iterations, binding_id = call.args
            payloads = [json.loads(line[len("P04_RESULT "):]) for line in wrapped.splitlines()
                        if line.startswith("P04_RESULT ")]
            self.assertEqual(payloads, [row["record"] for row in self.value["models"][index * 2:index * 2 + 2]])
            self.assertEqual(case["id"], self.request["model_cases"][index])
            self.assertEqual((iterations, binding_id), (2, self.request["binding"]["qualification_id"]))
            self.assertEqual(call.kwargs["backend"], "simx")
            self.assertEqual(call.kwargs["source_revision"], self.request["binding"]["source_revision"])

    def test_top_level_schema_labels_and_derived_counts_are_strict(self):
        for key, replacement in (("schema_version", True), ("schema_version", 2),
                                  ("contract_id", "foreign"), ("scope", "physical-fpga"),
                                  ("outcome", "fail"), ("acceptance_claimed", True)):
            value = copy.deepcopy(self.value)
            value[key] = replacement
            with self.subTest(field=key):
                self.reject(value)
        for key in self.value["counts"]:
            for replacement in (True, 0, self.value["counts"][key] + 1):
                value = copy.deepcopy(self.value)
                value["counts"][key] = replacement
                with self.subTest(count=key, replacement=replacement):
                    self.reject(value, message="counts")
        value = copy.deepcopy(self.value)
        value["unexpected"] = 1
        self.reject(value, message="fields")
        value = copy.deepcopy(self.value)
        value["counts"]["unexpected"] = 0
        self.reject(value, message="counts")

    def test_matmul_membership_iteration_and_two_distinct_poisons(self):
        for label, mutate in (("missing", lambda rows: rows.pop()),
                              ("extra", lambda rows: rows.append(copy.deepcopy(rows[0]))),
                              ("duplicate", lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0]))),
                              ("reorder", lambda rows: rows.reverse()),
                              ("case", lambda rows: rows[0].update(case_id="fp16-zero")),
                              ("bool iteration", lambda rows: rows[0].update(iteration=False)),
                              ("same poison", lambda rows: rows[1]["trace"].update(poison=records.POISONS[0]))):
            value = copy.deepcopy(self.value)
            mutate(value["matmuls"])
            with self.subTest(label=label):
                self.reject(value)

    def test_model_membership_iteration_and_two_distinct_poisons(self):
        for label, mutate in (("missing", lambda rows: rows.pop()),
                              ("extra", lambda rows: rows.append(copy.deepcopy(rows[0]))),
                              ("duplicate", lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0]))),
                              ("reorder", lambda rows: rows.reverse()),
                              ("case", lambda rows: rows[0].update(case_id="fp16-zero")),
                              ("bool iteration", lambda rows: rows[0].update(iteration=False)),
                              ("same poison", lambda rows: rows[1]["record"]["trace"].update(poison=records.POISONS[0]))):
            value = copy.deepcopy(self.value)
            mutate(value["models"])
            with self.subTest(label=label):
                self.reject(value)

    def test_actual_matmul_words_are_frozen_even_if_native_copy_is_changed_too(self):
        value, native = copy.deepcopy(self.value), copy.deepcopy(self.native)
        change_word(value["matmuls"][0]["actual_bits"])
        identifier = value["matmuls"][0]["case_id"]
        native["native_matmuls"][identifier][0]["actual_bits"] = value["matmuls"][0]["actual_bits"][:]
        self.assertNotEqual(hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
                            hashlib.sha256(json.dumps(self.value, sort_keys=True).encode()).hexdigest())
        self.reject(value, native=native, message="incomplete or reordered result")
        for replacement in ([], self.value["matmuls"][0]["actual_bits"][:-1],
                            self.value["matmuls"][0]["actual_bits"] + ["00000000"]):
            value = copy.deepcopy(self.value)
            value["matmuls"][0]["actual_bits"] = replacement
            self.reject(value)

    def test_native_matmul_and_model_word_disagreement_is_rejected(self):
        native = copy.deepcopy(self.native)
        identifier = self.value["matmuls"][0]["case_id"]
        change_word(native["native_matmuls"][identifier][0]["actual_bits"])
        self.reject(self.value, native=native, message="unchanged native executable")
        for key in ("hidden_words", "bridge_words", "output_words"):
            native = copy.deepcopy(self.native)
            identifier = self.value["models"][0]["case_id"]
            change_word(native["native_models"][identifier][0]["trace"][key])
            with self.subTest(field=key):
                self.reject(self.value, native=native, message="installed/native model differs")
        for key in ("a_bytes", "b_bytes", "output_words"):
            native = copy.deepcopy(self.native)
            stage = native["native_models"][self.value["models"][0]["case_id"]][0]["trace"]["native"][0]
            if key == "output_words":
                change_word(stage[key])
            else:
                stage[key] = "ff" + stage[key][2:]
            with self.subTest(stage_field=key):
                self.reject(self.value, native=native, message="installed/native model stage differs")

    def test_each_abi_header_and_address_segment_is_checked(self):
        for index in (0, 4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 55):
            value = copy.deepcopy(self.value)
            trace = value["matmuls"][0]["trace"]
            argument = bytearray.fromhex(trace["argument_bytes"])
            argument[index] ^= 1
            trace["argument_bytes"] = argument.hex()
            with self.subTest(byte=index):
                self.reject(value, message="ABI")
        for key, address in (("a_address", 0x1001), ("b_address", 0x1000),
                             ("d_address", 0x2004), ("d_address", (1 << 64) - 4)):
            value = copy.deepcopy(self.value)
            trace = value["matmuls"][0]["trace"]
            trace[key] = address
            trace["argument_bytes"] = wire(trace)
            with self.subTest(field=key, address=address):
                self.reject(value)

    def test_dispatch_counts_profiles_order_and_resources_are_observed(self):
        mutations = (
            ("writes", lambda row: row["trace"].update(writes_enqueued=2)),
            ("launches", lambda row: row["trace"].update(launches_enqueued=0)),
            ("reads", lambda row: row["trace"].update(reads_enqueued=0)),
            ("wait", lambda row: row["trace"].update(wait_calls=1, timed_out_waits=1)),
            ("binding", lambda row: row["trace"].update(qualification_id="f" * 64)),
            ("format", lambda row: row["trace"].update(input_dtype="bf16")),
            ("profile disabled", lambda row: row["trace"].update(profiling_enabled=False)),
            ("event failure", lambda row: row["trace"]["event_results"].__setitem__(0, 6)),
            ("bool event", lambda row: row["trace"]["event_results"].__setitem__(0, False)),
            ("profile failure", lambda row: row["trace"]["event_profile_results"].__setitem__(0, 6)),
            ("unqueried", lambda row: row["trace"]["event_profile_queried"].__setitem__(0, False)),
            ("missing profile", lambda row: row["trace"]["event_profiles"].pop()),
            ("reverse profile", lambda row: row["trace"]["event_profiles"][0].update(end_ns=0)),
            ("overlap profile", lambda row: row["trace"]["event_profiles"][1].update(submit_ns=10000)),
            ("used leak", lambda row: row["resources"].update(used_after=0)),
            ("free leak", lambda row: row["resources"].update(free_after=0)),
            ("query error", lambda row: row["resources"].update(before_status=6)),
            ("bool resource", lambda row: row["resources"].update(after_status=False)),
            ("incomplete", lambda row: row["status"].update(complete=False)),
            ("cleanup", lambda row: row["close_status"].update(cleanup=6)),
        )
        for label, mutate in mutations:
            value = copy.deepcopy(self.value)
            mutate(value["matmuls"][0])
            with self.subTest(label=label):
                self.reject(value)

    def test_full_p04_strict_model_contract_rejects_rehashed_corruptions(self):
        mutations = (
            ("fixture", lambda row: row.update(fixture_sha256="f" * 64)),
            ("revision", lambda row: row.update(source_revision="e" * 40)),
            ("binding", lambda row: row.update(qualification_id="f" * 64)),
            ("backend", lambda row: row.update(backend="rtlsim")),
            ("extra trace", lambda row: row["trace"].update(invented=True)),
            ("hidden", lambda row: change_word(row["trace"]["hidden_words"])),
            ("bridge", lambda row: change_word(row["trace"]["bridge_words"])),
            ("output", lambda row: change_word(row["trace"]["output_words"])),
            ("A input", lambda row: row["trace"]["native"][0].update(a_bytes="00" * 512)),
            ("B weight", lambda row: row["trace"]["native"][0].update(b_bytes="00" * 256)),
            ("bridge input", lambda row: row["trace"]["native"][1].update(a_bytes="00" * 128)),
            ("row order", lambda row: row["trace"]["native"][2].update(row_begin=0)),
            ("submission ordering", lambda row: row["trace"]["native"][1].update(submit_begin_ns=0)),
            ("queue boundary", lambda row: row["trace"]["native"][0]["dispatch"]["event_profiles"][0].update(queued_ns=0)),
            ("uint duration", lambda row: row["trace"].update(close_ns=True)),
            ("resource leak", lambda row: row["trace"]["resources"].update(used_after=0)),
            ("owner", lambda row: row["trace"].update(owner_closed=False)),
            ("launch", lambda row: row["trace"]["native"][0]["dispatch"].update(launches_enqueued=0)),
        )
        for label, mutate in mutations:
            value = copy.deepcopy(self.value)
            mutate(value["models"][0]["record"])
            with self.subTest(label=label):
                self.reject(value)

    def test_cross_operation_order_includes_matmul_to_model_transition(self):
        for index in (1, 2, 5):
            value = copy.deepcopy(self.value)
            trace = value["matmuls"][index]["trace"]
            for profile in trace["event_profiles"]:
                for key in profile:
                    profile[key] -= 10000
            with self.subTest(matmul=index):
                self.reject(value, message="predecessor")
        value = copy.deepcopy(self.value)
        value["models"][0]["record"]["trace"]["create_begin_ns"] = 1
        self.reject(value, message="predecessor")

    def test_installation_identity_pins_and_paths_are_strict(self):
        for key, replacement in (("prefix", "/foreign"), ("executable", self.value["installation"]["package_file"]),
                                  ("base_prefix", self.request["expected_prefix"]), ("base_prefix", "relative"),
                                  ("distribution_version", "0.2.0"), ("python_version", [3, 13, 0]),
                                  ("python_version", [3, 12, False]), ("python_implementation", "PyPy"),
                                  ("runtime_libraries", []), ("package_file", str(Path(__file__).resolve())),
                                  ("extension_file", str(Path(__file__).resolve())),
                                  ("build_info", {"binding_api": True, "source_sha256": "b" * 64,
                                                  "bundle_sha256": "a" * 64})):
            value = copy.deepcopy(self.value)
            value["installation"][key] = replacement
            with self.subTest(field=key):
                self.reject(value)
        for key in ("bundle_sha256", "source_sha256"):
            value = copy.deepcopy(self.value)
            value["installation"]["build_info"][key] = "f" * 64
            self.reject(value, message="immutable pins")

    def test_installed_file_symlink_and_noncanonical_paths_are_rejected(self):
        value = copy.deepcopy(self.value)
        source = Path(value["installation"]["extension_file"])
        alias = source.parent / "_native.alias.so"
        alias.symlink_to(source)
        value["installation"]["extension_file"] = str(alias)
        self.reject(value, message="isolated venv")
        value["installation"]["extension_file"] = str(source.parent / ".." / source.parent.name / source.name)
        self.reject(value, message="isolated venv")

    def test_raw_file_disagreement_duplicates_missing_and_reordering_are_rejected(self):
        lines = raw_log(self.value).splitlines(keepends=True)
        for label, raw in (("changed file", raw_log(self.value)), ("missing", "".join(lines[1:])),
                           ("duplicate", "".join([lines[0], *lines])),
                           ("reorder", "".join([lines[1], lines[0], *lines[2:]]))):
            value = copy.deepcopy(self.value)
            if label == "changed file":
                value["matmuls"][0]["trace"]["wait_calls"] += 1
            with self.subTest(label=label):
                self.reject(value, raw=raw, message="raw log")

    def test_raw_diagnostics_controls_and_ambiguous_markers_are_rejected(self):
        valid = raw_log(self.value)
        for prefix in ("FAILED", "FAIL", "ERROR", "FATAL", "ABORTED", "MISMATCH",
                       "P05_FAILURE", "Segmentation fault", "runtime error:", "\x00", "\x1b[0m", "\x85"):
            with self.subTest(prefix=repr(prefix)):
                self.reject(self.value, raw=prefix + "\n" + valid)
        for marker in ("x P05_MATMUL ", "P05_MATMUL=", "x P05_MODEL ", "P05_MODEL="):
            with self.subTest(marker=marker):
                self.reject(self.value, raw=marker + "{}\n" + valid, message="marker")

    def test_raw_marker_case_variants_cannot_hide_extra_observations(self):
        valid = raw_log(self.value)
        for marker in ("p05_matmul", "P05_Matmul", "p05_model", "P05_Model"):
            with self.subTest(marker=marker):
                self.reject(self.value, raw=marker + " {}\n" + valid, message="marker")

    def test_raw_global_order_requires_all_matmuls_before_models(self):
        rows = raw_log(self.value).splitlines(keepends=True)
        for raw in ("".join(rows[6:] + rows[:6]), "".join([*rows[:5], rows[6], rows[5], *rows[7:]])):
            self.reject(self.value, raw=raw, message="chronology")

    def test_native_library_stdout_without_record_or_failure_markers_is_allowed(self):
        rows = raw_log(self.value).splitlines(keepends=True)
        raw = "Vortex runtime version: host fixture\n" + "native library status: ready\n".join(rows)
        raw += "Native context released\n"
        self.assertEqual(self.verify(raw=raw)["counts"]["total_launches"], 36)

    def test_bounded_strict_json_rejects_duplicate_noninteger_and_invalid_data(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1.0}',
                    b'\xff', b'{', "{}", b"[" * 2000):
            with self.subTest(raw=repr(raw[:30])), self.assertRaises(ValueError):
                records.decode_json(raw)
        with patch.object(records, "MAX_JSON_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "oversized"):
                records.decode_json(b'{"x":123}')
            with self.assertRaisesRegex(ValueError, "oversized"):
                records._raw_rows("x" * 9, "P05_MATMUL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
