#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independently recompute frozen P04 mathematics from retained native logs.

This audit imports no implementation, fixture producer or production validator.
It checks retained observations; it does not execute or authenticate a backend.
Use the complementary source/build/dispatch audit before accepting execution.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


FIXTURE_SHA256 = "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03"
FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
FORMATS = ("fp16", "bf16")
VARIANTS = {(backend, fmt) for backend in ("simx", "rtlsim") for fmt in FORMATS}
POISONS = (0x7FC0DEAD, 0xDEADBEEF)
SHAPES = ((16, 8, 16), (8, 4, 8), (8, 4, 8))
OPERATIONS = ("hidden_matmul", "output_rows_0_7", "output_rows_8_15")
LIMIT = 16 * 1024 * 1024


def need(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, expected, label):
    need(type(value) is int and value == expected, label + " differs")


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def reject_number(value):
    raise ValueError("noninteger or nonfinite observation number: " + value[:32])


def decode_json(data, *, observations=False):
    options = {"object_pairs_hook": pairs, "parse_constant": reject_number}
    if observations:
        options["parse_float"] = reject_number
    return json.loads(data, **options)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_file(path, limit=LIMIT):
    path = path.absolute()
    need(path.resolve(strict=True) == path and path.is_file(), "nonregular or symlink input: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    need(len(data) <= limit, "input exceeds byte bound: " + str(path))
    return data


def member(root, name):
    need(type(name) is str, "packet member path is not text")
    path = PurePosixPath(name)
    need(name and not path.is_absolute() and ".." not in path.parts
         and str(path) == name, "invalid packet member path")
    return root.joinpath(*path.parts)


def identified_json(root, descriptor):
    data = read_file(member(root, descriptor["path"]))
    integer(descriptor["size_bytes"], len(data), "snapshot size")
    need(descriptor["sha256"] == digest(data), "snapshot hash differs")
    return decode_json(data)


def word_bytes(words, count):
    need(type(words) is list and len(words) == count, "incorrect packed-word count")
    need(all(type(word) is str and re.fullmatch(r"[0-9a-f]{8}", word) for word in words),
         "invalid canonical word")
    return b"".join(int(word, 16).to_bytes(4, "little") for word in words)


def hex_bytes(value, size):
    need(type(value) is str and len(value) == size * 2 and re.fullmatch(r"[0-9a-f]*", value),
         "incorrect byte string")
    return bytes.fromhex(value)


def ieee_integer(bits, fraction, exponent):
    """Decode an IEEE dyadic exactly, requiring the frozen integral domain."""
    sign = -1 if bits >> (fraction + exponent) else 1
    exp = (bits >> fraction) & ((1 << exponent) - 1)
    mantissa = bits & ((1 << fraction) - 1)
    need(exp != (1 << exponent) - 1, "nonfinite IEEE operand")
    bias = (1 << (exponent - 1)) - 1
    if exp:
        mantissa |= 1 << fraction
        power = exp - bias - fraction
    else:
        power = 1 - bias - fraction
    if power < 0:
        denominator = 1 << -power
        need(mantissa % denominator == 0, "operand is outside the exact integer domain")
        return sign * (mantissa // denominator)
    return sign * (mantissa << power)


def ieee_bits(value, fraction, exponent):
    """Encode an exactly representable integer without host float arithmetic."""
    need(type(value) is int, "encoding requires an integer")
    if value == 0:
        return 0
    sign, magnitude = int(value < 0), abs(value)
    leading = magnitude.bit_length() - 1
    remainder = magnitude - (1 << leading)
    shift = fraction - leading
    if shift < 0:
        need(remainder % (1 << -shift) == 0, "integer conversion would round")
        remainder >>= -shift
    else:
        remainder <<= shift
    encoded_exp = leading + (1 << (exponent - 1)) - 1
    need(0 < encoded_exp < (1 << exponent) - 1, "integer conversion overflows")
    return (sign << (fraction + exponent)) | (encoded_exp << fraction) | remainder


def unpack(data, fmt):
    need(len(data) % 2 == 0, "unaligned input bytes")
    fraction, exponent = (10, 5) if fmt == "fp16" else (7, 8)
    return [ieee_integer(int.from_bytes(data[i:i + 2], "little"), fraction, exponent)
            for i in range(0, len(data), 2)]


def fp32(values):
    return [format(ieee_bits(value, 23, 8), "08x") for value in values]


def bridge(values, fmt):
    fraction, exponent = (10, 5) if fmt == "fp16" else (7, 8)
    return b"".join(ieee_bits(max(0, value), fraction, exponent).to_bytes(2, "little")
                    for value in values)


def multiply(a, b, m, n, k, bound):
    need(len(a) == m * k and len(b) == k * n, "matrix extent differs")
    output, peak = [], 0
    for row in range(m):
        for column in range(n):
            total = 0
            for inner in range(k):
                total += a[row * k + inner] * b[column * k + inner]
                peak = max(peak, abs(total))
                need(abs(total) <= bound, "accumulation leaves frozen exactness bound")
            output.append(total)
    return output, peak


def fixture_oracles(path):
    data = read_file(path)
    need(digest(data) == FIXTURE_SHA256, "fixture is not the frozen P04 asset")
    fixture = decode_json(data)
    need(fixture["fixture_id"] == "p04-tiny-mlp-fixture-v1"
         and fixture["model_id"] == "p04-tiny-mlp-v1", "fixture identity differs")
    expected = [fmt + "-" + family for fmt in FORMATS for family in FAMILIES]
    need([case["id"] for case in fixture["cases"]] == expected, "fixture case inventory differs")
    oracles, peaks = {}, {"hidden": 0, "output": 0}
    for case in fixture["cases"]:
        fmt = case["format"]
        weights = fixture["weights"]["formats"][fmt]
        x = word_bytes(case["input_words"], 128)
        w1, w2 = word_bytes(weights["w1_words"], 64), word_bytes(weights["w2_words"], 16)
        a, b, c = unpack(x, fmt), unpack(w1, fmt), unpack(w2, fmt)
        need(all(-2 <= value <= 2 for value in a + b + c), "fixture input range differs")
        h, peak_h = multiply(a, b, 16, 8, 16, 64)
        packed_bridge = bridge(h, fmt)
        y, peak_y = multiply(unpack(packed_bridge, fmt), c, 16, 4, 8, 1024)
        need(fp32(h) == case["hidden_words"], "independent fixture hidden result differs")
        need(packed_bridge == word_bytes(case["bridge_words"], 64), "independent fixture bridge differs")
        need(fp32(y) == case["output_words"], "independent fixture output differs")
        oracles[case["id"]] = dict(case=case, x=x, w1=w1, w2=w2, h=h, y=y, bridge=packed_bridge)
        peaks["hidden"], peaks["output"] = max(peaks["hidden"], peak_h), max(peaks["output"], peak_y)
    return oracles, peaks


def completed(value, *, submission=False):
    for field in ("validation", "primary", "cleanup"):
        integer(value[field], 0, "execution " + field)
    need(type(value["complete"]) is bool, "completion is not boolean")
    need(submission or value["complete"], "incomplete execution or cleanup")


def observed(record, oracle, backend, revision, binding, iteration):
    case, fmt = oracle["case"], oracle["case"]["format"]
    integer(record["schema_version"], 1, "record schema")
    integer(record["iteration"], iteration, "poison iteration")
    need(record["backend"] == backend and record["source_revision"] == revision
         and record["qualification_id"] == binding and record["fixture_sha256"] == FIXTURE_SHA256
         and record["fixture_id"] == "p04-tiny-mlp-fixture-v1"
         and record["model_id"] == "p04-tiny-mlp-v1", "record identity differs")
    trace = record["trace"]
    need(trace["case_id"] == case["id"] and trace["input_dtype"] == fmt, "trace identity differs")
    integer(trace["poison"], POISONS[iteration], "model poison")
    for flag in ("hidden_valid", "bridge_attempted", "bridge_valid", "bridge_compared", "assembled",
                 "logits_valid", "logits_compared", "owner_closed"):
        need(trace[flag] is True, "missing numerical observation: " + flag)
    need(trace["result"]["terminal"] is True and trace["result"]["status"] == "success", "model did not succeed")
    completed(trace["result"]["execution"])
    completed(trace["owner_cleanup"])
    integer(trace["bridge_status"], 0, "bridge status")
    for field, count in (("bridge_checked_words", 64), ("bridge_mismatches", 0),
                         ("output_checked_words", 64), ("output_mismatches", 0)):
        integer(trace[field], count, field)
    stages = trace["native"]
    need(type(stages) is list and len(stages) == 3, "native graph is incomplete")
    h = None
    packed_bridge = None
    actual_blocks = []
    h2d = d2h = 0
    for index, (stage, (m, n, k)) in enumerate(zip(stages, SHAPES)):
        need(stage["operation_id"] == OPERATIONS[index], "native stage order differs")
        for field, count in (("sequence", index), ("row_begin", 8 if index == 2 else 0),
                             ("row_end", 8 if index == 1 else 16), ("a_size", m * k * 2),
                             ("b_size", k * n * 2), ("output_count", m * n),
                             ("checked_words", m * n), ("mismatches", 0)):
            integer(stage[field], count, "stage " + field)
        for flag in ("submitted", "waited", "trace_valid", "output_valid", "compared", "closed"):
            need(stage[flag] is True, "native stage observation missing: " + flag)
        completed(stage["submission"], submission=True)
        completed(stage["completion"])
        completed(stage["cleanup"])
        a, b = hex_bytes(stage["a_bytes"], m * k * 2), hex_bytes(stage["b_bytes"], k * n * 2)
        expected_a = oracle["x"] if index == 0 else packed_bridge[(index - 1) * 128:index * 128]
        need(a == expected_a and b == oracle["w1" if index == 0 else "w2"], "actual input lineage differs")
        values, _ = multiply(unpack(a, fmt), unpack(b, fmt), m, n, k, 64 if index == 0 else 1024)
        words = fp32(values)
        need(word_bytes(stage["output_words"], m * n) == word_bytes(words, m * n), "native output disagrees with independent dot products")
        if index == 0:
            h = [ieee_integer(int(word, 16), 23, 8) for word in stage["output_words"]]
            need(h == oracle["h"] and trace["hidden_words"] == words, "actual hidden result differs")
            packed_bridge = bridge(h, fmt)
            need(hex_bytes(trace["bridge_bytes"], 256) == packed_bridge == oracle["bridge"]
                 and word_bytes(trace["bridge_words"], 64) == packed_bridge, "actual hidden-to-bridge conversion differs")
        else:
            need(values == oracle["y"][(index - 1) * 32:index * 32], "output row slice differs")
            actual_blocks.extend(stage["output_words"])
        dispatch = stage["dispatch"]
        need(dispatch["input_dtype"] == fmt and dispatch["qualification_id"] == binding, "dispatch identity differs")
        for field, count in (("m", m), ("n", n), ("k", k), ("poison", POISONS[iteration]),
                             ("a_bytes", len(a)), ("b_bytes", len(b)), ("d_bytes", m * n * 4),
                             ("writes_enqueued", 3), ("launches_enqueued", 1), ("reads_enqueued", 1)):
            integer(dispatch[field], count, "dispatch " + field)
        h2d += len(a) + len(b) + m * n * 4
        d2h += m * n * 4
    need(trace["output_words"] == actual_blocks == fp32(oracle["y"]), "assembled actual output differs")
    return h2d, d2h


def raw_observations(data):
    text = data.decode("utf-8")
    need(not any((ord(ch) < 32 and ch not in "\t\r\n") or 127 <= ord(ch) <= 159 for ch in text), "log contains control characters")
    lines = text.splitlines()
    need(lines and lines[-1] == "PASSED!" and lines.count("PASSED!") == 1, "log lacks one final success marker")
    tokens = {token.upper() for token in re.findall(r"[A-Za-z_]+", text)}
    need(not tokens & {"FAIL", "FAILED", "ERROR", "FATAL", "ABORTED", "MISMATCH"}, "log contains failure diagnostics")
    need(len(re.findall(r"\bPASSED\b", text, re.IGNORECASE)) == 1, "log has an ambiguous success marker")
    rows = []
    for line in lines:
        if "p04_" in line.lower():
            need(line.startswith("P04_RESULT "), "log has a malformed or diagnostic model marker")
            need(len(line.encode("utf-8")) <= 256 * 1024, "model record exceeds byte bound")
            rows.append(decode_json(line[len("P04_RESULT "):], observations=True))
    need(len(rows) == 2, "log does not contain two poison observations")
    return rows


def audit_packets(paths, oracles, allow_partial):
    seen, identities, profiles, packets = set(), set(), set(), []
    total_cases = total_runs = total_h2d = total_d2h = 0
    for argument in paths:
        path = argument.absolute()
        report_path = path / "report.json" if path.is_dir() else path
        need(report_path.name == "report.json", "packet must identify report.json")
        root = report_path.parent
        report_bytes = read_file(report_path)
        report = decode_json(report_bytes)
        integer(report["schema_version"], 1, "packet schema")
        need(report["contract_id"] == "p04-managed-model-execution-v1"
             and report["state"] == "finished" and report["outcome"] == "pass"
             and report["development"] is False and report["source_stable"] is True,
             "packet is failed, unfinished, development or unstable")
        need(report["acceptance_claimed"] is False and report["phase_complete"] is False,
             "runner packet cannot grant phase acceptance")
        integer(report["iterations"], 2, "packet repetitions")
        need(report["fixture_sha256"] == FIXTURE_SHA256, "packet fixture differs")
        source = identified_json(root, report["source_before"])
        need(canonical(source) == canonical(identified_json(root, report["source_after"])), "source snapshots differ")
        checkout = source["checkout"]
        need(checkout["dirty"] is False and checkout["blockers"] == [], "source was not clean")
        revision, tree = checkout["revision"], checkout["tree"]
        need(all(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) for value in (revision, tree)), "invalid source identity")
        identities.add((revision, tree))
        commands = {}
        for command in report["commands"]:
            need(command["id"] not in commands, "duplicate command ID")
            need(command["outcome"] == "pass" and command["cleanup_complete"] is True
                 and command["process_started"] is True, "packet includes an unsuccessful command")
            integer(command["exit_code"], 0, "command exit")
            commands[command["id"]] = command
        used_commands, local_cases, local_runs, local_h2d, local_d2h, local_ids = set(), 0, 0, 0, 0, set()
        local_variants = set()
        need(type(report["variants"]) is list and report["variants"], "empty variant inventory")
        for variant in report["variants"]:
            key = (variant["backend"], variant["format"])
            need(key in VARIANTS and key not in seen and variant["outcome"] == "pass", "duplicate, unsupported or failed variant")
            seen.add(key)
            local_variants.add(key)
            backend, fmt = key
            need(variant["id"] == backend + "-" + fmt, "variant label differs")
            binding = identified_json(root, variant["binding"])
            binding_id = digest(canonical(binding).encode())
            need(variant["qualification_id"] == binding_id and binding["source"] == checkout
                 and binding["backend"] == backend and binding["format"] == fmt
                 and binding["fixture_sha256"] == FIXTURE_SHA256
                 and binding["model_id"] == "p04-tiny-mlp-v1", "variant binding differs")
            profile = binding["profile_sha256"]
            need(type(profile) is str and re.fullmatch(r"[0-9a-f]{64}", profile), "invalid profile identity")
            profiles.add(profile)
            expected_ids = [fmt + "-" + family for family in FAMILIES]
            need([case["id"] for case in variant["cases"]] == expected_ids, "variant case inventory differs")
            local_ids.update(expected_ids)
            for case in variant["cases"]:
                need(case["outcome"] == "pass", "failed case cannot contribute observations")
                command_id = variant["id"] + "-" + case["id"]
                command = commands[command_id]
                argv = command["argv"]
                need(type(argv) is list and len(argv) == 13 and all(type(value) is str for value in argv), "invalid native invocation")
                options = dict(zip(argv[1::2], argv[2::2]))
                need(len(options) == 6 and set(options) == {"--case", "--iterations", "--module", "--qualification-id", "--backend", "--source-revision"}, "ambiguous native arguments")
                need(options["--case"] == case["id"] and options["--iterations"] == "2"
                     and options["--backend"] == backend and options["--source-revision"] == revision
                     and options["--qualification-id"] == binding_id, "native invocation identity differs")
                log = read_file(member(root, command["log"]))
                integer(command["log_size_bytes"], len(log), "native log size")
                need(command["log_sha256"] == digest(log), "native log hash differs")
                rows = raw_observations(log)
                need(canonical(rows) == canonical(case["observations"]), "raw and reported observations differ")
                for iteration, record in enumerate(rows):
                    h2d, d2h = observed(record, oracles[case["id"]], backend, revision, binding_id, iteration)
                    local_h2d += h2d
                    local_d2h += d2h
                    local_runs += 1
                local_cases += 1
                used_commands.add(command_id)
        need(used_commands == {name for name, command in commands.items() if "--case" in command["argv"]}, "unaccounted native case command")
        need(report["case_ids"] == [key for key in oracles if key in local_ids], "packet selected-case inventory differs")
        need(report["full_matrix_requested"] is (local_variants == VARIANTS),
             "packet full-matrix declaration differs from its inventory")
        expected_counts = {"completed_case_executions": local_cases, "completed_model_runs": local_runs,
                           "completed_launches": local_runs * 3, "tensor_h2d_bytes": local_h2d,
                           "tensor_d2h_bytes": local_d2h}
        for name, expected in expected_counts.items():
            integer(report[name], expected, "reported " + name)
        for name, per_run in (("hidden_words", 128), ("bridge_words", 64), ("output_block_words", 64), ("assembled_output_words", 64)):
            integer(report["comparison_counts"][name], local_runs * per_run, "reported comparison " + name)
        total_cases += local_cases
        total_runs += local_runs
        total_h2d += local_h2d
        total_d2h += local_d2h
        packets.append({"report": str(report_path), "sha256": digest(report_bytes), **expected_counts})
    need(len(identities) == 1 and len(profiles) == 1, "packets mix source or profile identities")
    need(seen and (allow_partial or seen == VARIANTS), "complete four-variant matrix is required")
    revision, tree = next(iter(identities))
    return {"source_revision": revision, "source_tree": tree, "profile_sha256": next(iter(profiles)),
            "full_matrix_verified": seen == VARIANTS, "variants": sorted("-".join(key) for key in seen),
            "packet_count": len(packets), "packets": packets, "case_backend_pairs": total_cases,
            "model_runs": total_runs, "matmul_launches": total_runs * 3,
            "comparison_counts": {"hidden_words": total_runs * 128, "bridge_words": total_runs * 64,
                                  "output_block_words": total_runs * 64, "assembled_output_words": total_runs * 64},
            "tensor_h2d_bytes": total_h2d, "tensor_d2h_bytes": total_d2h}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", default=[])
    parser.add_argument("--allow-partial", "--selected-scope", action="store_true", dest="allow_partial")
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"schema_version": 1, "audit": "independent-p04-integer-numerics-v1",
              "outcome": "fail", "fixture_sha256": FIXTURE_SHA256,
              "execution_performed_by_audit": False, "phase_acceptance": False,
              "limitations": ["An internally consistent packet is not authentication of native execution.",
                              "Source/build provenance, ABI, profiling and resource review remain separate obligations."]}
    try:
        need(bool(args.packet) != args.fixture_only, "choose packet audit or --fixture-only")
        oracles, peaks = fixture_oracles(args.fixture)
        result.update(scope="frozen_fixture_math" if args.fixture_only else "retained_packet_numerics",
                      fixture_cases=len(oracles), accumulation_prefix_peaks=peaks)
        if args.fixture_only:
            result.update(full_matrix_verified=False, fixture_comparison_counts={
                "hidden_words": 1280, "bridge_words": 640, "output_words": 640})
        else:
            result.update(audit_packets(args.packet, oracles, args.allow_partial))
        result["outcome"] = "pass"
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        result["reason"] = str(error)
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
