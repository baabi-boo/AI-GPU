#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strictly load and export the frozen ordinary-WMMA fixture inventory.

The 20 existing layout matrices and 68 numerical matrices remain separate
source documents. Every load checks bounded, unambiguous JSON, the matrix
geometry and word counts, unique IDs, and byte-for-byte reproduction by the
independent producers. --write emits only the combined C++ header; --check
detects source-data or header drift without changing either source document.

load_cases(root=ROOT) returns a list of dictionaries retaining source metadata
and adding top-level m/n/k. a_words, b_words and expected stay lowercase hex8
strings. The order is the 20 layout cases followed by the 68 numerical cases.
These checks and exports do not constitute GPU execution evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import stat
import sys

import p02_fixture_oracle as leaf
import p02_layout_fixture_oracle as layout
import p02_wmma_numerical_fixture_oracle as numerical


ROOT = Path(__file__).resolve().parents[2]
LAYOUT_JSON = Path("ci/project/fixtures/p02_layout_v1.json")
NUMERICAL_JSON = Path("ci/project/fixtures/p02_wmma_numerical_v1.json")
HEADER_PATH = Path("tests/regression/sgemm_tcu/p02_fixtures.h")
MAX_JSON_BYTES = 1024 * 1024
MAX_HEADER_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_NUMBER_CHARS = 64
MAX_DIMENSION = 64
MAX_WORDS = 4096
CASE_COUNT = 88
FORMATS = ("fp16", "bf16")
WORD = re.compile(r"[0-9a-f]{8}\Z")
CASE_ID = re.compile(r"[a-z][a-z0-9_-]{0,127}\Z")


class FixtureError(ValueError):
    """The source fixture inventory or its exported representation is invalid."""


def _read_bounded(path: Path, maximum: int) -> bytes:
    """Read one bounded regular file, rejecting final symlinks and FIFOs."""
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise FixtureError(f"{path}: expected a regular file of at most {maximum} bytes")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise FixtureError(f"{path}: file exceeds the byte limit")
        return data
    except OSError as error:
        raise FixtureError(f"{path}: cannot read fixture input: {error.strerror}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise FixtureError("duplicate JSON field: " + key)
        result[key] = value
    return result


def _json_integer(token: str) -> int:
    if len(token) > MAX_NUMBER_CHARS:
        raise FixtureError("JSON integer exceeds the character limit")
    return int(token)


def _reject_number(token: str) -> None:
    raise FixtureError("floating-point and nonfinite JSON numbers are forbidden: " + token)


def decode_json(data: bytes) -> dict:
    """Decode bounded UTF-8 objects; reject duplicate keys and numeric ambiguity."""
    if type(data) is not bytes or len(data) > MAX_JSON_BYTES:
        raise FixtureError("fixture JSON must be bounded UTF-8 bytes")
    try:
        text = data.decode("utf-8", errors="strict")
        depth = 0
        quoted = escaped = False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                depth += 1
                if depth > MAX_JSON_DEPTH:
                    raise FixtureError("fixture JSON exceeds the nesting limit")
            elif character in "]}":
                depth -= 1
        document = json.loads(text, object_pairs_hook=_unique_fields,
                              parse_int=_json_integer, parse_float=_reject_number,
                              parse_constant=_reject_number)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise FixtureError("invalid fixture JSON: " + str(error)) from error
    if type(document) is not dict:
        raise FixtureError("fixture JSON root must be an object")
    return document


def _words(value: object, count: int, label: str) -> None:
    if (type(value) is not list or count > MAX_WORDS or len(value) != count
            or any(type(word) is not str or WORD.fullmatch(word) is None for word in value)):
        raise FixtureError(f"{label} must contain exactly {count} lowercase hex8 words")


def _integer_mapping(value: object, expected: dict[str, int], label: str) -> None:
    if (type(value) is not dict or set(value) != set(expected)
            or any(type(value[key]) is not int or value[key] != wanted
                   for key, wanted in expected.items())):
        raise FixtureError(label + " differs from the declared compact matrix geometry")


def validate_case(case: object) -> dict:
    """Validate compact matrix fields and return a normalized source-case copy."""
    if type(case) is not dict:
        raise FixtureError("each fixture case must be an object")
    case_id = case.get("id")
    if type(case_id) is not str or CASE_ID.fullmatch(case_id) is None:
        raise FixtureError("case ID must be a bounded lowercase identifier")
    if case.get("format") not in FORMATS:
        raise FixtureError(case_id + ": only FP16/BF16 input formats are supported")
    if type(case.get("family")) is not str or not 0 < len(case["family"]) <= 64:
        raise FixtureError(case_id + ": a bounded fixture family is required")
    dimensions = case.get("dimensions")
    if type(dimensions) is not dict or set(dimensions) != {"m", "n", "k"}:
        raise FixtureError(case_id + ": dimensions must contain exactly m, n and k")
    for key, multiple in (("m", 8), ("n", 4), ("k", 8)):
        value = dimensions[key]
        if type(value) is not int or not 0 < value <= MAX_DIMENSION or value % multiple:
            raise FixtureError(f"{case_id}: {key} must be a bounded positive multiple of {multiple}")
        if key in case and (type(case[key]) is not int or case[key] != value):
            raise FixtureError(case_id + ": normalized dimensions disagree with source dimensions")
    m, n, k = (dimensions[key] for key in ("m", "n", "k"))
    _integer_mapping(case.get("leading_dimensions"), {"lda": k, "ldb": k, "ldc": n},
                     case_id + ": leading dimensions")
    _integer_mapping(case.get("tile_iterations"), {"m": m // 8, "n": n // 4, "k": k // 8},
                     case_id + ": tile iterations")
    if type(case.get("fedp_steps_per_output")) is not int or case["fedp_steps_per_output"] != k // 4:
        raise FixtureError(case_id + ": FEDP step count differs from K/4")
    _words(case.get("a_words"), m * k // 2, case_id + ": A")
    _words(case.get("b_words"), k * n // 2, case_id + ": B")
    _words(case.get("expected"), m * n, case_id + ": expected output")
    return {**case, "m": m, "n": n, "k": k}


def validate_document(document: dict, expected_document: dict) -> list[dict]:
    """Check source schema, geometry, inventory and numerical provenance fields."""
    if type(document) is not dict or set(document) != set(expected_document):
        raise FixtureError("fixture document fields differ from its producer schema")
    for key in ("schema_version", "contract_version", "case_count"):
        if type(document.get(key)) is not int or document[key] != expected_document[key]:
            raise FixtureError("fixture " + key + " differs from the producer contract")
    if document.get("contract_id") != expected_document["contract_id"]:
        raise FixtureError("fixture contract ID differs from the producer contract")
    if document.get("gpu_execution_claimed") is not False:
        raise FixtureError("source fixtures cannot claim GPU execution")
    if document.get("producer") != expected_document["producer"]:
        raise FixtureError("fixture producer provenance differs")
    if document.get("geometry") != layout.GEOMETRY:
        raise FixtureError("fixture geometry differs from the P02 ordinary-WMMA profile")
    if (document.get("application") != expected_document["application"]
            or document.get("packing") != expected_document["packing"]):
        raise FixtureError("fixture application or packing contract differs")
    raw_cases = document.get("cases")
    if type(raw_cases) is not list or len(raw_cases) != document["case_count"]:
        raise FixtureError("fixture case inventory is empty or has the wrong count")
    cases = [validate_case(case) for case in raw_cases]
    if len({case["id"] for case in cases}) != len(cases):
        raise FixtureError("fixture case IDs must be unique")
    expected_counts = expected_document["case_count_by_format"]
    _integer_mapping(document.get("case_count_by_format"), expected_counts, "format counts")
    if Counter(case["format"] for case in cases) != expected_counts:
        raise FixtureError("fixture format inventory differs from the producer contract")
    if document["contract_id"] == numerical.CONTRACT_ID:
        for case in cases:
            _words(case.get("intermediate_expected"), case["k"] // 4,
                   case["id"] + ": intermediate expected results")
            ids = case.get("source_leaf_ids")
            if (type(ids) is not list or len(ids) != 1
                    or type(ids[0]) is not str or CASE_ID.fullmatch(ids[0]) is None):
                raise FixtureError(case["id"] + ": one frozen source leaf ID is required")
            trace = case.get("fedp_trace")
            if type(trace) is not list or len(trace) != case["k"] // 4:
                raise FixtureError(case["id"] + ": FEDP trace length differs from K/4")
            accumulator = "00000000"
            for index, step in enumerate(trace):
                if (type(step) is not dict or type(step.get("k_begin")) is not int
                        or step["k_begin"] != index * 4 or step.get("input_c") != accumulator
                        or step.get("expected") != case["intermediate_expected"][index]):
                    raise FixtureError(case["id"] + ": FEDP trace handoff differs")
                _words(step.get("a"), 2, case["id"] + ": trace A")
                _words(step.get("b"), 2, case["id"] + ": trace B")
                accumulator = step["expected"]
            if case["expected"] != [accumulator] * (case["m"] * case["n"]):
                raise FixtureError(case["id"] + ": repeated numerical outputs differ from the trace")
    return cases


def _load_produced_document(path: Path, producer) -> list[dict]:
    data = _read_bounded(path, MAX_JSON_BYTES)
    document = decode_json(data)
    expected = producer.fixture_document()
    cases = validate_document(document, expected)
    if data != producer.render_json(expected):
        raise FixtureError(f"{path}: frozen fixture differs byte-for-byte from its independent producer")
    return cases


def load_cases(root: Path = ROOT, *, layout_path: Path | None = None,
               numerical_path: Path | None = None) -> list[dict]:
    """Return 88 strictly validated cases with m/n/k normalized to top level.

    root selects an existing source tree, never an output location. Optional
    document paths support explicit validation of candidate copies; neither
    option relaxes canonical producer reproduction. The frozen leaf JSON is
    checked too because it supplies the numerical matrices' source vectors.
    """
    root = Path(root)
    leaf_path = root / leaf.JSON_PATH
    leaf_data = _read_bounded(leaf_path, MAX_JSON_BYTES)
    decode_json(leaf_data)
    if leaf_data != leaf.render_json(leaf.fixture_document()):
        raise FixtureError(f"{leaf_path}: frozen leaf fixture differs byte-for-byte from its producer")
    cases = _load_produced_document(
        Path(layout_path) if layout_path is not None else root / LAYOUT_JSON, layout)
    cases.extend(_load_produced_document(
        Path(numerical_path) if numerical_path is not None else root / NUMERICAL_JSON, numerical))
    if (len(cases) != CASE_COUNT or len({case["id"] for case in cases}) != CASE_COUNT
            or Counter(case["format"] for case in cases) != {"fp16": 44, "bf16": 44}):
        raise FixtureError("combined inventory must have 88 distinct cases, 44 per format")
    return cases


def render_header(cases: list[dict]) -> bytes:
    """Render raw packed inputs and exact expected bits without conversions."""
    if type(cases) is not list or len(cases) != CASE_COUNT:
        raise FixtureError("the C++ exporter requires all 88 source fixtures")
    cases = [validate_case(case) for case in cases]
    if (len({case["id"] for case in cases}) != CASE_COUNT
            or Counter(case["format"] for case in cases) != {"fp16": 44, "bf16": 44}):
        raise FixtureError("the C++ exporter requires distinct IDs and both complete format inventories")
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// Generated by ci/project/p02_wmma_fixtures.py; do not edit.",
        "// 20 layout and 68 numerical source fixtures; no GPU execution claim.",
        "", "#pragma once", "", "#include <cstddef>", "#include <cstdint>",
        "", "namespace p02 {", "", "using std::size_t;", "using std::uint32_t;", "",
        "struct Fixture {", "  const char* id;", "  const char* format;",
        "  uint32_t m, n, k;", "  const uint32_t* a_words;", "  size_t a_count;",
        "  const uint32_t* b_words;", "  size_t b_count;",
        "  const uint32_t* expected;", "  size_t output_count;", "};", "",
    ]
    for index, case in enumerate(cases):
        lines.append("// " + case["id"])
        for name, field in (("A", "a_words"), ("B", "b_words"), ("Expected", "expected")):
            lines.append(f"inline constexpr uint32_t k{name}{index}[] = {{")
            words = case[field]
            for start in range(0, len(words), 8):
                lines.append("  " + ", ".join(f"0x{word}u" for word in words[start:start + 8]) + ",")
            lines.extend(["};", ""])
    lines.append("inline constexpr Fixture kFixtures[] = {")
    for index, case in enumerate(cases):
        lines.extend([
            f"  {{\"{case['id']}\", \"{case['format']}\", {case['m']}u, {case['n']}u, {case['k']}u,",
            f"   kA{index}, {len(case['a_words'])}u, kB{index}, {len(case['b_words'])}u,",
            f"   kExpected{index}, {len(case['expected'])}u}},",
        ])
    lines.extend(["};", "", "inline constexpr size_t kFixtureCount = sizeof(kFixtures) / sizeof(kFixtures[0]);",
                  "", "} // namespace p02", ""])
    data = "\n".join(lines).encode("utf-8")
    if len(data) > MAX_HEADER_BYTES:
        raise FixtureError("generated C++ header exceeds the byte limit")
    return data


def generated_files(root: Path = ROOT) -> dict[Path, bytes]:
    return {Path(root) / HEADER_PATH: render_header(load_cases(root))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="export the checked inventory to its C++ header")
    mode.add_argument("--check", action="store_true", help="check source-data and generated-header drift")
    args = parser.parse_args(argv)
    try:
        for path, data in generated_files().items():
            if args.write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            elif _read_bounded(path, MAX_HEADER_BYTES) != data:
                raise FixtureError(f"{path}: generated header differs byte-for-byte")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(("Exported" if args.write else "Verified")
          + " 88 WMMA source fixtures and their C++ header (44 per format); no GPU execution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
