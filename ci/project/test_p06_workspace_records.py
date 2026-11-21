# SPDX-License-Identifier: Apache-2.0
"""Independent fail-closed workspace transport tests; parser/control evidence only."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_workspace_records as records
from p06_workspace_test_samples import (
    BINDING, FORMATS, POLICIES, PROBES, RESOURCES, ROOT, argument_hex,
    cases, contract, memory, process_records, render_log,
)


def at(value, path):
    for key in path:
        value = value[key]
    return value


def put(value, path, item):
    at(value, path[:-1])[path[-1]] = item


def leaves(value, path=()):
    if type(value) is dict:
        for key, item in value.items():
            yield from leaves(item, (*path, key))
    elif type(value) is list:
        for key, item in enumerate(value):
            yield from leaves(item, (*path, key))
    else:
        yield path, value


class WorkspaceOutputRecordTests(unittest.TestCase):
    rejection_checks = 0

    @classmethod
    def setUpClass(cls):
        cls.samples = {(fmt, policy): process_records(fmt, policy)
                       for fmt in FORMATS for policy in POLICIES}
        cls.contract = contract()
        cls.source_cases = {fmt: cases(fmt) for fmt in FORMATS}
        # Verify the independent producer once, then keep an immutable snapshot
        # for negative transport cases. Positive integrations use the real loader.
        cls.fixture_snapshot = json.dumps(records.fixtures.load_cases(ROOT))

    def verify(self, raw=None, *, fmt="bf16", policy="reusable_single_tile", text=None, **options):
        selected_fmt = fmt if type(fmt) is str and fmt in FORMATS else "bf16"
        selected_policy = policy if type(policy) is str and policy in POLICIES else "reusable_single_tile"
        if raw is None:
            raw = self.samples[selected_fmt, selected_policy]
        arguments = dict(cases=self.source_cases[selected_fmt], fmt=fmt, policy=policy,
                         binding_id=BINDING, contract=self.contract)
        arguments.update(options)
        return records.verify_output(render_log(raw) if text is None else text, **arguments)

    def reject(self, raw=None, **options):
        type(self).rejection_checks += 1
        with mock.patch.object(records.fixtures, "load_cases",
                               return_value=json.loads(self.fixture_snapshot)) as loader:
            with self.assertRaises(ValueError):
                self.verify(raw, **options)
            if loader.called:
                loader.assert_called_once_with(ROOT)

    def mutated(self, path, value, *, fmt="bf16", policy="reusable_single_tile"):
        raw = deepcopy(self.samples[fmt, policy])
        put(raw, path, value)
        return raw

    def test_complete_records_preserve_original_observations_for_both_policies_and_formats(self):
        for (fmt, policy), raw in self.samples.items():
            original = deepcopy(raw)
            with self.subTest(fmt=fmt, policy=policy):
                self.assertEqual(self.verify(raw, fmt=fmt, policy=policy), original)
                self.assertEqual(raw, original)
                self.assertEqual(sum(len(row["actual_bits"]) for row in raw["operations"]), 128)
                self.assertEqual(len(raw["summary"]["buffers"]), 3 if policy.startswith("reusable") else 12)
        self.assertIs(self.contract["performance_acceptance"], False)
        self.assertIs(self.contract["phase_acceptance"], False)

    def test_allocator_reuse_of_default_addresses_requires_distinct_complete_lifetimes(self):
        raw = deepcopy(self.samples["bf16", "per_operation"])
        addresses = [row["address"] for row in raw["summary"]["buffers"][:3]]
        for index, buffer in enumerate(raw["summary"]["buffers"]):
            buffer["address"] = addresses[index % 3]
        for row in raw["operations"]:
            for name, address in zip(("a_address", "b_address", "d_address"), addresses):
                row["dispatch"][name] = address
            row["dispatch"]["argument_bytes"] = argument_hex("bf16", addresses)
        self.assertEqual(self.verify(raw, policy="per_operation"), raw)
        raw["summary"]["buffers"][3]["buffer_id"] = 1
        self.reject(raw, policy="per_operation")

    def test_allocation_rounding_is_accepted_only_with_exact_live_device_reclamation(self):
        raw = deepcopy(self.samples["bf16", "reusable_single_tile"])
        boundaries = (512, 704, 832, 1024)
        for index, buffer in enumerate(raw["summary"]["buffers"]):
            buffer.update(create_before=memory(boundaries[index]), create_after=memory(boundaries[index + 1]),
                          release_before=memory(boundaries[index + 1]), release_after=memory(boundaries[index]))
        for row in raw["operations"]:
            for snapshot in row["resources"].values():
                snapshot["memory"] = memory(1024)
        self.assertEqual(self.verify(raw), raw)
        raw["summary"]["buffers"][0]["release_after"] = memory(576)
        self.reject(raw)

    def test_release_order_can_differ_from_creation_order(self):
        raw = deepcopy(self.samples["bf16", "reusable_single_tile"])
        # Release A, D, B instead of the sample's D, B, A.
        for index, before, after in ((0, 832, 704), (2, 704, 576), (1, 576, 512)):
            raw["summary"]["buffers"][index].update(release_before=memory(before), release_after=memory(after))
        self.assertEqual(self.verify(raw), raw)

    def test_boolean_integer_coercion_is_rejected_at_every_representative_leaf(self):
        roots = (("operations", 0), ("summary", "counts"), ("summary", "results"),
                 ("summary", "unsupported_shape"), ("summary", "buffers", 0),
                 ("summary", "devices", 0))
        for policy in POLICIES:
            raw = self.samples["bf16", policy]
            for root in roots:
                for path, value in leaves(at(raw, root), root):
                    if type(value) is bool or type(value) is int and value in (0, 1):
                        replacement = int(value) if type(value) is bool else bool(value)
                        with self.subTest(policy=policy, path=path):
                            self.reject(self.mutated(path, replacement, policy=policy), policy=policy)

    def test_missing_or_extra_fields_are_rejected_in_each_nested_schema(self):
        targets = (("operations", 0), ("operations", 0, "dispatch"),
                   ("operations", 0, "results"), ("operations", 0, "results", "submit"),
                   ("operations", 0, "probes"), ("operations", 0, "probes", PROBES[0]),
                   ("operations", 0, "resources"), ("operations", 0, "resources", RESOURCES[0]),
                   ("operations", 0, "resources", RESOURCES[0], "counts"),
                   ("operations", 0, "resources", RESOURCES[0], "memory"),
                   ("summary",), ("summary", "results"), ("summary", "counts"),
                   ("summary", "unsupported_shape"), ("summary", "buffers", 0),
                   ("summary", "devices", 0))
        for path in targets:
            for mutation in ("missing", "extra", "null", "array"):
                raw = deepcopy(self.samples["bf16", "reusable_single_tile"])
                selected = at(raw, path)
                if mutation == "missing":
                    del selected[next(iter(selected))]
                elif mutation == "extra":
                    selected["unobserved_success"] = True
                else:
                    put(raw, path, None if mutation == "null" else [])
                with self.subTest(path=path, mutation=mutation):
                    self.reject(raw)

    def test_missing_reordered_repeated_and_extra_operation_rows_fail(self):
        for fmt in FORMATS:
            for policy in POLICIES:
                for mutation in ("missing", "reordered", "repeated", "extra", "no_summary",
                                 "summary_first", "duplicate_summary", "result_after_summary"):
                    lines = render_log(self.samples[fmt, policy]).splitlines()
                    if mutation == "missing":
                        del lines[2]
                    elif mutation == "reordered":
                        lines[1], lines[2] = lines[2], lines[1]
                    elif mutation == "repeated":
                        lines[3] = lines[2]
                    elif mutation == "extra":
                        lines.insert(5, lines[4])
                    elif mutation == "no_summary":
                        del lines[5]
                    elif mutation == "summary_first":
                        lines.insert(1, lines.pop(5))
                    elif mutation == "duplicate_summary":
                        lines.insert(5, lines[5])
                    else:
                        lines.insert(6, lines[1])
                    with self.subTest(fmt=fmt, policy=policy, mutation=mutation):
                        self.reject(text="\n".join(lines) + "\n", fmt=fmt, policy=policy)

    def test_identity_cannot_be_substituted_on_any_operation_or_summary(self):
        substitutions = {"schema_version": 2, "contract_id": "p06-cold-benchmark-v1",
                         "qualification_id": "f" * 64, "policy": "per_operation", "format": "fp16"}
        for target in ((*(("operations", index) for index in range(4)), ("summary",))):
            for field, value in substitutions.items():
                with self.subTest(target=target, field=field):
                    self.reject(self.mutated((*target, field), value))

    def test_fixture_sequence_dimensions_poison_and_success_totals_are_exact(self):
        mutations = {"sequence_index": 9, "case_id": "bf16-single-k03", "m": 16,
                     "n": 8, "k": 16, "poison": 0, "checked": 31, "mismatches": 1, "passed": False}
        for index in range(4):
            for field, value in mutations.items():
                if field == "case_id" and index == 2:
                    value = "bf16-numerical-zero"
                with self.subTest(index=index, field=field):
                    self.reject(self.mutated(("operations", index, field), value))
        for field, value in (("operations", 3), ("checked", 127), ("mismatches", 1), ("passed", False)):
            with self.subTest(summary=field):
                self.reject(self.mutated(("summary", field), value))

    def test_every_actual_word_is_checked_despite_false_zero_mismatch_claims(self):
        for fmt in FORMATS:
            for index in range(4):
                policy = POLICIES[index % 2]
                for offset in range(32):
                    expected = self.samples[fmt, policy]["operations"][index]["actual_bits"][offset]
                    changed = format(int(expected, 16) ^ 1, "08x")
                    with self.subTest(fmt=fmt, index=index, offset=offset, policy=policy):
                        self.reject(self.mutated(("operations", index, "actual_bits", offset), changed,
                                                 fmt=fmt, policy=policy), fmt=fmt, policy=policy)

    def test_actual_words_require_exact_hex_width_case_type_and_count(self):
        raw = self.samples["bf16", "reusable_single_tile"]
        words = raw["operations"][0]["actual_bits"]
        for value in (words[:-1], words + [words[0]], "".join(words), None,
                      ["DEADBEEF"] + words[1:], ["0x000000"] + words[1:],
                      ["0000000"] + words[1:], ["000000000"] + words[1:],
                      [0] + words[1:], [False] + words[1:], ["gggggggg"] + words[1:]):
            with self.subTest(value=value):
                self.reject(self.mutated(("operations", 0, "actual_bits"), value))

    def test_source_fixture_substitution_cannot_supply_matching_forged_outputs(self):
        for field in ("a_words", "b_words", "expected"):
            selected = deepcopy(self.source_cases["bf16"])
            selected[0][field][0] = format(int(selected[0][field][0], 16) ^ 1, "08x")
            raw = deepcopy(self.samples["bf16", "reusable_single_tile"])
            if field == "expected":
                raw["operations"][0]["actual_bits"] = selected[0]["expected"]
            with self.subTest(field=field):
                self.reject(raw, cases=selected)
        for value in ([], tuple(self.source_cases["bf16"]), list(reversed(self.source_cases["bf16"])),
                      self.source_cases["fp16"], self.source_cases["bf16"][:3]):
            with self.subTest(value=type(value).__name__, length=len(value)):
                self.reject(cases=value)

    def test_every_argument_byte_is_bound_to_the_format_geometry_and_live_addresses(self):
        for fmt in FORMATS:
            wire = bytes.fromhex(self.samples[fmt, "reusable_single_tile"]["operations"][0]["dispatch"]["argument_bytes"])
            self.assertEqual(len(wire), 56)
            for offset in range(56):
                changed = bytearray(wire)
                changed[offset] ^= 1
                with self.subTest(fmt=fmt, byte=offset):
                    self.reject(self.mutated(("operations", 0, "dispatch", "argument_bytes"), changed.hex(), fmt=fmt), fmt=fmt)
        for wire in ("00" * 55, "00" * 57, "GG" * 56, 0, None):
            with self.subTest(wire=wire):
                self.reject(self.mutated(("operations", 0, "dispatch", "argument_bytes"), wire))

    def test_unsafe_addresses_fail_even_with_self_consistent_argument_bytes(self):
        for slot, field in enumerate(("a_address", "b_address", "d_address")):
            for address in (-4, True, 0.0, 1, (1 << 64), (1 << 64) - 4, 0x10004):
                raw = deepcopy(self.samples["bf16", "reusable_single_tile"])
                dispatch = raw["operations"][0]["dispatch"]
                dispatch[field] = address
                addresses = [dispatch[name] for name in ("a_address", "b_address", "d_address")]
                if type(address) is int and 0 <= address < (1 << 64):
                    dispatch["argument_bytes"] = argument_hex("bf16", addresses)
                with self.subTest(field=field, address=address):
                    self.reject(raw)

    def test_changed_resident_or_stale_default_addresses_cannot_borrow_other_lifetimes(self):
        for policy in POLICIES:
            raw = deepcopy(self.samples["bf16", policy])
            dispatch = raw["operations"][1]["dispatch"]
            addresses = [0x20000, 0x20100, 0x20200] if policy.startswith("reusable") else [0x10000, 0x10100, 0x10200]
            for name, address in zip(("a_address", "b_address", "d_address"), addresses):
                dispatch[name] = address
            dispatch["argument_bytes"] = argument_hex("bf16", addresses)
            with self.subTest(policy=policy):
                self.reject(raw, policy=policy)

    def test_dispatch_sizes_counts_events_waits_and_profile_are_exact(self):
        fields = {"a_bytes": 64, "b_bytes": 128, "d_bytes": 64, "writes": 2,
                  "launches": 0, "reads": 2, "waits": 0, "timed_out_waits": 1,
                  "profiling_enabled": True, "event_results": [0, 0, 0, 0]}
        for field, value in fields.items():
            with self.subTest(field=field):
                self.reject(self.mutated(("operations", 0, "dispatch", field), value))
        for index in range(5):
            with self.subTest(event=index):
                self.reject(self.mutated(("operations", 0, "dispatch", "event_results", index), 7))

    def test_each_submit_wait_close_and_final_teardown_status_remains_independent(self):
        paths = [("operations", index, "results", name)
                 for index in range(4) for name in ("submit", "wait", "close")]
        paths += [("summary", "results", name) for name in ("setup", "teardown", "teardown_repeat")]
        for path in paths:
            for field in ("validation", "primary", "cleanup", "complete"):
                value = not at(self.samples["bf16", "reusable_single_tile"], (*path, field)) if field == "complete" else 1
                with self.subTest(path=path, field=field):
                    self.reject(self.mutated((*path, field), value))

    def test_each_lease_probe_rejects_work_objects_or_changed_success_fields(self):
        for index in range(4):
            for name in PROBES:
                path = ("operations", index, "probes", name)
                for suffix, value in ((("returned_object",), True), (("result", "primary"), 0),
                                      (("result", "cleanup"), 1), (("before", "buffer_create_calls"), 99),
                                      (("after", "buffer_create_calls"), 99),
                                      (("after", "device_open_calls"), 2)):
                    with self.subTest(index=index, name=name, field=suffix):
                        self.reject(self.mutated((*path, *suffix), value))

    def test_unsupported_shape_probe_requires_the_policy_specific_tuple_and_no_work(self):
        for policy in POLICIES:
            for suffix, value in ((("m",), 16), (("n",), 8), (("k",), 32),
                                  (("result", "validation"), 0), (("result", "primary"), 7),
                                  (("result", "complete"), False), (("returned_object",), True),
                                  (("after", "buffer_create_calls"), 4)):
                with self.subTest(policy=policy, field=suffix):
                    self.reject(self.mutated(("summary", "unsupported_shape", *suffix), value, policy=policy), policy=policy)

    def test_each_resource_and_final_counter_is_bound_to_its_lifetime(self):
        for policy in POLICIES:
            paths = [("operations", 1, "resources", name, "counts") for name in RESOURCES]
            paths.append(("summary", "counts"))
            for path in paths:
                for field, value in at(self.samples["bf16", policy], path).items():
                    with self.subTest(policy=policy, path=path, field=field):
                        self.reject(self.mutated((*path, field), value + 1, policy=policy), policy=policy)

    def test_missing_failed_negative_overflowing_or_fabricated_memory_queries_fail(self):
        paths = [("operations", 0, "resources", name, "memory") for name in RESOURCES]
        paths += [("summary", "buffers", 0, name)
                  for name in ("create_before", "create_after", "release_before", "release_after")]
        paths += [("summary", "devices", 0, name) for name in ("after_open", "before_release")]
        for path in paths:
            for value in (None, {"status": 7, "free_bytes": 0, "used_bytes": 0},
                          {"status": 0, "free_bytes": -1, "used_bytes": 1},
                          {"status": 0, "free_bytes": 0, "used_bytes": 0},
                          {"status": 0, "free_bytes": 1 << 64, "used_bytes": 0}):
                with self.subTest(path=path, value=value):
                    self.reject(self.mutated(path, value))

    def test_balanced_counter_manipulation_does_not_forge_allocation_reclamation(self):
        changes = (
            (("summary", "buffers", 0, "release_after"), memory(576)),
            (("summary", "buffers", 0, "create_after"), memory(512)),
            (("summary", "buffers", 0, "release_before"), memory(704)),
            (("summary", "buffers", 1, "create_before"), memory(576)),
            (("summary", "buffers", 1, "release_before"), memory(768)),
            (("summary", "devices", 0, "before_release"), memory(320)),
        )
        for path, value in changes:
            with self.subTest(path=path):
                self.reject(self.mutated(path, value))
        for policy in POLICIES:
            raw = deepcopy(self.samples["bf16", policy])
            for snapshot in raw["operations"][1]["resources"].values():
                snapshot["memory"]["free_bytes"] -= 64
                snapshot["memory"]["used_bytes"] += 64
            with self.subTest(policy=policy, mutation="internally_stable_unexplained_memory"):
                self.reject(raw, policy=policy)

    def test_capacity_must_remain_constant_even_when_group_deltas_reconcile(self):
        raw = deepcopy(self.samples["bf16", "reusable_single_tile"])
        for buffer in raw["summary"]["buffers"]:
            for name in ("create_before", "create_after", "release_before", "release_after"):
                buffer[name]["free_bytes"] += 64
        for row in raw["operations"]:
            for snapshot in row["resources"].values():
                snapshot["memory"]["free_bytes"] += 64
        self.reject(raw)

    def test_context_baseline_cannot_predate_device_owned_allocations(self):
        raw = deepcopy(self.samples["bf16", "reusable_single_tile"])
        device = raw["summary"]["devices"][0]
        device["after_open"] = memory(576)
        device["before_release"] = memory(576)
        self.reject(raw)

    def test_buffer_inventory_binds_identity_permissions_size_phases_and_sequences(self):
        substitutions = {"buffer_id": 99, "device_id": 2, "requested_bytes": 64, "flags": 2,
                         "address": 0x30000, "address_status": 7, "create_status": 7,
                         "release_status": 7, "create_phase": "unknown", "release_phase": "unknown",
                         "create_sequence": 5, "release_sequence": 5, "release_device_live": False}
        for policy in POLICIES:
            for field, value in substitutions.items():
                with self.subTest(policy=policy, field=field):
                    self.reject(self.mutated(("summary", "buffers", 0, field), value, policy=policy), policy=policy)
            for mutation in ("missing", "extra", "reordered", "repeated"):
                raw = deepcopy(self.samples["bf16", policy])
                buffers = raw["summary"]["buffers"]
                if mutation == "missing":
                    buffers.pop()
                elif mutation == "extra":
                    buffers.append(deepcopy(buffers[-1]))
                elif mutation == "reordered":
                    buffers[0], buffers[1] = buffers[1], buffers[0]
                else:
                    buffers[1] = deepcopy(buffers[0])
                with self.subTest(policy=policy, inventory=mutation):
                    self.reject(raw, policy=policy)

    def test_final_release_cannot_be_incomplete_or_observed_after_device_death(self):
        for policy in POLICIES:
            count = len(self.samples["bf16", policy]["summary"]["buffers"])
            for index in range(count):
                for field, value in (("release_device_live", False), ("release_status", 1),
                                     ("release_after", None), ("release_sequence", 4)):
                    with self.subTest(policy=policy, buffer=index, field=field):
                        self.reject(self.mutated(("summary", "buffers", index, field), value, policy=policy), policy=policy)
            for field, value in (("release_status", 7), ("open_status", 7), ("device_id", 2), ("index", 1)):
                with self.subTest(policy=policy, device=field):
                    self.reject(self.mutated(("summary", "devices", 0, field), value, policy=policy), policy=policy)

    def test_duplicate_json_keys_are_rejected_even_if_values_are_identical(self):
        original = render_log(self.samples["bf16", "reusable_single_tile"])
        needles = ('"schema_version":1', '"format":"bf16"', '"primary":0', '"complete":false',
                   '"writes":3', '"device_open_calls":1', '"free_bytes":16776384',
                   '"release_device_live":true')
        for needle in needles:
            self.assertIn(needle, original)
            with self.subTest(field=needle):
                self.reject(text=original.replace(needle, needle + "," + needle, 1))
        lines = original.splitlines()
        lines[-2] = lines[-2].replace('"operations":4', '"operations":4,"operations":4')
        self.reject(text="\n".join(lines) + "\n")

    def test_json_numbers_depth_and_malformed_roots_are_rejected(self):
        original = render_log(self.samples["bf16", "reusable_single_tile"])
        for token in ("1.0", "1e0", "NaN", "Infinity", "-Infinity", "1" * 21):
            with self.subTest(token=token):
                self.reject(text=original.replace('"schema_version":1', '"schema_version":' + token, 1))
        for value in ("null", "[]", "true", "{} trailing", '{"nest":' + "[" * 17 + "0" + "]" * 17 + "}"):
            lines = original.splitlines()
            lines[1] = "P06_WORKSPACE_RESULT " + value
            with self.subTest(root=value):
                self.reject(text="\n".join(lines) + "\n")

    def test_failure_markers_and_false_or_ambiguous_success_cannot_be_hidden(self):
        original = render_log(self.samples["bf16", "reusable_single_tile"])
        for marker in ("FAILED", "FAIL", "ERROR", "fatal", "aborted", "Mismatch",
                       "Assertion probe failed", "Segmentation fault", "core dumped", "runtime error:"):
            with self.subTest(marker=marker):
                self.reject(text=marker + "\n" + original)
        mutations = (original.replace("PASSED!\n", ""), original + "PASSED!\n",
                     "PASSED!\n" + original, original + "trailing output\n", original + "\n",
                     original.replace("PASSED!", "PASSED"), original.replace("PASSED!", " PASSED!"),
                     "earlier PASSED marker\n" + original,
                     original.replace("P06_WORKSPACE_SUMMARY", " P06_WORKSPACE_SUMMARY", 1),
                     original.replace("P06_WORKSPACE_RESULT", "P06_WORKSPACE_BOGUS", 1),
                     original.replace("\nPASSED!", "\nunbound trailing diagnostics\nPASSED!"))
        for index, text in enumerate(mutations):
            with self.subTest(mutation=index):
                self.reject(text=text)

    def test_text_controls_types_unicode_and_size_limits_are_enforced(self):
        original = render_log(self.samples["bf16", "reusable_single_tile"])
        for prefix in ("\x00", "\x1b", "\x7f", "\x85", "\u00a0", "\u2028", "\ud800"):
            with self.subTest(prefix=repr(prefix)):
                self.reject(text=prefix + original)
        self.reject(text=original.encode())
        self.reject(text="x" * (16 * 1024 * 1024 + 1))
        lines = original.splitlines()
        lines[1] += " " * (256 * 1024)
        self.reject(text="\n".join(lines) + "\n")

    def test_call_binding_format_policy_and_contract_are_not_coerced(self):
        for options in ({"binding_id": "A" * 64}, {"binding_id": "0" * 63}, {"binding_id": 0},
                        {"fmt": "FP16"}, {"fmt": True}, {"policy": "pool"}, {"policy": 1}):
            with self.subTest(options=options):
                # Keep sample selection fixed while passing invalid public arguments.
                self.reject(text=render_log(self.samples["bf16", "reusable_single_tile"]),
                            **{"cases": self.source_cases["bf16"], **options})
        for key, value in (("performance_acceptance", True), ("phase_acceptance", True), ("schema_version", True)):
            changed = deepcopy(self.contract)
            changed[key] = value
            with self.subTest(contract=key):
                self.reject(contract=changed)


class WorkspaceManifestTests(unittest.TestCase):
    rejection_checks = 0

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-workspace-contract-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "ci/project/p06_workspace_contract.json"
        self.path.parent.mkdir(parents=True)
        self.original = (ROOT / "ci/project/p06_workspace_contract.json").read_bytes()

    def reject_bytes(self, data):
        self.path.write_bytes(data)
        type(self).rejection_checks += 1
        with self.assertRaises(ValueError):
            records.load_contract(self.root)

    def test_frozen_manifest_reads_exact_original_data(self):
        self.path.write_bytes(self.original)
        self.assertEqual(records.load_contract(self.root), json.loads(self.original))

    def test_each_frozen_leaf_rejects_changed_value_or_boolean_integer_type(self):
        source = json.loads(self.original)
        for path, value in leaves(source):
            changed = deepcopy(source)
            replacement = not value if type(value) is bool else value + 1 if type(value) is int else value + "-changed"
            put(changed, path, replacement)
            with self.subTest(path=path):
                self.reject_bytes(json.dumps(changed).encode())
        self.reject_bytes(self.original.replace(b'"schema_version": 1', b'"schema_version": true'))

    def test_duplicate_extra_missing_nonfinite_and_oversized_manifest_data_fail(self):
        self.reject_bytes(self.original.replace(b'"schema_version": 1', b'"schema_version": 1,"schema_version":1'))
        self.reject_bytes(self.original.replace(b'"schema_version": 1', b'"schema_version": NaN'))
        source = json.loads(self.original)
        source["invented_waiver"] = True
        self.reject_bytes(json.dumps(source).encode())
        source = json.loads(self.original)
        del source["scope"]
        self.reject_bytes(json.dumps(source).encode())
        self.reject_bytes(b" " * (64 * 1024 + 1))
        self.reject_bytes(b"\xff")

    def test_missing_symlink_directory_and_fifo_contracts_fail_without_blocking(self):
        for kind in ("missing", "symlink", "directory", "fifo"):
            if kind == "symlink":
                target = self.root / "target.json"
                target.write_bytes(self.original)
                self.path.symlink_to(target)
            elif kind == "directory":
                self.path.mkdir()
            elif kind == "fifo":
                os.mkfifo(self.path)
            type(self).rejection_checks += 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                records.load_contract(self.root)
            if kind == "directory":
                self.path.rmdir()
            elif kind != "missing":
                self.path.unlink()


if __name__ == "__main__":
    unittest.main()
