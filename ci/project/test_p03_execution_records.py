# SPDX-License-Identifier: Apache-2.0
"""Corruption checks for execution records; these tests do not execute a GPU."""

import copy
import json
from pathlib import Path
import struct
import unittest

import p03_execution_records as records
import test_p02_matrix as retained


BINDING_ID = "0123456789abcdef" * 4
TRANSPORT_BITS = ["00000000", "80000000", "7f800000", "ff800000",
                  "7fc00000", "3f800000", "bf800000", "00000001"]


def case(fmt="bf16", shape=(8, 4, 8)):
    m, n, k = shape
    return {"id": "transport-bits", "format": fmt, "m": m, "n": n, "k": k,
            "expected": TRANSPORT_BITS * (m * n // len(TRANSPORT_BITS))}


def wire(row):
    dispatch = row["dispatch"]
    return struct.pack("<8I3Q", 1, 56, 1 if row["format"] == "fp16" else 2, 0,
                       row["m"], row["n"], row["k"], 0,
                       dispatch["a_address"], dispatch["b_address"], dispatch["d_address"]).hex()


def result(input_case=None, iteration=0):
    selected = input_case or case()
    row = {"case_id": selected["id"], "format": selected["format"],
           "m": selected["m"], "n": selected["n"], "k": selected["k"],
           "iteration": iteration, "checked": selected["m"] * selected["n"],
           "mismatches": 0, "actual_bits": list(selected["expected"]),
           "qualification_id": BINDING_ID,
           "dispatch": {"a_address": 0x1000, "b_address": 0x2000, "d_address": 0x3000,
                        "a_bytes": selected["m"] * selected["k"] * 2,
                        "b_bytes": selected["k"] * selected["n"] * 2,
                        "d_bytes": selected["m"] * selected["n"] * 4,
                        "writes": 3, "reads": 1, "launches": 1, "waits": 1,
                        "poison": 0x7FC0DEAD if iteration == 0 else 0xDEADBEEF},
           "resources": {"used_before": 0x20000, "used_after": 0x20000,
                         "free_before": 0x100000, "free_after": 0x100000,
                         "primary": 0, "cleanup": 0}}
    row["dispatch"]["argument_bytes"] = wire(row)
    return row


def output(rows=None):
    selected = rows if rows is not None else [result(iteration=0), result(iteration=1)]
    return "P03_REJECTIONS checked=2\n" + "".join(
        "P03_RESULT " + json.dumps(row, separators=(",", ":")) + "\n" for row in selected) + "PASSED!\n"


class OutputCorruptionTests(unittest.TestCase):
    def reject(self, text, *, input_case=None, iterations=1, binding_id=BINDING_ID):
        with self.assertRaises((ValueError, TypeError)):
            records.verify_output(text, input_case or case(), iterations, binding_id)

    def test_all_six_signatures_preserve_raw_output_and_literal_wire_fields(self):
        for fmt in ("fp16", "bf16"):
            for shape in ((8, 4, 8), (8, 4, 16), (16, 8, 16)):
                selected = case(fmt, shape)
                rows = [result(selected, 0), result(selected, 1)]
                with self.subTest(format=fmt, shape=shape):
                    self.assertEqual(records.verify_output(output(rows), selected, 2, BINDING_ID), rows)
        self.assertEqual(result()["dispatch"]["argument_bytes"],
            "0100000038000000020000000000000008000000040000000800000000000000"
            "001000000000000000200000000000000030000000000000")

    def test_every_returned_word_is_compared_without_float_conversion(self):
        for index, replacement in ((0, "80000000"), (1, "00000000"), (4, "7fc00001"),
                                    (31, "00000000"), (4, "7FC00000"), (0, 0), (0, False)):
            row = result()
            row["actual_bits"][index] = replacement
            with self.subTest(index=index, replacement=replacement):
                self.reject(output([row]))
        for replacement in ([], TRANSPORT_BITS, case()["expected"] + ["00000000"], None, "0"):
            row = result()
            row["actual_bits"] = replacement
            with self.subTest(replacement=replacement):
                self.reject(output([row]))

    def test_identity_shape_count_and_binding_corruption_are_rejected(self):
        for key, value in (("case_id", "another"), ("format", "fp16"), ("m", 16), ("n", 8),
                           ("k", 16), ("checked", 31), ("mismatches", 1),
                           ("qualification_id", "f" * 64)):
            row = result()
            row[key] = value
            with self.subTest(field=key):
                self.reject(output([row]))
        for value in ("", "g" * 64, "0" * 63, BINDING_ID.upper()):
            with self.subTest(binding=value):
                self.reject(output([result()]), binding_id=value)

    def test_missing_extra_duplicate_and_reordered_launches_are_rejected(self):
        for order in ([], [0], [1], [0, 0], [1, 0], [0, 2], [0, 1, 2]):
            with self.subTest(order=order):
                self.reject(output([result(iteration=i) for i in order]), iterations=2)
        for iterations in (0, -1, 3, True, 1.0):
            with self.subTest(iterations=iterations):
                self.reject(output([result()]), iterations=iterations)

    def test_each_transfer_launch_wait_and_poison_is_required(self):
        for key, value in (("a_bytes", 64), ("b_bytes", 128), ("d_bytes", 64),
                           ("writes", 2), ("reads", 0), ("launches", 0), ("launches", 2),
                           ("waits", 0), ("poison", 0xDEADBEEF)):
            row = result()
            row["dispatch"][key] = value
            with self.subTest(field=key):
                self.reject(output([row]))
        rows = [result(), result(iteration=1)]
        rows[1]["dispatch"]["poison"] = rows[0]["dispatch"]["poison"]
        self.reject(output(rows), iterations=2)

    def test_exact_argument_header_and_addresses_are_checked(self):
        for index in (0, 4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 55):
            row = result()
            changed = bytearray.fromhex(row["dispatch"]["argument_bytes"])
            changed[index] ^= 1
            row["dispatch"]["argument_bytes"] = changed.hex()
            with self.subTest(byte=index):
                self.reject(output([row]))
        for replacement in ("", "00" * 55, "00" * 57, None, 56, "gg" * 56):
            row = result()
            row["dispatch"]["argument_bytes"] = replacement
            with self.subTest(replacement=replacement):
                self.reject(output([row]))

    def test_alias_alignment_and_wrapped_ranges_fail_even_with_matching_wire(self):
        for field, address in (("a_address", 0x1001), ("b_address", 0x1000),
                               ("d_address", 0x2004), ("d_address", (1 << 64) - 4)):
            row = result()
            row["dispatch"][field] = address
            row["dispatch"]["argument_bytes"] = wire(row)
            with self.subTest(field=field, address=address):
                self.reject(output([row]))
        row = result()
        row["dispatch"]["d_address"] = (1 << 64) - row["dispatch"]["d_bytes"]
        row["dispatch"]["argument_bytes"] = wire(row)
        self.assertEqual(records.verify_output(output([row]), case(), 1, BINDING_ID), [row])

    def test_memory_leaks_and_primary_or_cleanup_errors_are_rejected(self):
        for key, value in (("used_after", 0x20040), ("free_after", 0xFFFF0),
                           ("primary", 6), ("cleanup", 10)):
            row = result()
            row["resources"][key] = value
            with self.subTest(field=key):
                self.reject(output([row]))

    def test_boolean_float_string_and_negative_measurements_are_rejected(self):
        original = result()
        for section in (None, "dispatch", "resources"):
            keys = ("m", "n", "k", "iteration", "checked", "mismatches") if section is None else \
                [key for key in original[section] if key != "argument_bytes"]
            for key in keys:
                for replacement in (True, False, 0.0, "0", None, -1):
                    row = result()
                    (row if section is None else row[section])[key] = replacement
                    with self.subTest(section=section, field=key, replacement=replacement):
                        self.reject(output([row]))

    def test_missing_extra_and_duplicate_fields_are_rejected_at_each_level(self):
        for section in (None, "dispatch", "resources"):
            for mutation in ("missing", "extra"):
                row = result()
                target = row if section is None else row[section]
                if mutation == "missing":
                    del target[next(iter(target))]
                else:
                    target["unexpected"] = 1
                with self.subTest(section=section, mutation=mutation):
                    self.reject(output([row]))
        for key in ("m", "poison", "used_before"):
            self.reject(output([result()]).replace('"' + key + '":', '"' + key + '":0,"' + key + '":', 1))

    def test_failure_control_and_ambiguous_success_markers_are_rejected(self):
        good = output([result()])
        for prefix in ("FAILED", "FAIL", "ERROR", "FATAL", "ABORTED", "MISMATCH",
                       "Assertion x failed", "Segmentation fault", "runtime error:",
                       "\x00", "\x1b[32m", "\v", "\f", "PASSED earlier"):
            with self.subTest(prefix=prefix):
                self.reject(prefix + "\n" + good)
        for text in ("", good.replace("PASSED!\n", ""), good + "PASSED!\n",
                     good + "trailer\n", good.replace("P03_RESULT ", "x P03_RESULT "),
                     good.replace("P03_RESULT ", "P03_RESULT=")):
            with self.subTest(text=text[:30]):
                self.reject(text)


class CompilerBindingTests(unittest.TestCase):
    def samples(self, backend="simx"):
        values = [retained.sample(backend + "_rt"), retained.sample(backend + "_backend"),
                  retained.sample("application")]
        lines = values[2].splitlines()
        lines[2] = "-L" + str(retained.BUILD / "sw/runtime") + " -lvortex"
        values[2] = "\n".join(lines) + "\n"
        return values

    def validate(self, values, backend="simx"):
        return records.validate_records(*values, driver=backend, fmt="bf16", source=retained.SOURCE,
                                        build=retained.BUILD, jobs=2)

    def test_both_backend_record_sets_preserve_independent_roles(self):
        for backend, roles in (("simx", ["runtime", "backend_cpp", "kernel", "host"]),
                               ("rtlsim", ["runtime", "verilator", "backend_cpp", "kernel", "host"])):
            with self.subTest(backend=backend):
                values = self.validate(self.samples(backend), backend)
                self.assertEqual([item["role"] for item in values], roles)

    def test_configuration_cannot_be_borrowed_from_another_record(self):
        for backend in ("simx", "rtlsim"):
            original = self.samples(backend)
            for index, text in enumerate(original):
                lines = text.splitlines()
                for line_index in range(len(lines) - (1 if index == 2 else 0)):
                    changed = list(original)
                    edited = list(lines)
                    self.assertIn("-DITYPE=bf16", edited[line_index])
                    edited[line_index] = edited[line_index].replace("-DITYPE=bf16", "")
                    changed[index] = "\n".join(edited)
                    with self.subTest(backend=backend, record=index, line=line_index), self.assertRaises(ValueError):
                        self.validate(changed, backend)

    def test_nonnative_arithmetic_and_other_format_rejected_per_record(self):
        original = self.samples()
        for index in range(3):
            for old, new in (("-DITYPE=bf16", "-DITYPE=fp16"),
                             ("-DVX_CFG_TCU_TYPE=TFR", "-DVX_CFG_TCU_TYPE=DPI"),
                             ("-DKUNROLL=1", "-DKUNROLL=2")):
                changed = list(original)
                self.assertIn(old, changed[index])
                changed[index] = changed[index].replace(old, new, 1)
                with self.subTest(record=index, replacement=new), self.assertRaises(ValueError):
                    self.validate(changed)

    def test_link_binding_must_name_only_the_exact_runtime_directory(self):
        for link in ("-L/another/runtime -lvortex", "-L" + str(retained.BUILD / "sw/runtime") + " -lfake",
                     "-L" + str(retained.BUILD / "sw/runtime") + " -lvortex -lother", "-lvortex",
                     "$(cat /tmp/flags)", "@flags.rsp"):
            values = self.samples()
            lines = values[2].splitlines()
            lines[2] = link
            values[2] = "\n".join(lines)
            with self.subTest(link=link), self.assertRaises(ValueError):
                self.validate(values)

    def test_missing_extra_and_reordered_record_roles_rejected(self):
        for backend in ("simx", "rtlsim"):
            for index in range(3):
                for extra in (False, True):
                    values = self.samples(backend)
                    lines = values[index].splitlines()
                    values[index] = "\n".join(lines + [lines[0]] if extra else lines[1:])
                    with self.subTest(backend=backend, index=index, extra=extra), self.assertRaises(ValueError):
                        self.validate(values, backend)
            values = self.samples(backend)
            lines = values[2].splitlines()
            values[2] = "\n".join((lines[1], lines[0], lines[2]))
            with self.subTest(backend=backend), self.assertRaises(ValueError):
                self.validate(values, backend)

    def test_binding_digest_is_canonical_and_changes_with_each_bound_identity(self):
        original = {"backend": "simx", "module_sha256": "a" * 64, "source": "b" * 40,
                    "compiler_records": [{"role": "kernel", "sha256": "c" * 64}]}
        digest = records.qualification_id(original)
        self.assertEqual(digest, records.qualification_id(dict(reversed(list(original.items())))))
        for key in original:
            changed = copy.deepcopy(original)
            changed[key] = "changed"
            with self.subTest(key=key):
                self.assertNotEqual(digest, records.qualification_id(changed))
        with self.assertRaises(ValueError):
            records.qualification_id({"invalid": float("nan")})


if __name__ == "__main__":
    unittest.main()
