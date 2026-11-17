# SPDX-License-Identifier: Apache-2.0
"""Independent, source-only audit of the frozen WGMMA integer fixtures.

Expected results come from decoding the exported input bytes, not the producer's
input formulas, arithmetic, packing helpers, or expected-result encoder. These
checks establish fixture sensitivity; they do not establish GPU execution.
"""

import csv
from copy import deepcopy
from fractions import Fraction
from itertools import accumulate
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest

import p02_wgmma_fixture_oracle as producer


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "ci/project/fixtures/p02_wgmma_v1.json"
HEADER = ROOT / "tests/regression/p02_wgmma/fixtures.h"
FORMATS = {"fp16": (10, 15), "bf16": (7, 127)}
CASE_IDENTITIES = {
    f"{fmt}-{'sparse' if sparse else 'dense'}-signatures-{letter}": (fmt, sparse, pattern)
    for fmt, sparse in (("fp16", False), ("bf16", False), ("fp16", True))
    for pattern, letter in enumerate("ab")
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw_words(words, count):
    require(isinstance(words, list) and len(words) == count, "wrong word count")
    require(all(isinstance(word, str) and re.fullmatch(r"[0-9a-f]{8}", word)
                for word in words), "noncanonical word")
    return [int(word, 16) for word in words]


def exact_integer(bits, format_name):
    """Decode IEEE binary16 or bfloat16 using an exact rational value."""
    fraction_bits, bias = FORMATS[format_name]
    exponent = (bits & 0x7fff) >> fraction_bits
    fraction = bits & ((1 << fraction_bits) - 1)
    require(exponent != 2 * bias + 1, "nonfinite operand")
    require(bits != 0x8000, "negative zero operand")
    significand = fraction + (1 << fraction_bits if exponent else 0)
    power = (exponent or 1) - bias - fraction_bits
    value = (-1 if bits & 0x8000 else 1) * significand * Fraction(2) ** power
    require(value.denominator == 1, "noninteger operand")
    return value.numerator


def input_rows(words, count, columns, format_name):
    # Decode memory in two-byte units, independently of the producer's shifts.
    memory = b"".join(word.to_bytes(4, "little") for word in raw_words(words, count))
    values = [exact_integer(bits, format_name) for (bits,) in struct.iter_unpack("<H", memory)]
    require(all(1 <= abs(value) <= 7 for value in values), "operand outside nonzero integer bound")
    return [values[offset:offset + columns] for offset in range(0, len(values), columns)]


def metadata_masks(words):
    """Read two active lane words per K8 tile, then undo byte bit planes.

    Each active word holds four row bytes. Within a byte, the low pair and
    high pair of each nibble belong to different groups of four. This inverse
    uses byte/nibble extraction rather than the producer's per-element table.
    """
    values = raw_words(words, 128)
    rows = [[] for _ in range(64)]
    for tile_index in range(16):
        lanes = values[tile_index * 8:(tile_index + 1) * 8]
        require(all(lanes[lane] == 0 for lane in (1, 3, 4, 5, 6, 7)),
                "nonzero metadata padding")
        row_bytes = lanes[0].to_bytes(4, "little") + lanes[2].to_bytes(4, "little")
        for local_row, byte in enumerate(row_bytes):
            first = (byte & 0x03) | ((byte >> 2) & 0x0c)
            second = ((byte >> 2) & 0x03) | ((byte >> 4) & 0x0c)
            require(first.bit_count() == second.bit_count() == 2, "metadata is not two-of-four")
            rows[(tile_index // 2) * 8 + local_row].extend((first, second))
    return rows


def expand_sparse(compressed, masks):
    result = []
    for values, groups in zip(compressed, masks):
        positions = [4 * group + bit for group, mask in enumerate(groups)
                     for bit in range(4) if mask & (1 << bit)]
        require(len(positions) == len(values) == 8, "sparse row cardinality")
        selected = dict(zip(positions, values))
        result.append([selected.get(column, 0) for column in range(16)])
    return result


def product(a, b):
    columns = tuple(zip(*b))
    results = []
    for row in a:
        for column in columns:
            products = [left * right for left, right in zip(row, column)]
            require(all(abs(value) <= 49 for value in products), "product bound exceeded")
            partials = list(accumulate(products))
            require(all(abs(value) <= 784 for value in partials), "partial-sum bound exceeded")
            results.append(partials[-1])
    return results


def decode_case(case):
    require(case.get("id") in CASE_IDENTITIES, "unexpected case identity")
    fmt, sparse, pattern = CASE_IDENTITIES[case["id"]]
    require(type(case.get("sparse")) is bool and type(case.get("pattern")) is int,
            "case field types")
    require((case.get("format"), case["sparse"], case["pattern"]) == (fmt, sparse, pattern),
            "case identity disagrees with fields")
    require(all(type(case.get(key)) is int for key in ("m", "n", "k")) and
            (case["m"], case["n"], case["k"]) == (64, 8, 16), "wrong geometry")
    stored_a = input_rows(case["a_words"], 256 if sparse else 512, 8 if sparse else 16, fmt)
    b = input_rows(case["b_words"], 64, 8, fmt)
    if sparse:
        masks = metadata_masks(case["metadata_words"])
        require(case["sparse_masks"] == [[f"{mask:x}" for mask in row] for row in masks],
                "declared masks disagree with metadata")
        a = expand_sparse(stored_a, masks)
    else:
        require(case["metadata_words"] == [] and case["sparse_masks"] == [],
                "dense case has sparse metadata")
        masks, a = None, stored_a
    raw_words(case["expected"], 512)
    expected = product(a, b)
    # Every result is a small exact integer. The standard IEEE packer is an
    # independent encoding path, with no production or producer helper call.
    require(case["expected"] == [struct.pack(">f", value).hex() for value in expected],
            "expected FP32 words disagree with decoded input product")
    return a, b, stored_a, masks, expected


def fault_results(case):
    a, b, stored_a, masks, _ = decode_case(case)
    # Drop faults are computed from the surviving dot-product slice directly.
    variants = {
        "drop_first_k_tile": product([row[8:] for row in a], b[8:]),
        "drop_second_k_tile": product([row[:8] for row in a], b[:8]),
    }
    stale_b = [b[index % 8] for index in range(16)]
    if masks is None:
        stale_a = [[row[index % 8] for index in range(16)] for row in stored_a]
    else:
        repeated = [[row[index % 4] for index in range(8)] for row in stored_a]
        stale_a = expand_sparse(repeated, masks)
        # Fault the actual metadata memory first; decode it through our inverse.
        stale_metadata = case["metadata_words"].copy()
        for warp in range(8):
            start = warp * 16
            stale_metadata[start + 8:start + 16] = stale_metadata[start:start + 8]
        rotated_metadata = case["metadata_words"][16:] + case["metadata_words"][:16]
        variants["stale_second_metadata_tile"] = product(
            expand_sparse(stored_a, metadata_masks(stale_metadata)), b)
        variants["next_warp_metadata"] = product(
            expand_sparse(stored_a, metadata_masks(rotated_metadata)), b)
    variants["stale_second_a_tile"] = product(stale_a, b)
    variants["stale_second_b_tile"] = product(a, stale_b)
    variants["stale_second_a_and_b_tiles"] = product(stale_a, stale_b)
    return variants


def audit_document(document):
    require(document["schema_version"] == document["contract_version"] == 1,
            "wrong contract version")
    require(document["contract_id"] == "p02-wgmma-integer-matrices-v1", "wrong contract")
    require(document["gpu_execution_claimed"] is False and
            document["producer"]["production_model_used"] is False and
            document["producer"]["production_packing_used"] is False, "wrong claim scope")
    require(type(document["case_count"]) is int and document["case_count"] == 6 and
            len(document["cases"]) == 6, "wrong case count")
    require({case["id"] for case in document["cases"]} == set(CASE_IDENTITIES),
            "missing or duplicate case")
    return [decode_case(case) for case in document["cases"]]


def audit_header(text, document):
    declarations = re.findall(r"inline constexpr uint32_t (\w+)\[\] = \{(.*?)\};", text, re.S)
    arrays = {}
    for name, body in declarations:
        require(name not in arrays, "duplicate header array")
        words = re.findall(r"0x([0-9a-f]{8})u", body)
        require(not re.sub(r"0x[0-9a-f]{8}u|[\s,]", "", body), "invalid header literal")
        arrays[name] = words
    table = re.search(r"inline constexpr Case cases\[\] = \{(.*?)\n\};", text, re.S)
    require(table is not None, "missing header table")
    entries = [line.strip() for line in table.group(1).splitlines() if line.strip()]
    require(len(entries) == len(document["cases"]), "header case count")
    referenced = set()
    for line, case in zip(entries, document["cases"]):
        require(line.startswith("{") and line.endswith("},"), "header entry syntax")
        fields = next(csv.reader([line[1:-2]], skipinitialspace=True))
        require(len(fields) == 14, "header entry field count")
        require(fields[:6] == [case["id"], case["format"], str(case["sparse"]).lower(),
                               "64u", "8u", "16u"], "header case identity")
        for offset, key in zip((6, 8, 10, 12), ("a_words", "b_words", "metadata_words", "expected")):
            pointer, count = fields[offset:offset + 2]
            require(count == f"{len(case[key])}u", "header word count")
            if case[key]:
                require(arrays.get(pointer) == case[key], "header array content or pointer")
                referenced.add(pointer)
            else:
                require(pointer == "nullptr", "empty header array pointer")
    require(referenced == set(arrays), "unreferenced header array")
    require("case_count = sizeof(cases) / sizeof(cases[0]);" in text, "header count expression")


class WgmmaFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(CORPUS.read_text())
        cls.cases = cls.document["cases"]
        cls.header = HEADER.read_text()

    def test_exact_decoder_has_independent_known_encodings(self):
        for fmt, examples in {
            "fp16": {0x0000: 0, 0x3c00: 1, 0xc000: -2, 0x4700: 7},
            "bf16": {0x0000: 0, 0x3f80: 1, 0xc000: -2, 0x40e0: 7},
        }.items():
            for bits, value in examples.items():
                with self.subTest(format=fmt, bits=bits):
                    self.assertEqual(exact_integer(bits, fmt), value)
        for fmt, bits in (("fp16", 0x3e00), ("bf16", 0x3fc0),
                          ("fp16", 0x0001), ("bf16", 0x0001),
                          ("fp16", 0x7c00), ("bf16", 0x7fc0), ("fp16", 0x8000)):
            with self.subTest(format=fmt, bits=bits), self.assertRaises(ValueError):
                exact_integer(bits, fmt)

    def test_independent_products_match_all_3072_words(self):
        decoded = audit_document(self.document)
        self.assertEqual(sum(len(item[-1]) for item in decoded), 3072)

    def test_frozen_geometry_and_arithmetic_scope(self):
        self.assertEqual(self.document["geometry"], {
            "xlen": 64, "threads_per_warp": 8, "warps": 8, "issue_width": 4,
            "warps_per_cta": 4, "cta_count": 2, "warp_output_shape": [8, 8],
            "k_tile_elements": 8, "k_tile_count": 2, "nrc": 8, "kunroll": 1,
            "m": 64, "n": 8, "k": 16,
        })
        for key, value in {"operand_integer_bound": 7, "product_integer_bound": 49,
                           "partial_sum_integer_bound": 784, "initial_fp32_bits": "00000000",
                           "zero_encoding": "positive zero", "comparison": "exact uint32 equality"}.items():
            self.assertEqual(self.document["arithmetic"][key], value)

    def test_sparse_masks_padding_and_reconstruction(self):
        for case in self.cases:
            if not case["sparse"]:
                continue
            with self.subTest(case=case["id"]):
                a, _, compressed, masks, _ = decode_case(case)
                self.assertEqual({mask for row in masks for mask in row}, {3, 5, 6, 9, 10, 12})
                for row, packed, groups in zip(a, compressed, masks):
                    self.assertEqual([value for value in row if value], packed)
                    for group, mask in enumerate(groups):
                        actual = sum(1 << bit for bit, value in enumerate(row[group * 4:group * 4 + 4]) if value)
                        self.assertEqual(actual, mask)

    def test_warp_and_cta_output_signatures_are_distinct(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                expected = decode_case(case)[-1]
                warps = {tuple(expected[start:start + 64]) for start in range(0, 512, 64)}
                ctas = {tuple(expected[start:start + 256]) for start in (0, 256)}
                self.assertEqual(len(warps), 8)
                self.assertEqual(len(ctas), 2)
                self.assertEqual(case["sensitivity"]["distinct_warp_output_signatures"], len(warps))
                self.assertEqual(case["sensitivity"]["distinct_cta_output_signatures"], len(ctas))

    def test_declared_fault_counts_and_every_warp_sensitivity(self):
        for case in self.cases:
            expected = decode_case(case)[-1]
            faults = fault_results(case)
            self.assertEqual(set(case["sensitivity"]), set(faults) | {
                "distinct_warp_output_signatures", "distinct_cta_output_signatures"})
            for name, actual in faults.items():
                mismatches = [left != right for left, right in zip(actual, expected)]
                with self.subTest(case=case["id"], fault=name):
                    self.assertEqual(sum(mismatches), case["sensitivity"][name])
                    for warp in range(8):
                        self.assertTrue(any(mismatches[warp * 64:(warp + 1) * 64]),
                                        f"{name} invisible in warp {warp}")

    def test_patterns_differ_and_dense_formats_agree(self):
        by_id = {case["id"]: case for case in self.cases}
        for kind in ("fp16-dense", "bf16-dense", "fp16-sparse"):
            first, second = (by_id[f"{kind}-signatures-{letter}"] for letter in "ab")
            for field in ("a_words", "b_words", "expected"):
                self.assertNotEqual(first[field], second[field])
        for letter in "ab":
            fp16 = decode_case(by_id[f"fp16-dense-signatures-{letter}"])
            bf16 = decode_case(by_id[f"bf16-dense-signatures-{letter}"])
            self.assertEqual(fp16, bf16)

    def test_frozen_outputs_regenerate_deterministically(self):
        first, second = producer.fixture_document(), producer.fixture_document()
        self.assertEqual(first, second)
        self.assertEqual((json.dumps(first, indent=2) + "\n").encode(), CORPUS.read_bytes())
        self.assertEqual(producer.header_bytes(first), producer.header_bytes(second))
        self.assertEqual(producer.header_bytes(first), HEADER.read_bytes())

    def test_producer_check_entrypoint(self):
        completed = subprocess.run([sys.executable, str(ROOT / "ci/project/p02_wgmma_fixture_oracle.py"),
                                    "--check"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("6 cases, 3072 exact output words", completed.stdout)

    def test_header_data_counts_and_case_bindings(self):
        audit_header(self.header, self.document)

    def test_single_input_sign_change_is_detected(self):
        for original in self.cases:
            for field in ("a_words", "b_words"):
                case = deepcopy(original)
                case[field][0] = f"{int(case[field][0], 16) ^ 0x8000:08x}"
                with self.subTest(case=case["id"], field=field), self.assertRaisesRegex(ValueError, "expected FP32"):
                    decode_case(case)

    def test_single_expected_bit_change_is_detected(self):
        for original in self.cases:
            case = deepcopy(original)
            case["expected"][0] = f"{int(case['expected'][0], 16) ^ 1:08x}"
            with self.subTest(case=case["id"]), self.assertRaisesRegex(ValueError, "expected FP32"):
                decode_case(case)

    def test_metadata_bit_and_padding_changes_are_detected(self):
        for original in self.cases:
            if not original["sparse"]:
                continue
            for lane, error in ((0, "two-of-four"), (1, "metadata padding")):
                case = deepcopy(original)
                case["metadata_words"][lane] = f"{int(case['metadata_words'][lane], 16) ^ 1:08x}"
                with self.subTest(case=case["id"], lane=lane), self.assertRaisesRegex(ValueError, error):
                    decode_case(case)

    def test_legal_metadata_change_with_matching_masks_still_fails_product(self):
        for original in self.cases:
            if not original["sparse"]:
                continue
            case = deepcopy(original)
            # Complement the first row's first two-of-four group; cardinality
            # remains legal. Update its declaration so arithmetic must catch it.
            case["metadata_words"][0] = f"{int(case['metadata_words'][0], 16) ^ 0x33:08x}"
            case["sparse_masks"][0][0] = f"{int(case['sparse_masks'][0][0], 16) ^ 0xf:x}"
            with self.subTest(case=case["id"]), self.assertRaisesRegex(ValueError, "expected FP32"):
                decode_case(case)

    def test_case_inventory_mutations_are_rejected(self):
        for mutation in ("count", "missing", "duplicate", "format", "geometry"):
            document = deepcopy(self.document)
            if mutation == "count":
                document["case_count"] -= 1
            elif mutation == "missing":
                document["cases"].pop()
            elif mutation == "duplicate":
                document["cases"][-1] = deepcopy(document["cases"][0])
            elif mutation == "format":
                document["cases"][0]["format"] = "bf16"
            else:
                document["cases"][0]["k"] = 8
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_document(document)

    def test_word_count_and_noncanonical_word_mutations_are_rejected(self):
        for field in ("a_words", "b_words", "expected", "metadata_words"):
            for mutation in ("truncate", "append", "malformed"):
                case = deepcopy(self.cases[-1])
                if mutation == "truncate":
                    case[field].pop()
                elif mutation == "append":
                    case[field].append("00000000")
                else:
                    case[field][0] = "0x12345678"
                with self.subTest(field=field, mutation=mutation), self.assertRaises(ValueError):
                    decode_case(case)

    def test_header_word_pointer_and_count_mutations_are_rejected(self):
        for old, new in (("0xc400c700u", "0xc400c701u"),
                         ("case_0_expected,", "case_1_expected,"),
                         ("case_0_expected, 512u", "case_0_expected, 511u")):
            self.assertIn(old, self.header)
            with self.subTest(mutation=old), self.assertRaises(ValueError):
                audit_header(self.header.replace(old, new, 1), self.document)


if __name__ == "__main__":
    unittest.main()
