# SPDX-License-Identifier: Apache-2.0
"""Independent synthetic record controls; no native or performance result."""

from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import p06_managed_preflight_contract as manifest
import p06_managed_preflight_records as records
import p06_warm_contract as warm_contract
import p06_warm_records as warm_records
import p06_warm_test_fixture as warm_fixture
from p06_managed_preflight_test_fixture import (
    BINDING, EXPECTED_LIBRARIES, raw_records, render_log, synthetic_log,
)


class ManagedPreflightRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = manifest.load_contract()
        cls.warm_contract = warm_contract.load_contract()
        cls.examples = {(fmt, policy): raw_records(fmt, policy, contract=cls.contract)
                        for fmt, policy in itertools.product(("fp16", "bf16"),
                            ("per_operation", "reusable_single_tile"))}

    def raw(self, fmt="fp16", policy="per_operation"):
        return deepcopy(self.examples[fmt, policy])

    def verify(self, raw=None, *, fmt="fp16", policy="per_operation", text=..., **changes):
        case, operations, summary, witness = self.raw(fmt, policy) if raw is None else raw
        kwargs = {
            "contract": self.contract, "case": case, "fmt": fmt, "policy": policy,
            "binding_id": BINDING, "sample_id": f"warm-simx-{fmt}-pair0-{policy}",
            "process_id": f"preflight-simx-{fmt}-{policy}",
            "expected_libraries": EXPECTED_LIBRARIES,
        }
        kwargs.update(changes)
        return records.verify_output(render_log(operations, summary, witness)
                                     if text is ... else text, **kwargs)

    def reject(self, change, *, raw=None, fmt="fp16", policy="per_operation"):
        raw = self.raw(fmt, policy) if raw is None else deepcopy(raw)
        change(*raw)
        with self.assertRaises(ValueError):
            self.verify(raw, fmt=fmt, policy=policy)

    @staticmethod
    def at(raw, path):
        value = raw
        for part in path:
            value = value[part]
        return value

    def reject_value(self, path, value):
        raw = self.raw()
        self.at(raw, path[:-1])[path[-1]] = value
        with self.assertRaises(ValueError):
            self.verify(raw)

    @staticmethod
    def set_counter(raw, ordinal, name, value):
        summary, witness = raw[2:]
        snapshot = witness["snapshots"][ordinal]
        rows = summary["snapshots"][snapshot["name"]]["counters"]
        enabled = [row for row in rows if row["enabled"]]
        index = next(index for index, row in enumerate(enabled) if row["name"] == name)
        enabled[index]["value"] = value
        for half in (0, 1):
            witness["reads"][ordinal * 66 + index * 2 + half]["value"] = (value >> (half * 32)) & 0xFFFFFFFF
        if name in ("cycles", "instructions"):
            for side in ("before", "after"):
                snapshot[side]["core_" + name] = value
            if ordinal == 0:
                witness["observation"]["constructed_state"] = deepcopy(snapshot["before"])
            if ordinal == 3:
                witness["observation"]["destruction"]["before"] = deepcopy(snapshot["after"])

    def test_four_cells_preserve_the_complete_unchanged_warm_result(self):
        totals = {name: 0 for name in ("launches", "checked_words", "snapshots", "half_replies")}
        for (fmt, policy), raw in self.examples.items():
            with self.subTest(fmt=fmt, policy=policy):
                case, operations, summary, witness = raw
                result = self.verify(raw, fmt=fmt, policy=policy)
                prefix = warm_fixture.render_log(operations, summary)
                original = warm_records.verify_output(prefix, case=case, fmt=fmt, policy=policy,
                    binding_id=BINDING, sample_id=f"warm-simx-{fmt}-pair0-{policy}",
                    pair_index=0, phase="warmup", contract=self.warm_contract)
                self.assertEqual(result["warm"], original)
                self.assertEqual(result["witness"], witness)
                self.assertEqual(result["warm"]["raw_log_sha256"], hashlib.sha256(prefix.encode()).hexdigest())
                self.assertEqual(operations, warm_fixture.raw_records(fmt, policy,
                    pair_index=0, contract=self.warm_contract)[1])
                self.assertIn("Synthetic host-test records; no native execution", prefix)
                self.assertEqual(sorted(row["sequence"] for row in
                                        witness["reads"] + witness["cache_flush_reads"]), list(range(1, 298)))
                self.assertEqual([(row["read_begin"], row["read_end"]) for row in witness["snapshots"]],
                                 [(0, 66), (66, 132), (132, 198), (198, 264)])
                for name in manifest.FALSE_CLAIMS:
                    self.assertIs(witness[name], False)
                totals["launches"] += result["warm"]["accounting"]["launches"]
                totals["checked_words"] += result["warm"]["accounting"]["checked_words"]
                totals["snapshots"] += len(witness["snapshots"])
                totals["half_replies"] += len(witness["reads"])
        self.assertEqual(totals, {"launches": 132, "checked_words": 4224,
                                 "snapshots": 16, "half_replies": 1056})

    def test_all_45_rows_have_the_exact_33_enabled_and_12_unqueried_inventory(self):
        for (fmt, policy), raw in self.examples.items():
            for ordinal, snapshot in enumerate(raw[3]["snapshots"]):
                with self.subTest(fmt=fmt, policy=policy, snapshot=snapshot["name"]):
                    rows = raw[2]["snapshots"][snapshot["name"]]["counters"]
                    self.assertEqual(len(rows), 45)
                    enabled = [row for row in rows if row["enabled"]]
                    unavailable = [row for row in rows if not row["enabled"]]
                    self.assertEqual((len(enabled), len(unavailable)), (33, 12))
                    for row in unavailable:
                        self.assertIsNone(row["status"])
                        self.assertIsNone(row["value"])
                    for index, row in enumerate(enabled):
                        low, high = raw[3]["reads"][ordinal * 66 + 2 * index:ordinal * 66 + 2 * index + 2]
                        self.assertEqual(low["value"] | (high["value"] << 32), row["value"])
                        self.assertEqual(low["tag"], (row["mpm_class"] << 22)
                                         | ((row["csr"] - 0xB00) << 16) | row["core_id"])
                        self.assertEqual(high["tag"], low["tag"] | (32 << 16))
                        self.assertEqual((low["addr"], high["addr"]), (1, 1))
                        self.assertEqual(row["value"] == 0, ordinal == 0)
                        if ordinal:
                            self.assertGreater(high["value"], 0)

    def test_helper_is_deterministic_and_carries_custom_binding_and_timings(self):
        self.assertEqual(synthetic_log(contract=self.contract), render_log(*self.raw()[1:]))
        durations = [17] + list(range(1, 33))
        raw = raw_records("bf16", "reusable_single_tile", binding_id="a" * 64,
                          durations_ns=durations, counter_deltas={"cycles": 321}, contract=self.contract)
        result = self.verify(raw, fmt="bf16", policy="reusable_single_tile", binding_id="a" * 64)
        self.assertEqual(result["warm"]["operation_durations_ns"], durations)
        self.assertEqual(next(row["value"] for row in result["warm"]["counter_deltas"]
                              if row["name"] == "cycles"), 321)

    def test_helper_rejects_ambiguous_or_unbounded_inputs(self):
        for changes in ({"fmt": "tf32"}, {"policy": "pool"}, {"binding_id": "A" * 64},
                        {"durations_ns": True}, {"durations_ns": [1] * 32},
                        {"counter_deltas": {"cycles": True}}, {"counter_deltas": {"other": 1}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                raw_records(contract=self.contract, **changes)

    def test_each_of_the_264_raw_half_values_is_checked(self):
        for index in range(264):
            with self.subTest(half=index):
                self.reject(lambda c, o, s, w, index=index:
                    w["reads"][index].__setitem__("value", w["reads"][index]["value"] ^ 1))

    def test_routes_sequence_and_half_order_are_not_reconstructed_from_counts(self):
        for index in (0, 1, 64, 65, 66, 67, 130, 131, 132, 197, 198, 262, 263):
            for key, mask in (("tag", 1), ("sequence", 1), ("addr", 1)):
                with self.subTest(half=index, field=key):
                    self.reject(lambda c, o, s, w, index=index, key=key, mask=mask:
                        w["reads"][index].__setitem__(key, w["reads"][index][key] ^ mask))
        for first, second in ((0, 1), (0, 2), (65, 66), (66, 198)):
            def swap(case, operations, summary, witness, first=first, second=second):
                witness["reads"][first], witness["reads"][second] = witness["reads"][second], witness["reads"][first]
            with self.subTest(swap=(first, second)):
                self.reject(swap)

    def test_class_csr_and_core_tag_bits_are_independently_bound(self):
        for mask in (1, 1 << 16, 1 << 21, 1 << 22, 1 << 31):
            with self.subTest(mask=mask):
                self.reject(lambda c, o, s, w, mask=mask:
                    w["reads"][72].__setitem__("tag", w["reads"][72]["tag"] ^ mask))

    def test_missing_extra_duplicate_or_null_raw_reads_fail(self):
        for value in ([], None, {}, self.raw()[3]["reads"][:-1], self.raw()[3]["reads"] + [self.raw()[3]["reads"][-1]]):
            with self.subTest(kind=type(value).__name__, count=len(value) if value is not None else None):
                self.reject_value((3, "reads"), value)
        self.reject(lambda c, o, s, w: w["reads"].__setitem__(131, deepcopy(w["reads"][130])))
        self.reject_value((3, "reads", 0), None)

    def test_half_status_completion_idle_and_overflow_cannot_be_asserted_away(self):
        for key, value in (("status", 1), ("status", False), ("completed", False),
                           ("completed", 1), ("overflow", True), ("overflow", 0),
                           ("idle_before", False), ("idle_after", False),
                           ("any_running_before", True), ("any_running_after", True)):
            with self.subTest(field=key, value=value):
                self.reject_value((3, "reads", 119, key), value)

    def test_each_half_uses_one_generation_reset_tick_and_restored_class(self):
        for key in ("generation", "ticks_before", "ticks_after", "reset_before", "reset_after",
                    "class_before", "class_after"):
            with self.subTest(field=key):
                original = self.raw()[3]["reads"][100][key]
                self.reject_value((3, "reads", 100, key), original + 1)
        def foreign_pair(case, operations, summary, witness):
            for row in witness["reads"][100:102]:
                row["class_before"] = row["class_after"] = 7
        self.reject(foreign_pair)
        def detached_clock(case, operations, summary, witness):
            for row in witness["reads"][66:132]:
                row["ticks_before"] += 1
                row["ticks_after"] += 1
        self.reject(detached_clock)

    def test_coherent_nonzero_saved_class_is_permitted_and_not_confused_with_tag_class(self):
        raw = self.raw()
        for row in raw[3]["reads"][66:132]:
            row["class_before"] = row["class_after"] = 7
        self.verify(raw)

    def test_snapshot_names_order_lengths_and_half_spans_are_exact(self):
        for value in ([], None, self.raw()[3]["snapshots"][:-1], self.raw()[3]["snapshots"] * 2):
            with self.subTest(kind=type(value).__name__):
                self.reject_value((3, "snapshots"), value)
        for index in range(4):
            for key in ("read_begin", "read_end"):
                with self.subTest(snapshot=index, field=key):
                    value = self.raw()[3]["snapshots"][index][key]
                    self.reject_value((3, "snapshots", index, key), value + 1)
        self.reject_value((3, "snapshots", 1, "name"), "after_batch")
        self.reject(lambda c, o, s, w: w["snapshots"].reverse())

    def test_model_state_must_remain_quiescent_and_unchanged_within_each_snapshot(self):
        for key, value in (("live", False), ("idle", False), ("any_running", True),
                           ("generation", 2), ("ticks", 1), ("reset_generation", 9),
                           ("core_cycles", 1), ("core_instructions", 1), ("exitcode", 1)):
            with self.subTest(field=key):
                self.reject_value((3, "snapshots", 1, "after", key), value)

    def test_monotonic_reset_generations_do_not_require_monotonic_platform_ticks(self):
        raw = self.raw()
        self.assertLess(raw[3]["snapshots"][2]["before"]["ticks"], raw[3]["snapshots"][1]["before"]["ticks"])
        self.verify(raw)
        def backwards_reset(case, operations, summary, witness):
            for side in ("before", "after"):
                witness["snapshots"][2][side]["reset_generation"] = 1
            for row in witness["reads"][132:198]:
                row["reset_before"] = row["reset_after"] = 1
        self.reject(backwards_reset)

    def test_actual_core_counters_are_bound_to_public_aggregates(self):
        for field in ("core_cycles", "core_instructions"):
            def mutate(case, operations, summary, witness, field=field):
                for side in ("before", "after"):
                    witness["snapshots"][1][side][field] += 1
            with self.subTest(field=field):
                self.reject(mutate)

    def test_every_opening_aggregate_must_be_zero_even_with_consistent_raw_halves(self):
        enabled = [row["name"] for row in self.raw()[2]["snapshots"]["after_open"]["counters"] if row["enabled"]]
        for name in enabled:
            raw = self.raw()
            self.set_counter(raw, 0, name, 1)
            with self.subTest(counter=name), self.assertRaises(ValueError):
                self.verify(raw)

    def test_uint64_counter_maximum_keeps_both_complete_uint32_halves(self):
        raw = self.raw()
        self.set_counter(raw, 1, "cycles", (1 << 64) - 33)
        for ordinal in (2, 3):
            self.set_counter(raw, ordinal, "cycles", (1 << 64) - 1)
        result = self.verify(raw)
        self.assertEqual([row["value"] for row in result["witness"]["reads"][132:134]], [0xFFFFFFFF, 0xFFFFFFFF])

    def test_no_counter_descriptor_can_be_removed_from_any_snapshot(self):
        for index in range(45):
            with self.subTest(descriptor=index):
                self.reject(lambda c, o, s, w, index=index:
                    s["snapshots"]["after_prime"]["counters"].pop(index))
        self.reject(lambda c, o, s, w: s["snapshots"]["after_batch"]["counters"].reverse())
        self.reject(lambda c, o, s, w: s["snapshots"]["before_release"]["counters"].__setitem__(
            1, deepcopy(s["snapshots"]["before_release"]["counters"][0])))

    def test_unavailable_rows_cannot_claim_a_query_status_value_or_enabled_route(self):
        rows = self.raw()[2]["snapshots"]["after_prime"]["counters"]
        unavailable = [index for index, row in enumerate(rows) if not row["enabled"]]
        self.assertEqual(len(unavailable), 12)
        for index in unavailable:
            for key, value in (("status", 0), ("value", 0), ("enabled", True)):
                with self.subTest(descriptor=index, field=key):
                    self.reject_value((2, "snapshots", "after_prime", "counters", index, key), value)
        missing = rows[unavailable[0]]
        route = (missing["mpm_class"] << 22) | ((missing["csr"] - 0xB00) << 16) | missing["core_id"]
        self.reject_value((3, "reads", 66, "tag"), route)

    def test_public_counter_descriptor_status_null_and_value_remain_independently_validated(self):
        for key, value in (("name", "other"), ("mpm_class", 7), ("csr", 0xB01),
                           ("core_id", 1), ("enabled", 1), ("status", False),
                           ("status", 1), ("value", None), ("value", True)):
            with self.subTest(field=key, value=value):
                self.reject_value((2, "snapshots", "after_prime", "counters", 0, key), value)
        self.reject_value((2, "snapshots", "after_prime", "counters"), None)

    def test_constructor_run_reader_and_destructor_actual_counts_are_required(self):
        for key in ("constructed", "destroyed", "constructor_entries", "destructor_entries",
                    "run_entries", "run_completed", "dcr_read_entries", "dcr_read_completed",
                    "read_count", "generation"):
            with self.subTest(field=key):
                value = self.raw()[3]["observation"][key]
                self.reject_value((3, "observation", key), value - 1)
        self.reject_value((3, "observation", "live"), True)

    def test_every_guard_error_or_unfinished_dcr_write_invalidates_observation(self):
        for key in ("run_errors", "dcr_read_errors", "dcr_write_errors", "overflow_errors",
                    "underflow_errors", "negative_operand_errors", "unexpected_errors", "violations"):
            with self.subTest(field=key):
                self.reject_value((3, "observation", key), 1)
        self.reject_value((3, "observation", "dcr_write_completed"), 171)
        raw = self.raw()
        raw[3]["observation"]["dcr_write_entries"] = raw[3]["observation"]["dcr_write_completed"] = 173
        self.verify(raw)

    def test_complete_destruction_is_observed_beyond_successful_device_release(self):
        for key, value in (("completed", False), ("idle_after", False), ("ticks_after", 1), ("reset_after", 35)):
            with self.subTest(field=key):
                self.reject_value((3, "observation", "destruction", key), value)
        self.reject_value((3, "observation", "destruction", "before", "ticks"), 1)
        self.reject_value((3, "observation", "constructed_state", "ticks"), 1)
        raw = self.raw()
        self.assertEqual(raw[2]["device_release"]["status"], 0)
        self.assertGreater(raw[3]["observation"]["destruction"]["before"]["ticks"], 0)
        self.assertEqual(raw[3]["observation"]["destruction"]["ticks_after"], 0)
        self.verify(raw)

    def test_terminal_cp_requires_one_reference_no_queue_and_no_buffer(self):
        for key, value in (("device_refs", 0), ("device_refs", 2), ("queues", 1), ("buffers", 1)):
            with self.subTest(field=key, value=value):
                self.reject_value((3, "snapshots", 3, key), value)
        self.reject_value((3, "snapshots", 0, "device_refs"), 0)
        self.reject_value((3, "snapshots", 1, "queues"), 1)

    def test_terminal_cp_requires_enabled_idle_clean_exact_retirement(self):
        for side in ("cp_before", "cp_after"):
            for key, value in (("control", 0), ("queue_control", 0), ("status", 1), ("error", 1),
                               ("retired", 0), ("expected", 0), ("runtime_tail", 0),
                               ("tail_register_pair_raw", 0)):
                with self.subTest(side=side, field=key):
                    self.reject_value((3, "snapshots", 3, side, key), value)

    def test_unsupported_cp_head_writeback_cannot_be_replaced_by_tail_or_claimed_supported(self):
        for side in ("cp_before", "cp_after"):
            for key, value in (("head_writeback_raw", 65536), ("head_writeback_status", "supported"),
                               ("drain_basis", "head-equals-tail")):
                with self.subTest(side=side, field=key):
                    self.reject_value((3, "snapshots", 3, side, key), value)

    def test_exactly_66_terminal_commands_must_retire_even_if_cp_rows_are_self_consistent(self):
        for difference in (0, 65, 67):
            def mutate(case, operations, summary, witness, difference=difference):
                before, after = (witness["snapshots"][3][key] for key in ("cp_before", "cp_after"))
                after["expected"] = after["retired"] = before["expected"] + difference
                after["runtime_tail"] = after["tail_register_pair_raw"] = after["expected"] * 64
            with self.subTest(difference=difference):
                self.reject(mutate)

    def test_cp_is_absent_before_terminal_release_and_required_at_terminal_release(self):
        for ordinal in range(3):
            for side in ("cp_before", "cp_after"):
                with self.subTest(snapshot=ordinal, side=side):
                    self.reject_value((3, "snapshots", ordinal, side), self.raw()[3]["snapshots"][3][side])
        for side in ("cp_before", "cp_after"):
            with self.subTest(side=side):
                self.reject_value((3, "snapshots", 3, side), None)

    def test_cp_uint32_retirement_maximum_is_valid_without_counter_wrap(self):
        raw = self.raw()
        for side, expected in (("cp_before", (1 << 32) - 67), ("cp_after", (1 << 32) - 1)):
            row = raw[3]["snapshots"][3][side]
            row["expected"] = row["retired"] = expected
            row["runtime_tail"] = row["tail_register_pair_raw"] = expected * 64
        self.verify(raw)
        raw[3]["snapshots"][3]["cp_after"]["expected"] = 1 << 32
        with self.assertRaises(ValueError):
            self.verify(raw)

    def test_loaded_library_inventory_is_exact_unique_ordered_and_bound(self):
        rows = self.raw()[3]["loaded_libraries"]
        self.assertEqual([row["name"] for row in rows], ["libramulator-vortex.so", "libramulator.so",
                         "libsimx.so", "libvortex-simx.so", "libvortex.so"])
        for index in range(5):
            with self.subTest(missing=index):
                self.reject(lambda c, o, s, w, index=index: w["loaded_libraries"].pop(index))
            with self.subTest(foreign=index):
                self.reject_value((3, "loaded_libraries", index, "path"), "/foreign/" + rows[index]["name"])
        self.reject_value((3, "loaded_libraries"), rows + [deepcopy(rows[0])])
        self.reject_value((3, "loaded_libraries"), list(reversed(rows)))
        self.reject_value((3, "loaded_libraries", 1), deepcopy(rows[0]))
        self.reject_value((3, "loaded_libraries"), None)

    def test_loader_paths_are_canonical_inert_data_and_never_opened(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            if str(path).startswith("/producer/"):
                self.fail("recorded library path was opened")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            self.verify()
        for path in ("relative/libsimx.so", "/producer/../libsimx.so", "/producer//libsimx.so",
                     "/producer/libsimx.so/", "/producer/libvortex.so", "/producer/with space/libsimx.so",
                     "/producer/\nlibsimx.so", "/producer/é/libsimx.so"):
            with self.subTest(path=path):
                self.reject_value((3, "loaded_libraries", 2, "path"), path)

    def test_independent_expected_library_mapping_is_not_optional_or_self_attested(self):
        for expected in (None, {}, list(EXPECTED_LIBRARIES), dict(EXPECTED_LIBRARIES, extra="/extra"),
                         dict(EXPECTED_LIBRARIES, **{"libsimx.so": "/independent/libsimx.so"})):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.verify(expected_libraries=expected)

    def test_witness_and_inner_binding_identity_cannot_be_relabelled(self):
        for key, value in (("schema_version", True), ("contract_id", "p06-warm-workspace-v1"),
                           ("process_id", "preflight-simx-bf16-per_operation"),
                           ("sample_id", "warm-simx-fp16-pair1-per_operation"),
                           ("execution_binding_sha256", "a" * 64), ("format", "bf16"),
                           ("policy", "reusable_single_tile"), ("backend", "rtlsim"),
                           ("xlen", 32), ("checked_counter_bits", 32), ("simulation_workers", 2)):
            with self.subTest(field=key):
                self.reject_value((3, key), value)
        self.reject_value((1, 12, "qualification_id"), "a" * 64)
        self.reject_value((2, "qualification_id"), "a" * 64)

    def test_external_identity_or_contract_cannot_admit_another_process(self):
        for changes in ({"binding_id": "A" * 64}, {"binding_id": "a" * 63},
                        {"binding_id": "a" * 64}, {"sample_id": "warm-simx-fp16-pair1-per_operation"},
                        {"process_id": "preflight-simx-bf16-per_operation"}, {"contract": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.verify(**changes)
        changed = deepcopy(self.contract)
        changed["per_process"]["half_replies"] = 262
        with self.assertRaises(ValueError):
            self.verify(contract=changed)

    def test_seeded_or_qualified_or_acceptance_claims_are_never_promoted(self):
        for field in ("seeded", *manifest.FALSE_CLAIMS):
            for value in (True, 0, "false", None):
                with self.subTest(field=field, value=value):
                    self.reject_value((3, field), value)
        for value in ([], list(reversed(manifest.UNRESOLVED_OBLIGATIONS)),
                      list(manifest.UNRESOLVED_OBLIGATIONS)[:-1], list(manifest.UNRESOLVED_OBLIGATIONS) + ["resolved"]):
            with self.subTest(obligations=value):
                self.reject_value((3, "unresolved_obligations"), value)

    def test_favorable_and_unfavorable_timings_do_not_rescue_invalid_evidence(self):
        for duration in (1, 1000000000):
            for policy in ("per_operation", "reusable_single_tile"):
                raw = raw_records(policy=policy, durations_ns=duration, contract=self.contract)
                with self.subTest(duration=duration, policy=policy):
                    result = self.verify(raw, policy=policy)
                    self.assertEqual(result["warm"]["timed_operation_durations_ns"], [duration] * 32)
                    self.assertIs(result["witness"]["performance_acceptance"], False)
                    self.reject(lambda c, o, s, w: w["reads"][263].__setitem__("value", 0), raw=raw, policy=policy)
                    self.reject(lambda c, o, s, w: w.__setitem__("qualified", True), raw=raw, policy=policy)

    def test_numerical_outputs_poison_and_complete_population_stay_mandatory(self):
        for index in (0, 16, 32):
            with self.subTest(operation=index):
                self.reject(lambda c, o, s, w, index=index:
                    o[index]["actual_bits"].__setitem__(0, "00000000"))
        self.reject(lambda c, o, s, w: o.pop())
        self.reject_value((1, 1, "poison"), 0xDEADBEEF)
        self.reject_value((2, "checked"), 1024)
        raw = self.raw()
        raw[0]["expected"][0] = "00000000"
        for operation in raw[1]:
            operation["actual_bits"][0] = "00000000"
        with self.assertRaises(ValueError):
            self.verify(raw)

    def test_every_witness_field_is_required_and_unknown_fields_fail(self):
        for field in manifest.WITNESS_FIELDS:
            with self.subTest(missing=field):
                self.reject(lambda c, o, s, w, field=field: w.pop(field))
        self.reject(lambda c, o, s, w: w.__setitem__("native_qualified", True))

    def test_nested_record_field_inventories_are_exact(self):
        paths = ((3, "observation"), (3, "observation", "constructed_state"),
                 (3, "observation", "destruction"), (3, "observation", "destruction", "before"),
                 (3, "snapshots", 1), (3, "snapshots", 1, "before"),
                 (3, "snapshots", 3, "cp_after"), (3, "reads", 131), (3, "loaded_libraries", 2))
        for path in paths:
            for extra in (False, True):
                raw = self.raw()
                target = self.at(raw, path)
                if extra:
                    target["unknown"] = 0
                else:
                    target.pop(next(iter(target)))
                with self.subTest(path=path, extra=extra), self.assertRaises(ValueError):
                    self.verify(raw)

    def test_booleans_cannot_stand_in_for_observation_counts(self):
        for field in manifest.OBSERVATION_COUNTER_FIELDS:
            with self.subTest(field=field):
                self.reject_value((3, "observation", field), True)

    def test_numeric_native_widths_nulls_and_negative_values_are_enforced(self):
        paths = (
            ((3, "reads", 67, "value"), 32), ((3, "reads", 67, "tag"), 32),
            ((3, "reads", 67, "addr"), 32), ((3, "reads", 67, "class_before"), 32),
            ((3, "reads", 67, "sequence"), 64), ((3, "reads", 67, "ticks_before"), 64),
            ((3, "observation", "dcr_write_entries"), 64),
            ((3, "snapshots", 1, "read_begin"), 64), ((3, "snapshots", 1, "buffers"), 64),
            ((3, "snapshots", 1, "before", "core_cycles"), 64),
            ((3, "snapshots", 3, "cp_after", "expected"), 32),
            ((3, "snapshots", 3, "cp_after", "runtime_tail"), 64),
        )
        for path, bits in paths:
            for value in (True, None, -1, 1 << bits):
                with self.subTest(path=path, value=value):
                    self.reject_value(path, value)
        for value in (True, None, -(1 << 31) - 1, 1 << 31):
            with self.subTest(exitcode=value):
                self.reject_value((3, "snapshots", 1, "before", "exitcode"), value)

    def test_witness_must_be_one_last_line_immediately_after_original_success(self):
        raw = self.raw()
        warm = warm_fixture.render_log(raw[1], raw[2])
        full = render_log(*raw[1:])
        trailer = full[len(warm):]
        invalid = {
            "missing": warm, "duplicate": full + trailer, "before_warm": trailer + warm,
            "between_summary_and_success": warm[:-len("PASSED!\n")] + trailer + "PASSED!\n",
            "diagnostic_gap": warm + "diagnostic\n" + trailer,
            "blank_gap": warm + "\n" + trailer, "no_final_newline": full[:-1],
            "trailing_blank": full + "\n", "trailing_diagnostic": full + "diagnostic\n",
            "trailing_success": full + "PASSED!\n", "trailing_record": full + "P06_OTHER {}\n",
            "prefix_whitespace": warm + " " + trailer, "prefix_separator": warm + trailer.replace("WITNESS ", "WITNESS\t", 1),
            "unknown_marker": warm + trailer.replace("WITNESS ", "OTHER ", 1),
            "crlf": full.replace("\n", "\r\n"), "nul": full.replace("\n", "\x00\n", 1),
        }
        for name, text in invalid.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.verify(raw, text=text)

    def test_earlier_failures_unknown_markers_or_second_success_are_not_sanitized(self):
        full = render_log(*self.raw()[1:])
        for diagnostic in ("FAILED", "ERROR: query incomplete", "runtime error: overflow",
                           "Segmentation fault", "PASSED!", "P06_UNKNOWN {}", "P06_MANAGED_COUNTER_WITNESSoops"):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                self.verify(text=diagnostic + "\n" + full)
        self.verify(text="ordinary diagnostic\n" + full)

    def test_duplicate_json_fields_are_rejected_at_every_relevant_depth(self):
        full = render_log(*self.raw()[1:])
        warm, body = full.rsplit(manifest.WITNESS_PREFIX, 1)
        for original, replacement in (
            ('"schema_version":1', '"schema_version":1,"schema_version":1'),
            ('"run_entries":33', '"run_entries":33,"run_entries":33'),
            ('"sequence":1,', '"sequence":1,"sequence":1,'),
            ('"control":1', '"control":1,"control":1'),
            ('"name":"libsimx.so"', '"name":"libsimx.so","name":"libsimx.so"'),
        ):
            self.assertIn(original, body)
            with self.subTest(field=original), self.assertRaises(ValueError):
                self.verify(text=warm + manifest.WITNESS_PREFIX + body.replace(original, replacement, 1))

    def test_malformed_truncated_float_nonfinite_and_multiple_json_values_fail(self):
        raw = self.raw()
        warm = warm_fixture.render_log(raw[1], raw[2])
        body = json.dumps(raw[3], separators=(",", ":"))
        invalid = ("", "null", "[]", "true", "{} {}", body[:-1], body + "{}", body + " trailing",
                   body.replace('"schema_version":1', '"schema_version":1.0', 1),
                   body.replace('"schema_version":1', '"schema_version":NaN', 1),
                   body.replace('"schema_version":1', '"schema_version":Infinity', 1),
                   body.replace('"schema_version":1', '"schema_version":1e0', 1),
                   body.replace('"schema_version":1', '"schema_version":18446744073709551616', 1),
                   body.replace('"schema_version":1', '"schema_version":9999999999999999999999999', 1),
                   '{"unexpected":' + "[" * 17 + "0" + "]" * 17 + "}",
                   body.replace('"simx"', '"\\ud800"', 1))
        for index, changed in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.verify(raw, text=warm + manifest.WITNESS_PREFIX + changed + "\n")

    def test_nontext_nonunicode_and_bounded_output_reject_before_validation(self):
        for text in (None, b"PASSED!\n", [], "\ud800", ""):
            with self.subTest(kind=type(text).__name__), self.assertRaises(ValueError):
                self.verify(text=text)
        full = render_log(*self.raw()[1:])
        with patch.object(manifest, "MAX_OUTPUT_BYTES", len(full.encode()) - 1), self.assertRaises(ValueError):
            self.verify(text=full)
        warm, body = full.rsplit(manifest.WITNESS_PREFIX, 1)
        with patch.object(manifest, "MAX_RECORD_BYTES", len(body.encode()) - 2), self.assertRaises(ValueError):
            self.verify(text=full)


if __name__ == "__main__":
    unittest.main()
