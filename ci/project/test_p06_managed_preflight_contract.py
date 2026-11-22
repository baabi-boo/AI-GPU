# SPDX-License-Identifier: Apache-2.0
"""Independent host checks of the fixed managed preflight input boundary."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_contract as contract
import p06_warm_contract as warm


ROOT = Path(__file__).resolve().parents[2]
WARM_SHA256 = "893d85401b1d5f7757d82cb7c743a89b36264fe19c7d08c239b7f216b7a8cbbd"
CLAIMS = (
    "qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
    "acceptance_claimed", "phase_acceptance", "performance_acceptance",
)
GAPS = [
    "all_40_component_lifetime_and_pending_balance",
    "dependency_source_to_loaded_binary_provenance",
    "independent_complete_counter_qualification",
]
LIBRARIES = (
    "libramulator-vortex.so", "libramulator.so", "libsimx.so",
    "libvortex-simx.so", "libvortex.so",
)


def replace_at(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


class ManagedPreflightContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = contract.load_contract(ROOT)
        cls.warm = warm.load_contract(ROOT)

    def test_exact_four_processes_keep_original_warmup_sample_identity(self):
        expected = [
            {"id": f"preflight-simx-{fmt}-{policy}",
             "sample_id": f"warm-simx-{fmt}-pair0-{policy}", "backend": "simx",
             "format": fmt, "policy": policy, "pair_index": 0, "phase": "warmup"}
            for fmt in ("fp16", "bf16")
            for policy in ("per_operation", "reusable_single_tile")
        ]
        self.assertEqual(contract.process_plan(self.document), expected)
        historical = {row["id"]: row for row in warm.process_plan(self.warm)}
        self.assertEqual(len(historical), 24)
        for row in expected:
            self.assertEqual({key: value for key, value in row.items()
                              if key not in ("id", "sample_id")},
                             {key: value for key, value in historical[row["sample_id"]].items()
                              if key != "id"})

    def test_counts_derive_from_complete_fixture_geometry_and_four_snapshots(self):
        cases = contract.select_cases(self.document, ROOT)
        self.assertEqual([case["id"] for case in cases],
                         ["fp16-single-dense_boundaries", "bf16-single-dense_boundaries"])
        for case in cases:
            self.assertEqual((case["m"], case["n"], case["k"]), (8, 4, 8))
            self.assertEqual(len(case["expected"]), 32)
        self.assertEqual(self.document["per_process"], {
            "operations": 1 + 32, "launches": 1 + 32, "checked_words": 33 * 8 * 4,
            "snapshots": 4, "available_queries": 4 * 33, "half_replies": 4 * 33 * 2,
            "cache_flush_reads": 33, "dcr_reads": 264 + 33,
            "unavailable_rows": 4 * 12,
        })
        self.assertEqual(self.document["complete_matrix"], {
            "processes": 4, "launches": 132, "checked_words": 4224, "snapshots": 16,
            "available_queries": 528, "half_replies": 1056, "unavailable_rows": 192,
            "cache_flush_reads": 132, "dcr_reads": 1188,
        })
        for key, value in self.document["complete_matrix"].items():
            if key != "processes":
                self.assertEqual(value, 4 * self.document["per_process"][key])

    def test_historical_manifest_bytes_are_frozen(self):
        self.assertEqual(hashlib.sha256((ROOT / warm.MANIFEST_PATH).read_bytes()).hexdigest(),
                         WARM_SHA256)
        self.assertEqual(self.document["warm_contract"], {
            "path": "ci/project/p06_warm_contract.json", "contract_id": "p06-warm-workspace-v1",
            "sha256": WARM_SHA256,
        })

    def test_semantically_identical_reformatted_warm_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="managed-contract-") as temporary:
            source = Path(temporary)
            names = [row["path"] for row in self.warm["source_inputs"]] + [warm.MANIFEST_PATH]
            for name in names:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            manifest = source / warm.MANIFEST_PATH
            manifest.write_bytes(manifest.read_bytes() + b"\n")
            self.assertEqual(warm.load_contract(source), self.warm)
            with self.assertRaisesRegex(contract.ContractError, "manifest bytes changed"):
                contract.load_contract(source)

    def test_substituted_warm_helper_location_is_rejected(self):
        with mock.patch.object(warm, "__file__", "/untrusted/p06_warm_contract.py"):
            with self.assertRaisesRegex(contract.ContractError, "trusted repository"):
                contract.load_contract(ROOT)

    def test_scope_and_unresolved_obligations_never_claim_acceptance(self):
        self.assertEqual(self.document["contract_id"], "p06-managed-counter-preflight-v1")
        self.assertEqual(self.document["scope"], "seed-free-managed-counter-preflight")
        self.assertEqual(self.document["unresolved_obligations"], GAPS)
        self.assertEqual(self.document["statistical_role"],
                         "preflight_only_no_performance_sampling_or_admission")
        self.assertEqual(self.document["failed_process_policy"],
                         "retain_and_fail_entire_attempt_no_replacements")
        for name in CLAIMS:
            self.assertIs(self.document[name], False)
            self.assertIn(name, self.document["witness_fields"])

    def test_checked_production_measurement_keeps_complete_original_caller(self):
        self.assertEqual(self.document["guard"], {"macro": "SIMX_CHECKED_COUNTERS", "value": "1", "bits": 64})
        self.assertEqual(self.document["profile"], self.warm["profile"])
        self.assertEqual(self.document["profile"]["simulation_mode"], "timing")
        self.assertEqual(self.document["backends"], ["simx"])
        self.assertTrue({
            "tests/regression/ai_warm_workspace/main.cpp",
            "tests/regression/ai_warm_workspace/observer.cpp",
            "tests/regression/ai_bench_common/counters.h", "sw/kernel/ai/matmul.cpp",
        } <= set(self.document["required_measurement_sources"]))
        self.assertEqual(self.document["forbidden_source_roots"],
                         ["tests/unittest/checked_counters", "tests/unittest/mpm_transport"])
        self.assertTrue({"counter_test::", "seed_component", "clear_components"}
                        <= set(self.document["forbidden_symbols"]))
        self.assertEqual(self.document["record_placement"],
                         "one_witness_after_the_unchanged_warm_success_line")

    def test_exact_counter_inventory_retains_unavailable_l2_and_l3_rows(self):
        inventory = contract.counter_inventory(self.document, ROOT)
        self.assertEqual((len(inventory["enabled"]), len(inventory["unavailable"])), (33, 12))
        expected_unavailable = {f"{cache}_{name}" for cache in ("l2cache", "l3cache")
                                for name in ("reads", "writes", "miss_r", "miss_w", "evicts", "mshr_st")}
        self.assertEqual({row["name"] for row in inventory["unavailable"]}, expected_unavailable)
        rows = inventory["enabled"] + inventory["unavailable"]
        self.assertEqual({row["name"]: row for row in rows},
                         {row["name"]: row for row in self.warm["counters"]})
        self.assertEqual(len({(row["mpm_class"], row["csr"], row["core_id"]) for row in rows}), 45)
        self.assertEqual(self.document["snapshot_names"],
                         ["after_open", "after_prime", "after_batch", "before_release"])
        self.assertEqual(self.document["halves_per_snapshot"], 66)

    def test_fixed_budget_distinguishes_two_build_jobs_and_one_simulation_worker(self):
        self.assertEqual(self.document["simulation_workers"], 1)
        self.assertEqual(self.document["budget"], {
            "max_rss_bytes": 4 * 1024**3, "min_free_bytes": 15 * 1024**3,
            "max_log_bytes": 16 * 1024**2, "jobs": 2, "threads": 1,
            "timeouts_seconds": {"configure": 120, "build": 1800, "run": 180},
            "hosted_job_minutes": 90,
        })

    def test_returned_plans_fixtures_and_inventory_are_independent_copies(self):
        plan = contract.process_plan(self.document)
        plan[0]["policy"] = "changed"
        cases = contract.select_cases(self.document)
        cases[0]["expected"][0] = "changed"
        inventory = contract.counter_inventory(self.document)
        inventory["enabled"][0]["name"] = "changed"
        document = contract.load_contract()
        document["budget"]["timeouts_seconds"]["run"] = 1
        self.assertEqual(contract.load_contract(), self.document)
        self.assertEqual(contract.process_plan(self.document)[0]["policy"], "per_operation")
        self.assertNotEqual(contract.select_cases(self.document)[0]["expected"][0], "changed")
        self.assertEqual(contract.counter_inventory(self.document)["enabled"][0]["name"], "cycles")

    def test_missing_and_unknown_contract_fields_fail_at_nested_boundaries(self):
        for path in ((), ("warm_contract",), ("profile",), ("guard",), ("processes", 0),
                     ("per_process",), ("complete_matrix",), ("budget", "timeouts_seconds")):
            for mutation in ("extra", "missing"):
                with self.subTest(path=path, mutation=mutation):
                    changed = deepcopy(self.document)
                    target = changed
                    for key in path:
                        target = target[key]
                    if mutation == "extra":
                        target["unreviewed_override"] = False
                    else:
                        target.pop(next(iter(target)))
                    with self.assertRaises(contract.ContractError):
                        contract.validate_contract(changed)

    def test_boolean_integer_float_and_container_type_confusion_is_rejected(self):
        mutations = [
            (("schema_version",), True), (("schema_version",), 1.0),
            (("simulation_workers",), True), (("simulation_workers",), "1"),
            (("processes", 0, "pair_index"), False), (("guard", "bits"), "64"),
            (("budget", "threads"), True), (("formats",), ("fp16", "bf16")),
            (("qualified",), 0), (("qualified",), None),
            (("complete_matrix", "processes"), 4.0), (("shape", 0), "8"),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                changed = deepcopy(self.document)
                replace_at(changed, path, value)
                with self.assertRaises(contract.ContractError):
                    contract.validate_contract(changed)

    def test_process_population_order_scope_and_reference_ids_cannot_change(self):
        processes = self.document["processes"]
        alternatives = [processes[:-1], processes + [processes[0]], list(reversed(processes)),
                        [processes[0]] * 4]
        for key, value in (("id", "warm-simx-fp16-pair0-per_operation"),
                           ("sample_id", "warm-simx-fp16-pair1-per_operation"),
                           ("backend", "rtlsim"), ("format", "fp32"), ("policy", "cached"),
                           ("pair_index", 1), ("phase", "measured")):
            changed = deepcopy(processes)
            changed[0][key] = value
            alternatives.append(changed)
        for index, value in enumerate(alternatives):
            with self.subTest(alternative=index):
                changed = deepcopy(self.document)
                changed["processes"] = value
                with self.assertRaises(contract.ContractError):
                    contract.process_plan(changed)

    def test_every_claim_requires_explicit_false_and_every_gap_remains_visible(self):
        claims = dict.fromkeys(CLAIMS, False)
        contract.false_claims(claims)
        for name in CLAIMS:
            for value in (True, 0, 1, "false", None):
                with self.subTest(claim=name, value=value):
                    with self.assertRaises(contract.ContractError):
                        contract.false_claims(dict(claims, **{name: value}))
            with self.subTest(missing=name), self.assertRaises(contract.ContractError):
                contract.false_claims({key: value for key, value in claims.items() if key != name})
        for gaps in ([], GAPS[:-1], list(reversed(GAPS)), GAPS + ["closed"]):
            with self.subTest(gaps=gaps):
                changed = deepcopy(self.document)
                changed["unresolved_obligations"] = gaps
                with self.assertRaises(contract.ContractError):
                    contract.validate_contract(changed)

    def test_execution_binding_and_process_identity_are_exact(self):
        for fmt in ("fp16", "bf16"):
            for policy in ("per_operation", "reusable_single_tile"):
                self.assertEqual(contract.process_identity(fmt, policy, "ab" * 32), {
                    "schema_version": 1, "contract_id": "p06-managed-counter-preflight-v1",
                    "process_id": f"preflight-simx-{fmt}-{policy}",
                    "sample_id": f"warm-simx-{fmt}-pair0-{policy}",
                    "execution_binding_sha256": "ab" * 32, "format": fmt, "policy": policy,
                })
        for args in (("fp32", "per_operation", "ab" * 32),
                     ("fp16", "resident", "ab" * 32), (True, "per_operation", "ab" * 32),
                     ("fp16", "per_operation", "AB" * 32), ("fp16", "per_operation", "0" * 63)):
            with self.subTest(args=args), self.assertRaises(contract.ContractError):
                contract.process_identity(*args)


class ManagedPreflightJSONTests(unittest.TestCase):
    def test_valid_unicode_escapes_and_signed_storage_boundaries(self):
        expected = {"low": -(1 << 63), "high": (1 << 64) - 1,
                    "escaped": 'brackets [] {} and quote " and slash \\', "unicode": "μ🙂"}
        self.assertEqual(contract.decode_record(json.dumps(expected).encode()), expected)
        self.assertEqual(contract.decode_record(json.dumps(expected, ensure_ascii=False).encode()), expected)

    def test_duplicate_fields_are_rejected_at_every_json_nesting_level(self):
        for body in (b'{"x":1,"x":1}', b'{"outer":{"x":1,"x":2}}',
                     b'{"outer":[{"x":1,"x":2}]}', b'{"x":1,"\\u0078":2}'):
            with self.subTest(body=body), self.assertRaisesRegex(contract.ContractError, "duplicate"):
                contract.decode_record(body)

    def test_floats_exponents_negative_zero_floats_and_nonfinite_values_are_rejected(self):
        for number in ("0.0", "-0.0", "1e0", "1E+2", "1e9999", "NaN", "Infinity", "-Infinity"):
            with self.subTest(number=number), self.assertRaises(contract.ContractError):
                contract.decode_record(('{"value":' + number + '}').encode())

    def test_integer_storage_overflow_and_excessive_digits_are_rejected(self):
        for number in (str(-(1 << 63) - 1), str(1 << 64), "9" * 21, "-" + "9" * 21,
                       "9" * 5000):
            with self.subTest(digits=len(number)), self.assertRaises(contract.ContractError):
                contract.decode_record(('{"value":' + number + '}').encode())

    def test_invalid_utf8_and_escaped_unpaired_surrogates_are_rejected(self):
        for body in (b'{"x":"\xff"}', b'{"x":"\xc0\xaf"}', b'\xef\xbb\xbf{}',
                     b'{"x":"\\ud800"}', b'{"x":["\\udfff"]}', b'{"\\ud800":0}'):
            with self.subTest(body=body), self.assertRaises(contract.ContractError):
                contract.decode_record(body)

    def test_nesting_limit_counts_containers_but_not_quoted_brackets(self):
        accepted = b'{"value":' + b'[' * 15 + b'0' + b']' * 15 + b'}'
        rejected = b'{"value":' + b'[' * 16 + b'0' + b']' * 16 + b'}'
        self.assertIsInstance(contract.decode_record(accepted), dict)
        with self.assertRaisesRegex(contract.ContractError, "nesting"):
            contract.decode_record(rejected)
        text = '[{"\\' * 40
        self.assertEqual(contract.decode_record(json.dumps({"value": text}).encode()), {"value": text})

    def test_record_type_nonempty_and_exact_byte_size_boundaries(self):
        maximum = 512 * 1024
        body = b'{"x":"' + b'a' * (maximum - 8) + b'"}'
        self.assertEqual(len(body), maximum)
        self.assertEqual(len(contract.decode_record(body)["x"]), maximum - 8)
        for value in (body + b' ', b'', '{}', bytearray(b'{}'), memoryview(b'{}'), None):
            with self.subTest(type=type(value).__name__), self.assertRaises(contract.ContractError):
                contract.decode_record(value)

    def test_nonobjects_and_malformed_or_multiple_documents_are_rejected(self):
        for body in (b'[]', b'null', b'true', b'0', b'"x"', b'{}{}', b'{"x":1,}',
                     b'{"x":01}', b'{"x":"\x00"}', b'{} # comment', b'{"x":', b' '):
            with self.subTest(body=body), self.assertRaises(contract.ContractError):
                contract.decode_record(body)

    def test_unsigned_integer_and_digest_checks_are_type_strict(self):
        for bits in (32, 64):
            for value in (0, (1 << bits) - 1):
                contract.uint(value, "value", bits=bits)
            for value in (-1, 1 << bits, True, False, 0.0, "0", None):
                with self.subTest(bits=bits, value=value), self.assertRaises(contract.ContractError):
                    contract.uint(value, "value", bits=bits)
        with self.assertRaises(contract.ContractError):
            contract.uint(0, "positive", minimum=1)
        contract.digest("0123456789abcdef" * 4, "digest")
        for value in ("a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", b"a" * 64, None):
            with self.subTest(value=value), self.assertRaises(contract.ContractError):
                contract.digest(value, "digest")


class ManagedPreflightLoadedLibraryTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"name": name, "path": "/build/lib/" + name} for name in LIBRARIES]
        self.paths = {row["name"]: row["path"] for row in self.rows}

    def test_exact_five_libraries_are_returned_as_an_independent_copy(self):
        result = contract.validate_loaded_libraries(self.rows, self.paths)
        self.assertEqual(result, self.rows)
        result[0]["path"] = "/changed"
        self.assertEqual(self.rows[0]["path"], "/build/lib/libramulator-vortex.so")

    def test_omitted_extra_duplicate_reordered_and_unknown_libraries_are_rejected(self):
        alternatives = [self.rows[:-1], self.rows + [self.rows[0]], list(reversed(self.rows)),
                        [self.rows[0]] * 5, tuple(self.rows), {row["name"]: row for row in self.rows}]
        changed = deepcopy(self.rows)
        changed[0] = {"name": "libseed.so", "path": "/build/lib/libseed.so"}
        alternatives.append(changed)
        for index, value in enumerate(alternatives):
            with self.subTest(alternative=index), self.assertRaises(contract.ContractError):
                contract.validate_loaded_libraries(value)

    def test_library_rows_reject_missing_unknown_and_mistyped_fields(self):
        for row in ({"name": LIBRARIES[0]}, {"path": self.rows[0]["path"]},
                    dict(self.rows[0], sha256="a" * 64), {"name": 0, "path": self.rows[0]["path"]},
                    {"name": LIBRARIES[0], "path": None}):
            with self.subTest(row=row), self.assertRaises(contract.ContractError):
                contract.validate_loaded_libraries([row, *self.rows[1:]])

    def test_noncanonical_relative_escaped_and_wrong_basename_paths_are_rejected(self):
        for path in ("build/lib/" + LIBRARIES[0], "/build/../lib/" + LIBRARIES[0],
                     "/build/./" + LIBRARIES[0], "/build//" + LIBRARIES[0],
                     "/build/lib/" + LIBRARIES[0] + "/", "/build/lib/libother.so",
                     "/build/sp ace/" + LIBRARIES[0], "/build/μ/" + LIBRARIES[0],
                     "/build/\x00/" + LIBRARIES[0], "/" + "a" * 4096 + "/" + LIBRARIES[0]):
            with self.subTest(path=path[:80]), self.assertRaises(contract.ContractError):
                contract.validate_loaded_libraries([dict(self.rows[0], path=path), *self.rows[1:]])

    def test_same_named_library_at_substituted_path_cannot_match_retained_selection(self):
        changed = deepcopy(self.rows)
        changed[2]["path"] = "/other/build/libsimx.so"
        self.assertEqual(contract.validate_loaded_libraries(changed), changed)
        with self.assertRaisesRegex(contract.ContractError, "loaded library libsimx.so"):
            contract.validate_loaded_libraries(changed, self.paths)

    def test_expected_path_inventory_must_be_complete_canonical_and_exact(self):
        for paths in ({}, {key: value for key, value in self.paths.items() if key != "libsimx.so"},
                      dict(self.paths, extra="/build/lib/extra.so"),
                      dict(self.paths, **{"libsimx.so": "/build/../lib/libsimx.so"}), list(self.paths)):
            with self.subTest(paths=paths), self.assertRaises(contract.ContractError):
                contract.validate_loaded_libraries(self.rows, paths)


if __name__ == "__main__":
    unittest.main()
