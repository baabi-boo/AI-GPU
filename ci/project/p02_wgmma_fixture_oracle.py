#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Produce exact integer WGMMA matrices without production arithmetic or packing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "ci/project/fixtures/p02_wgmma_v1.json"
HEADER_PATH = ROOT / "tests/regression/p02_wgmma/fixtures.h"
CONTRACT_ID = "p02-wgmma-integer-matrices-v1"
M, N, K = 64, 8, 16
MASKS = (0x3, 0x5, 0x9, 0x6, 0xA, 0xC)
META_BIT = (0, 1, 4, 5, 2, 3, 6, 7)
FORMATS = {"fp16": (5, 10, 15), "bf16": (8, 7, 127), "fp32": (8, 23, 127)}


def encode_integer(value: int, format_name: str) -> int:
    if type(value) is not int or format_name not in FORMATS:
        raise ValueError("an integer and a supported binary format are required")
    if value == 0:
        return 0
    exponent_bits, fraction_bits, bias = FORMATS[format_name]
    magnitude = abs(value)
    exponent = magnitude.bit_length() - 1
    if exponent + bias >= (1 << exponent_bits) - 1:
        raise ValueError("integer overflows its binary format")
    shift = fraction_bits - exponent
    if shift < 0:
        significand, discarded = divmod(magnitude, 1 << -shift)
        if discarded:
            raise ValueError("integer cannot be represented exactly")
    else:
        significand = magnitude << shift
    return ((int(value < 0) << (exponent_bits + fraction_bits))
            | ((exponent + bias) << fraction_bits)
            | (significand - (1 << fraction_bits)))


def pack_memory(values: list[int], format_name: str) -> list[str]:
    if format_name not in ("fp16", "bf16") or len(values) % 2:
        raise ValueError("an even number of FP16/BF16 elements is required")
    elements = [encode_integer(value, format_name) for value in values]
    return [f"{elements[i] | (elements[i + 1] << 16):08x}"
            for i in range(0, len(elements), 2)]


def _nonzero_operand(index: int) -> int:
    residue = index % 14
    return residue - 7 if residue < 7 else residue - 6


def logical_inputs(pattern: int) -> tuple[list[list[int]], list[list[int]], list[list[int]]]:
    if type(pattern) is not int or pattern not in (0, 1):
        raise ValueError("only the two frozen patterns are supported")
    a = [[_nonzero_operand(5 * row + 3 * inner + 3 * (row // 8)
                          + 7 * (inner // 8) + pattern * (row % 7 + 2 * inner + 1)
                          + (row % 4) * (inner % 3))
          for inner in range(K)] for row in range(M)]
    b = [[_nonzero_operand(7 * inner + 5 * col + 3 * (inner // 8)
                          + pattern * (2 * col + inner % 5 + 3)
                          + (inner % 3) * (col % 4))
          for col in range(N)] for inner in range(K)]
    masks = [[MASKS[((row // 8) + 3 * (row % 8) + 2 * group + group // 2
                    + pattern * (group + row + 1)) % len(MASKS)]
              for group in range(K // 4)] for row in range(M)]
    return a, b, masks


def sparse_inputs(a: list[list[int]], masks: list[list[int]]) -> tuple[list[list[int]], list[list[int]]]:
    if len(a) != M or len(masks) != M:
        raise ValueError("sparse input requires 64 rows")
    dense, compressed = [], []
    for row, row_masks in zip(a, masks):
        if len(row) != K or len(row_masks) != K // 4 or any(mask not in MASKS for mask in row_masks):
            raise ValueError("each row needs sixteen values and four two-of-four masks")
        selected = [bool(row_masks[inner // 4] & (1 << (inner % 4))) for inner in range(K)]
        dense.append([value if selected[inner] else 0 for inner, value in enumerate(row)])
        compressed.append([value for inner, value in enumerate(row) if selected[inner]])
    return dense, compressed


def pack_metadata(masks: list[list[int]]) -> list[str]:
    if (len(masks) != M or any(len(row) != K // 4 for row in masks)
            or any(mask not in MASKS for row in masks for mask in row)):
        raise ValueError("metadata requires the frozen 64-by-four two-of-four masks")
    words = [0] * 128
    for row in range(M):
        warp, local_row = divmod(row, 8)
        lane = 2 * (local_row // 4)
        for tile in range(2):
            word_index = (warp * 2 + tile) * 8 + lane
            for element in range(8):
                mask = masks[row][tile * 2 + element // 4]
                if mask & (1 << (element % 4)):
                    words[word_index] |= 1 << (8 * (local_row % 4) + META_BIT[element])
    return [f"{word:08x}" for word in words]


def matrix_product(a: list[list[int]], b: list[list[int]]) -> list[int]:
    if len(a) != M or len(b) != K or any(len(row) != K for row in a) or any(len(row) != N for row in b):
        raise ValueError("matrix geometry must be 64-by-8-by-16")
    if any(type(value) is not int or abs(value) > 7 for matrix in (a, b) for row in matrix for value in row):
        raise ValueError("operands must be integers within -7 through 7")
    results = []
    for row in range(M):
        for col in range(N):
            total = 0
            for inner in range(K):
                total += a[row][inner] * b[inner][col]
                if abs(total) > 784:
                    raise ValueError("integer accumulation exceeded its proof bound")
            results.append(total)
    return results


def _project_compressed(compressed: list[list[int]], masks: list[list[int]]) -> list[list[int]]:
    output = [[0] * K for _ in range(M)]
    for row in range(M):
        offset = 0
        for group in range(K // 4):
            for position in range(4):
                if masks[row][group] & (1 << position):
                    output[row][4 * group + position] = compressed[row][offset]
                    offset += 1
    return output


def sensitivity(a: list[list[int]], b: list[list[int]], expected: list[int],
                compressed: list[list[int]] | None, masks: list[list[int]]) -> dict[str, int]:
    variants = {
        "drop_first_k_tile": ([([0] * 8 + row[8:]) for row in a], b),
        "drop_second_k_tile": ([(row[:8] + [0] * 8) for row in a], b),
        "stale_second_b_tile": (a, b[:8] + b[:8]),
    }
    if compressed is None:
        stale_a = [row[:8] + row[:8] for row in a]
    else:
        stale_a = _project_compressed([row[:4] + row[:4] for row in compressed], masks)
        stale_masks = [row[:2] + row[:2] for row in masks]
        variants["stale_second_metadata_tile"] = (_project_compressed(compressed, stale_masks), b)
        other_warp_masks = [masks[(row + 8) % M] for row in range(M)]
        variants["next_warp_metadata"] = (_project_compressed(compressed, other_warp_masks), b)
    variants["stale_second_a_tile"] = (stale_a, b)
    variants["stale_second_a_and_b_tiles"] = (stale_a, b[:8] + b[:8])
    counts = {name: sum(actual != wanted for actual, wanted in zip(matrix_product(va, vb), expected))
              for name, (va, vb) in variants.items()}
    if any(count == 0 for count in counts.values()):
        raise ValueError("fixture does not detect a declared stale-data fault")
    counts["distinct_warp_output_signatures"] = len({tuple(expected[warp * 64:(warp + 1) * 64])
                                                    for warp in range(8)})
    counts["distinct_cta_output_signatures"] = len({tuple(expected[:256]), tuple(expected[256:])})
    if counts["distinct_warp_output_signatures"] != 8 or counts["distinct_cta_output_signatures"] != 2:
        raise ValueError("warp and CTA signatures must be distinct")
    return counts


def make_case(format_name: str, sparse: bool, pattern: int) -> dict:
    if format_name not in ("fp16", "bf16") or type(sparse) is not bool or (sparse and format_name != "fp16"):
        raise ValueError("only dense FP16/BF16 and sparse FP16 are in this corpus")
    a, b, masks = logical_inputs(pattern)
    compressed = None
    if sparse:
        a, compressed = sparse_inputs(a, masks)
    expected = matrix_product(a, b)
    storage_a = a if compressed is None else compressed
    return {
        "id": f"{format_name}-{'sparse' if sparse else 'dense'}-signatures-{'ab'[pattern]}",
        "format": format_name, "sparse": sparse, "pattern": pattern,
        "m": M, "n": N, "k": K,
        "a_words": pack_memory([value for row in storage_a for value in row], format_name),
        "b_words": pack_memory([value for row in b for value in row], format_name),
        "metadata_words": pack_metadata(masks) if sparse else [],
        "sparse_masks": [[f"{mask:x}" for mask in row] for row in masks] if sparse else [],
        "expected": [f"{encode_integer(value, 'fp32'):08x}" for value in expected],
        "sensitivity": sensitivity(a, b, expected, compressed, masks),
    }


def fixture_document() -> dict:
    cases = [make_case(fmt, sparse, pattern)
             for fmt, sparse in (("fp16", False), ("bf16", False), ("fp16", True))
             for pattern in range(2)]
    return {
        "schema_version": 1, "contract_id": CONTRACT_ID, "contract_version": 1,
        "producer": {"path": "ci/project/p02_wgmma_fixture_oracle.py", "version": 1,
                     "method": "integer-only matrix product and exact binary encoding",
                     "production_model_used": False, "production_packing_used": False},
        "claim_scope": "Source fixtures for bounded WGMMA processor and protocol validation.",
        "gpu_execution_claimed": False, "case_count": len(cases),
        "arithmetic": {"operand_integer_bound": 7, "product_integer_bound": 49,
                       "partial_sum_integer_bound": 784, "initial_fp32_bits": "00000000",
                       "zero_encoding": "positive zero", "comparison": "exact uint32 equality",
                       "exactness": "Every product and partial sum is an exactly representable integer; no exponent span exceeds ten significant bits."},
        "geometry": {"xlen": 64, "threads_per_warp": 8, "warps": 8, "issue_width": 4,
                     "warps_per_cta": 4, "cta_count": 2, "warp_output_shape": [8, 8],
                     "k_tile_elements": 8, "k_tile_count": 2, "nrc": 8, "kunroll": 1,
                     "m": M, "n": N, "k": K},
        "storage": {"a": "compact row-major; sparse A keeps selected elements in ascending K order",
                    "b": "compact row-major", "output": "compact row-major FP32",
                    "packed_input_word": "earlier 16-bit element in low half; little-endian bytes",
                    "metadata_words_per_warp_tile": 8,
                    "metadata_word_index": "(warp * 2 + k_tile) * 8 + 2 * (local_row // 4)",
                    "metadata_bit_index": "8 * (local_row % 4) + [0,1,4,5,2,3,6,7][element_in_k_tile]",
                    "metadata_unused_lanes": [1, 3, 4, 5, 6, 7]},
        "limits": ["These integer fixtures do not extend the numerical rounding contract or qualify exceptional values.",
                   "Only dense FP16/BF16 and sparse FP16 with the declared geometry are represented.",
                   "Fixture generation does not demonstrate concurrency, metadata scheduling, stalls, or GPU execution.",
                   "Distinct output signatures and stale-data mutations are test sensitivity checks, not observed hardware coverage."],
        "cases": cases,
    }


def header_bytes(document: dict) -> bytes:
    lines = ["// SPDX-License-Identifier: Apache-2.0",
             "// Generated by ci/project/p02_wgmma_fixture_oracle.py; do not edit.",
             "#ifndef P02_WGMMA_FIXTURES_H", "#define P02_WGMMA_FIXTURES_H", "",
             "#include <cstddef>", "#include <cstdint>", "", "namespace p02_wgmma {", "",
             "struct Case {", "  const char* id;", "  const char* format;", "  bool sparse;",
             "  uint32_t m, n, k;", "  const uint32_t* a_words;", "  std::size_t a_word_count;",
             "  const uint32_t* b_words;", "  std::size_t b_word_count;",
             "  const uint32_t* metadata_words;", "  std::size_t metadata_word_count;",
             "  const uint32_t* expected;", "  std::size_t expected_count;", "};", ""]
    entries = []
    for index, case in enumerate(document["cases"]):
        names = {}
        for field in ("a_words", "b_words", "metadata_words", "expected"):
            words = case[field]
            if not words:
                names[field] = "nullptr"
                continue
            name = f"case_{index}_{field}"
            names[field] = name
            lines.append(f"inline constexpr uint32_t {name}[] = {{")
            for offset in range(0, len(words), 8):
                lines.append("  " + ", ".join("0x" + word + "u" for word in words[offset:offset + 8]) + ",")
            lines.extend(["};", ""])
        entries.append("  {\"%s\", \"%s\", %s, %du, %du, %du, %s, %du, %s, %du, %s, %du, %s, %du}," % (
            case["id"], case["format"], "true" if case["sparse"] else "false", case["m"], case["n"], case["k"],
            names["a_words"], len(case["a_words"]), names["b_words"], len(case["b_words"]),
            names["metadata_words"], len(case["metadata_words"]), names["expected"], len(case["expected"])))
    lines.extend(["inline constexpr Case cases[] = {", *entries, "};", "",
                  "inline constexpr std::size_t case_count = sizeof(cases) / sizeof(cases[0]);",
                  "", "} // namespace p02_wgmma", "", "#endif", ""])
    return "\n".join(lines).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="require the checked-in JSON and header to reproduce exactly")
    args = parser.parse_args(argv)
    try:
        document = fixture_document()
        outputs = {JSON_PATH: (json.dumps(document, indent=2) + "\n").encode("utf-8"),
                   HEADER_PATH: header_bytes(document)}
        for path, expected in outputs.items():
            if args.check:
                if not path.is_file() or path.read_bytes() != expected:
                    raise ValueError(f"generated fixture differs: {path.relative_to(ROOT)}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(expected)
        print(f"WGMMA fixtures {'verified' if args.check else 'written'}: {len(document['cases'])} cases, 3072 exact output words")
        return 0
    except (OSError, ValueError) as error:
        print(f"WGMMA fixture error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
