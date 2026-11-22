# SPDX-License-Identifier: Apache-2.0
"""Independent, bounded tests of the frozen warm-workspace experiment inputs."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest import mock

import p06_warm_contract as contract


ROOT = Path(__file__).resolve().parents[2]
RAW_MANIFEST = (ROOT / contract.MANIFEST_PATH).read_bytes()
MANIFEST = json.loads(RAW_MANIFEST)


def replace_at(document, path, value):
    cursor = document
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value


def scalar_paths(value, path=()):
    if type(value) is dict:
        for key, item in value.items():
            yield from scalar_paths(item, path + (key,))
    elif type(value) is list:
        for index, item in enumerate(value):
            yield from scalar_paths(item, path + (index,))
    else:
        yield path, value


def stage_inputs(destination):
    # Only the 17 pinned inputs and manifest are needed (under 1 MiB total).
    # Never clone or copy the build tree for contract-only fault injection.
    for name in [row["path"] for row in MANIFEST["source_inputs"]] + [contract.MANIFEST_PATH]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())


class WarmInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = contract.load_contract(ROOT)
        cls.cases = contract.select_cases(cls.document, ROOT)

    def test_exact_24_process_order_has_matched_alternating_policy_pairs(self):
        one_format = [
            (0, "per_operation", "warmup"), (0, "reusable_single_tile", "warmup"),
            (1, "reusable_single_tile", "measured"), (1, "per_operation", "measured"),
            (2, "per_operation", "measured"), (2, "reusable_single_tile", "measured"),
            (3, "reusable_single_tile", "measured"), (3, "per_operation", "measured"),
            (4, "per_operation", "measured"), (4, "reusable_single_tile", "measured"),
            (5, "reusable_single_tile", "measured"), (5, "per_operation", "measured"),
        ]
        expected = [
            {"id": f"warm-simx-{fmt}-pair{pair}-{policy}", "backend": "simx",
             "format": fmt, "policy": policy, "pair_index": pair, "phase": phase}
            for fmt in ("fp16", "bf16") for pair, policy, phase in one_format
        ]
        plan = contract.process_plan(self.document)
        self.assertEqual(plan, expected)
        self.assertEqual(len({row["id"] for row in plan}), 24)
        self.assertTrue(all(re.fullmatch(self.document["observation"]["sample_id_pattern"],
                                        row["id"]) for row in plan))
        self.assertEqual(self.document["sampling"]["pair_indices"], [0, 1, 2, 3, 4, 5])
        self.assertEqual((self.document["sampling"]["warmup_pairs"],
                          self.document["sampling"]["measured_pairs"]), (1, 5))

    def test_counts_derive_from_exact_fixture_geometry_and_complete_matrix(self):
        self.assertEqual([case["id"] for case in self.cases],
                         ["fp16-single-dense_boundaries", "bf16-single-dense_boundaries"])
        for case in self.cases:
            with self.subTest(case=case["id"]):
                m, n, k = (case[key] for key in ("m", "n", "k"))
                self.assertEqual((m, n, k), (8, 4, 8))
                self.assertEqual((len(case["a_words"]), len(case["b_words"]),
                                  len(case["expected"])), (32, 16, 32))
                self.assertEqual(self.document["per_operation"], {
                    "launches": 1, "checked_words": m * n, "useful_flops": 2 * m * n * k,
                    "input_h2d_bytes": 4 * (len(case["a_words"]) + len(case["b_words"])),
                    "poison_h2d_bytes": 4 * m * n, "tensor_d2h_bytes": 4 * m * n,
                    "argument_bytes": 56,
                })
        per_operation = self.document["per_operation"]
        self.assertEqual(self.document["per_process"], {
            "operations": 33, "timed_operations": 32, "launches": 33,
            "checked_words": 33 * per_operation["checked_words"],
            "timed_useful_flops": 32 * per_operation["useful_flops"],
            "peak_requested_payload_bytes": per_operation["input_h2d_bytes"]
                                            + per_operation["tensor_d2h_bytes"],
            "per_operation_buffer_creates": 3 * 33, "per_operation_buffer_releases": 3 * 33,
            "resident_buffer_creates": 3, "resident_buffer_releases": 3,
        })
        plan = contract.process_plan(self.document)
        measured = sum(row["phase"] == "measured" for row in plan)
        warmups = sum(row["phase"] == "warmup" for row in plan)
        self.assertEqual((len(plan), measured, warmups), (24, 20, 4))
        self.assertEqual(self.document["complete_matrix"], {
            "processes": len(plan), "warmup_processes": warmups, "measured_processes": measured,
            "launches": len(plan) * 33, "checked_words": len(plan) * 33 * 32,
            "measured_operations": measured * 32, "measured_checked_words": measured * 32 * 32,
            "measured_useful_flops": measured * 32 * 512,
        })
        self.assertEqual((self.document["sampling"]["prime_operations"],
                          self.document["sampling"]["timed_operations"],
                          self.document["sampling"]["operations_per_process"]), (1, 32, 33))
        argument_header = (ROOT / "sw/common/ai_matmul_args.h").read_text()
        self.assertEqual(re.findall(r"constexpr uint32_t kArgumentBytes = ([0-9]+);",
                                    argument_header), ["56"])

    def test_fixture_identity_and_poison_sequence_are_fixed(self):
        self.assertEqual(self.document["fixture_path"], "ci/project/fixtures/p02_layout_v1.json")
        self.assertEqual(self.document["fixture_sha256"],
                         "0543f9f4208de3ff4743fe1894d97ccf3b8cca4707e9a26acd1f3dde884725b2")
        expected = [0xDEADBEEF, 0x7FC0DEAD] * 16 + [0xDEADBEEF]
        self.assertEqual([contract.poison_for(index) for index in range(33)], expected)
        self.assertEqual(self.document["sampling"]["poisons"], expected[:2])
        self.assertEqual(self.document["sampling"]["poison_order"],
                         "alternate_by_operation_index_prime_is_zero")
        for value in (-1, 33, True, False, 0.0, "0", None):
            with self.subTest(index=value), self.assertRaises(contract.ContractError):
                contract.poison_for(value)

    def test_same_build_mode_requires_timing_simx_perf_and_original_counter_inventory(self):
        self.assertEqual(self.document["source_matching"],
                         "one_clean_revision_and_same_binaries_per_format_both_policies")
        self.assertEqual(self.document["backends"], ["simx"])
        self.assertEqual(self.document["profile"], {
            "backend": "simx", "forbidden_macros": ["SIMX_FUNCTIONAL", "SIMX_MT"],
            "path": "profiles/p02-tfr.json", "performance_backend_macro": "PERF_ENABLE",
            "scalar_arithmetic": "STD", "tensor_arithmetic": "TFR", "simulation_mode": "timing",
            "xlen": 64, "sha256": "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102",
        })
        symbols = {name: value for section in tomllib.loads((ROOT / "VX_types.toml").read_text()).values()
                   if type(section) is dict for name, value in section.items()}
        counters = self.document["counters"]
        self.assertEqual(len(counters), 45)
        self.assertEqual(len({row["name"] for row in counters}), 45)
        self.assertEqual(len({(row["mpm_class"], row["csr"], row["core_id"])
                              for row in counters}), 45)
        unavailable = []
        for row in counters:
            self.assertEqual(row["mpm_class"], symbols[row["class_macro"]])
            self.assertEqual(row["csr"], symbols[row["csr_macro"]])
            self.assertEqual(row["core_id"], 0)
            if row["required_isa"] & self.document["capability_values"]["isa_flags"] != row["required_isa"]:
                unavailable.append(row["name"])
        self.assertEqual(len(unavailable), 12)
        self.assertTrue(all(name.startswith(("l2cache_", "l3cache_")) for name in unavailable))
        observation = self.document["observation"]
        self.assertIs(observation["profiling_enabled"], False)
        self.assertEqual(observation["counter_bits"], 64)
        self.assertEqual(observation["positive_counter_deltas"], ["cycles", "instructions"])
        self.assertEqual(observation["counter_delta_policy"], "after_batch_minus_after_prime_no_wrap_or_reset")
        self.assertEqual(observation["disabled_counter_policy"], "enabled_false_status_null_value_null")
        self.assertEqual(observation["snapshot_names"],
                         ["after_open", "after_prime", "after_batch", "before_release"])

    def test_budget_and_rejection_thresholds_do_not_imply_phase_acceptance(self):
        self.assertEqual(self.document["budget"], {
            "jobs_max": 2, "max_rss_bytes": 4 * 1024**3, "min_free_bytes": 15 * 1024**3,
            "max_log_bytes": 16 * 1024**2, "build_timeout_seconds": 1800,
            "run_timeout_seconds": 180, "hosted_job_timeout_minutes": 90,
        })
        self.assertEqual(self.document["observation"]["wait_timeout_ns"], 120_000_000_000)
        analysis = self.document["analysis"]
        self.assertEqual(analysis["candidate_median_percent_of_reference_max"], 95)
        self.assertEqual(analysis["batch_statistic"], "arithmetic_mean_of_32_primary_intervals")
        self.assertEqual(analysis["population"], "five_measured_batch_means_per_format_and_policy")
        self.assertEqual(analysis["statistics"],
                         ["count", "minimum", "maximum", "median", "population_stddev"])
        for name in ("each_measured_candidate_pair_must_not_be_slower",
                     "each_measured_candidate_pair_cycles_must_not_increase", "all_formats_must_improve"):
            self.assertIs(analysis[name], True)
        self.assertEqual(analysis["required_validity"],
                         ["numerics", "dispatch", "ownership", "cleanup", "provenance", "resources"])
        self.assertIs(analysis["decision_is_phase_acceptance"], False)
        for name in ("acceptance_claimed", "execution_claimed", "phase_acceptance"):
            self.assertIs(self.document[name], False)
        self.assertEqual(self.document["sampling"]["failed_sample_policy"],
                         "retain_and_fail_entire_attempt_no_replacements")
        self.assertEqual(self.document["sampling"]["outlier_policy"], "none")
        self.assertIs(self.document["sampling"]["optional_stopping"], False)

    def test_primary_timer_requires_completed_validation_and_excludes_retention(self):
        timing = self.document["timing"]
        self.assertEqual(timing["begin"], "immediately_before_submit")
        self.assertEqual(timing["end"], "after_wait_exact_comparison_explicit_close_and_success_checks")
        self.assertEqual(timing["included"], ["submit", "wait", "exact_output_comparison",
                                            "explicit_operation_close", "success_checks",
                                            "minimal_fixed_storage_allocation_observer"])
        self.assertEqual(timing["excluded"], ["input_packing", "context_create", "counter_queries",
                                            "memory_queries", "trace_copy", "output_copy_for_retention",
                                            "record_serialization", "owner_close"])
        self.assertTrue(set(timing["included"]).isdisjoint(timing["excluded"]))
        self.assertIs(timing["positive_duration_required"], True)
        self.assertIs(timing["counter_queries_outside_primary_interval"], True)
        self.assertIs(timing["memory_queries_outside_primary_interval"], True)
        self.assertEqual(timing["supervisor_containment_allowance_ns"], 1000)
        self.assertEqual(timing["supervisor_duration"], "separate_observation_never_corrected_or_subtracted")

    def test_valid_subsets_preserve_plan_order_and_return_independent_fixtures(self):
        original = deepcopy(self.document)
        complete = contract.process_plan(self.document)
        for formats in (["fp16"], ["bf16"], ["fp16", "bf16"]):
            with self.subTest(formats=formats):
                self.assertEqual(contract.process_plan(self.document, formats),
                                 [row for row in complete if row["format"] in formats])
                cases = contract.select_cases(self.document, ROOT, formats)
                self.assertEqual([row["format"] for row in cases], formats)
                cases[0]["expected"][0] = "bad-copy"
                cases[0]["m"] = -1
        self.assertEqual(self.document, original)
        fresh = contract.select_cases(self.document, ROOT, ["fp16"])[0]
        self.assertEqual(fresh["m"], 8)
        self.assertRegex(fresh["expected"][0], r"\A[0-9a-f]{8}\Z")


class WarmManifestRejectionTests(unittest.TestCase):
    def reject_change(self, path, value):
        changed = deepcopy(MANIFEST)
        replace_at(changed, path, value)
        with self.assertRaises(contract.ContractError):
            contract.validate_contract(changed, ROOT)

    def test_all_integer_and_boolean_fields_reject_equal_values_of_wrong_type(self):
        for path, value in scalar_paths(MANIFEST):
            if type(value) not in (int, bool):
                continue
            alternatives = [int(value)] if type(value) is bool else [float(value), str(value), None]
            if type(value) is int and value in (0, 1):
                alternatives.append(bool(value))
            for replacement in alternatives:
                with self.subTest(path=path, replacement=replacement):
                    self.reject_change(path, replacement)

    def test_frozen_source_identity_fixture_paths_and_counter_config_reject_drift(self):
        changes = [
            (("source_matching",), "different_binaries_per_policy"),
            (("source_inputs", 0, "sha256"), "0" * 64),
            (("source_inputs", 0, "path"), "../VX_config.toml"),
            (("fixture_path",), "ci/project/fixtures/p02_wmma_numerical_v1.json"),
            (("fixture_sha256",), "f" * 64), (("fixture_suffix",), "single-zero"),
            (("kernel_source_sha256",), "f" * 64), (("profile", "sha256"), "f" * 64),
            (("profile", "simulation_mode"), "functional"),
            (("profile", "performance_backend_macro"), "PERF_DISABLE"),
            (("profile", "forbidden_macros"), []), (("profile", "xlen"), 32),
            (("backends",), ["rtlsim"]), (("formats",), ["bf16", "fp16"]),
            (("policies",), ["reusable_single_tile", "per_operation"]),
            (("counters", 0, "csr"), 2818), (("counters", 0, "scope"), "global"),
            (("observation", "counter_delta_policy"), "after_batch_minus_after_open"),
            (("observation", "profiling_enabled"), True),
        ]
        for path, replacement in changes:
            with self.subTest(path=path):
                self.reject_change(path, replacement)

    def test_sampling_counts_budgets_thresholds_and_claims_cannot_be_relaxed(self):
        for section in ("per_operation", "per_process", "complete_matrix", "budget"):
            for name, value in MANIFEST[section].items():
                with self.subTest(section=section, field=name):
                    self.reject_change((section, name), value + 1)
        changes = [
            (("sampling", "warmup_pairs"), 0), (("sampling", "measured_pairs"), 6),
            (("sampling", "prime_operations"), 0), (("sampling", "timed_operations"), 31),
            (("sampling", "operations_per_process"), 32), (("sampling", "pair_indices"), [0, 1, 2, 3, 4]),
            (("sampling", "poisons"), [0, 0]), (("sampling", "optional_stopping"), True),
            (("sampling", "outlier_policy"), "remove_slowest"),
            (("sampling", "failed_sample_policy"), "replace_failed_sample"),
            (("analysis", "candidate_median_percent_of_reference_max"), 100),
            (("analysis", "each_measured_candidate_pair_must_not_be_slower"), False),
            (("analysis", "each_measured_candidate_pair_cycles_must_not_increase"), False),
            (("analysis", "all_formats_must_improve"), False),
            (("analysis", "decision_is_phase_acceptance"), True),
            (("acceptance_claimed",), True), (("execution_claimed",), True), (("phase_acceptance",), True),
            (("timing", "supervisor_containment_allowance_ns"), 1_000_000),
            (("timing", "positive_duration_required"), False),
            (("timing", "counter_queries_outside_primary_interval"), False),
            (("timing", "memory_queries_outside_primary_interval"), False),
        ]
        for path, replacement in changes:
            with self.subTest(path=path):
                self.reject_change(path, replacement)

    def test_missing_unknown_duplicated_and_reordered_inventory_fields_fail(self):
        changed = deepcopy(MANIFEST)
        del changed["budget"]
        with self.assertRaises(contract.ContractError):
            contract.validate_contract(changed, ROOT)
        changed = deepcopy(MANIFEST)
        changed["analysis"]["allow_retries"] = True
        with self.assertRaises(contract.ContractError):
            contract.validate_contract(changed, ROOT)
        for section in ("source_inputs", "counters", "capabilities"):
            for replacement in (list(reversed(MANIFEST[section])),
                                MANIFEST[section] + [MANIFEST[section][0]], MANIFEST[section][:-1]):
                with self.subTest(section=section, length=len(replacement)):
                    self.reject_change((section,), replacement)
        for section in ("operation_keys", "summary_keys", "count_keys", "dispatch_keys", "memory_names"):
            self.reject_change(("observation", section), MANIFEST["observation"][section][:-1])

    def test_selection_rejects_wrong_order_duplicates_wrong_types_and_unknown_formats(self):
        for formats in ([], ["bf16", "fp16"], ["fp16", "fp16"], ["fp16", "bf16", "fp16"],
                        ["fp32"], ["FP16"], [True], [None], "fp16", ("fp16",), {"fp16"}, False):
            with self.subTest(formats=formats):
                with self.assertRaises(contract.ContractError):
                    contract.process_plan(MANIFEST, formats)
                with self.assertRaises(contract.ContractError):
                    contract.select_cases(MANIFEST, ROOT, formats)


class WarmJsonBoundaryTests(unittest.TestCase):
    def test_manifest_round_trip_and_uint64_boundary(self):
        self.assertEqual(contract.decode_contract(RAW_MANIFEST), MANIFEST)
        self.assertEqual(contract.decode_contract(b'{"n":18446744073709551615}'),
                         {"n": (1 << 64) - 1})

    def test_duplicate_keys_including_escaped_nested_aliases_fail(self):
        for raw in (b'{"schema_version":1,"schema_version":1}',
                    b'{"sampling":{"measured_pairs":5,"measured_pairs":6}}',
                    b'{"x":1,"\\u0078":1}'):
            with self.subTest(raw=raw), self.assertRaises(contract.ContractError):
                contract.decode_contract(raw)

    def test_float_nonfinite_negative_and_out_of_range_integers_fail(self):
        for value in (b"1.0", b"1e0", b"NaN", b"Infinity", b"-Infinity", b"-1", b"-0",
                      b"18446744073709551616", b"9" * 21, b"9" * 1000):
            with self.subTest(value=value[:30]), self.assertRaises(contract.ContractError):
                contract.decode_contract(b'{"n":' + value + b"}")

    def test_malformed_utf8_nonobjects_and_nonbytes_fail(self):
        for raw in (b"", b"[]", b"null", b"true", b"1", b'"object"', b'{"x":}',
                    b'{"x":1,}', b'{"x":1} trailing', b'{"x":"\xff"}',
                    "{}", bytearray(b"{}"), memoryview(b"{}"), None):
            with self.subTest(raw=raw), self.assertRaises(contract.ContractError):
                contract.decode_contract(raw)

    def test_byte_and_depth_boundaries_ignore_quoted_braces_and_escaped_quotes(self):
        maximum = 256 * 1024
        self.assertEqual(contract.MAX_MANIFEST_BYTES, maximum)
        self.assertEqual(contract.decode_contract(b"{}" + b" " * (maximum - 2)), {})
        with self.assertRaises(contract.ContractError):
            contract.decode_contract(b"{}" + b" " * (maximum - 1))
        allowed = b'{"nested":' + b"[" * 15 + b"0" + b"]" * 15 + b"}"
        self.assertIn("nested", contract.decode_contract(allowed))
        with self.assertRaises(contract.ContractError):
            contract.decode_contract(b'{"nested":' + b"[" * 16 + b"0" + b"]" * 16 + b"}")
        text = "[" * 40 + '\\"' + "}" * 40
        self.assertEqual(contract.decode_contract(json.dumps({"text": text}).encode()), {"text": text})


class WarmSourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-warm-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        stage_inputs(self.source)

    def test_each_pinned_source_rejects_changed_bytes_and_rehashing_cannot_bless_drift(self):
        self.assertEqual(len(MANIFEST["source_inputs"]), 17)
        self.assertEqual([row["path"] for row in MANIFEST["source_inputs"]],
                         sorted({row["path"] for row in MANIFEST["source_inputs"]}))
        for row in MANIFEST["source_inputs"]:
            path = self.source / row["path"]
            original = path.read_bytes()
            with self.subTest(path=row["path"]):
                self.assertEqual(hashlib.sha256(original).hexdigest(), row["sha256"])
                try:
                    path.write_bytes(original + b"\n")
                    with self.assertRaisesRegex(contract.ContractError, "frozen warm input changed"):
                        contract.validate_contract(MANIFEST, self.source)
                    forged = deepcopy(MANIFEST)
                    next(item for item in forged["source_inputs"] if item["path"] == row["path"])["sha256"] = \
                        hashlib.sha256(path.read_bytes()).hexdigest()
                    with self.assertRaises(contract.ContractError):
                        contract.validate_contract(forged, self.source)
                finally:
                    path.write_bytes(original)

    def test_staged_valid_source_load_and_selection_are_read_only(self):
        before = {path.relative_to(self.source): path.read_bytes()
                  for path in self.source.rglob("*") if path.is_file()}
        loaded = contract.load_contract(self.source)
        with mock.patch.object(contract.fixtures, "load_cases", wraps=contract.fixtures.load_cases) as producer:
            selected = contract.select_cases(loaded, self.source)
        producer.assert_called_once_with(self.source)
        self.assertEqual([row["id"] for row in selected],
                         ["fp16-single-dense_boundaries", "bf16-single-dense_boundaries"])
        self.assertEqual(before, {path.relative_to(self.source): path.read_bytes()
                                  for path in self.source.rglob("*") if path.is_file()})

    def test_imported_helper_locations_and_current_helper_bytes_are_trusted_separately(self):
        modules = [contract.fixtures, contract.fixtures.leaf,
                   contract.fixtures.layout, contract.fixtures.numerical]
        for module in modules:
            name = Path(module.__file__).name
            with self.subTest(module=name, fault="location"):
                with mock.patch.object(module, "__file__", str(self.source / "ci/project" / name)):
                    with self.assertRaisesRegex(contract.ContractError, "trusted repository"):
                        contract.validate_contract(MANIFEST, self.source)
            trusted_path = ROOT / "ci/project" / name
            real_read = contract._read_file

            def changed_helper(path, maximum):
                original = real_read(path, maximum)
                return original + b"\n" if Path(path) == trusted_path else original

            with self.subTest(module=name, fault="bytes"):
                with mock.patch.object(contract, "_read_file", side_effect=changed_helper):
                    with self.assertRaisesRegex(contract.ContractError, "loaded fixture helper changed"):
                        contract.validate_contract(MANIFEST, self.source)

    def test_counter_reference_requires_trusted_location_and_original_bytes(self):
        with mock.patch.object(contract.counter_reference, "__file__",
                               str(self.source / "ci/project/p06_contract.py")):
            with self.assertRaisesRegex(contract.ContractError, "trusted repository"):
                contract.expected_contract()
        real_read = contract._read_file

        def changed_counter(path, maximum):
            result = real_read(path, maximum)
            return result + b"\n" if Path(path) == ROOT / "ci/project/p06_contract.py" else result

        with mock.patch.object(contract, "_read_file", side_effect=changed_counter):
            with self.assertRaisesRegex(contract.ContractError, "counter definition source changed"):
                contract.expected_contract()

    def test_independent_fixture_header_reproduction_is_required(self):
        with mock.patch.object(contract.fixtures, "render_header", return_value=b"forged header"):
            with self.assertRaisesRegex(contract.ContractError, "independent fixture header did not reproduce"):
                contract.select_cases(MANIFEST, self.source)

    def test_missing_directory_fifo_and_oversized_manifests_are_bounded_failures(self):
        path = self.source / contract.MANIFEST_PATH
        path.unlink()
        with self.assertRaises(contract.ContractError):
            contract.load_contract(self.source)
        path.mkdir()
        try:
            with self.assertRaises(contract.ContractError):
                contract.load_contract(self.source)
        finally:
            path.rmdir()
        os.mkfifo(path)
        try:
            with self.assertRaises(contract.ContractError):
                contract.load_contract(self.source)
        finally:
            path.unlink()
        with path.open("wb") as stream:
            stream.truncate(contract.MAX_MANIFEST_BYTES + 1)
        with self.assertRaises(contract.ContractError):
            contract.load_contract(self.source)

    def test_symlinked_manifest_parent_and_root_and_parent_traversal_are_rejected(self):
        path = self.source / contract.MANIFEST_PATH
        path.unlink()
        path.symlink_to(ROOT / contract.MANIFEST_PATH)
        with self.assertRaisesRegex(contract.ContractError, "symbolic link"):
            contract.load_contract(self.source)
        path.unlink()
        path.write_bytes(RAW_MANIFEST)
        parent = self.source / "ci/project"
        saved = self.source / "ci/retained-project"
        parent.rename(saved)
        parent.symlink_to(saved, target_is_directory=True)
        with self.assertRaisesRegex(contract.ContractError, "symbolic link"):
            contract.load_contract(self.source)
        parent.unlink()
        saved.rename(parent)
        link = self.source / "root-link"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(contract.ContractError, "symbolic link"):
            contract.load_contract(link)
        with self.assertRaisesRegex(contract.ContractError, "parent or symbolic link"):
            contract.load_contract(self.source / "ci" / "..")

    def test_nonregular_missing_symlinked_and_oversized_pinned_inputs_fail(self):
        path = self.source / "VX_config.toml"
        path.unlink()
        with self.assertRaises(contract.ContractError):
            contract.validate_contract(MANIFEST, self.source)
        path.mkdir()
        try:
            with self.assertRaises(contract.ContractError):
                contract.validate_contract(MANIFEST, self.source)
        finally:
            path.rmdir()
        os.mkfifo(path)
        try:
            with self.assertRaises(contract.ContractError):
                contract.validate_contract(MANIFEST, self.source)
        finally:
            path.unlink()
        path.symlink_to(ROOT / "VX_config.toml")
        with self.assertRaises(contract.ContractError):
            contract.validate_contract(MANIFEST, self.source)
        path.unlink()
        with path.open("wb") as stream:
            stream.truncate(contract.MAX_SOURCE_BYTES + 1)
        with self.assertRaises(contract.ContractError):
            contract.validate_contract(MANIFEST, self.source)


if __name__ == "__main__":
    unittest.main()
